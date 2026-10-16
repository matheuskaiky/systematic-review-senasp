"""Cota DIARIA esgotada (nivel gratuito do Gemini): reconhecer, nao repetir e parar a etapa sem espalhar falhas."""
import json
import logging

import pytest

import adaptadores.classificador_gemini as modulo
from adaptadores.classificador_gemini import ClassificadorGemini
from dados_metricas import _params, construir_downloads
from aplicacao import classificacao
from config import consultas as C
from dominio.erros import CotaDiariaEsgotada
from dominio.modelos import EntradaClassificacao, Instrucoes, RegistroChamada, ResultadoClassificacao
from infra import http
from test_classificador_gemini import ESQUEMA, _Resp, _chamar

DIARIA = json.dumps({"error": {"code": 429, "message": "You exceeded your current quota. * Quota exceeded for metric: "
    "generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 500, model: gemini-3.5-flash-lite\nPlease retry in 2h49m27s.",
    "status": "RESOURCE_EXHAUSTED", "details": [
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [
            {"quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
             "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier", "quotaValue": "500"}]},
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "10167s"}]}})
POR_MINUTO = json.dumps({"error": {"code": 429, "message": "Quota exceeded", "details": [
    {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{"quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}]},
    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "27s"}]}})


# ---------- reconhecimento ----------
def test_reconhece_a_cota_diaria_e_o_tempo_para_renovar():
    assert http.cota_diaria_esgotada(DIARIA) == (True, 10167.0)


@pytest.mark.parametrize("texto", [POR_MINUTO, "isto nao e json", "{}", '{"error": {"code": 500, "message": "PerDay"}}', "null", "[1]", ""])
def test_cota_por_minuto_erro_comum_e_texto_estranho_nao_sao_cota_diaria(texto):
    assert http.cota_diaria_esgotada(texto) == (False, None)


def test_reconhece_pela_mensagem_quando_nao_ha_detalhes():
    assert http.cota_diaria_esgotada(json.dumps({"error": {"code": 429, "message": "limit exceeded GenerateRequestsPerDay"}}))[0] is True


# ---------- chamar nao repete cota diaria, mas repete o resto ----------
class _R:
    def __init__(self, status, texto=""):
        self.status_code, self.text, self.content, self.ok = status, texto, texto.encode(), status < 400

    def close(self):
        pass


def _requests(monkeypatch, respostas):
    fila, chamadas, dormiu = list(respostas), [], []
    monkeypatch.setattr(http.requests, "request", lambda *a, **k: (chamadas.append(1), fila.pop(0))[1])
    monkeypatch.setattr(http.time, "sleep", lambda s: dormiu.append(s))
    return chamadas, dormiu


def test_chamar_sem_o_gancho_repete_o_429_como_antes(monkeypatch):
    chamadas, dormiu = _requests(monkeypatch, [_R(429, DIARIA)] * 4)
    r = http.chamar("POST", "https://x.example/a")
    assert len(chamadas) == 4 and r["http_status"] == 429 and dormiu == [2, 4, 8]


def test_chamar_com_cota_diaria_faz_uma_tentativa_e_nao_espera(monkeypatch):
    chamadas, dormiu = _requests(monkeypatch, [_R(429, DIARIA)] * 4)
    r = http.chamar("POST", "https://x.example/a", nao_repetir=lambda resp: http.cota_diaria_esgotada(resp.text)[0])
    assert len(chamadas) == 1 and dormiu == [] and r["tentativas"] == 1 and r["http_status"] == 429 and r["erro"].startswith("HTTP 429")


def test_chamar_com_cota_por_minuto_ou_503_continua_repetindo(monkeypatch):
    for corpo, status in ((POR_MINUTO, 429), ("", 503)):
        chamadas, dormiu = _requests(monkeypatch, [_R(status, corpo), _R(200, "{}")])
        r = http.chamar("POST", "https://x.example/a", nao_repetir=lambda resp: http.cota_diaria_esgotada(resp.text)[0])
        assert len(chamadas) == 2 and r["http_status"] == 200 and len(dormiu) == 1


# ---------- adaptador ----------
def _gemini():
    return ClassificadorGemini("CHAVE-FALSA-123456", "modelo-x", preco_entrada_por_m=0.3, preco_saida_por_m=2.5)


def _entrada():
    return EntradaClassificacao("PI", "https://exemplo.gov.br/pi/1", "Titulo", "texto enviado", "pagina", False)


def test_adaptador_marca_cota_diaria_e_passa_o_gancho_ao_chamar(monkeypatch):
    visto = _chamar(monkeypatch, DIARIA, erro="HTTP 429: ...", http_status=429)
    c = _gemini().classificar(_entrada(), Instrucoes("v", "S", "U", ESQUEMA)).chamada
    assert c.extras["cota_diaria_esgotada"] is True and c.extras["cota_renova_em_s"] == 10167.0 and not c.sucesso
    assert callable(visto["nao_repetir"]) and visto["nao_repetir"](_Resp(DIARIA)) and not visto["nao_repetir"](_Resp(POR_MINUTO))


def test_adaptador_nao_marca_outros_429(monkeypatch):
    _chamar(monkeypatch, POR_MINUTO, erro="HTTP 429: ...", http_status=429)
    c = _gemini().classificar(_entrada(), Instrucoes("v", "S", "U", ESQUEMA)).chamada
    assert "cota_diaria_esgotada" not in c.extras


# ---------- etapa ----------
class _CotaNoSegundo:
    nome = "gemini:teste"

    def __init__(self):
        self.n = 0

    def classificar(self, entrada, instr):
        self.n += 1
        reg = RegistroChamada(provedor=self.nome, operacao="classificar", parametros={}, requisitado_em="2026-10-16T00:00:00+00:00",
                              http_status=200, latencia_ms=1, tokens_entrada=10, tokens_saida=5, custo_usd=0.0)
        if self.n >= 2:
            reg.erro, reg.http_status = "HTTP 429: cota", 429
            reg.extras.update({"cota_diaria_esgotada": True, "cota_renova_em_s": 7200.0})
            return ResultadoClassificacao(False, [], False, "", reg)
        return ResultadoClassificacao(False, [], True, "{}", reg)


def test_etapa_para_no_primeiro_429_diario_sem_chamar_mais_nem_marcar_as_outras_falhas(tmp_path):
    logging.disable(logging.CRITICAL)
    try:
        repo, run_id = construir_downloads(tmp_path)
        fake = _CotaNoSegundo()
        with pytest.raises(CotaDiariaEsgotada) as e:
            classificacao.executar(repo, repo_bruto(tmp_path), fake, run_id, run_id, _params(), C.UFS, [], 0, ufs={"PI"})
    finally:
        logging.disable(logging.NOTSET)
    assert fake.n == 2                                                    # a segunda chamada falhou e a etapa parou ali
    assert "2h00min" in str(e.value) and "--retomar" in str(e.value) and e.value.renova_em_s == 7200.0
    assert repo.conn.execute("SELECT valor FROM metricas_run WHERE run_id=? AND chave='classificacao_parada_cota_diaria'", (run_id,)).fetchone()[0] == 1
    assert repo.conn.execute("SELECT COUNT(*) FROM chamadas WHERE run_id=? AND etapa='classificacao' AND sucesso=0", (run_id,)).fetchone()[0] == 1


def repo_bruto(tmp_path):
    from adaptadores.bruto_local import BrutoLocal
    return BrutoLocal(tmp_path / "raw")


def test_mensagem_do_erro_de_dominio():
    assert "5h03min" in str(CotaDiariaEsgotada("gemini", "", 18200)) and "esgotada" in str(CotaDiariaEsgotada("gemini"))
