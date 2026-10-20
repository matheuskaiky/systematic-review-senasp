import logging
import time
from dominio.erros import CotaDiariaEsgotada
from dominio.modelos import Instrucoes
from dominio.servicos import hash_chave
from dominio.triagem_escopo import (chave_item, enriquecer_termos, escolher_amostra, fora_do_recorte_temporal, lotes,
                                    custo_lote_usd, montar_esquema, montar_mensagem_usuario, sistema_da_fonte,
                                    validar_resposta)
from aplicacao.comum import item_gravado, registrar_falha_apos_chamada

ETAPA = "triagem_escopo"


def selecionar(repo, fonte, mapas, config, amostra=None, estratificar=False, semente="", limite=None, refazer=False):
    """Itens a triar. Ordem das decisoes: (1) enriquece com os textos dos termos; (2) se houver `amostra`, escolhe a amostra
    de TODOS os itens (deterministica pela `semente`: repetir o comando repete a amostra e, por isso, nao gasta de novo);
    (3) corta em `limite` (sobre o conjunto escolhido, para que repetir ou retomar o comando nao amplie o gasto);
    (4) tira os ja triados com esta versao do prompt, salvo `refazer`.
    Devolve (itens, resumo) com `resumo` = {"total", "na_amostra", "ja_triados", "a_triar"}.
    Artigos com ano conhecido anterior a config.ano_minimo vao so para a triagem curta (config.curta) e saem da completa (D80); na curta, conta como ja triado o item respondido por qualquer versao do prompt."""
    if config.curta and fonte != "artigo":
        raise ValueError("A triagem curta vale só para artigos.")
    todos = enriquecer_termos(repo.itens_para_triagem_escopo(fonte), mapas)
    if config.curta:
        todos = [i for i in todos if fora_do_recorte_temporal(i, config)]
    elif fonte == "artigo":
        todos = [i for i in todos if not fora_do_recorte_temporal(i, config)]
    escolhidos = escolher_amostra(todos, amostra, estratificar, semente) if amostra else todos
    if limite:
        escolhidos = escolhidos[:limite]       # o limite vale para o conjunto, nao para o que falta: repetir nao amplia o gasto
    if refazer:
        feitos = set()
    elif config.curta:
        feitos = repo.triagem_escopo_respondida(fonte)          # o antigo ja triado por qualquer prompt nao gasta de novo
    else:
        feitos = repo.triagem_escopo_feita_por_versao(fonte, config.versao)
    pendentes = [i for i in escolhidos if (i["item_id"], i["uf"] or "") not in feitos]
    resumo = {"total": len(todos), "na_amostra": len(escolhidos), "ja_triados": len(escolhidos) - len(pendentes)}
    resumo["a_triar"] = len(pendentes)
    return pendentes, resumo


def executar(repo, bruto, triador, run_id, fonte, mapas, config, precos, segredos, pausa, lote=None, amostra=None,
             estratificar=False, semente="", limite=None, max_custo_usd=None, refazer=False, max_falhas_por_lote=3):
    """Triagem de escopo em lotes. Cada lote e uma chamada; o resultado vai para `triagem_escopo` (a opiniao do modelo, a
    parte da triagem humana e dos achados, que esta etapa nunca toca).

    - Idempotente: o lote ja concluido nesta execucao nao e chamado de novo (chave = ids do lote + versao do prompt +
      triador); itens ja triados com a mesma versao do prompt sao pulados, salvo `refazer`.
    - Teto de custo: ANTES de cada chamada, se o custo acumulado da execucao mais a estimativa (nivel alto) da chamada
      passar de `max_custo_usd`, a etapa para e grava o motivo em `metricas_run`. Exige `precos`.
    - Falha de um lote (HTTP, bloqueio, MAX_TOKENS, JSON invalido) nao aborta a execucao: os itens ficam sem triagem e
      podem ser repetidos; depois de `max_falhas_por_lote` falhas do mesmo lote nesta execucao ele e abandonado.
    Devolve um resumo com as contagens."""
    lote = lote or config.lote_padrao
    if max_custo_usd is not None and not precos:
        raise ValueError("max_custo_usd exige os precos por milhao de tokens (entrada e saida)")
    itens, resumo = selecionar(repo, fonte, mapas, config, amostra, estratificar, semente, limite, refazer)
    lista = lotes(itens, lote)
    acumulado = repo.custo_execucao(run_id)
    r = {**resumo, "lotes": len(lista), "chamadas": 0, "lotes_falhos": 0, "desistencias": 0, "itens_triados": 0,
         "itens_sem_resposta": 0, "parou_por_custo": False, "custo_usd": 0.0}
    logging.info("[triagem_escopo] fonte=%s itens=%d lotes=%d (lote=%d) prompt=%s", fonte, len(itens), len(lista), lote,
                 config.versao)
    for n, grupo in enumerate(lista, 1):
        chaves = [chave_item(i) for i in grupo]
        chave = hash_chave(ETAPA, triador.nome, config.versao, fonte, *chaves)
        if repo.ja_feito(run_id, chave):
            continue
        if repo.contar_falhas(run_id, chave) >= max_falhas_por_lote:
            r["desistencias"] += 1
            logging.warning("[triagem_escopo %d/%d] %d falhas deste lote nesta execucao; lote abandonado (veja "
                            "chamadas.erro; se for MAX_TOKENS, reduza --lote)", n, len(lista), max_falhas_por_lote)
            continue
        if max_custo_usd is not None:
            estimado = custo_lote_usd(grupo, precos, config, "alto")
            if acumulado + estimado > max_custo_usd:
                r["parou_por_custo"] = True
                logging.warning("[triagem_escopo %d/%d] parada antes da chamada: custo acumulado US$ %.4f + estimativa "
                                "(nivel alto) US$ %.4f passaria do teto de US$ %.4f (--max-custo)",
                                n, len(lista), acumulado, estimado, max_custo_usd)
                repo.registrar_metrica(run_id, "triagem_escopo_parou_por_custo", 1)
                repo.registrar_metrica(run_id, "triagem_escopo_custo_estimado_proxima_chamada_usd", estimado)
                repo.registrar_metrica(run_id, "triagem_escopo_teto_custo_usd", max_custo_usd)
                break
        instr = Instrucoes(versao=config.versao, sistema=sistema_da_fonte(fonte, config),
                           usuario=montar_mensagem_usuario(grupo, config), esquema=montar_esquema(config, chaves))
        res = triador.triar(grupo, instr)
        r["chamadas"] += 1
        linhas = None
        try:
            if res.chamada.erro is None:
                linhas, extras = validar_resposta(grupo, res.texto_resposta, config)
                if not extras["json_valido"]:
                    res.chamada.erro = "resposta_json_invalida: o texto do modelo nao e JSON no formato esperado"
                    linhas = None
        except BaseException as e:
            registrar_falha_apos_chamada(repo, bruto, run_id, ETAPA, "lote", f"{fonte}:{len(grupo)}:{chaves[0]}", chave,
                                         res.chamada, segredos, e, "falha_ao_validar")
            raise
        acumulado += res.chamada.custo_usd or 0.0
        cota = res.chamada.extras.get("cota_diaria_esgotada")
        with item_gravado(repo, bruto, run_id, ETAPA, "lote", f"{fonte}:{len(grupo)}:{chaves[0]}", chave, res.chamada,
                          segredos) as chamada_id:
            if cota:
                # a cota diaria do provedor acabou: repetir hoje so gasta tempo. A chamada ficou registrada (auditoria), os
                # itens deste lote seguem sem triagem (e podem ser repetidos) e os lotes anteriores ja estao gravados.
                repo.registrar_metrica(run_id, "triagem_escopo_parada_cota_diaria", 1)
                repo.registrar_metrica(run_id, "triagem_escopo_itens_triados", r["itens_triados"])
            elif linhas is None:
                r["lotes_falhos"] += 1
                motivo = str(res.chamada.erro)
                if motivo.startswith("resposta_truncada"):
                    logging.error("[triagem_escopo %d/%d] FALHA: resposta cortada por MAX_TOKENS; nenhum item do lote foi "
                                  "aproveitado (tokens e custo ficaram gravados). Reduza --lote.", n, len(lista))
                else:
                    logging.error("[triagem_escopo %d/%d] FALHA do lote (itens ficam sem triagem e podem ser repetidos): %s",
                                  n, len(lista), motivo)
            else:
                repo.salvar_triagem_escopo(run_id, chamada_id, config.versao, linhas)
                sem = len(extras["ids_ausentes"])
                r["itens_triados"] += len(linhas) - sem
                r["itens_sem_resposta"] += sem
                if sem or extras["ids_duplicados"] or extras["ids_desconhecidos"]:
                    logging.warning("[triagem_escopo %d/%d] ids ausentes=%s duplicados=%s desconhecidos=%s", n, len(lista),
                                    extras["ids_ausentes"], extras["ids_duplicados"], extras["ids_desconhecidos"])
                logging.info("[triagem_escopo %d/%d] ok itens=%d invalidos=%d", n, len(lista), len(linhas),
                             sum(1 for l in linhas if not l["valido"]))
        if cota:
            raise CotaDiariaEsgotada(triador.nome, "Os itens do lote afetado seguem sem triagem.",
                                     res.chamada.extras.get("cota_renova_em_s"), res.chamada.extras.get("cota_motivo", "cota_diaria"))
        time.sleep(pausa)
    r["custo_usd"] = acumulado
    for chave_m, valor in (("triagem_escopo_itens_triados", r["itens_triados"]),
                           ("triagem_escopo_itens_sem_resposta", r["itens_sem_resposta"]),
                           ("triagem_escopo_lotes_falhos", r["lotes_falhos"]),
                           ("triagem_escopo_desistencias", r["desistencias"]),
                           ("triagem_escopo_lote", lote)):
        repo.registrar_metrica(run_id, chave_m, valor)
    repo.confirmar()
    return r
