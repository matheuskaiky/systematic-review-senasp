"""Triador de escopo (Gemini): nenhum teste abre conexao; `chamar` e substituido e as respostas sao sinteticas."""
import json
import pathlib

import pytest

from adaptadores import triador_gemini, REGISTROS
from adaptadores.triador_gemini import TriadorEscopoGemini
from adaptadores.simulados import TriadorSimulado
from config.triagem_escopo import CONFIG
from dominio.modelos import Instrucoes
from dominio.triagem_escopo import chave_item, montar_esquema, montar_mensagem_usuario, validar_resposta

SINT = pathlib.Path(__file__).parent / "fixtures" / "sintetico"
CHAVE = "CHAVE-GEMINI-FALSA-123456"
ITENS = [{"item_id": 1, "fonte": "artigo", "uf": "", "provedor": "serpapi_scholar", "titulo": "Reconhecimento facial na polícia",
          "resumo": "Estudo no Brasil.", "autores_publicacao": "A - B, 2023", "ano": 2023, "termos": ["reconhecimento facial"]},
         {"item_id": 2, "fonte": "artigo", "uf": "", "provedor": "serpapi_scholar", "titulo": "Diagnóstico de pacientes",
          "resumo": "Saúde.", "autores_publicacao": "", "ano": 2024, "termos": ["reconhecimento facial"]}]


def _fix(nome):
    return (SINT / nome).read_text(encoding="utf-8")


def _triador(**kw):
    kw.setdefault("modelo", "gemini-3.5-flash-lite")
    kw.setdefault("preco_entrada_por_m", 0.3)
    kw.setdefault("preco_saida_por_m", 2.5)
    return TriadorEscopoGemini(CHAVE, **kw)


def _instr():
    return Instrucoes("t1", CONFIG.sistema_artigo, montar_mensagem_usuario(ITENS, CONFIG),
                      montar_esquema(CONFIG, [chave_item(i) for i in ITENS]))


class _Resp:
    def __init__(self, texto):
        self.text, self.content = texto, texto.encode()


def _chamar(monkeypatch, texto=None, erro=None, http_status=200):
    visto = {}

    def falso(metodo, url, **kw):
        visto.update(metodo=metodo, url=url, **kw)
        return {"resp": _Resp(texto) if texto is not None else None, "http_status": http_status, "latencia_ms": 900,
                "tentativas": 1, "erro": erro, "latencia_total_ms": 900, "historico": [], "corpo_erro": None}

    monkeypatch.setattr(triador_gemini, "chamar", falso)
    return visto


def test_registrado_como_triador_gemini_e_padrao_de_8192_tokens():
    assert REGISTROS["triador"]["gemini"] is TriadorEscopoGemini
    assert _triador()._max == 8192 and _triador(max_tokens_saida=4000)._max == 4000


def test_sucesso_devolve_texto_do_modelo_tokens_custo_e_extras(monkeypatch):
    visto = _chamar(monkeypatch, _fix("gemini_triagem_sintetico.json"))
    res = _triador().triar(ITENS, _instr())
    reg = res.chamada
    assert reg.sucesso and reg.operacao == "triar_escopo" and reg.provedor == "gemini:gemini-3.5-flash-lite"
    assert "Raciocinio interno" not in res.texto_resposta                 # a parte de raciocinio fica de fora
    assert (reg.tokens_entrada, reg.tokens_saida) == (1800, 260 + 140)
    assert reg.custo_usd == pytest.approx((1800 * 0.3 + 400 * 2.5) / 1e6)
    assert reg.extras["custo_origem"] == "calculado_por_tokens" and reg.extras["service_tier"] == "standard"
    assert reg.id_externo == "resp-sintetico-triagem-0001" and reg.raw
    assert reg.parametros["n_itens"] == 2 and reg.parametros["itens"] == ["1", "2"] and reg.parametros["prompt_versao"] == "t1"
    assert visto["url"].endswith("/models/gemini-3.5-flash-lite:generateContent")
    assert visto["json_body"]["generationConfig"]["maxOutputTokens"] == 8192
    # o texto devolvido passa pelas conferencias do dominio
    linhas, extras = validar_resposta(ITENS, res.texto_resposta, CONFIG)
    assert extras["json_valido"] and [l["status"] for l in linhas] == ["elegivel", "quarentena"]
    assert linhas[1]["termo_gerador"] == "reconhecimento facial" and linhas[1]["valido"]


def test_a_chave_vai_no_cabecalho_e_nunca_nos_parametros_ou_extras(monkeypatch):
    visto = _chamar(monkeypatch, _fix("gemini_triagem_sintetico.json"))
    reg = _triador().triar(ITENS, _instr()).chamada
    assert visto["headers"]["x-goog-api-key"] == CHAVE
    tudo = json.dumps(reg.parametros) + json.dumps(reg.extras, default=str) + str(reg.erro)
    assert CHAVE not in tudo and CHAVE not in str(visto["json_body"])


def test_max_tokens_e_falha_com_tokens_e_custo_gravados(monkeypatch):
    _chamar(monkeypatch, _fix("gemini_triagem_max_tokens_sintetico.json"))
    reg = _triador().triar(ITENS, _instr()).chamada
    assert not reg.sucesso and reg.erro == "resposta_truncada: MAX_TOKENS"
    assert reg.tokens_saida == 30 + 8162 and reg.custo_usd == pytest.approx((1800 * 0.3 + 8192 * 2.5) / 1e6)
    assert reg.extras["finish_reason"] == "MAX_TOKENS"


def test_erro_http_vira_falha_sem_levantar(monkeypatch):
    _chamar(monkeypatch, texto=None, erro="HTTP 500", http_status=500)
    res = _triador().triar(ITENS, _instr())
    assert not res.chamada.sucesso and res.chamada.erro == "HTTP 500" and res.texto_resposta == ""
    assert res.chamada.custo_usd is None


def test_prompt_bloqueado_registra_motivo_e_custo_conservador(monkeypatch):
    _chamar(monkeypatch, _fix("gemini_sem_candidatos_sintetico.json"))
    reg = _triador().triar(ITENS, _instr()).chamada
    assert reg.erro == "sem_candidatos: SAFETY" and reg.extras["custo_cobranca_incerta"] is True
    assert reg.tokens_entrada == 1200 and reg.custo_usd == pytest.approx(1200 * 0.3 / 1e6)


def test_candidato_sem_conteudo_e_falha(monkeypatch):
    _chamar(monkeypatch, _fix("gemini_sem_conteudo_sintetico.json"))
    assert _triador().triar(ITENS, _instr()).chamada.erro == "sem_conteudo: SAFETY"


def test_resposta_que_nao_e_json_da_api_vira_resposta_inesperada(monkeypatch):
    _chamar(monkeypatch, "nao e json")
    assert _triador().triar(ITENS, _instr()).chamada.erro.startswith("resposta_inesperada")


@pytest.mark.parametrize("formato", ["responseSchema", "responseJsonSchema", "responseFormat"])
def test_corpo_aceita_os_tres_formatos_de_esquema(formato):
    corpo = _triador(formato_esquema=formato)._corpo(_instr())
    assert corpo["systemInstruction"]["parts"][0]["text"] == CONFIG.sistema_artigo
    assert corpo["contents"][0]["parts"][0]["text"].startswith("Screen the following 2 items")


# ---------------------------------------------------------------- triador simulado
def test_simulado_obedece_ao_esquema_e_mistura_status():
    itens = [{**ITENS[0], "item_id": n, "termos": ["termo a"]} for n in range(1, 41)]
    res = TriadorSimulado().triar(itens, Instrucoes("t1", "s", "u", {}))
    linhas, extras = validar_resposta(itens, res.texto_resposta, CONFIG)
    assert extras["ids_ausentes"] == [] and all(l["valido"] for l in linhas)
    status = {l["status"] for l in linhas}
    assert status == {"elegivel", "quarentena", "excluido"}
    assert any(l["status_bruto"] == "excluido" and l["status"] == "quarentena" for l in linhas)   # regra de seguranca
    assert len({l["categoria_motivo"] for l in linhas if l["categoria_motivo"]}) >= 3
    assert res.chamada.sucesso and res.chamada.operacao == "triar_escopo"


def test_simulado_omite_ids_e_devolve_termo_ruim_sob_comando():
    itens = [{**ITENS[0], "item_id": n, "termos": ["termo a"]} for n in range(1, 21)]
    res = TriadorSimulado(omitir={"3"}, termo_ruim=True).triar(itens, Instrucoes("t1", "s", "u", {}))
    linhas, extras = validar_resposta(itens, res.texto_resposta, CONFIG)
    assert extras["ids_ausentes"] == ["3"]
    assert any("termo_gerador_fora_da_lista" in l["problemas"] for l in linhas)
    assert TriadorSimulado(json_invalido=True).triar(itens, Instrucoes("t1", "s", "u", {})).texto_resposta == "isto nao e json"
    assert not TriadorSimulado(falhar_chamadas={1}).triar(itens, Instrucoes("t1", "s", "u", {})).chamada.sucesso


_CORPO_429_DIARIO = json.dumps({"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "Quota exceeded",
    "details": [{"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [
        {"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]},
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "7200s"}]}})
_CORPO_429_MINUTO = json.dumps({"error": {"code": 429, "message": "Quota exceeded",
    "details": [{"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [
        {"quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}]}]}})


def test_429_de_cota_diaria_marca_extras_e_pede_para_nao_repetir(monkeypatch):
    visto = _chamar(monkeypatch, _CORPO_429_DIARIO, erro="HTTP 429", http_status=429)
    reg = _triador().triar(ITENS, _instr()).chamada
    assert not reg.sucesso and reg.extras["cota_diaria_esgotada"] is True and reg.extras["cota_renova_em_s"] == 7200.0
    assert visto["nao_repetir"](_Resp(_CORPO_429_DIARIO)) is True        # chamar() devolve na hora, sem novas tentativas
    assert visto["nao_repetir"](_Resp(_CORPO_429_MINUTO)) is False       # cota por minuto continua retentavel


def test_429_por_minuto_nao_marca_cota_diaria(monkeypatch):
    _chamar(monkeypatch, _CORPO_429_MINUTO, erro="HTTP 429", http_status=429)
    assert "cota_diaria_esgotada" not in _triador().triar(ITENS, _instr()).chamada.extras
