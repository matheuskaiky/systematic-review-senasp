import logging
import sys

import pytest
import requests

from infra import http, log
from infra.util import agora


class _Resp:
    def __init__(self, status, texto="", content=b""):
        self.status_code, self.text, self.content = status, texto, content
        self.ok = status < 400
        self.closed = False

    def close(self):
        self.closed = True


@pytest.fixture
def pausas(monkeypatch):
    """Substitui time.sleep e devolve a lista de esperas pedidas."""
    esperas = []
    monkeypatch.setattr(http.time, "sleep", lambda s: esperas.append(s))
    return esperas


def _sequencia(monkeypatch, itens):
    """requests.request devolve (ou levanta) os itens em ordem."""
    chamadas = []

    def falso(metodo, url, **kw):
        chamadas.append((metodo, url, kw))
        item = itens[min(len(chamadas), len(itens)) - 1]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(http.requests, "request", falso)
    return chamadas


def test_chamar_nunca_levanta_em_erro_de_rede(monkeypatch, pausas):
    chamadas = _sequencia(monkeypatch, [requests.ConnectionError("sem rede")])
    r = http.chamar("GET", "https://x", max_tentativas=3)
    assert r["resp"] is None and r["http_status"] is None
    assert "ConnectionError" in r["erro"]
    assert r["tentativas"] == 3 and len(chamadas) == 3
    assert pausas == [2, 4]                   # espera_base ** tentativa, sem esperar apos a ultima


def test_chamar_503_depois_200(monkeypatch, pausas):
    chamadas = _sequencia(monkeypatch, [_Resp(503), _Resp(200, "ok")])
    r = http.chamar("GET", "https://x")
    assert r["erro"] is None and r["http_status"] == 200 and r["tentativas"] == 2
    assert r["resp"].text == "ok" and len(chamadas) == 2
    assert pausas == [2]


def test_chamar_503_em_todas_as_tentativas_devolve_o_erro(monkeypatch, pausas):
    _sequencia(monkeypatch, [_Resp(503, "indisponivel")])
    r = http.chamar("GET", "https://x", max_tentativas=2)
    assert r["http_status"] == 503 and r["tentativas"] == 2
    assert r["erro"].startswith("HTTP 503") and "indisponivel" in r["erro"]


def test_chamar_erro_nao_retentavel_nao_repete(monkeypatch, pausas):
    chamadas = _sequencia(monkeypatch, [_Resp(404, "nao achei")])
    r = http.chamar("GET", "https://x")
    assert r["http_status"] == 404 and r["tentativas"] == 1 and len(chamadas) == 1
    assert r["erro"] == "HTTP 404: nao achei" and pausas == []


def test_chamar_com_stream_nao_le_o_corpo_no_erro(monkeypatch, pausas):
    _sequencia(monkeypatch, [_Resp(404, "corpo")])
    r = http.chamar("GET", "https://x", stream=True)
    assert r["erro"] == "HTTP 404"


def test_chamar_repassa_parametros(monkeypatch, pausas):
    chamadas = _sequencia(monkeypatch, [_Resp(200)])
    http.chamar("POST", "https://x", params={"a": 1}, json_body={"b": 2}, headers={"h": "v"}, timeout=7)
    metodo, url, kw = chamadas[0]
    assert (metodo, url) == ("POST", "https://x")
    assert kw["params"] == {"a": 1} and kw["json"] == {"b": 2} and kw["headers"] == {"h": "v"} and kw["timeout"] == 7


def test_agora_e_iso_8601_em_utc():
    assert agora().endswith("+00:00") and "T" in agora()


# ---------- C13: log ----------
@pytest.fixture
def raiz_limpa():
    raiz = logging.getLogger()
    salvos, nivel = list(raiz.handlers), raiz.level
    yield raiz
    for h in list(raiz.handlers):
        raiz.removeHandler(h)
        h.close()
    for h in salvos:
        raiz.addHandler(h)
    raiz.setLevel(nivel)


def test_iniciar_log_duas_vezes_deixa_dois_handlers(raiz_limpa, tmp_path):
    log.iniciar_log("run_a", tmp_path)
    log.iniciar_log("run_b", tmp_path)
    assert len(raiz_limpa.handlers) == 2


def test_iniciar_log_grava_em_arquivo_com_acentos(raiz_limpa, tmp_path):
    log.iniciar_log("run_c", tmp_path / "logs")
    logging.info("Segurança pública: ação")
    for h in raiz_limpa.handlers:
        h.flush()
    assert "Segurança pública: ação" in (tmp_path / "logs" / "run_c.log").read_text(encoding="utf-8")


def test_iniciar_log_reconfigura_stdout_quando_disponivel(raiz_limpa, tmp_path, monkeypatch):
    chamado = {}

    class Saida:
        def reconfigure(self, **kw):
            chamado.update(kw)

        def write(self, s):
            pass

        def flush(self):
            pass

    monkeypatch.setattr(sys, "stdout", Saida())
    log.iniciar_log("run_d", tmp_path)
    assert chamado == {"encoding": "utf-8", "errors": "replace"}
