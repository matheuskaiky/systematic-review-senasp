"""Endereco que so recebe formulario (POST), aberto pela barra de enderecos: pagina de erro do painel com o cabecalho
Allow, nunca o JSON cru do framework."""
import pytest

from test_autenticacao import _criar, _entrar, painel  # noqa: F401
from test_painel import demo  # noqa: F401

TITULO = "Endereço só para formulários"
TEXTO = "Este endereço só recebe o envio de um formulário. Volte à página anterior e use o botão."


@pytest.mark.parametrize("rota", ["/admin/grupos/novo", "/admin/grupos/1/renomear", "/sair", "/achados/1/verificar",
                                  "/literatura/artigos/1/triar"])
def test_get_em_rota_so_de_formulario_mostra_a_pagina_de_erro(painel, rota):
    cli = painel[0]
    _criar(painel, "chefe", "Administrador")
    assert _entrar(cli, "chefe").status_code == 303
    r = cli.get(rota, follow_redirects=False)
    assert r.status_code == 405
    assert r.headers["content-type"].startswith("text/html")
    assert TITULO in r.text and TEXTO in r.text
    assert "Method Not Allowed" not in r.text
    assert "POST" in r.headers["allow"]


def test_rota_inexistente_continua_404(painel):
    cli = painel[0]
    _criar(painel, "chefe", "Administrador")
    _entrar(cli, "chefe")
    r = cli.get("/admin/grupos/novo/nada", follow_redirects=False)
    assert r.status_code == 404 and "Página não encontrada" in r.text
