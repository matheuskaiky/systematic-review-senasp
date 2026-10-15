"""Desempenho do painel com um banco em escala de coleta completa (painel_demo.construir_grande): cada pagina deve responder rapido.

O limite do teste (1,5 s) e folgado de proposito, para nao quebrar em maquina lenta; a meta de projeto e abaixo de 500 ms.
Para ver a tabela de tempos: `pytest tests/test_painel_desempenho.py -s`."""
import sqlite3
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent))
from test_painel import _app  # noqa: E402

import painel_demo  # noqa: E402

LIMITE_S = 1.5
META_S = 0.5
REPETICOES = 3


@pytest.fixture(scope="module")
def grande(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("grande")
    return painel_demo.construir_grande(pasta), pasta / "raw_demo_grande", pasta


def _ids(banco):
    c = sqlite3.connect(banco)
    try:
        achado_texto = c.execute("""SELECT a.achado_id FROM achados a JOIN classificacoes k ON k.classificacao_id=a.classificacao_id
                                    JOIN paginas p ON p.pagina_id=k.pagina_id WHERE p.texto_path IS NOT NULL ORDER BY a.achado_id LIMIT 1""").fetchone()[0]
        runs = [r[0] for r in c.execute("SELECT run_id FROM execucoes ORDER BY iniciado_em")]
        return {"achado": achado_texto, "runs": runs,
                "chamada": c.execute("SELECT MIN(chamada_id) FROM chamadas WHERE etapa='classificacao'").fetchone()[0],
                "chamada_bruta": c.execute("SELECT MIN(chamada_id) FROM chamadas WHERE raw_path IS NOT NULL").fetchone()[0],
                "artigo": c.execute("SELECT artigo_id FROM artigos ORDER BY citacoes DESC LIMIT 1").fetchone()[0]}
    finally:
        c.close()


def _rotas(i):
    web, classif = i["runs"][0], i["runs"][2]
    return [
        "/", "/estados", "/estados/SP",
        "/achados", "/achados?p=40", "/achados?uf=SP&verificacao=pendente&p=2", "/achados?q=reconhecimento&p=3",
        "/achados?evidencia=0&confianca=baixa", "/achados?esfera=municipal", f"/achados/{i['achado']}", f"/achados/{i['achado']}?completo=1",
        "/revisao/achados",
        "/execucoes", f"/execucoes/{web}", f"/execucoes/{classif}", f"/execucoes/comparar?a={web}&b={classif}",
        "/chamadas", "/chamadas?etapa=classificacao&p=20", "/chamadas?resultado=falha", "/chamadas?q=SP", f"/chamadas/{i['chamada']}",
        f"/chamadas/{i['chamada_bruta']}",
        "/literatura", "/literatura/artigos", "/literatura/artigos?q=estudo&p=5", "/literatura/artigos?multi=1&decisao=pendente",
        f"/literatura/artigos/{i['artigo']}", "/literatura/triagem", "/literatura/prisma",
        "/sobre",
    ]


@pytest.fixture(scope="module")
def tempos(grande):
    banco, raw, pasta = grande
    app, _ = _app(banco, raw, pasta)
    cli = TestClient(app, raise_server_exceptions=False)
    ids = _ids(banco)
    rotas = _rotas(ids)
    for extra in ("/classificadores", "/metodologia"):             # paginas de outros modulos: medidas so se existirem
        if cli.get(extra).status_code == 200:
            rotas.append(extra)
    cli.get("/")                                                     # aquecimento: abre o banco e le o CSS/templates
    saida = {}
    for rota in rotas:
        medidas = []
        for _ in range(REPETICOES):
            t0 = time.perf_counter()
            r = cli.get(rota, follow_redirects=True)
            medidas.append(time.perf_counter() - t0)
            assert r.status_code == 200, (rota, r.status_code)
        saida[rota] = medidas
    return saida


def test_banco_grande_tem_a_escala_pedida(grande):
    banco, _, _ = grande
    c = sqlite3.connect(banco)
    n = lambda t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    assert n("resultados_web") == 3000 and n("classificacoes") == 1000 and n("achados") == 2000 and n("artigos") == 1500
    assert n("chamadas") >= 500
    assert c.execute("SELECT COUNT(*) FROM urls WHERE url_original NOT LIKE '%exemplo.gov.br%' AND url_original NOT LIKE '%.example/%'").fetchone()[0] == 0
    c.close()


def test_construir_grande_e_deterministico_e_nao_toca_outros_bancos(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    pa, pb = painel_demo.construir_grande(a), painel_demo.construir_grande(b)
    assert pa.name == "demo_grande.db"
    assert sorted(p.name for p in a.iterdir() if p.suffix == ".db") == ["demo_grande.db"]
    ca, cb = sqlite3.connect(pa), sqlite3.connect(pb)
    consulta = "SELECT achado_id, uf, tecnologia, status_reportado, evidencia_confere, confianca, verificado FROM achados ORDER BY achado_id"
    assert ca.execute(consulta).fetchall() == cb.execute(consulta).fetchall()
    ca.close(), cb.close()


@pytest.mark.parametrize("rota", [pytest.param(r, id=r) for r in _rotas({"achado": 1, "runs": ["a", "b", "c"], "chamada": 1, "chamada_bruta": 1, "artigo": 1})])
def test_pagina_responde_dentro_do_limite(tempos, rota):
    # as rotas com ids reais sao refeitas na fixture; aqui comparamos por posicao no dicionario
    chaves = list(tempos)
    modelo = _rotas({"achado": 1, "runs": ["a", "b", "c"], "chamada": 1, "chamada_bruta": 1, "artigo": 1})
    real = chaves[modelo.index(rota)]
    assert max(tempos[real]) < LIMITE_S, f"{real}: {max(tempos[real]) * 1000:.0f} ms"


def test_paginas_de_outros_modulos_medidas_quando_existirem(tempos):
    for rota, medidas in tempos.items():
        if rota in ("/classificadores", "/metodologia"):
            assert max(medidas) < LIMITE_S, rota


def test_tabela_de_tempos(tempos, capsys):
    """Imprime a tabela (visivel com -s) e confere que a mediana de cada pagina esta na meta de projeto, com folga."""
    linhas = [f"{'rota':<60} {'1a (ms)':>8} {'mediana':>8} {'maximo':>8}"]
    for rota, m in tempos.items():
        linhas.append(f"{rota[:60]:<60} {m[0] * 1000:>8.0f} {sorted(m)[len(m) // 2] * 1000:>8.0f} {max(m) * 1000:>8.0f}")
    with capsys.disabled():
        print("\n" + "\n".join(linhas))
    lentas = {r: sorted(m)[len(m) // 2] for r, m in tempos.items() if sorted(m)[len(m) // 2] > LIMITE_S}
    assert not lentas


def test_gasto_real_usa_o_indice_de_provedor_e_custo(grande):
    """v_gasto_real fazia uma varredura da tabela por chamada sem custo (533 ms com 2.300 chamadas); o indice evita isso."""
    banco, _, _ = grande
    c = sqlite3.connect(banco)
    plano = " ".join(str(l[3]) for l in c.execute("EXPLAIN QUERY PLAN SELECT * FROM v_gasto_real"))
    c.close()
    assert "ix_chamadas_provedor_custo" in plano and "SCAN x" not in plano
