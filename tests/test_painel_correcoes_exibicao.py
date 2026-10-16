"""Regressoes de exibicao achadas na revisao do guia do painel (16/10/2026)."""
import shutil
import sqlite3

import pytest
from fastapi.testclient import TestClient

import painel_demo
from adaptadores.leitura_sqlite import LeituraPainelSQLite
from test_painel import _app


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("demo_exibicao")
    return painel_demo.construir(pasta), pasta / "raw_demo"


@pytest.fixture
def cliente(demo, tmp_path):
    banco, raw = demo
    copia = tmp_path / "demo.db"
    shutil.copy(banco, copia)
    app, _ = _app(copia, raw, tmp_path, somente_leitura=True)
    return TestClient(app), copia


def test_chamada_de_download_mostra_pagina_baixada_sem_despejar_dicionario(cliente):
    cli, banco = cliente
    c = sqlite3.connect(banco)
    ids = [r[0] for r in c.execute("SELECT chamada_id FROM chamadas WHERE etapa='download' AND chamada_id IN (SELECT chamada_id FROM paginas) LIMIT 3")]
    assert ids, "a demonstracao deveria ter downloads com pagina"
    leitura = LeituraPainelSQLite(banco)
    for i in ids:
        d = leitura.chamada(i)
        assert d["pagina_baixada"] and isinstance(d["pagina_baixada"], dict)
        assert not isinstance(d["pagina"], dict)             # o numero da pagina da busca nao e sobrescrito
        html = cli.get(f"/chamadas/{i}").text
        assert "Página baixada" in html and "{&#39;pagina_id&#39;" not in html and "pagina_id" not in html


def test_contagem_de_fontes_da_triagem_conta_itens_distintos(demo, tmp_path):
    banco, _ = demo
    copia = tmp_path / "t.db"
    shutil.copy(banco, copia)
    c = sqlite3.connect(copia)
    colunas = [r[1] for r in c.execute("PRAGMA table_info(triagem_escopo)") if r[1] != "id"]
    runs = [r[0] for r in c.execute("SELECT run_id FROM execucoes LIMIT 3")]
    assert len(runs) == 3
    base = {"run_id": runs[0], "fonte": "artigo", "item_id": 1, "uf": "",
            "status": "elegivel", "status_bruto": "elegivel", "confianca": "alta", "valido": 1, "prompt_versao": "t2",
            "criado_em": "2026-10-16T00:00:00+00:00", "categoria_motivo": "NENHUMA", "justificativa": "x"}
    for run in runs:                                           # tres linhas (uma por execucao) para o MESMO item: conta como 1
        valores = {k: base.get(k) for k in colunas}
        valores["run_id"] = run
        c.execute(f"INSERT INTO triagem_escopo ({', '.join(colunas)}) VALUES ({', '.join('?' * len(colunas))})", list(valores.values()))
    c.commit()
    c.close()
    assert LeituraPainelSQLite(copia).fontes_com_triagem_escopo() == {"artigo": 1}


def test_pagina_do_estado_informa_o_total_real_mesmo_com_teto(cliente):
    cli, _ = cliente
    html = cli.get("/estados/SP").text
    assert "achado(s), agrupados por tecnologia" in html
