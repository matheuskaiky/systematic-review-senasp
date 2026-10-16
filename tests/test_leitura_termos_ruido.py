"""Leituras RE7 e RD12 (adaptadores/leitura_termos_ruido.py): bancos pequenos montados a mao com o esquema real, banco de demonstracao
(sem triagem de escopo), banco vazio e banco antigo sem tabelas. So le: o arquivo do banco nao muda."""
import hashlib
import json
import shutil
import sqlite3

import pytest

import painel_demo
from adaptadores.leitura_sqlite import LeituraPainelSQLite
from adaptadores.leitura_termos_ruido import LeituraTermosRuido
from adaptadores.repositorio_sqlite import RepositorioSQLite

METODOS = [("analise_prefiltro_web", ()), ("analise_ruido_por_termo", ()), ("analise_simulacao_contexto", ()),
           ("analise_simulacao_contexto", ("T01",))]


# o mixin ja faz parte de LeituraPainelSQLite (adaptadores/leitura_sqlite.py): o teste usa a classe real
Leitura = LeituraPainelSQLite
assert issubclass(LeituraPainelSQLite, LeituraTermosRuido)



def _sql(banco, sql, args=()):
    conn = sqlite3.connect(banco)
    try:
        conn.execute("PRAGMA synchronous = OFF")          # banco de teste descartavel: sem fsync a cada linha
        r = conn.execute(sql, args).fetchall()
        conn.commit()
        return r
    finally:
        conn.close()


def _sha(caminho):
    return hashlib.sha256(open(caminho, "rb").read()).hexdigest()


TERMOS = [{"id": "T01", "query": '"reconhecimento facial"', "idioma": "pt", "grupo": "reconhecimento", "pai": ""},
          {"id": "T02", "query": '"policiamento preditivo"', "idioma": "pt", "grupo": "preditiva", "pai": ""},
          {"id": "T40", "query": '"machine learning"', "idioma": "en", "grupo": "dados", "pai": ""}]
POLITICA = {"palavras_chave": ["camera", "reconhecimento facial"], "max_urls_por_uf": 2, "dominios_excluir": [], "apenas_oficiais": False}


class Banco:
    """Banco com o esquema real e linhas acrescentadas a mao (as chaves estrangeiras ficam desligadas, como nos outros testes)."""

    def __init__(self, caminho, modelo):
        self.caminho = caminho
        shutil.copy(modelo, caminho)                  # o esquema (lento) e criado uma vez por modulo
        self._te = 0

    def execucao(self, run_id, comando, iniciado, termos=True, politica=True, relatorio=1):
        cfg = {}
        if termos:
            cfg["termos"] = TERMOS
        if politica:
            cfg["politica_download"] = POLITICA
        _sql(self.caminho, "INSERT INTO execucoes (run_id, iniciado_em, comando, config_hash, config_json, no_relatorio) VALUES (?,?,?,?,?,?)",
             (run_id, iniciado, comando, "h", json.dumps(cfg), relatorio))

    def url(self, url_id):
        _sql(self.caminho, "INSERT INTO urls (url_id, url_normalizada, url_original, dominio, fonte_oficial) VALUES (?,?,?,?,1)",
             (url_id, f"https://x/{url_id}", f"https://x/{url_id}", "x.gov.br"))

    def resultado(self, run, url_id, uf, titulo, snippet="", posicao=1, vezes=1):
        for k in range(vezes):
            _sql(self.caminho, "INSERT INTO resultados_web (chamada_id, run_id, consulta_id, uf, url_id, posicao, titulo, snippet) VALUES (?,?,?,?,?,?,?,?)",
                 (1, run, f"c{k}", uf, url_id, posicao + k, titulo, snippet))

    def selecao(self, run, url_id, uf, sel, motivo=None):
        _sql(self.caminho, "INSERT INTO selecao_download (run_id, url_id, uf, selecionada, motivo) VALUES (?,?,?,?,?)", (run, url_id, uf, sel, motivo))

    def veredito(self, fonte, item_id, status, uf="", valido=1, termos=(), categoria=None, dominio=None, run="T1", escopo="brasil", sinal=None):
        self._te += 1
        _sql(self.caminho, """INSERT INTO triagem_escopo (run_id, fonte, item_id, uf, termos_consulta, status, status_bruto, valido,
                                  categoria_motivo, dominio_tematico, escopo_geografico, sinal_negativo, prompt_versao, criado_em)
                              VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
             (run, fonte, item_id, uf, json.dumps(list(termos)), status, status, valido, categoria, dominio, escopo, sinal, "t2",
              f"2026-01-01T00:00:{self._te:02d}"))

    def artigo(self, artigo_id, titulo, resumo, termo_id, ano=2024):
        _sql(self.caminho, "INSERT OR IGNORE INTO artigos (artigo_id, chave_dedup, titulo, snippet, ano) VALUES (?,?,?,?,?)",
             (artigo_id, f"k{artigo_id}", titulo, resumo, ano))
        _sql(self.caminho, "INSERT INTO ocorrencias (chamada_id, artigo_id, termo_id, run_id, posicao) VALUES (1,?,?,?,1)",
             (artigo_id, termo_id, "A1"))


@pytest.fixture(scope="module")
def modelo(tmp_path_factory):
    caminho = tmp_path_factory.mktemp("modelo_termos") / "modelo.db"
    RepositorioSQLite(caminho).fechar()
    return caminho


@pytest.fixture
def web(tmp_path, modelo):
    """UF PI, limite 2. Palavras do pre-filtro: camera e reconhecimento facial. 9 pares (url, PI):
    1,2 selecionados (elegivel, excluido); 3 limite (elegivel, ranking 3); 4 limite (elegivel, ranking 4); 5 limite (excluido);
    6,7 pre-filtro (elegivel 'senasp', excluido); 8 pre-filtro (elegivel 'senasp'); 9 sem veredito valido; 10 sem decisao de download."""
    b = Banco(tmp_path / "web.db", modelo)
    b.execucao("ANTIGA", "pipeline-uf", "2026-01-01T00:00:00")                  # sem selecao_download: nao e a coleta principal
    b.execucao("PRINCIPAL", "pipeline-uf", "2026-02-01T00:00:00")
    b.execucao("PILOTO", "baixar", "2026-03-01T00:00:00")                       # tem selecao, mas nao e pipeline-uf
    b.selecao("PILOTO", 1, "PI", 0, "prefiltro_palavras")
    linhas = [(1, "camera na viatura", "x", 1, None, "elegivel", 5), (2, "camera velha", "x", 1, None, "excluido", 4),
              (3, "sistema integrado", "x", 0, "limite_por_uf", "elegivel", 3), (4, "outro sistema", "x", 0, "limite_por_uf", "elegivel", 2),
              (5, "receita", "x", 0, "limite_por_uf", "excluido", 1), (6, "senasp painel", "senasp", 0, "prefiltro_palavras", "elegivel", 1),
              (7, "futebol", "x", 0, "prefiltro_palavras", "excluido", 1), (8, "senasp relatorio", "senasp", 0, "prefiltro_palavras", "elegivel", 1)]
    for url, titulo, snip, sel, motivo, status, vezes in linhas:
        b.url(url)
        b.resultado("PRINCIPAL", url, "PI", titulo, snip, posicao=url, vezes=vezes)
        b.selecao("PRINCIPAL", url, "PI", sel, motivo)
        b.veredito("web", url, status, "PI")
    b.url(9)
    b.resultado("PRINCIPAL", 9, "PI", "invalido", "", vezes=1)
    b.selecao("PRINCIPAL", 9, "PI", 0, "prefiltro_palavras")
    b.veredito("web", 9, "elegivel", "PI", valido=0)
    b.url(10)
    b.veredito("web", 10, "elegivel", "PI")                                      # triado, mas sem decisao de download
    b.veredito("web", 7, "elegivel", "PI", run="T2")                                 # veredito mais recente do item 7: elegivel
    return b


def test_prefiltro_acha_a_coleta_principal_pelo_comando_e_le_o_prefiltro(web):
    r = Leitura(web.caminho).analise_prefiltro_web()
    assert r["run_id"] == "PRINCIPAL" and r["comando"] == "pipeline-uf" and r["tem_dados"] is True
    assert r["prefiltro"] == POLITICA["palavras_chave"] and r["limite_por_uf"]["limite"] == 2
    assert r["n_selecao"] == 9 and r["n_sem_triagem"] == 0 and r["n_sem_selecao"] == 1 and r["n_invalidos"] == 1
    json.dumps(r)


def test_prefiltro_grupos_usam_o_veredito_mais_recente(web):
    r = Leitura(web.caminho).analise_prefiltro_web()
    g = {x["chave"]: x for x in r["grupos"]}
    assert g["selecionada"]["n"] == 2 and g["selecionada"]["n_elegivel"] == 1
    assert g["prefiltro_palavras"]["n"] == 3 and g["prefiltro_palavras"]["n_elegivel"] == 3      # o item 7 virou elegivel (linha mais nova)
    assert g["limite_por_uf"]["n"] == 3 and g["limite_por_uf"]["n_elegivel"] == 2
    assert g["nao_selecionada"]["n"] == 6 and g["nao_selecionada"]["n_elegivel"] == 5
    assert g["nao_selecionada"]["elegivel"]["k"] == 5 and g["nao_selecionada"]["elegivel"]["ic_inf"] < 83.3 < g["nao_selecionada"]["elegivel"]["ic_sup"]


def test_prefiltro_limite_por_uf_reconstroi_a_ordem_e_o_teto(web):
    lim = Leitura(web.caminho).analise_prefiltro_web()["limite_por_uf"]
    pi = lim["por_uf"][0]
    # 5 candidatos passaram pelo pre-filtro; por ocorrencias: 1 (5), 2 (4), 3 (3), 4 (2), 5 (1) -> ranks 1..5; os elegiveis cortados sao 3 e 4
    assert pi["uf"] == "PI" and pi["n_candidatos"] == 5 and pi["n_no_limite"] == 3
    assert pi["n_elegiveis_perdidos"] == 2 and pi["teto_necessario"] == 4 and pi["downloads_extras"] == 2
    assert lim["teto_necessario"] == 4 and lim["curva"][-1] == {"teto": 4, "elegiveis_capturados": 2, "uteis_capturados": 2, "downloads_extras": 2}


def test_prefiltro_palavras_candidatas_e_desempenho(web):
    r = Leitura(web.caminho).analise_prefiltro_web()
    assert r["n_frente"] == 3 and r["n_fundo"] == 2
    d = {x["palavra"]: x for x in r["desempenho_prefiltro"]}
    assert d["camera"]["n"] == 2 and d["camera"]["n_elegivel"] == 1 and d["reconhecimento facial"]["n"] == 0
    # `senasp` aparece em 2 dos 3 elegiveis descartados; com suporte minimo 5 (padrao) nao ha candidata; baixando o suporte ela surge
    assert all(c["n_frente"] >= 5 for c in r["palavras_candidatas"])


def test_prefiltro_em_banco_so_com_execucao_antiga_ou_sem_triagem(tmp_path, modelo):
    b = Banco(tmp_path / "x.db", modelo)
    r = Leitura(b.caminho).analise_prefiltro_web()
    assert r["tem_dados"] is False and r["run_id"] is None and r["grupos"][0]["n"] == 0 and r["grupos"][0]["elegivel"]["pct"] is None
    b.execucao("P", "pipeline-uf", "2026-01-01T00:00:00")
    b.selecao("P", 1, "PI", 1)                                                    # coleta principal, mas nenhum veredito
    r2 = Leitura(b.caminho).analise_prefiltro_web()
    assert r2["run_id"] == "P" and r2["tem_dados"] is False and r2["n_selecao"] == 1 and r2["n_sem_triagem"] == 1


def test_prefiltro_sem_json_de_politica_usa_padroes(tmp_path, modelo):
    b = Banco(tmp_path / "x.db", modelo)
    b.execucao("P", "pipeline-uf", "2026-01-01T00:00:00", politica=False)
    b.url(1)
    b.resultado("P", 1, "PI", "a")
    b.selecao("P", 1, "PI", 1)
    b.veredito("web", 1, "elegivel", "PI")
    r = Leitura(b.caminho).analise_prefiltro_web()
    assert r["prefiltro"] == [] and r["limite_por_uf"]["limite"] == 40 and r["tem_dados"] is True


# ---------------------------------------------------------------- artigos
@pytest.fixture
def artigos(tmp_path, modelo):
    """T01 (pt): 6 artigos, 3 elegiveis (2 com 'policia'), 3 excluidos (saude). T02 (pt): 12 artigos, todos elegiveis. T40 (en): 2 excluidos."""
    b = Banco(tmp_path / "art.db", modelo)
    b.execucao("A1", "academico", "2026-01-01T00:00:00")
    t1 = '"reconhecimento facial"'
    dados = [(1, "Polícia usa reconhecimento", "elegivel"), (2, "Policia federal e rostos", "elegivel"), (3, "Rostos no Brasil", "elegivel"),
             (4, "Face em exames de saude", "excluido"), (5, "Saude e imagem", "excluido"), (6, "Policia e hospital", "excluido")]
    for i, titulo, status in dados:
        b.artigo(i, titulo, "resumo", "T01")
        b.veredito("artigo", i, status, termos=[t1], categoria=None if status == "elegivel" else "FORA_SEGURANCA_PUBLICA",
                   dominio=None if status == "elegivel" else "saude", sinal="saude" if status == "excluido" else None)
    for i in range(20, 32):
        b.artigo(i, f"Policiamento preditivo {i}", "dados", "T02")
        b.veredito("artigo", i, "elegivel", termos=['"policiamento preditivo"'])
    for i in (40, 41):
        b.artigo(i, "Machine learning for farms", "agro", "T40")
        b.veredito("artigo", i, "excluido", termos=['"machine learning"'], categoria="FORA_SEGURANCA_PUBLICA", dominio="agropecuaria_meio_ambiente",
                   escopo="internacional")
    b.veredito("artigo", 6, "elegivel", termos=[t1], run="T2")                          # o veredito mais recente do artigo 6: elegivel
    return b


def test_ruido_por_termo_tabela_e_mapeamento_de_termo_id(artigos):
    r = Leitura(artigos.caminho).analise_ruido_por_termo()
    assert r["tem_dados"] is True and r["n_termos"] == 3 and r["n_itens"] == 20 and r["n_invalidos"] == 0
    t = {l["termo_id"]: l for l in r["tabela"]}
    assert t["T01"]["n"] == 6 and t["T01"]["n_elegivel"] == 4 and t["T01"]["n_excluido"] == 2 and t["T01"]["grupo"] == "reconhecimento"
    assert t["T01"]["elegivel"]["pct"] == pytest.approx(66.7, abs=0.05) and t["T01"]["dominio_top"] == "saude"
    assert t["T02"]["acao"] == "manter" and t["T40"]["acao"] == "amostra pequena"
    assert t["T01"]["acao"] == "amostra pequena"                                  # 6 resultados: abaixo do minimo para concluir
    assert [l["termo_id"] for l in r["tabela"]][0] == "T40"                    # menos elegivel primeiro
    assert [f["termo_id"] for f in r["fichas"]] and "dominios" in r["fichas"][0]
    assert r["matriz"] and {"termo_gerador", "categoria_motivo", "dominio_tematico", "n"} <= set(r["matriz"][0])


def test_ruido_por_termo_negativos_reutilizam_o_dominio(artigos):
    r = Leitura(artigos.caminho).analise_ruido_por_termo()
    por = {n["chave"]: n for n in r["negativos"]}
    assert "saude" in por and por["saude"]["n_excluidos_atingidos"] == 2         # artigos 4 e 5 (o 6 deixou de ser excluido)
    assert por["saude"]["veredito"] in ("seguro", "arriscado", "perigoso")
    assert sum(r["por_veredito"].values()) == r["n_negativos"] >= len(r["negativos"])
    assert r["ganho_minimo_negativo"] >= 1 and 0 <= r["n_negativos_seguros_de_ganho"] <= r["por_veredito"]["seguro"]
    json.dumps(r)


def test_ruido_por_termo_respeita_limites_e_protegidos(artigos):
    r = Leitura(artigos.caminho).analise_ruido_por_termo(limite_negativos=1, limite_matriz=1, protegidos=["saude"])
    assert len(r["negativos"]) == 1 and len(r["matriz"]) == 1 and r["n_negativos"] >= 1
    por = {n["chave"]: n for n in Leitura(artigos.caminho).analise_ruido_por_termo(protegidos=["saude"])["negativos"]}
    assert por["saude"]["protegida"] is True and por["saude"]["veredito"] == "perigoso"


def test_simulacao_por_termo_contagens_e_candidatas(artigos):
    r = Leitura(artigos.caminho).analise_simulacao_contexto()
    assert r["tem_dados"] is True and r["n_termos"] == 3 and r["n_pares"] == 20 and r["limite_perda"] == 0.10
    assert [t["termo_id"] for t in r["termos"]] == ["T01", "T02", "T40"]
    t1 = r["termos"][0]
    assert (t1["n"], t1["n_elegivel"], t1["n_excluido"], t1["idioma"]) == (6, 4, 2, "pt") and t1["n_candidatas"] == len(t1["candidatas"])
    por = {c["rotulo"]: c for c in t1["candidatas"]}
    pol = por["polícia"]                                                          # artigos 1, 2 e 6 (elegiveis) passam; os excluidos 4 e 5 nao
    assert pol["origem"] == "padrao" and pol["aprovada"] is False and pol["n_passam"] == 3
    assert pol["retencao_elegivel"]["k"] == 3 and pol["retencao_elegivel"]["n"] == 4 and pol["perda_elegivel"] == 1
    assert pol["perda_elegivel_pct"] == 25.0
    assert pol["ruido_removido"]["k"] == 2 and pol["ruido_removido"]["pct"] == 100.0 and pol["perde_muitos_uteis"] is True
    assert pol["pct_elegivel_resultante"]["pct"] == 100.0
    en = r["termos"][2]
    assert en["idioma"] == "en" and any(c["rotulo"] == "Brazil" for c in en["candidatas"]) and not any(c["rotulo"] == "Brasil" for c in en["candidatas"])


def test_simulacao_agregado_e_limites_no_resultado(artigos):
    r = Leitura(artigos.caminho).analise_simulacao_contexto()
    ids = {a["id"] for a in r["agregado"]}
    assert "padrao:pt:policia" in ids and "padrao:en:police" in ids and all(i.startswith("padrao:") for i in ids)
    pol = {a["id"]: a for a in r["agregado"]}["padrao:pt:policia"]
    assert pol["n_termos"] == 2                                                   # T01 e T02 sao termos em portugues
    assert len(r["limites"]) >= 3 and "RD4" in " ".join(r["limites"]) and "nada" in r["aviso"].lower()


def test_simulacao_filtra_por_termo_e_limita_candidatas(artigos):
    r = Leitura(artigos.caminho).analise_simulacao_contexto(termo_id="T01", limite=3)
    assert r["n_termos"] == 1 and r["termos"][0]["termo_id"] == "T01" and len(r["termos"][0]["candidatas"]) == 3
    assert r["termos"][0]["n_candidatas"] > 3
    ruidos = [c["ruido_removido"]["pct"] or 0 for c in r["termos"][0]["candidatas"]]
    assert ruidos == sorted(ruidos, reverse=True)
    assert Leitura(artigos.caminho).analise_simulacao_contexto(termo_id="T99")["tem_dados"] is False
    assert Leitura(artigos.caminho).analise_simulacao_contexto(limite=0)["termos"][0]["candidatas"] == []


def test_simulacao_ignora_vereditos_invalidos_e_artigos_sem_veredito(artigos):
    artigos.veredito("artigo", 1, "excluido", termos=['"reconhecimento facial"'], valido=0, run="T3")     # linha mais nova do artigo 1, invalida
    artigos.artigo(99, "Sem veredito", "x", "T01")
    t1 = Leitura(artigos.caminho).analise_simulacao_contexto("T01")["termos"][0]
    assert t1["n"] == 5 and t1["n_elegivel"] == 3                                  # o artigo 1 saiu das contas; o 99 nunca entrou


# ---------------------------------------------------------------- banco de demonstracao, vazio e antigo
@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    return painel_demo.construir(tmp_path_factory.mktemp("demo_termos_ruido"))


@pytest.mark.parametrize("nome,args", METODOS)
def test_demo_sem_triagem_de_escopo_devolve_estruturas_vazias(demo, nome, args):
    r = getattr(Leitura(demo), nome)(*args)
    assert isinstance(r, dict)
    json.dumps(r)
    assert not r.get("tem_dados")


@pytest.mark.parametrize("nome,args", METODOS)
def test_banco_vazio_e_banco_antigo_nao_falham(tmp_path, modelo, nome, args):
    vazio = tmp_path / "vazio.db"
    shutil.copy(modelo, vazio)
    antigo = tmp_path / "antigo.db"
    sqlite3.connect(antigo).close()
    for caminho in (vazio, antigo):
        r = getattr(Leitura(caminho), nome)(*args)
        json.dumps(r)
        assert not r.get("tem_dados")


def test_demo_com_vereditos_acrescentados_a_mao(demo, tmp_path):
    """Banco de demonstracao copiado, com vereditos para os artigos e para as decisoes de download: formas e somas fecham."""
    copia = tmp_path / "copia.db"
    shutil.copy(demo, copia)
    run = _sql(copia, "SELECT run_id FROM execucoes WHERE no_relatorio = 1 ORDER BY run_id LIMIT 1")[0][0]
    _sql(copia, "UPDATE execucoes SET comando = 'pipeline-uf' WHERE comando = 'baixar'")
    n = 0
    for (artigo_id,) in _sql(copia, "SELECT artigo_id FROM artigos ORDER BY artigo_id"):
        n += 1
        _sql(copia, """INSERT INTO triagem_escopo (run_id, fonte, item_id, uf, termos_consulta, status, status_bruto, valido, prompt_versao, criado_em)
                       VALUES (?,?,?,?,?,?,?,1,'t2','2026-01-01T00:00:00')""", (run, "artigo", artigo_id, "", json.dumps(['"reconhecimento facial"']),
                                                                                 "elegivel" if n % 3 else "excluido", "elegivel" if n % 3 else "excluido"))
    for url_id, uf in _sql(copia, "SELECT url_id, uf FROM selecao_download"):
        _sql(copia, """INSERT OR IGNORE INTO triagem_escopo (run_id, fonte, item_id, uf, termos_consulta, status, status_bruto, valido, prompt_versao, criado_em)
                       VALUES (?,?,?,?,?,?,?,1,'t2','2026-01-01T00:00:00')""", (run, "web", url_id, uf, "[]", "elegivel", "elegivel"))
    antes = _sha(copia)
    L = Leitura(copia)
    p, rt, s = L.analise_prefiltro_web(), L.analise_ruido_por_termo(), L.analise_simulacao_contexto()
    assert _sha(copia) == antes                                                   # so leitura
    for d in (p, rt, s):
        json.dumps(d)
    assert p["tem_dados"] and p["n_validos"] == _sql(copia, "SELECT COUNT(*) FROM selecao_download")[0][0] - p["n_sem_triagem"]
    g = {x["chave"]: x for x in p["grupos"]}
    assert g["selecionada"]["n"] + g["nao_selecionada"]["n"] == p["n_validos"]
    assert rt["tem_dados"] and rt["n_itens"] == _sql(copia, "SELECT COUNT(*) FROM artigos")[0][0]
    assert s["tem_dados"] and s["n_pares"] <= _sql(copia, "SELECT COUNT(*) FROM (SELECT DISTINCT artigo_id, termo_id FROM r_ocorrencias)")[0][0]
    for t in s["termos"]:
        assert t["n_elegivel"] + t["n_excluido"] + t["n_quarentena"] == t["n"]
        for c in t["candidatas"]:
            assert c["retencao_elegivel"]["k"] + c["perda_elegivel"] == t["n_elegivel"]
