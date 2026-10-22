"""Faixa do banco no painel: no banco de viés algorítmico, as dicas de comando das telas valem com --banco vies (D111)."""
import pytest
from fastapi.testclient import TestClient

from adaptadores.bruto_local import BrutoLocal
from adaptadores.leitura_sqlite import LeituraPainelSQLite
from config import consultas as C, vocabulario as V
from painel.app import Contexto, criar_app

def _cli(tmp_path, banco, somente_leitura=False):
    ctx = Contexto(banco=banco, nome_banco="busca.db", somente_leitura=somente_leitura, pasta_backup=tmp_path / "b",
                   ufs=dict(C.UFS), status_permitidos=set(V.STATUS), status_definicoes=dict(V.STATUS),
                   hosts_permitidos=("testserver",))
    return TestClient(criar_app(LeituraPainelSQLite(tmp_path / "nao.db"), lambda: None, BrutoLocal(tmp_path), ctx))


@pytest.mark.parametrize("banco, somente_leitura, detalhe", [
    ("vies", False, "busca.db · comandos: acrescente --banco vies"),
    ("vies", True, "busca.db · somente leitura · comandos: acrescente --banco vies"),
    ("real", False, "busca.db"), ("real", True, "busca.db · somente leitura"),
])
def test_faixa_do_banco(banco, somente_leitura, detalhe, tmp_path):
    html = _cli(tmp_path, banco, somente_leitura).get("/sobre").text
    assert f'<span class="banner-detalhe">{detalhe}</span>' in html

