"""M7: adaptadores alternativos (busca web SerpApi Google e LLM compativel com chat completions) e a troca de provedor.
Nenhum teste abre conexao: `chamar` e substituido."""
import json
import logging
import pathlib
import re

import pytest

import config.settings as S
from adaptadores import REGISTROS, busca_serpapi_google as modulo_google, classificador_openai_compat as modulo_openai
from adaptadores.bruto_local import BrutoLocal
from adaptadores.busca_perplexity import BuscaPerplexity
from adaptadores.busca_serpapi_google import BuscaSerpApiGoogle
from adaptadores.classificador_gemini import ClassificadorGemini
from adaptadores.classificador_openai_compat import ClassificadorOpenAICompat
from adaptadores.repositorio_sqlite import RepositorioSQLite
from adaptadores.simulados import ExtratorSimulado, FetcherSimulado
from aplicacao import busca_web, classificacao, download
from composicao import Fabrica
from config import consultas as C, vocabulario as V
from dados_metricas import _consulta_pi, _novo_run, _params
from dominio.esquemas import esquema_classificacao
from dominio.modelos import ConsultaWeb, EntradaClassificacao, FiltrosBusca, Instrucoes
from dominio.servicos import gerar_consultas_web

SINT = pathlib.Path(__file__).parent / "fixtures" / "sintetico"
RAIZ = pathlib.Path(__file__).resolve().parent.parent
CHAVE = "CHAVE-FALSA-ABCDEF-123456"
ESQUEMA = esquema_classificacao(tuple(V.TECNOLOGIAS), tuple(V.STATUS), V.CONFIANCA)


def _fix(nome):
    return (SINT / nome).read_text(encoding="utf-8")


class _Resp:
    def __init__(self, texto):
        self.text, self.content = texto, texto.encode()


def _chamar(modulo, monkeypatch, texto=None, erro=None, http_status=200):
    visto = {}

    def falso(metodo, url, **kw):
        visto.update(metodo=metodo, url=url, **kw)
        return {"resp": _Resp(texto) if texto is not None else None, "http_status": http_status, "latencia_ms": 400,
                "tentativas": 1, "erro": erro, "latencia_total_ms": 400, "historico": [], "corpo_erro": None}

    monkeypatch.setattr(modulo, "chamar", falso)
    return visto


@pytest.fixture
def silencio():
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)


# ============================== SerpApi Google ==============================
def _consulta(idioma="pt"):
    return ConsultaWeb("M01-PI-x", "reconhecimento facial Piauí", idioma, "PI", "reconhecimento_facial", "M01", "oficial")


def test_params_com_allowlist_vira_operador_site():
    p = BuscaSerpApiGoogle(CHAVE)._params(_consulta(), FiltrosBusca(dominios_incluir=(".gov.br",), max_resultados=10))
    assert p == {"engine": "google", "q": "reconhecimento facial Piauí (site:gov.br)", "num": 10, "hl": "pt", "gl": "br"}


def test_params_com_varios_dominios_usa_or_e_com_denylist_usa_menos_site():
    p = BuscaSerpApiGoogle(CHAVE)._params(_consulta(), FiltrosBusca(dominios_incluir=(".gov.br", ".jus.br")))
    assert p["q"].endswith("(site:gov.br OR site:jus.br)")
    p = BuscaSerpApiGoogle(CHAVE)._params(_consulta(), FiltrosBusca(dominios_excluir=("reddit.com", "quora.com")))
    assert p["q"] == "reconhecimento facial Piauí -site:reddit.com -site:quora.com"


def test_params_aceita_allowlist_e_denylist_juntas_e_limita_num():
    p = BuscaSerpApiGoogle(CHAVE)._params(_consulta("en"), FiltrosBusca(dominios_incluir=(".gov.br",), dominios_excluir=("x.com",), max_resultados=500))
    assert p["q"].endswith("(site:gov.br) -site:x.com") and p["num"] == 100 and p["hl"] == "en"


def test_pais_e_configuravel():
    assert BuscaSerpApiGoogle(CHAVE, pais="pt")._params(_consulta(), FiltrosBusca())["gl"] == "pt"


def test_google_interpreta_fixture_sintetica():
    resultados, id_externo, erro = BuscaSerpApiGoogle.interpretar(_fix("serpapi_google_sintetico.json"))
    assert (id_externo, erro) == ("sintetico-google-0001", None)
    assert [r.url for r in resultados] == ["https://ssp.exemplo.gov.br/noticias/a", "https://licitacoes.exemplo.gov.br/edital/1",
                                           "https://exemplo.com.br/materia"]                      # o item sem link saiu
    assert [r.posicao for r in resultados] == [1, 2, 4]                                          # sem position: indice + 1
    assert resultados[0].data == "May 1, 2024" and resultados[1].data is None
    assert resultados[0].titulo.startswith("Reconhecimento facial") and resultados[0].snippet


@pytest.mark.parametrize("raw", ["{}", '{"organic_results": null}', '{"organic_results": []}'])
def test_google_respostas_vazias(raw):
    assert BuscaSerpApiGoogle.interpretar(raw) == ([], None, None)


def test_google_buscar_com_sucesso(monkeypatch):
    visto = _chamar(modulo_google, monkeypatch, _fix("serpapi_google_sintetico.json"))
    resp = BuscaSerpApiGoogle(CHAVE).buscar(_consulta(), FiltrosBusca(dominios_incluir=(".gov.br",)))
    c = resp.chamada
    assert len(resp.resultados) == 3 and c.sucesso and c.provedor == "serpapi_google" and c.operacao == "buscar"
    assert c.id_externo == "sintetico-google-0001" and c.http_status == 200 and "latencia_total_ms" in c.extras
    assert visto["params"] == {**c.parametros, "api_key": CHAVE} and visto["url"] == BuscaSerpApiGoogle.URL


def test_google_a_chave_nunca_vai_para_o_registro(monkeypatch):
    _chamar(modulo_google, monkeypatch, _fix("serpapi_google_sintetico.json"))
    c = BuscaSerpApiGoogle(CHAVE).buscar(_consulta(), FiltrosBusca()).chamada
    assert CHAVE not in json.dumps(c.parametros) and "api_key" not in c.parametros and CHAVE not in json.dumps(c.extras)


def test_google_200_sem_resultados_nao_e_erro(monkeypatch):
    _chamar(modulo_google, monkeypatch, _fix("serpapi_google_sem_resultados_sintetico.json"))
    resp = BuscaSerpApiGoogle(CHAVE).buscar(_consulta(), FiltrosBusca())
    assert resp.chamada.sucesso and resp.resultados == []


def test_google_outro_erro_da_api_e_registrado(monkeypatch):
    _chamar(modulo_google, monkeypatch, '{"error": "Your account has run out of searches."}')
    resp = BuscaSerpApiGoogle(CHAVE).buscar(_consulta(), FiltrosBusca())
    assert resp.chamada.erro == "Your account has run out of searches." and resp.resultados == []


def test_google_erro_http_e_falha_de_rede(monkeypatch):
    _chamar(modulo_google, monkeypatch, '{"error": "x"}', erro="HTTP 401: x", http_status=401)
    r = BuscaSerpApiGoogle(CHAVE).buscar(_consulta(), FiltrosBusca())
    assert r.chamada.erro.startswith("HTTP 401") and r.chamada.raw is not None
    _chamar(modulo_google, monkeypatch, None, erro="ConnectionError('x')", http_status=None)
    assert BuscaSerpApiGoogle(CHAVE).buscar(_consulta(), FiltrosBusca()).chamada.raw is None


@pytest.mark.parametrize("texto", ["isto nao e json", '{"organic_results": [5, "x"]}', '{"search_metadata": 3, "organic_results": [{"link": "u"}]}'])
def test_google_resposta_fora_do_formato(monkeypatch, texto):
    _chamar(modulo_google, monkeypatch, texto)
    c = BuscaSerpApiGoogle(CHAVE).buscar(_consulta(), FiltrosBusca()).chamada
    assert c.erro.startswith("resposta_inesperada") and c.raw == texto.encode()


# ============================== OpenAI compativel ==============================
def _instr(**kw):
    return Instrucoes("v-teste", "SISTEMA", "USUARIO", ESQUEMA)


def _entrada():
    return EntradaClassificacao("PI", "https://exemplo.gov.br/pi/1", "Titulo", "texto enviado", "pagina", False)


def _openai(**kw):
    kw.setdefault("url", "https://api.exemplo.test/v1/chat/completions")
    kw.setdefault("modelo", "modelo-x")
    return ClassificadorOpenAICompat(CHAVE, **kw)


def test_corpo_padrao_usa_max_tokens_e_temperatura():
    c = _openai(temperatura=0.0, max_tokens=4096)._corpo(_instr())
    assert (c["model"], c["temperature"], c["max_tokens"]) == ("modelo-x", 0.0, 4096) and "max_completion_tokens" not in c
    assert [m["role"] for m in c["messages"]] == ["system", "user"] and c["messages"][1]["content"] == "USUARIO"
    assert "response_format" not in c


def test_c14_campo_max_completion_tokens():
    c = _openai(campo_max_tokens="max_completion_tokens", max_tokens=2048)._corpo(_instr())
    assert c["max_completion_tokens"] == 2048 and "max_tokens" not in c


def test_c14_temperatura_none_omite_o_campo():
    c = _openai(temperatura=None)._corpo(_instr())
    assert "temperature" not in c and "max_tokens" in c


def test_c14_as_duas_variantes_juntas():
    c = _openai(temperatura=None, campo_max_tokens="max_completion_tokens")._corpo(_instr())
    assert "temperature" not in c and "max_tokens" not in c and c["max_completion_tokens"] == 4096


def test_sem_response_format_o_esquema_vai_no_prompt_de_sistema():
    c = _openai(usar_response_format=False)._corpo(_instr())
    sistema = c["messages"][0]["content"]
    assert sistema.startswith("SISTEMA") and "Respond ONLY with valid JSON" in sistema and json.dumps(ESQUEMA, ensure_ascii=False) in sistema


def test_com_response_format_o_esquema_vai_no_campo_proprio():
    c = _openai(usar_response_format=True)._corpo(_instr())
    assert c["response_format"] == {"type": "json_schema", "json_schema": {"name": "classificacao", "schema": ESQUEMA}}
    assert c["messages"][0]["content"] == "SISTEMA"


def test_openai_interpretar_fixture_sintetica():
    texto, t_in, t_out, custo, id_externo = ClassificadorOpenAICompat.interpretar(_fix("openai_compat_sintetico.json"))
    assert json.loads(texto)["achados"][0]["tecnologia"] == "reconhecimento_facial"
    assert (t_in, t_out, custo, id_externo) == (1000, 100, None, "chatcmpl-sintetico-0001")


def test_openai_interpretar_custo_informado_pelo_provedor_inclusive_em_dicionario():
    base = {"choices": [{"message": {"content": "{}"}}], "id": "x"}
    assert ClassificadorOpenAICompat.interpretar(json.dumps({**base, "usage": {"cost": 0.0012}}))[3] == 0.0012
    assert ClassificadorOpenAICompat.interpretar(json.dumps({**base, "usage": {"cost": {"total_cost": 0.003}}}))[3] == 0.003


def test_openai_metadados():
    m = ClassificadorOpenAICompat.metadados(_fix("openai_compat_sintetico.json"))
    assert (m["finish_reason"], m["modelo_versao"], m["response_id"], m["sem_escolhas"]) == ("stop", "modelo-sintetico-2026-01-01", "chatcmpl-sintetico-0001", False)
    assert ClassificadorOpenAICompat.metadados(_fix("openai_compat_sem_escolhas_sintetico.json"))["sem_escolhas"] is True
    for raw in ("nao e json", "[1]", "null", '{"choices": 5}', '{"choices": ["x"]}'):
        ClassificadorOpenAICompat.metadados(raw)                                                 # nunca levanta


def test_openai_classificar_com_resposta_normal(monkeypatch):
    visto = _chamar(modulo_openai, monkeypatch, _fix("openai_compat_sintetico.json"))
    res = _openai(preco_entrada_por_m=0.5, preco_saida_por_m=1.5).classificar(_entrada(), _instr())
    c = res.chamada
    assert res.relevante and res.json_valido and len(res.achados) == 1 and c.sucesso
    assert c.provedor == "openai_compat:modelo-x" and (c.tokens_entrada, c.tokens_saida) == (1000, 100)
    assert c.custo_usd == pytest.approx((1000 * 0.5 + 100 * 1.5) / 1e6) and c.extras["custo_origem"] == "calculado_por_tokens"
    assert c.id_externo == "chatcmpl-sintetico-0001" and c.extras["finish_reason"] == "stop" and c.extras["modelo_versao"] == "modelo-sintetico-2026-01-01"
    assert visto["headers"]["Authorization"] == f"Bearer {CHAVE}" and visto["url"] == "https://api.exemplo.test/v1/chat/completions"


def test_openai_a_chave_nunca_vai_para_o_registro(monkeypatch):
    _chamar(modulo_openai, monkeypatch, _fix("openai_compat_sintetico.json"))
    c = _openai().classificar(_entrada(), _instr()).chamada
    assert CHAVE not in json.dumps(c.parametros) and CHAVE not in json.dumps(c.extras)
    assert c.parametros["max_tokens"] == 4096 and c.parametros["usar_response_format"] is False and len(c.parametros["sistema_sha256"]) == 64


def test_openai_o_nome_do_campo_do_limite_fica_nos_parametros(monkeypatch):
    _chamar(modulo_openai, monkeypatch, _fix("openai_compat_sintetico.json"))
    p = _openai(campo_max_tokens="max_completion_tokens", max_tokens=1024).classificar(_entrada(), _instr()).chamada.parametros
    assert p["max_completion_tokens"] == 1024 and "max_tokens" not in p


def test_openai_custo_do_provedor_tem_prioridade_sobre_o_calculo(monkeypatch):
    raw = json.dumps({"id": "x", "model": "m", "choices": [{"finish_reason": "stop", "message": {"content": '{"relevante": false, "achados": []}'}}],
                      "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.0042}})
    _chamar(modulo_openai, monkeypatch, raw)
    c = _openai(preco_entrada_por_m=100, preco_saida_por_m=100).classificar(_entrada(), _instr()).chamada
    assert c.custo_usd == 0.0042 and c.extras["custo_origem"] == "informado_pelo_provedor"


def test_openai_sem_preco_nem_custo_informado_deixa_o_custo_vazio(monkeypatch):
    _chamar(modulo_openai, monkeypatch, _fix("openai_compat_sintetico.json"))
    c = _openai().classificar(_entrada(), _instr()).chamada
    assert c.custo_usd is None and "custo_origem" not in c.extras and c.tokens_entrada == 1000


def test_openai_resposta_cortada_por_length_e_falha_com_tokens_e_custo(monkeypatch):
    _chamar(modulo_openai, monkeypatch, _fix("openai_compat_truncado_sintetico.json"))
    res = _openai(preco_entrada_por_m=1, preco_saida_por_m=2).classificar(_entrada(), _instr())
    c = res.chamada
    assert c.erro == "resposta_truncada: length" and not c.sucesso and c.extras["finish_reason"] == "length"
    assert (c.tokens_entrada, c.tokens_saida) == (1000, 4096) and c.custo_usd == pytest.approx((1000 + 4096 * 2) / 1e6)
    assert res.achados == [] and not res.json_valido and res.texto_resposta.startswith('{"relevante": true')


def test_openai_resposta_sem_escolhas_grava_os_tokens(monkeypatch):
    _chamar(modulo_openai, monkeypatch, _fix("openai_compat_sem_escolhas_sintetico.json"))
    c = _openai(preco_entrada_por_m=1, preco_saida_por_m=2).classificar(_entrada(), _instr()).chamada
    assert c.erro == "sem_escolhas: resposta sem choices" and (c.tokens_entrada, c.tokens_saida) == (1000, 0) and c.custo_usd == pytest.approx(0.001)


def test_openai_erro_http_e_falha_de_rede(monkeypatch):
    _chamar(modulo_openai, monkeypatch, '{"error": {"message": "max_tokens nao suportado"}}', erro="HTTP 400: max_tokens nao suportado", http_status=400)
    res = _openai().classificar(_entrada(), _instr())
    assert res.chamada.erro.startswith("HTTP 400") and res.chamada.raw is not None and res.achados == []
    _chamar(modulo_openai, monkeypatch, None, erro="ConnectionError('x')", http_status=None)
    assert _openai().classificar(_entrada(), _instr()).chamada.raw is None


@pytest.mark.parametrize("texto", ["isto nao e json", '{"choices": [{"message": 5}]}', '{"choices": [{"finish_reason": "stop"}]}'])
def test_openai_resposta_fora_do_formato(monkeypatch, texto):
    _chamar(modulo_openai, monkeypatch, texto)
    assert _openai().classificar(_entrada(), _instr()).chamada.erro.startswith("resposta_inesperada")


def test_openai_texto_que_nao_e_json_gera_json_invalido_sem_erro(monkeypatch):
    raw = json.dumps({"id": "x", "choices": [{"finish_reason": "stop", "message": {"content": "Nao consigo."}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}})
    _chamar(modulo_openai, monkeypatch, raw)
    res = _openai().classificar(_entrada(), _instr())
    assert res.chamada.sucesso and not res.json_valido and res.texto_resposta == "Nao consigo."


# ============================== troca de provedor (prova offline) ==============================
def test_registro_de_adaptadores_e_o_da_especificacao():
    assert {porta: set(nomes) for porta, nomes in REGISTROS.items()} == {
        "busca_web": {"perplexity_search", "serpapi_google"}, "academico": {"serpapi_scholar"}, "fetcher": {"requests"},
        "extrator": {"padrao"}, "classificador": {"gemini", "openai_compat"}, "triador": {"gemini"},
        "armazenamento": {"sqlite"},
        "bruto": {"local"}, "exportador": {"excel"}}


def test_trocar_so_a_configuracao_monta_o_adaptador_de_busca_alternativo(monkeypatch):
    monkeypatch.setenv("PERPLEXITY_API_KEY", CHAVE)
    monkeypatch.setenv("SERPAPI_KEY", CHAVE + "2")
    assert isinstance(Fabrica().busca_web, BuscaPerplexity)
    monkeypatch.setitem(S.PROVEDORES, "busca_web", "serpapi_google")
    b = Fabrica().busca_web
    assert isinstance(b, BuscaSerpApiGoogle) and b.nome == "serpapi_google" and b._pais == "br"            # opcoes de OPCOES["serpapi_google"]


def test_trocar_so_a_configuracao_monta_o_classificador_alternativo(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", CHAVE)
    monkeypatch.setenv("LLM_API_KEY", CHAVE + "2")
    assert isinstance(Fabrica().classificador, ClassificadorGemini)
    monkeypatch.setitem(S.PROVEDORES, "classificador", "openai_compat")
    monkeypatch.setitem(S.OPCOES["openai_compat"], "modelo", "modelo-do-pesquisador")
    c = Fabrica().classificador
    assert isinstance(c, ClassificadorOpenAICompat) and c.nome == "openai_compat:modelo-do-pesquisador"
    assert (c._campo_max, c._temp, c._max) == ("max_tokens", 0.0, 4096)


def test_a_troca_exige_a_chave_do_novo_provedor(monkeypatch):
    monkeypatch.setitem(S.PROVEDORES, "busca_web", "serpapi_google")
    with pytest.raises(SystemExit) as e:
        Fabrica().busca_web
    assert "SERPAPI_KEY" in str(e.value)
    monkeypatch.setitem(S.PROVEDORES, "classificador", "openai_compat")
    with pytest.raises(SystemExit) as e:
        Fabrica().classificador
    assert "LLM_API_KEY" in str(e.value)


def test_trocar_o_provedor_muda_o_hash_da_configuracao(monkeypatch):
    antes = S.snapshot_config()["hash"]
    monkeypatch.setitem(S.PROVEDORES, "busca_web", "serpapi_google")
    assert S.snapshot_config()["hash"] != antes                       # --retomar nao mistura provedores


def test_estagio_de_busca_roda_igual_com_o_adaptador_trocado(tmp_path, monkeypatch, silencio):
    monkeypatch.setenv("SERPAPI_KEY", CHAVE)
    monkeypatch.setitem(S.PROVEDORES, "busca_web", "serpapi_google")
    _chamar(modulo_google, monkeypatch, _fix("serpapi_google_sintetico.json"))
    repo, bruto = RepositorioSQLite(tmp_path / "t.db"), BrutoLocal(tmp_path / "raw")
    run_id = _novo_run(repo, "busca-web")
    consultas = gerar_consultas_web(C.MODELOS_WEB[:2], {"reconhecimento_facial": "reconhecimento facial"}, {"PI": C.UFS["PI"]})
    assert len(consultas) == 2
    busca_web.executar(repo, bruto, Fabrica().busca_web, run_id, consultas, C.PERFIS_BUSCA_WEB, [CHAVE], 0)
    assert repo.conn.execute("SELECT DISTINCT provedor FROM chamadas").fetchall()[0][0] == "serpapi_google"
    assert repo.conn.execute("SELECT COUNT(*) FROM resultados_web").fetchone()[0] == 6               # 2 consultas x 3 resultados
    assert repo.conn.execute("SELECT COUNT(*) FROM urls").fetchone()[0] == 3
    assert repo.conn.execute("SELECT n_retornados FROM chamadas").fetchone()[0] == 3
    assert CHAVE not in repo.conn.execute("SELECT parametros_json || extras_json FROM chamadas").fetchone()[0]


def test_estagio_de_classificacao_roda_igual_com_o_classificador_trocado(tmp_path, monkeypatch, silencio):
    monkeypatch.setenv("LLM_API_KEY", CHAVE)
    monkeypatch.setitem(S.PROVEDORES, "classificador", "openai_compat")
    monkeypatch.setitem(S.OPCOES["openai_compat"], "modelo", "modelo-x")
    _chamar(modulo_openai, monkeypatch, _fix("openai_compat_sintetico.json"))
    from adaptadores.simulados import BuscaSimulada
    repo, bruto = RepositorioSQLite(tmp_path / "t.db"), BrutoLocal(tmp_path / "raw")
    run_id = _novo_run(repo, "pipeline-uf")
    busca_web.executar(repo, bruto, BuscaSimulada(), run_id, _consulta_pi(), C.PERFIS_BUSCA_WEB, [], 0)
    download.executar(repo, bruto, FetcherSimulado(), ExtratorSimulado(), run_id, run_id, C.POLITICA_DOWNLOAD, [], 0, ufs={"PI"})
    classificacao.executar(repo, bruto, Fabrica().classificador, run_id, run_id, _params(), C.UFS, [CHAVE], 0, ufs={"PI"})
    k = repo.conn.execute("SELECT DISTINCT classificador FROM classificacoes").fetchall()
    assert [x[0] for x in k] == ["openai_compat:modelo-x"] and repo.conn.execute("SELECT COUNT(*) FROM achados").fetchone()[0] == 3
    assert repo.conn.execute("SELECT SUM(evidencia_confere) FROM achados").fetchone()[0] == 3        # a checagem da evidencia nao muda


def test_nenhum_nome_de_provedor_aparece_no_codigo_fora_de_config_e_adaptadores():
    """Trocar de provedor so mexe em config/settings.py: o codigo das etapas, do dominio e da composicao nao cita provedores."""
    nomes = re.compile(r"perplexity|serpapi|gemini|openai", re.I)
    achados = []
    for pasta in ("dominio", "aplicacao", "infra"):
        for p in (RAIZ / pasta).rglob("*.py"):
            achados += [(str(p), l) for l in p.read_text(encoding="utf-8").splitlines() if nomes.search(re.sub(r"#.*$", "", l))]
    for p in (RAIZ / "main.py", RAIZ / "composicao.py"):
        achados += [(str(p), l) for l in p.read_text(encoding="utf-8").splitlines() if nomes.search(re.sub(r"#.*$", "", l))]
    assert not achados, achados
