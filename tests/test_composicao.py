import pytest

import composicao
import config.settings as S
from composicao import Fabrica


class _FetcherFalso:
    """Guarda os argumentos recebidos, no lugar do adaptador real."""
    def __init__(self, **kw):
        self.kw = kw


@pytest.fixture
def fetcher_falso(monkeypatch):
    monkeypatch.setitem(composicao.REGISTROS, "fetcher", {"requests": _FetcherFalso})


def test_user_agent_recebe_o_email_do_ambiente(fetcher_falso, monkeypatch):
    monkeypatch.setenv("RESEARCHER_EMAIL", "pesquisador@exemplo.org")
    ua = Fabrica().fetcher.kw["user_agent"]
    assert "contact: pesquisador@exemplo.org" in ua and "{email}" not in ua


def test_sem_email_no_ambiente_a_fabrica_encerra(fetcher_falso):
    with pytest.raises(SystemExit) as e:
        Fabrica().fetcher
    assert "RESEARCHER_EMAIL" in str(e.value)


def test_modo_simulado_nao_exige_email(fetcher_falso):
    assert Fabrica(simulado=True).fetcher.nome == "simulado"


def test_email_nao_entra_na_configuracao_nem_no_hash(fetcher_falso, monkeypatch):
    antes = S.snapshot_config()
    monkeypatch.setenv("RESEARCHER_EMAIL", "pesquisador@exemplo.org")
    Fabrica().fetcher
    depois = S.snapshot_config()
    assert depois == antes
    assert "pesquisador@exemplo.org" not in depois["json"] and "{email}" in depois["json"]
