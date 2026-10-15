"""Coluna `cidade` (secretarias municipais): consultas, gravacao, views, exportacao, migracao e painel."""
import logging
import sqlite3

import pytest
from fastapi.testclient import TestClient

from adaptadores.bruto_local import BrutoLocal
from adaptadores.repositorio_sqlite import RepositorioSQLite
from adaptadores.simulados import BuscaSimulada, ClassificadorSimulado, ExtratorSimulado, FetcherSimulado
from aplicacao import busca_web, classificacao, download
from config import consultas as C, vocabulario as V
from dados_metricas import _novo_run, _params
from dominio.modelos import ModeloConsultaWeb, ResultadoWeb, RespostaBusca
from dominio.servicos import gerar_consultas_web
from test_painel import _app

MODELO_MUN = ModeloConsultaWeb("M11", "{tec} Secretaria Municipal de Segurança {cidade} {uf}", perfil="oficial")
UFS_PI = {"PI": C.UFS["PI"]}
TEC = {"reconhecimento_facial": "reconhecimento facial"}


@pytest.fixture(autouse=True)
def silencio():
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)


# ---------- configuracao e geracao das consultas ----------
def test_por_padrao_nao_ha_consulta_municipal_e_nada_foi_inventado():
    assert C.MUNICIPIOS == {} and C.MODELOS_WEB_MUNICIPAIS == []
    assert len(gerar_consultas_web(C.MODELOS_WEB, V.TECNOLOGIAS, C.UFS, C.MUNICIPIOS, C.MODELOS_WEB_MUNICIPAIS)) == 270


def test_consultas_municipais_carregam_a_cidade_e_ids_unicos():
    cs = gerar_consultas_web([], TEC, UFS_PI, {"PI": ["São Luís do Piauí", "Teresina"]}, [MODELO_MUN])
    assert [c.cidade for c in cs] == ["São Luís do Piauí", "Teresina"]
    assert cs[0].id == "M11-PI-sao_luis_do_piaui-reconhecimento_facial" and len({c.id for c in cs}) == 2
    assert cs[1].texto == "reconhecimento facial Secretaria Municipal de Segurança Teresina PI" and cs[1].uf == "PI"


def test_municipios_de_uf_nao_selecionada_ficam_de_fora_e_estaduais_nao_tem_cidade():
    cs = gerar_consultas_web(C.MODELOS_WEB[:1], TEC, UFS_PI, {"PI": ["A"], "CE": ["B"]}, [MODELO_MUN])
    assert [c.cidade for c in cs] == ["", "A"]


def test_snapshot_da_configuracao_inclui_municipios():
    import config.settings as S
    import json
    j = json.loads(S.snapshot_config()["json"])
    assert j["municipios"] == {} and j["modelos_web_municipais"] == []


# ---------- ponta a ponta ----------
class BuscaComCidade(BuscaSimulada):
    def buscar(self, consulta, filtros):
        base = f"https://{(consulta.cidade or 'ssp').lower().replace(' ', '-')}.exemplo.gov.br/{consulta.uf.lower()}"
        res = [ResultadoWeb(f"{base}/{n}", f"Reconhecimento facial {consulta.cidade or consulta.uf} {n}", "câmeras com reconhecimento facial", None, n)
               for n in (1, 2)]
        from adaptadores.simulados import _reg
        return RespostaBusca(res, _reg(self.nome, "buscar", raw=b"{}"))


@pytest.fixture
def repo(tmp_path):
    r = RepositorioSQLite(tmp_path / "c.db")
    bruto = BrutoLocal(tmp_path / "raw")
    run = _novo_run(r, "pipeline-uf")
    cs = gerar_consultas_web(C.MODELOS_WEB[:1], TEC, UFS_PI, {"PI": ["Cidade Demo"]}, [MODELO_MUN])
    busca_web.executar(r, bruto, BuscaComCidade(), run, cs, C.PERFIS_BUSCA_WEB, [], 0)
    download.executar(r, bruto, FetcherSimulado(), ExtratorSimulado(), run, run, C.POLITICA_DOWNLOAD, [], 0, ufs={"PI"})
    classificacao.executar(r, bruto, ClassificadorSimulado(), run, run, _params(), C.UFS, [], 0, ufs={"PI"})
    return r


def test_cidade_percorre_resultado_classificacao_e_view(repo):
    c = repo.conn
    assert {tuple(x) for x in c.execute("SELECT DISTINCT consulta_id LIKE 'M11%', cidade FROM resultados_web")} == {(0, None), (1, "Cidade Demo")}
    assert {tuple(x) for x in c.execute("SELECT url_id IN (SELECT url_id FROM urls WHERE url_original LIKE '%cidade-demo%'), cidade FROM classificacoes")} == {(0, None), (1, "Cidade Demo")}
    fila = {x["url"]: x["cidade"] for x in c.execute("SELECT url, cidade FROM v_achados_revisao")}
    assert fila and all((("cidade-demo" in u) == (cid == "Cidade Demo")) for u, cid in fila.items())


def test_resumo_por_municipio_e_secretarias_confirmadas(repo):
    ids = [r[0] for r in repo.conn.execute("SELECT achado_id FROM v_achados_revisao WHERE cidade IS NOT NULL")]
    estadual = repo.conn.execute("SELECT achado_id FROM v_achados_revisao WHERE cidade IS NULL").fetchone()[0]
    permitidos = set(V.STATUS) | set(V.STATUS_FINAL_EXTRA)
    repo.verificar_achado(ids[0], "em_uso", "Ana", None, permitidos)
    repo.verificar_achado(estadual, "piloto", "Ana", None, permitidos)
    m = [dict(x) for x in repo.conn.execute("SELECT * FROM v_resumo_municipio")]
    assert m == [{"uf": "PI", "cidade": "Cidade Demo", "n_achados": len(ids), "n_verificados": 1, "n_confirmados": 1, "n_evidencia_ok": len(ids)}]
    sec = {x["achado_id"]: x["cidade"] for x in repo.conn.execute("SELECT achado_id, cidade FROM v_secretarias_confirmadas")}
    assert sec == {ids[0]: "Cidade Demo", estadual: None}
    resumo_uf = repo.conn.execute("SELECT n_achados FROM v_resumo_uf WHERE uf='PI'").fetchone()[0]
    assert resumo_uf == repo.conn.execute("SELECT COUNT(*) FROM achados").fetchone()[0] > len(ids)   # a UF soma estaduais e municipais


def test_exportacao_traz_a_coluna_e_a_aba_municipios(repo):
    t = repo.tabelas_para_exportacao()
    assert "cidade" in t["Achados"].columns and "cidade" in t["Secretarias"].columns
    assert list(t["Municipios"]["cidade"]) == ["Cidade Demo"]
    assert set(t["Achados"]["cidade"].dropna()) == {"Cidade Demo"}


def test_mesma_url_em_busca_estadual_e_municipal_fica_com_a_cidade(tmp_path):
    """Limite conhecido: o item e (url, uf); se a mesma URL vem de uma busca estadual e de uma municipal, fica a cidade."""
    r = RepositorioSQLite(tmp_path / "x.db")
    bruto = BrutoLocal(tmp_path / "raw")
    run = _novo_run(r, "busca-web")
    cs = gerar_consultas_web(C.MODELOS_WEB[:1], TEC, UFS_PI, {"PI": ["Cidade Demo"]}, [MODELO_MUN])
    busca_web.executar(r, bruto, BuscaSimulada(), run, cs, C.PERFIS_BUSCA_WEB, [], 0)       # mesma URL para as duas consultas
    cands = r.candidatos_download(run)
    assert cands and all(c.cidade == "Cidade Demo" for c in cands)


# ---------- migracao ----------
def test_banco_antigo_ganha_as_colunas_de_cidade(tmp_path):
    db = sqlite3.connect(tmp_path / "velho.db")
    db.executescript("CREATE TABLE resultados_web (resultado_id INTEGER PRIMARY KEY, chamada_id INTEGER, run_id TEXT, consulta_id TEXT, uf TEXT, url_id INTEGER);"
                     "CREATE TABLE classificacoes (classificacao_id INTEGER PRIMARY KEY, chamada_id INTEGER, run_id TEXT, url_id INTEGER, uf TEXT);")
    db.close()
    r = RepositorioSQLite(tmp_path / "velho.db")
    for tabela in ("resultados_web", "classificacoes"):
        assert "cidade" in {l["name"] for l in r.conn.execute(f"PRAGMA table_info({tabela})")}


# ---------- painel ----------
def test_painel_filtra_por_esfera_e_cidade_e_mostra_a_coluna(repo, tmp_path):
    banco = tmp_path / "c.db"
    cli = TestClient(_app(banco, tmp_path / "raw", tmp_path)[0])
    todos = cli.get("/achados").text
    assert "<th>Cidade</th>" in todos and "Cidade Demo" in todos and "estadual" in todos
    so_mun = cli.get("/achados?esfera=municipal").text
    assert "Cidade Demo" in so_mun and "ssp.exemplo.gov.br" not in so_mun
    so_est = cli.get("/achados?esfera=estadual").text
    assert "Cidade Demo</td>" not in so_est and "ssp.exemplo.gov.br" in so_est
    assert "Cidade Demo" in cli.get("/achados?cidade=Cidade+Demo").text
    assert "Nenhum achado" in cli.get("/achados?cidade=Outra").text
    i = sqlite3.connect(banco).execute("SELECT achado_id FROM v_achados_revisao WHERE cidade IS NOT NULL").fetchone()[0]
    d = cli.get(f"/achados/{i}").text
    assert "Municipal: Cidade Demo (PI)" in d
    j = sqlite3.connect(banco).execute("SELECT achado_id FROM v_achados_revisao WHERE cidade IS NULL").fetchone()[0]
    assert "Estadual: Piauí" in cli.get(f"/achados/{j}").text
