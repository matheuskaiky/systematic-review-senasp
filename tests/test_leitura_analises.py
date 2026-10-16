"""Leituras da pagina /analises (adaptadores/leitura_analises.py): formas devolvidas, contagens contra o banco de demonstracao,
casos montados a mao (fornecedores, bloqueios, falsa exclusao, faixas de texto), banco vazio e banco sem tabelas."""
import json
import shutil
import sqlite3

import pytest

import painel_demo
from adaptadores.leitura_analises import REGIAO_DA_UF, REGIOES
from adaptadores.leitura_sqlite import LeituraPainelSQLite
from adaptadores.repositorio_sqlite import RepositorioSQLite

METODOS = [
    ("analise_maturidade_uf_tecnologia", ()), ("analise_maturidade_uf_tecnologia", (True,)), ("analise_lgpd_por_tecnologia", ()),
    ("analise_fornecedores", ()), ("analise_funil_por_provedor", ()), ("analise_retorno_por_posicao", ("web",)),
    ("analise_retorno_por_posicao", ("scholar",)), ("analise_literatura_temporal", ()), ("analise_multitermo", ()),
    ("analise_calibracao_confianca", ()), ("analise_falsa_exclusao", ()), ("analise_opacidade_dominios", ()),
    ("analise_saturacao", ()), ("analise_calibracao_tokens", ()), ("analise_tamanho_texto_achados", ()),
    ("analise_termos_triagem_escopo", ()), ("analise_termos_triagem_escopo", ("web",)), ("analise_resumo", ()),
]


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    return painel_demo.construir(tmp_path_factory.mktemp("demo_analises"))


@pytest.fixture
def copia(demo, tmp_path):
    """Copia do banco de demonstracao, para os testes que acrescentam linhas a mao."""
    destino = tmp_path / "copia.db"
    shutil.copy(demo, destino)
    return destino


@pytest.fixture(scope="module")
def L(demo):
    return LeituraPainelSQLite(demo)


def _sql(banco, sql, args=()):
    conn = sqlite3.connect(banco)
    try:
        r = conn.execute(sql, args).fetchall()
        conn.commit()
        return r
    finally:
        conn.close()


def _run(banco):
    return _sql(banco, "SELECT run_id FROM execucoes WHERE no_relatorio = 1 ORDER BY run_id LIMIT 1")[0][0]


def _te(banco, fonte, item_id, status, uf="", valido=1, categoria=None, termos=None, provedor="serpapi_scholar", run=None):
    run = run or _run(banco)
    _sql(banco, """INSERT INTO triagem_escopo (run_id, fonte, item_id, uf, provedor, termos_consulta, status, status_bruto, valido,
                       categoria_motivo, prompt_versao, criado_em) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
         (run, fonte, item_id, uf, provedor, json.dumps(termos or []), status, status, valido, categoria, "t2", "2026-01-01T00:00:00"))


# ---------- banco minimo montado a mao ----------
class Minimo:
    """Banco com o schema e uma execucao no relatorio; acrescenta achados e downloads linha a linha."""

    def __init__(self, caminho):
        self.caminho = caminho
        RepositorioSQLite(caminho).fechar()
        self.run = "R1"
        _sql(caminho, "INSERT INTO execucoes (run_id, iniciado_em, config_hash, config_json, no_relatorio) VALUES (?,?,?,?,1)",
             (self.run, "2026-01-01T00:00:00", "h", "{}"))
        self._n = 0

    def chamada(self, etapa, provedor, alvo, sucesso=1, http=None, erro=None, tokens=None, custo=None):
        self._n += 1
        _sql(self.caminho, """INSERT INTO chamadas (run_id, etapa, provedor, alvo_id, parametros_json, chave_idempotencia, requisitado_em,
                                  http_status, sucesso, erro, tokens_entrada, custo_usd) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
             (self.run, etapa, provedor, str(alvo), "{}", f"k{self._n}", "2026-01-01T00:00:00", http, sucesso, erro, tokens, custo))
        return _sql(self.caminho, "SELECT MAX(chamada_id) FROM chamadas")[0][0]

    def url(self, dominio):
        _sql(self.caminho, "INSERT INTO urls (url_normalizada, url_original, dominio, fonte_oficial) VALUES (?,?,?,1)",
             (f"https://{dominio}/{self._n}", f"https://{dominio}/{self._n}", dominio))
        self._n += 1
        return _sql(self.caminho, "SELECT MAX(url_id) FROM urls")[0][0]

    def achado(self, uf, tecnologia, status, fornecedor=None, verificado=0, final=None, confianca="alta", original=None,
               lgpd=0, cita_lgpd=0, chars=1000, tokens=400, json_valido=1, truncado=0, n_achados=1):
        cid = self.chamada("classificacao", "gemini", f"{self._n}:{uf}", tokens=tokens)
        url = self.url("x.gov.br")
        _sql(self.caminho, """INSERT INTO classificacoes (chamada_id, run_id, url_id, uf, origem_texto, texto_truncado, n_chars_enviados,
                                  classificador, relevante, json_valido, n_achados) VALUES (?,?,?,?,?,?,?,?,1,?,?)""",
             (cid, self.run, url, uf, "pagina", truncado, chars, "gemini", json_valido, n_achados))
        k = _sql(self.caminho, "SELECT MAX(classificacao_id) FROM classificacoes")[0][0]
        _sql(self.caminho, """INSERT INTO achados (classificacao_id, uf, tecnologia, status_reportado, fornecedor, menciona_lgpd, confianca,
                                  confianca_original, evidencia_cita_lgpd, verificado, status_final) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
             (k, uf, tecnologia, status, fornecedor, lgpd, confianca, original or confianca, cita_lgpd, verificado, final))


@pytest.fixture
def minimo(tmp_path):
    return Minimo(tmp_path / "minimo.db")


# ============================== todos os metodos ==============================
@pytest.mark.parametrize("nome,args", METODOS)
def test_metodos_devolvem_estruturas_json_na_demo(L, nome, args):
    r = getattr(L, nome)(*args)
    assert isinstance(r, dict)
    json.dumps(r)


@pytest.mark.parametrize("nome,args", METODOS)
def test_metodos_em_banco_vazio_nao_falham_e_nao_dividem_por_zero(tmp_path, nome, args):
    vazio = tmp_path / "vazio.db"
    RepositorioSQLite(vazio).fechar()
    r = getattr(LeituraPainelSQLite(vazio), nome)(*args)
    json.dumps(r)
    for chave in ("tem_dados_humanos", "tem_dados_humanos_achados"):
        assert r.get(chave, False) is False


@pytest.mark.parametrize("nome,args", METODOS)
def test_metodos_em_banco_antigo_sem_tabelas_devolvem_vazio(tmp_path, nome, args):
    antigo = tmp_path / "antigo.db"
    sqlite3.connect(antigo).close()
    json.dumps(getattr(LeituraPainelSQLite(antigo), nome)(*args))


def test_fonte_invalida_na_posicao_levanta_erro(L):
    with pytest.raises(ValueError):
        L.analise_retorno_por_posicao("outra")


# ============================== 1. maturidade ==============================
def test_maturidade_demo(L, demo):
    r = L.analise_maturidade_uf_tecnologia()
    esperado = _sql(demo, "SELECT COUNT(*) FROM r_achados WHERE NOT (verificado = 1 AND status_final = 'descartado')")[0][0]
    assert r["base"] == "status_final_ou_reportado" and r["n_achados"] + r["n_ignorados"] == esperado
    assert r["n_verificados"] > 0 and r["tem_dados_humanos"]
    assert sum(c["n_achados"] for c in r["celulas"]) == r["n_achados"]
    for c in r["celulas"]:
        assert c["peso"] == max(r["pesos"][s] for s, n in c["por_status"].items() if n)
        assert c["regiao"] == REGIAO_DA_UF[c["uf"]]
    cont = r["contingencia_regiao_tecnologia"]
    assert cont["regioes"] == list(REGIOES) and len(cont["tabela"]) == 5 and cont["n"] == r["n_achados"] - r["n_sem_regiao"]
    assert len(REGIAO_DA_UF) == 27 and set(REGIAO_DA_UF.values()) == set(REGIOES)


def test_maturidade_somente_confirmados(L, demo):
    r = L.analise_maturidade_uf_tecnologia(True)
    n = _sql(demo, "SELECT COUNT(*) FROM r_achados WHERE verificado = 1 AND COALESCE(status_final, '') <> 'descartado'")[0][0]
    assert r["base"] == "confirmados" and r["n_achados"] + r["n_ignorados"] == n and r["n_verificados"] == r["n_achados"]


def test_maturidade_status_mais_avancado_e_descartado_fora(minimo):
    minimo.achado("PI", "leitura_placas", "licitacao")
    minimo.achado("PI", "leitura_placas", "em_uso", verificado=1, final="piloto")        # a decisao humana vale
    minimo.achado("PI", "leitura_placas", "em_uso", verificado=1, final="descartado")    # nunca entra
    minimo.achado("SP", "reconhecimento_facial", "apenas_citado")
    minimo.achado("SP", "reconhecimento_facial", "status_estranho")
    r = LeituraPainelSQLite(minimo.caminho).analise_maturidade_uf_tecnologia()
    por = {(c["uf"], c["tecnologia"]): c for c in r["celulas"]}
    assert por[("PI", "leitura_placas")]["status_max"] == "piloto" and por[("PI", "leitura_placas")]["n_achados"] == 2
    assert por[("SP", "reconhecimento_facial")]["peso"] == 0
    assert r["n_descartados"] == 1 and r["n_ignorados"] == 1 and r["n_achados"] == 3
    tab = r["contingencia_regiao_tecnologia"]
    assert tab["tabela"][REGIOES.index("Nordeste")][tab["tecnologias"].index("leitura_placas")] == 2
    assert tab["tabela"][REGIOES.index("Sudeste")][tab["tecnologias"].index("reconhecimento_facial")] == 1


# ============================== 2 e 3. LGPD e fornecedores ==============================
def test_lgpd_por_tecnologia(minimo):
    minimo.achado("PI", "leitura_placas", "em_uso", lgpd=1, cita_lgpd=1)
    minimo.achado("PI", "leitura_placas", "em_uso", lgpd=1, cita_lgpd=0)
    minimo.achado("PI", "leitura_placas", "em_uso", verificado=1, final="descartado", cita_lgpd=1)
    minimo.achado("SP", "analise_preditiva", "piloto")
    r = LeituraPainelSQLite(minimo.caminho).analise_lgpd_por_tecnologia()
    por = {t["tecnologia"]: t for t in r["por_tecnologia"]}
    assert por["leitura_placas"]["n_achados"] == 2 and por["leitura_placas"]["n_cita_lgpd"] == 1
    assert por["leitura_placas"]["n_menciona_lgpd"] == 2 and por["leitura_placas"]["pct_cita_lgpd"] == 50.0
    assert por["analise_preditiva"]["pct_cita_lgpd"] == 0.0 and r["n_achados"] == 3 and r["n_verificados"] == 0


def test_lgpd_demo_somas(L, demo):
    r = L.analise_lgpd_por_tecnologia()
    assert r["n_cita_lgpd"] == sum(t["n_cita_lgpd"] for t in r["por_tecnologia"])
    assert r["n_achados"] == _sql(demo, "SELECT COUNT(*) FROM r_achados WHERE NOT (verificado = 1 AND status_final = 'descartado')")[0][0]


def test_fornecedores_normalizacao_leve_e_nao_informado(minimo):
    for forn, uf in (("Axis", "PI"), ("  axis ", "SP"), ("AXIS", "SP"), ("Foo  Bar", "BA"), ("", "BA"), (None, "AC"), ("N/D", "AC")):
        minimo.achado(uf, "leitura_placas", "em_uso", fornecedor=forn)
    r = LeituraPainelSQLite(minimo.caminho).analise_fornecedores()
    assert r["n_nao_informado"] == 3 and r["n_informado"] == 4 and r["n_achados"] == 7 and r["n_fornecedores"] == 2
    assert r["top"][0]["chave"] == "axis" and r["top"][0]["n_achados"] == 3 and r["top"][0]["n_ufs"] == 2
    assert r["top"][0]["ufs"] == ["PI", "SP"] and r["top"][1]["fornecedor"] == "Foo Bar"
    assert r["share_top3"] == 1.0
    assert {(x["uf"], x["fornecedor"]): x["n"] for x in r["por_uf"]}[("SP", r["top"][0]["fornecedor"])] == 2


def test_fornecedores_limite_e_concentracao(minimo):
    for i in range(5):
        minimo.achado("PI", "leitura_placas", "em_uso", fornecedor=f"F{i}")
    minimo.achado("PI", "leitura_placas", "em_uso", fornecedor="F0")
    r = LeituraPainelSQLite(minimo.caminho).analise_fornecedores(limite=2)
    assert len(r["top"]) == 2 and r["n_fornecedores"] == 5 and r["share_top3"] == round(4 / 6, 4)


def test_fornecedores_demo(L):
    r = L.analise_fornecedores(limite=5)
    assert len(r["top"]) <= 5 and r["n_informado"] + r["n_nao_informado"] == r["n_achados"]
    assert r["top"] == sorted(r["top"], key=lambda t: -t["n_achados"])


# ============================== 4. funil por provedor ==============================
def test_funil_por_provedor_demo(L, demo):
    r = L.analise_funil_por_provedor()
    assert r["n_provedores"] == len(r["provedores"]) >= 1
    for p in r["provedores"]:
        assert p["resultados"] >= p["urls_unicas"] and p["achados"] >= p["confirmados"]
        assert [e["chave"] for e in p["etapas"]][0] == "resultados" and p["etapas"][-1]["n"] == p["confirmados"]
    assert sum(p["resultados"] for p in r["provedores"]) == _sql(demo, "SELECT COUNT(*) FROM r_resultados_web")[0][0]
    custo = _sql(demo, "SELECT COALESCE(SUM(custo_usd), 0) FROM r_chamadas WHERE etapa = 'busca_web' AND sucesso = 1")[0][0]
    assert sum(p["custo_usd"] for p in r["provedores"]) == pytest.approx(custo)


def test_funil_nao_assume_dois_provedores(minimo):
    r = LeituraPainelSQLite(minimo.caminho).analise_funil_por_provedor()
    assert r["provedores"] == [] and r["n_provedores"] == 0


def test_funil_dois_provedores_a_mao(minimo):
    u1, u2 = minimo.url("a.gov.br"), minimo.url("b.gov.br")
    for prov, urls in (("perplexity_search", (u1, u2)), ("serpapi_google", (u1,))):
        cid = minimo.chamada("busca_web", prov, "M01-PI", custo=0.5)
        for pos, u in enumerate(urls, 1):
            _sql(minimo.caminho, """INSERT INTO resultados_web (chamada_id, run_id, consulta_id, uf, url_id, posicao) VALUES (?,?,?,?,?,?)""",
                 (cid, minimo.run, "M01-PI", "PI", u, pos))
    cid = minimo.chamada("classificacao", "gemini", "x")
    _sql(minimo.caminho, "INSERT INTO classificacoes (chamada_id, run_id, url_id, uf, relevante, json_valido, n_achados) VALUES (?,?,?,?,1,1,1)",
         (cid, minimo.run, u1, "PI"))
    k = _sql(minimo.caminho, "SELECT MAX(classificacao_id) FROM classificacoes")[0][0]
    _sql(minimo.caminho, "INSERT INTO achados (classificacao_id, uf, tecnologia, status_reportado, verificado, status_final) VALUES (?,?,?,?,1,?)",
         (k, "PI", "leitura_placas", "em_uso", "em_uso"))
    r = {p["provedor"]: p for p in LeituraPainelSQLite(minimo.caminho).analise_funil_por_provedor()["provedores"]}
    assert r["perplexity_search"]["resultados"] == 2 and r["perplexity_search"]["urls_unicas"] == 2
    assert r["serpapi_google"]["resultados"] == 1 and r["serpapi_google"]["custo_usd"] == 0.5
    assert r["perplexity_search"]["confirmados"] == 1 and r["serpapi_google"]["confirmados"] == 1   # a mesma URL achada pelos dois
    assert r["perplexity_search"]["classificacoes_relevantes"] == 1


# ============================== 5. posicao ==============================
def test_posicao_web_demo(L, demo):
    r = L.analise_retorno_por_posicao("web")
    assert r["fonte"] == "web" and r["agrupamento"] == "posicao"
    assert r["n_total"] == _sql(demo, "SELECT COUNT(*) FROM r_resultados_web WHERE posicao IS NOT NULL")[0][0]
    assert [l["posicao"] for l in r["linhas"]] == sorted(l["posicao"] for l in r["linhas"])
    assert all(l["n_com_achados"] <= l["n_resultados"] and l["n_triados"] == 0 for l in r["linhas"])   # demo sem triagem_escopo
    assert r["tem_dados_humanos"] and r["n_verificados"] > 0


def test_posicao_web_com_triagem_escopo(copia):
    pares = _sql(copia, "SELECT DISTINCT url_id, uf FROM resultados_web ORDER BY url_id, uf LIMIT 4")
    for i, (u, uf) in enumerate(pares):
        _te(copia, "web", u, "elegivel" if i % 2 == 0 else "excluido", uf=uf, provedor="demo_busca")
    r = LeituraPainelSQLite(copia).analise_retorno_por_posicao("web")
    assert sum(l["n_triados"] for l in r["linhas"]) >= 4 and sum(l["n_elegiveis"] for l in r["linhas"]) >= 2
    assert all(l["n_elegiveis"] <= l["n_triados"] for l in r["linhas"])


def test_posicao_scholar_faixas_de_10(L, demo):
    r = L.analise_retorno_por_posicao("scholar")
    assert r["agrupamento"] == "faixa_10" and r["n_total"] == _sql(demo, "SELECT COUNT(*) FROM r_ocorrencias")[0][0]
    assert r["linhas"][0]["rotulo"] == "1-10" and r["linhas"][0]["posicao_de"] == 1 and r["linhas"][-1]["posicao_ate"] % 10 == 0
    assert r["n_humanos"] == 53 and r["tem_dados_humanos"]


def test_posicao_scholar_com_escopo_e_humano(copia):
    ocs = _sql(copia, "SELECT DISTINCT artigo_id FROM ocorrencias WHERE posicao <= 10 ORDER BY artigo_id LIMIT 3")
    for a, in ocs:
        _te(copia, "artigo", a, "elegivel")
    r = LeituraPainelSQLite(copia).analise_retorno_por_posicao("scholar")
    assert r["linhas"][0]["n_elegiveis"] >= 1 and r["linhas"][0]["pct_elegiveis"] is not None


# ============================== 6. literatura ==============================
def test_literatura_temporal_demo(L, demo):
    r = L.analise_literatura_temporal()
    assert r["n_artigos"] == _sql(demo, "SELECT COUNT(*) FROM r_artigos")[0][0]
    assert sum(l["n_artigos"] for l in r["por_ano"]) == r["n_artigos"]
    assert r["n_humanos"] == 53 and sum(l["n_incluidos"] for l in r["por_ano"]) == 31
    assert all(c["grupo"] in r["grupos"] for c in r["celulas"])
    assert sum(c["n_artigos"] for c in r["celulas"]) >= r["n_artigos"]           # um artigo pode estar em varios grupos
    assert r["n_triagem_escopo"] == 0 and sum(l["n_elegiveis"] for l in r["por_ano"]) == 0


def test_literatura_temporal_elegiveis(copia):
    ids = [a for a, in _sql(copia, "SELECT artigo_id FROM artigos ORDER BY artigo_id LIMIT 5")]
    for a in ids[:3]:
        _te(copia, "artigo", a, "elegivel")
    _te(copia, "artigo", ids[3], "elegivel", valido=0)         # veredito invalido nao conta
    _te(copia, "artigo", ids[4], "excluido")
    r = LeituraPainelSQLite(copia).analise_literatura_temporal()
    assert sum(l["n_elegiveis"] for l in r["por_ano"]) == 3 and r["n_triagem_escopo"] == 5


def test_multitermo_demo(L, demo):
    r = L.analise_multitermo()
    assert r["n_artigos"] == _sql(demo, "SELECT COUNT(*) FROM v_artigos_multi_termo")[0][0]
    assert [f["faixa"] for f in r["faixas"]] == sorted(f["faixa"] for f in r["faixas"])
    assert r["faixas"][0]["faixa"] == "1" and all(f["n_artigos"] > 0 for f in r["faixas"])
    assert r["tem_dados_humanos"] and sum(f["n_incluidos"] for f in r["faixas"]) <= 31


def test_multitermo_junta_4_ou_mais(minimo):
    a = _sql(minimo.caminho, "INSERT INTO artigos (chave_dedup, titulo, ano) VALUES ('a', 'A', 2023) RETURNING artigo_id")[0][0]
    b = _sql(minimo.caminho, "INSERT INTO artigos (chave_dedup, titulo, ano) VALUES ('b', 'B', 2023) RETURNING artigo_id")[0][0]
    cid = minimo.chamada("busca_academica", "serpapi_scholar", "T01")
    for t in ("T01", "T02", "T03", "T04", "T05"):
        _sql(minimo.caminho, "INSERT INTO ocorrencias (chamada_id, artigo_id, termo_id, run_id, posicao) VALUES (?,?,?,?,1)", (cid, a, t, "R1"))
    _sql(minimo.caminho, "INSERT INTO ocorrencias (chamada_id, artigo_id, termo_id, run_id, posicao) VALUES (?,?,?,?,2)", (cid, b, "T01", "R1"))
    _sql(minimo.caminho, "INSERT INTO triagem (artigo_id, decisao) VALUES (?, 'incluir')", (a,))
    r = {f["faixa"]: f for f in LeituraPainelSQLite(minimo.caminho).analise_multitermo()["faixas"]}
    assert r["4+"]["n_artigos"] == 1 and r["4+"]["pct_incluidos"] == 100.0 and r["1"]["n_artigos"] == 1 and r["1"]["pct_incluidos"] is None


# ============================== 7. calibracao da confianca ==============================
def test_calibracao_confianca_demo(L, demo):
    r = L.analise_calibracao_confianca()
    assert [c["confianca"] for c in r["por_confianca"]][:3] == ["alta", "media", "baixa"]
    assert r["n_achados"] == _sql(demo, "SELECT COUNT(*) FROM r_achados")[0][0] and r["n_verificados"] > 0
    for c in r["por_confianca"]:
        assert c["n_confirmados"] + c["n_descartados"] == c["n_verificados"]
        assert (c["taxa_confirmacao"] is None) == (c["n_verificados"] == 0)


def test_calibracao_confianca_a_mao(minimo):
    minimo.achado("PI", "leitura_placas", "em_uso", verificado=1, final="em_uso", confianca="alta")
    minimo.achado("PI", "leitura_placas", "em_uso", verificado=1, final="descartado", confianca="alta")
    minimo.achado("PI", "leitura_placas", "em_uso", confianca="alta", original="alta")
    minimo.achado("PI", "leitura_placas", "em_uso", verificado=1, final="piloto", confianca="baixa", original="alta")
    minimo.achado("PI", "leitura_placas", "em_uso", confianca="baixa", original="alta")
    r = LeituraPainelSQLite(minimo.caminho).analise_calibracao_confianca()
    por = {c["confianca"]: c for c in r["por_confianca"]}
    assert por["alta"]["n_achados"] == 3 and por["alta"]["n_verificados"] == 2 and por["alta"]["taxa_confirmacao"] == 0.5
    assert por["baixa"]["n_achados"] == 2 and por["baixa"]["taxa_confirmacao"] == 1.0 and r["n_verificados"] == 3
    assert r["ajuste"]["n_rebaixados"] == 2 and r["ajuste"]["rebaixados"] == {"n": 2, "n_verificados": 1, "n_confirmados": 1, "n_descartados": 0}


# ============================== 8. falsa exclusao ==============================
def test_falsa_exclusao_sem_triagem_escopo_e_tudo_zero(L):
    r = L.analise_falsa_exclusao()
    assert r["n_humanos"] == 0 and r["n_falsas_exclusoes"] == 0 and r["taxa_falsa_exclusao"] is None and not r["tem_dados_humanos"]
    assert all(v == 0 for linha in r["cruzamento"].values() for v in linha.values()) and r["falsas_exclusoes"] == []


def test_falsa_exclusao_sem_decisao_humana(minimo):
    a = _sql(minimo.caminho, "INSERT INTO artigos (chave_dedup, titulo) VALUES ('a', 'A') RETURNING artigo_id")[0][0]
    _te(minimo.caminho, "artigo", a, "excluido", categoria="FORA_DO_RECORTE_TEMPORAL", run="R1")
    r = LeituraPainelSQLite(minimo.caminho).analise_falsa_exclusao()
    assert r["n_humanos"] == 0 and r["taxa_falsa_exclusao"] is None and r["cruzamento"]["excluido"]["pendente"] == 1


def test_falsa_exclusao_cruzamento_e_lista(copia):
    decididos = _sql(copia, "SELECT artigo_id, decisao FROM triagem WHERE decisao IN ('incluir', 'excluir') ORDER BY artigo_id")
    inc = [a for a, d in decididos if d == "incluir"][:2]
    exc = [a for a, d in decididos if d == "excluir"][:1]
    pend = _sql(copia, "SELECT a.artigo_id FROM artigos a LEFT JOIN triagem t ON t.artigo_id = a.artigo_id WHERE t.artigo_id IS NULL LIMIT 1")[0][0]
    _te(copia, "artigo", inc[0], "excluido", categoria="FORA_DO_RECORTE_TEMPORAL")         # falsa exclusao
    _te(copia, "artigo", inc[1], "elegivel")
    _te(copia, "artigo", exc[0], "excluido", categoria="RUIDO_WEB")
    _te(copia, "artigo", pend, "quarentena")
    r = LeituraPainelSQLite(copia).analise_falsa_exclusao()
    assert r["cruzamento"]["excluido"] == {"incluir": 1, "excluir": 1, "pendente": 0}
    assert r["cruzamento"]["elegivel"]["incluir"] == 1 and r["cruzamento"]["quarentena"]["pendente"] == 1
    assert r["n_humanos"] == 3 and r["n_falsas_exclusoes"] == 1 and r["taxa_falsa_exclusao"] == round(1 / 3, 4) and r["tem_dados_humanos"]
    assert r["falsas_exclusoes"][0]["artigo_id"] == inc[0] and r["falsas_exclusoes"][0]["categoria_motivo"] == "FORA_DO_RECORTE_TEMPORAL"
    assert r["por_categoria_falsa"] == {"FORA_DO_RECORTE_TEMPORAL": 1}


def test_falsa_exclusao_usa_so_o_veredito_atual(copia):
    a = _sql(copia, "SELECT artigo_id FROM triagem WHERE decisao = 'incluir' LIMIT 1")[0][0]
    _te(copia, "artigo", a, "excluido", categoria="X")
    runs = [r for r, in _sql(copia, "SELECT run_id FROM execucoes ORDER BY run_id")]
    _te(copia, "artigo", a, "elegivel", run=runs[-1] if runs[-1] != _run(copia) else runs[0])   # outra execucao, mais recente
    assert LeituraPainelSQLite(copia).analise_falsa_exclusao()["n_falsas_exclusoes"] == 0


# ============================== 9. opacidade ==============================
def test_opacidade_demo(L):
    r = L.analise_opacidade_dominios()
    assert r["n_tentadas"] == r["n_ok"] + r["n_robots"] + r["n_http_bloqueio"] + r["n_outros"] > 0
    assert sum(m["n"] for m in r["motivos"]) >= r["n_tentadas"] and r["n_dominios"] >= len(r["dominios"])
    assert r["pct_bloqueado"] == 0.0 and r["n_robots"] == 0


def test_opacidade_robots_e_http_a_mao(minimo):
    banco = minimo.caminho
    casos = (("a.gov.br", "bloqueado_por_robots", None, 0), ("a.gov.br", "HTTP 403", 403, 0), ("a.gov.br", None, 200, 1),
             ("b.gov.br", "HTTP 429", 429, 0), ("b.gov.br", "HTTP 404", 404, 0), ("c.gov.br", None, 200, 1))
    for dominio, erro, http, ok in casos:
        u = minimo.url(dominio)
        _sql(banco, "INSERT INTO selecao_download (run_id, url_id, uf, selecionada) VALUES (?,?,?,1)", ("R1", u, "PI"))
        cid = minimo.chamada("download", "requests", u, sucesso=ok, http=http, erro=erro)
        if ok:
            _sql(banco, "INSERT INTO paginas (run_id, url_id, chamada_id, extracao_ok, dominio_final) VALUES (?,?,?,1,?)", ("R1", u, cid, dominio))
    u = minimo.url("d.gov.br")
    _sql(banco, "INSERT INTO selecao_download (run_id, url_id, uf, selecionada) VALUES (?,?,?,1)", ("R1", u, "PI"))   # nunca tentada
    r = LeituraPainelSQLite(banco).analise_opacidade_dominios()
    assert (r["n_tentadas"], r["n_ok"], r["n_robots"], r["n_http_bloqueio"], r["n_outros"]) == (6, 2, 1, 2, 1)
    assert r["pct_bloqueado"] == 50.0
    por = {d["dominio"]: d for d in r["dominios"]}
    assert por["a.gov.br"]["n_tentadas"] == 3 and por["a.gov.br"]["n_robots"] == 1 and por["a.gov.br"]["n_http_bloqueio"] == 1
    assert por["a.gov.br"]["pct_bloqueado"] == round(100 * 2 / 3, 1) and por["b.gov.br"]["n_outros"] == 1 and "d.gov.br" not in por
    assert r["dominios"][0]["dominio"] == "a.gov.br" and r["por_uf"][0]["uf"] == "PI"
    assert len(LeituraPainelSQLite(banco).analise_opacidade_dominios(limite=1)["dominios"]) == 1


# ============================== 10. saturacao ==============================
def test_saturacao_demo(L, demo):
    r = L.analise_saturacao()
    curva = r["curva"]
    assert r["n_chamadas"] == len(curva) > 0 and [c["ordem"] for c in curva] == list(range(1, len(curva) + 1))
    assert all(a["novos_acumulado"] <= b["novos_acumulado"] for a, b in zip(curva, curva[1:]))
    assert r["n_novos_total"] == curva[-1]["novos_acumulado"] == _sql(
        demo, "SELECT SUM(n_novos) FROM r_chamadas WHERE etapa = 'busca_academica' AND sucesso = 1")[0][0]


# ============================== 11. tokens ==============================
def test_calibracao_tokens_razao_e_regressao(minimo):
    for chars, tokens in ((340, 100), (680, 200), (1020, 300), (3400, 1000)):          # exatamente 3,4 caracteres por token
        minimo.achado("PI", "leitura_placas", "em_uso", chars=chars, tokens=tokens)
    minimo.achado("PI", "leitura_placas", "em_uso", chars=0, tokens=50)                 # sem texto: fora
    r = LeituraPainelSQLite(minimo.caminho).analise_calibracao_tokens()
    assert r["n"] == 4 and r["razao_mediana"] == 3.4 and r["razao_media"] == 3.4
    assert r["regressao"]["chars_por_token_marginal"] == 3.4 and r["regressao"]["r2"] == 1.0 and r["regressao"]["intercepto"] == 0.0
    assert sorted(r["pares"]) == [[340, 100], [680, 200], [1020, 300], [3400, 1000]]


def test_calibracao_tokens_demo(L, demo):
    r = L.analise_calibracao_tokens()
    n = _sql(demo, """SELECT COUNT(*) FROM r_classificacoes k JOIN r_chamadas c ON c.chamada_id = k.chamada_id
                      WHERE c.tokens_entrada > 0 AND k.n_chars_enviados > 0""")[0][0]
    assert r["n"] == len(r["pares"]) == n and r["razao_mediana"] > 0


# ============================== 12. tamanho do texto ==============================
def test_tamanho_texto_faixas_e_json_invalido(minimo):
    for chars, valido, trunc, n in ((100, 1, 0, 1), (4999, 1, 0, 2), (5000, 1, 0, 3), (30000, 0, 0, 0), (59999, 1, 0, 6), (60000, 1, 1, 0), (60000, 0, 1, 0)):
        minimo.achado("PI", "leitura_placas", "em_uso", chars=chars, json_valido=valido, truncado=trunc, n_achados=n)
    r = LeituraPainelSQLite(minimo.caminho).analise_tamanho_texto_achados()
    f = {x["faixa"]: x for x in r["faixas"]}
    assert [x["faixa"] for x in r["faixas"]] == ["<5k", "5-20k", "20-60k", ">=60k"]
    assert (f["<5k"]["n"], f["5-20k"]["n"], f["20-60k"]["n"], f[">=60k"]["n"]) == (2, 1, 2, 2)
    assert f["20-60k"]["n_json_invalido"] == 1 and f["20-60k"]["taxa_json_invalido"] == 0.5 and f[">=60k"]["taxa_json_invalido"] == 0.5
    assert f["<5k"]["achados_por_mil_chars"] == round(1000 * 3 / (100 + 4999), 4) and f["<5k"]["achados_por_classificacao"] == 1.5
    assert r["n"] == 7 and r["n_truncados"] == 2 and r["truncamento"]["truncados"]["n"] == 2 and r["truncamento"]["integros"]["n"] == 5
    assert r["truncamento"]["integros"]["n_json_invalido"] == 1 and r["n_json_invalido"] == 2


def test_tamanho_texto_filtra_origem_e_demo(L, demo):
    todos = L.analise_tamanho_texto_achados()
    assert todos["n"] == _sql(demo, "SELECT COUNT(*) FROM r_classificacoes")[0][0] == sum(f["n"] for f in todos["faixas"])
    assert L.analise_tamanho_texto_achados("snippet")["n"] + L.analise_tamanho_texto_achados("pagina")["n"] == todos["n"]
    assert all(f["taxa_json_invalido"] is None for f in L.analise_tamanho_texto_achados("inexistente")["faixas"])


# ============================== 13. termos da triagem de escopo ==============================
def test_termos_triagem_escopo_reaproveita_a_ficha(copia):
    consulta = _sql(copia, "SELECT termo_id, query FROM v_termos WHERE termo_id = 'T01'")[0]
    ids = [a for a, in _sql(copia, "SELECT artigo_id FROM artigos ORDER BY artigo_id LIMIT 4")]
    for a, st in zip(ids, ("elegivel", "elegivel", "excluido", "quarentena")):
        _te(copia, "artigo", a, st, termos=[consulta[1]], categoria=None if st == "elegivel" else "RUIDO_WEB")
    r = LeituraPainelSQLite(copia).analise_termos_triagem_escopo()
    assert r["fonte"] == "artigo" and r["n_itens"] == 4 and r["n_termos"] == 1
    f = r["termos"][0]
    assert f["termo_id"] == "T01" and f["grupo"] and f["n_itens"] == 4 and f["n_elegivel"] == 2 and f["pct_ruido"] == 50.0


def test_termos_triagem_escopo_sem_tabela_e_fonte_invalida(L):
    assert L.analise_termos_triagem_escopo() == {"fonte": "artigo", "n_itens": 0, "n_termos": 0, "termos": []}
    assert L.analise_termos_triagem_escopo("xyz")["termos"] == []


# ============================== 14. resumo ==============================
def test_resumo_demo(L, demo):
    r = L.analise_resumo()
    assert r["n_achados"] == _sql(demo, "SELECT COUNT(*) FROM r_achados")[0][0] and r["n_verificados"] == 57
    assert r["n_triagem_humana"] == 53 and r["tem_dados_humanos"] and r["tem_dados_humanos_achados"] and r["tem_dados_humanos_artigos"]
    assert r["n_triagem_escopo"] == {} and r["provedores"]["busca_web"] == ["demo_busca"] and r["provedores"]["triagem_escopo"] == []
    assert r["n_artigos"] == 119 and r["n_chamadas_busca_academica"] > 0 and r["n_classificacoes"] > 0


def test_resumo_conta_triagem_escopo_por_fonte_pela_linha_atual(copia):
    _te(copia, "artigo", 1, "elegivel")
    _te(copia, "artigo", 2, "excluido")
    _te(copia, "web", 1, "elegivel", uf="PI", provedor="perplexity_search")
    r = LeituraPainelSQLite(copia).analise_resumo()
    assert r["n_triagem_escopo"] == {"artigo": 2, "web": 1} and r["provedores"]["triagem_escopo"] == ["perplexity_search", "serpapi_scholar"]


def test_resumo_sem_dados_humanos(minimo):
    minimo.achado("PI", "leitura_placas", "em_uso")
    r = LeituraPainelSQLite(minimo.caminho).analise_resumo()
    assert r["n_achados"] == 1 and r["n_verificados"] == 0 and r["tem_dados_humanos"] is False


# ============================== so leitura e execucoes fora do relatorio ==============================
def test_execucao_fora_do_relatorio_nao_entra(minimo):
    minimo.achado("PI", "leitura_placas", "em_uso")
    _sql(minimo.caminho, "UPDATE execucoes SET no_relatorio = 0")
    L = LeituraPainelSQLite(minimo.caminho)
    assert L.analise_resumo()["n_achados"] == 0 and L.analise_fornecedores()["n_achados"] == 0
    assert L.analise_maturidade_uf_tecnologia()["celulas"] == [] and L.analise_calibracao_tokens()["n"] == 0


def test_leituras_nao_gravam_no_banco(demo):
    antes = demo.stat().st_mtime_ns
    L = LeituraPainelSQLite(demo)
    for nome, args in METODOS:
        getattr(L, nome)(*args)
    assert demo.stat().st_mtime_ns == antes
