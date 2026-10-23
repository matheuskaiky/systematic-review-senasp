"""Traducao do SQL do SQLite para o PostgreSQL feita na hora pela conexao compativel (painel na nuvem, D96), a URL do
pool, a escolha do banco pelo ambiente e as dependencias declaradas. Sem banco: so texto e configuracao."""
import ast
import pathlib
import subprocess
import sys

import pytest

from adaptadores.postgres.conexao import criar_pool, traduzir

RAIZ = pathlib.Path(__file__).resolve().parents[1]
TABELAS = (("execucoes", ("run_id",), False, ("run_id", "iniciado_em", "ordem_gravacao")),
           ("grupos", ("grupo_id",), True, ("grupo_id", "nome")),
           ("metricas_run", ("run_id", "chave"), False, ("run_id", "chave", "valor")))

TRADUCOES = [
    # parametros e % : so no codigo; literais e comentarios ficam como estao (comentario sai)
    ("SELECT * FROM t WHERE a = ? AND b = '?' AND c LIKE '50%'",
     "SELECT * FROM t WHERE a = %s AND b = '?' AND c ILIKE '50%%' COLLATE \"C\"", None),
    ("SELECT a FROM t -- quem? pergunta\nWHERE b = ?", "SELECT a FROM t  \nWHERE b = %s", None),
    ("SELECT a FROM t /* ? e 'x */ WHERE b = ?", "SELECT a FROM t   WHERE b = %s", None),
    ("SELECT a FROM t WHERE b = 'it''s ?'", "SELECT a FROM t WHERE b = 'it''s ?'", None),
    # IS ? / IS NOT ?
    ("SELECT a FROM t WHERE x IS ? AND y IS NOT ? AND z IS NULL",
     "SELECT a FROM t WHERE x IS NOT DISTINCT FROM %s AND y IS DISTINCT FROM %s AND z IS NULL", None),
    # NULL ordena como no SQLite; virgula dentro de literal nao separa itens
    ("SELECT a FROM t ORDER BY CASE WHEN d = 'a,b' THEN 1 END, e DESC",
     "SELECT a FROM t ORDER BY CASE WHEN d = 'a,b' THEN 1 END NULLS FIRST, e DESC NULLS LAST", None),
    ("SELECT a FROM t ORDER BY a NULLS LAST, b desc LIMIT 3", "SELECT a FROM t ORDER BY a NULLS LAST, b desc NULLS LAST LIMIT 3", None),
    # MIN/MAX escalares: NULL quando algum argumento e NULL; agregado fica
    ("SELECT MIN(a, b), max(a, (SELECT MAX(c) FROM u)), MIN(x) FROM t",
     "SELECT CASE WHEN (a) IS NULL OR (b) IS NULL THEN NULL ELSE LEAST(a, b) END, CASE WHEN (a) IS NULL OR "
     "((SELECT MAX(c) FROM u)) IS NULL THEN NULL ELSE GREATEST(a, (SELECT MAX(c) FROM u)) END, MIN(x) FROM t", None),
    ("SELECT MIN(a, ')') FROM t", "SELECT CASE WHEN (a) IS NULL OR (')') IS NULL THEN NULL ELSE LEAST(a, ')') END FROM t", None),
    # divisao por zero da NULL
    ("SELECT a / b, (a + 1) / (b - 1), a / COUNT(*), a / NULLIF(b, 0), a / -b, 'x/y' FROM t",
     "SELECT a / NULLIF(b, 0), (a + 1) / NULLIF((b - 1), 0), a / NULLIF(COUNT(*), 0), a / NULLIF(b, 0), a / NULLIF(-b, 0), 'x/y' FROM t", None),
    ("SELECT 100.0 * a / MIN(b, c) FROM t",
     "SELECT 100.0::double precision * a / NULLIF(CASE WHEN (b) IS NULL OR (c) IS NULL THEN NULL ELSE LEAST(b, c) END, 0) FROM t", None),
    # LIKE: ILIKE; sem escape padrao (o SQLite nao tem); ESCAPE explicito fica
    ("SELECT a FROM t WHERE b LIKE ? OR c NOT LIKE ? ESCAPE '\\' OR d LIKE 'erro:%' OR e LIKE 'a\\b'",
     "SELECT a FROM t WHERE b ILIKE %s COLLATE \"C\" ESCAPE '' OR c NOT ILIKE %s COLLATE \"C\" ESCAPE '\\' "
     "OR d ILIKE 'erro:%%' COLLATE \"C\" OR e ILIKE 'a\\b' COLLATE \"C\" ESCAPE ''", None),
    # lower/upper so mudam letras ASCII, como no SQLite (o parametro usaria a colacao do banco)
    ("SELECT 1 FROM grupos WHERE lower(nome) = lower(?) ORDER BY upper(x)",
     'SELECT 1 FROM grupos WHERE lower((nome) COLLATE "C") = lower((%s) COLLATE "C") ORDER BY upper((x) COLLATE "C") NULLS FIRST', None),
    # ? IS NULL: o PostgreSQL precisa do tipo do parametro
    ("SELECT a FROM t WHERE (? IS NULL OR a = ?) AND ? is not null",
     "SELECT a FROM t WHERE (CAST(%s AS TEXT) IS NULL OR a = %s) AND CAST(%s AS TEXT) is not null", None),
    # CASE no COALESCE nao e condicao (a razao real nao vira inteiro); NOT no nivel de cima e
    ("SELECT COALESCE(CASE WHEN n > 0 THEN 1.0 * x / n END, 0), COALESCE(NOT x, 0) FROM t",
     "SELECT COALESCE(CASE WHEN n > 0 THEN 1.0::double precision * x / NULLIF(n, 0) END, 0), COALESCE((NOT x)::int, 0) FROM t", None),
    ("SELECT * FROM execucoes WHERE run_id = ?", "SELECT run_id, iniciado_em FROM execucoes WHERE run_id = %s", None),
    # INSERT: RETURNING da identidade (lastrowid); OR IGNORE -> ON CONFLICT DO NOTHING
    ("INSERT OR IGNORE INTO grupos (nome) VALUES (?)",
     "INSERT INTO grupos (nome) VALUES (%s) ON CONFLICT DO NOTHING RETURNING grupo_id", "grupo_id"),
    ("INSERT INTO grupos (nome) VALUES (?)", "INSERT INTO grupos (nome) VALUES (%s) RETURNING grupo_id", "grupo_id"),
    ("INSERT INTO metricas_run (run_id, chave, valor) VALUES (?,?,?)",
     "INSERT INTO metricas_run (run_id, chave, valor) VALUES (%s,%s,%s)", None),
    ("INSERT INTO grupos (nome) VALUES (?) RETURNING grupo_id", "INSERT INTO grupos (nome) VALUES (%s) RETURNING grupo_id", None),
    ("INSERT INTO tabela_desconhecida (x) VALUES (?)", "INSERT INTO tabela_desconhecida (x) VALUES (%s)", None),
    # rowid -> ordem_gravacao; SELECT * nao devolve a coluna que so existe no PostgreSQL
    ("SELECT * FROM execucoes ORDER BY iniciado_em, rowid",
     "SELECT run_id, iniciado_em FROM execucoes ORDER BY iniciado_em NULLS FIRST, ordem_gravacao NULLS FIRST", None),
    ("SELECT e.run_id FROM execucoes e ORDER BY e.rowid DESC",
     "SELECT e.run_id FROM execucoes e ORDER BY e.ordem_gravacao DESC NULLS LAST", None),
    ("SELECT * FROM grupos", "SELECT * FROM grupos", None),
    ("SELECT name FROM sqlite_master WHERE type = 'table'",
     "SELECT name FROM (SELECT table_name AS name, CASE table_type WHEN 'VIEW' THEN 'view' ELSE 'table' END AS type, "
     "NULL::text AS sql FROM information_schema.tables WHERE table_schema = current_schema()) sqlite_master WHERE type = 'table'", None),
    ("SELECT substr(a, 1, 3), SUM(b), 100.0 * c, COALESCE(a = b, 0), group_concat(x, ', ') FROM t;",
     "SELECT compat_substr(a, 1, 3), compat_soma(b), 100.0::double precision * c, COALESCE((a = b)::int, 0), "
     "group_concat(x, ', ' ORDER BY x NULLS FIRST) FROM t", None),
]


@pytest.mark.parametrize("sql,esperado,retorno", TRADUCOES)
def test_traducao(sql, esperado, retorno):
    assert traduzir(sql, TABELAS) == (esperado, retorno)


RECUSAS = [
    ("INSERT OR REPLACE INTO metricas_run (run_id, chave, valor) VALUES (?,?,?)",
     "INSERT OR REPLACE não tem tradução exata no PostgreSQL (só as gravações do painel rodam lá)."),
    ("SELECT a FROM t WHERE b LIKE '%' || ? || '%'",
     "LIKE com padrão concatenado (||) não suportado no PostgreSQL: monte o padrão no Python e use ?."),
    ("SELECT a FROM t WHERE b LIKE c", "LIKE sem ESCAPE com padrão 'c': escreva o padrão como ? ou literal."),
    ("SELECT MAX(?, a) FROM t", "MIN/MAX com mais de um argumento não aceita parâmetro (?) no PostgreSQL: o argumento seria repetido."),
    ("SELECT * FROM execucoes e JOIN grupos g ON 1 = 1",
     "SELECT * com execucoes só na forma SELECT * FROM <tabela> [WHERE/ORDER BY/LIMIT] (a coluna ordem_gravacao só existe no PostgreSQL)."),
    ("SELECT e.* FROM execucoes e",
     "SELECT * com execucoes só na forma SELECT * FROM <tabela> [WHERE/ORDER BY/LIMIT] (a coluna ordem_gravacao só existe no PostgreSQL)."),
    ("SELECT a, e.* FROM execucoes e",
     "SELECT * com execucoes só na forma SELECT * FROM <tabela> [WHERE/ORDER BY/LIMIT] (a coluna ordem_gravacao só existe no PostgreSQL)."),
    ("SELECT a / FROM t", "Divisão por expressão sem parênteses não suportada no PostgreSQL: 'FROM t'."),
    ("SELECT a FROM t WHERE a /", "SQL malformado (parênteses ou operador sem operando)."),
    ("SELECT a / CASE WHEN b > 0 THEN b END FROM t",
     "Divisão por expressão sem parênteses não suportada no PostgreSQL: 'CASE WHEN b > 0 THEN b END FROM t'."),
]


@pytest.mark.parametrize("sql,mensagem", RECUSAS)
def test_sem_traducao_exata_e_recusado(sql, mensagem):
    with pytest.raises(ValueError) as e:
        traduzir(sql, TABELAS)
    assert str(e.value) == mensagem


INVALIDA = "A DATABASE_URL é inválida (confira o formato postgresql://usuario:senha@host/banco)."
SEM_TLS = "Conexão remota sem TLS: acrescente sslmode=require à DATABASE_URL."


@pytest.mark.parametrize("url,mensagem", [
    ("postgresql://u:p@db.exemplo.org/banco", SEM_TLS),
    ("postgresql://u:p@localhost/banco?hostaddr=203.0.113.5", SEM_TLS),          # hostaddr remoto: nao e local
    ("postgresql://u:p@localhost/banco?host=db.exemplo.org", SEM_TLS),
    ("postgresql://u:p@db.exemplo.org/banco?sslmode=require&sslmode=disable", SEM_TLS),
    ("postgresql:///banco", INVALIDA),                                           # sem host: a libpq usaria o PGHOST
    ("postgresql://u:p@/banco?service=nuvem", INVALIDA),
    ("mysql://u:p@localhost/banco", INVALIDA),
    ("", INVALIDA),
])
def test_pool_recusa_url(url, mensagem):
    with pytest.raises(ValueError) as e:
        criar_pool(url)
    assert str(e.value) == mensagem and "u:p" not in str(e.value)


@pytest.mark.parametrize("url", [
    "postgresql://u:p@ep-x-pooler.sa-east-1.aws.neon.tech/banco?sslmode=require",   # o pool do Neon e o esperado aqui
    "postgresql://u:p@localhost/banco",
    "postgresql://u:p@127.0.0.1:5432/banco",
    "postgresql://u:p@db.exemplo.org/banco?sslmode=disable&sslmode=verify-full",
])
def test_pool_aceita_url_sem_conectar(url):
    pool = criar_pool(url)                            # min_size=0: nenhuma conexao e aberta aqui
    pool.close()


@pytest.mark.parametrize("valor,esperado", [(None, "sqlite"), ("", "sqlite"), ("   ", "sqlite"), ("sqlite", "sqlite"),
                                            (" Postgres ", "postgres"), ("POSTGRES", "postgres")])
def test_banco_do_ambiente(monkeypatch, valor, esperado):
    import composicao
    if valor is None:
        monkeypatch.delenv("DB_BACKEND", raising=False)
    else:
        monkeypatch.setenv("DB_BACKEND", valor)
    assert composicao.banco_do_ambiente() == esperado


def test_banco_do_ambiente_desconhecido(monkeypatch):
    import composicao
    monkeypatch.setenv("DB_BACKEND", "mysql")
    with pytest.raises(SystemExit) as e:
        composicao.banco_do_ambiente()
    assert str(e.value) == "DB_BACKEND aceita só sqlite ou postgres."


@pytest.mark.parametrize("ambiente,simulado,mensagem", [
    ({"DB_BACKEND": "postgres"}, False, "Com DB_BACKEND=postgres, defina DATABASE_URL (no Neon, a URL com -pooler; com --banco vies, a URL direta)."),
    ({"DB_BACKEND": "postgres", "DATABASE_URL": "   "}, False,
     "Com DB_BACKEND=postgres, defina DATABASE_URL (no Neon, a URL com -pooler; com --banco vies, a URL direta)."),
    ({"DB_BACKEND": "postgres", "DATABASE_URL": "postgresql://u:p@localhost/b"}, True,
     "--simulado usa só o SQLite: tire DB_BACKEND=postgres do ambiente."),
    ({"DB_BACKEND": "postgres", "DATABASE_URL": "postgresql://u:p@db.exemplo.org/b"}, False, SEM_TLS),
    ({"DB_BACKEND": "postgres", "DATABASE_URL": "nao-e-url"}, False, INVALIDA),
])
def test_fabrica_postgres_recusa(monkeypatch, ambiente, simulado, mensagem):
    import composicao
    monkeypatch.delenv("DATABASE_URL", raising=False)
    for k, v in ambiente.items():
        monkeypatch.setenv(k, v)
    with pytest.raises(SystemExit) as e:
        composicao.Fabrica(simulado=simulado).postgres
    assert str(e.value) == mensagem


def test_fabrica_sqlite_por_padrao(monkeypatch):
    import composicao
    monkeypatch.delenv("DB_BACKEND", raising=False)
    assert composicao.Fabrica(simulado=True).postgres is None


@pytest.mark.parametrize("comando", ["estimar", "painel-relatorio"])
def test_comando_fora_do_painel_recusa_postgres(comando):
    """Com DB_BACKEND=postgres so rodam painel, usuario-admin, pg-migrar e pg-demo; o resto le o SQLite local."""
    env = {k: v for k, v in __import__("os").environ.items() if k not in ("DATABASE_URL", "DATABASE_URL_DIRECT")}
    env.update(DB_BACKEND="postgres", PYTHON_DOTENV_DISABLED="1")
    r = subprocess.run([sys.executable, "main.py", comando], cwd=RAIZ, env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 1 and r.stderr.strip().endswith(
        f"O comando {comando} roda só no SQLite local: tire DB_BACKEND=postgres do ambiente.")


# ---------- dependencias: toda biblioteca importada pelo codigo que roda no painel e na coleta esta declarada ----------
# modulo importado -> nome no requirements.txt (as que chegam como dependencia de outra declarada: entre parenteses)
DECLARADAS = {"dotenv": "python-dotenv", "fastapi": "fastapi", "markupsafe": "(jinja2)", "openpyxl": "openpyxl",
              "pandas": "pandas", "psycopg": "psycopg", "psycopg_pool": "psycopg-pool", "pypdf": "pypdf",
              "requests": "requests", "starlette": "(fastapi)", "trafilatura": "trafilatura", "uvicorn": "uvicorn"}


def _importados():
    locais = {p.name for p in RAIZ.iterdir() if p.is_dir()} | {p.stem for p in RAIZ.glob("*.py")}
    arquivos = list(RAIZ.glob("*.py")) + [f for d in ("adaptadores", "aplicacao", "dominio", "painel", "config", "infra")
                                           for f in (RAIZ / d).rglob("*.py")]
    achados = set()
    for p in arquivos:
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            nomes = ([a.name for a in n.names] if isinstance(n, ast.Import)
                     else [n.module] if isinstance(n, ast.ImportFrom) and n.level == 0 and n.module else [])
            for x in nomes:
                topo = x.split(".")[0]
                if topo not in sys.stdlib_module_names and topo not in locais:
                    achados.add(topo)
    return achados


def test_toda_biblioteca_importada_esta_no_requirements():
    requisitos = {l.split("==")[0].split("[")[0].strip().lower()
                  for l in (RAIZ / "requirements.txt").read_text(encoding="utf-8").splitlines() if l.strip()}
    sem_registro = sorted(_importados() - set(DECLARADAS) - {"pytest"})
    assert sem_registro == []
    faltam = sorted(n for n in DECLARADAS.values() if n.strip("()") not in requisitos)
    assert faltam == []
