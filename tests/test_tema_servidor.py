"""RB15 (D75): o servidor do tema claro/escuro (cookie `tema`), o cache das fontes locais e o relatorio estatico com o CSS novo."""
import re
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from painel.relatorio import _sem_tema_escuro
from test_painel import _app, demo  # noqa: F401

ESTATICOS = Path(__file__).resolve().parent.parent / "painel" / "static"
FONTE = "fonts/inter-latin-wght-normal.woff2"


@pytest.fixture
def cli(demo, tmp_path):
    banco, raw = demo
    copia = tmp_path / "demo.db"
    shutil.copy(banco, copia)
    app, _ = _app(copia, raw, tmp_path)
    return TestClient(app)


def _html_tag(cli, cookie):
    h = cli.get("/", headers={"Cookie": cookie} if cookie is not None else {}).text
    return re.search(r"<html[^>]*>", h).group(0), re.search(r'aria-pressed="(true|false)"', h).group(1)


# Hipoteses de operacao: o cookie `tema` so e escrito pelo painel.js com "light" ou "dark"; o Starlette tira aspas e espacos
# das pontas e, com o cookie repetido, vale o ultimo; qualquer outro valor significa "seguir o sistema" (sem data-theme), nunca erro.
@pytest.mark.parametrize("cookie,tema", [
    (None, None), ("tema=dark", "dark"), ("tema=light", "light"), ("tema=DARK", None), ('tema="dark"', "dark"),
    ("tema= dark", "dark"), ("tema=dark%20", None), ("tema=<script>", None), ("tema=" + "x" * 8000, None),
    ("tema=dark; tema=light", "light"), ("tema=light; tema=dark", "dark"), ("tema=dark;tema=", None), ("tema", None)])
def test_cookie_de_tema(cli, cookie, tema):
    tag, pressionado = _html_tag(cli, cookie)
    if tema is None:
        assert "data-theme" not in tag
    else:
        assert f'data-theme="{tema}"' in tag
    assert pressionado == ("true" if tema == "dark" else "false")


def test_botao_de_tema_e_o_ultimo_item_do_banner_fora_do_menu(cli):
    """D81: o botao de tema fica no fim do banner (desenho Observatorio), sem a faixa .topo."""
    h = cli.get("/").text
    banner = re.search(r'<header class="banner[^"]*" role="banner">.*?</header>', h, flags=re.S).group(0)
    assert re.search(r'<button type="button" class="tema-alternar" data-tema-alternar[^>]*>.*?</button>\s*</header>$', banner, flags=re.S)
    assert '<div class="topo">' not in h and h.index("</header>") < h.index('<div class="layout">')
    nav = h[h.index("<nav"):h.index("</nav>")]
    assert "tema-alternar" not in nav


@pytest.mark.parametrize("metodo", ["GET", "HEAD"])
def test_fonte_com_cache_de_um_ano_e_tipo_certo(cli, metodo):
    r = cli.request(metodo, "/static/" + FONTE)
    assert r.status_code == 200 and r.headers["content-type"] == "font/woff2"
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"


@pytest.mark.parametrize("caminho", ["/static/painel.css", "/static/painel.js", "/static/fonts/../painel.css"])
def test_css_e_js_sem_cache_longo(cli, caminho):
    r = cli.get(caminho)
    assert r.status_code == 200 and "immutable" not in r.headers.get("cache-control", "")


def test_vary_cookie_so_nas_paginas(cli):
    assert "Cookie" in cli.get("/").headers.get("vary", "")
    for caminho in ("/static/painel.css", "/static/" + FONTE):
        assert "Cookie" not in cli.get(caminho).headers.get("vary", "")


@pytest.mark.parametrize("folha", ["painel.css", "metodologia.css", "analises.css"])
def test_relatorio_tira_so_o_bloco_escuro_mesmo_com_comentarios(folha):
    """Comentarios nao podem confundir a remocao do tema escuro do relatorio estatico."""
    css = (ESTATICOS / folha).read_text(encoding="utf-8")
    sem_comentarios = lambda t: re.sub(r"/\*.*?\*/", "", t, flags=re.S)
    assert sem_comentarios(_sem_tema_escuro(css)) == _sem_tema_escuro(sem_comentarios(css))
    assert not any("prefers-color-scheme" in c or "@media print {" in c for c in re.findall(r"/\*.*?\*/", css, flags=re.S))


def test_relatorio_mantem_os_tokens_claros():
    css = (ESTATICOS / "painel.css").read_text(encoding="utf-8")
    r = _sem_tema_escuro(css)
    assert "--tinta-50:" in r and "--esp-1:" in r and "--fonte-base:" in r      # D81: primitivo claro do desenho Observatorio
    assert css.count("@media (prefers-color-scheme: dark)") == 1
