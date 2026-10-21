import hashlib
import json
import logging
from contextlib import contextmanager

from dominio.servicos import url_valida


def resultados_validos(resp, alvo_id):
    """Os resultados de uma busca com URL que pode ser gravada, na ordem da resposta. Cada link invalido vai para o log
    (ele continua na resposta bruta) e a contagem vai para os extras da chamada (sobrevive a retomada)."""
    validos = []
    for r in resp.resultados:
        if url_valida(r.url):
            validos.append(r)
        else:
            logging.warning("[%s] link invalido descartado: %r", alvo_id, r.url[:2000] if isinstance(r.url, str) else r.url)
    if len(validos) < len(resp.resultados):
        resp.chamada.extras["urls_invalidas"] = len(resp.resultados) - len(validos)
    return validos


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
                      uf=None, pagina=None, raw_salvo=None):
    """Saves the raw payload (without secrets) and the row in `chamadas`. Returns (chamada_id, raw_path).
    `raw_salvo` = (caminho, sha256) de um bruto ja gravado desta mesma chamada: a linha aponta para ele e nada e gravado de novo."""
    raw_path = raw_sha = None
    _limpar_registro(reg, segredos)
    if raw_salvo is not None:
        raw_path, raw_sha = raw_salvo
    elif reg.raw is not None:
        dados = reg.raw
        if reg.raw_ext in ("json", "txt"):                 # never persist an API key
            for s in segredos:
                dados = dados.replace(s.encode(), b"***")
        raw_path, raw_sha = bruto.salvar(etapa, run_id, chave, dados, reg.raw_ext)
    chamada_id = repo.salvar_chamada(run_id=run_id, etapa=etapa, alvo_tipo=alvo_tipo, alvo_id=alvo_id,
                                     chave=chave, registro=reg, raw_path=raw_path, raw_sha256=raw_sha,
                                     uf=uf, pagina=pagina)
    return chamada_id, raw_path


def registrar_falha_apos_chamada(repo, bruto, run_id, etapa, alvo_tipo, alvo_id, chave, reg, segredos, excecao, prefixo,
                                 uf=None, pagina=None):
    """A chamada paga ja respondeu, mas o trabalho antes da gravacao (extrair o texto, validar a resposta) falhou ou foi
    interrompido: registra a chamada como falha ("<prefixo>: <Tipo>"), para ela ficar rastreada e contar no --limite."""
    reg.erro = f"{prefixo}: {type(excecao).__name__}" + (f" | {reg.erro}" if reg.erro else "")
    try:
        with item_gravado(repo, bruto, run_id, etapa, alvo_tipo, alvo_id, chave, reg, segredos, uf=uf, pagina=pagina):
            pass
    except BaseException as registro:
        # quem chamou relanca a excecao ORIGINAL (o Ctrl+C continua sendo uma interrupcao, nao uma falha de banco)
        logging.error("O registro da falha depois da chamada levantou %s; segue a excecao original (%s). etapa=%s chave=%s",
                      type(registro).__name__, type(excecao).__name__, etapa, chave)


@contextmanager
def item_gravado(repo, bruto, run_id, etapa, alvo_tipo, alvo_id, chave, reg, segredos, uf=None, pagina=None):
    """Grava a chamada e o que o item produziu numa transacao so, confirmada ao sair do bloco. Se algo falha antes da
    confirmacao (erro de banco, Ctrl+C), desfaz o que o item gravou e regrava a chamada como falha ("falha_ao_gravar: <Tipo>"),
    apontando para o mesmo arquivo bruto: a chamada paga continua rastreada e a retomada refaz o item (ate o limite de
    falhas da etapa). O que estava pendente antes do item (metricas) e confirmado antes, para o desfazer so pegar o item."""
    repo.confirmar()
    chamada_id = raw_path = None
    try:
        chamada_id, raw_path = registrar_chamada(repo, bruto, run_id, etapa, alvo_tipo, alvo_id, chave, reg, segredos,
                                                 uf=uf, pagina=pagina)
        yield chamada_id
        repo.confirmar()
    except BaseException as original:
        if chamada_id is not None and not repo.pendente():
            raise                                   # o item ja foi confirmado por inteiro: nada a desfazer nem a regravar
        repo.desfazer()
        try:
            reg.erro = f"falha_ao_gravar: {type(original).__name__}" + (f" | {reg.erro}" if reg.erro else "")
            salvo = (raw_path, hashlib.sha256(bruto.ler(raw_path)).hexdigest()) if raw_path else None
            registrar_chamada(repo, bruto, run_id, etapa, alvo_tipo, alvo_id, chave, reg, segredos,
                              uf=uf, pagina=pagina, raw_salvo=salvo)
            repo.confirmar()
        except BaseException as segunda:
            repo.desfazer()
            logging.error("Chamada sem registro: a gravacao do item falhou (%s) e o registro da falha tambem (%s). "
                          "etapa=%s chave=%s bruto=%s", type(original).__name__, type(segunda).__name__, etapa, chave, raw_path)
        raise original
