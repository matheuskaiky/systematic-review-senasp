"""Migracoes do banco PostgreSQL (painel na nuvem, D96). Aplicadas so pelo comando `python main.py pg-migrar`, com a URL
direta do Neon; o painel nunca migra, so confere a versao ao subir.

Dois tipos de arquivo em adaptadores/postgres/migracoes/:
- `V<nnnn>_<nome>.sql`: versionados, aplicados uma unica vez, em ordem; um arquivo ja aplicado que mude e recusado.
- `R_<nome>.sql`: repetiveis (as views, derivadas do schema.sql), reaplicados quando o texto muda; nao apagam dado.
Cada arquivo roda numa transacao propria; uma trava consultiva impede duas aplicacoes ao mesmo tempo."""
import hashlib
from datetime import datetime, timezone
from pathlib import Path
import psycopg
from psycopg.conninfo import conninfo_to_dict

PASTA = Path(__file__).resolve().parent / "postgres" / "migracoes"
TRAVA = 726_473_201                      # chave da trava consultiva (pg_advisory_lock) das migracoes deste projeto


class ErroMigracao(Exception):
    pass


def _arquivos(pasta):
    versionados = sorted(p for p in pasta.glob("V*.sql"))
    repetiveis = sorted(p for p in pasta.glob("R_*.sql"))
    return versionados, repetiveis


def _hash(p):
    """Hash do texto com quebras de linha normalizadas (um checkout com CRLF nao parece migracao alterada)."""
    return hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


LOCAIS = ("localhost", "127.0.0.1", "::1")
INVALIDA = "A URL do PostgreSQL é inválida (confira o formato postgresql://usuario:senha@host/banco)."


def analisar_url(url):
    """(hosts, remoto_sem_tls) pelos valores que a conexao vai usar (o leitor de URL do psycopg: parametro repetido vale o
    ultimo, `host=` na query vale mais que o host do endereco, varios hosts separados por virgula, `hostaddr`). URL sem
    host e invalida (a libpq cairia no PGHOST ou no service do ambiente). Usada pela migracao e pelo pool do painel."""
    if not isinstance(url, str) or not url.startswith(("postgresql://", "postgres://")):
        raise ErroMigracao(INVALIDA)
    try:
        info = conninfo_to_dict(url)
    except psycopg.Error:
        raise ErroMigracao(INVALIDA) from None
    if info.get("service"):
        raise ErroMigracao(INVALIDA)
    hosts = [h.strip().lower() for chave in ("host", "hostaddr") for h in str(info.get(chave) or "").split(",") if h.strip()]
    if not hosts:
        raise ErroMigracao(INVALIDA)
    remotos = [h for h in hosts if h not in LOCAIS and not h.startswith("/")]
    return hosts, bool(remotos) and info.get("sslmode") not in ("require", "verify-ca", "verify-full")


def conferir_url(url):
    """A migracao precisa de sessao propria (trava consultiva): nunca a URL do pool (-pooler no Neon). Host remoto exige
    TLS (sslmode=require ou mais forte). A mensagem nunca repete a URL."""
    hosts, sem_tls = analisar_url(url)
    if any("-pooler" in h for h in hosts):
        raise ErroMigracao("Use a conexão direta (sem -pooler) para migrar: a URL do pool não mantém a trava da migração.")
    if sem_tls:
        raise ErroMigracao("Conexão remota sem TLS: acrescente sslmode=require à URL do PostgreSQL.")


def _conectar(url, **kw):
    try:
        return psycopg.connect(url, connect_timeout=10, **kw)
    except psycopg.Error:
        raise ErroMigracao("Não foi possível conectar ao PostgreSQL (confira a URL, a senha e se o banco está no ar).") from None


def _ordem_dos_versionados(versionados, feitos):
    """Recusa versionado registrado que sumiu do disco e versionado novo numerado antes do ultimo aplicado."""
    nomes = [p.name for p in versionados]
    sumidos = sorted(n for n in feitos if n.startswith("V") and n not in nomes)
    if sumidos:
        raise ErroMigracao("Migração aplicada não existe mais no disco: " + ", ".join(sumidos) + ".")
    aplicados = [n for n in nomes if n in feitos]
    novos = [n for n in nomes if n not in feitos]
    if aplicados and novos and min(novos) < max(aplicados):
        raise ErroMigracao("Migração nova numerada antes da última aplicada: " + ", ".join(n for n in novos if n < max(aplicados)) + ".")


COLACOES_BYTE_A_BYTE = ("C", "C.UTF-8", "C.utf8", "POSIX")


VERSAO_MINIMA = 160000                    # subconsulta sem apelido no FROM (as consultas do painel e do catalogo): 16+


def _conferir_servidor(conn):
    """Versao do servidor (16 ou mais nova) e colacao byte a byte; recusa antes de aplicar ou de abrir o painel."""
    versao = int(conn.execute("SELECT current_setting('server_version_num')").fetchone()[0])
    if versao < VERSAO_MINIMA:
        raise ErroMigracao(f"O PostgreSQL precisa ser da versão 16 ou mais nova (este é {versao // 10000}): "
                           "crie o projeto do Neon com a versão 16 ou 17.")
    _conferir_colacao(conn)


def _conferir_colacao(conn):
    """O texto precisa ser ordenado e comparado byte a byte, como no SQLite (o Neon usa C.UTF-8 por padrao): provedor
    libc com LC_COLLATE C/C.UTF-8/POSIX, ou o provedor builtin (PostgreSQL 17) com C ou C.UTF-8. ICU nunca (o LC_COLLATE
    de um banco ICU nao e a colacao usada). A colacao de um banco nao muda depois de criado: com outra, recusa antes de
    aplicar qualquer coisa."""
    colacao, provedor, icu, builtin = conn.execute(
        "SELECT d.datcollate, d.datlocprovider::text, to_jsonb(d) ->> 'daticulocale', to_jsonb(d) ->> 'datlocale' "
        "FROM pg_database d WHERE d.datname = current_database()").fetchone()
    if provedor == "c" and colacao in COLACOES_BYTE_A_BYTE:
        return
    if provedor == "b" and builtin in ("C", "C.UTF-8"):
        return
    usa = {"c": colacao, "i": f"ICU {icu or builtin}", "b": f"builtin {builtin}"}.get(provedor, f"o provedor {provedor}")
    raise ErroMigracao("O banco PostgreSQL precisa da ordenação byte a byte (C ou C.UTF-8, o padrão do Neon) e usa "
                       f"{usa}: crie outro banco com LC_COLLATE 'C.UTF-8'.")


def _registro(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS versao_esquema (arquivo TEXT PRIMARY KEY, sha256 TEXT NOT NULL, aplicada_em TEXT NOT NULL)")
    return dict(conn.execute("SELECT arquivo, sha256 FROM versao_esquema").fetchall())


def pendentes_na_conexao(conn, pasta=PASTA):
    """Os mesmos pendentes de `pendentes`, lendo por uma conexao ja aberta (o pool do painel, que usa a URL -pooler)."""
    versionados, repetiveis = _arquivos(pasta)
    _conferir_servidor(conn)
    existe = conn.execute("SELECT to_regclass('versao_esquema') IS NOT NULL").fetchone()[0]
    feitos = dict(conn.execute("SELECT arquivo, sha256 FROM versao_esquema").fetchall()) if existe else {}
    return [p.name for p in versionados if feitos.get(p.name) != _hash(p)] + [p.name for p in repetiveis if feitos.get(p.name) != _hash(p)]


def pendentes(url, pasta=PASTA):
    """Arquivos que `aplicar` aplicaria agora (sem aplicar nada). Lista vazia = esquema em dia."""
    conferir_url(url)
    versionados, repetiveis = _arquivos(pasta)
    with _conectar(url) as conn:
        _conferir_servidor(conn)
        existe = conn.execute("SELECT to_regclass('versao_esquema') IS NOT NULL").fetchone()[0]
        feitos = dict(conn.execute("SELECT arquivo, sha256 FROM versao_esquema").fetchall()) if existe else {}
    alterados = [p.name for p in versionados if p.name in feitos and feitos[p.name] != _hash(p)]
    if alterados:
        raise ErroMigracao("Migração já aplicada foi alterada: " + ", ".join(alterados) + ". Crie um arquivo novo em vez de editar.")
    _ordem_dos_versionados(versionados, feitos)
    return ([p.name for p in versionados if p.name not in feitos]
            + [p.name for p in repetiveis if feitos.get(p.name) != _hash(p)])


def aplicar(url, pasta=PASTA):
    """Aplica o que falta, em ordem (versionados, depois repetiveis). Devolve a lista de arquivos aplicados."""
    conferir_url(url)
    versionados, repetiveis = _arquivos(pasta)
    aplicados = []
    with _conectar(url, autocommit=True) as trava:
        trava.execute("SELECT pg_advisory_lock(%s)", (TRAVA,))
        try:
            with _conectar(url) as conn:
                _conferir_servidor(conn)
                feitos = _registro(conn)
                conn.commit()
                alterados = [p.name for p in versionados if p.name in feitos and feitos[p.name] != _hash(p)]
                if alterados:
                    raise ErroMigracao("Migração já aplicada foi alterada: " + ", ".join(alterados)
                                       + ". Crie um arquivo novo em vez de editar.")
                _ordem_dos_versionados(versionados, feitos)
                for p in versionados + repetiveis:
                    h = _hash(p)
                    if feitos.get(p.name) == h:
                        continue
                    try:
                        with conn.transaction():
                            conn.execute(p.read_text(encoding="utf-8"))
                            conn.execute("INSERT INTO versao_esquema (arquivo, sha256, aplicada_em) VALUES (%s, %s, %s) "
                                         "ON CONFLICT (arquivo) DO UPDATE SET sha256 = excluded.sha256, aplicada_em = excluded.aplicada_em",
                                         (p.name, h, datetime.now(timezone.utc).isoformat()))
                    except psycopg.Error as erro:      # o arquivo inteiro volta atras; os anteriores ficam aplicados
                        raise ErroMigracao(f"A migração {p.name} falhou e foi desfeita (código do PostgreSQL: "
                                           f"{erro.sqlstate or 'desconhecido'}).") from None
                    aplicados.append(p.name)
        finally:
            trava.execute("SELECT pg_advisory_unlock(%s)", (TRAVA,))
    return aplicados
