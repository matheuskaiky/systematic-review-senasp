"""Testes do sistema de ícones. O ícone de um elemento vem do atributo data-ic="nome" (e do matiz, opcional, data-tom="...");
o CSS tem uma regra [data-ic="nome"] por ícone. Um nome errado não quebra nada, mas o ícone some em silêncio: estes testes pegam o erro de digitação."""
import pathlib
import re

import pytest

RAIZ = pathlib.Path(__file__).resolve().parent.parent
CAMINHOS = {"css": str(RAIZ / "painel/static/painel.css"), "fonte": str(RAIZ / "painel/static/fonts/observatorio-icones-v1.woff2"), "templates": str(RAIZ / "painel/templates"), "codigo": str(RAIZ / "painel")}
MATIZES = {"cobalto", "petroleo", "violeta", "ambar", "rosa"}


def _css():
    return pathlib.Path(CAMINHOS["css"]).read_text(encoding="utf-8")


def _fontes_de_marcacao():
    """Templates e arquivos .py que escrevem HTML (macros em Python, gráficos, selos)."""
    arquivos = list(pathlib.Path(CAMINHOS["templates"]).glob("*.html")) + [p for p in pathlib.Path(CAMINHOS["codigo"]).rglob("*.py") if "tests" not in p.parts]
    return {str(p): p.read_text(encoding="utf-8") for p in arquivos}


def test_todo_data_ic_usado_tem_regra_no_css():
    conhecidos = set(re.findall(r'\[data-ic="([\w-]+)"\]', _css()))
    assert len(conhecidos) >= 100, "o mapa de ícones de painel.css está incompleto"
    usados = set()
    for caminho, texto in _fontes_de_marcacao().items():
        for nome in re.findall(r'data-ic="([\w-]+)"', texto):
            usados.add(nome)
            assert nome in conhecidos, f"{caminho}: data-ic=\"{nome}\" não existe em painel.css"
    assert usados, "nenhum data-ic encontrado: o patch dos templates (03_ICONES_E_MATIZES_POR_TELA.md) foi aplicado?"


def test_todo_data_tom_e_um_dos_cinco_matizes():
    for caminho, texto in _fontes_de_marcacao().items():
        for tom in re.findall(r'data-tom="([\w-]+)"', texto):
            assert tom in MATIZES, f"{caminho}: data-tom=\"{tom}\" não é um dos cinco matizes {sorted(MATIZES)}"


def test_icone_so_em_elementos_que_o_css_conhece():
    """data-ic vale em h2, h3, summary, .kpi, .aviso, .vazio, a, button, .botao e .selo (ver o cabeçalho do mapa de ícones em painel.css)."""
    permitidos = re.compile(r"<(h2|h3|summary|div|a|button|span|p|section)\b[^>]*\bdata-ic=")
    for caminho, texto in _fontes_de_marcacao().items():
        for m in re.finditer(r"<(\w+)\b[^>]*\bdata-ic=", texto):
            assert m.group(1) in ("h2", "h3", "summary", "div", "a", "button", "span", "p", "section"), f"{caminho}: <{m.group(1)} data-ic>"
    assert permitidos


def test_codigos_de_glifo_do_css_existem_na_fonte():
    fonttools = pytest.importorskip("fontTools.ttLib")
    font = fonttools.TTFont(CAMINHOS["fonte"])
    cmap = font.getBestCmap()
    codigos = {int(c, 16) for c in re.findall(r'"\\(e[0-9a-f]{3})"', _css())}
    assert codigos, "nenhum glifo de ícone no CSS"
    faltam = sorted(hex(c) for c in codigos if c not in cmap)
    assert not faltam, f"glifos que o CSS usa e a fonte não tem: {faltam}"
