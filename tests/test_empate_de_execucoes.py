"""Duas execucoes iniciadas no mesmo segundo: "a mais recente" e a gravada por ultimo (rowid), nunca a de sufixo aleatorio
maior. Cada consulta que ordena execucoes por inicio desempata pela ordem de gravacao."""
import json
import re
from pathlib import Path

import pytest

from adaptadores.leitura_sqlite import LeituraPainelSQLite
from adaptadores.repositorio_sqlite import RepositorioSQLite

RAIZ = Path(__file__).resolve().parent.parent
MESMO = "2026-10-20T10:00:00+00:00"
ANTES = "2026-10-20T09:00:00+00:00"
# gravadas nesta ordem; o sufixo aleatorio poe a ultima gravada em primeiro lugar na ordem alfabetica
RUNS = [("20261020_090000_mmmmmm", ANTES, None, "x antigo"),
        ("20261020_100000_zzzzzz", MESMO, "20261020_090000_mmmmmm", "x primeiro"),
        ("20261020_100000_aaaaaa", MESMO, "20261020_090000_mmmmmm", "x segundo")]


@pytest.fixture
def banco(tmp_path):
    caminho = tmp_path / "empate.db"
    repo = RepositorioSQLite(caminho)
    for run_id, inicio, origem, query in RUNS:
        cfg = json.dumps({"termos": [{"id": "T1", "query": query, "idioma": "pt", "grupo": "g", "pai": None}]})
        repo.conn.execute("INSERT INTO execucoes (run_id, iniciado_em, comando, config_hash, config_json, run_origem) "
                          "VALUES (?, ?, 'classificar', 'h', ?, ?)", (run_id, inicio, cfg, origem))
    repo.conn.commit()
    return caminho, repo


def test_painel_lista_a_gravada_por_ultimo_primeiro(banco):
    caminho, _ = banco
    L = LeituraPainelSQLite(caminho)
    esperado = ["20261020_100000_aaaaaa", "20261020_100000_zzzzzz", "20261020_090000_mmmmmm"]
    assert [e["run_id"] for e in L.execucoes_recentes(5)] == esperado
    assert [e["run_id"] for e in L.execucoes()] == esperado
    assert L.opcoes_chamadas()["runs"] == esperado
    assert [e["run_id"] for e in L.execucoes_classificacao()] == esperado


def test_derivadas_em_ordem_de_gravacao(banco):
    caminho, _ = banco
    e = LeituraPainelSQLite(caminho).execucao("20261020_090000_mmmmmm")
    assert e["run_destino"] == ["20261020_100000_zzzzzz", "20261020_100000_aaaaaa"]


def test_exportacao_e_metodologia_em_ordem_de_gravacao(banco):
    caminho, repo = banco
    assert repo.tabelas_para_exportacao()["Execucoes"]["run_id"].tolist() == [r[0] for r in RUNS]
    fatos = LeituraPainelSQLite(caminho).fatos_metodologia()
    assert [e["run_id"] for e in fatos["execucoes"]] == [r[0] for r in RUNS]


def test_definicao_do_termo_vem_da_execucao_gravada_por_ultimo(banco):
    _, repo = banco
    assert repo.conn.execute("SELECT query FROM v_termos WHERE termo_id='T1'").fetchone()[0] == "x segundo"


def test_toda_ordenacao_por_inicio_desempata_por_rowid():
    """Guarda: nenhuma consulta de producao ordena execucoes por inicio sem desempatar pela ordem de gravacao."""
    faltam = []
    for p in sorted((RAIZ / "adaptadores").glob("*.py")) + [RAIZ / "adaptadores" / "schema.sql"]:
        texto = p.read_text(encoding="utf-8")
        for m in re.finditer(r"ORDER BY[^\"\n)]*iniciado_em[^\"\n]*", texto):
            if "rowid" not in m.group(0):
                faltam.append(f"{p.name}:{texto[:m.start()].count(chr(10)) + 1}")
    assert faltam == []
