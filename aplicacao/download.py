import logging
import time
from dominio.servicos import hash_chave, selecionar_candidatos
from aplicacao.comum import registrar_chamada


def executar(repo, bruto, fetcher, extrator, run_id, run_origem, politica, segredos, pausa,
             limite=None, ufs=None):
    cands = [c for c in repo.candidatos_download(run_origem) if not ufs or c.uf in ufs]
    decisao = selecionar_candidatos(cands, politica)
    repo.salvar_selecao(run_id, [(c.url_id, c.uf, int(ok), motivo) for c, ok, motivo in decisao])
    repo.registrar_metrica(run_id, "download_candidatos", len(cands))
    repo.registrar_metrica(run_id, "download_selecionados", sum(1 for _, ok, _ in decisao if ok))
    repo.confirmar()
    logging.info("Candidates: %d | selected: %d", len(cands), sum(1 for _, ok, _ in decisao if ok))

    feitos = 0
    for url_id, url in repo.urls_selecionadas(run_id):
        if limite and feitos >= limite:
            break
        chave = hash_chave("download", fetcher.nome, url_id)
        if repo.ja_feito(run_id, chave):
            continue
        arq = fetcher.baixar(url)
        chamada_id, _ = registrar_chamada(repo, bruto, run_id, "download", "url", str(url_id), chave,
                                          arq.chamada, segredos)
        if arq.chamada.sucesso:
            texto = extrator.extrair(arq.conteudo, arq.content_type, arq.url_final)
            texto_path = None
            if texto.ok:
                texto_path, _ = bruto.salvar("texto", run_id, chave, texto.texto.encode("utf-8"), "txt")
            repo.salvar_pagina(run_id, url_id, chamada_id, arq, texto, texto_path)
        repo.confirmar()
        feitos += 1
        logging.info("[download %d] ok=%s status=%s", url_id, arq.chamada.sucesso, arq.http_status)
        time.sleep(pausa)
