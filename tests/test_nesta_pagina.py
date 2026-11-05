"""Índice "Nesta página" da Visão geral: uma linha de links-âncora para as seções que a própria página já mostra, na mesma
ordem e com os mesmos títulos. Não lê dado novo: as seções vêm do mesmo `secoes` que a página renderiza (logo respeita
perfil e divulgação). Só aparece com 3 seções ou mais."""
import re

import pytest

from painel import visao_geral as VG
from test_autenticacao import painel  # noqa: F401
from test_painel import demo  # noqa: F401
from test_menu_e_acoes_por_permissao import clientes, vies  # noqa: F401
from test_validacao_vies import banco  # noqa: F401

NAV = re.compile(r'<nav class="nesta-pagina" aria-label="Nesta página">\n<ul>\n(.*?)</ul>\n</nav>', re.S)


def _secoes(h):
    return re.findall(r'<section class="vg-secao" id="vg-([a-z_]+)" aria-labelledby="t-vg-\1">\n<h2 id="t-vg-\1">([^<]+)</h2>', h)


def _links(h):
    m = NAV.search(h)
    assert m, "índice ausente"
    itens = re.findall(r'<li><a href="#vg-([a-z_]+)">([^<]+)</a></li>\n', m.group(1))
    assert "".join(f'<li><a href="#vg-{i}">{t}</a></li>\n' for i, t in itens) == m.group(1)      # nada além dos itens
    return itens


@pytest.mark.parametrize("grupo", ["Visitante", "Leitor", "Revisor", "Administrador"])
def test_indice_lista_as_secoes_da_pagina_na_mesma_ordem_e_com_os_mesmos_titulos(clientes, grupo):  # noqa: F811
    h = clientes[grupo].get("/").text
    secoes = _secoes(h)
    assert len(secoes) >= 3
    assert _links(h) == secoes
    assert h.count('class="nesta-pagina"') == 1


def test_indice_fica_entre_a_apresentacao_e_a_primeira_secao(clientes):  # noqa: F811
    h = clientes["Administrador"].get("/").text
    i_nav = h.index('<nav class="nesta-pagina"')
    assert h.index("<h1>Visão geral</h1>") < i_nav < h.index('<section class="vg-secao"')
    assert "vg-ap-" not in h[i_nav:h.index('<section class="vg-secao"')]


def test_cada_link_do_indice_aponta_para_um_id_que_existe(clientes):  # noqa: F811
    h = clientes["Administrador"].get("/").text
    for sid, _ in _links(h):
        assert h.count(f'id="vg-{sid}"') == 1, sid


@pytest.mark.parametrize("grupo", ["Visitante", "Leitor", "Revisor", "Administrador"])
def test_indice_no_banco_vies_para_cada_perfil(vies, grupo):  # noqa: F811
    h = vies[grupo].get("/").text
    assert _links(h) == _secoes(h) and len(_secoes(h)) >= 3
    for sid, _ in _links(h):
        assert h.count(f'id="vg-{sid}"') == 1, (grupo, sid)


@pytest.mark.parametrize("n, aparece", [(0, False), (1, False), (2, False), (3, True)])
def test_indice_so_com_tres_secoes_ou_mais(clientes, monkeypatch, n, aparece):  # noqa: F811
    original = VG.montar
    monkeypatch.setattr(VG, "montar", lambda dados, quem: original(dados, quem)[:n])
    h = clientes["Administrador"].get("/").text
    assert ('class="nesta-pagina"' in h) is aparece
    if aparece:
        assert _links(h) == _secoes(h) and len(_secoes(h)) == 3


def test_titulo_com_caractere_especial_sai_escapado(clientes, monkeypatch):  # noqa: F811
    original = VG.montar

    def com_titulo(dados, quem):
        s = original(dados, quem)
        s[0] = {**s[0], "titulo": "A <b>pesquisa</b> & cia"}
        return s
    monkeypatch.setattr(VG, "montar", com_titulo)
    h = clientes["Administrador"].get("/").text
    m = NAV.search(h)
    assert "A &lt;b&gt;pesquisa&lt;/b&gt; &amp; cia" in m.group(1) and "<b>" not in m.group(1)
