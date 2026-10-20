"""Paridade SQLite x PostgreSQL com dados: o banco de demonstracao montado em SQLite e importado no PostgreSQL da as
mesmas linhas em cada uma das 73 views, e a importacao recusa destino com dados."""
import sqlite3

import pytest

from adaptadores import migrador_postgres as M
from adaptadores.postgres import importador as I

pytestmark = pytest.mark.postgres


def _normal(v):
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def _linhas(rows):
    return sorted((tuple(_normal(v) for v in r) for r in rows), key=repr)


@pytest.fixture(scope="module")
def demo_pg(copiar_demo, pg_url_modulo):
    banco, _ = copiar_demo("paridade_pg")
    M.aplicar(pg_url_modulo)
    relatorio = I.importar(banco, pg_url_modulo)
    yield banco, pg_url_modulo, relatorio


def test_importacao_copia_todas_as_linhas(demo_pg):
    banco, _, relatorio = demo_pg
    con = sqlite3.connect(banco)
    for t, (origem, destino) in relatorio.items():
        assert origem == destino == con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0], t
    assert relatorio["achados"][0] > 0 and relatorio["artigos"][0] > 0


def test_todas_as_views_dao_as_mesmas_linhas(demo_pg):
    import psycopg
    from adaptadores.postgres.conexao import _configurar
    banco, url, _ = demo_pg
    con = sqlite3.connect(banco)
    views = [n for (n,) in con.execute("SELECT name FROM sqlite_master WHERE type='view' ORDER BY name")]
    diferentes = {}
    with psycopg.connect(url) as pg:
        _configurar(pg)
        for v in views:
            a = _linhas(con.execute(f"SELECT * FROM {v}").fetchall())
            b = _linhas(pg.execute(f"SELECT * FROM {v}").fetchall())
            if a != b:
                so_a = [x for x in a if x not in b][:2]
                so_b = [x for x in b if x not in a][:2]
                diferentes[v] = (len(a), len(b), so_a, so_b)
    assert len(views) == 73 and diferentes == {}


def test_importar_de_novo_e_recusado(demo_pg):
    banco, url, _ = demo_pg
    with pytest.raises(I.ErroImportacao, match="^A tabela execucoes do PostgreSQL já tem dados: a importação só vale para um banco vazio.$"):
        I.importar(banco, url)


def test_identidades_continuam_depois_dos_ids_importados(demo_pg):
    import psycopg
    _, url, _ = demo_pg
    with psycopg.connect(url) as pg:
        maximo = pg.execute("SELECT MAX(chamada_id) FROM chamadas").fetchone()[0]
        novo = pg.execute("SELECT nextval(pg_get_serial_sequence('chamadas', 'chamada_id'))").fetchone()[0]
        pg.rollback()
    assert novo == maximo + 1
