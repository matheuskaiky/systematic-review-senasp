"""Conexão SOMENTE LEITURA com data/busca.db para o ambiente de pesquisa.

Garantias, em camadas (qualquer uma sozinha já impediria a gravação):
1. o arquivo é aberto pela URI `file:...?mode=ro` (o SQLite recusa gravar);
2. `PRAGMA query_only = ON`;
3. um autorizador do SQLite (`set_authorizer`) que só aceita leitura (SELECT, leitura de coluna, funções);
   PRAGMA, ATTACH, INSERT, UPDATE, DELETE, DDL e transações são negados;
4. `consultar` só aceita um único comando que comece por SELECT ou WITH.

Este módulo usa só a biblioteca padrão no momento da importação: o pandas é importado dentro das funções que
devolvem DataFrame, para que a proteção seja testável sem as bibliotecas extras.
"""
import re
import sqlite3
from pathlib import Path

CAMINHO_PADRAO = Path(__file__).resolve().parent.parent / "data" / "busca.db"


class ErroSomenteLeitura(Exception):
    """Tentativa de executar algo que não seja uma consulta de leitura."""


# Ações do SQLite que uma consulta de leitura pode usar. Tudo o mais é negado.
_ACOES_PERMITIDAS = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION}
if hasattr(sqlite3, "SQLITE_RECURSIVE"):
    _ACOES_PERMITIDAS.add(sqlite3.SQLITE_RECURSIVE)


def _autorizador(acao, arg1, arg2, banco, gatilho):
    return sqlite3.SQLITE_OK if acao in _ACOES_PERMITIDAS else sqlite3.SQLITE_DENY


def _sem_comentarios(sql):
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    return re.sub(r"--[^\n]*", " ", sql).strip()


def exigir_leitura(sql):
    """Levanta ErroSomenteLeitura se `sql` não for um único SELECT (ou WITH ... SELECT)."""
    limpo = _sem_comentarios(str(sql)).rstrip(";").strip()
    if not re.match(r"(?i)^(select|with)\b", limpo):
        raise ErroSomenteLeitura("somente consultas SELECT são permitidas neste ambiente (banco aberto só para leitura)")
    if ";" in limpo:
        raise ErroSomenteLeitura("um único comando por consulta; ';' no meio do texto não é permitido")
    return limpo


def abrir(caminho=None):
    """Abre o banco só para leitura. `caminho`: arquivo .db (padrão: data/busca.db da raiz do projeto)."""
    caminho = Path(caminho) if caminho else CAMINHO_PADRAO
    if not caminho.is_file():
        raise FileNotFoundError(f"banco não encontrado: {caminho}")
    con = sqlite3.connect(f"{caminho.resolve().as_uri()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only = ON")
    con.set_authorizer(_autorizador)   # depois do PRAGMA: a partir daqui PRAGMA também é negado
    return con


def _executar(con, sql, args):
    sql = exigir_leitura(sql)
    try:
        cursor = con.execute(sql, tuple(args))
        return cursor.fetchall(), [d[0] for d in cursor.description]
    except sqlite3.DatabaseError as erro:
        if "not authorized" in str(erro).lower() or "readonly" in str(erro).lower():
            raise ErroSomenteLeitura(f"operação negada (banco somente leitura): {erro}") from erro
        raise


def consultar(con, sql, args=()):
    """Executa uma consulta de leitura e devolve a lista de sqlite3.Row. Recusa qualquer outra coisa."""
    return _executar(con, sql, args)[0]


def tabela(con, sql, args=()):
    """Resultado de uma consulta como DataFrame do pandas (importado aqui, só quando necessário)."""
    import pandas as pd
    linhas, colunas = _executar(con, sql, args)
    return pd.DataFrame([tuple(l) for l in linhas], columns=colunas)


def existe(con, nome):
    """True se a tabela ou a view `nome` existe no banco."""
    return bool(consultar(con, "SELECT 1 FROM sqlite_master WHERE name = ? AND type IN ('table', 'view')", (nome,)))


# ---------- tabelas e views principais ----------

def achados(con):
    """`r_achados`: achados da classificação vigente das execuções do relatório."""
    return tabela(con, "SELECT * FROM r_achados")


def classificacoes(con):
    """`r_classificacoes`: classificação vigente (uma por url_id e uf)."""
    return tabela(con, "SELECT * FROM r_classificacoes")


def classificacoes_historico(con):
    """`r_classificacoes_historico`: toda classificação feita (desempenho e custo do classificador)."""
    return tabela(con, "SELECT * FROM r_classificacoes_historico")


def artigos(con):
    return tabela(con, "SELECT * FROM r_artigos")


def termos(con):
    return tabela(con, "SELECT * FROM v_termos")


def ocorrencias(con):
    return tabela(con, "SELECT * FROM r_ocorrencias")


def triagem_escopo_atual(con, fonte=None, somente_validos=True):
    """Veredito atual da triagem de escopo: a linha de maior `id` por (fonte, item_id, uf); com `somente_validos`,
    só as de valido = 1 (convenção do projeto, a mesma de v_prisma). `fonte`: 'artigo', 'web' ou None (todas)."""
    sql = ("SELECT * FROM triagem_escopo WHERE id IN (SELECT MAX(id) FROM triagem_escopo GROUP BY fonte, item_id, uf)")
    args = []
    if somente_validos:
        sql += " AND valido = 1"
    if fonte:
        sql += " AND fonte = ?"
        args.append(fonte)
    return tabela(con, sql, args)


def triagem(con):
    """`triagem`: decisões humanas por artigo (hoje costuma estar vazia)."""
    return tabela(con, "SELECT * FROM triagem")


def chamadas(con):
    """`r_chamadas`: chamadas das execuções do relatório."""
    return tabela(con, "SELECT * FROM r_chamadas")


def curva_descoberta(con):
    return tabela(con, "SELECT * FROM v_curva_descoberta ORDER BY chamada_id")
