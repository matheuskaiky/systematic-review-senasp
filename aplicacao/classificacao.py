import logging
import time
from dataclasses import replace
from dominio.modelos import EntradaClassificacao, Instrucoes
from dominio.servicos import hash_chave, evidencia_confere, evidencia_cita_termo, evidencia_cita_lgpd
from aplicacao.comum import registrar_chamada
from dominio.erros import CotaDiariaEsgotada

_CONFIANCAS = ("alta", "media", "baixa")


def executar(repo, bruto, classificador, run_id, run_origem, params, ufs_nomes, segredos, pausa,
             limite=None, ufs=None, max_falhas_por_item=None):
    feitos = ignorados = desistencias = 0
    for item in repo.itens_para_classificar(run_origem):
        if ufs and item.uf not in ufs:
            continue
        if limite and feitos >= limite:
            break
        chave = hash_chave("classificacao", classificador.nome, params.versao_prompt, item.url_id, item.uf)
        if repo.ja_feito(run_id, chave):
            continue
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
        instr = Instrucoes(
            versao=params.versao_prompt, sistema=params.sistema, esquema=params.esquema,
            usuario=params.usuario_template.format(uf=item.uf, nome=ufs_nomes.get(item.uf, item.uf),
                                                   url=item.url, titulo=entrada.titulo,
                                                   origem=origem, texto=texto_env))
        res = classificador.classificar(entrada, instr)
        chamada_id, _ = registrar_chamada(repo, bruto, run_id, "classificacao", "item",
                                          f"{item.url_id}:{item.uf}", chave, res.chamada, segredos, uf=item.uf)
        if res.chamada.extras.get("cota_diaria_esgotada"):
            # a cota diaria do provedor acabou: repetir hoje so gasta tempo e espalharia falhas por todos os itens.
            # Para aqui; o item nao conta como falha propria e a retomada (--retomar) refaz o que faltou.
            repo.registrar_metrica(run_id, "classificacao_parada_cota_diaria", 1)
            repo.confirmar()
            raise CotaDiariaEsgotada(classificador.nome, "Retome com --retomar depois que a cota renovar.",
                                     res.chamada.extras.get("cota_renova_em_s"), res.chamada.extras.get("cota_motivo", "cota_diaria"))
        if res.chamada.sucesso:
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
                validos.append(replace(a, confianca=conf, confianca_original=a.confianca,
                                       evidencia_confere=evidencia_confere(a.evidencia, texto_env),
                                       evidencia_cita_tecnologia=evidencia_cita_termo(a.evidencia, palavras) if palavras else None,
                                       evidencia_cita_lgpd=evidencia_cita_lgpd(a.evidencia)))
            cid = repo.salvar_classificacao(chamada_id, run_id, item, entrada, classificador.nome,
                                            params.versao_prompt, res, validos, invalidos)
            if descartados:
                repo.salvar_achados_descartados(cid, descartados)
        if res.chamada.erro and str(res.chamada.erro).startswith("resposta_truncada"):
            logging.warning("[classify %s %s] resposta truncada (o raciocinio conta no limite de saida): aumente "
                            "max_tokens_saida; repetir com a mesma configuracao repete o corte e o gasto", item.uf, item.url_id)
        repo.confirmar()
        feitos += 1
        logging.info("[classify %s %s] ok=%s origin=%s findings=%d", item.uf, item.url_id,
                     res.chamada.sucesso, origem, len(res.achados))
        time.sleep(pausa)
    repo.registrar_metrica(run_id, "classificacao_ignorados_sem_texto", ignorados)
    repo.registrar_metrica(run_id, "classificacao_desistencias", desistencias)
    repo.confirmar()
