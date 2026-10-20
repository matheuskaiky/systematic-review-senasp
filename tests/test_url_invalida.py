"""Link malformado nao derruba a coleta: a busca web descarta o que nao e URL http(s) baixavel (e conta nos extras da
chamada), e o download recusa a URL inicial invalida sem rede e para num redirecionamento para destino invalido."""
import json
import logging

import pytest

from adaptadores.bruto_local import BrutoLocal
from adaptadores.fetcher_requests import FetcherRequests
from adaptadores.repositorio_sqlite import RepositorioSQLite
from adaptadores.simulados import BuscaSimulada
from aplicacao import busca_web
from config import consultas as C
from dados_metricas import _consulta_pi, _novo_run
from dominio.modelos import RespostaBusca, ResultadoWeb
from dominio import servicos
from test_robustez_coleta import A, UA, Rede, Resp, _redir, robots  # noqa: F401


@pytest.mark.parametrize("url,valida", [
    ("https://a.gov.br/x", True),
    ("http://a.gov.br", True),
    ("HTTPS://A.GOV.BR/x", True),
    ("https://www.a.gov.br/", True),
    ("https://segurança.gov.br/x", True),
    ("  https://a.gov.br/x  ", False),
    ("https://a.gov.br/x ", False),
    ("https://a\u00a0b.gov.br/x", False),
    ("https://a.gov.br/x\u00a0", False),
    ("https://www./x", False),
    ("https://WWW./x", False),
    ("https://a.gov.br:8080/x", True),
    ("https://[::1]/x", True),
    ("https://a.gov.br/x?q=1&r=%20", True),
    (None, False),
    (5, False),
    (b"https://a.gov.br/x", False),
    ("", False),
    ("   ", False),
    ("http://[bad/", False),
    ("http://[::1", False),
    ("https://a.gov.br:99999/x", False),
    ("https://a.gov.br:abc/", False),
    ("https://a b.gov.br/x", False),
    ("https://a.gov.br/x y", False),
    ("https://a.gov.br/x\ty", False),
    ("https://a.gov.br/\x00", False),
    ("https://a.gov.br/\x7f", False),
    ("javascript:alert(1)", False),
    ("ftp://x.gov.br/a", False),
    ("mailto:a@b.gov.br", False),
    ("//a.gov.br/x", False),
    ("a.gov.br/x", False),
    ("https://", False),
    ("https:///x", False),
    ("https://:80/", False),
])
def test_url_valida(url, valida):
    assert servicos.url_valida(url) is valida


# ====================== busca web ======================
class BuscaComLinksRuins(BuscaSimulada):
    LINKS = ["https://pi.gov.br/1", "http://[bad/", "https://pi.gov.br/2", "javascript:void(0)", "  "]

    def buscar(self, consulta, filtros):
        res = [ResultadoWeb(u, f"Reconhecimento facial {i}", "câmeras com reconhecimento facial", None, i)
               for i, u in enumerate(self.LINKS, 1)]
        return RespostaBusca(res, super().buscar(consulta, filtros).chamada)


class BuscaSoComLinksBons(BuscaSimulada):
    def buscar(self, consulta, filtros):
        res = [ResultadoWeb("https://pi.gov.br/1", "Reconhecimento facial", "câmeras", None, 1)]
        return RespostaBusca(res, super().buscar(consulta, filtros).chamada)


def _rodar_busca(tmp_path, busca):
    repo = RepositorioSQLite(tmp_path / "b.db")
    bruto = BrutoLocal(tmp_path / "raw")
    run_id = _novo_run(repo, "buscar-web")
    busca_web.executar(repo, bruto, busca, run_id, _consulta_pi(), C.PERFIS_BUSCA_WEB, [], 0)
    return repo, bruto, run_id


def test_busca_descarta_links_invalidos_e_conta_nos_extras(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        repo, _, run_id = _rodar_busca(tmp_path, BuscaComLinksRuins())
    urls = [r[0] for r in repo.conn.execute("SELECT u.url_original FROM resultados_web w JOIN urls u USING (url_id) "
                                            "ORDER BY w.posicao")]
    assert urls == ["https://pi.gov.br/1", "https://pi.gov.br/2"]
    sucesso, n_ret, n_novos, extras = repo.conn.execute(
        "SELECT sucesso, n_retornados, n_novos, extras_json FROM chamadas WHERE run_id=? AND etapa='busca_web'", (run_id,)).fetchone()
    assert (sucesso, n_ret, n_novos) == (1, 5, 2)
    assert json.loads(extras)["urls_invalidas"] == 3
    assert "link invalido descartado: 'http://[bad/'" in caplog.text
    assert "link invalido descartado: 'javascript:void(0)'" in caplog.text
    assert "link invalido descartado: '  '" in caplog.text


def test_busca_sem_link_invalido_nao_grava_a_contagem(tmp_path):
    repo, _, run_id = _rodar_busca(tmp_path, BuscaSoComLinksBons())
    extras = repo.conn.execute("SELECT extras_json FROM chamadas WHERE run_id=? AND etapa='busca_web'", (run_id,)).fetchone()[0]
    assert "urls_invalidas" not in json.loads(extras or "{}")


def test_retomar_a_busca_com_links_invalidos_nao_muda_nada(tmp_path):
    repo, bruto, run_id = _rodar_busca(tmp_path, BuscaComLinksRuins())
    antes = list(repo.conn.iterdump())
    busca_web.executar(repo, bruto, BuscaComLinksRuins(), run_id, _consulta_pi(), C.PERFIS_BUSCA_WEB, [], 0)
    assert list(repo.conn.iterdump()) == antes


# ====================== download ======================
@pytest.mark.parametrize("url", ["http://[bad/", "javascript:alert(1)", "ftp://a.gov.br/x", "", "https://a.gov.br/x y"])
def test_url_inicial_invalida_nao_faz_pedido_nenhum(robots, monkeypatch, url):
    lidos = []                                   # o robots.txt e lido por requests.get: nem ele pode ser pedido
    original = robots["padrao"]
    monkeypatch.setattr("adaptadores.fetcher_requests.requests.get", lambda u, **k: lidos.append(u) or original)
    rede = Rede(monkeypatch, {})
    a = FetcherRequests(UA).baixar(url)
    assert a.chamada.erro == "url_invalida" and not a.chamada.sucesso and a.conteudo == b""
    assert rede.pedidos == [] and lidos == []


@pytest.mark.parametrize("destino", ["http://[bad/", "ftp://b.example/x", "javascript:x", "https://www./x",
                                     "http://b.example:99999/"])
def test_redirecionamento_para_destino_invalido_para_sem_novo_pedido(robots, monkeypatch, destino):
    r1, _, _, _ = resp = _redir(destino)
    rede = Rede(monkeypatch, {A: resp})
    a = FetcherRequests(UA).baixar(A)
    assert a.chamada.erro == "url_invalida_apos_redirecionamento" and not a.chamada.sucesso and a.conteudo == b""
    assert [p[0] for p in rede.pedidos] == [A] and r1.closed
    assert a.chamada.extras["redirecionamentos"] == [A] and a.chamada.extras["destino_invalido"] == destino


def test_destino_invalido_muito_longo_e_cortado_nos_extras(robots, monkeypatch):
    destino = "ftp://b.example/" + "x" * 5000
    Rede(monkeypatch, {A: _redir(destino)})
    a = FetcherRequests(UA).baixar(A)
    assert a.chamada.extras["destino_invalido"] == destino[:2000]


def test_redirecionamento_relativo_valido_continua_funcionando(robots, monkeypatch):
    rede = Rede(monkeypatch, {A: _redir("/outra"), "https://a.gov.br/outra": Resp(url="https://a.gov.br/outra")})
    a = FetcherRequests(UA).baixar(A)
    assert a.chamada.sucesso and [p[0] for p in rede.pedidos] == [A, "https://a.gov.br/outra"]


def test_segundo_salto_invalido_lista_so_os_saltos_validos(robots, monkeypatch):
    B = "https://b.example/final"
    rede = Rede(monkeypatch, {A: _redir(B), B: _redir("http://[bad/", url=B)})
    a = FetcherRequests(UA).baixar(A)
    assert a.chamada.erro == "url_invalida_apos_redirecionamento" and [p[0] for p in rede.pedidos] == [A, B]
    assert a.chamada.extras["redirecionamentos"] == [A, B] and a.chamada.extras["destino_invalido"] == "http://[bad/"


@pytest.mark.parametrize("location,destino", [("/a b.pdf", "https://a.gov.br/a%20b.pdf"),
                                              (" /outra ", "https://a.gov.br/outra"),
                                              ("https://b.example/x y", "https://b.example/x%20y"),
                                              ("/ja%20codificado", "https://a.gov.br/ja%20codificado")])
def test_location_com_espaco_e_codificado_e_seguido(robots, monkeypatch, location, destino):
    rede = Rede(monkeypatch, {A: _redir(location), destino: Resp(url=destino)})
    a = FetcherRequests(UA).baixar(A)
    assert a.chamada.sucesso and [p[0] for p in rede.pedidos] == [A, destino]
    assert a.chamada.extras["redirecionamentos"] == [A, destino]


@pytest.mark.parametrize("location", ["", "   "])
def test_location_vazio_nao_e_redirecionamento(robots, monkeypatch, location):
    rede = Rede(monkeypatch, {A: (Resp(url=A, status=302, location=location or None, blocos=(b"x",)), None, 302, None)})
    if location:
        rede.paginas[A][0].headers["Location"] = location
    a = FetcherRequests(UA).baixar(A)
    assert [p[0] for p in rede.pedidos] == [A] and "redirecionamentos" not in a.chamada.extras
    assert a.chamada.erro != "url_invalida_apos_redirecionamento"


def test_link_invalido_muito_longo_e_cortado_no_log(tmp_path, caplog):
    class BuscaLonga(BuscaSimulada):
        def buscar(self, consulta, filtros):
            res = [ResultadoWeb("ftp://x/" + "y" * 5000, "t", "s", None, 1)]
            return RespostaBusca(res, super().buscar(consulta, filtros).chamada)
    with caplog.at_level(logging.WARNING):
        _rodar_busca(tmp_path, BuscaLonga())
    linha = next((r.getMessage() for r in caplog.records if "link invalido descartado" in r.getMessage()), "")
    assert linha.endswith(repr(("ftp://x/" + "y" * 5000)[:2000]))
