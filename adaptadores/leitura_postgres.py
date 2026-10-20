"""Leituras do painel no PostgreSQL (painel na nuvem, D96): as mesmas consultas da LeituraPainelSQLite (herdadas), sobre
a conexao compativel, cada uma numa transacao somente leitura com conexao emprestada do pool."""
from adaptadores.leitura_sqlite import LeituraPainelSQLite
from adaptadores.postgres.conexao import ConexaoPostgres


class LeituraPainelPostgres(LeituraPainelSQLite):
    def __init__(self, pool, chaves):
        self._pool = pool
        self._chaves = chaves
        self._caminho = None

    def existe(self):
        """O esquema e conferido ao subir o painel (versao das migracoes); aqui o banco sempre existe."""
        return True

    def _consulta(self, sql, args=()):
        conn = ConexaoPostgres(self._pool, self._chaves)
        try:
            conn.somente_leitura()
            return [dict(l) for l in conn.execute(sql, args).fetchall()]
        finally:
            conn.close()
