"""Download: `max_falhas_por_pagina` abandona a pagina que falha sempre igual nas retomadas; sucessos nunca sao limitados."""
import logging

import pytest

import config.settings as S
from adaptadores.bruto_local import BrutoLocal
from adaptadores.repositorio_sqlite import RepositorioSQLite
from adaptadores.simulados import ExtratorSimulado, FetcherSimulado
from aplicacao import busca_web, download
from config import consultas as C
from dados_metricas import Busca4Urls, _consulta_pi, _novo_run
from dominio.modelos import ArquivoBaixado


class FetcherContador(FetcherSimulado):
    """Conta as chamadas por URL; `sempre_falha` (sufixos) falham sempre, as demais tem sucesso."""

    def __init__(self, sempre_falha=()):
        self.sempre_falha, self.chamadas = tuple(sempre_falha), []

    def baixar(self, url):
        self.chamadas.append(url)
        base = super().baixar(url)
        if url.endswith(self.sempre_falha) and self.sempre_falha:
            base.chamada.erro, base.chamada.http_status = "HTTP 503", 503
            return ArquivoBaixado(url, 503, "", b"", False, base.chamada)
        return base


@pytest.fixture
def cenario(tmp_path):
    repo, bruto = RepositorioSQLite(tmp_path / "d.db"), BrutoLocal(tmp_path / "raw")
    run_id = _novo_run(repo, "baixar")
    busca_web.executar(repo, bruto, Busca4Urls(), run_id, _consulta_pi(), C.PERFIS_BUSCA_WEB, [], 0)
    return repo, bruto, run_id


def _baixar(cenario, fetcher, **kw):
    repo, bruto, run_id = cenario
    download.executar(repo, bruto, fetcher, ExtratorSimulado(), run_id, run_id, C.POLITICA_DOWNLOAD, [], 0, ufs={"PI"}, **kw)


def _metrica(repo, run_id):
    linha = repo.conn.execute("SELECT valor FROM metricas_run WHERE run_id=? AND chave='download_desistencias'", (run_id,)).fetchone()
    return None if linha is None else linha[0]


def test_a_configuracao_traz_o_limite_e_ele_entra_no_hash():
    assert S.DOWNLOAD == {"max_falhas_por_pagina": 3}
    antes = S.snapshot_config()["hash"]
    S.DOWNLOAD["max_falhas_por_pagina"] = 5
    try:
        assert S.snapshot_config()["hash"] != antes
    finally:
        S.DOWNLOAD["max_falhas_por_pagina"] = 3


def test_retomar_tres_vezes_para_de_chamar_o_fetcher_depois_do_limite(cenario, caplog):
    repo, _, run_id = cenario
    f = FetcherContador(sempre_falha=("/pi/2",))
    for _ in range(3):
        _baixar(cenario, f, max_falhas_por_pagina=3)
    ruins = [u for u in f.chamadas if u.endswith("/pi/2")]
    assert len(ruins) == 3 and _metrica(repo, run_id) == 0                      # 3 tentativas, ainda nao desistiu
    with caplog.at_level(logging.WARNING):
        _baixar(cenario, f, max_falhas_por_pagina=3)                           # 4a retomada: limite atingido
    assert len([u for u in f.chamadas if u.endswith("/pi/2")]) == 3 and _metrica(repo, run_id) == 1
    assert any("abandonada" in r.message and "3 falhas" in r.message for r in caplog.records)
    _baixar(cenario, f, max_falhas_por_pagina=3)
    assert len([u for u in f.chamadas if u.endswith("/pi/2")]) == 3


def test_sucessos_nunca_sao_limitados_nem_rebaixados(cenario):
    repo, _, run_id = cenario
    f = FetcherContador(sempre_falha=("/pi/2",))
    for _ in range(5):
        _baixar(cenario, f, max_falhas_por_pagina=1)
    boas = [u for u in f.chamadas if not u.endswith("/pi/2")]
    assert len(boas) == 3 and len(set(boas)) == 3                               # baixadas uma vez so (idempotencia), nunca desistidas
    assert repo.conn.execute("SELECT COUNT(*) FROM paginas").fetchone()[0] == 3
    assert len([u for u in f.chamadas if u.endswith("/pi/2")]) == 1 and _metrica(repo, run_id) == 1


def test_sem_limite_o_comportamento_antigo_continua(cenario):
    repo, _, run_id = cenario
    f = FetcherContador(sempre_falha=("/pi/2",))
    for _ in range(5):
        _baixar(cenario, f)
    assert len([u for u in f.chamadas if u.endswith("/pi/2")]) == 5 and _metrica(repo, run_id) == 0


def test_falhas_de_outra_execucao_nao_contam(cenario, tmp_path):
    repo, bruto, run_id = cenario
    f = FetcherContador(sempre_falha=("/pi/2",))
    _baixar(cenario, f, max_falhas_por_pagina=1)
    outra = _novo_run(repo, "baixar")
    download.executar(repo, bruto, f, ExtratorSimulado(), outra, run_id, C.POLITICA_DOWNLOAD, [], 0, ufs={"PI"}, max_falhas_por_pagina=1)
    assert len([u for u in f.chamadas if u.endswith("/pi/2")]) == 2             # a nova execucao tenta de novo
