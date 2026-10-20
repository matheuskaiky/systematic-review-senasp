"""Gravacoes do painel no PostgreSQL (painel na nuvem, D96): os mesmos metodos do RepositorioSQLite (herdados), sobre a
conexao compativel. Nao aplica esquema (as migracoes fazem isso) e nao copia arquivo de banco: a recuperacao fica com o
historico e as branches do Neon. A coleta e a classificacao continuam no SQLite local."""
from adaptadores.postgres.conexao import ConexaoPostgres
from adaptadores.repositorio_sqlite import RepositorioSQLite


class RepositorioPostgres(RepositorioSQLite):
    def __init__(self, pool, chaves):
        self.conn = ConexaoPostgres(pool, chaves)

    def copia_de_seguranca(self, pasta, manter=10, sufixo="painel"):
        """Nada a copiar: o Neon guarda o historico do banco (restauracao por ponto no tempo e branches)."""
        return ""
