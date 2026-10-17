"""Proteção de somente leitura do ambiente de pesquisa (`analises/conexao.py`), só com a biblioteca padrão.

O módulo não importa o pandas ao ser importado, então este teste roda no ambiente principal. Usa uma CÓPIA temporária
de um banco de exemplo; o `data/busca.db` real nunca é aberto aqui."""
import hashlib
import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent


def _carregar():
    especificacao = importlib.util.spec_from_file_location("analises_conexao", RAIZ / "analises" / "conexao.py")
    modulo = importlib.util.module_from_spec(especificacao)
    especificacao.loader.exec_module(modulo)
    return modulo


@pytest.fixture
def conexao():
    return _carregar()


@pytest.fixture
def banco(tmp_path):
    caminho = tmp_path / "copia.db"
    con = sqlite3.connect(caminho)
    con.executescript("""CREATE TABLE t (id INTEGER PRIMARY KEY, valor TEXT);
                         INSERT INTO t (valor) VALUES ('a'), ('b');
                         CREATE VIEW v AS SELECT valor FROM t;""")
    con.commit()
    con.close()
    return caminho


def _sha(caminho):
    return hashlib.sha256(Path(caminho).read_bytes()).hexdigest()


def test_importar_nao_traz_o_pandas():
    antes = "pandas" in sys.modules
    _carregar()
    assert ("pandas" in sys.modules) == antes


def test_le_tabela_e_view(conexao, banco):
    con = conexao.abrir(banco)
    assert [l["valor"] for l in conexao.consultar(con, "SELECT valor FROM v ORDER BY valor")] == ["a", "b"]
    assert conexao.existe(con, "t") and conexao.existe(con, "v") and not conexao.existe(con, "nada")
    assert conexao.consultar(con, "WITH x AS (SELECT 1 AS n) SELECT n FROM x")[0]["n"] == 1
    con.close()


@pytest.mark.parametrize("sql", [
    "INSERT INTO t (valor) VALUES ('x')", "UPDATE t SET valor = 'z'", "DELETE FROM t", "DROP TABLE t",
    "CREATE TABLE novo (a)", "PRAGMA query_only = OFF", "ATTACH DATABASE ':memory:' AS m", "VACUUM", "BEGIN",
    "SELECT 1; DELETE FROM t", "  -- comentario\n DELETE FROM t", "/* x */ UPDATE t SET valor = 'z'", "",
])
def test_recusa_o_que_nao_e_select(conexao, banco, sql):
    antes = _sha(banco)
    con = conexao.abrir(banco)
    with pytest.raises(conexao.ErroSomenteLeitura):
        conexao.consultar(con, sql)
    con.close()
    assert _sha(banco) == antes


def test_banco_recusa_gravar_mesmo_sem_a_protecao_do_modulo(conexao, banco):
    """A camada do próprio SQLite: usa a conexão direto (ignorando `consultar`) e tenta gravar."""
    antes = _sha(banco)
    con = conexao.abrir(banco)
    for sql in ("INSERT INTO t (valor) VALUES ('x')", "DELETE FROM t", "DROP VIEW v", "PRAGMA query_only = OFF"):
        with pytest.raises(sqlite3.DatabaseError):
            con.execute(sql)
    with pytest.raises(sqlite3.DatabaseError):
        con.executescript("DELETE FROM t")
    con.close()
    assert _sha(banco) == antes


def test_uri_somente_leitura_sozinha_recusa_gravar(banco):
    """Prova a camada 1 isolada: a URI `mode=ro` já impede a gravação."""
    con = sqlite3.connect(f"{banco.resolve().as_uri()}?mode=ro", uri=True)
    with pytest.raises(sqlite3.OperationalError):
        con.execute("INSERT INTO t (valor) VALUES ('x')")
    con.close()


def test_arquivo_inexistente_nao_e_criado(conexao, tmp_path):
    with pytest.raises(FileNotFoundError):
        conexao.abrir(tmp_path / "nao_existe.db")
    assert not (tmp_path / "nao_existe.db").exists()


def test_leitura_nao_altera_o_arquivo_nem_cria_arquivos_auxiliares(conexao, banco):
    antes = _sha(banco)
    con = conexao.abrir(banco)
    for _ in range(5):
        conexao.consultar(con, "SELECT * FROM t")
    con.close()
    assert _sha(banco) == antes
    assert sorted(p.name for p in banco.parent.iterdir()) == ["copia.db"]
