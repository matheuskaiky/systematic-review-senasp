"""Leituras da análise RG5 (adaptadores/leitura_termos_cobertura.py): banco montado a mão com o esquema real, banco de
demonstração, banco vazio e banco antigo sem tabelas. Só leitura: nenhum teste chama API."""
import json
import shutil
import sqlite3
from types import SimpleNamespace

import pytest

import painel_demo
from adaptadores.leitura_sqlite import LeituraPainelSQLite
from adaptadores.leitura_termos_cobertura import LeituraTermosCobertura
from adaptadores.repositorio_sqlite import RepositorioSQLite

METODOS = [("analise_cobertura_termos", ()), ("analise_redundancia_termos", ()), ("analise_redundancia_termos", (2,)),
           ("analise_cobertura_incremental", ()), ("analise_cobertura_incremental", (True,)),
           ("analise_cobertura_se_mantidos", (["T01", "T99"],)), ("analise_cobertura_web", ())]


# o mixin ja faz parte de LeituraPainelSQLite (adaptadores/leitura_sqlite.py): o teste usa a classe real
Leitura = LeituraPainelSQLite
assert issubclass(LeituraPainelSQLite, LeituraTermosCobertura)



def _sql(banco, sql, args=()):
    conn = sqlite3.connect(banco)
    try:
        r = conn.execute(sql, args).fetchall()
        conn.commit()
        return r
    finally:
        conn.close()


TERMOS = [{"id": "T01", "query": '"reconhecimento facial"', "idioma": "pt", "grupo": "g1", "pai": ""},
          {"id": "T02", "query": '"biometria facial"', "idioma": "pt", "grupo": "g1", "pai": ""},
          {"id": "T03", "query": '"facial recognition"', "idioma": "en", "grupo": "g2", "pai": ""},
          {"id": "T04", "query": '"gunshot detection"', "idioma": "en", "grupo": "g2", "pai": ""}]


class Banco:
    """Banco com o esquema real, uma execução no relatório e linhas acrescentadas a mão."""

    def __init__(self, caminho, termos=TERMOS, modelo=None):
        self.caminho = caminho
        if modelo:                                            # copia o esquema já criado (criar o esquema leva ~1 s)
            shutil.copy(modelo, caminho)
        else:
            RepositorioSQLite(caminho).fechar()
        self.run = "R1"
        _sql(caminho, "INSERT INTO execucoes (run_id, iniciado_em, config_hash, config_json, no_relatorio) VALUES (?,?,?,?,1)",
             (self.run, "2026-01-01T00:00:00", "h", json.dumps({"termos": termos})))
        _sql(caminho, "INSERT INTO execucoes (run_id, iniciado_em, config_hash, config_json, no_relatorio) VALUES (?,?,?,?,1)",
             ("R0", "2025-12-31T00:00:00", "h", "{}"))                # execução anterior (veredito antigo)
        self._n = 0

    def chamada(self, etapa, provedor, alvo, pagina=None, sucesso=1, custo=None, run=None):
        self._n += 1
        _sql(self.caminho, """INSERT INTO chamadas (run_id, etapa, provedor, alvo_id, pagina, parametros_json, chave_idempotencia,
                                  requisitado_em, sucesso, custo_usd) VALUES (?,?,?,?,?,?,?,?,?,?)""",
             (run or self.run, etapa, provedor, alvo, pagina, "{}", f"k{self._n}", "2026-01-01T00:00:00", sucesso, custo))
        return _sql(self.caminho, "SELECT MAX(chamada_id) FROM chamadas")[0][0]

    def artigo(self, nome):
        _sql(self.caminho, "INSERT INTO artigos (chave_dedup, titulo) VALUES (?,?)", (nome, nome))
        return _sql(self.caminho, "SELECT MAX(artigo_id) FROM artigos")[0][0]

    def ocorrencia(self, chamada, artigo, termo, posicao):
        _sql(self.caminho, "INSERT INTO ocorrencias (chamada_id, artigo_id, termo_id, run_id, posicao) VALUES (?,?,?,?,?)",
             (chamada, artigo, termo, self.run, posicao))

    def veredito(self, fonte, item, status, uf="", valido=1, run=None):
        _sql(self.caminho, """INSERT INTO triagem_escopo (run_id, fonte, item_id, uf, status, valido, criado_em)
                              VALUES (?,?,?,?,?,?,?)""", (run or self.run, fonte, item, uf, status, valido, "2026-01-01T00:00:00"))

    def url(self, n):
        _sql(self.caminho, "INSERT INTO urls (url_normalizada, url_original, dominio, fonte_oficial) VALUES (?,?,?,1)",
             (f"https://x.gov.br/{n}", f"https://x.gov.br/{n}", "x.gov.br"))
        return _sql(self.caminho, "SELECT MAX(url_id) FROM urls")[0][0]

    def resultado_web(self, chamada, consulta, url, posicao, tecnologia, perfil, uf="PI", cidade=None):
        _sql(self.caminho, """INSERT INTO resultados_web (chamada_id, run_id, consulta_id, uf, tecnologia, perfil, url_id, posicao, cidade)
                              VALUES (?,?,?,?,?,?,?,?,?)""", (chamada, self.run, consulta, uf, tecnologia, perfil, url, posicao, cidade))


@pytest.fixture(scope="module")
def modelo_vazio(tmp_path_factory):
    caminho = tmp_path_factory.mktemp("modelo_cobertura") / "modelo.db"
    RepositorioSQLite(caminho).fechar()
    return caminho


@pytest.fixture
def vazio(tmp_path, modelo_vazio):
    destino = tmp_path / "vazio.db"
    shutil.copy(modelo_vazio, destino)
    return destino


@pytest.fixture(scope="module")
def banco_base(tmp_path_factory, modelo_vazio):
    """Literatura: T01 (a1..a4, 2 páginas), T02 (a3, a5, a9), T03 (a6, a1, a7), T04 sem resultado. Web: M01 e M02 x rec e pla."""
    b = Banco(tmp_path_factory.mktemp("banco_cobertura") / "cob.db", modelo=modelo_vazio)
    a = {n: b.artigo(f"a{n}") for n in range(1, 10)}
    c1, c1b = b.chamada("busca_academica", "serpapi_scholar", "T01", 1), b.chamada("busca_academica", "serpapi_scholar", "T01", 2)
    c2, c3, c4 = (b.chamada("busca_academica", "serpapi_scholar", t, 1) for t in ("T02", "T03", "T04"))
    for artigo, termo, ch, pos in [(1, "T01", c1, 1), (2, "T01", c1, 2), (3, "T01", c1, 3), (4, "T01", c1b, 4), (3, "T02", c2, 1),
                                   (5, "T02", c2, 2), (9, "T02", c2, 3), (6, "T03", c3, 1), (1, "T03", c3, 2), (7, "T03", c3, 3)]:
        b.ocorrencia(ch, a[artigo], termo, pos)
    b.veredito("artigo", a[2], "excluido", run="R0")       # veredito antigo: o último (elegível) é o que vale
    for n, st in [(1, "elegivel"), (2, "elegivel"), (3, "excluido"), (4, "quarentena"), (5, "elegivel"), (6, "elegivel"), (7, "excluido")]:
        b.veredito("artigo", a[n], st)
    b.veredito("artigo", a[9], "elegivel", valido=0)       # resposta inválida: não conta como triado
    b.veredito("artigo", a[8], "elegivel")                 # artigo sem termo (manual): fora da análise
    b.chamada("busca_academica", "serpapi_scholar", "T02", 2, sucesso=0)       # falha não gasta crédito
    u = {n: b.url(n) for n in range(1, 6)}
    ch = {k: b.chamada("busca_web", "perplexity_search", k, custo=0.005) for k in ("M01-PI-rec", "M02-PI-rec", "M01-PI-pla", "M02-PI-pla")}
    b.chamada("busca_web", "perplexity_search", "M11-PI-cidade-rec", custo=0.5)              # municipal: fora do custo estadual
    for consulta, urls in [("M01-PI-rec", [1, 2, 3]), ("M02-PI-rec", [2, 4]), ("M01-PI-pla", [5]), ("M02-PI-pla", [1])]:
        modelo, tec = consulta.split("-")[0], consulta.split("-")[2]
        for i, n in enumerate(urls, 1):
            b.resultado_web(ch[consulta], consulta, u[n], i, tec, "oficial" if modelo == "M01" else "geral")
    b.resultado_web(ch["M01-PI-rec"], "M11-PI-cidade-rec", u[5], 1, "rec", "oficial", cidade="Cidade")      # municipal: fora
    for n, st in [(1, "elegivel"), (2, "elegivel"), (3, "excluido"), (4, "elegivel"), (5, "quarentena")]:
        b.veredito("web", u[n], st, uf="PI")
    return b


@pytest.fixture
def banco(banco_base, tmp_path):
    """Cópia do banco montado, para os testes que alteram o banco."""
    destino = tmp_path / "cob.db"
    shutil.copy(banco_base.caminho, destino)
    return SimpleNamespace(caminho=destino)


@pytest.fixture
def L(banco):
    return Leitura(banco.caminho)


# ============================== formas e robustez ==============================
@pytest.mark.parametrize("nome,args", METODOS)
def test_metodos_devolvem_json_no_banco_montado(L, nome, args):
    json.dumps(getattr(L, nome)(*args))


@pytest.mark.parametrize("nome,args", METODOS)
def test_metodos_em_banco_vazio(vazio, nome, args):
    r = getattr(Leitura(vazio), nome)(*args)
    json.dumps(r)
    assert not any(v for k, v in r.items() if k in ("n_artigos", "n_elegiveis", "universo", "n_resultados", "tem_dados", "tem_triagem"))


@pytest.mark.parametrize("nome,args", METODOS)
def test_metodos_em_banco_antigo_sem_tabelas(tmp_path, nome, args):
    antigo = tmp_path / "antigo.db"
    sqlite3.connect(antigo).close()
    json.dumps(getattr(Leitura(antigo), nome)(*args))
    assert Leitura(antigo).analise_ganho_combinacoes() == []


def test_banco_sem_triagem_de_escopo_traz_resultados_mas_nao_elegiveis(banco):
    _sql(banco.caminho, "DROP TABLE triagem_escopo")
    r = Leitura(banco.caminho).analise_cobertura_termos()
    assert r["tem_triagem"] is False and r["n_artigos"] == 8 and r["n_elegiveis"] == 0 and r["n_triados"] == 0
    assert all(t["precisao"] is None for t in r["por_termo"])
    assert Leitura(banco.caminho).analise_cobertura_incremental()["universo"] == 0


# ============================== 1. rendimento por termo ==============================
def test_cobertura_termos_numeros_a_mao(L):
    r = L.analise_cobertura_termos()
    assert (r["n_termos"], r["n_termos_com_resultado"], r["n_artigos"]) == (4, 3, 8)       # a8 não tem termo
    assert (r["n_triados"], r["n_sem_veredito"], r["n_elegiveis"], r["n_quarentena"], r["n_excluidos"]) == (7, 1, 4, 1, 2)
    assert r["creditos_total"] == 5 and r["tem_triagem"] is True
    t = {x["termo_id"]: x for x in r["por_termo"]}
    assert [x["termo_id"] for x in r["por_termo"]] == ["T01", "T02", "T03", "T04"]
    assert (t["T01"]["n_resultados"], t["T01"]["n_elegiveis"], t["T01"]["n_quarentena"], t["T01"]["n_excluidos"]) == (4, 2, 1, 1)
    assert t["T01"]["precisao"] == 0.5 and t["T01"]["creditos"] == 2 and t["T01"]["elegiveis_por_credito"] == 1.0
    assert t["T01"]["n_elegiveis_unicos"] == 1 and t["T01"]["pct_elegiveis_de_outros"] == 50.0
    assert t["T01"]["posicao_media_elegiveis"] == 1.5 and t["T01"]["idioma"] == "pt" and t["T01"]["grupo"] == "g1"
    assert (t["T02"]["n_resultados"], t["T02"]["n_triados"], t["T02"]["n_elegiveis"]) == (3, 2, 1)     # a9 sem veredito válido
    assert t["T03"]["n_elegiveis"] == 2 and t["T03"]["n_elegiveis_unicos"] == 1
    assert t["T04"]["n_resultados"] == 0 and t["T04"]["precisao"] is None and t["T04"]["creditos"] == 1     # gastou 1 crédito
    assert t["T02"]["creditos"] == 1                                                                # a chamada que falhou não conta


def test_cobertura_termos_ultimo_veredito_e_o_que_vale(L, banco):
    t = {x["termo_id"]: x for x in L.analise_cobertura_termos()["por_termo"]}
    assert t["T01"]["n_elegiveis"] == 2                                                              # a2 foi excluído, depois elegível


def test_cobertura_termos_por_idioma_e_por_faixa(L):
    r = L.analise_cobertura_termos()
    i = {x["achado_por"]: x for x in r["por_idioma"]}
    assert (i["apenas_pt"]["n_artigos"], i["apenas_pt"]["n_triados"], i["apenas_pt"]["n_elegiveis"]) == (5, 4, 2)
    assert (i["apenas_en"]["n_artigos"], i["apenas_en"]["n_elegiveis"]) == (2, 1)
    assert (i["ambos"]["n_artigos"], i["ambos"]["n_elegiveis"]) == (1, 1)
    f = {(x["grupo"], x["faixa"]): x for x in r["por_faixa_grupo"]}
    assert f[("g1", 1)]["n_triados"] == 5 and f[("g1", 1)]["n_elegiveis"] == 3                      # a1..a5 (a9 sem veredito)
    assert f[("g2", 1)]["n_triados"] == 3 and f[("g2", 1)]["n_elegiveis"] == 2


# ============================== 2. redundância ==============================
def test_redundancia_com_minimo_baixo(L):
    r = L.analise_redundancia_termos(minimo_elegiveis=1)
    assert r["termos"] == ["T01", "T02", "T03"] and r["matriz"][0][2] == round(1 / 3, 4)           # T01 e T03 dividem a1
    assert r["pares"][0]["termo_a"] == "T01" and r["pares"][0]["termo_b"] == "T03" and r["pares"][0]["n_em_comum"] == 1
    assert r["pares"][0]["n_uniao"] == 3
    c = {x["termo_id"]: x for x in r["contidos"]}
    assert c["T02"]["contido_em"] is None and c["T01"]["contido_em"] == "T03" and c["T01"]["pct_contido"] == 50.0


def test_redundancia_minimo_padrao_deixa_todos_de_fora(L):
    r = L.analise_redundancia_termos()
    assert r["minimo_elegiveis"] == 5 and r["termos"] == [] and r["matriz"] == [] and r["n_termos_fora"] == 3


# ============================== 3. cobertura incremental ==============================
def test_incremental_ordem_guloso_marcos_e_dispensaveis(L):
    r = L.analise_cobertura_incremental()
    assert r["base"] == "elegiveis" and r["universo"] == 4 and r["n_termos"] == 4 and r["creditos_total"] == 5
    assert [p["termo_id"] for p in r["passos"]] == ["T03", "T02", "T01", "T04"]                      # desempate por créditos
    assert [p["ganho"] for p in r["passos"]] == [2, 1, 1, 0]
    assert [p["acumulado"] for p in r["passos"]] == [2, 3, 4, 4]
    assert [p["creditos_acumulados"] for p in r["passos"]] == [1, 2, 4, 5]
    assert r["passos"][0]["query"] == '"facial recognition"' and r["passos"][0]["idioma"] == "en" and r["passos"][0]["n_elegiveis"] == 2
    assert {m["percentual"]: m["n_chaves"] for m in r["marcos"]} == {80: 3, 90: 3, 95: 3, 100: 3}
    assert [d["termo_id"] for d in r["dispensaveis"]] == ["T04"] and r["dispensaveis"][0]["sem_resultados"] is True
    assert r["n_dispensaveis_sem_elegiveis"] == 1 and r["creditos_dispensaveis"] == 1
    assert {u["termo_id"]: u["n_unicos"] for u in r["com_unicos"]} == {"T01": 1, "T02": 1, "T03": 1}


def test_incremental_com_quarentena_muda_o_universo(L):
    r = L.analise_cobertura_incremental(incluir_quarentena=True)
    assert r["base"] == "elegiveis_e_quarentena" and r["universo"] == 5            # + a4 (quarentena)


def test_cobertura_se_mantidos(L):
    r = L.analise_cobertura_se_mantidos(["T03", "T02", "T99"])
    assert r["n_mantidos"] == 2 and r["desconhecidos"] == ["T99"] and r["universo"] == 4
    assert r["n_cobertos"] == 3 and r["pct_cobertos"] == 75.0
    assert r["creditos_mantidos"] == 2 and r["creditos_total"] == 5 and r["creditos_economizados"] == 3
    assert r["termos_descartados"] == ["T01", "T04"]
    assert L.analise_cobertura_se_mantidos([])["pct_cobertos"] == 0.0


# ============================== 4. web ==============================
def test_cobertura_web_numeros_a_mao(L):
    r = L.analise_cobertura_web()
    assert r["tem_dados"] and r["tem_triagem"]
    assert (r["n_resultados"], r["n_triados"], r["n_elegiveis"], r["n_quarentena"]) == (5, 5, 3, 1)    # o resultado municipal fica de fora
    assert r["custo_total_usd"] == 0.02                                                            # 4 buscas estaduais; a municipal não entra
    c = {x["chave"]: x for x in r["por_celula"]}
    assert set(c) == {"rec|M01", "rec|M02", "pla|M01", "pla|M02"}
    assert (c["rec|M01"]["n_resultados"], c["rec|M01"]["n_elegiveis"], c["rec|M01"]["precisao"]) == (3, 2, round(2 / 3, 4))
    assert c["rec|M01"]["perfil"] == "oficial" and c["rec|M02"]["perfil"] == "geral"
    assert c["rec|M02"]["n_elegiveis_unicos"] == 1 and c["rec|M01"]["n_elegiveis_unicos"] == 0
    assert c["pla|M01"]["n_elegiveis"] == 0 and c["pla|M01"]["n_quarentena"] == 1 and c["pla|M01"]["precisao"] == 0.0
    assert c["rec|M01"]["custo_usd"] == 0.005 and c["rec|M01"]["n_consultas"] == 1 and c["rec|M01"]["elegiveis_por_usd"] == 400.0
    m = {x["modelo_id"]: x for x in r["por_modelo"]}
    assert (m["M01"]["n_resultados"], m["M01"]["n_elegiveis"], m["M02"]["n_elegiveis"]) == (4, 2, 3)
    assert m["M02"]["n_elegiveis_unicos"] == 1 and m["M01"]["custo_usd"] == 0.01


def test_cobertura_web_sobreposicao_entre_modelos(L):
    s = L.analise_cobertura_web()["sobreposicao_modelos"]
    assert len(s) == 1 and (s[0]["modelo_a"], s[0]["modelo_b"]) == ("M01", "M02")
    assert (s[0]["n_a"], s[0]["n_b"], s[0]["n_em_comum"], s[0]["n_uniao"]) == (2, 3, 2, 3)
    assert s[0]["jaccard"] == round(2 / 3, 4) and (s[0]["so_a"], s[0]["so_b"]) == (0, 1)
    assert s[0]["jaccard_resultados"] == round(2 / 5, 4)                                            # {u1,u2} em comum, {u1..u5} na união


def test_cobertura_web_incremental(L):
    inc = L.analise_cobertura_web()["incremental"]
    assert inc["universo"] == 3 and inc["n_chaves"] == 4
    assert [p["chave"] for p in inc["passos"]] == ["rec|M01", "rec|M02", "pla|M02", "pla|M01"]       # empate: custo igual, depois nome
    assert [p["ganho"] for p in inc["passos"]] == [2, 1, 0, 0] and inc["passos"][-1]["acumulado"] == 3
    assert inc["passos"][1]["custo_acumulado_usd"] == 0.01 and inc["passos"][0]["tecnologia"] == "rec" and inc["passos"][0]["modelo_id"] == "M01"
    assert {d["chave"] for d in inc["dispensaveis"]} == {"pla|M01", "pla|M02"}
    assert {u["chave"] for u in inc["com_unicos"]} == {"rec|M02"}
    assert {m["percentual"]: m["n_chaves"] for m in inc["marcos"]} == {80: 2, 90: 2, 95: 2, 100: 2}


def test_cobertura_web_sem_resultados_mas_com_buscas_conta_o_custo(tmp_path, modelo_vazio):
    b = Banco(tmp_path / "w.db", modelo=modelo_vazio)
    b.chamada("busca_web", "perplexity_search", "M01-PI-rec", custo=0.005)
    r = Leitura(b.caminho).analise_cobertura_web()
    assert r["tem_dados"] is False and r["custo_total_usd"] == 0.005 and r["por_celula"][0]["chave"] == "rec|M01"
    assert r["por_celula"][0]["n_resultados"] == 0 and r["por_celula"][0]["precisao"] is None


# ============================== 5. combinações ==============================
def test_ganho_combinacoes_vazio_sem_termo_composto(L):
    assert L.analise_ganho_combinacoes() == []


def test_ganho_combinacoes_com_termo_composto(tmp_path, modelo_vazio):
    termos = TERMOS + [{"id": "T05", "query": '"reconhecimento facial" AND (polícia)', "idioma": "pt", "grupo": "g1", "pai": "T01"}]
    b = Banco(tmp_path / "comp.db", termos, modelo_vazio)
    a = {n: b.artigo(f"a{n}") for n in range(1, 6)}
    c1, c5 = b.chamada("busca_academica", "serpapi_scholar", "T01", 1), b.chamada("busca_academica", "serpapi_scholar", "T05", 1)
    for n, termo, ch in [(1, "T01", c1), (2, "T01", c1), (3, "T01", c1), (1, "T05", c5), (4, "T05", c5)]:
        b.ocorrencia(ch, a[n], termo, n)
    for n, st in [(1, "elegivel"), (2, "excluido"), (3, "elegivel"), (4, "elegivel")]:
        b.veredito("artigo", a[n], st)
    r = Leitura(b.caminho).analise_ganho_combinacoes()
    assert len(r) == 1 and r[0]["termo_composto"] == "T05" and r[0]["termo_pai"] == "T01"
    assert r[0]["so_no_composto"] == 1 and r[0]["so_no_pai"] == 2                                   # colunas da view
    assert (r[0]["n_elegiveis_composto"], r[0]["n_elegiveis_pai"], r[0]["elegiveis_em_comum"]) == (2, 2, 1)
    assert (r[0]["elegiveis_so_no_composto"], r[0]["elegiveis_so_no_pai"]) == (1, 1)
    assert r[0]["creditos_composto"] == 1 and r[0]["elegiveis_novos_por_credito"] == 1.0
    cob = Leitura(b.caminho).analise_cobertura_termos()
    assert {t["termo_id"]: t["pai"] for t in cob["por_termo"]}["T05"] == "T01"


# ============================== banco de demonstração ==============================
@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    return painel_demo.construir(tmp_path_factory.mktemp("demo_cobertura"))


def test_demo_sem_triagem_de_escopo_e_com_triagem(demo, tmp_path):
    banco = tmp_path / "demo.db"
    shutil.copy(demo, banco)
    L = Leitura(banco)
    sem = L.analise_cobertura_termos()
    esperado = _sql(banco, "SELECT COUNT(DISTINCT artigo_id) FROM r_ocorrencias")[0][0]
    assert sem["n_artigos"] == esperado > 0 and sem["tem_triagem"] is False and sem["n_elegiveis"] == 0
    assert sem["creditos_total"] == _sql(banco, "SELECT COUNT(*) FROM r_chamadas WHERE etapa='busca_academica' AND sucesso=1")[0][0]
    # veredito para todos: pares elegíveis, ímpares excluídos
    for (aid,) in _sql(banco, "SELECT artigo_id FROM artigos"):
        _sql(banco, """INSERT INTO triagem_escopo (run_id, fonte, item_id, uf, status, valido, criado_em) SELECT run_id, 'artigo', ?, '', ?, 1, 'x'
                       FROM execucoes LIMIT 1""", (aid, "elegivel" if aid % 2 == 0 else "excluido"))
    r = L.analise_cobertura_termos()
    assert r["tem_triagem"] is True and r["n_triados"] == esperado
    assert r["n_elegiveis"] == _sql(banco, "SELECT COUNT(DISTINCT artigo_id) FROM r_ocorrencias WHERE artigo_id % 2 = 0")[0][0]
    assert sum(t["n_resultados"] for t in r["por_termo"]) == _sql(banco, "SELECT COUNT(DISTINCT termo_id || '|' || artigo_id) FROM r_ocorrencias")[0][0]
    inc = L.analise_cobertura_incremental()
    assert inc["universo"] == r["n_elegiveis"] and inc["passos"][-1]["acumulado"] == inc["universo"]
    json.dumps([r, inc, L.analise_redundancia_termos(1), L.analise_cobertura_web(), L.analise_ganho_combinacoes()])


def test_demo_web_confere_com_o_banco(demo):
    r = Leitura(demo).analise_cobertura_web()
    esperado = _sql(demo, "SELECT COUNT(DISTINCT url_id || '|' || uf) FROM r_resultados_web WHERE cidade IS NULL")[0][0]
    assert r["tem_dados"] is True and r["n_resultados"] == esperado and r["tem_triagem"] is False
    assert {m["modelo_id"] for m in r["por_modelo"]} >= {"M01", "M02"}
