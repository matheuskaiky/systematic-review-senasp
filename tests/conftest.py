import logging
import shutil

import pytest

import config.settings as S

CHAVES = ("SERPAPI_KEY", "PERPLEXITY_API_KEY", "GEMINI_API_KEY", "LLM_API_KEY", "RESEARCHER_EMAIL",
          "DATABASE_URL", "DATABASE_URL_DIRECT")         # nenhum teste toca um banco PostgreSQL real


@pytest.fixture(autouse=True)
def sem_chaves(monkeypatch):
    """Nenhum teste pode usar chave real: o main carrega o .env ao ser importado."""
    for c in CHAVES:
        monkeypatch.delenv(c, raising=False)


@pytest.fixture
def raiz_limpa():
    """Isola o logger raiz: iniciar_log remove e recria os handlers."""
    raiz = logging.getLogger()
    salvos, nivel = list(raiz.handlers), raiz.level
    yield raiz
    for h in list(raiz.handlers):
        raiz.removeHandler(h)
        h.close()
    for h in salvos:
        raiz.addHandler(h)
    raiz.setLevel(nivel)


@pytest.fixture
def ambiente_cli(tmp_path, monkeypatch, raiz_limpa):
    """Aponta dados, logs e saidas para tmp_path e zera as pausas entre chamadas."""
    monkeypatch.setattr(S, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(S, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(S, "OUT_DIR", tmp_path / "outputs")
    monkeypatch.setitem(S.OPCOES["excel"], "pasta", tmp_path / "outputs")
    monkeypatch.setattr(S, "PAUSAS", {k: 0 for k in S.PAUSAS})
    # o commit gravado em cada execucao vem de 3 chamadas ao git (segundos cada em /mnt/c); nenhum teste da CLI confere
    # esse valor, e o proprio _commit_git tem testes com um repositorio de verdade (test_auditoria_coleta.py)
    import main
    monkeypatch.setattr(main, "_commit_git", lambda: "teste00")
    return tmp_path


@pytest.fixture(scope="session")
def copiar_demo(tmp_path_factory):
    """Constroi o banco de demonstracao uma vez por sessao (leva uns 18 s) e entrega a cada modulo uma copia propria da pasta,
    com `demo.db` e `raw_demo/`: os modulos que gravam no banco nao contaminam os outros. Devolve (banco, raw)."""
    import painel_demo
    modelo = tmp_path_factory.mktemp("demo_modelo")
    banco = painel_demo.construir(modelo)

    def copiar(nome):
        destino = tmp_path_factory.mktemp(nome)
        shutil.copytree(modelo, destino, dirs_exist_ok=True)
        return destino / banco.name, destino / "raw_demo"
    return copiar


def _banco_pg_descartavel():
    """Um banco PostgreSQL novo e vazio num servidor descartavel (PG_TESTE_URL aponta o banco de administracao, ex.:
    postgresql://postgres:teste@127.0.0.1:55432/postgres), com a colacao do Neon (C.UTF-8). Apagado no fim. Sem
    PG_TESTE_URL, o teste e pulado; um servidor que nao e local e recusado (os testes criam e apagam bancos)."""
    import os
    import uuid
    from urllib.parse import urlsplit, urlunsplit
    adm = os.environ.get("PG_TESTE_URL", "").strip()
    if not adm:
        pytest.skip("PG_TESTE_URL nao definida: sem PostgreSQL de teste")
    if (urlsplit(adm).hostname or "") not in ("localhost", "127.0.0.1"):
        pytest.fail("PG_TESTE_URL so pode apontar para um PostgreSQL local descartavel: os testes criam e apagam bancos")
    import psycopg
    nome = "t_" + uuid.uuid4().hex[:12]
    with psycopg.connect(adm, autocommit=True) as c:
        c.execute(f"CREATE DATABASE {nome} TEMPLATE template0 LC_COLLATE 'C.UTF-8' LC_CTYPE 'C.UTF-8'")
    p = urlsplit(adm)
    try:
        yield urlunsplit((p.scheme, p.netloc, "/" + nome, p.query, ""))
    finally:
        with psycopg.connect(adm, autocommit=True) as c:
            c.execute(f"DROP DATABASE IF EXISTS {nome} WITH (FORCE)")


@pytest.fixture
def pg_url():
    yield from _banco_pg_descartavel()


@pytest.fixture(scope="module")
def pg_url_modulo():
    yield from _banco_pg_descartavel()
