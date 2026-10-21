"""Busca web da Tarefa 1: uma falha ou interrupcao entre a resposta paga e o registro deixa a chamada gravada como falha,
e a validacao dos links e a mesma da busca de literatura (`aplicacao.comum.resultados_validos`)."""
import logging
import pathlib
import sys

import pytest

from adaptadores.bruto_local import BrutoLocal
from adaptadores.repositorio_sqlite import RepositorioSQLite
from aplicacao import busca_web
from aplicacao.comum import resultados_validos
from config import consultas as C
from dominio.modelos import RegistroChamada, RespostaBusca, ResultadoWeb
from dominio.servicos import gerar_consultas_web
from infra.util import agora

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from dados_metricas import _novo_run  # noqa: E402


class _ListaQueInterrompe(list):
    def __iter__(self):
        raise KeyboardInterrupt


class _Busca:
    nome = "falsa"

    def __init__(self, resultados=None):
        self.pedidos, self._resultados = [], resultados

    def buscar(self, consulta, filtros):
        self.pedidos.append(consulta.id)
        reg = RegistroChamada(provedor=self.nome, operacao="buscar", parametros={}, requisitado_em=agora(),
                              http_status=200, raw=b"{}")
        res = self._resultados if self._resultados is not None else [ResultadoWeb(f"https://a.gov.br/{consulta.id}", "t", "s", None, 1)]
        return RespostaBusca(res, reg)


def _consultas():
    return gerar_consultas_web(C.MODELOS_WEB[:2], {"reconhecimento_facial": "reconhecimento facial"}, {"PI": C.UFS["PI"]})


@pytest.fixture
def repo(tmp_path):
    r = RepositorioSQLite(tmp_path / "t.db")
    yield r
    r.fechar()


def _linhas(repo, sql, *p):
    return [tuple(l) for l in repo.conn.execute(sql, p)]


def test_interrupcao_depois_da_chamada_fica_registrada_como_falha(repo, tmp_path):
    run_id = _novo_run(repo, "busca-web")
    busca = _Busca(resultados=_ListaQueInterrompe([ResultadoWeb("https://a.gov.br/1", "t", "s", None, 1)]))
    with pytest.raises(KeyboardInterrupt):
        busca_web.executar(repo, BrutoLocal(tmp_path / "raw"), busca, run_id, _consultas(), C.PERFIS_BUSCA_WEB, [], 0)
    assert _linhas(repo, "SELECT alvo_id, uf, sucesso, erro FROM chamadas WHERE run_id=?", run_id) == [
        ("M01-PI-reconhecimento_facial", "PI", 0, "falha_ao_validar: KeyboardInterrupt")]
    assert _linhas(repo, "SELECT COUNT(*) FROM resultados_web") == [(0,)]
    assert busca.pedidos == ["M01-PI-reconhecimento_facial"]


def test_registro_da_falha_que_falha_nao_esconde_a_interrupcao(repo, tmp_path, monkeypatch):
    import aplicacao.comum as comum

    def quebra(*a, **k):
        raise RuntimeError("banco fora")
    monkeypatch.setattr(comum, "registrar_chamada", quebra)
    run_id = _novo_run(repo, "busca-web")
    busca = _Busca(resultados=_ListaQueInterrompe([]))
    with pytest.raises(KeyboardInterrupt):
        busca_web.executar(repo, BrutoLocal(tmp_path / "raw"), busca, run_id, _consultas(), C.PERFIS_BUSCA_WEB, [], 0)


def test_consulta_que_falhou_na_janela_e_refeita_na_retomada_e_conta_no_limite(repo, tmp_path):
    run_id = _novo_run(repo, "busca-web")
    with pytest.raises(KeyboardInterrupt):
        busca_web.executar(repo, BrutoLocal(tmp_path / "raw"), _Busca(resultados=_ListaQueInterrompe([])), run_id,
                           _consultas(), C.PERFIS_BUSCA_WEB, [], 0, limite=1)
    busca = _Busca()
    busca_web.executar(repo, BrutoLocal(tmp_path / "raw"), busca, run_id, _consultas(), C.PERFIS_BUSCA_WEB, [], 0, limite=1)
    assert busca.pedidos == ["M01-PI-reconhecimento_facial"]          # refeita; a segunda passaria do limite
    assert _linhas(repo, "SELECT alvo_id, sucesso FROM chamadas WHERE run_id=? ORDER BY chamada_id", run_id) == [
        ("M01-PI-reconhecimento_facial", 0), ("M01-PI-reconhecimento_facial", 1)]


@pytest.mark.parametrize("urls, validos, extras", [
    ([], [], {}),
    (["https://a.gov.br/1", "https://a.gov.br/1"], ["https://a.gov.br/1", "https://a.gov.br/1"], {}),   # repetida nao some aqui
    (["https://a.gov.br/1", "https://b.gov.br/2"], ["https://a.gov.br/1", "https://b.gov.br/2"], {}),
    (["https://a.gov.br/1", "nao e url", "https://b.gov.br/2"], ["https://a.gov.br/1", "https://b.gov.br/2"], {"urls_invalidas": 1}),
    (["ftp://x.org/a", None, 42], [], {"urls_invalidas": 3}),
])
def test_resultados_validos_na_ordem_da_resposta(urls, validos, extras, caplog):
    reg = RegistroChamada(provedor="falsa", operacao="buscar", parametros={}, requisitado_em=agora())
    resp = RespostaBusca([ResultadoWeb(u, None, None, None, n) for n, u in enumerate(urls, 1)], reg)
    with caplog.at_level(logging.WARNING):
        assert [r.url for r in resultados_validos(resp, "X1")] == validos
    assert reg.extras == extras
    invalidas = [u for u in urls if u not in validos]
    assert [x.getMessage() for x in caplog.records] == [f"[X1] link invalido descartado: {u!r}" for u in invalidas]


def test_link_invalido_longo_aparece_cortado_no_log(caplog):
    reg = RegistroChamada(provedor="falsa", operacao="buscar", parametros={}, requisitado_em=agora())
    longo = "x" * 5000
    with caplog.at_level(logging.WARNING):
        resultados_validos(RespostaBusca([ResultadoWeb(longo, None, None, None, 1)], reg), "X1")
    assert caplog.records[0].getMessage() == f"[X1] link invalido descartado: {'x' * 2000!r}"


def test_extras_que_ja_existiam_continuam():
    reg = RegistroChamada(provedor="falsa", operacao="buscar", parametros={}, requisitado_em=agora(), extras={"historico": [1]})
    resultados_validos(RespostaBusca([ResultadoWeb("nao e url", None, None, None, 1)], reg), "X1")
    assert reg.extras == {"historico": [1], "urls_invalidas": 1}
