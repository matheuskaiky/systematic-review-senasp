import json
import pathlib

import pytest

from adaptadores import busca_perplexity
from adaptadores.busca_perplexity import BuscaPerplexity
from dominio.modelos import ConsultaWeb, FiltrosBusca

FIX = pathlib.Path(__file__).parent / "fixtures"
SINT = FIX / "sintetico"

_PERPLEXITY_REAL = FIX / "perplexity_search.json"


# ---------- Perplexity Search ----------
@pytest.mark.skipif(not _PERPLEXITY_REAL.exists(),
                    reason="fixture real ainda nao existe (criada no M3, depois da primeira busca real)")
def test_busca_perplexity_interpreta_bruto_real():
    resultados, _ = BuscaPerplexity.interpretar(_PERPLEXITY_REAL.read_text(encoding="utf-8"))
    assert resultados and all(r.url and r.posicao >= 1 for r in resultados)


@pytest.mark.skipif(not _PERPLEXITY_REAL.exists(), reason="fixture real ainda nao existe")
def test_busca_perplexity_fixture_real_traz_todos_os_campos():
    """Resposta real de 14/10/2026 (consulta M01-PI-reconhecimento_facial): o formato que o adaptador assume."""
    resultados, id_externo = BuscaPerplexity.interpretar(_PERPLEXITY_REAL.read_text(encoding="utf-8"))
    assert id_externo and len(resultados) == 10
    assert [r.posicao for r in resultados] == list(range(1, 11))
    assert all(r.titulo and r.snippet and r.data for r in resultados)
    assert all(".gov.br" in r.url for r in resultados)                     # perfil oficial: allowlist .gov.br aceita pela API
    assert set(json.loads(_PERPLEXITY_REAL.read_text(encoding="utf-8"))) == {"id", "results"}


def test_busca_perplexity_interpreta_fixture_sintetica():
    resultados, id_externo = BuscaPerplexity.interpretar(
        (SINT / "perplexity_search_sintetico.json").read_text(encoding="utf-8"))
    assert id_externo == "sintetico-0001"
    assert [r.url for r in resultados] == [
        "https://ssp.exemplo.gov.br/noticias/reconhecimento-facial",
        "https://licitacoes.exemplo.gov.br/edital/123",
        "https://exemplo.com.br/materia"]                       # o item sem url foi ignorado
    assert [r.posicao for r in resultados] == [1, 2, 4]          # posicao segue a ordem original
    assert resultados[0].data == "2024-05-01"                    # "date" tem prioridade
    assert resultados[1].data == "2024-03-15"                    # senao "last_updated"
    assert resultados[2].data is None
    assert resultados[0].titulo.startswith("Reconhecimento facial") and resultados[0].snippet


def test_busca_perplexity_interpreta_formato_em_lote():
    resultados, id_externo = BuscaPerplexity.interpretar(
        (SINT / "perplexity_search_lote_sintetico.json").read_text(encoding="utf-8"))
    assert id_externo == "sintetico-0002"
    assert [(r.url, r.posicao) for r in resultados] == [("https://exemplo.gov.br/a", 1), ("https://exemplo.gov.br/b", 2)]


def test_busca_perplexity_resposta_vazia():
    assert BuscaPerplexity.interpretar('{"id": "x", "results": []}') == ([], "x")
    assert BuscaPerplexity.interpretar("{}") == ([], None)


def _consulta():
    return ConsultaWeb("M01-PI-reconhecimento_facial", "reconhecimento facial Piauí", "pt", "PI",
                       "reconhecimento_facial", "M01", "oficial")


def test_busca_perplexity_corpo_com_allowlist():
    corpo = BuscaPerplexity("k")._corpo(_consulta(), FiltrosBusca(dominios_incluir=(".gov.br",), max_resultados=7))
    assert corpo == {"query": "reconhecimento facial Piauí", "max_results": 7, "search_domain_filter": [".gov.br"]}


def test_busca_perplexity_corpo_com_denylist_usa_prefixo_menos():
    corpo = BuscaPerplexity("k")._corpo(_consulta(), FiltrosBusca(dominios_excluir=("reddit.com", "quora.com")))
    assert corpo["search_domain_filter"] == ["-reddit.com", "-quora.com"]


def test_busca_perplexity_corpo_sem_filtro_nao_envia_search_domain_filter():
    assert "search_domain_filter" not in BuscaPerplexity("k")._corpo(_consulta(), FiltrosBusca())


def test_busca_perplexity_nao_mistura_allowlist_e_denylist():
    with pytest.raises(ValueError):
        BuscaPerplexity("k")._corpo(_consulta(), FiltrosBusca(dominios_incluir=(".gov.br",), dominios_excluir=("a.com",)))


def test_busca_perplexity_corpo_extra_e_repassado():
    corpo = BuscaPerplexity("k", corpo_extra={"country": "BR"})._corpo(_consulta(), FiltrosBusca())
    assert corpo["country"] == "BR"


class _Resp:
    def __init__(self, texto):
        self.text, self.content = texto, texto.encode()


def _chamar_falso(monkeypatch, *, resp=None, erro=None, http_status=200):
    visto = {}

    def falso(metodo, url, **kw):
        visto.update(metodo=metodo, url=url, **kw)
        return {"resp": resp, "http_status": http_status, "latencia_ms": 12, "tentativas": 1, "erro": erro}

    monkeypatch.setattr(busca_perplexity, "chamar", falso)
    return visto


def test_buscar_sucesso_preenche_o_registro(monkeypatch):
    texto = (SINT / "perplexity_search_sintetico.json").read_text(encoding="utf-8")
    visto = _chamar_falso(monkeypatch, resp=_Resp(texto))
    resp = BuscaPerplexity("SEGREDO-FALSO").buscar(_consulta(), FiltrosBusca(dominios_incluir=(".gov.br",)))
    assert len(resp.resultados) == 3
    c = resp.chamada
    assert c.sucesso and c.provedor == "perplexity_search" and c.operacao == "buscar"
    assert c.id_externo == "sintetico-0001" and c.http_status == 200 and c.latencia_ms == 12
    assert c.raw == texto.encode() and c.raw_ext == "json"
    assert (visto["metodo"], visto["url"]) == ("POST", BuscaPerplexity.URL)
    assert visto["headers"]["Authorization"] == "Bearer SEGREDO-FALSO"


def test_buscar_nunca_guarda_a_chave_nos_parametros_do_registro(monkeypatch):
    _chamar_falso(monkeypatch, resp=_Resp('{"results": []}'))
    c = BuscaPerplexity("SEGREDO-FALSO").buscar(_consulta(), FiltrosBusca()).chamada
    assert "SEGREDO-FALSO" not in json.dumps(c.parametros)


def test_buscar_erro_http_nao_levanta_e_devolve_lista_vazia(monkeypatch):
    _chamar_falso(monkeypatch, resp=_Resp("erro"), erro="HTTP 401: nao autorizado", http_status=401)
    resp = BuscaPerplexity("k").buscar(_consulta(), FiltrosBusca())
    assert resp.resultados == [] and not resp.chamada.sucesso
    assert resp.chamada.erro.startswith("HTTP 401") and resp.chamada.raw == b"erro"


def test_buscar_erro_de_rede_sem_resposta(monkeypatch):
    _chamar_falso(monkeypatch, resp=None, erro="ConnectionError()", http_status=None)
    resp = BuscaPerplexity("k").buscar(_consulta(), FiltrosBusca())
    assert resp.resultados == [] and resp.chamada.raw is None and not resp.chamada.sucesso


@pytest.mark.parametrize("texto", ["isto nao e json", '{"results": [{"url": 1, "title": "x"}, 5]}'])
def test_buscar_resposta_inesperada_vira_erro_registrado(monkeypatch, texto):
    _chamar_falso(monkeypatch, resp=_Resp(texto))
    resp = BuscaPerplexity("k").buscar(_consulta(), FiltrosBusca())
    assert resp.resultados == []
    assert resp.chamada.erro.startswith("resposta_inesperada")
    assert resp.chamada.raw == texto.encode()


def test_buscar_grava_o_custo_por_requisicao_quando_o_preco_esta_configurado(monkeypatch):
    _chamar_falso(monkeypatch, resp=_Resp('{"results": []}'))
    c = BuscaPerplexity("k", preco_por_requisicao_usd=0.005).buscar(_consulta(), FiltrosBusca()).chamada
    assert c.custo_usd == 0.005


def test_buscar_sem_preco_configurado_deixa_o_custo_vazio(monkeypatch):
    _chamar_falso(monkeypatch, resp=_Resp('{"results": []}'))
    assert BuscaPerplexity("k").buscar(_consulta(), FiltrosBusca()).chamada.custo_usd is None


def test_buscar_com_erro_http_nao_grava_custo(monkeypatch):
    _chamar_falso(monkeypatch, resp=_Resp("erro"), erro="HTTP 500: x", http_status=500)
    assert BuscaPerplexity("k", preco_por_requisicao_usd=0.005).buscar(_consulta(), FiltrosBusca()).chamada.custo_usd is None


def test_preco_da_configuracao_chega_ao_adaptador_da_busca_web():
    import config.settings as S
    assert S.OPCOES["perplexity_search"]["preco_por_requisicao_usd"] == S.PRECO_BUSCA_WEB_USD
    assert BuscaPerplexity("k", **S.OPCOES["perplexity_search"])._preco == S.PRECO_BUSCA_WEB_USD
