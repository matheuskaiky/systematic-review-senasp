"""Adaptador SQLite para contas, grupos, permissões e sessões de usuários do painel."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3

from dominio import autenticacao, divulgacao
from infra.sqlite_wal import ligar_wal

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
    """CREATE TABLE IF NOT EXISTS tokens_api (
    usuario_id INTEGER PRIMARY KEY REFERENCES usuarios(usuario_id),
    token_hash TEXT NOT NULL UNIQUE,
    inicio TEXT NOT NULL,
    criado_em TEXT NOT NULL,
    ultimo_uso TEXT
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
            ligar_wal(conn, self.caminho)                  # leitores nao esperam quem grava; so troca uma vez
            conn.execute("PRAGMA synchronous = FULL")
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
            self._semear_grupos(conn)

    def _semear_grupos(self, conn) -> None:
        """Grupos padrão e suas permissões; não mexe em grupo que já existe (idempotente)."""
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
        """Valida a sessão por ociosidade (12h), validade absoluta (7 dias desde a criação) e usuário ativo, atualizando acessos.
        Criação ou último uso ilegíveis ou no futuro invalidam a sessão; a sessão nunca renovada (último uso igual à criação) tolera até TOLERANCIA_RELOGIO_NA_CRIACAO_SEGUNDOS de relógio atrasado (RI38)."""
        with self._conexao(escrita=True) as conn:
            row = conn.execute(
                "SELECT s.token_hash, s.usuario_id, s.ultimo_uso, u.login, u.nome, u.ativo, g.nome, g.grupo_id, s.criada_em "
                "FROM sessoes s JOIN usuarios u USING (usuario_id) JOIN grupos g USING (grupo_id) "
                "WHERE s.token_hash = ?",
                (token_hash,),
            ).fetchone()
            if not row:
                return None

            _, usuario_id, ultimo_uso_str, login, nome, ativo, grupo_nome, grupo_id, criada_em_str = row
            if ativo != 1:
                conn.execute("DELETE FROM sessoes WHERE usuario_id = ?", (usuario_id,))
                return None

            ultimo_uso_dt = autenticacao.ler_instante(ultimo_uso_str)
            agora_dt = autenticacao.ler_instante(agora)
            criada_dt = autenticacao.ler_instante(criada_em_str)
            if ultimo_uso_dt is None or agora_dt is None or criada_dt is None:
                conn.execute("DELETE FROM sessoes WHERE token_hash = ?", (token_hash,))
                return None

            recem_criada = (ultimo_uso_dt == criada_dt)
            limite = agora_dt + timedelta(seconds=autenticacao.TOLERANCIA_RELOGIO_NA_CRIACAO_SEGUNDOS) if recem_criada else agora_dt
            if (criada_dt > limite or ultimo_uso_dt > limite
                    or (agora_dt - ultimo_uso_dt) >= timedelta(hours=autenticacao.HORAS_DE_SESSAO)
                    or (agora_dt - criada_dt) >= timedelta(days=autenticacao.DIAS_MAXIMOS_DE_SESSAO)):
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

    def reservar_tentativa(self, login: str, agora: str) -> dict:
        """Reserva uma tentativa de login antes de conferir a senha, numa transacao so: varios pedidos simultaneos para o
        mesmo login nunca conferem mais de FALHAS_ATE_BLOQUEIO senhas por janela de bloqueio. A tentativa reservada conta
        como falha ate o acerto (abrir_sessao zera); a reserva que leva a contagem a FALHAS_ATE_BLOQUEIO ja grava o bloqueio,
        que vence sozinho em MINUTOS_DE_BLOQUEIO (nenhuma conta fica bloqueada para sempre se a conferencia nao terminar).
        Uma contagem gravada que nao e inteiro >= 0 conta como cheia (bloqueia ja, com prazo).
        Devolve {"situacao": "inexistente" | "bloqueado" | "reservado", "usuario": dict | None}."""
        agora_dt = autenticacao.ler_instante(agora)
        bloq_ate = (agora_dt + timedelta(minutes=autenticacao.MINUTOS_DE_BLOQUEIO)).isoformat()
        with self._conexao(escrita=True) as conn:
            row = conn.execute(
                "SELECT u.usuario_id, u.login, u.nome, g.nome, u.ativo, u.senha_hash, u.falhas_login, u.bloqueado_ate "
                "FROM usuarios u JOIN grupos g USING (grupo_id) WHERE u.login = ?",
                (login,),
            ).fetchone()
            if not row or row[4] != 1:
                return {"situacao": "inexistente", "usuario": None}
            falhas = row[6]
            if type(falhas) is not int or falhas < 0:
                falhas = autenticacao.FALHAS_ATE_BLOQUEIO    # contagem que o painel nao gravaria: conta como cheia
            bloq_dt = autenticacao.ler_instante(row[7])
            if bloq_dt is not None and bloq_dt > agora_dt:
                return {"situacao": "bloqueado", "usuario": None}
            if bloq_dt is not None:
                falhas = 0                              # o bloqueio venceu: a contagem recomeca
            if falhas >= autenticacao.FALHAS_ATE_BLOQUEIO:
                # contagem cheia sem bloqueio gravado (estado antigo): bloqueia agora, com prazo
                conn.execute("UPDATE usuarios SET bloqueado_ate = ? WHERE usuario_id = ?", (bloq_ate, row[0]))
                return {"situacao": "bloqueado", "usuario": None}
            falhas += 1
            conn.execute("UPDATE usuarios SET falhas_login = ?, bloqueado_ate = ? WHERE usuario_id = ?",
                         (falhas, bloq_ate if falhas >= autenticacao.FALHAS_ATE_BLOQUEIO else None, row[0]))
            return {"situacao": "reservado", "usuario": {
                "usuario_id": row[0], "login": row[1], "nome": row[2], "grupo": row[3], "ativo": row[4],
                "senha_hash": row[5], "falhas_login": falhas, "bloqueado_ate": None}}

    def abrir_sessao(self, usuario_id: int, token_hash: str, agora: str, senha_hash: str | None = None) -> bool:
        """Registra nova sessão, zera falhas e remove bloqueios de login. Com `senha_hash` (o hash que acabou de ser
        conferido), só abre se o usuário continua ativo e com essa mesma senha: uma senha redefinida no meio do login não
        abre sessão com a senha antiga. Devolve se abriu."""
        with self._conexao(escrita=True) as conn:
            if senha_hash is not None and not conn.execute(
                    "SELECT 1 FROM usuarios WHERE usuario_id = ? AND ativo = 1 AND senha_hash = ?",
                    (usuario_id, senha_hash)).fetchone():
                return False
            conn.execute(
                "INSERT INTO sessoes (token_hash, usuario_id, criada_em, ultimo_uso) VALUES (?, ?, ?, ?)",
                (token_hash, usuario_id, agora, agora),
            )
            conn.execute(
                "UPDATE usuarios SET falhas_login = 0, bloqueado_ate = NULL, ultimo_acesso = ? WHERE usuario_id = ?",
                (agora, usuario_id),
            )
            return True

    def fechar_sessao(self, token_hash: str) -> None:
        """Remove a sessão do banco se ela existir."""
        with self._conexao(escrita=True) as conn:
            conn.execute("DELETE FROM sessoes WHERE token_hash = ?", (token_hash,))

    def _gravar_auditoria(self, conn, auditoria: tuple | None) -> None:
        if not auditoria:
            return
        admin_login, acao, alvo, detalhe, agora = auditoria
        if acao not in autenticacao.ACOES_AUDITORIA:
            raise ValueError(f"Ação de auditoria desconhecida: {acao}")
        conn.execute(
            "INSERT INTO auditoria_admin (quando, admin_login, acao, alvo, detalhe) VALUES (?, ?, ?, ?, ?)",
            (agora, admin_login, acao, alvo, detalhe),
        )

    def auditar(self, admin_login: str, acao: str, alvo: str | None, detalhe: str | None, agora: str) -> None:
        """Insere um registro de auditoria validando a ação."""
        with self._conexao(escrita=True) as conn:
            self._gravar_auditoria(conn, (admin_login, acao, alvo, detalhe, agora))

    def auditoria(self, limite: int = 200) -> list[dict]:
        """Retorna os registros de auditoria mais recentes (ORDER BY id DESC LIMIT ?)."""
        with self._conexao() as conn:
            rows = conn.execute(
                "SELECT quando, admin_login, acao, alvo, detalhe FROM auditoria_admin ORDER BY id DESC LIMIT ?",
                (limite,),
            ).fetchall()
            return [
                {
                    "quando": r[0],
                    "admin_login": r[1],
                    "acao": r[2],
                    "alvo": r[3],
                    "detalhe": r[4],
                }
                for r in rows
            ]

    def listar_usuarios(self) -> list[dict]:
        """Retorna lista de todos os usuários ordenados por lower(nome)."""
        with self._conexao() as conn:
            rows = conn.execute(
                "SELECT u.usuario_id, u.login, u.nome, g.nome, u.grupo_id, u.ativo, u.ultimo_acesso, u.criado_em, "
                "t.inicio, t.criado_em, t.ultimo_uso "
                "FROM usuarios u JOIN grupos g USING (grupo_id) LEFT JOIN tokens_api t ON t.usuario_id = u.usuario_id "
                "ORDER BY lower(u.nome)"
            ).fetchall()
            return [
                {
                    "usuario_id": r[0],
                    "login": r[1],
                    "nome": r[2],
                    "grupo": r[3],
                    "grupo_id": r[4],
                    "ativo": r[5],
                    "ultimo_acesso": r[6],
                    "criado_em": r[7],
                    "token": {"inicio": r[8], "criado_em": r[9], "ultimo_uso": r[10]} if r[8] is not None else None,
                }
                for r in rows
            ]

    def usuario(self, usuario_id: int) -> dict | None:
        """Retorna os dados do usuário ou None se não existir."""
        with self._conexao() as conn:
            row = conn.execute(
                "SELECT u.usuario_id, u.login, u.nome, g.nome, u.grupo_id, u.ativo, u.ultimo_acesso, u.criado_em, "
                "t.inicio, t.criado_em, t.ultimo_uso "
                "FROM usuarios u JOIN grupos g USING (grupo_id) LEFT JOIN tokens_api t ON t.usuario_id = u.usuario_id "
                "WHERE u.usuario_id = ?",
                (usuario_id,),
            ).fetchone()
            if not row:
                return None
            return {
                "usuario_id": row[0],
                "login": row[1],
                "nome": row[2],
                "grupo": row[3],
                "grupo_id": row[4],
                "ativo": row[5],
                "ultimo_acesso": row[6],
                "criado_em": row[7],
                "token": {"inicio": row[8], "criado_em": row[9], "ultimo_uso": row[10]} if row[8] is not None else None,
            }

    def grupos(self) -> list[dict]:
        """Retorna grupos ordenados: Administrador, Visitante, depois demais por lower(nome)."""
        with self._conexao() as conn:
            grupos_linhas = conn.execute(
                "SELECT grupo_id, nome, fixo FROM grupos "
                "ORDER BY CASE WHEN nome = ? THEN 1 WHEN nome = ? THEN 2 ELSE 3 END, lower(nome)",
                (autenticacao.GRUPO_ADMIN, autenticacao.GRUPO_VISITANTE),
            ).fetchall()
            perms_linhas = conn.execute("SELECT grupo_id, permissao FROM grupo_permissoes").fetchall()
            perms_map = {}
            for gid, p in perms_linhas:
                perms_map.setdefault(gid, set()).add(p)
            return [
                {
                    "grupo_id": gid,
                    "nome": nome,
                    "fixo": fixo,
                    "permissoes": perms_map.get(gid, set()),
                }
                for gid, nome, fixo in grupos_linhas
            ]

    def contar_admins_ativos(self) -> int:
        """Retorna o número de administradores ativos."""
        with self._conexao() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM usuarios u JOIN grupos g USING (grupo_id) "
                "WHERE g.nome = ? AND u.ativo = 1",
                (autenticacao.GRUPO_ADMIN,),
            ).fetchone()
            return row[0]

    def criar_usuario(self, login: str, nome: str, grupo_id: int, senha_hash: str, agora: str, auditoria: tuple | None = None) -> int:
        """Cria novo usuário validando login único, nome único insensível e grupo existente nesta ordem."""
        with self._conexao(escrita=True) as conn:
            if conn.execute("SELECT 1 FROM usuarios WHERE login = ?", (login,)).fetchone():
                raise ValueError(f"Login já existe: {login}")
            nome_cf = nome.casefold()
            for row in conn.execute("SELECT nome FROM usuarios").fetchall():
                if row[0].casefold() == nome_cf:
                    raise ValueError(f"Nome já existe: {nome}")
            row_g = conn.execute("SELECT grupo_id, nome FROM grupos WHERE grupo_id = ?", (grupo_id,)).fetchone()
            if not row_g:
                raise ValueError(f"Grupo não existe: {grupo_id}")
            if row_g[1] == autenticacao.GRUPO_VISITANTE:
                raise ValueError("O grupo Visitante não recebe usuários.")
            cursor = conn.execute(
                "INSERT INTO usuarios (login, nome, grupo_id, senha_hash, ativo, criado_em, falhas_login) "
                "VALUES (?, ?, ?, ?, 1, ?, 0)",
                (login, nome, grupo_id, senha_hash, agora),
            )
            self._gravar_auditoria(conn, auditoria)
            return cursor.lastrowid

    def editar_usuario(self, usuario_id: int, login: str, nome: str, grupo_id: int, auditoria: tuple | None = None) -> None:
        """Edita login, nome e grupo do usuário validando unicidade e existência do grupo."""
        with self._conexao(escrita=True) as conn:
            if conn.execute("SELECT 1 FROM usuarios WHERE login = ? AND usuario_id != ?", (login, usuario_id)).fetchone():
                raise ValueError(f"Login já existe: {login}")
            nome_cf = nome.casefold()
            for row in conn.execute("SELECT usuario_id, nome FROM usuarios WHERE usuario_id != ?", (usuario_id,)).fetchall():
                if row[1].casefold() == nome_cf:
                    raise ValueError(f"Nome já existe: {nome}")
            row_g = conn.execute("SELECT grupo_id, nome FROM grupos WHERE grupo_id = ?", (grupo_id,)).fetchone()
            if not row_g:
                raise ValueError(f"Grupo não existe: {grupo_id}")
            if row_g[1] == autenticacao.GRUPO_VISITANTE:
                raise ValueError("O grupo Visitante não recebe usuários.")
            era_admin = self._admin_ativo(conn, usuario_id)
            conn.execute(
                "UPDATE usuarios SET login = ?, nome = ?, grupo_id = ? WHERE usuario_id = ?",
                (login, nome, grupo_id, usuario_id),
            )
            self._exigir_admin_ativo(conn, era_admin)
            self._gravar_auditoria(conn, auditoria)

    def redefinir_senha(self, usuario_id: int, senha_hash: str, auditoria: tuple | None = None) -> None:
        """Redefine senha, zera falhas e bloqueio, e remove sessões e o token de envio do usuário."""
        with self._conexao(escrita=True) as conn:
            conn.execute(
                "UPDATE usuarios SET senha_hash = ?, falhas_login = 0, bloqueado_ate = NULL WHERE usuario_id = ?",
                (senha_hash, usuario_id),
            )
            conn.execute("DELETE FROM sessoes WHERE usuario_id = ?", (usuario_id,))
            conn.execute("DELETE FROM tokens_api WHERE usuario_id = ?", (usuario_id,))   # conta recuperada: o envio tambem
            self._gravar_auditoria(conn, auditoria)

    def definir_ativo(self, usuario_id: int, ativo: int, auditoria: tuple | None = None) -> None:
        """Define situação ativa/desativada do usuário; quando desativa, encerra as sessões e apaga o token de envio."""
        with self._conexao(escrita=True) as conn:
            era_admin = self._admin_ativo(conn, usuario_id)
            conn.execute("UPDATE usuarios SET ativo = ? WHERE usuario_id = ?", (ativo, usuario_id))
            self._exigir_admin_ativo(conn, era_admin)
            if ativo == 0:
                conn.execute("DELETE FROM sessoes WHERE usuario_id = ?", (usuario_id,))
                conn.execute("DELETE FROM tokens_api WHERE usuario_id = ?", (usuario_id,))   # conta desativada nao envia
            self._gravar_auditoria(conn, auditoria)

    def gravar_token(self, usuario_id: int, token_hash: str, inicio: str, agora: str, auditoria: tuple | None = None) -> bool:
        """Grava o token de envio do usuário (só o hash e o começo), trocando o anterior se havia. Devolve True quando
        trocou um anterior. ValueError se o usuário não existe ou está desativado."""
        with self._conexao(escrita=True) as conn:
            ativo = conn.execute("SELECT ativo FROM usuarios WHERE usuario_id = ?", (usuario_id,)).fetchone()
            if ativo is None or ativo[0] != 1:
                raise ValueError("Conta inexistente ou desativada: não pode ter token.")
            trocou = conn.execute("DELETE FROM tokens_api WHERE usuario_id = ?", (usuario_id,)).rowcount == 1
            conn.execute("INSERT INTO tokens_api (usuario_id, token_hash, inicio, criado_em) VALUES (?, ?, ?, ?)",
                         (usuario_id, token_hash, inicio, agora))
            if auditoria is not None:
                quem, acao, alvo, _, quando = auditoria
                auditoria = (quem, acao, alvo, "substituiu o token anterior" if trocou else None, quando)
            self._gravar_auditoria(conn, auditoria)
            return trocou

    def revogar_token(self, usuario_id: int, auditoria: tuple | None = None) -> bool:
        """Apaga o token de envio do usuário. Devolve True se havia um; sem token, não grava nada (nem auditoria)."""
        with self._conexao(escrita=True) as conn:
            apagou = conn.execute("DELETE FROM tokens_api WHERE usuario_id = ?", (usuario_id,)).rowcount == 1
            if apagou:
                self._gravar_auditoria(conn, auditoria)
            return apagou

    def usuario_do_token(self, token_hash: str) -> dict | None:
        """O dono ativo do token de envio ({usuario_id, login, nome, grupo, permissoes}) ou None. Só lê (sem a trava de
        gravação das contas): um token inventado não segura os logins."""
        with self._conexao() as conn:
            row = conn.execute(
                "SELECT u.usuario_id, u.login, u.nome, u.ativo, g.nome, g.grupo_id FROM tokens_api t "
                "JOIN usuarios u USING (usuario_id) JOIN grupos g USING (grupo_id) WHERE t.token_hash = ?",
                (token_hash,),
            ).fetchone()
            if not row or row[3] != 1:
                return None
            permissoes = {r[0] for r in conn.execute("SELECT permissao FROM grupo_permissoes WHERE grupo_id = ?", (row[5],))}
            return {"usuario_id": row[0], "login": row[1], "nome": row[2], "grupo": row[4], "permissoes": permissoes}

    def registrar_uso_do_token(self, token_hash: str, agora: str) -> None:
        """Último uso = o último envio aceito pela nuvem."""
        with self._conexao(escrita=True) as conn:
            conn.execute("UPDATE tokens_api SET ultimo_uso = ? WHERE token_hash = ?", (agora, token_hash))

    def token_do_usuario(self, usuario_id: int) -> dict | None:
        """{inicio, criado_em, ultimo_uso} do token de envio do usuário, ou None."""
        with self._conexao() as conn:
            r = conn.execute("SELECT inicio, criado_em, ultimo_uso FROM tokens_api WHERE usuario_id = ?", (usuario_id,)).fetchone()
            return {"inicio": r[0], "criado_em": r[1], "ultimo_uso": r[2]} if r else None

    @staticmethod
    def _admin_ativo(conn, usuario_id: int) -> bool:
        return conn.execute("SELECT 1 FROM usuarios u JOIN grupos g USING (grupo_id) WHERE u.usuario_id = ? AND g.nome = ? "
                            "AND u.ativo = 1", (usuario_id, autenticacao.GRUPO_ADMIN)).fetchone() is not None

    @staticmethod
    def _exigir_admin_ativo(conn, era_admin: bool) -> None:
        """Dentro da mesma transacao da mudanca: se ela tirou um administrador ativo e nao sobrou nenhum, e desfeita com esta
        mensagem (dois administradores rebaixando um ao outro ao mesmo tempo nao zeram os administradores)."""
        if not era_admin:
            return
        n = conn.execute("SELECT COUNT(*) FROM usuarios u JOIN grupos g USING (grupo_id) WHERE g.nome = ? AND u.ativo = 1",
                         (autenticacao.GRUPO_ADMIN,)).fetchone()[0]
        if n == 0:
            raise ValueError("O painel precisa de pelo menos um administrador ativo.")

    def _aplicar_permissoes(self, conn, grupo_id: int, novas: set[str], atuais: set[str]) -> tuple[set[str], set[str]]:
        adicionadas = novas - atuais
        removidas = atuais - novas
        if adicionadas or removidas:
            for p in removidas:
                conn.execute("DELETE FROM grupo_permissoes WHERE grupo_id = ? AND permissao = ?", (grupo_id, p))
            for p in adicionadas:
                conn.execute("INSERT INTO grupo_permissoes (grupo_id, permissao) VALUES (?, ?)", (grupo_id, p))
        return adicionadas, removidas

    def definir_permissoes(self, grupo_id: int, permissoes: set[str], auditoria: tuple | None = None) -> int:
        """Substitui as permissões do grupo de forma atômica e estritamente idempotente."""
        with self._conexao(escrita=True) as conn:
            row = conn.execute("SELECT grupo_id, nome FROM grupos WHERE grupo_id = ?", (grupo_id,)).fetchone()
            if not row:
                raise ValueError(f"Grupo não existe: {grupo_id}")
            if row[1] == autenticacao.GRUPO_ADMIN:
                raise ValueError("As permissões do Administrador não podem ser alteradas.")
            desconhecidas = set(permissoes) - set(autenticacao.PERMISSOES)
            if desconhecidas:
                raise ValueError(f"Permissão desconhecida: {min(desconhecidas)}")
            if row[1] == autenticacao.GRUPO_VISITANTE:
                proibidas = set(permissoes) & autenticacao.PERMISSOES_PROIBIDAS_VISITANTE
                if proibidas:
                    raise ValueError(f"O grupo Visitante não pode receber essa permissão: {sorted(proibidas)[0]}")

            atuais = {r[0] for r in conn.execute("SELECT permissao FROM grupo_permissoes WHERE grupo_id = ?", (grupo_id,)).fetchall()}
            adicionadas, removidas = self._aplicar_permissoes(conn, grupo_id, set(permissoes), atuais)
            diff_count = len(adicionadas) + len(removidas)
            if diff_count > 0:
                self._gravar_auditoria(conn, auditoria)
            return diff_count

    def definir_permissoes_do_grupo(
        self,
        grupo_id: int,
        marcadas: list[str],
        exibidas: list[str],
        versao_esperada: str | None,
        confirmado: bool,
        justificativa: str,
        auditoria: tuple[str, str],
    ) -> dict:
        """Altera com segurança as permissões de um grupo com conferência de versão e auditoria."""
        if type(grupo_id) is not int or not (1 <= grupo_id <= 9223372036854775807):
            raise autenticacao.AlteracaoRecusada(["Este grupo não existe mais."])

        with self._conexao(escrita=True) as conn:
            row = conn.execute("SELECT nome FROM grupos WHERE grupo_id = ?", (grupo_id,)).fetchone()
            if not row:
                raise autenticacao.AlteracaoRecusada(["Este grupo não existe mais."])
            nome = row[0]

            rows = conn.execute("SELECT permissao FROM grupo_permissoes WHERE grupo_id = ?", (grupo_id,)).fetchall()
            if any(type(r[0]) is not str for r in rows):
                raise autenticacao.AlteracaoRecusada(
                    ["As permissões gravadas deste grupo têm um valor inválido. Nada foi alterado."]
                )
            atuais = {r[0] for r in rows}

            if autenticacao.versao_permissoes({grupo_id: atuais}) != versao_esperada:
                raise autenticacao.PermissoesAlteradas(
                    "As permissões deste grupo mudaram desde que a página foi aberta."
                )

            r = autenticacao.revisar_alteracao(nome, atuais, marcadas, exibidas)
            if r["erros"]:
                raise autenticacao.AlteracaoRecusada(r["erros"])

            p = autenticacao.pendencias_da_gravacao(r, confirmado, justificativa)
            if p:
                raise autenticacao.AlteracaoRecusada(p)

            if not r["concedidas"] and not r["retiradas"]:
                return r

            self._aplicar_permissoes(conn, grupo_id, set(r["depois"]), atuais)

            admin_login, agora = auditoria
            detalhe = autenticacao.detalhe_auditoria(r, justificativa)
            self._gravar_auditoria(conn, (admin_login, "salvar_permissoes", nome, detalhe, agora))

            return r

    def definir_matriz(
        self,
        permissoes_por_grupo: dict[int, set[str]],
        auditoria: tuple[str, str] | None = None,
        versao_esperada: str | None = None,
        detalhes: dict[int, str] | None = None,
    ) -> int:
        """Atualiza a matriz de permissões para todos os grupos em uma única transação."""
        with self._conexao(escrita=True) as conn:
            cur_p = conn.execute("SELECT grupo_id, permissao FROM grupo_permissoes")
            atuais_por_grupo = {}
            for gid, p in cur_p.fetchall():
                atuais_por_grupo.setdefault(gid, set()).add(p)

            if versao_esperada is not None:
                estado_atual = {gid: atuais_por_grupo.get(gid, set()) for gid in permissoes_por_grupo}
                if autenticacao.versao_permissoes(estado_atual) != versao_esperada:
                    raise autenticacao.PermissoesAlteradas("As permissões de algum grupo mudaram desde que a página foi aberta.")

            total_alteracoes = 0

            grupos_ordenados = conn.execute(
                "SELECT grupo_id, nome FROM grupos "
                "ORDER BY CASE WHEN nome = ? THEN 1 WHEN nome = ? THEN 2 ELSE 3 END, lower(nome)",
                (autenticacao.GRUPO_ADMIN, autenticacao.GRUPO_VISITANTE),
            ).fetchall()

            for gid, g_nome in grupos_ordenados:
                if gid not in permissoes_por_grupo:
                    continue
                if g_nome == autenticacao.GRUPO_ADMIN:
                    continue
                novas = set(permissoes_por_grupo[gid])
                if g_nome == autenticacao.GRUPO_VISITANTE:
                    novas = novas - autenticacao.PERMISSOES_PROIBIDAS_VISITANTE
                novas = novas & set(autenticacao.PERMISSOES)

                atuais = atuais_por_grupo.get(gid, set())
                adicionadas, removidas = self._aplicar_permissoes(conn, gid, novas, atuais)
                if adicionadas or removidas:
                    total_alteracoes += len(adicionadas) + len(removidas)
                    if detalhes and gid in detalhes:
                        detalhe = detalhes[gid]
                    else:
                        detalhe = ", ".join(["+" + p for p in sorted(adicionadas)] + ["-" + p for p in sorted(removidas)])
                    if auditoria:
                        admin_login, agora = auditoria
                        self._gravar_auditoria(conn, (admin_login, "salvar_permissoes", g_nome, detalhe, agora))
            return total_alteracoes

    def criar_grupo(self, nome: str, agora: str, auditoria: tuple | None = None) -> int:
        """Cria um novo grupo não fixo validando unicidade insensível (ASCII lower)."""
        nome_limpo = nome.strip()
        with self._conexao(escrita=True) as conn:
            if conn.execute("SELECT 1 FROM grupos WHERE lower(nome) = lower(?)", (nome_limpo,)).fetchone():
                raise ValueError(f"Grupo já existe: {nome_limpo}")
            cursor = conn.execute(
                "INSERT INTO grupos (nome, fixo, criado_em) VALUES (?, 0, ?)",
                (nome_limpo, agora),
            )
            grupo_id = cursor.lastrowid
            self._gravar_auditoria(conn, auditoria)
            return grupo_id

    def renomear_grupo(self, grupo_id: int, nome: str, auditoria: tuple | None = None) -> None:
        """Renomeia grupo não padrão validando unicidade insensível (ASCII lower) excluindo o próprio."""
        nome_limpo = nome.strip()
        with self._conexao(escrita=True) as conn:
            row_g = conn.execute("SELECT nome, fixo FROM grupos WHERE grupo_id = ?", (grupo_id,)).fetchone()
            if not row_g:
                raise ValueError(f"Grupo não existe: {grupo_id}")
            if row_g[0] in autenticacao.GRUPOS_PADRAO or row_g[1] == 1:
                raise ValueError("Este grupo não pode ser renomeado.")
            if nome_limpo == row_g[0]:
                return
            if conn.execute("SELECT 1 FROM grupos WHERE lower(nome) = lower(?) AND grupo_id != ?", (nome_limpo, grupo_id)).fetchone():
                raise ValueError(f"Grupo já existe: {nome_limpo}")
            conn.execute("UPDATE grupos SET nome = ? WHERE grupo_id = ?", (nome_limpo, grupo_id))
            self._gravar_auditoria(conn, auditoria)

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
                conn.execute("DELETE FROM tokens_api WHERE usuario_id = ?", (usuario_id,))   # senha nova: token tambem
                return "atualizado"

    def politica_divulgacao(self, banco: str) -> tuple[dict, str]:
        """Lê a política de divulgação para a pesquisa no banco de contas."""
        with self._conexao() as conn:
            row = conn.execute(
                "SELECT valor FROM configuracoes WHERE chave = ?",
                (divulgacao.chave(banco),),
            ).fetchone()
        valor = row[0] if row is not None else None
        return divulgacao.ler_politica(valor)

    def estado_divulgacao(self, banco: str) -> dict:
        """Lê a política, situação e versão do registro bruto no banco de contas."""
        with self._conexao() as conn:
            row = conn.execute(
                "SELECT valor FROM configuracoes WHERE chave = ?",
                (divulgacao.chave(banco),),
            ).fetchone()
        raw = row[0] if row is not None else None
        politica, situacao = divulgacao.ler_politica(raw)
        return {"politica": politica, "situacao": situacao, "versao": divulgacao.versao(raw)}

    def alterar_divulgacao(
        self, banco: str, nova: dict, versao_esperada: str, confirmado: bool, auditoria: tuple[str, str]
    ) -> dict:
        """Altera a política de divulgação de uma pesquisa em transação única com trava e auditoria."""
        if not isinstance(banco, str) or banco not in divulgacao.PESQUISAS:
            raise autenticacao.AlteracaoRecusada(["Pesquisa inválida."])
        erros = divulgacao.validar_nova(nova)
        if erros:
            raise autenticacao.AlteracaoRecusada(erros)
        if (
            not isinstance(auditoria, tuple)
            or len(auditoria) != 2
            or not isinstance(auditoria[0], str)
            or not auditoria[0].strip()
            or not isinstance(auditoria[1], str)
            or not auditoria[1].strip()
        ):
            raise ValueError("Auditoria inválida.")
        login, agora = auditoria

        with self._conexao(escrita=True) as conn:
            chave = divulgacao.chave(banco)
            row = conn.execute(
                "SELECT valor FROM configuracoes WHERE chave = ?",
                (chave,),
            ).fetchone()
            raw = row[0] if row is not None else None
            if divulgacao.versao(raw) != versao_esperada:
                raise divulgacao.DivulgacaoAlterada()

            antes, situacao = divulgacao.ler_politica(raw)
            r = divulgacao.revisar(antes, nova)
            if not r["muda"]:
                return r

            if confirmado is not True:
                raise autenticacao.AlteracaoRecusada(["Marque a confirmação para gravar a alteração."])

            conn.execute("DELETE FROM configuracoes WHERE chave = ?", (chave,))
            conn.execute(
                "INSERT INTO configuracoes (chave, valor) VALUES (?, ?)",
                (chave, divulgacao.valor(nova)),
            )
            detalhe = json.dumps(
                {
                    "antes": antes,
                    "depois": nova,
                    "situacao_antes": situacao,
                    "versao_antes": divulgacao.versao(raw),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            self._gravar_auditoria(conn, (login, "alterar_divulgacao", banco, detalhe, agora))
            return r
