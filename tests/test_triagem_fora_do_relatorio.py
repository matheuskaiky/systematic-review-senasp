"""Triagem humana de artigo que so apareceu em execucao fora do relatorio (piloto) nao entra no PRISMA, nos motivos de
exclusao nem na eficiencia: as contagens ficam iguais as de um banco sem o piloto."""
import re
from pathlib import Path

from dados_metricas import _chamada_academica, _id_artigo, _novo_run, construir_academico

RAIZ = Path(__file__).resolve().parent.parent


def _numeros(repo):
    return ([tuple(r) for r in repo.conn.execute("SELECT ordem, valor FROM v_prisma ORDER BY ordem")],
            [tuple(r) for r in repo.conn.execute("SELECT etapa, motivo, n FROM v_motivos_exclusao")],
            tuple(repo.conn.execute("SELECT artigos_incluidos, creditos_por_artigo_incluido FROM v_eficiencia").fetchone()))


def test_piloto_triado_nao_muda_os_numeros_do_relatorio(tmp_path):
    base, _ = construir_academico(tmp_path / "base.db")
    esperado = _numeros(base)
    repo, _ = construir_academico(tmp_path / "piloto.db")
    piloto = _novo_run(repo, "academico")
    _chamada_academica(repo, piloto, "T01", 3, [20, 21], 10)                  # A20 e A21 so existem no piloto
    repo.conn.execute("UPDATE execucoes SET no_relatorio = 0 WHERE run_id = ?", (piloto,))
    repo.conn.execute("INSERT INTO triagem (artigo_id, decisao, decisao_texto_completo) VALUES (?, 'incluir', 'incluir')",
                      (_id_artigo(repo, 20),))
    repo.conn.execute("INSERT INTO triagem (artigo_id, decisao, motivo) VALUES (?, 'excluir', 'so no piloto')",
                      (_id_artigo(repo, 21),))
    repo.conn.commit()
    assert _numeros(repo) == esperado
    assert all(m != "so no piloto" for _, m, _ in _numeros(repo)[1])


def test_o_mesmo_artigo_no_relatorio_continua_contando(tmp_path):
    repo, _ = construir_academico(tmp_path / "b.db")
    antes = dict(repo.conn.execute("SELECT ordem, valor FROM v_prisma"))
    a1 = _id_artigo(repo, 6)                                                   # pendente no banco montado
    repo.conn.execute("UPDATE triagem SET decisao = 'incluir' WHERE artigo_id = ?", (a1,))
    repo.conn.commit()
    depois = dict(repo.conn.execute("SELECT ordem, valor FROM v_prisma"))
    assert depois[15] == antes[15] + 1 and depois[16] == antes[16] - 1


def test_nenhuma_view_conta_a_tabela_triagem_sem_filtro():
    sql = (RAIZ / "adaptadores" / "schema.sql").read_text(encoding="utf-8")
    assert re.findall(r"FROM triagem WHERE", sql) == []
    assert "CREATE VIEW r_triagem AS\nSELECT t.* FROM triagem t WHERE t.artigo_id IN (SELECT artigo_id FROM r_artigos);" in sql
