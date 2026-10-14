def registrar_chamada(repo, bruto, run_id, etapa, alvo_tipo, alvo_id, chave, reg, segredos,
                      uf=None, pagina=None):
    """Saves the raw payload (without secrets) and the row in `chamadas`. Returns (chamada_id, raw_path)."""
    raw_path = raw_sha = None
    if reg.raw is not None:
        dados = reg.raw
        if reg.raw_ext in ("json", "txt"):                 # never persist an API key
            for s in segredos:
                dados = dados.replace(s.encode(), b"***")
        raw_path, raw_sha = bruto.salvar(etapa, run_id, chave, dados, reg.raw_ext)
    chamada_id = repo.salvar_chamada(run_id=run_id, etapa=etapa, alvo_tipo=alvo_tipo, alvo_id=alvo_id,
                                     chave=chave, registro=reg, raw_path=raw_path, raw_sha256=raw_sha,
                                     uf=uf, pagina=pagina)
    return chamada_id, raw_path
