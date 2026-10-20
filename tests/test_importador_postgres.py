"""Importacao SQLite -> PostgreSQL (python main.py pg-demo; a copia de dados reais nao tem comando): ordem das chaves estrangeiras e as recusas,
todas antes de gravar ou com a transacao inteira desfeita (o destino continua vazio)."""
import shutil
import sqlite3
from datetime import datetime, timezone

import psycopg
import pytest

from adaptadores import migrador_postgres as M
from adaptadores.postgres import importador as I


@pytest.mark.parametrize("tabelas,pais,esperado", [
    (["a", "b", "c"], {}, ["a", "b", "c"]),                                   # sem chaves: ordem de criacao
    (["filho", "pai"], {"filho": {"pai"}}, ["pai", "filho"]),                # pai criado depois do filho
    (["c", "b", "a"], {"c": {"b"}, "b": {"a"}}, ["a", "b", "c"]),
    (["x", "y"], {"x": {"x"}}, ["x", "y"]),                                   # auto-referencia nao conta
    (["x", "y"], {"x": {"fora"}}, ["x", "y"]),                                # pai que nao vem do SQLite nao conta
])
def test_ordem_de_copia(tabelas, pais, esperado):
    assert I.ordem_de_copia(tabelas, pais) == esperado


def test_ordem_de_copia_com_ciclo():
    with pytest.raises(I.ErroImportacao) as e:
        I.ordem_de_copia(["a", "b", "c"], {"a": {"b"}, "b": {"a"}})
    assert str(e.value) == "Chaves estrangeiras em ciclo entre as tabelas: a, b."


def _vazio(url):
    with psycopg.connect(url) as c:
        tabelas = [t for (t,) in c.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' "
                                           "AND table_type = 'BASE TABLE' AND table_name <> 'versao_esquema'")]
        return all(not c.execute(f'SELECT EXISTS (SELECT 1 FROM "{t}")').fetchone()[0] for t in tabelas)


@pytest.fixture
def demo(copiar_demo):
    banco, _ = copiar_demo("importador_pg")
    return banco


@pytest.mark.postgres
def test_arquivo_inexistente(pg_url, tmp_path):
    M.aplicar(pg_url)
    falta = tmp_path / "nao_existe.db"
    with pytest.raises(I.ErroImportacao) as e:
        I.importar(falta, pg_url)
    assert str(e.value) == f"O arquivo SQLite {falta} não existe ou não pode ser lido."


@pytest.mark.postgres
def test_caminho_com_caracteres_de_uri(pg_url, demo, tmp_path):
    M.aplicar(pg_url)
    pasta = tmp_path / "a?b#c%20d"
    pasta.mkdir()
    shutil.copy(demo, pasta / "busca.db")
    relatorio = I.importar(pasta / "busca.db", pg_url)
    assert relatorio["achados"][0] == relatorio["achados"][1] > 0


@pytest.mark.postgres
def test_sem_esquema(pg_url, demo):
    with pytest.raises(I.ErroImportacao) as e:
        I.importar(demo, pg_url)
    assert str(e.value) == "O PostgreSQL ainda não tem o esquema: rode antes python main.py pg-migrar."


@pytest.mark.postgres
def test_mesma_tabela_nos_dois_arquivos(pg_url, demo):
    M.aplicar(pg_url)
    primeira = sqlite3.connect(demo).execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                                             "AND name <> 'meta_schema' ORDER BY rowid").fetchone()[0]
    with pytest.raises(I.ErroImportacao) as e:
        I.importar(demo, pg_url, demo)
    assert str(e.value) == f"A tabela {primeira} aparece nos dois arquivos SQLite: a importação recusa para não misturar dados."
    assert _vazio(pg_url)


@pytest.mark.postgres
def test_chave_estrangeira_sem_par(pg_url, demo):
    M.aplicar(pg_url)
    con = sqlite3.connect(demo)
    con.execute("UPDATE triagem SET artigo_id = 999999999 WHERE rowid = (SELECT MIN(rowid) FROM triagem)")
    con.commit()
    tabela, rowid, pai, _ = con.execute("PRAGMA foreign_key_check").fetchone()
    con.close()
    with pytest.raises(I.ErroImportacao) as e:
        I.importar(demo, pg_url)
    assert str(e.value) == (f"O SQLite tem linha com chave estrangeira sem par (tabela {tabela}, rowid {rowid}, aponta para {pai}): "
                            "corrija antes de importar.")
    assert _vazio(pg_url)


@pytest.mark.postgres
def test_falha_no_meio_da_copia_desfaz_tudo(pg_url, demo):
    M.aplicar(pg_url)
    con = sqlite3.connect(demo)
    con.execute("UPDATE artigos SET titulo = ? WHERE artigo_id = (SELECT MAX(artigo_id) FROM artigos)", ("com\x00nulo",))
    con.commit()
    con.close()
    with pytest.raises(I.ErroImportacao) as e:
        I.importar(demo, pg_url)
    assert str(e.value) == "A cópia da tabela artigos falhou e nada foi importado (código do PostgreSQL: sem código)."
    assert _vazio(pg_url)


@pytest.mark.postgres
def test_importa_pesquisa_e_contas(pg_url, demo, tmp_path):
    from adaptadores.contas_sqlite import ContasSQLite
    from dominio import autenticacao as A
    M.aplicar(pg_url)
    contas = ContasSQLite(tmp_path / "contas.db")
    contas.garantir_padrao()
    contas.definir_admin("chefe", "Coordenação", A.hash_senha("senha-de-teste-123"), datetime.now(timezone.utc).isoformat())
    relatorio = I.importar(demo, pg_url, tmp_path / "contas.db")
    assert relatorio["usuarios"] == (1, 1) and relatorio["grupos"][0] == len(A.GRUPOS_PADRAO)
    with psycopg.connect(pg_url) as c:
        assert c.execute("SELECT login FROM usuarios").fetchall() == [("chefe",)]
