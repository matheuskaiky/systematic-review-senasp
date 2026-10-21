"""Filtros de idioma e pais por perfil de busca web e os conjuntos de consultas da busca de literatura (D103, D104, D105).
Nenhum teste abre conexao: `chamar` e substituido."""
import json
import logging
import pathlib
import sys

import pytest

import config.settings as S
from adaptadores import busca_perplexity as modulo_perplexity, busca_serpapi_google as modulo_google
from adaptadores.bruto_local import BrutoLocal
from adaptadores.busca_perplexity import BuscaPerplexity
from adaptadores.busca_serpapi_google import BuscaSerpApiGoogle
from adaptadores.repositorio_sqlite import RepositorioSQLite
from adaptadores.simulados import BuscaSimulada
from aplicacao import busca_web
from config import consultas as C
from dominio.modelos import ConsultaWeb, FiltrosBusca, Termo
from dominio.servicos import chave_filtros_busca, gerar_consultas_web, hash_chave

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from dados_metricas import _novo_run  # noqa: E402

CONSULTA = ConsultaWeb("LA1", "inteligência artificial segurança pública", "pt", "", "", "LA1", "literatura")
MSG_IDIOMA = "FiltrosBusca: idiomas precisa ser uma tupla de códigos ISO 639-1 de duas letras minúsculas"
MSG_PAIS = "FiltrosBusca: pais precisa ser vazio ou um código ISO 3166-1 de duas letras maiúsculas"
MSG_GOOGLE = "SerpApi Google: language and country filters per profile are not supported"


class _Resp:
    def __init__(self, texto):
        self.text, self.content = texto, texto.encode()


def _chamar(modulo, monkeypatch, texto='{"id": "x", "results": []}'):
    visto = {}

    def falso(metodo, url, **kw):
        visto.update(metodo=metodo, url=url, **kw)
        return {"resp": _Resp(texto), "http_status": 200, "latencia_ms": 4, "tentativas": 1, "erro": None,
                "latencia_total_ms": 4, "historico": [], "corpo_erro": None}

    monkeypatch.setattr(modulo, "chamar", falso)
    return visto


# ---------- chave de idempotencia: perfis sem idioma e pais nao mudam ----------
@pytest.mark.parametrize("perfil, esperado", [
    ("oficial", '{"dominios_excluir": [], "dominios_incluir": [".gov.br"], "max_resultados": 10}'),
    ("geral", '{"dominios_excluir": ["reddit.com", "pinterest.com", "facebook.com", "instagram.com", "quora.com"], '
              '"dominios_incluir": [], "max_resultados": 10}'),
])
def test_chave_dos_perfis_atuais_e_a_mesma_de_antes(perfil, esperado):
    assert chave_filtros_busca(C.PERFIS_BUSCA_WEB[perfil]) == esperado


@pytest.mark.parametrize("filtros, esperado", [
    (FiltrosBusca(), '{"dominios_excluir": [], "dominios_incluir": [], "max_resultados": 10}'),
    (FiltrosBusca(idiomas=("pt",)), '{"dominios_excluir": [], "dominios_incluir": [], "idiomas": ["pt"], "max_resultados": 10}'),
    (FiltrosBusca(pais="BR"), '{"dominios_excluir": [], "dominios_incluir": [], "max_resultados": 10, "pais": "BR"}'),
    (FiltrosBusca(max_resultados=20, idiomas=("pt", "es"), pais="BR"),
     '{"dominios_excluir": [], "dominios_incluir": [], "idiomas": ["pt", "es"], "max_resultados": 20, "pais": "BR"}'),
])
def test_chave_dos_filtros_so_leva_idioma_e_pais_quando_preenchidos(filtros, esperado):
    assert chave_filtros_busca(filtros) == esperado


def test_idiomas_em_outra_ordem_dao_outra_chave():
    assert chave_filtros_busca(FiltrosBusca(idiomas=("pt", "es"))) != chave_filtros_busca(FiltrosBusca(idiomas=("es", "pt")))


def test_etapa_de_busca_web_grava_as_mesmas_chaves_de_antes(tmp_path):
    """Chaves gravadas pela etapa antes dos campos novos (calculadas no codigo anterior): a retomada de uma execucao
    antiga nao repete chamadas."""
    logging.disable(logging.CRITICAL)
    try:
        repo, bruto = RepositorioSQLite(tmp_path / "t.db"), BrutoLocal(tmp_path / "raw")
        run_id = _novo_run(repo, "busca-web")
        consultas = gerar_consultas_web(C.MODELOS_WEB[:2], {"reconhecimento_facial": "reconhecimento facial"},
                                        {"PI": C.UFS["PI"]})
        busca_web.executar(repo, bruto, BuscaSimulada(), run_id, consultas, C.PERFIS_BUSCA_WEB, [], 0)
    finally:
        logging.disable(logging.NOTSET)
    linhas = [tuple(r) for r in repo.conn.execute("SELECT alvo_id, chave_idempotencia FROM chamadas ORDER BY chamada_id")]
    assert linhas == [("M01-PI-reconhecimento_facial", "9fd8e8797e8fd20c45d2740587f333afed497592"),
                      ("M02-PI-reconhecimento_facial", "5a7dd497f2e5b5645a46765befd1025265e0f681")]


def test_chave_da_etapa_usa_o_texto_dos_filtros():
    assert hash_chave("busca_web", "perplexity_search", "M01_PI_x", chave_filtros_busca(C.PERFIS_BUSCA_WEB["oficial"])) \
        == "231cc8445e5e740b270f22ca2e2757a08e3b2098"


# ---------- Perplexity: corpo do pedido ----------
@pytest.mark.parametrize("filtros, extra, esperado", [
    (FiltrosBusca(), None, {"query": CONSULTA.texto, "max_results": 10}),
    (FiltrosBusca(idiomas=("pt",)), None, {"query": CONSULTA.texto, "max_results": 10, "search_language_filter": ["pt"]}),
    (FiltrosBusca(pais="BR"), None, {"query": CONSULTA.texto, "max_results": 10, "country": "BR"}),
    (FiltrosBusca(max_resultados=20, idiomas=("pt", "es"), pais="BR"), None,
     {"query": CONSULTA.texto, "max_results": 20, "search_language_filter": ["pt", "es"], "country": "BR"}),
    (FiltrosBusca(dominios_incluir=(".gov.br",), idiomas=("pt",), pais="BR"), None,
     {"query": CONSULTA.texto, "max_results": 10, "search_domain_filter": [".gov.br"],
      "search_language_filter": ["pt"], "country": "BR"}),
    # corpo_extra da configuracao continua valendo por cima do perfil (como antes)
    (FiltrosBusca(idiomas=("pt",), pais="BR"), {"country": "US", "search_type": "fast"},
     {"query": CONSULTA.texto, "max_results": 10, "search_language_filter": ["pt"], "country": "US", "search_type": "fast"}),
])
def test_corpo_do_perplexity_leva_idioma_e_pais_do_perfil(filtros, extra, esperado):
    corpo = BuscaPerplexity("k", corpo_extra=extra)._corpo(CONSULTA, filtros)
    assert corpo == esperado
    assert list(corpo)[:2] == ["query", "max_results"]


@pytest.mark.parametrize("kw, mensagem", [
    ({"idiomas": ("PT",)}, MSG_IDIOMA),
    ({"idiomas": ("pt ",)}, MSG_IDIOMA),
    ({"idiomas": (" pt",)}, MSG_IDIOMA),
    ({"idiomas": ("pt\n",)}, MSG_IDIOMA),
    ({"idiomas": ("",)}, MSG_IDIOMA),
    ({"idiomas": ("por",)}, MSG_IDIOMA),
    ({"idiomas": ("pt", "E")}, MSG_IDIOMA),
    ({"idiomas": ("pé",)}, MSG_IDIOMA),
    ({"idiomas": "pt"}, MSG_IDIOMA),                 # texto em vez de tupla
    ({"idiomas": ["pt"]}, MSG_IDIOMA),               # lista em vez de tupla
    ({"idiomas": None}, MSG_IDIOMA),
    ({"idiomas": 5}, MSG_IDIOMA),
    ({"idiomas": (None,)}, MSG_IDIOMA),
    ({"idiomas": (1,)}, MSG_IDIOMA),
    ({"idiomas": (b"pt",)}, MSG_IDIOMA),
    ({"pais": "br"}, MSG_PAIS),
    ({"pais": " BR"}, MSG_PAIS),
    ({"pais": "BR\n"}, MSG_PAIS),
    ({"pais": "BRA"}, MSG_PAIS),
    ({"pais": "B"}, MSG_PAIS),
    ({"pais": "ÉR"}, MSG_PAIS),
    ({"pais": " "}, MSG_PAIS),
    ({"pais": None}, MSG_PAIS),
    ({"pais": 1}, MSG_PAIS),
    ({"pais": b"BR"}, MSG_PAIS),
    ({"idiomas": ("PT",), "pais": "br"}, MSG_IDIOMA),   # o idioma e conferido antes do pais
])
def test_perfil_com_idioma_ou_pais_fora_do_formato_nao_e_criado(kw, mensagem):
    with pytest.raises(ValueError) as e:
        FiltrosBusca(**kw)
    assert str(e.value) == mensagem


def test_mistura_de_dominios_continua_recusada_pelo_perplexity():
    with pytest.raises(ValueError, match="do not mix allowlist and denylist"):
        BuscaPerplexity("k")._corpo(CONSULTA, FiltrosBusca(dominios_incluir=("a.br",), dominios_excluir=("b.br",),
                                                            idiomas=("pt",)))


def test_busca_do_perplexity_envia_e_registra_os_filtros(monkeypatch):
    visto = _chamar(modulo_perplexity, monkeypatch)
    resp = BuscaPerplexity("k").buscar(CONSULTA, C.FILTROS_LITERATURA_WEB)
    esperado = {"query": CONSULTA.texto, "max_results": 20, "search_language_filter": ["pt"], "country": "BR"}
    assert visto["json_body"] == esperado
    assert resp.chamada.parametros == esperado


# ---------- SerpApi Google: recusa em vez de ignorar ----------
@pytest.mark.parametrize("filtros", [FiltrosBusca(idiomas=("pt",)), FiltrosBusca(pais="BR"),
                                     FiltrosBusca(idiomas=("pt",), pais="BR")])
def test_serpapi_google_recusa_idioma_e_pais_por_perfil(filtros, monkeypatch):
    visto = _chamar(modulo_google, monkeypatch)
    with pytest.raises(ValueError) as e:
        BuscaSerpApiGoogle("k").buscar(CONSULTA, filtros)
    assert str(e.value) == MSG_GOOGLE
    assert visto == {}


def test_serpapi_google_sem_idioma_e_pais_continua_igual():
    p = BuscaSerpApiGoogle("k")._params(CONSULTA, FiltrosBusca(dominios_incluir=(".gov.br",)))
    assert p == {"engine": "google", "q": CONSULTA.texto + " (site:gov.br)", "num": 10, "hl": "pt", "gl": "br"}


# ---------- configuracao da frente ----------
def test_conjuntos_de_literatura_sao_as_consultas_aprovadas():
    assert {k: [(t.id, t.query, t.idioma, t.grupo, t.pai) for t in v] for k, v in C.CONJUNTOS_LITERATURA.items()} == {
        "A": [
            ("LA1", "inteligência artificial segurança pública viés algorítmico investigação criminal", "pt", "conjunto_A", ""),
            ("LA2", "inteligência artificial investigação criminal viés algorítmico", "pt", "conjunto_A", ""),
            ("LA3", "inteligência artificial segurança pública viés algorítmico", "pt", "conjunto_A", ""),
            ("LA4", "inteligência artificial segurança pública investigação criminal", "pt", "conjunto_A", ""),
            ("LA5", "viés algorítmico investigação criminal segurança pública", "pt", "conjunto_A", ""),
        ],
        "B": [
            ("LB1", "inteligência artificial segurança pública viés algorítmico discriminação ética", "pt", "conjunto_B", ""),
            ("LB2", "inteligência artificial segurança pública discriminação", "pt", "conjunto_B", ""),
            ("LB3", "inteligência artificial segurança pública ética", "pt", "conjunto_B", ""),
            ("LB4", "viés algorítmico discriminação segurança pública", "pt", "conjunto_B", ""),
            ("LB5", "inteligência artificial viés algorítmico ética", "pt", "conjunto_B", ""),
        ],
    }
    assert all(isinstance(t, Termo) for v in C.CONJUNTOS_LITERATURA.values() for t in v)
    assert all(isinstance(v, tuple) for v in C.CONJUNTOS_LITERATURA.values())


def test_ids_da_literatura_nao_repetem_os_termos_da_tarefa_2():
    ids = {t.id for v in C.CONJUNTOS_LITERATURA.values() for t in v}
    assert not ids & {t.id for t in C.TERMOS + C.TERMOS_COMPOSTOS}


def test_filtros_da_literatura():
    assert C.FILTROS_LITERATURA_WEB == FiltrosBusca(dominios_incluir=(), dominios_excluir=(), max_resultados=20,
                                                    idiomas=("pt",), pais="BR")


def test_perfis_da_tarefa_1_nao_ganham_idioma_nem_pais_nem_perfil_novo():
    assert set(C.PERFIS_BUSCA_WEB) == {"oficial", "geral"}
    assert all(f.idiomas == () and f.pais == "" for f in C.PERFIS_BUSCA_WEB.values())


def test_snapshot_da_configuracao_registra_os_conjuntos_e_os_filtros():
    d = json.loads(S.snapshot_config()["json"])
    assert [t["id"] for t in d["conjuntos_literatura"]["A"]] == ["LA1", "LA2", "LA3", "LA4", "LA5"]
    assert [t["id"] for t in d["conjuntos_literatura"]["B"]] == ["LB1", "LB2", "LB3", "LB4", "LB5"]
    assert d["filtros_literatura_web"] == {"dominios_incluir": [], "dominios_excluir": [], "max_resultados": 20,
                                           "idiomas": ["pt"], "pais": "BR"}
    assert len(d["termos"]) == len(C.TERMOS) + len(C.TERMOS_COMPOSTOS)      # v_termos da Tarefa 2 nao muda
