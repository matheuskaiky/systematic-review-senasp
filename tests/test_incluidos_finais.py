"""Incluido final = incluido por titulo e resumo E por texto completo (como a linha 20 do PRISMA), em toda view de rendimento."""
from dados_metricas import _id_artigo, construir_academico


def test_decisao_de_texto_completo_que_ficou_de_um_incluir_antigo_nao_conta(tmp_path):
    repo, _ = construir_academico(tmp_path / "a.db")
    a1 = _id_artigo(repo, 1)                                                   # incluido por titulo e resumo no banco montado
    repo.conn.execute("UPDATE triagem SET decisao_texto_completo = 'incluir' WHERE artigo_id = ?", (a1,))
    repo.conn.commit()
    linha20 = repo.conn.execute("SELECT valor FROM v_prisma WHERE ordem = 20").fetchone()[0]
    fontes = sum(r[0] for r in repo.conn.execute("SELECT n_incluidos_finais FROM v_rendimento_fonte"))
    assert linha20 == 1 and fontes == 1
    repo.conn.execute("UPDATE triagem SET decisao = 'excluir' WHERE artigo_id = ?", (a1,))   # mudou de ideia; o tc ficou
    repo.conn.commit()
    assert repo.conn.execute("SELECT valor FROM v_prisma WHERE ordem = 20").fetchone()[0] == 0
    assert sum(r[0] for r in repo.conn.execute("SELECT n_incluidos_finais FROM v_rendimento_fonte")) == 0
    assert sum(r[0] for r in repo.conn.execute("SELECT n_incluidos_finais FROM v_rendimento_termo")) == 0
