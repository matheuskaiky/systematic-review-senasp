import logging

import pytest

import config.settings as S

CHAVES = ("SERPAPI_KEY", "PERPLEXITY_API_KEY", "GEMINI_API_KEY", "LLM_API_KEY", "RESEARCHER_EMAIL")


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
    monkeypatch.setattr(S, "PAUSAS", {k: 0 for k in S.PAUSAS})
    return tmp_path
