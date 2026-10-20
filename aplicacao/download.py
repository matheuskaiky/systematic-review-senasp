import logging
import time
from dominio.servicos import hash_chave
from aplicacao.comum import item_gravado, registrar_falha_apos_chamada
from aplicacao.planejamento import planejar_download


def executar(repo, bruto, fetcher, extrator, run_id, run_origem, politica, segredos, pausa,
             limite=None, ufs=None, auditoria=0, semente="", max_falhas_por_pagina=None,
             so_sem_pagina=False, so_falha=None, urls=None):
    """`max_falhas_por_pagina`: depois de N chamadas com falha para a mesma pagina nesta execucao, a pagina e abandonada
    (nao e baixada de novo a cada --retomar); o total de desistencias vai para a metrica `download_desistencias`.
    Sucessos nunca sao limitados.

    `run_origem`: uma ou mais execucoes de busca (texto ou lista). `so_sem_pagina`, `so_falha` e `urls` sao os filtros de
    resgate (ver `aplicacao.planejamento.planejar_download`), aplicados antes da selecao."""
    # auditoria do pre-filtro: amostra reprodutivel dos descartados por palavra-chave tambem e baixada e classificada
    cands, decisao, amostra = planejar_download(repo, run_origem, politica, ufs, auditoria, semente, so_sem_pagina,
                                                so_falha, urls, excluir_run=run_id)
    repo.salvar_selecao(run_id, [(c.url_id, c.uf, int(ok), motivo, int((c.url_id, c.uf) in amostra))
                                 for c, ok, motivo in decisao])
    repo.registrar_metrica(run_id, "download_auditoria_amostra", len(amostra))
    repo.registrar_metrica(run_id, "download_candidatos", len(cands))
    repo.registrar_metrica(run_id, "download_selecionados", sum(1 for _, ok, _ in decisao if ok))
    repo.confirmar()
    logging.info("Candidates: %d | selected: %d", len(cands), sum(1 for _, ok, _ in decisao if ok))

    desistencias = 0
    chamadas = repo.chaves_com_chamada(run_id, "download")    # o --limite vale para a execucao inteira, retomadas incluidas
    for url_id, url in repo.urls_selecionadas(run_id):
        chave = hash_chave("download", fetcher.nome, url_id)
        if repo.ja_feito(run_id, chave):
            continue
        if limite and chave not in chamadas and len(chamadas) >= limite:
            break
        if max_falhas_por_pagina and repo.contar_falhas(run_id, chave) >= max_falhas_por_pagina:
            desistencias += 1
            logging.warning("[download %d] abandonada depois de %d falhas nesta execucao: %s", url_id, max_falhas_por_pagina, url)
            repo.registrar_metrica(run_id, "download_desistencias", desistencias)       # ja gravada se a execucao for interrompida
            continue
        arq = fetcher.baixar(url)
        chamadas.add(chave)
        # O trabalho lento (extracao de PDFs grandes leva dezenas de segundos) acontece ANTES de qualquer gravacao: assim a
        # chamada e a pagina entram juntas numa transacao curta e o banco nao fica bloqueado para o painel e para as outras
        # etapas (16/10/2026: uma extracao longa segurava o banco e outro processo morria com "database is locked").
        texto = texto_path = None
        try:
            if arq.chamada.sucesso:
                texto = extrator.extrair(arq.conteudo, arq.content_type, arq.url_final)
                if texto.ok:
                    texto_path, _ = bruto.salvar("texto", run_id, chave, texto.texto.encode("utf-8"), "txt")
        except BaseException as e:
            registrar_falha_apos_chamada(repo, bruto, run_id, "download", "url", str(url_id), chave, arq.chamada, segredos,
                                         e, "falha_ao_extrair")
            raise
        with item_gravado(repo, bruto, run_id, "download", "url", str(url_id), chave, arq.chamada, segredos) as chamada_id:
            if arq.chamada.sucesso:
                repo.salvar_pagina(run_id, url_id, chamada_id, arq, texto, texto_path)
        logging.info("[download %d] ok=%s status=%s", url_id, arq.chamada.sucesso, arq.http_status)
        time.sleep(pausa)
    repo.registrar_metrica(run_id, "download_desistencias", desistencias)
    repo.confirmar()
