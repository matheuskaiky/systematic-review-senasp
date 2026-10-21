"""Conexao PostgreSQL com a interface que os adaptadores SQLite usam (D96, ADR-postgresql-neon).

Os adaptadores (contas, leituras do painel, gravacoes do painel) foram escritos para o `sqlite3`. Em vez de reescrever
cada consulta, eles recebem esta conexao, que se comporta como a do modulo `sqlite3`:
- fora de transacao, cada comando vale sozinho (autocommit); um INSERT/UPDATE/DELETE abre a transacao sozinho, como o
  `sqlite3` faz; `in_transaction` diz se ha transacao aberta por BEGIN ou por gravacao (uma leitura nao abre);
- um gravador por vez, como no SQLite: a primeira gravacao da transacao (ou o BEGIN IMMEDIATE) pega a trava consultiva
  da transacao; quem espera mais que ESPERA_TRAVA recebe "database is locked";
- dentro da transacao, cada comando roda num savepoint: o que falha e desfeito sozinho e o resto continua valendo;
- traduz o SQL na hora, com as mesmas regras das views (adaptadores/postgres/traducao.py), e guarda a traducao em cache;
- devolve linhas que funcionam como `sqlite3.Row` (por posicao e por nome) e cursores com `rowcount` e `lastrowid`;
- so levanta erros do `sqlite3` (IntegrityError; OperationalError para todo o resto), para os `except` atuais valerem;
- le `numeric` como no SQLite: inteiro quando o valor e inteiro, real quando nao.
Nada aqui le o ambiente: a URL chega pronta de composicao.py."""
import re
import sqlite3
from contextlib import contextmanager
from functools import lru_cache

import psycopg
from psycopg.adapt import Loader
from psycopg_pool import ConnectionPool

from adaptadores import migrador_postgres
from adaptadores.postgres import traducao as T

TRAVA_ESCRITA = 726_473_202          # trava consultiva das gravacoes da pesquisa (o "um gravador por vez" do SQLite)
TRAVA_CONTAS = 726_473_203           # a das contas: no SQLite eram dois arquivos, cada um com a sua trava
TRAVA_ENVIO = 726_473_204            # a dos envios de coleta (D100): um envio por vez, sem parar as gravacoes do painel
ESPERA_TRAVA = "30s"                 # lock_timeout de cada transacao (o busy_timeout do SQLite)
MAX_CONEXOES = 4
ESPERA_POOL = 30                     # segundos esperando uma conexao livre do pool
INDISPONIVEL = "banco PostgreSQL indisponível"
TLS = "Conexão remota sem TLS: acrescente sslmode=require à DATABASE_URL."
URL_INVALIDA = "A DATABASE_URL é inválida (confira o formato postgresql://usuario:senha@host/banco)."


class _NumericoComoSQLite(Loader):
    """SUM/AVG sobre inteiros sao numeric no PostgreSQL; no SQLite, inteiro (soma) ou real (media)."""

    def load(self, data):
        texto = bytes(data).decode()
        return int(texto) if texto.lstrip("-").isdigit() else float(texto)


def _configurar(conn):
    conn.adapters.register_loader("numeric", _NumericoComoSQLite)


def criar_pool(url, maximo=MAX_CONEXOES):
    """Pool pequeno por instancia (o Neon ja tem o PgBouncer na URL -pooler). A URL passa pela mesma conferencia da
    migracao (o leitor de URL do psycopg: host, hostaddr, sslmode efetivos), mas aqui a URL do pool e a esperada.
    ValueError com mensagem fixa (nunca repete a URL): URL invalida ou host remoto sem TLS."""
    try:
        _, sem_tls = migrador_postgres.analisar_url(url)
    except migrador_postgres.ErroMigracao:
        raise ValueError(URL_INVALIDA) from None
    if sem_tls:
        raise ValueError(TLS)
    # prepare_threshold=None: o pool transacional do Neon (PgBouncer) nao guarda prepared statements entre transacoes.
    # check: a conexao e testada ao sair do pool (o Neon derruba as ociosas quando o banco dorme).
    return ConnectionPool(url, min_size=0, max_size=maximo, open=True, configure=_configurar, timeout=ESPERA_POOL,
                          check=ConnectionPool.check_connection,
                          kwargs={"autocommit": True, "connect_timeout": 10, "prepare_threshold": None})


class Linha(tuple):
    """Como sqlite3.Row: linha[0], linha["coluna"], dict(linha), linha.keys()."""
    __slots__ = ()
    _nomes = ()

    def __new__(cls, valores):
        return super().__new__(cls, valores)

    def __getitem__(self, chave):
        if isinstance(chave, str):                  # como no sqlite3.Row: sem diferenca de maiusculas; repetida vale a primeira
            try:
                return tuple.__getitem__(self, self._indices[chave.lower()])
            except KeyError:
                raise IndexError("No item with that key") from None
        return tuple.__getitem__(self, chave)

    def keys(self):
        return list(self._nomes)


@lru_cache(maxsize=512)
def _classe_de_linha(nomes):
    indices = {}
    for i, n in enumerate(nomes):
        indices.setdefault(n.lower(), i)
    return type("Linha", (Linha,), {"__slots__": (), "_nomes": nomes, "_indices": indices})


class Cursor:
    def __init__(self, cur=None, lastrowid=None, linhas=None):
        """`cur` None: cursor vazio (PRAGMA, BEGIN, COMMIT). As linhas sao lidas na hora (o savepoint ja foi liberado)."""
        self.lastrowid = lastrowid
        self.rowcount = cur.rowcount if cur is not None else -1
        self.description = cur.description if cur is not None else None
        self._classe = _classe_de_linha(tuple(c.name for c in self.description)) if self.description else None
        self._linhas = list(linhas if linhas is not None else (cur.fetchall() if self._classe else []))

    def fetchone(self):
        return self._classe(self._linhas.pop(0)) if self._linhas else None

    def fetchall(self):
        linhas, self._linhas = self._linhas, []
        return [self._classe(v) for v in linhas]

    def __iter__(self):
        return iter(self.fetchall())


# ---------- traducao do SQL em tempo de execucao ----------
# Colunas que o PostgreSQL exige no GROUP BY das consultas escritas no Python (o SQLite aceita coluna solta). Revisadas uma a
# uma: todas dependem da chave do agrupamento (execucoes pelo run_id; v_termos pelo termo). Achadas varrendo todas as
# paginas do painel; uma consulta nova com coluna solta falha no teste de paridade das paginas.
GROUP_BY_EXTRA_SQL = {
    "GROUP BY te.run_id ORDER BY MAX(te.criado_em) DESC, MAX(te.id) DESC": ("e.iniciado_em", "e.status", "e.no_relatorio"),
    "GROUP BY c.alvo_id ORDER BY c.alvo_id": ("t.query", "t.idioma"),
}
_SQLITE_MASTER = ("(SELECT table_name AS name, CASE table_type WHEN 'VIEW' THEN 'view' ELSE 'table' END AS type, "
                  "NULL::text AS sql FROM information_schema.tables WHERE table_schema = 'public') sqlite_master")
COLUNAS_SO_DO_POSTGRES = ("ordem_gravacao",)     # nao existem no SQLite: SELECT * nao as devolve


def _placeholders(sql):
    """`?` -> `%s` no codigo; `%` -> `%%` no codigo e nos literais (o psycopg reserva o %). Comentarios saem."""
    out = []
    for tipo, t in T.segmentos(sql):
        if tipo == "comentario":
            out.append(" ")
        elif tipo == "literal":
            out.append(t.replace("%", "%%"))
        else:
            out.append(t.replace("%", "%%").replace("?", "%s"))
    return "".join(out)


@lru_cache(maxsize=4096)
def traduzir(sql, tabelas):
    """SQL do SQLite -> (SQL do PostgreSQL, coluna do RETURNING ou None). `tabelas`: ((tabela, (colunas da chave
    primaria), identidade?, (todas as colunas)), ...), de `chaves_do_banco`. ValueError com mensagem fixa para o que nao
    tem traducao exata (INSERT OR REPLACE, LIKE sem ESCAPE com padrao que nao e ? nem literal, divisao por CASE)."""
    info = {t: (pk, ident, cols) for t, pk, ident, cols in tabelas}
    s = T.sem_comentarios(sql).strip().rstrip(";").strip()
    for trecho, colunas in GROUP_BY_EXTRA_SQL.items():
        if trecho in s:
            chave, resto = trecho.split(" ORDER BY ", 1)
            s = s.replace(trecho, chave + ", " + ", ".join(colunas) + " ORDER BY " + resto)
    s = T._fora_de_aspas(s, lambda t: re.sub(r"\?(?=\s+IS\s+(NOT\s+)?NULL\b)", "CAST(? AS TEXT)", t, flags=re.I))
    s = T._fora_de_aspas(s, lambda t: re.sub(r"\bIS NOT \?", "IS DISTINCT FROM ?", t, flags=re.I))
    s = T._fora_de_aspas(s, lambda t: re.sub(r"\bIS \?", "IS NOT DISTINCT FROM ?", t, flags=re.I))
    s = T._fora_de_aspas(s, lambda t: re.sub(r"\bsqlite_master\b", _SQLITE_MASTER, t))

    def _sem_colunas_novas(m):
        cols = info.get(m.group(2), (None, None, ()))[2]
        if not any(c in COLUNAS_SO_DO_POSTGRES for c in cols):
            return m.group(0)
        return m.group(1) + ", ".join(c for c in cols if c not in COLUNAS_SO_DO_POSTGRES) + " FROM " + m.group(2)
    mas = T.mascara(s)
    ocultas = [t for t, (_, _, cols) in info.items() if any(c in COLUNAS_SO_DO_POSTGRES for c in cols)]
    simples = re.fullmatch(r"(?is)SELECT\s+\*\s+FROM\s+([a-z_]+)(\s+(WHERE|ORDER\s+BY|LIMIT)\b.*)?", mas)
    if simples and simples.group(1) in ocultas:
        s = re.sub(r"^(SELECT\s+)\*\s+FROM\s+([a-z_]+)\b", _sem_colunas_novas, s, count=1, flags=re.I)
    elif any(re.search(rf"\b{t}\b", mas) for t in ocultas) and re.search(r"(?i)\bSELECT\s+(\w+\.)?\*|,\s*(\w+\.)?\*\s*(,|\bFROM\b)", mas):
        raise ValueError("SELECT * com " + ", ".join(ocultas) + " só na forma SELECT * FROM <tabela> [WHERE/ORDER BY/LIMIT] "
                         "(a coluna ordem_gravacao só existe no PostgreSQL).")
    try:
        s = T.semantica_sqlite(s)
    except IndexError:
        raise ValueError("SQL malformado (parênteses ou operador sem operando).") from None
    m = re.match(r"INSERT\s+OR\s+(IGNORE|REPLACE)\s+INTO\b", s, re.I)
    if m and m.group(1).upper() == "REPLACE":
        raise ValueError("INSERT OR REPLACE não tem tradução exata no PostgreSQL (só as gravações do painel rodam lá).")
    if m:                                        # IGNORE: so o conflito de unicidade e ignorado (NOT NULL e CHECK falham)
        s = "INSERT INTO" + s[m.end():] + " ON CONFLICT DO NOTHING"
    retorno = None
    m = re.match(r"INSERT\s+INTO\s+([a-z_]+)", s, re.I)
    if m and m.group(1) in info and info[m.group(1)][1] and not re.search(r"\bRETURNING\b", T.mascara(s), re.I):
        retorno = info[m.group(1)][0][0]
        s += f" RETURNING {retorno}"
    return _placeholders(s), retorno


def _converter_erro(erro):
    """psycopg -> sqlite3: IntegrityError fica IntegrityError; o resto vira OperationalError (texto do SQLite quando ha
    equivalente). A mensagem nunca traz valores (o PostgreSQL os poe no DETAIL, que fica de fora)."""
    estado = getattr(erro, "sqlstate", None)
    if isinstance(erro, psycopg.IntegrityError):
        return sqlite3.IntegrityError(erro.diag.message_primary or "violação de integridade")
    if isinstance(erro, psycopg.errors.LockNotAvailable):
        return sqlite3.OperationalError("database is locked")
    if isinstance(erro, psycopg.errors.ReadOnlySqlTransaction):
        return sqlite3.OperationalError("attempt to write a readonly database")
    if estado is None or estado.startswith(("08", "57P")):
        return sqlite3.OperationalError(INDISPONIVEL)
    return sqlite3.OperationalError(erro.diag.message_primary or type(erro).__name__)


class ConexaoPostgres:
    """Conexao emprestada do pool com a interface de sqlite3.Connection usada pelos adaptadores."""

    def __init__(self, pool, chaves, trava=TRAVA_ESCRITA):
        self._pool = pool
        self._chaves = chaves
        self._chave_trava = trava
        self._somente_leitura = False
        self._sem_savepoint = False
        self._em_transacao = False
        self._trava = False
        self.row_factory = None                     # aceito e ignorado: as linhas ja funcionam como sqlite3.Row
        try:
            self._conn = pool.getconn()
        except Exception:                           # pool esgotado (PoolTimeout) ou banco fora do ar
            raise sqlite3.OperationalError(INDISPONIVEL) from None

    @property
    def in_transaction(self):
        return self._em_transacao

    def _bruto(self, sql, params=None):
        try:
            return self._conn.execute(sql, params)
        except psycopg.Error as erro:
            raise _converter_erro(erro) from None

    def _iniciar(self, somente_leitura=False):
        if self._em_transacao:
            raise sqlite3.OperationalError("cannot start a transaction within a transaction")
        self._bruto(("BEGIN READ ONLY" if somente_leitura else "BEGIN") + f"; SET LOCAL lock_timeout = '{ESPERA_TRAVA}'")
        self._em_transacao, self._trava, self._somente_leitura = True, False, somente_leitura

    def _travar(self):
        """Num savepoint: se a espera estoura ("database is locked"), a transacao continua usavel, como no sqlite3."""
        if not self._trava:
            try:
                if self._sem_savepoint:
                    self._conn.execute("SELECT pg_advisory_xact_lock(%s)", (self._chave_trava,))
                else:
                    with self._conn.transaction():
                        self._conn.execute("SELECT pg_advisory_xact_lock(%s)", (self._chave_trava,))
            except psycopg.Error as erro:
                raise _converter_erro(erro) from None
            self._trava = True

    @contextmanager
    def modo_envio(self):
        """Para juntar um envio de coleta (tudo ou nada): a trava dos envios no lugar da trava das gravacoes, e nenhum
        savepoint por comando (qualquer falha desfaz a transacao inteira; o savepoint so custaria idas ao banco)."""
        antes = (self._chave_trava, self._sem_savepoint)
        self._chave_trava, self._sem_savepoint = TRAVA_ENVIO, True
        try:
            yield self
        finally:
            self._chave_trava, self._sem_savepoint = antes

    def execute(self, sql, params=()):
        comando = re.sub(r"\s+", " ", sql).strip().rstrip(";").strip().upper()
        m = re.fullmatch(r"PRAGMA TABLE_INFO\( ?([A-Z_0-9]+) ?\)", comando)
        if m:                                       # as colunas de uma tabela ou view, na ordem, como no SQLite
            return Cursor(self._bruto("SELECT ordinal_position - 1 AS cid, column_name AS name, data_type AS type "
                                      "FROM information_schema.columns WHERE table_schema = 'public' AND table_name = %s "
                                      "AND column_name <> ALL(%s) ORDER BY ordinal_position",
                                      (m.group(1).lower(), list(COLUNAS_SO_DO_POSTGRES))))
        if comando.startswith("PRAGMA"):
            return Cursor()
        if comando in ("BEGIN", "BEGIN DEFERRED", "BEGIN TRANSACTION", "BEGIN DEFERRED TRANSACTION"):
            self._iniciar()
            return Cursor()
        if comando in ("BEGIN IMMEDIATE", "BEGIN EXCLUSIVE", "BEGIN IMMEDIATE TRANSACTION", "BEGIN EXCLUSIVE TRANSACTION"):
            self._iniciar()
            try:
                self._travar()
            except sqlite3.OperationalError:          # como no SQLite: BEGIN IMMEDIATE que nao trava nao abre transacao
                self.rollback()
                raise
            return Cursor()
        if comando in ("COMMIT", "END", "COMMIT TRANSACTION", "END TRANSACTION"):
            self.commit()
            return Cursor()
        if comando in ("ROLLBACK", "ROLLBACK TRANSACTION"):
            self.rollback()
            return Cursor()
        try:
            texto, retorno = traduzir(sql, self._chaves)
        except ValueError as erro:
            raise sqlite3.OperationalError(str(erro)) from None
        return self._executar(texto, retorno, tuple(params) if params is not None else ())

    @staticmethod
    def _e_gravacao(texto):
        mas = T.mascara(texto)
        return bool(re.match(r"\s*(INSERT|UPDATE|DELETE)\b", mas, re.I)
                    or (re.match(r"\s*WITH\b", mas, re.I) and re.search(r"\b(INSERT|UPDATE|DELETE)\b", mas, re.I)))

    def _executar(self, texto, retorno, params, muitos=None):
        gravacao = self._e_gravacao(texto)
        if gravacao and not self._em_transacao:
            self._iniciar()                         # como o sqlite3: a gravacao abre a transacao sozinha
        if gravacao:
            self._travar()
        try:
            if not self._em_transacao or self._somente_leitura:  # sem gravacao a desfazer: sem savepoint (menos idas ao banco)
                cur = self._conn.execute(texto, params)
                return Cursor(cur)
            if self._sem_savepoint:                 # modo_envio: tudo ou nada, a falha desfaz a transacao inteira
                if muitos is not None:
                    vazio = Cursor()
                    vazio.rowcount = sum(max(self._conn.execute(texto, p).rowcount, 0) for p in muitos)
                    return vazio
                cur = self._conn.execute(texto, params)
                linhas = cur.fetchall() if cur.description else []
                ultimo = linhas[0][0] if retorno and cur.rowcount == 1 else None
                return Cursor(cur, ultimo, linhas=[] if retorno else linhas)
            with self._conn.transaction():          # savepoint: o comando que falha e desfeito sozinho
                if muitos is not None:              # um comando por linha (sem o modo pipeline, que o PgBouncer antigo estranha)
                    total = 0
                    for p in muitos:
                        total += max(self._conn.execute(texto, p).rowcount, 0)
                    vazio = Cursor()
                    vazio.rowcount = total
                    return vazio
                cur = self._conn.execute(texto, params)
                linhas = cur.fetchall() if cur.description else []
            ultimo = linhas[0][0] if retorno and cur.rowcount == 1 else None
            return Cursor(cur, ultimo, linhas=[] if retorno else linhas)
        except psycopg.Error as erro:
            raise _converter_erro(erro) from None

    def executemany(self, sql, linhas):
        try:
            texto, _ = traduzir(sql, self._chaves)
        except ValueError as erro:
            raise sqlite3.OperationalError(str(erro)) from None
        return self._executar(texto, None, (), muitos=[tuple(p) for p in linhas])

    def somente_leitura(self):
        """Abre a transacao como somente leitura (o mode=ro do SQLite): uma gravacao por engano falha."""
        if not self._em_transacao:
            self._iniciar(somente_leitura=True)

    def commit(self):
        if not self._em_transacao:
            return
        try:
            cur = self._bruto("COMMIT")
        finally:
            self._em_transacao = self._trava = self._somente_leitura = False
        if cur.statusmessage != "COMMIT":           # o PostgreSQL desfez a transacao (nao deveria: cada comando tem savepoint)
            raise sqlite3.OperationalError("a transação foi desfeita pelo PostgreSQL")

    def rollback(self):
        """Nunca levanta: com a conexao caida, a transacao ja foi descartada pelo servidor."""
        if not self._em_transacao:
            return
        try:
            self._conn.execute("ROLLBACK")
        except psycopg.Error:
            pass
        finally:
            self._em_transacao = self._trava = self._somente_leitura = False

    def close(self):
        """Devolve a conexao ao pool mesmo se ela caiu (o pool descarta a quebrada); nunca levanta."""
        if self._conn is None:
            return
        try:
            self.rollback()
        except Exception:
            pass
        finally:
            conn, self._conn = self._conn, None
            self._pool.putconn(conn)


def chaves_do_banco(pool):
    """((tabela, (colunas da chave primaria), tem identidade?, (colunas na ordem)), ...) lido do catalogo, uma vez por
    processo."""
    with pool.connection() as c:
        colunas = c.execute("SELECT table_name, column_name, is_identity = 'YES' FROM information_schema.columns "
                            "WHERE table_schema = 'public' ORDER BY table_name, ordinal_position").fetchall()
        chaves = c.execute(
            "SELECT tc.table_name, kcu.column_name FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu ON kcu.constraint_name = tc.constraint_name "
            "AND kcu.table_schema = tc.table_schema WHERE tc.table_schema = 'public' AND tc.constraint_type = 'PRIMARY KEY' "
            "ORDER BY tc.table_name, kcu.ordinal_position").fetchall()
    cols, ident, pk = {}, {}, {}
    for t, col, e_ident in colunas:
        cols[t] = cols.get(t, ()) + (col,)
        ident[(t, col)] = e_ident
    for t, col in chaves:
        pk[t] = pk.get(t, ()) + (col,)
    return tuple(sorted((t, pk.get(t, ()), len(pk.get(t, ())) == 1 and ident[(t, pk[t][0])], cols[t]) for t in cols))
