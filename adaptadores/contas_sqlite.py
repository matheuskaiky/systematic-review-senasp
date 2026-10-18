"""Adaptador SQLite para contas, grupos, permissões e sessões de usuários do painel."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3

from dominio import autenticacao

DDL_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS grupos (
    grupo_id INTEGER PRIMARY KEY,
    nome TEXT NOT NULL UNIQUE,
    fixo INTEGER NOT NULL DEFAULT 0,
    criado_em TEXT NOT NULL
)""",
    """CREATE TABLE IF NOT EXISTS grupo_permissoes (
    grupo_id INTEGER NOT NULL REFERENCES grupos(grupo_id),
    permissao TEXT NOT NULL,
    PRIMARY KEY (grupo_id, permissao)
)""",
    """CREATE TABLE IF NOT EXISTS usuarios (
    usuario_id INTEGER PRIMARY KEY,
    login TEXT NOT NULL UNIQUE,
    nome TEXT NOT NULL,
    grupo_id INTEGER NOT NULL REFERENCES grupos(grupo_id),
    senha_hash TEXT NOT NULL,
    ativo INTEGER NOT NULL DEFAULT 1,
    criado_em TEXT NOT NULL,
    ultimo_acesso TEXT,
    falhas_login INTEGER NOT NULL DEFAULT 0,
    bloqueado_ate TEXT
)""",
    "CREATE UNIQUE INDEX IF NOT EXISTS usuarios_nome_unico ON usuarios (lower(nome))",
    """CREATE TABLE IF NOT EXISTS sessoes (
    token_hash TEXT PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(usuario_id),
    criada_em TEXT NOT NULL,
    ultimo_uso TEXT NOT NULL
)""",
    "CREATE INDEX IF NOT EXISTS sessoes_por_usuario ON sessoes (usuario_id)",
    """CREATE TABLE IF NOT EXISTS auditoria_admin (
    id INTEGER PRIMARY KEY,
    quando TEXT NOT NULL,
    admin_login TEXT NOT NULL,
    acao TEXT NOT NULL,
    alvo TEXT,
    detalhe TEXT
)""",
    """CREATE TABLE IF NOT EXISTS configuracoes (
    chave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
)""",
)


class ContasSQLite:
    """Repositório de contas, sessões e permissões em banco SQLite dedicado."""

    def __init__(self, caminho: str | Path) -> None:
        self.caminho = Path(caminho)

    @contextmanager
    def _conexao(self, escrita: bool = False):
        conn = None
        try:
            conn = sqlite3.connect(self.caminho, isolation_level=None)
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA busy_timeout = 5000")
            if escrita:
                conn.execute("BEGIN IMMEDIATE")
            else:
                conn.execute("BEGIN")
            try:
                yield conn
                conn.execute("COMMIT")
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
        except sqlite3.OperationalError as e:
            raise autenticacao.ContasOcupadas(str(e)) from e
        finally:
            if conn is not None:
                conn.close()

    def garantir_padrao(self) -> None:
        """Cria pastas, esquema DDL e semeia os grupos padrão de forma atômica e idempotente."""
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        with self._conexao(escrita=True) as conn:
            for stmt in DDL_STATEMENTS:
                conn.execute(stmt)
            agora = datetime.now(timezone.utc).isoformat()
            for grupo, perms in autenticacao.GRUPOS_PADRAO.items():
                fixo = 1 if grupo in (autenticacao.GRUPO_ADMIN, autenticacao.GRUPO_VISITANTE) else 0
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO grupos (nome, fixo, criado_em) VALUES (?, ?, ?)",
                    (grupo, fixo, agora),
                )
                if cursor.rowcount == 1:
                    grupo_id = cursor.lastrowid
                    for p in sorted(perms):
                        conn.execute(
                            "INSERT INTO grupo_permissoes (grupo_id, permissao) VALUES (?, ?)",
                            (grupo_id, p),
                        )

    def permissoes_do_grupo(self, nome: str) -> set[str]:
        """Retorna o conjunto de permissões do grupo informado."""
        with self._conexao() as conn:
            cursor = conn.execute(
                "SELECT gp.permissao FROM grupo_permissoes gp JOIN grupos g USING (grupo_id) WHERE g.nome = ?",
                (nome,),
            )
            return {row[0] for row in cursor.fetchall()}

    def usuario_por_login(self, login: str) -> dict | None:
        """Busca usuário ativo ou inativo pelo login exato."""
        with self._conexao() as conn:
            row = conn.execute(
                "SELECT u.usuario_id, u.login, u.nome, g.nome, u.ativo, u.senha_hash, u.falhas_login, u.bloqueado_ate "
                "FROM usuarios u JOIN grupos g USING (grupo_id) WHERE u.login = ?",
                (login,),
            ).fetchone()
            if not row:
                return None
            return {
                "usuario_id": row[0],
                "login": row[1],
                "nome": row[2],
                "grupo": row[3],
                "ativo": row[4],
                "senha_hash": row[5],
                "falhas_login": row[6],
                "bloqueado_ate": row[7],
            }

    def usuario_da_sessao(self, token_hash: str, agora: str) -> dict | None:
        """Valida a sessão por ociosidade (12h) e usuário ativo, atualizando acessos."""
        with self._conexao(escrita=True) as conn:
            row = conn.execute(
                "SELECT s.token_hash, s.usuario_id, s.ultimo_uso, u.login, u.nome, u.ativo, g.nome, g.grupo_id "
                "FROM sessoes s JOIN usuarios u USING (usuario_id) JOIN grupos g USING (grupo_id) "
                "WHERE s.token_hash = ?",
                (token_hash,),
            ).fetchone()
            if not row:
                return None

            _, usuario_id, ultimo_uso_str, login, nome, ativo, grupo_nome, grupo_id = row
            if ativo != 1:
                conn.execute("DELETE FROM sessoes WHERE usuario_id = ?", (usuario_id,))
                return None

            ultimo_uso_dt = autenticacao.ler_instante(ultimo_uso_str)
            agora_dt = autenticacao.ler_instante(agora)
            if ultimo_uso_dt is None or agora_dt is None or (agora_dt - ultimo_uso_dt) >= timedelta(hours=autenticacao.HORAS_DE_SESSAO):
                conn.execute("DELETE FROM sessoes WHERE token_hash = ?", (token_hash,))
                return None

            if (agora_dt - ultimo_uso_dt) > timedelta(seconds=60):
                conn.execute("UPDATE sessoes SET ultimo_uso = ? WHERE token_hash = ?", (agora, token_hash))
                conn.execute("UPDATE usuarios SET ultimo_acesso = ? WHERE usuario_id = ?", (agora, usuario_id))

            cur_p = conn.execute("SELECT permissao FROM grupo_permissoes WHERE grupo_id = ?", (grupo_id,))
            permissoes = {r[0] for r in cur_p.fetchall()}

            return {
                "usuario_id": usuario_id,
                "login": login,
                "nome": nome,
                "grupo": grupo_nome,
                "permissoes": permissoes,
            }

    def registrar_falha(self, usuario_id: int, agora: str) -> None:
        """Registra falha de login e bloqueia a conta temporariamente na 5ª falha."""
        agora_dt = autenticacao.ler_instante(agora)
        bloq_ate = (agora_dt + timedelta(minutes=autenticacao.MINUTOS_DE_BLOQUEIO)).isoformat()
        with self._conexao(escrita=True) as conn:
            conn.execute(
                "UPDATE usuarios SET "
                "falhas_login = CASE WHEN falhas_login + 1 >= 5 THEN 0 ELSE falhas_login + 1 END, "
                "bloqueado_ate = CASE WHEN falhas_login + 1 >= 5 THEN ? ELSE bloqueado_ate END "
                "WHERE usuario_id = ?",
                (bloq_ate, usuario_id),
            )

    def abrir_sessao(self, usuario_id: int, token_hash: str, agora: str) -> None:
        """Registra nova sessão, zera falhas e remove bloqueios de login."""
        with self._conexao(escrita=True) as conn:
            conn.execute(
                "INSERT INTO sessoes (token_hash, usuario_id, criada_em, ultimo_uso) VALUES (?, ?, ?, ?)",
                (token_hash, usuario_id, agora, agora),
            )
            conn.execute(
                "UPDATE usuarios SET falhas_login = 0, bloqueado_ate = NULL, ultimo_acesso = ? WHERE usuario_id = ?",
                (agora, usuario_id),
            )

    def fechar_sessao(self, token_hash: str) -> None:
        """Remove a sessão do banco se ela existir."""
        with self._conexao(escrita=True) as conn:
            conn.execute("DELETE FROM sessoes WHERE token_hash = ?", (token_hash,))

    def criar_usuario(self, login: str, nome: str, grupo_id: int, senha_hash: str, agora: str) -> int:
        """Cria novo usuário validando login único, nome único insensível e grupo existente nesta ordem."""
        with self._conexao(escrita=True) as conn:
            if conn.execute("SELECT 1 FROM usuarios WHERE login = ?", (login,)).fetchone():
                raise ValueError(f"Login já existe: {login}")
            nome_cf = nome.casefold()
            for row in conn.execute("SELECT nome FROM usuarios").fetchall():
                if row[0].casefold() == nome_cf:
                    raise ValueError(f"Nome já existe: {nome}")
            if not conn.execute("SELECT 1 FROM grupos WHERE grupo_id = ?", (grupo_id,)).fetchone():
                raise ValueError(f"Grupo não existe: {grupo_id}")
            cursor = conn.execute(
                "INSERT INTO usuarios (login, nome, grupo_id, senha_hash, ativo, criado_em, falhas_login) "
                "VALUES (?, ?, ?, ?, 1, ?, 0)",
                (login, nome, grupo_id, senha_hash, agora),
            )
            return cursor.lastrowid

    def existe_admin_ativo(self) -> bool:
        """Indica se existe pelo menos um administrador ativo cadastrado."""
        with self._conexao() as conn:
            row = conn.execute(
                "SELECT 1 FROM usuarios u JOIN grupos g USING (grupo_id) "
                "WHERE g.nome = ? AND u.ativo = 1 LIMIT 1",
                (autenticacao.GRUPO_ADMIN,),
            ).fetchone()
            return row is not None

    def definir_admin(self, login: str, nome: str, senha_hash: str, agora: str) -> str:
        """Cria administrador ou redefine senha/nome de administrador existente."""
        self.garantir_padrao()
        with self._conexao(escrita=True) as conn:
            row_g = conn.execute("SELECT grupo_id FROM grupos WHERE nome = ?", (autenticacao.GRUPO_ADMIN,)).fetchone()
            admin_grupo_id = row_g[0]

            row_u = conn.execute("SELECT usuario_id FROM usuarios WHERE login = ?", (login,)).fetchone()
            nome_cf = nome.casefold()
            if row_u is None:
                for row in conn.execute("SELECT nome FROM usuarios").fetchall():
                    if row[0].casefold() == nome_cf:
                        raise ValueError(f"Nome já existe: {nome}")
                conn.execute(
                    "INSERT INTO usuarios (login, nome, grupo_id, senha_hash, ativo, criado_em, falhas_login) "
                    "VALUES (?, ?, ?, ?, 1, ?, 0)",
                    (login, nome, admin_grupo_id, senha_hash, agora),
                )
                return "criado"
            else:
                usuario_id = row_u[0]
                for uid, n in conn.execute("SELECT usuario_id, nome FROM usuarios WHERE usuario_id != ?", (usuario_id,)).fetchall():
                    if n.casefold() == nome_cf:
                        raise ValueError(f"Nome já existe: {nome}")
                conn.execute(
                    "UPDATE usuarios SET nome = ?, senha_hash = ?, grupo_id = ?, ativo = 1, falhas_login = 0, bloqueado_ate = NULL "
                    "WHERE usuario_id = ?",
                    (nome, senha_hash, admin_grupo_id, usuario_id),
                )
                conn.execute("DELETE FROM sessoes WHERE usuario_id = ?", (usuario_id,))
                return "atualizado"
