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


def conferir_url(url):
    """A migracao precisa de sessao propria (trava consultiva): nunca a URL do pool (-pooler no Neon). Host remoto exige
    TLS (sslmode=require ou mais forte). Decide pelos valores que a conexao vai usar (o leitor de URL do psycopg: parametro
    repetido vale o ultimo, `host=` na query vale mais que o host do endereco, varios hosts separados por virgula).
    A mensagem nunca repete a URL."""
    if not isinstance(url, str) or not url.startswith(("postgresql://", "postgres://")):
        raise ErroMigracao(INVALIDA)
    try:
        info = conninfo_to_dict(url)
    except psycopg.Error:
        raise ErroMigracao(INVALIDA) from None
    hosts = [h.strip().lower() for chave in ("host", "hostaddr") for h in str(info.get(chave) or "").split(",") if h.strip()]
    if not hosts:
        raise ErroMigracao(INVALIDA)
    if any("-pooler" in h for h in hosts):
        raise ErroMigracao("Use a conexão direta (sem -pooler) para migrar: a URL do pool não mantém a trava da migração.")
    remotos = [h for h in hosts if h not in LOCAIS and not h.startswith("/")]
    if remotos and info.get("sslmode") not in ("require", "verify-ca", "verify-full"):
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


def _registro(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS versao_esquema (arquivo TEXT PRIMARY KEY, sha256 TEXT NOT NULL, aplicada_em TEXT NOT NULL)")
    return dict(conn.execute("SELECT arquivo, sha256 FROM versao_esquema").fetchall())


def pendentes(url, pasta=PASTA):
    """Arquivos que `aplicar` aplicaria agora (sem aplicar nada). Lista vazia = esquema em dia."""
    conferir_url(url)
    versionados, repetiveis = _arquivos(pasta)
    with _conectar(url) as conn:
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
