import logging
import time
from dataclasses import replace
from dominio.modelos import EntradaClassificacao, Instrucoes
from dominio.servicos import hash_chave, evidencia_confere, evidencia_cita_termo, evidencia_cita_lgpd
from dominio.solucoes import nome_solucao_no_texto
from aplicacao.comum import item_gravado
from aplicacao.planejamento import planejar_classificacao
from dominio.erros import CotaDiariaEsgotada

_CONFIANCAS = ("alta", "media", "baixa")


def executar(repo, bruto, classificador, run_id, run_origem, params, ufs_nomes, segredos, pausa,
             limite=None, ufs=None, max_falhas_por_item=None, so_nao_classificadas=False, urls=None):
    """`run_origem`: uma ou mais execucoes de download (texto ou lista). `so_nao_classificadas` e `urls` filtram os itens
    (ver `aplicacao.planejamento.planejar_classificacao`); quem decide qual classificacao vale e a leitura, nao esta funcao."""
    ignorados = desistencias = nomes_descartados = 0
    chamadas = repo.chaves_com_chamada(run_id, "classificacao")   # o --limite vale para a execucao inteira, retomadas incluidas
    for item in planejar_classificacao(repo, run_origem, ufs, urls, so_nao_classificadas, params.versao_prompt,
                                       classificador.nome, excluir_run=run_id):
        chave = hash_chave("classificacao", classificador.nome, params.versao_prompt, item.url_id, item.uf)
        if repo.ja_feito(run_id, chave):
            continue
        if limite and chave not in chamadas and len(chamadas) >= limite:
            break
        if max_falhas_por_item and repo.contar_falhas(run_id, chave) >= max_falhas_por_item:
            # falha que se repete (por exemplo, resposta truncada) nao deve ser paga de novo a cada retomada
            desistencias += 1
            logging.warning("[classify %s %s] %d falhas nesta execucao; item abandonado (veja chamadas.erro; se for "
                            "resposta truncada, aumente max_tokens_saida e rode como nova execucao)",
                            item.uf, item.url_id, max_falhas_por_item)
            repo.registrar_metrica(run_id, "classificacao_desistencias", desistencias)
            continue

        if item.texto_path:
            texto, origem = bruto.ler(item.texto_path).decode("utf-8"), "pagina"
        elif params.usar_snippet_se_falhar and (item.titulo or item.snippet):
            texto, origem = f"{item.titulo or ''}\n{item.snippet or ''}", "snippet"
        else:
            ignorados += 1                              # sem texto utilizavel: fica registrado na metrica e no log
            logging.warning("[classify %s %s] sem texto utilizavel; item ignorado", item.uf, item.url_id)
            repo.registrar_metrica(run_id, "classificacao_ignorados_sem_texto", ignorados)   # ja gravada se a execucao for interrompida
            continue

        truncado = len(texto) > params.max_chars
        texto_env = texto[:params.max_chars]
        entrada = EntradaClassificacao(item.uf, item.url, item.titulo or "", texto_env, origem, truncado)
        # Tudo o que o prompt entrega como conteudo da pagina: o texto, o titulo e a URL (um nome so no titulo ou na URL tambem esta na
        # entrada do modelo). O nome do estado-alvo, que o prompt tambem traz, nao conta.
        conteudo_enviado = f"{entrada.titulo}\n{entrada.url}\n{texto_env}"
        instr = Instrucoes(
            versao=params.versao_prompt, sistema=params.sistema, esquema=params.esquema,
            usuario=params.usuario_template.format(uf=item.uf, nome=ufs_nomes.get(item.uf, item.uf),
                                                   url=item.url, titulo=entrada.titulo,
                                                   origem=origem, texto=texto_env))
        res = classificador.classificar(entrada, instr)
        chamadas.add(chave)
        cota = res.chamada.extras.get("cota_diaria_esgotada")
        with item_gravado(repo, bruto, run_id, "classificacao", "item", f"{item.url_id}:{item.uf}", chave, res.chamada,
                          segredos, uf=item.uf) as chamada_id:
            if cota:
                # a cota diaria do provedor acabou: repetir hoje so gasta tempo e espalharia falhas por todos os itens.
                # Para aqui; o item nao conta como falha propria e a retomada (--retomar) refaz o que faltou.
                repo.registrar_metrica(run_id, "classificacao_parada_cota_diaria", 1)
            elif res.chamada.sucesso:
                validos, invalidos, descartados = [], 0, []
                for a in res.achados:
                    if a.tecnologia not in params.tecnologias or a.status not in params.status:
                        invalidos += 1                      # outside the vocabulary: discarded and counted
                        motivo = ("tecnologia_fora_do_vocabulario" if a.tecnologia not in params.tecnologias
                                  else "status_fora_do_vocabulario")
                        descartados.append((a, motivo))     # ...mas guardado para auditoria
                        continue
                    conf = a.confianca if a.confianca in _CONFIANCAS else "baixa"
                    if origem == "snippet":
                        conf = "baixa"                      # snippet only: never high confidence
                    palavras = params.palavras_tecnologia.get(a.tecnologia)
                    nome = a.nome_solucao or ""
                    if nome and not nome_solucao_no_texto(nome, conteudo_enviado):
                        # antialucinacao: o nome so vale se aparece no que o modelo recebeu. Fica vazio; a resposta bruta guarda o original
                        nomes_descartados += 1
                        logging.warning("[classify %s %s] nome_solucao %r descartado: não aparece no texto enviado ao modelo",
                                        item.uf, item.url_id, nome)
                        repo.registrar_metrica(run_id, "classificacao_nome_solucao_descartado", nomes_descartados)
                        nome = ""
                    validos.append(replace(a, confianca=conf, confianca_original=a.confianca, nome_solucao=nome,
                                           evidencia_confere=evidencia_confere(a.evidencia, texto_env),
                                           evidencia_cita_tecnologia=evidencia_cita_termo(a.evidencia, palavras) if palavras else None,
                                           evidencia_cita_lgpd=evidencia_cita_lgpd(a.evidencia)))
                cid = repo.salvar_classificacao(chamada_id, run_id, item, entrada, classificador.nome,
                                                params.versao_prompt, res, validos, invalidos)
                if descartados:
                    repo.salvar_achados_descartados(cid, descartados)
        if cota:
            raise CotaDiariaEsgotada(classificador.nome, "Retome com --retomar depois que a cota renovar.",
                                     res.chamada.extras.get("cota_renova_em_s"), res.chamada.extras.get("cota_motivo", "cota_diaria"))
        if res.chamada.erro and str(res.chamada.erro).startswith("resposta_truncada"):
            logging.warning("[classify %s %s] resposta truncada (o raciocinio conta no limite de saida): aumente "
                            "max_tokens_saida; repetir com a mesma configuracao repete o corte e o gasto", item.uf, item.url_id)
        logging.info("[classify %s %s] ok=%s origin=%s findings=%d", item.uf, item.url_id,
                     res.chamada.sucesso, origem, len(res.achados))
        time.sleep(pausa)
    repo.registrar_metrica(run_id, "classificacao_ignorados_sem_texto", ignorados)
    repo.registrar_metrica(run_id, "classificacao_desistencias", desistencias)
    repo.registrar_metrica(run_id, "classificacao_nome_solucao_descartado", nomes_descartados)
    repo.confirmar()
