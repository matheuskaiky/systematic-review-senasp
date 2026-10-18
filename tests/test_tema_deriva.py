"""Teste anti-deriva do tema (colar em tests/). Garante que os quatro lugares de troca de tema continuam coerentes.
Ajuste CAMINHOS para os arquivos reais. Cobre o bloco de tokens de painel.css e o bloco forçado de analises.css."""
import pathlib
import re

RAIZ = pathlib.Path(__file__).resolve().parent.parent
CAMINHOS = {"painel": RAIZ / "painel/static/painel.css", "analises": RAIZ / "painel/static/analises.css"}


def _css(nome):
    texto = pathlib.Path(CAMINHOS[nome]).read_text(encoding="utf-8")
    return re.sub(r"/\*.*?\*/", "", texto, flags=re.S)  # comentários citam `:root {` e enganariam a busca


def _bloco(css, cabeca):
    """Texto entre as chaves do primeiro bloco que começa com `cabeca`."""
    i = css.index(cabeca)
    j = css.index("{", i)
    nivel, k = 1, j + 1
    while nivel:
        nivel += (css[k] == "{") - (css[k] == "}")
        k += 1
    return css[j + 1 : k - 1]


def _decls(bloco):
    return dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", bloco))


def _quatro(css, raiz_claro):
    claro = _decls(_bloco(css, raiz_claro))
    sistema = _decls(_bloco(_bloco(css, "@media (prefers-color-scheme: dark)"), ":root"))
    tela = _bloco(css, "@media screen")
    forcado_escuro = _decls(_bloco(tela, ':root[data-theme="dark"]'))
    forcado_claro = _decls(_bloco(tela, ':root[data-theme="light"]'))
    return claro, sistema, forcado_escuro, forcado_claro


def _confere(css, raiz_claro):
    claro, sistema, f_escuro, f_claro = _quatro(css, raiz_claro)
    # escuro escolhido no botão == escuro pedido pelo sistema (mesmos tokens, mesmos valores)
    assert {k: v.strip() for k, v in f_escuro.items() if k in sistema} == {k: v.strip() for k, v in sistema.items()}
    assert set(sistema) <= set(f_escuro)
    # claro escolhido no botão restaura exatamente os valores claros dos tokens que o escuro troca
    assert {k: v.strip() for k, v in f_claro.items()} == {k: claro[k].strip() for k in sistema if k in claro}


def test_painel_css_quatro_lugares_coerentes():
    _confere(_css("painel"), ":root {")


def test_analises_css_quatro_lugares_coerentes():
    css = _css("analises")
    _confere(css, ":root {")
