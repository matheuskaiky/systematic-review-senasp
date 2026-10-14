import json


def _limpar(texto, segredos):
    for s in segredos:
        for forma in {s, json.dumps(s)[1:-1]}:          # o segredo tambem aparece escapado dentro de JSON
            texto = texto.replace(forma, "***")
    return texto


def _limpar_registro(reg, segredos):
    """Nenhum campo que vai para o banco pode guardar a chave: erro, parametros e extras (o raw e limpo a parte)."""
    if not segredos:
        return
    if reg.erro:
        reg.erro = _limpar(reg.erro, segredos)
    reg.parametros = json.loads(_limpar(json.dumps(reg.parametros, default=str), segredos))
    reg.extras = json.loads(_limpar(json.dumps(reg.extras, default=str), segredos))


def registrar_chamada(repo, bruto, run_id, etapa, alvo_tipo, alvo_id, chave, reg, segredos,
                      uf=None, pagina=None):
    """Saves the raw payload (without secrets) and the row in `chamadas`. Returns (chamada_id, raw_path)."""
    raw_path = raw_sha = None
    _limpar_registro(reg, segredos)
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
