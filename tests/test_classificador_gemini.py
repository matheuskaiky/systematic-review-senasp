"""M5: classificador Gemini. Nenhum teste abre conexao: `chamar` e substituido."""
import json
import logging
import pathlib

import pytest

from adaptadores import classificador_gemini
from adaptadores.bruto_local import BrutoLocal
from adaptadores.classificador_gemini import ClassificadorGemini, FORMATOS_ESQUEMA, _para_esquema_gemini
from adaptadores.repositorio_sqlite import RepositorioSQLite
from adaptadores.simulados import BuscaSimulada, ExtratorSimulado, FetcherSimulado
from aplicacao import busca_web, classificacao, download
from config import consultas as C, vocabulario as V
from dados_metricas import _consulta_pi, _novo_run, _params
from dominio.esquemas import esquema_classificacao
from dominio.modelos import EntradaClassificacao, Instrucoes

SINT = pathlib.Path(__file__).parent / "fixtures" / "sintetico"
CHAVE = "CHAVE-GEMINI-FALSA-123456"
ESQUEMA = esquema_classificacao(tuple(V.TECNOLOGIAS), tuple(V.STATUS), V.CONFIANCA)


def _fix(nome):
    return (SINT / nome).read_text(encoding="utf-8")


def _gemini(**kw):
    kw.setdefault("modelo", "gemini-3.5-flash-lite")
    kw.setdefault("preco_entrada_por_m", 0.3)
    kw.setdefault("preco_saida_por_m", 2.5)
    return ClassificadorGemini(CHAVE, **kw)


def _instr():
    return Instrucoes("v-teste", "SISTEMA", "USUARIO", ESQUEMA)


def _entrada():
    return EntradaClassificacao("PI", "https://exemplo.gov.br/pi/1", "Titulo", "texto enviado", "pagina", False)


class _Resp:
    def __init__(self, texto):
        self.text, self.content = texto, texto.encode()


def _chamar(monkeypatch, texto=None, erro=None, http_status=200, extras=None):
    visto = {}

    def falso(metodo, url, **kw):
        visto.update(metodo=metodo, url=url, **kw)
        return {"resp": _Resp(texto) if texto is not None else None, "http_status": http_status, "latencia_ms": 800,
                "tentativas": 1, "erro": erro, "latencia_total_ms": 800, "historico": [], "corpo_erro": None, **(extras or {})}

    monkeypatch.setattr(classificador_gemini, "chamar", falso)
    return visto


# ====================== _para_esquema_gemini ======================
def test_tipos_viram_maiusculas_e_a_estrutura_e_preservada():
    e = _para_esquema_gemini(ESQUEMA)
    assert e["type"] == "OBJECT" and e["required"] == ["relevante", "achados"]
    assert e["properties"]["relevante"]["type"] == "BOOLEAN"
    achados = e["properties"]["achados"]
    assert achados["type"] == "ARRAY" and achados["items"]["type"] == "OBJECT"
    p = achados["items"]["properties"]
    assert p["tecnologia"] == {"type": "STRING", "enum": list(V.TECNOLOGIAS)}
    assert p["status"]["enum"] == list(V.STATUS) and p["confianca"]["enum"] == list(V.CONFIANCA)
    assert p["menciona_lgpd"] == {"type": "BOOLEAN"} and p["fornecedor"]["description"]
    assert achados["items"]["required"] == ["tecnologia", "status", "fornecedor", "menciona_lgpd", "evidencia", "confianca"]


def test_campos_fora_do_dialeto_sao_descartados():
    e = _para_esquema_gemini({"type": "object", "additionalProperties": False, "minimum": 1, "title": "x",
                              "properties": {"a": {"type": "integer", "minimum": 0}}})
    assert e == {"type": "OBJECT", "properties": {"a": {"type": "INTEGER"}}}


def test_nenhum_tipo_minusculo_sobra_no_esquema_convertido():
    def tipos(n):
        if isinstance(n, dict):
            yield from ([n["type"]] if isinstance(n.get("type"), str) else [])
            for v in n.values():
                yield from tipos(v)
        elif isinstance(n, list):
            for v in n:
                yield from tipos(v)
    assert all(t == t.upper() for t in tipos(_para_esquema_gemini(ESQUEMA)))


def test_conversao_nao_altera_o_esquema_neutro():
    antes = json.dumps(ESQUEMA, sort_keys=True)
    _para_esquema_gemini(ESQUEMA)
    assert json.dumps(ESQUEMA, sort_keys=True) == antes


# ====================== _corpo ======================
def test_corpo_padrao_usa_responseSchema_da_referencia_rest():
    c = _gemini(temperatura=0.0, max_tokens_saida=4096)._corpo(_instr())
    assert c["systemInstruction"] == {"parts": [{"text": "SISTEMA"}]}
    assert c["contents"] == [{"role": "user", "parts": [{"text": "USUARIO"}]}]
    g = c["generationConfig"]
    assert (g["temperature"], g["maxOutputTokens"], g["responseMimeType"]) == (0.0, 4096, "application/json")
    assert g["responseSchema"]["type"] == "OBJECT" and set(g) == {"temperature", "maxOutputTokens", "responseMimeType", "responseSchema"}


def test_corpo_com_responseJsonSchema_envia_o_esquema_neutro():
    g = _gemini(formato_esquema="responseJsonSchema")._corpo(_instr())["generationConfig"]
    assert g["responseJsonSchema"] == ESQUEMA and "responseSchema" not in g and g["responseMimeType"] == "application/json"


def test_corpo_com_responseFormat_aninha_mimeType_e_schema():
    g = _gemini(formato_esquema="responseFormat")._corpo(_instr())["generationConfig"]
    assert g["responseFormat"] == {"text": {"mimeType": "application/json", "schema": ESQUEMA}}
    assert "responseMimeType" not in g and "responseSchema" not in g


def test_formato_de_esquema_invalido_e_recusado():
    with pytest.raises(ValueError):
        _gemini(formato_esquema="outro")
    assert set(FORMATOS_ESQUEMA) == {"responseSchema", "responseJsonSchema", "responseFormat"}


def test_o_formato_do_esquema_esta_na_configuracao_e_no_hash():
    import config.settings as S
    assert S.OPCOES["gemini"]["formato_esquema"] == "responseSchema" and S.OPCOES["gemini"]["modelo"] == "gemini-3.5-flash-lite"
    antes = S.snapshot_config()["hash"]
    S.OPCOES["gemini"]["formato_esquema"] = "responseFormat"
    try:
        assert S.snapshot_config()["hash"] != antes
    finally:
        S.OPCOES["gemini"]["formato_esquema"] = "responseSchema"


# ====================== interpretar ======================
def test_partes_de_raciocinio_ficam_de_fora_do_texto():
    texto, t_in, t_out = ClassificadorGemini.interpretar(_fix("gemini_generate_content_sintetico.json"))
    assert "Raciocinio interno" not in texto and texto.startswith('{"relevante": true')
    assert json.loads(texto)["achados"][0]["tecnologia"] == "reconhecimento_facial"


def test_tokens_de_raciocinio_contam_como_saida():
    _, t_in, t_out = ClassificadorGemini.interpretar(_fix("gemini_generate_content_sintetico.json"))
    assert (t_in, t_out) == (1200, 80 + 120)


def test_varias_partes_de_texto_sao_concatenadas():
    raw = json.dumps({"candidates": [{"content": {"parts": [{"text": "{\"a\":"}, {"text": " 1}"}]}}]})
    assert ClassificadorGemini.interpretar(raw) == ('{"a": 1}', None, 0)


def test_interpretar_sem_candidatos_levanta_keyerror():
    with pytest.raises(KeyError):
        ClassificadorGemini.interpretar(_fix("gemini_sem_candidatos_sintetico.json"))


# ====================== metadados ======================
def test_metadados_da_resposta_normal():
    m = ClassificadorGemini.metadados(_fix("gemini_generate_content_sintetico.json"))
    assert m["finish_reason"] == "STOP" and m["modelo_versao"] == "gemini-3.5-flash-lite-sintetico"
    assert m["response_id"] == "resp-sintetico-0001" and m["tokens_raciocinio"] == 120
    assert (m["sem_candidatos"], m["sem_conteudo"], m["bloqueio"]) == (False, False, None)


def test_metadados_de_prompt_bloqueado():
    m = ClassificadorGemini.metadados(_fix("gemini_sem_candidatos_sintetico.json"))
    assert (m["sem_candidatos"], m["bloqueio"], m["finish_reason"]) == (True, "SAFETY", None)


def test_metadados_de_candidato_sem_conteudo():
    m = ClassificadorGemini.metadados(_fix("gemini_sem_conteudo_sintetico.json"))
    assert (m["sem_candidatos"], m["sem_conteudo"], m["finish_reason"]) == (False, True, "SAFETY")


@pytest.mark.parametrize("raw", ["nao e json", "[1, 2]", "null", '{"candidates": 5}', '{"candidates": ["x"]}'])
def test_metadados_nunca_levantam(raw):
    ClassificadorGemini.metadados(raw)


# ====================== custo ======================
def test_custo_usa_tokens_de_entrada_e_de_saida_com_raciocinio():
    c = _gemini()._custo(1200, 200)
    assert c == pytest.approx((1200 * 0.3 + 200 * 2.5) / 1_000_000)


@pytest.mark.parametrize("pin, pout, t_in", [(None, 2.5, 100), (0.3, None, 100), (0.3, 2.5, None)])
def test_custo_indisponivel_sem_preco_ou_sem_tokens(pin, pout, t_in):
    assert _gemini(preco_entrada_por_m=pin, preco_saida_por_m=pout)._custo(t_in, 10) is None


# ====================== classificar ======================
def test_classificar_com_resposta_normal(monkeypatch):
    visto = _chamar(monkeypatch, _fix("gemini_generate_content_sintetico.json"))
    res = _gemini().classificar(_entrada(), _instr())
    assert res.relevante and res.json_valido and len(res.achados) == 1
    a = res.achados[0]
    assert (a.tecnologia, a.status, a.confianca, a.menciona_lgpd) == ("reconhecimento_facial", "em_uso", "alta", True)
    c = res.chamada
    assert c.sucesso and c.provedor == "gemini:gemini-3.5-flash-lite" and c.operacao == "classificar"
    assert (c.tokens_entrada, c.tokens_saida) == (1200, 200) and c.custo_usd == pytest.approx((1200 * 0.3 + 200 * 2.5) / 1e6)
    assert c.id_externo == "resp-sintetico-0001" and c.http_status == 200 and c.latencia_ms == 800
    assert c.extras["finish_reason"] == "STOP" and c.extras["modelo_versao"] == "gemini-3.5-flash-lite-sintetico"
    assert c.extras["tokens_raciocinio"] == 120 and c.extras["custo_origem"] == "calculado_por_tokens" and "latencia_total_ms" in c.extras
    assert c.raw == _fix("gemini_generate_content_sintetico.json").encode()
    assert visto["url"].endswith("/models/gemini-3.5-flash-lite:generateContent") and visto["metodo"] == "POST"


def test_a_chave_vai_no_cabecalho_e_nunca_na_url_nem_nos_parametros(monkeypatch):
    visto = _chamar(monkeypatch, _fix("gemini_generate_content_sintetico.json"))
    c = _gemini().classificar(_entrada(), _instr()).chamada
    assert visto["headers"]["x-goog-api-key"] == CHAVE and CHAVE not in visto["url"]
    assert CHAVE not in json.dumps(c.parametros) and CHAVE not in json.dumps(c.extras)
    assert "key" not in visto.get("params", {})


def test_parametros_registram_o_necessario_para_reproduzir(monkeypatch):
    _chamar(monkeypatch, _fix("gemini_generate_content_sintetico.json"))
    p = _gemini().classificar(_entrada(), _instr()).chamada.parametros
    assert (p["modelo"], p["temperatura"], p["max_tokens_saida"], p["formato_esquema"], p["prompt_versao"]) == \
        ("gemini-3.5-flash-lite", 0.0, 4096, "responseSchema", "v-teste")
    assert (p["uf"], p["url"], p["n_chars"]) == ("PI", "https://exemplo.gov.br/pi/1", len("texto enviado"))
    assert len(p["entrada_sha256"]) == 64 and len(p["sistema_sha256"]) == 64 and p["entrada_sha256"] != p["sistema_sha256"]


def test_sem_preco_configurado_o_custo_fica_vazio(monkeypatch):
    _chamar(monkeypatch, _fix("gemini_generate_content_sintetico.json"))
    c = _gemini(preco_entrada_por_m=None, preco_saida_por_m=None).classificar(_entrada(), _instr()).chamada
    assert c.custo_usd is None and "custo_origem" not in c.extras and c.tokens_entrada == 1200


def test_prompt_bloqueado_vira_erro_sem_candidatos(monkeypatch):
    _chamar(monkeypatch, _fix("gemini_sem_candidatos_sintetico.json"))
    res = _gemini().classificar(_entrada(), _instr())
    c = res.chamada
    assert c.erro == "sem_candidatos: SAFETY" and not c.sucesso
    assert (res.relevante, res.achados, res.json_valido, res.texto_resposta) == (False, [], False, "")
    assert c.extras["bloqueio"] == "SAFETY" and c.id_externo == "resp-sintetico-0002" and c.raw is not None and c.custo_usd is None


def test_resposta_sem_candidatos_e_sem_motivo(monkeypatch):
    _chamar(monkeypatch, "{}")
    assert _gemini().classificar(_entrada(), _instr()).chamada.erro == "sem_candidatos: sem_motivo"


def test_candidato_sem_conteudo_vira_erro_sem_conteudo(monkeypatch):
    _chamar(monkeypatch, _fix("gemini_sem_conteudo_sintetico.json"))
    c = _gemini().classificar(_entrada(), _instr()).chamada
    assert c.erro == "sem_conteudo: SAFETY" and c.extras["finish_reason"] == "SAFETY"


def test_resposta_truncada_por_max_tokens_fica_visivel_nos_extras(monkeypatch):
    _chamar(monkeypatch, _fix("gemini_max_tokens_sintetico.json"))
    res = _gemini().classificar(_entrada(), _instr())
    c = res.chamada
    assert c.sucesso and c.extras["finish_reason"] == "MAX_TOKENS" and c.extras["tokens_raciocinio"] == 4056
    assert not res.json_valido and res.achados == [] and res.texto_resposta.startswith('{"relevante": true')
    assert (c.tokens_entrada, c.tokens_saida) == (1200, 40 + 4056) and c.custo_usd > 0                   # a cobranca existe mesmo assim


def test_erro_http_nao_levanta_e_guarda_o_corpo(monkeypatch):
    _chamar(monkeypatch, '{"error": {"code": 400, "message": "schema invalido"}}', erro="HTTP 400: schema invalido", http_status=400)
    res = _gemini().classificar(_entrada(), _instr())
    c = res.chamada
    assert c.erro.startswith("HTTP 400") and c.http_status == 400 and not c.sucesso
    assert c.raw is not None and (res.relevante, res.achados, res.json_valido) == (False, [], False) and c.custo_usd is None


def test_falha_de_rede_sem_resposta(monkeypatch):
    _chamar(monkeypatch, None, erro="ConnectionError('x')", http_status=None)
    c = _gemini().classificar(_entrada(), _instr()).chamada
    assert not c.sucesso and c.raw is None and c.tentativas == 1


@pytest.mark.parametrize("texto", ["isto nao e json", '{"candidates": [{"content": {"parts": [1]}}]}'])
def test_resposta_fora_do_formato_vira_resposta_inesperada(monkeypatch, texto):
    _chamar(monkeypatch, texto)
    c = _gemini().classificar(_entrada(), _instr()).chamada
    assert c.erro and c.raw == texto.encode()


def test_texto_que_nao_e_o_json_esperado_gera_json_invalido_sem_erro(monkeypatch):
    raw = json.dumps({"candidates": [{"content": {"parts": [{"text": "Desculpe, nao consigo."}]}, "finishReason": "STOP"}],
                      "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5}})
    _chamar(monkeypatch, raw)
    res = _gemini().classificar(_entrada(), _instr())
    assert res.chamada.sucesso and not res.json_valido and res.texto_resposta == "Desculpe, nao consigo."


# ====================== composicao e estagio ======================
def test_fabrica_monta_o_classificador_com_a_chave_do_ambiente(monkeypatch):
    from composicao import Fabrica
    monkeypatch.setenv("GEMINI_API_KEY", CHAVE)
    c = Fabrica().classificador
    assert isinstance(c, ClassificadorGemini) and c.nome == "gemini:gemini-3.5-flash-lite"
    assert (c._pin, c._pout, c._max, c._formato) == (0.3, 2.5, 4096, "responseSchema")


def test_fabrica_sem_chave_nao_cria_o_classificador():
    from composicao import Fabrica
    with pytest.raises(SystemExit) as e:
        Fabrica().classificador
    assert "GEMINI_API_KEY" in str(e.value)


def test_estagio_de_classificacao_com_o_gemini_grava_achado_custo_e_extras(tmp_path, monkeypatch):
    logging.disable(logging.CRITICAL)
    try:
        trecho = "implantou reconhecimento facial nas câmeras da capital"
        raw = json.dumps({"candidates": [{"content": {"parts": [{"thought": True, "text": "..."}, {"text": json.dumps(
            {"relevante": True, "achados": [{"tecnologia": "reconhecimento_facial", "status": "em_uso", "fornecedor": "",
                                             "menciona_lgpd": True, "evidencia": trecho, "confianca": "alta"},
                                            {"tecnologia": "inventada", "status": "em_uso", "fornecedor": "", "menciona_lgpd": False,
                                             "evidencia": "x", "confianca": "alta"}]})}]}, "finishReason": "STOP"}],
                          "usageMetadata": {"promptTokenCount": 1000, "candidatesTokenCount": 100, "thoughtsTokenCount": 50},
                          "modelVersion": "gemini-3.5-flash-lite-001", "responseId": "r-1"})
        _chamar(monkeypatch, raw)
        repo, bruto = RepositorioSQLite(tmp_path / "g.db"), BrutoLocal(tmp_path / "raw")
        run_id = _novo_run(repo, "pipeline-uf")
        busca_web.executar(repo, bruto, BuscaSimulada(), run_id, _consulta_pi(), C.PERFIS_BUSCA_WEB, [], 0)
        download.executar(repo, bruto, FetcherSimulado(), ExtratorSimulado(), run_id, run_id, C.POLITICA_DOWNLOAD, [], 0, ufs={"PI"})
        classificacao.executar(repo, bruto, _gemini(), run_id, run_id, _params(), C.UFS, [CHAVE], 0, ufs={"PI"})
        assert repo.conn.execute("SELECT COUNT(*) FROM classificacoes WHERE json_valido=1").fetchone()[0] == 3
        a = repo.conn.execute("SELECT evidencia_confere, confianca, confianca_original FROM achados").fetchone()
        assert tuple(a) == (1, "alta", "alta")                                     # a evidencia literal existe no texto enviado
        assert repo.conn.execute("SELECT COUNT(*) FROM achados_descartados WHERE motivo='tecnologia_fora_do_vocabulario'").fetchone()[0] == 3
        v = dict(repo.conn.execute("SELECT * FROM v_custos WHERE etapa='classificacao'").fetchone())
        assert v["n_chamadas"] == 3 and v["tokens_entrada"] == 3000 and v["tokens_saida"] == 450
        assert v["custo_usd"] == pytest.approx(3 * (1000 * 0.3 + 150 * 2.5) / 1e6, abs=1e-4)
        c = repo.conn.execute("SELECT * FROM chamadas WHERE etapa='classificacao'").fetchone()
        assert c["id_externo"] == "r-1" and json.loads(c["extras_json"])["modelo_versao"] == "gemini-3.5-flash-lite-001"
        assert CHAVE not in c["parametros_json"] + c["extras_json"]
        q = dict(repo.conn.execute("SELECT * FROM v_qualidade_classificacao").fetchone())
        assert q["classificador"] == "gemini:gemini-3.5-flash-lite" and q["pct_json_valido"] == 100.0
    finally:
        logging.disable(logging.NOTSET)


_REAL = pathlib.Path(__file__).parent / "fixtures" / "gemini_generate_content.json"


@pytest.mark.skipif(not _REAL.exists(), reason="fixture real ainda nao existe (criada no M5, depois da primeira classificacao real)")
def test_gemini_interpreta_resposta_real():
    texto, t_in, t_out = ClassificadorGemini.interpretar(_REAL.read_text(encoding="utf-8"))
    assert texto and t_in and t_out
    assert ClassificadorGemini.metadados(_REAL.read_text(encoding="utf-8"))["modelo_versao"]
