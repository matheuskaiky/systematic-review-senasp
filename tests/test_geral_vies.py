"""Visão geral e menu do banco `vies` (busca de viés algorítmico): a página inicial mostra os números desta busca, o menu
esconde as telas só da Tarefa 1 (as rotas continuam no ar) e o banco real fica como estava."""
import re
from pathlib import Path

import pytest

from painel import navegacao
from test_analises_vies import _cli, banco  # noqa: F401  (fixture do banco vies com triagem)

TAREFA_1 = {"/estados", "/achados", "/revisao/achados", "/classificadores", "/execucoes/comparar", "/solucoes", "/buscar-texto"}


def _hrefs(grupos):
    return [i["href"] for g in grupos for i in g["itens"]]


def _menu(html):
    return re.search(r'<nav class="menu" aria-label="Principal">.*?</nav>', html, re.S).group(0)


def test_lista_das_telas_so_da_tarefa_1():
    assert navegacao.SO_TAREFA_1 == TAREFA_1 and TAREFA_1 <= set(navegacao.enderecos())


def test_menu_do_vies_sem_as_telas_da_tarefa_1_na_mesma_ordem():
    todos = navegacao.enderecos()
    assert _hrefs(navegacao.grupos("/", banco="vies")) == [h for h in todos if h not in TAREFA_1]
    assert _hrefs(navegacao.grupos("/", banco="real")) == [h for h in todos if h not in navegacao.SO_VIES] == _hrefs(navegacao.grupos("/"))
    assert [g["id"] for g in navegacao.grupos("/", banco="vies")] == ["revisao", "analises", "auditoria"]


def test_menu_do_vies_com_admin_mantem_a_administracao():
    assert _hrefs(navegacao.grupos("/", admin=True, banco="vies"))[-4:] == ["/admin/usuarios", "/admin/grupos", "/admin/auditoria",
                                                                           "/estatisticas-usuarios"]


def test_pagina_do_vies_sem_links_da_tarefa_1_no_menu_e_rotas_no_ar(banco, tmp_path):
    cli = _cli(banco, tmp_path)
    for caminho in ("/", "/analises", "/literatura/artigos"):
        menu = _menu(cli.get(caminho).text)
        assert all(f'href="{h}"' not in menu for h in TAREFA_1), caminho
        assert 'href="/literatura/referencias"' in menu and 'href="/analises"' in menu
    for h in TAREFA_1:
        assert cli.get(h).status_code == 200, h


def test_visao_geral_do_vies_mostra_os_numeros_da_busca(banco, tmp_path):
    html = _cli(banco, tmp_path).get("/").text
    assert "Busca de literatura científica e cinzenta sobre viés algorítmico" in html
    assert '<span class="kpi-valor">5</span><span class="kpi-rotulo">Obras distintas</span>' in html
    assert '<span class="kpi-valor">4</span><span class="kpi-rotulo">Referências da web</span>' in html
    assert '<span class="kpi-valor">1</span><span class="kpi-rotulo">Fora do escopo</span>' in html
    assert "Relevância alta ou média segundo o modelo: 100% das referências da web e 0% dos artigos do Scholar" in html
    assert '<link rel="stylesheet" href="/static/analises.css">' in html
    assert "Funil do levantamento nas secretarias" not in html and "Prontidão metodológica" not in html
    assert "Triagem humana dos artigos" in html and "Últimas execuções" in html


def test_visao_geral_do_banco_real_continua_com_o_funil(copiar_demo, tmp_path):
    demo, _ = copiar_demo("geral_real")
    html = _cli(demo, tmp_path, nome="real").get("/").text
    assert "Funil do levantamento nas secretarias" in html and "Obras distintas" not in html
    assert all(f'href="{h}"' in _menu(html) for h in TAREFA_1)


@pytest.mark.parametrize("arquivo, seletor", [
    ("design/src/analises.css", ".an-abas"), ("painel/static/analises.css", ".an-abas"),
    ("design/src/triagem_escopo.css", ".abas"), ("painel/static/triagem_escopo.css", ".abas"),
])
def test_barras_de_abas_ocupam_a_largura_dos_cartoes(arquivo, seletor):
    css = Path(arquivo).read_text(encoding="utf-8")
    regra = re.search("^" + re.escape(seletor) + r" \{[^}]*\}", css, re.M).group(0)
    assert "fit-content" not in regra and "max-width: 100%" not in regra
