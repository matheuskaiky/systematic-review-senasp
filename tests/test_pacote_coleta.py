"""Pacote de uma execucao enviada do computador local para a nuvem (D99, D100): conferencia do formato, montagem no banco
local e juntada no banco central (SQLite e PostgreSQL), com renumeracao, reenvio que atualiza so o que mudou, decisoes
humanas e linhas compartilhadas intocadas, dono da execucao e tudo ou nada."""
import copy
import json
import sqlite3

import pytest

from adaptadores import pacote_coleta as J
from adaptadores.repositorio_sqlite import RepositorioSQLite
from dominio import pacote_coleta as P

RUN = "20261020_101500_abc123"
OUTRA = "20261019_090000_def456"


def linha(t, **valores):
    l = {c: None for c in P.COLUNAS[t]}
    l.update(valores)
    return l


def pacote():
    """Um pacote pequeno e valido, com uma linha de cada tabela e os tres formatos de alvo_id que levam numeros."""
    return {"versao": 2, "run_id": RUN, "externas": {"paginas": []}, "tabelas": {
        "execucoes": [linha("execucoes", run_id=RUN, iniciado_em="2026-10-20T10:15:00+00:00", config_hash="h", config_json="{}",
                            status="concluida")],
        "execucoes_retomadas": [linha("execucoes_retomadas", retomada_id=3, run_id=RUN, retomado_em="2026-10-20T11:00:00+00:00")],
        "metricas_run": [linha("metricas_run", run_id=RUN, chave="n_urls", valor=1.0)],
        "saldos": [linha("saldos", id=4, run_id=RUN, provedor="serpapi", momento="inicio", valor=100.0)],
        "chamadas": [
            linha("chamadas", chamada_id=10, run_id=RUN, etapa="download", provedor="http", alvo_id="7", parametros_json="{}",
                  chave_idempotencia="k10", requisitado_em="t", sucesso=1),
            linha("chamadas", chamada_id=11, run_id=RUN, etapa="classificacao", provedor="gemini", alvo_id="7:SP",
                  parametros_json="{}", chave_idempotencia="k11", requisitado_em="t", sucesso=1),
            linha("chamadas", chamada_id=12, run_id=RUN, etapa="triagem_escopo", provedor="gemini", alvo_id="artigo:1:5",
                  parametros_json="{}", chave_idempotencia="k12", requisitado_em="t", sucesso=1),
            linha("chamadas", chamada_id=13, run_id=RUN, etapa="busca_web", provedor="serpapi", alvo_id="M01-SP-x",
                  parametros_json="{}", chave_idempotencia="k13", requisitado_em="t", sucesso=1)],
        "ocorrencias": [linha("ocorrencias", ocorrencia_id=20, chamada_id=12, artigo_id=5, termo_id="T01", run_id=RUN, posicao=1)],
        "ocorrencias_web": [linha("ocorrencias_web", ocorrencia_id=22, chamada_id=13, run_id=RUN, conjunto="A", consulta_id="LA1",
                                  referencia_id=8, posicao=1, titulo="Uma referência")],
        "resultados_web": [linha("resultados_web", resultado_id=21, chamada_id=13, run_id=RUN, consulta_id="M01", uf="SP", url_id=7)],
        "selecao_download": [linha("selecao_download", run_id=RUN, url_id=7, uf="SP", selecionada=1, auditoria=0)],
        "paginas": [linha("paginas", pagina_id=30, run_id=RUN, url_id=7, chamada_id=10)],
        "classificacoes": [linha("classificacoes", classificacao_id=40, chamada_id=11, run_id=RUN, url_id=7, pagina_id=30, uf="SP")],
        "achados": [linha("achados", achado_id=50, classificacao_id=40, uf="SP", tecnologia="drones", confianca="alta")],
        "achados_descartados": [linha("achados_descartados", descartado_id=51, classificacao_id=40, uf="SP")],
        "triagem_escopo": [linha("triagem_escopo", id=60, run_id=RUN, chamada_id=12, fonte="artigo", item_id=5, uf="", status="ok",
                                 valido=1, criado_em="t")],
        "urls": [linha("urls", url_id=7, url_normalizada="https://ssp.sp.gov.br/a", url_original="https://www.ssp.sp.gov.br/a")],
        "artigos": [linha("artigos", artigo_id=5, chave_dedup="abc", titulo="Um artigo")],
        "referencias_web": [linha("referencias_web", referencia_id=8, url_normalizada="https://exemplo.org/a",
                                  url_original="https://www.exemplo.org/a", dominio="exemplo.org", primeira_vez_run=RUN,
                                  primeira_vez_em="t")],
    }}


def _com(mudar):
    p = pacote()
    mudar(p)
    return P.conferir(p)


T = lambda p: p["tabelas"]  # noqa: E731

CASOS = [
    ("valido", lambda p: None, []),
    ("nao e objeto", None, ["O pacote precisa ser um objeto JSON com as chaves versao, run_id, tabelas e externas."]),
    ("chave a mais", lambda p: p.update(extra=1), ["O pacote precisa ser um objeto JSON com as chaves versao, run_id, tabelas e externas."]),
    ("sem externas", lambda p: p.pop("externas"), ["O pacote precisa ser um objeto JSON com as chaves versao, run_id, tabelas e externas."]),
    ("versao 1", lambda p: p.update(versao=1), ["Versão do pacote não suportada: 1 (esta nuvem aceita 2)."]),
    ("versao 3", lambda p: p.update(versao=3), ["Versão do pacote não suportada: 3 (esta nuvem aceita 2)."]),
    ("versao texto", lambda p: p.update(versao="2"), ["Versão do pacote não suportada: '2' (esta nuvem aceita 2)."]),
    ("versao booleana", lambda p: p.update(versao=True), ["Versão do pacote não suportada: True (esta nuvem aceita 2)."]),
    ("run_id ruim", lambda p: p.update(run_id="20261020_1015_abc123"), ["run_id inválido: '20261020_1015_abc123'."]),
    ("run_id maiusculo", lambda p: p.update(run_id="20261020_101500_ABC123"), ["run_id inválido: '20261020_101500_ABC123'."]),
    ("tabelas lista", lambda p: p.update(tabelas=[]), ["tabelas precisa ser um objeto com uma lista de linhas por tabela."]),
    ("faltam e sobram", lambda p: (T(p).pop("saldos"), T(p).pop("urls"), T(p).update(zz=[], aa=[])),
     ["Tabelas faltando no pacote: saldos, urls.", "Tabelas desconhecidas no pacote: aa, zz."]),
    ("tabela nao lista", lambda p: T(p).update(saldos={}), ["saldos: deve ser uma lista de linhas."]),
    ("sem execucao", lambda p: T(p).update(execucoes=[]), ["execucoes: o pacote precisa de exatamente uma linha."]),
    ("duas execucoes", lambda p: T(p)["execucoes"].append(dict(T(p)["execucoes"][0])),
     ["execucoes: o pacote precisa de exatamente uma linha."]),
    ("externas ruim", lambda p: p.update(externas={"paginas": [], "outra": []}), ["externas precisa ser um objeto só com a lista paginas."]),
    ("linha nao objeto", lambda p: T(p)["saldos"].append([1]), ["saldos, linha 2: deve ser um objeto."]),
    ("colunas faltam e sobram", lambda p: (T(p)["saldos"][0].pop("valor"), T(p)["saldos"][0].update(zz=1, aa=2)),
     ["saldos, linha 1: colunas faltando: valor; colunas desconhecidas: aa, zz."]),
    ("campo humano no pacote", lambda p: T(p)["achados"][0].update(verificado=1),
     ["achados, linha 1: colunas desconhecidas: verificado."]),
    ("id zero", lambda p: T(p)["saldos"][0].update(id=0), ["saldos, linha 1: id deve ser um número inteiro positivo."]),
    ("id texto", lambda p: T(p)["saldos"][0].update(id="4"), ["saldos, linha 1: id deve ser um número inteiro positivo."]),
    ("id booleano", lambda p: T(p)["saldos"][0].update(id=True), ["saldos, linha 1: id deve ser um número inteiro positivo."]),
    ("id acima de 64 bits", lambda p: T(p)["saldos"][0].update(id=2 ** 63), ["saldos, linha 1: id deve ser um número inteiro positivo."]),
    ("id no limite", lambda p: T(p)["saldos"][0].update(id=2 ** 63 - 1), []),
    ("valor lista e booleano", lambda p: T(p)["saldos"][0].update(provedor=["x"], valor=False),
     ["saldos, linha 1: valor inválido em provedor, valor (tipo errado, fora do limite, NaN ou texto com NUL)."]),
    ("inteiro acima de 64 bits fora da chave", lambda p: T(p)["chamadas"][0].update(latencia_ms=10 ** 30),
     ["chamadas, linha 1: valor inválido em latencia_ms (tipo errado, fora do limite, NaN ou texto com NUL)."]),
    ("real nan e texto com NUL", lambda p: (T(p)["chamadas"][0].update(custo_usd=float("nan")), T(p)["achados"][0].update(evidencia="a\x00b")),
     ["chamadas, linha 1: valor inválido em custo_usd (tipo errado, fora do limite, NaN ou texto com NUL).", "achados, linha 1: valor inválido em evidencia (tipo errado, fora do limite, NaN ou texto com NUL)."]),
    ("caractere sem par", lambda p: T(p)["achados"][0].update(evidencia="\ud800"), ["achados, linha 1: valor inválido em evidencia (tipo errado, fora do limite, NaN ou texto com NUL)."]),
    ("texto no limite e acima", lambda p: (T(p)["achados"][0].update(evidencia="x" * P.MAX_TEXTO),
                                           T(p)["achados_descartados"][0].update(evidencia="x" * (P.MAX_TEXTO + 1))),
     ["achados_descartados, linha 1: valor inválido em evidencia (tipo errado, fora do limite, NaN ou texto com NUL)."]),
    ("numero no texto e texto no numero", lambda p: (T(p)["urls"][0].update(url_normalizada=5), T(p)["saldos"][0].update(valor="1")),
     ["saldos, linha 1: valor inválido em valor (tipo errado, fora do limite, NaN ou texto com NUL).", "urls, linha 1: valor inválido em url_normalizada (tipo errado, fora do limite, NaN ou texto com NUL)."]),
    ("real como inteiro e aceito", lambda p: T(p)["saldos"][0].update(valor=100), []),
    ("obrigatorias vazias", lambda p: (T(p)["chamadas"][0].update(parametros_json=None, sucesso=None),
                                       T(p)["execucoes"][0].update(config_hash=None)),
     ["execucoes, linha 1: não pode ficar vazio: config_hash.", "chamadas, linha 1: não pode ficar vazio: parametros_json, sucesso."]),
    ("run_id de outra execucao", lambda p: T(p)["saldos"][0].update(run_id=OUTRA), ["saldos, linha 1: run_id diferente do do pacote."]),
    ("referencia vazia proibida", lambda p: T(p)["paginas"][0].update(url_id=None),
     ["paginas, linha 1: não pode ficar vazio: url_id."]),
    ("referencias vazias permitidas", lambda p: (T(p)["classificacoes"][0].update(pagina_id=None),
                                                 T(p)["triagem_escopo"][0].update(chamada_id=None)), []),
    ("alvo fora do formato", lambda p: T(p)["chamadas"][1].update(alvo_id="7-SP"),
     ["chamadas, linha 2: alvo_id '7-SP' fora do formato da etapa classificacao."]),
    ("alvo vazio no download", lambda p: T(p)["chamadas"][0].update(alvo_id=None),
     ["chamadas, linha 1: alvo_id None fora do formato da etapa download."]),
    ("alvo livre em outra etapa", lambda p: T(p)["chamadas"][3].update(alvo_id=None), []),
    ("fonte invalida", lambda p: T(p)["triagem_escopo"][0].update(fonte="pdf"),
     ["triagem_escopo, linha 1: fonte deve ser web ou artigo e item_id um número inteiro positivo."]),
    ("chave repetida", lambda p: (T(p)["saldos"].append(dict(T(p)["saldos"][0])),
                                  T(p)["chamadas"].append(dict(T(p)["chamadas"][3], chave_idempotencia="k14"))),
     ["saldos: id 4 repetido.", "chamadas: chamada_id 13 repetido."]),
    ("idempotencia repetida so entre as de sucesso", lambda p: (
        T(p)["chamadas"].append(dict(T(p)["chamadas"][3], chamada_id=14)),
        T(p)["chamadas"].append(dict(T(p)["chamadas"][3], chamada_id=15, sucesso=0)),
        T(p)["chamadas"].append(dict(T(p)["chamadas"][3], chamada_id=16, sucesso=0))),
     ["chamadas: chave_idempotencia k13 repetido."]),
    ("triagem repetida pela restricao unica", lambda p: T(p)["triagem_escopo"].append(dict(T(p)["triagem_escopo"][0], id=61)),
     ["triagem_escopo: fonte, item_id, uf artigo, 5,  repetido."]),
    ("alvo com digitos demais", lambda p: T(p)["chamadas"][0].update(alvo_id="9" * 5000),
     [f"chamadas, linha 1: alvo_id {'9' * 5000!r} fora do formato da etapa download."]),
    ("alvo com zero a esquerda", lambda p: T(p)["chamadas"][0].update(alvo_id="07"),
     ["chamadas, linha 1: alvo_id '07' fora do formato da etapa download."]),
    ("pagina externa repetida", lambda p: p.update(externas={"paginas": [{"pagina_id": 31, "run_id": OUTRA},
                                                                        {"pagina_id": 31, "run_id": "20261018_090000_aaa111"}]}),
     ["externas.paginas: pagina_id 31 repetido."]),
    ("pagina externa invalida nao gera cascata", lambda p: (T(p)["classificacoes"][0].update(pagina_id=31),
                                                            p.update(externas={"paginas": [{"pagina_id": 31, "run_id": "ruim"}]})),
     ["externas.paginas, linha 1: precisa de pagina_id (número inteiro positivo) e run_id de outra execução."]),
    ("chave natural repetida", lambda p: T(p)["metricas_run"].append(dict(T(p)["metricas_run"][0])),
     ["metricas_run: run_id, chave 20261020_101500_abc123, n_urls repetido."]),
    ("url repetida pela chave natural", lambda p: T(p)["urls"].append(dict(T(p)["urls"][0], url_id=8)),
     ["urls: url_normalizada 'https://ssp.sp.gov.br/a' repetido."]),
    ("referencias fora do pacote", lambda p: (T(p)["resultados_web"][0].update(chamada_id=99, url_id=98)),
     ["resultados_web, linha 1: chamada_id 99 não está no pacote (chamadas).",
      "resultados_web, linha 1: url_id 98 não está no pacote (urls)."]),
    ("alvo e item fora do pacote", lambda p: (T(p)["chamadas"][0].update(alvo_id="70"), T(p)["triagem_escopo"][0].update(item_id=6)),
     ["chamadas, linha 1: alvo_id '70' aponta para urls 70, que não está no pacote.",
      "triagem_escopo, linha 1: item_id 6 não está no pacote (artigos)."]),
    ("pagina de outra execucao declarada", lambda p: (T(p)["classificacoes"][0].update(pagina_id=31),
                                                      p.update(externas={"paginas": [{"pagina_id": 31, "run_id": OUTRA}]})), []),
    ("pagina externa da propria execucao", lambda p: p.update(externas={"paginas": [{"pagina_id": 31, "run_id": RUN}]}),
     ["externas.paginas, linha 1: precisa de pagina_id (número inteiro positivo) e run_id de outra execução."]),
    ("erro de linha isola a linha", lambda p: T(p)["resultados_web"][0].update(resultado_id=0, chamada_id=99),
     ["resultados_web, linha 1: resultado_id deve ser um número inteiro positivo."]),
    ("combinacao na ordem", lambda p: (T(p)["chamadas"].append(dict(T(p)["chamadas"][3], chave_idempotencia="k14")),
                                       T(p)["saldos"][0].pop("valor"), T(p)["paginas"][0].update(chamada_id=77),
                                       p.update(externas={"paginas": [{"pagina_id": 1, "run_id": RUN}]})),
     ["saldos, linha 1: colunas faltando: valor.",
      "externas.paginas, linha 1: precisa de pagina_id (número inteiro positivo) e run_id de outra execução.",
      "chamadas: chamada_id 13 repetido.", "paginas, linha 1: chamada_id 77 não está no pacote (chamadas)."]),
    # busca de literatura na web (versao 2 do pacote)
    ("sem ocorrencias_web", lambda p: T(p).pop("ocorrencias_web"), ["Tabelas faltando no pacote: ocorrencias_web."]),
    ("sem referencias_web", lambda p: T(p).pop("referencias_web"), ["Tabelas faltando no pacote: referencias_web."]),
    ("referencia que falta", lambda p: T(p)["ocorrencias_web"][0].update(referencia_id=99),
     ["ocorrencias_web, linha 1: referencia_id 99 não está no pacote (referencias_web)."]),
    ("referencia_id zero", lambda p: T(p)["ocorrencias_web"][0].update(referencia_id=0),
     ["ocorrencias_web, linha 1: referencia_id deve ser um número inteiro positivo."]),
    ("conjunto numero", lambda p: T(p)["ocorrencias_web"][0].update(conjunto=1),
     ["ocorrencias_web, linha 1: valor inválido em conjunto (tipo errado, fora do limite, NaN ou texto com NUL)."]),
    ("conjunto null", lambda p: T(p)["ocorrencias_web"][0].update(conjunto=None),
     ["ocorrencias_web, linha 1: não pode ficar vazio: conjunto."]),
    ("ocorrencia de outra execucao", lambda p: T(p)["ocorrencias_web"][0].update(run_id=OUTRA),
     ["ocorrencias_web, linha 1: run_id diferente do do pacote."]),
    ("ocorrencia com coluna a mais", lambda p: T(p)["ocorrencias_web"][0].update(extra=1),
     ["ocorrencias_web, linha 1: colunas desconhecidas: extra."]),
    ("url_normalizada null", lambda p: T(p)["referencias_web"][0].update(url_normalizada=None),
     ["referencias_web, linha 1: não pode ficar vazio: url_normalizada."]),
    ("referencia com url repetida", lambda p: T(p)["referencias_web"].append(dict(T(p)["referencias_web"][0], referencia_id=9)),
     ["referencias_web: url_normalizada 'https://exemplo.org/a' repetido."]),
    ("ocorrencia sem chamada", lambda p: T(p)["ocorrencias_web"][0].update(chamada_id=None),
     ["ocorrencias_web, linha 1: não pode ficar vazio: chamada_id."]),
    ("ocorrencia com chamada que falta", lambda p: T(p)["ocorrencias_web"][0].update(chamada_id=99),
     ["ocorrencias_web, linha 1: chamada_id 99 não está no pacote (chamadas)."]),
    ("posicao texto", lambda p: T(p)["ocorrencias_web"][0].update(posicao="1"),
     ["ocorrencias_web, linha 1: valor inválido em posicao (tipo errado, fora do limite, NaN ou texto com NUL)."]),
    ("referencia sem url_original", lambda p: T(p)["referencias_web"][0].update(url_original=None),
     ["referencias_web, linha 1: não pode ficar vazio: url_original."]),
    ("referencia sem dominio", lambda p: T(p)["referencias_web"][0].update(dominio=None),
     ["referencias_web, linha 1: não pode ficar vazio: dominio."]),
    ("referencia sem primeira_vez_run", lambda p: T(p)["referencias_web"][0].update(primeira_vez_run=None),
     ["referencias_web, linha 1: não pode ficar vazio: primeira_vez_run."]),
    ("referencia sem primeira_vez_em", lambda p: T(p)["referencias_web"][0].update(primeira_vez_em=None),
     ["referencias_web, linha 1: não pode ficar vazio: primeira_vez_em."]),
    ("referencia_id invalido", lambda p: T(p)["referencias_web"][0].update(referencia_id="8"),
     ["referencias_web, linha 1: referencia_id deve ser um número inteiro positivo.",
      "ocorrencias_web, linha 1: referencia_id 8 não está no pacote (referencias_web)."]),
    ("referencia_id repetido", lambda p: T(p)["referencias_web"].append(
        dict(T(p)["referencias_web"][0], url_normalizada="https://x.org/b")), ["referencias_web: referencia_id 8 repetido."]),
]


@pytest.mark.parametrize("nome,mudar,erros", CASOS, ids=[c[0] for c in CASOS])
def test_conferir(nome, mudar, erros):
    assert (P.conferir([]) if mudar is None else _com(mudar)) == erros


def test_colunas_do_pacote_sao_as_da_base_menos_as_decisoes_humanas(tmp_path):
    RepositorioSQLite(tmp_path / "x.db").fechar()
    con = sqlite3.connect(tmp_path / "x.db")
    for t in P.TABELAS:
        base = [r[1] for r in con.execute(f"PRAGMA table_info({t})")]
        fora = P.CAMPOS_HUMANOS.get(t, ()) + P.CAMPOS_SO_DO_VIES.get(t, ())
        assert list(P.COLUNAS[t]) == [c for c in base if c not in fora], t


# ---------- montar no banco local ----------
@pytest.fixture
def local(copiar_demo):
    banco, _ = copiar_demo("pacote_local")
    repo = RepositorioSQLite(banco)
    yield repo
    repo.fechar()


def _run_com_urls_e_chamadas(repo):
    """A primeira execucao (na ordem de envio) com URLs e chamadas: as execucoes da demonstracao criadas no mesmo segundo
    mudam de ordem entre as maquinas, e a academica nao tem URL."""
    return next(r for r in _runs(repo) if (lambda p: p["tabelas"]["urls"] and p["tabelas"]["chamadas"])(repo.pacote_da_execucao(r)))


def _runs(repo):
    """As execucoes numa ordem de envio valida: a dona de uma pagina usada por outra vai antes (as externas)."""
    todas = [r[0] for r in repo.conn.execute("SELECT run_id FROM execucoes ORDER BY run_id")]
    depende = {r: {e["run_id"] for e in repo.pacote_da_execucao(r)["externas"]["paginas"]} for r in todas}
    ordem = []
    while len(ordem) < len(todas):
        ordem.append(next(r for r in todas if r not in ordem and depende[r] <= set(ordem)))
    return ordem


def _pacote_json(repo, run_id):
    return json.loads(json.dumps(repo.pacote_da_execucao(run_id)))


def test_montar_execucao_inexistente(local):
    with pytest.raises(J.ErroPacote) as e:
        local.pacote_da_execucao(RUN)
    assert str(e.value) == f"A execução {RUN} não existe neste banco."


def test_pacotes_da_demonstracao_sao_validos_e_sem_decisoes_humanas(local):
    externas = 0
    for r in _runs(local):
        p = _pacote_json(local, r)
        assert P.conferir(p) == [] and p["run_id"] == r
        assert all("verificado" not in a for a in p["tabelas"]["achados"])
        assert all("no_relatorio" not in e for e in p["tabelas"]["execucoes"])
        externas += len(p["externas"]["paginas"])
    assert externas > 0                                   # a demonstracao tem classificacao sobre pagina de outra execucao


# ---------- juntar no banco central ----------
@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)])
def central(request, tmp_path):
    """Fabrica de repositorios do banco central (um por envio, como no painel)."""
    if request.param == "sqlite":
        caminho = tmp_path / "central.db"
        RepositorioSQLite(caminho).fechar()
        yield lambda: RepositorioSQLite(caminho), lambda sql, args=(): sqlite3.connect(caminho).execute(sql, args).fetchall()
        return
    import psycopg
    from adaptadores import migrador_postgres as M
    from adaptadores.postgres.conexao import chaves_do_banco, criar_pool
    from adaptadores.repositorio_postgres import RepositorioPostgres
    url = request.getfixturevalue("pg_url")
    M.aplicar(url)
    pool = criar_pool(url)
    chaves = chaves_do_banco(pool)

    from adaptadores.postgres.conexao import _configurar

    def consultar(sql, args=()):
        with psycopg.connect(url) as c:
            _configurar(c)                             # numeric como o painel le (inteiro ou real)
            return [tuple(r) for r in c.execute(sql.replace("?", "%s"), args).fetchall()]
    yield lambda: RepositorioPostgres(pool, chaves), consultar
    pool.close()


def _enviar(fabrica, pacote, usuario=1):
    repo = fabrica()
    try:
        return repo.juntar_pacote(pacote, usuario, "2026-10-20T12:00:00+00:00")
    finally:
        repo.fechar()


def _contagens(consultar):
    return {t: consultar(f"SELECT COUNT(*) FROM {t}")[0][0] for t in P.TABELAS + ("origem_ids", "envios_execucao")}


def _canonico(consultar):
    """O conteudo da coleta sem os numeros de cada banco: urls e artigos pela chave natural; as outras linhas pela
    execucao e pela posicao dentro dela; alvo_id e item_id com os numeros trocados pelo mesmo canonico."""
    urls = {i: n for i, n in consultar("SELECT url_id, url_normalizada FROM urls")}
    artigos = {i: n for i, n in consultar("SELECT artigo_id, chave_dedup FROM artigos")}
    run_da = {"classificacoes": {i: r for i, r in consultar("SELECT classificacao_id, run_id FROM classificacoes")}}
    referencias = {i: n for i, n in consultar("SELECT referencia_id, url_normalizada FROM referencias_web")}
    canon = {"urls": urls, "artigos": artigos, "referencias_web": referencias}
    saida = {}
    for t, chave, colunas, refs in P.DA_EXECUCAO:
        linhas = [dict(zip(colunas, r)) for r in consultar(f"SELECT {', '.join(colunas)} FROM {t}")]
        if chave:
            def run_de(l):
                return l["run_id"] if "run_id" in l else run_da["classificacoes"][l["classificacao_id"]]
            ordem = sorted(linhas, key=lambda l: (run_de(l), l[chave]))
            posicao, por_run = {}, {}
            for l in ordem:
                n = por_run[run_de(l)] = por_run.get(run_de(l), 0) + 1
                posicao[l[chave]] = (run_de(l), n)
            canon[t] = posicao
        saida[t] = linhas
    resultado = {}
    for t, chave, colunas, refs in P.DA_EXECUCAO:
        lista = []
        for l in saida[t]:
            l = dict(l)
            if chave:
                l[chave] = canon[t][l[chave]]
            for c, alvo in refs.items():
                if l[c] is not None:
                    l[c] = canon[alvo.rstrip("?")][l[c]]
            if t == "chamadas" and l["etapa"] in P.RE_ALVO and l["alvo_id"] is not None:
                m = P.RE_ALVO[l["etapa"]].fullmatch(l["alvo_id"])
                if l["etapa"] == "triagem_escopo":
                    l["alvo_id"] = (m["fonte"], m["n"], canon[P.FONTE_DO_ITEM[m["fonte"]]][int(m["item"])], m["resto"])
                else:
                    l["alvo_id"] = (urls[int(m["url"])], m.groupdict().get("uf"))
            if t == "triagem_escopo":
                l["item_id"] = canon[P.FONTE_DO_ITEM[l["fonte"]]][l["item_id"]]
            lista.append(tuple(sorted((k, repr(v)) for k, v in l.items())))
        resultado[t] = sorted(lista)
    return resultado


def test_todas_as_execucoes_chegam_iguais_e_reenviar_nao_muda_nada(local, central):
    fabrica, consultar = central
    runs = _runs(local)
    for r in runs:
        _enviar(fabrica, _pacote_json(local, r))
    lite = lambda sql, args=(): local.conn.execute(sql, args).fetchall()  # noqa: E731
    assert _canonico(consultar) == _canonico(lite)
    antes = _contagens(consultar)
    for r in runs:
        rel = _enviar(fabrica, _pacote_json(local, r))
        assert all(v["novas"] == 0 and v["atualizadas"] == 0 for v in rel.values()), r
    assert _contagens(consultar) == antes
    assert consultar("SELECT run_id, usuario_id, n_envios FROM envios_execucao ORDER BY run_id") == [(r, 1, 2) for r in sorted(runs)]


def test_reenvio_acrescenta_e_atualiza_so_o_que_mudou_e_nada_e_apagado(local, central):
    fabrica, consultar = central
    run = _run_com_urls_e_chamadas(local)
    local.conn.execute("INSERT INTO metricas_run (run_id, chave, valor) VALUES (?, 'metrica_apagada_depois', 1.0)", (run,))
    local.conn.commit()
    _enviar(fabrica, _pacote_json(local, run))
    cid = local.conn.execute("SELECT MIN(chamada_id) FROM chamadas WHERE run_id = ?", (run,)).fetchone()[0]
    local.conn.execute("UPDATE chamadas SET erro = 'mudou no local' WHERE chamada_id = ?", (cid,))
    local.conn.execute("INSERT INTO metricas_run (run_id, chave, valor) VALUES (?, 'nova_metrica', 3.5)", (run,))
    chave_apagada = "metrica_apagada_depois"
    local.conn.execute("DELETE FROM metricas_run WHERE run_id = ? AND chave = ?", (run, chave_apagada))
    local.conn.commit()
    rel = _enviar(fabrica, _pacote_json(local, run))
    assert rel["chamadas"]["atualizadas"] == 1 and rel["metricas_run"]["novas"] == 1
    assert sum(v["novas"] + v["atualizadas"] for v in rel.values()) == 2
    assert consultar("SELECT COUNT(*) FROM chamadas WHERE erro = 'mudou no local'") == [(1,)]
    assert consultar("SELECT COUNT(*) FROM metricas_run WHERE run_id = ? AND chave = ?", (run, chave_apagada)) == [(1,)]


def test_decisoes_humanas_e_exclusao_do_relatorio_nunca_sao_tocadas(local, central):
    fabrica, consultar = central
    ordem = _runs(local)
    run = next(r for r in ordem if local.conn.execute(
        "SELECT 1 FROM achados a JOIN classificacoes k USING (classificacao_id) WHERE k.run_id = ?", (r,)).fetchone())
    for r in ordem[:ordem.index(run) + 1]:                # as execucoes de que ela depende vao antes
        _enviar(fabrica, _pacote_json(local, r))
    repo = fabrica()
    try:
        repo.conn.execute("UPDATE achados SET verificado = 1, status_final = 'em_uso', verificado_por = 'Ana', "
                          "verificado_em = 'v', observacao = 'o' WHERE classificacao_id IN "
                          "(SELECT classificacao_id FROM classificacoes WHERE run_id = ?)", (run,))
        repo.conn.execute("UPDATE execucoes SET no_relatorio = 0, motivo_exclusao = 'teste', excluida_em = 'e' WHERE run_id = ?", (run,))
        repo.conn.commit()
    finally:
        repo.fechar()
    local.conn.execute("UPDATE achados SET confianca = 'baixa', verificado = 0, status_final = NULL "
                       "WHERE classificacao_id IN (SELECT classificacao_id FROM classificacoes WHERE run_id = ?)", (run,))
    local.conn.execute("UPDATE execucoes SET status = 'interrompida', no_relatorio = 1 WHERE run_id = ?", (run,))
    local.conn.commit()
    _enviar(fabrica, _pacote_json(local, run))
    assert set(consultar("SELECT a.verificado, a.status_final, a.verificado_por, a.verificado_em, a.observacao, a.confianca "
                         "FROM achados a JOIN classificacoes k USING (classificacao_id) WHERE k.run_id = ?", (run,))) == \
        {(1, "em_uso", "Ana", "v", "o", "baixa")}
    assert consultar("SELECT status, no_relatorio, motivo_exclusao, excluida_em FROM execucoes WHERE run_id = ?", (run,)) == \
        [("interrompida", 0, "teste", "e")]


def test_url_e_artigo_da_nuvem_nunca_mudam(local, central):
    fabrica, consultar = central
    run = _run_com_urls_e_chamadas(local)
    p = _pacote_json(local, run)
    u, a = p["tabelas"]["urls"][0], p["tabelas"]["artigos"][0] if p["tabelas"]["artigos"] else None
    repo = fabrica()
    try:
        repo.conn.execute("INSERT INTO urls (url_normalizada, url_original) VALUES (?, 'da-nuvem')", (u["url_normalizada"],))
        if a:
            repo.conn.execute("INSERT INTO artigos (chave_dedup, titulo, citacoes) VALUES (?, 'titulo da nuvem', 1)", (a["chave_dedup"],))
        repo.conn.commit()
    finally:
        repo.fechar()
    rel = _enviar(fabrica, p)
    assert rel["urls"]["iguais"] == 1 and consultar("SELECT url_original FROM urls WHERE url_normalizada = ?",
                                                    (u["url_normalizada"],)) == [("da-nuvem",)]
    if a:
        assert consultar("SELECT titulo, citacoes FROM artigos WHERE chave_dedup = ?", (a["chave_dedup"],)) == [("titulo da nuvem", 1)]


def test_execucao_de_outro_usuario_e_recusada_sem_gravar(local, central):
    fabrica, consultar = central
    run = _runs(local)[0]
    _enviar(fabrica, _pacote_json(local, run), usuario=1)
    antes = _contagens(consultar)
    with pytest.raises(J.ErroPacote) as e:
        _enviar(fabrica, _pacote_json(local, run), usuario=2)
    assert str(e.value) == f"A execução {run} foi enviada por outro usuário: só quem a enviou primeiro pode reenviá-la."
    assert _contagens(consultar) == antes


def test_pagina_de_execucao_ainda_nao_enviada_recusa_tudo(local, central):
    fabrica, consultar = central
    run, p = next((r, p) for r in _runs(local) for p in [_pacote_json(local, r)] if p["externas"]["paginas"])
    vazio = _contagens(consultar)
    e0 = p["externas"]["paginas"][0]
    with pytest.raises(J.ErroPacote) as e:
        _enviar(fabrica, p)
    assert str(e.value) == (f"A execução {run} usa a página {e0['pagina_id']} da execução {e0['run_id']}, que ainda não foi "
                            f"enviada: envie antes a execução {e0['run_id']}.")
    assert _contagens(consultar) == vazio


def test_execucao_ja_existente_sem_envio_e_recusada(local, central):
    fabrica, consultar = central
    run = _runs(local)[0]
    repo = fabrica()
    try:
        repo.conn.execute("INSERT INTO execucoes (run_id, iniciado_em, config_hash, config_json, status) VALUES (?, 't', 'h', '{}', 'x')",
                          (run,))
        repo.conn.commit()
    finally:
        repo.fechar()
    with pytest.raises(J.ErroPacote) as e:
        _enviar(fabrica, _pacote_json(local, run))
    assert str(e.value) == f"A execução {run} já existe neste banco sem registro de envio: não é juntada por envio."


def test_pacote_invalido_e_recusado_sem_gravar(central):
    fabrica, consultar = central
    p = pacote()
    p["tabelas"]["saldos"][0]["id"] = 0
    vazio = _contagens(consultar)
    with pytest.raises(J.ErroPacote) as e:
        _enviar(fabrica, p)
    assert str(e.value) == "Pacote recusado: saldos, linha 1: id deve ser um número inteiro positivo."
    muitos = pacote()
    for t in ("saldos", "paginas", "achados", "ocorrencias", "resultados_web", "classificacoes"):
        muitos["tabelas"][t][0].pop(P.COLUNAS[t][-1])
    with pytest.raises(J.ErroPacote) as e:
        _enviar(fabrica, muitos)
    assert str(e.value).endswith(" (e mais 1)")
    assert _contagens(consultar) == vazio


def test_pacote_pequeno_renumera_os_alvos(central):
    fabrica, consultar = central
    repo = fabrica()
    try:                                                  # numeros da nuvem diferentes dos locais
        repo.conn.execute("INSERT INTO urls (url_normalizada, url_original) VALUES ('https://outra/1', 'x')")
        repo.conn.execute("INSERT INTO artigos (chave_dedup, titulo) VALUES ('zzz', 'outro')")
        repo.conn.commit()
    finally:
        repo.fechar()
    _enviar(fabrica, pacote())
    url = consultar("SELECT url_id FROM urls WHERE url_normalizada = 'https://ssp.sp.gov.br/a'")[0][0]
    art = consultar("SELECT artigo_id FROM artigos WHERE chave_dedup = 'abc'")[0][0]
    assert url != 7 and art != 5
    assert dict(consultar("SELECT etapa, alvo_id FROM chamadas")) == {
        "download": str(url), "classificacao": f"{url}:SP", "triagem_escopo": f"artigo:1:{art}", "busca_web": "M01-SP-x"}
    assert consultar("SELECT item_id FROM triagem_escopo") == [(art,)]
    assert consultar("SELECT url_id FROM selecao_download") == [(url,)]


def test_falha_no_meio_desfaz_tudo(central, monkeypatch):
    fabrica, consultar = central
    vazio = _contagens(consultar)
    original = J._alvo_central

    def falha(etapa, alvo, mapa):
        if etapa == "triagem_escopo":
            raise RuntimeError("falhou no meio")
        return original(etapa, alvo, mapa)
    monkeypatch.setattr(J, "_alvo_central", falha)
    with pytest.raises(RuntimeError):
        _enviar(fabrica, pacote())
    assert _contagens(consultar) == vazio


def test_pacote_e_json_puro(local):
    p = local.pacote_da_execucao(_runs(local)[0])
    assert json.loads(json.dumps(p)) == p and copy.deepcopy(p) == p


def test_reenvio_com_linha_filha_nova_aponta_para_o_pai_ja_enviado(local, central):
    fabrica, consultar = central
    ordem = _runs(local)
    run = next(r for r in ordem if local.conn.execute("SELECT 1 FROM classificacoes WHERE run_id = ?", (r,)).fetchone())
    for r in ordem[:ordem.index(run) + 1]:
        _enviar(fabrica, _pacote_json(local, r))
    kid = local.conn.execute("SELECT MIN(classificacao_id) FROM classificacoes WHERE run_id = ?", (run,)).fetchone()[0]
    local.conn.execute("INSERT INTO achados (classificacao_id, uf, tecnologia, evidencia, confianca) VALUES (?, 'SP', 'drones', "
                       "'achado novo depois do envio', 'alta')", (kid,))
    local.conn.commit()
    rel = _enviar(fabrica, _pacote_json(local, run))
    assert rel["achados"]["novas"] == 1 and sum(v["novas"] for v in rel.values()) == 1
    central_kid = consultar("SELECT id_central FROM origem_ids WHERE run_id = ? AND tabela = 'classificacoes' AND id_local = ?",
                            (run, kid))[0][0]
    assert consultar("SELECT classificacao_id FROM achados WHERE evidencia = 'achado novo depois do envio'") == [(central_kid,)]


def test_urls_e_artigos_chegam_com_todos_os_campos(local, central):
    fabrica, consultar = central
    for r in _runs(local):
        _enviar(fabrica, _pacote_json(local, r))
    for t in ("urls", "artigos"):
        chave, natural, colunas = P.COMPARTILHADAS[t]
        resto = [c for c in colunas if c != chave]
        na_nuvem = sorted(tuple(r) for r in consultar(f"SELECT {', '.join(resto)} FROM {t}"))
        naturais = {r[0] for r in na_nuvem}
        no_local = sorted(tuple(r) for r in local.conn.execute(f"SELECT {', '.join(resto)} FROM {t}").fetchall() if r[0] in naturais)
        assert na_nuvem == no_local and len(na_nuvem) > 0, t


def test_ordem_de_envio_nao_muda_nenhuma_view(local, central):
    """Execucoes uma hora depois da outra (a ordem passa a importar) e sem decisoes humanas; enviadas na ordem mais inversa
    possivel (as donas de paginas externas vao antes): as 73 views da nuvem dao as mesmas linhas que as do local."""
    from datetime import datetime, timedelta
    fabrica, consultar = central
    c = local.conn
    runs = [r for (r,) in c.execute("SELECT run_id FROM execucoes ORDER BY iniciado_em, rowid")]
    for horas, run in enumerate(runs):
        for tabela, coluna in (("execucoes", "iniciado_em"), ("chamadas", "requisitado_em"), ("triagem_escopo", "criado_em")):
            for k, v in c.execute(f"SELECT rowid, {coluna} FROM {tabela} WHERE run_id = ?", (run,)).fetchall():
                novo = (datetime.fromisoformat(v) + timedelta(hours=horas)).isoformat(timespec="seconds")
                c.execute(f"UPDATE {tabela} SET {coluna} = ? WHERE rowid = ?", (novo, k))
    c.execute("UPDATE execucoes SET no_relatorio = 1, motivo_exclusao = NULL, excluida_em = NULL")
    c.execute("UPDATE achados SET verificado = 0, status_final = NULL, verificado_por = NULL, verificado_em = NULL, observacao = NULL")
    for t in ("triagem", "triagem_revisoes", "achados_revisoes", "sugestoes", "auditoria_negativos", "buscas_manuais",
              "ocorrencias_manuais", "leitura_referencias"):
        c.execute(f"DELETE FROM {t}")
    c.execute("DELETE FROM artigos WHERE artigo_id NOT IN (SELECT artigo_id FROM ocorrencias) AND artigo_id NOT IN "
              "(SELECT item_id FROM triagem_escopo WHERE fonte = 'artigo')")
    c.commit()
    depende = {r: {e["run_id"] for e in local.pacote_da_execucao(r)["externas"]["paginas"]} for r in runs}
    ordem = []
    while len(ordem) < len(runs):
        ordem.append(next(r for r in reversed(runs) if r not in ordem and depende[r] <= set(ordem)))
    assert ordem != runs
    for r in ordem:
        _enviar(fabrica, _pacote_json(local, r))
    volta = {}
    for run, tabela, id_local, id_central in consultar("SELECT run_id, tabela, id_local, id_central FROM origem_ids"):
        volta.setdefault(tabela, {})[id_central] = id_local
    for t, (chave, natural, _) in P.COMPARTILHADAS.items():
        local_por_natural = {n: i for i, n in c.execute(f"SELECT {chave}, {natural} FROM {t}").fetchall()}
        volta[t] = {i: local_por_natural[n] for i, n in consultar(f"SELECT {chave}, {natural} FROM {t}")}
    coluna_da_tabela = {"achado_id": "achados", "classificacao_id": "classificacoes", "descartado_id": "achados_descartados",
                        "chamada_id": "chamadas", "pagina_id": "paginas", "ocorrencia_id": "ocorrencias",
                        "resultado_id": "resultados_web", "url_id": "urls", "artigo_id": "artigos"}
    views = [v for (v,) in c.execute("SELECT name FROM sqlite_master WHERE type = 'view' ORDER BY name")]
    diferentes = {}
    from collections import Counter

    def normal(x):                                     # como na paridade das views: real inteiro vale o inteiro
        if isinstance(x, float):
            return int(x) if x.is_integer() else round(x, 9)
        return x
    for v in views:
        cur = c.execute(f"SELECT * FROM {v}")
        cols = [d[0] for d in cur.description]
        la = Counter(repr(tuple(normal(x) for x in r)) for r in cur.fetchall())
        idx = [(i, coluna_da_tabela[col]) for i, col in enumerate(cols) if col in coluna_da_tabela]
        lb = Counter()
        for r in consultar(f"SELECT * FROM {v}"):
            r = list(r)
            for i, t in idx:
                if r[i] is not None:
                    r[i] = volta.get(t, {}).get(r[i], r[i])
            lb[repr(tuple(normal(x) for x in r))] += 1
        if la != lb:
            diferentes[v] = (sum((la - lb).values()), sum((lb - la).values()), sorted(la - lb)[:1], sorted(lb - la)[:1])
    assert len(views) == 73 and diferentes == {}


@pytest.mark.postgres
def test_dois_envios_ao_mesmo_tempo_com_url_nova_em_comum(pg_url):
    import threading
    from adaptadores import migrador_postgres as M
    from adaptadores.postgres.conexao import chaves_do_banco, criar_pool
    from adaptadores.repositorio_postgres import RepositorioPostgres
    import psycopg
    M.aplicar(pg_url)
    pool = criar_pool(pg_url, maximo=4)
    chaves = chaves_do_banco(pool)
    a, b = pacote(), pacote()
    b["run_id"] = OUTRA
    for t in P.DA_EXECUCAO:
        for l in b["tabelas"][t[0]]:
            if "run_id" in l:
                l["run_id"] = OUTRA
    erros = []

    def envia(p, usuario):
        try:
            repo = RepositorioPostgres(pool, chaves)
            try:
                repo.juntar_pacote(p, usuario, "2026-10-20T12:00:00+00:00")
            finally:
                repo.fechar()
        except Exception as e:                       # pragma: no cover - o teste mostra qual
            erros.append(repr(e))
    try:
        fios = [threading.Thread(target=envia, args=(a, 1)), threading.Thread(target=envia, args=(b, 2))]
        for f in fios:
            f.start()
        for f in fios:
            f.join(60)
        assert erros == []
        with psycopg.connect(pg_url) as c:
            assert c.execute("SELECT COUNT(*) FROM urls").fetchone()[0] == 1
            assert c.execute("SELECT COUNT(*) FROM execucoes").fetchone()[0] == 2
    finally:
        pool.close()


def _comandos(conn, faz):
    """Os comandos SQL que `faz()` manda pela conexao SQLite."""
    feitos = []
    conn.set_trace_callback(feitos.append)
    try:
        faz()
    finally:
        conn.set_trace_callback(None)
    return feitos


def test_montar_e_reenviar_nao_fazem_uma_consulta_por_linha(local, tmp_path):
    """Montar e reenviar sem mudanca: o numero de comandos e fixo (um por tabela, mais os lotes de 500), nao cresce com as
    linhas. Uma execucao com 2.000 metricas, 1.500 selecoes e 1.200 URLs mostra a diferenca."""
    run = _runs(local)[0]
    c = local.conn
    c.executemany("INSERT INTO metricas_run (run_id, chave, valor) VALUES (?, ?, 1.0)", [(run, f"m{i}") for i in range(2000)])
    c.executemany("INSERT INTO urls (url_normalizada, url_original) VALUES (?, ?)", [(f"https://x.exemplo/{i}", "x") for i in range(1200)])
    novas = [r[0] for r in c.execute("SELECT url_id FROM urls WHERE url_normalizada LIKE 'https://x.exemplo/%'")]
    c.executemany("INSERT INTO selecao_download (run_id, url_id, uf, selecionada, auditoria) VALUES (?, ?, 'SP', 1, 0)",
                  [(run, u) for u in novas[:1500]])
    c.commit()
    pacote = {}
    feitos = _comandos(c, lambda: pacote.update(local.pacote_da_execucao(run)))
    assert len(pacote["tabelas"]["metricas_run"]) >= 2000 and len(pacote["tabelas"]["urls"]) >= 1200
    assert len(feitos) <= 40, len(feitos)
    pacote = json.loads(json.dumps(pacote))
    central = RepositorioSQLite(tmp_path / "central.db")
    try:
        central.juntar_pacote(pacote, 1, "t")
        feitos = _comandos(central.conn, lambda: central.juntar_pacote(pacote, 1, "t"))
    finally:
        central.fechar()
    assert len(feitos) <= 60, len(feitos)


def test_toda_tabela_da_execucao_tem_indice_pelo_run_id(tmp_path):
    RepositorioSQLite(tmp_path / "x.db").fechar()
    con = sqlite3.connect(tmp_path / "x.db")
    sem = []
    for t, _, colunas, _ in P.DA_EXECUCAO:
        if "run_id" not in colunas:
            continue
        primeiras = set()
        for (_, nome, *_resto) in con.execute(f"PRAGMA index_list({t})").fetchall():
            cols = [r[2] for r in con.execute(f"PRAGMA index_info({nome})").fetchall()]
            parcial = con.execute("SELECT sql FROM sqlite_master WHERE name = ?", (nome,)).fetchone()
            if cols and not (parcial and parcial[0] and " WHERE " in parcial[0].upper()):
                primeiras.add(cols[0])
        if "run_id" not in primeiras:
            sem.append(t)
    assert sem == []


def test_paginas_externas_e_correspondencias_em_lote(tmp_path):
    """Uma execucao que usa 301 paginas de outra e grava 600 linhas novas: buscar as paginas e gravar a correspondencia
    sao feitos em lotes (o numero de comandos nao cresce uma por pagina nem uma por linha nova)."""
    origem = pacote()
    origem["run_id"] = OUTRA
    for t in P.DA_EXECUCAO:
        for l in origem["tabelas"][t[0]]:
            if "run_id" in l:
                l["run_id"] = OUTRA
    origem["tabelas"]["paginas"] = [linha("paginas", pagina_id=1000 + i, run_id=OUTRA, url_id=7, chamada_id=10) for i in range(301)]
    origem["tabelas"]["classificacoes"][0]["pagina_id"] = 1000
    central = RepositorioSQLite(tmp_path / "central.db")
    try:
        central.juntar_pacote(origem, 1, "t")
        p = pacote()
        base = dict(p["tabelas"]["classificacoes"][0])
        p["tabelas"]["classificacoes"] = [dict(base, classificacao_id=40 + i, pagina_id=1000 + i) for i in range(301)]
        p["tabelas"]["saldos"] = [linha("saldos", id=5000 + i, run_id=RUN, provedor="serpapi", momento="fim", valor=1.0)
                                  for i in range(300)]
        p["externas"] = {"paginas": [{"pagina_id": 1000 + i, "run_id": OUTRA} for i in range(301)]}
        p["tabelas"]["paginas"] = []
        p["tabelas"]["achados"][0]["classificacao_id"] = 40
        p["tabelas"]["achados_descartados"][0]["classificacao_id"] = 40
        assert P.conferir(p) == []
        feitos = _comandos(central.conn, lambda: central.juntar_pacote(p, 1, "t"))
        selects = [f for f in feitos if f.lstrip().upper().startswith("SELECT")]
        origens = [f for f in feitos if "INSERT INTO origem_ids" in f]
        assert len(selects) <= 40 and len(origens) <= 15, (len(selects), len(origens))   # um lote por tabela com linhas novas
        assert central.conn.execute("SELECT COUNT(DISTINCT pagina_id) FROM classificacoes WHERE run_id = ?", (RUN,)).fetchone()[0] == 301
    finally:
        central.fechar()


# ---------- busca de literatura na web (versao 2) ----------
def _literatura_local(tmp_path):
    """Banco local com duas execucoes da busca de literatura simulada (A e depois B): a URL comum e da primeira."""
    import logging
    from adaptadores.bruto_local import BrutoLocal
    from adaptadores.simulados import BuscaSimulada
    from aplicacao import busca_literatura
    from config import consultas as C, settings as S
    repo = RepositorioSQLite(tmp_path / "literatura_local.db")
    snap = S.snapshot_config()
    runs = []
    logging.disable(logging.CRITICAL)
    try:
        for conjunto in ("A", "B"):
            run = repo.iniciar_execucao("buscar-literatura", snap["hash"], snap["json"], "c")
            busca_literatura.executar(repo, BrutoLocal(tmp_path / "raw"), BuscaSimulada(), run,
                                      [(conjunto, C.CONJUNTOS_LITERATURA[conjunto])], C.FILTROS_LITERATURA_WEB, [], 0)
            repo.finalizar_execucao(run, "concluida")
            runs.append(run)
    finally:
        logging.disable(logging.NOTSET)
    return repo, runs


def test_pacote_leva_a_busca_de_literatura(tmp_path):
    repo, (run_a, _) = _literatura_local(tmp_path)
    try:
        p = repo.pacote_da_execucao(run_a)
    finally:
        repo.fechar()
    assert p["versao"] == 2 and P.conferir(p) == []
    assert len(p["tabelas"]["ocorrencias_web"]) == 15 and len(p["tabelas"]["referencias_web"]) == 11
    assert {l["referencia_id"] for l in p["tabelas"]["ocorrencias_web"]} == {l["referencia_id"] for l in p["tabelas"]["referencias_web"]}
    assert [l["etapa"] for l in p["tabelas"]["chamadas"]] == ["busca_literatura"] * 5


def test_juntar_busca_de_literatura_reaproveita_a_referencia_e_reenvio_nao_muda(central, tmp_path):
    fabrica, consultar = central
    local, runs = _literatura_local(tmp_path)
    try:
        pacotes = [local.pacote_da_execucao(r) for r in runs]
    finally:
        local.fechar()

    def juntar(p):
        repo = fabrica()
        try:
            return repo.juntar_pacote(p, 1, "2026-10-21T12:00:00+00:00")
        finally:
            repo.fechar()
    r1 = juntar(pacotes[0])
    assert r1["referencias_web"] == {"novas": 11, "atualizadas": 0, "iguais": 0}
    assert r1["ocorrencias_web"] == {"novas": 15, "atualizadas": 0, "iguais": 0}
    r2 = juntar(pacotes[1])                                      # a URL comum ja esta na nuvem: so 10 novas
    assert r2["referencias_web"] == {"novas": 10, "atualizadas": 0, "iguais": 1}
    assert r2["ocorrencias_web"]["novas"] == 15
    de_novo = juntar(pacotes[0])
    assert de_novo["referencias_web"] == {"novas": 0, "atualizadas": 0, "iguais": 11}
    assert de_novo["ocorrencias_web"] == {"novas": 0, "atualizadas": 0, "iguais": 15}
    assert consultar("SELECT COUNT(*) FROM referencias_web") == [(21,)]
    assert consultar("SELECT COUNT(*) FROM ocorrencias_web") == [(30,)]
    # cada ocorrencia aponta, na nuvem, para a referencia da mesma URL que tinha no local
    esperado = sorted((o["consulta_id"], o["posicao"], r["url_normalizada"])
                      for p in pacotes for o in p["tabelas"]["ocorrencias_web"]
                      for r in p["tabelas"]["referencias_web"] if r["referencia_id"] == o["referencia_id"])
    obtido = sorted(tuple(l) for l in consultar(
        "SELECT o.consulta_id, o.posicao, r.url_normalizada FROM ocorrencias_web o JOIN referencias_web r "
        "ON r.referencia_id = o.referencia_id"))
    assert obtido == esperado
    assert consultar("SELECT DISTINCT primeira_vez_run FROM referencias_web WHERE url_normalizada = "
                     "'https://exemplo.org/literatura/comum'") == [(runs[0],)]


def test_referencias_chegam_com_todos_os_campos(central, tmp_path):
    fabrica, consultar = central
    local, runs = _literatura_local(tmp_path)
    try:
        for r in runs:
            _enviar(fabrica, local.pacote_da_execucao(r))
        colunas = [c for c in P.COMPARTILHADAS["referencias_web"][2] if c != "referencia_id"]
        no_local = sorted(tuple(l) for l in local.conn.execute(f"SELECT {', '.join(colunas)} FROM referencias_web").fetchall())
    finally:
        local.fechar()
    assert sorted(tuple(l) for l in consultar(f"SELECT {', '.join(colunas)} FROM referencias_web")) == no_local


def test_execucao_da_literatura_so_com_chamadas_que_falharam_vai_e_volta_vazia(central, tmp_path):
    import logging
    from adaptadores.bruto_local import BrutoLocal
    from aplicacao import busca_literatura
    from config import consultas as C, settings as S
    from dominio.modelos import RegistroChamada, RespostaBusca

    class Falha:
        nome = "falsa"

        def buscar(self, consulta, filtros):
            return RespostaBusca([], RegistroChamada(provedor="falsa", operacao="buscar", parametros={}, requisitado_em="t",
                                                     http_status=500, erro="HTTP 500", raw=b"{}"))
    fabrica, consultar = central
    local = RepositorioSQLite(tmp_path / "falhas.db")
    snap = S.snapshot_config()
    try:
        run = local.iniciar_execucao("buscar-literatura", snap["hash"], snap["json"], "c")
        logging.disable(logging.CRITICAL)
        try:
            busca_literatura.executar(local, BrutoLocal(tmp_path / "raw"), Falha(), run, [("A", C.CONJUNTOS_LITERATURA["A"])],
                                      C.FILTROS_LITERATURA_WEB, [], 0)
        finally:
            logging.disable(logging.NOTSET)
        local.finalizar_execucao(run, "concluida")
        p = local.pacote_da_execucao(run)
    finally:
        local.fechar()
    assert P.conferir(p) == []
    assert (len(p["tabelas"]["ocorrencias_web"]), len(p["tabelas"]["referencias_web"]), len(p["tabelas"]["chamadas"])) == (0, 0, 5)
    _enviar(fabrica, p)
    assert consultar("SELECT COUNT(*), SUM(sucesso) FROM chamadas WHERE etapa = 'busca_literatura'") == [(5, 0)]


def test_referencia_que_ja_esta_na_nuvem_nao_muda_com_outro_envio(central, tmp_path):
    """Dois computadores acham a mesma URL normalizada com outra URL original: a linha da nuvem fica como chegou primeiro."""
    fabrica, consultar = central
    pacotes = []
    for n, (pasta, original) in enumerate((("um", "https://www.exemplo.org/a?utm_source=x"), ("dois", "https://exemplo.org/a/"))):
        repo = RepositorioSQLite(tmp_path / f"{pasta}.db")
        try:
            run = repo.iniciar_execucao("buscar-literatura", "h", "{}", "c")
            from aplicacao.comum import registrar_chamada
            from dominio.modelos import RegistroChamada, ResultadoWeb
            reg = RegistroChamada(provedor="falsa", operacao="buscar", parametros={}, requisitado_em="t", http_status=200)
            chamada, _ = registrar_chamada(repo, None, run, "busca_literatura", "consulta_literatura", "LA1", f"k{n}", reg, [])
            repo.salvar_referencias_web(chamada, run, "A", "LA1", [ResultadoWeb(original, "t", "s", None, 1)])
            repo.confirmar()
            pacotes.append((run, repo.pacote_da_execucao(run)))
        finally:
            repo.fechar()
    _enviar(fabrica, pacotes[0][1])
    _enviar(fabrica, pacotes[1][1])
    assert consultar("SELECT url_normalizada, url_original, primeira_vez_run FROM referencias_web") == [
        ("https://exemplo.org/a", "https://www.exemplo.org/a?utm_source=x", pacotes[0][0])]
    assert consultar("SELECT COUNT(*), COUNT(DISTINCT referencia_id) FROM ocorrencias_web") == [(2, 1)]


def test_juntar_referencias_em_lotes_sem_leitura_por_linha(tmp_path):
    """600 referencias e 600 ocorrencias: as leituras sao por lote; so a insercao de cada linha nova e uma por linha
    (o numero novo de cada uma e preciso para o mapa)."""
    p = pacote()
    T(p)["referencias_web"] = [linha("referencias_web", referencia_id=i, url_normalizada=f"https://e.org/{i}", url_original=f"https://e.org/{i}",
                                     dominio="e.org", primeira_vez_run=RUN, primeira_vez_em="t") for i in range(1, 601)]
    T(p)["ocorrencias_web"] = [linha("ocorrencias_web", ocorrencia_id=1000 + i, chamada_id=13, run_id=RUN, conjunto="A", consulta_id="LA1",
                                     referencia_id=i, posicao=i) for i in range(1, 601)]
    assert P.conferir(p) == []
    caminho = tmp_path / "central_lotes.db"
    RepositorioSQLite(caminho).fechar()

    def enviar_contando():
        repo = RepositorioSQLite(caminho)
        comandos = []
        repo.conn.set_trace_callback(comandos.append)
        try:
            repo.juntar_pacote(copy.deepcopy(p), 1, "t")
        finally:
            repo.conn.set_trace_callback(None)
            repo.fechar()
        selects = [c for c in comandos if c.lstrip().upper().startswith("SELECT")]
        return selects, [c for c in comandos if c.startswith("INSERT INTO referencias_web")], \
            [c for c in comandos if c.startswith("INSERT INTO ocorrencias_web")]
    selects, ins_ref, ins_oc = enviar_contando()
    assert len(ins_ref) == 600 and len(ins_oc) == 600
    assert len(selects) <= 40                                       # leituras por lote, nao por linha (sem lote: mais de 600)
    selects, ins_ref, ins_oc = enviar_contando()                    # reenvio: nada novo
    assert (len(ins_ref), len(ins_oc)) == (0, 0) and len(selects) <= 40
