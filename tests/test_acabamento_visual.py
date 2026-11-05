"""Acabamento visual do painel (só CSS publicado a partir de design/src): menu compacto em telas estreitas, pista de
rolagem em tabelas e abas, ficha do Observatório, uma ação primária por bloco da Visão geral, padrão único dos resumos
recolhíveis, gráficos legíveis no celular e o estilo do índice "Nesta página". Nenhum texto, valor ou permissão muda."""
import re
from pathlib import Path

import pytest

from test_painel_acessibilidade import _blocos, _regras, _sem_comentarios

STATIC = Path(__file__).resolve().parent.parent / "painel" / "static"


def _css(nome):
    return _sem_comentarios((STATIC / nome).read_text(encoding="utf-8"))


def _media(css, condicao, contem=None):
    """Regras do primeiro bloco @media cuja condição casa com `condicao` (e que contém o texto `contem`, se dado)."""
    for prefixo, corpo in _blocos(css):
        if re.match(r"@media\s*\(" + condicao + r"\)", prefixo) and (contem is None or contem in corpo):
            return _regras(corpo)
    raise AssertionError(f"bloco @media ({condicao}) não encontrado")


def _estreito():
    return _media(_css("painel.css"), r"max-width:\s*900px", contem=".layout")


# ---------- C1: barra e menu compactos em telas estreitas ----------
@pytest.mark.parametrize("seletor, propriedade, valor", [
    (".banner-detalhe", "display", "none"),
    (".banner > strong", "flex", "1 1 100%"),
    (".menu-grupo > summary", "padding-block", ".3rem"),
    (".menu-lista a", "min-height", "2rem"),
    (".menu-lista a", "padding", ".25rem .75rem"),
    (".menu-lista a", "font-size", "var(--fs-sm)"),
    (".menu-lista a::before", "display", "none"),
])
def test_menu_compacto_no_estreito(seletor, propriedade, valor):
    assert _estreito()[seletor][propriedade] == valor


def test_no_desktop_o_detalhe_tecnico_e_os_icones_do_menu_continuam():
    regras = _regras(_css("painel.css"))
    assert regras[".banner-detalhe"].get("display") != "none"
    assert regras.get(".menu-lista a::before", {}).get("display") != "none"


def test_o_menu_estreito_continua_quebrando_linha_e_sem_esconder_links():
    estreito = _estreito()
    assert estreito[".menu-lista"]["flex-wrap"] == "wrap"
    assert all("nowrap" not in v for d in estreito.values() for v in d.values())
    for seletor in (".banner .conta", ".conta", ".conta-estatisticas", ".conta-admin", ".conta-nome", ".form-sair",
                    ".menu-lista", ".menu-lista a", ".menu-grupo", ".tema-alternar"):
        assert estreito.get(seletor, {}).get("display") != "none", seletor
        assert "hidden" not in estreito.get(seletor, {}).get("overflow", ""), seletor


# ---------- C2: pista de rolagem ----------
@pytest.mark.parametrize("arquivo, seletor", [("painel.css", ".tabela-rolavel"), ("analises.css", ".an-abas")])
def test_pista_de_rolagem_so_com_css(arquivo, seletor):
    decl = _regras(_css(arquivo))[seletor]
    anexo = decl.get("background-attachment", "")
    assert "local" in anexo and "scroll" in anexo, (seletor, decl)


def test_a_tabela_rolavel_continua_rolando():
    assert "overflow-x" in _regras(_css("painel.css"))[".tabela-rolavel"]


# ---------- C3: ficha do Observatório ----------
@pytest.mark.parametrize("seletor, propriedade, valor", [
    (".obs-ficha", "display", "flex"),
    (".obs-ficha", "flex-wrap", "wrap"),
    (".obs-ficha dd", "margin", "0"),
    (".obs-ficha dt", "color", "var(--texto-suave)"),
    (".obs-ficha dt", "font-size", "var(--fs-sm)"),
])
def test_ficha_do_observatorio_tem_estilo(seletor, propriedade, valor):
    assert _regras(_css("analises.css"))[seletor][propriedade] == valor


# ---------- C4: uma ação primária por bloco da Visão geral ----------
SECUNDARIOS = (".vg-bloco .botao ~ .botao", "#vg-bloco-links .botao")


def _blocos_com(css, seletor):
    """Regras de cada bloco (topo e @media) em que `seletor` aparece."""
    saida = [("topo", _regras(css))]
    saida += [(p, _regras(c)) for p, c in _blocos(css) if p.startswith("@media")]
    return [(p, r) for p, r in saida if seletor in r]


@pytest.mark.parametrize("estado", ["", ":hover"])
def test_acoes_seguintes_do_bloco_e_links_tem_o_visual_secundario_em_todo_tema(estado):
    css = _css("painel.css")
    blocos = _blocos_com(css, ".botao.secundario" + estado)
    assert blocos
    for prefixo, regras in blocos:
        for seletor in SECUNDARIOS:
            assert regras.get(seletor + estado) == regras[".botao.secundario" + estado], (prefixo, seletor + estado)


# ---------- C5: gráficos legíveis no celular ----------
def test_grafico_no_celular_rola_dentro_do_cartao_em_vez_de_encolher():
    assert _media(_css("analises.css"), r"max-width:\s*600px")[".an-grafico .an-svg"]["min-width"] == "34rem"
    assert "overflow-x" in _regras(_css("analises.css"))[".an-grafico"]


# ---------- C6: "Definições e origem dos números" no padrão da Memória de cálculo ----------
@pytest.mark.parametrize("seletor, propriedade, valor", [
    ("details.vg-definicoes > summary", "list-style", "none"),
    ("details.vg-definicoes > summary", "display", "flex"),
    ("details.vg-definicoes > summary", "cursor", "pointer"),
    ("details.vg-definicoes > summary::-webkit-details-marker", "display", "none"),
    ("details.vg-definicoes > summary::after", "content", '"Mostrar"'),
    ("details.vg-definicoes[open] > summary::after", "content", '"Ocultar"'),
])
def test_definicoes_no_padrao_da_memoria_de_calculo(seletor, propriedade, valor):
    assert _regras(_css("painel.css"))[seletor][propriedade] == valor


def test_o_foco_dos_resumos_continua_visivel():
    css = _css("painel.css")
    assert "summary:focus-visible" in css.replace("\n", " ")
    assert "outline: none" not in css and "outline:none" not in css


# ---------- estilo do índice "Nesta página" ----------
@pytest.mark.parametrize("seletor, propriedade, valor", [
    (".nesta-pagina ul", "display", "flex"),
    (".nesta-pagina ul", "flex-wrap", "wrap"),
    (".nesta-pagina ul", "list-style", "none"),
])
def test_estilo_do_indice_nesta_pagina(seletor, propriedade, valor):
    assert _regras(_css("painel.css"))[seletor][propriedade] == valor


@pytest.mark.parametrize("arquivo, seletor", [("painel.css", ".tabela-rolavel"), ("analises.css", ".an-abas")])
def test_pista_de_rolagem_usa_so_cores_de_token(arquivo, seletor):
    decl = _regras(_css(arquivo))[seletor]
    fundo = decl.get("background", "") + decl.get("background-image", "")
    assert "var(--" in fundo
    assert not re.search(r"rgba?\(|hsla?\(|#[0-9a-fA-F]{3,8}\b", fundo), (seletor, fundo)
