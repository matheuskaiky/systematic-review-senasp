"""Contas, sessoes e permissoes do painel no PostgreSQL (painel na nuvem, D96). As mesmas regras do ContasSQLite (o
codigo e o mesmo, herdado), sobre a conexao compativel: BEGIN IMMEDIATE vira a trava consultiva da transacao e o
esquema vem das migracoes (nunca e criado aqui). A trava das contas e separada da das gravacoes da pesquisa (no SQLite
eram dois arquivos): um login nunca espera uma decisao demorada."""
from contextlib import contextmanager
import sqlite3

from adaptadores.contas_sqlite import ContasSQLite
from adaptadores.postgres.conexao import TRAVA_CONTAS, ConexaoPostgres
from dominio import autenticacao


class ContasPostgres(ContasSQLite):
    def __init__(self, pool, chaves) -> None:
        self._pool = pool
        self._chaves = chaves
        self.caminho = None

    @contextmanager
    def _conexao(self, escrita: bool = False):
        conn = None
        try:
            conn = ConexaoPostgres(self._pool, self._chaves, trava=TRAVA_CONTAS)
            conn.execute("BEGIN IMMEDIATE" if escrita else "BEGIN")
            try:
                yield conn
                conn.commit()
            except BaseException:
                try:
                    if conn.in_transaction:
                        conn.rollback()
                except Exception:                  # o erro original e o que importa (o desfazer nao o esconde)
                    pass
                raise
        except sqlite3.OperationalError as e:      # pool esgotado, banco fora do ar ou trava: "contas ocupadas"
            raise autenticacao.ContasOcupadas(str(e)) from e
        finally:
            if conn is not None:
                conn.close()

    def garantir_padrao(self) -> None:
        """Só semeia os grupos padrão (as tabelas vêm de python main.py pg-migrar)."""
        with self._conexao(escrita=True) as conn:
            self._semear_grupos(conn)
