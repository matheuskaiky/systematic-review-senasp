"""Testes das fontes locais (colar em tests/). As fontes NÃO usam @font-face: o CSS só nomeia as famílias e painel.js as carrega pela API FontFace
(trecho static/painel_fontes_trecho.js). Assim nenhum teste do contrato precisa ser relaxado: painel.css continua sem `url(`, sem `@import` e sem `http`,
e as páginas continuam com um só <link>. Ajuste CAMINHOS se a árvore for diferente."""
import pathlib
import re

RAIZ = pathlib.Path(__file__).resolve().parent.parent
CAMINHOS = {"css": RAIZ / "painel/static/painel.css", "js": RAIZ / "painel/static/painel.js", "fontes": RAIZ / "painel/static/fonts", "templates": RAIZ / "painel/templates"}
LIMITE_BYTES = 150_000  # por arquivo; hoje: Inter ~48 KB e Source Serif 4 ~51 KB
ARQUIVOS = {"Inter": "inter-latin-wght-normal.woff2", "Source Serif 4": "source-serif-4-latin-wght-normal.woff2"}


def _ler(chave):
    return pathlib.Path(CAMINHOS[chave]).read_text(encoding="utf-8")


def test_css_continua_sem_funcao_de_endereco_e_sem_font_face():
    css = _ler("css")
    assert "url(" not in css.lower()
    assert "@font-face" not in css.lower()
    assert "@import" not in css and "http" not in css.lower()


def test_familias_nomeadas_no_css_batem_com_as_carregadas_no_js():
    css, js = _ler("css"), _ler("js")
    assert '--fonte-base: "Inter"' in css and '--fonte-leitura: "Source Serif 4"' in css
    for familia, arquivo in ARQUIVOS.items():
        assert f'nome: "{familia}"' in js and f"/static/fonts/{arquivo}" in js


def test_js_de_fontes_respeita_as_proibicoes_de_painel_js():
    js = _ler("js")
    for proibido in ("eval(", "innerHTML", "document.write", "XMLHttpRequest", "fetch(", "import(", "http://", "https://"):
        assert proibido not in js, proibido


def test_arquivos_de_fonte_existem_sao_woff2_e_leves():
    pasta = pathlib.Path(CAMINHOS["fontes"])
    for arquivo in ARQUIVOS.values():
        f = pasta / arquivo
        assert f.is_file(), f"fonte ausente: {f}"
        assert f.stat().st_size <= LIMITE_BYTES
        assert f.read_bytes()[:4] == b"wOF2"  # assinatura de woff2


def test_licencas_junto_dos_arquivos():
    nomes = {p.name for p in pathlib.Path(CAMINHOS["fontes"]).iterdir()}
    assert any(n.startswith("LICENSE-Inter") for n in nomes)
    assert any(n.startswith("LICENSE-SourceSerif4") for n in nomes)


def test_nenhum_template_carrega_fonte_por_link():
    for t in pathlib.Path(CAMINHOS["templates"]).glob("*.html"):
        texto = t.read_text(encoding="utf-8").lower()
        assert 'rel="preload"' not in texto and ".woff" not in texto, t.name
