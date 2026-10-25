"""O Observatorio no menu do painel: so no banco `vies`, primeiro item de "Analises e qualidade", marcado como atual na
pagina e na lista de obras, com o icone e a cor do grupo vindos do gerador do CSS (bussola, violeta)."""
import re
from pathlib import Path

from painel import navegacao
from test_observatorio_obras import _cli, sintetico  # noqa: F401
from test_painel_navegacao import _menu
from test_validacao_vies import banco  # noqa: F401

RAIZ = Path(__file__).resolve().parent.parent


def _analises(html):
    return next(links for nome, _, links in _menu(html) if nome == "Análises e qualidade")


def test_observatorio_so_no_menu_do_vies(banco, tmp_path):
    assert "/observatorio" in navegacao.SO_VIES and "/observatorio" in navegacao.enderecos()
    vies = [h for h, _, _ in _analises(_cli(banco, tmp_path).get("/").text)]
    assert vies[:2] == ["/observatorio", "/analises"]
    real = [h for h, _, _ in _analises(_cli(banco, tmp_path, nome="real").get("/").text)]
    assert "/observatorio" not in real


def test_texto_e_marca_de_pagina_atual(sintetico):
    cli, _ = sintetico
    for rota in ("/observatorio", "/observatorio?perspectiva=vies", "/observatorio/obras", "/observatorio/obras?fonte=web"):
        links = _analises(cli.get(rota).text)
        assert links[0] == ("/observatorio", True, "Observatório"), rota
        assert not any(atual for h, atual, _ in links[1:]), rota
    links = _analises(cli.get("/analises").text)
    assert links[0] == ("/observatorio", False, "Observatório") and links[1][:2] == ("/analises", True)


def test_icone_e_cor_vem_do_gerador():
    gerador = (RAIZ / "design" / "tools" / "gerar_painel_css.py").read_text(encoding="utf-8")
    assert '("/observatorio", "compass", "violeta")' in gerador
    css = (RAIZ / "painel" / "static" / "painel.css").read_text(encoding="utf-8")
    regra = re.search(r"\.menu-lista a\[href='/observatorio'\] \{([^}]+)\}", css)
    assert regra and "--menu-violeta-fundo" in regra.group(1)
    assert ".layout:has(.menu-lista a[href='/observatorio'][aria-current=\"page\"])" in css
