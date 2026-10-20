"""O primeiro <strong> de um aviso vira titulo em linha propria; quando ele comeca uma frase (um numero, um trecho seguido
de ':'), leva a classe em-linha e fica na mesma linha do resto do texto."""
import re
from pathlib import Path

import pytest

PAINEL = Path(__file__).resolve().parent.parent / "painel"
_AVISO = re.compile(r'<(\w+)[^>]*class="[^"]*\baviso\b[^"]*"[^>]*>\s*(?:\{%[^%]*%\}\s*)*<strong([^>]*)>(.*?)</strong>(.{0,30})', re.S)


def _avisos():
    for p in sorted((PAINEL / "templates").rglob("*.html")):
        texto = p.read_text(encoding="utf-8")
        for m in _AVISO.finditer(texto):
            yield f"{p.name}:{texto[:m.start()].count(chr(10)) + 1}", m.group(2), m.group(3).strip(), m.group(4).lstrip()


def test_css_so_poe_em_linha_propria_o_strong_que_nao_e_em_linha():
    css = (PAINEL / "static" / "painel.css").read_text(encoding="utf-8")
    assert ".aviso > strong:first-child:not(.em-linha) { display: block; margin-bottom: .1rem; }" in css
    assert ".aviso > strong:first-child {" not in css


def test_strong_de_abertura_e_titulo_ou_e_em_linha():
    """Titulo: termina em '.', ':' ou '?', ou vem antes de uma lista. Qualquer outro comeca uma frase e precisa de em-linha."""
    ruins = [onde for onde, atributos, texto, depois in _avisos()
             if 'class="em-linha"' not in atributos
             and not (texto.endswith((".", ":", "?")) or depois.startswith(("<ul", "<ol")))]
    assert ruins == []


@pytest.mark.parametrize("arquivo,trecho", [
    ("artigos.html", '<strong class="em-linha">{{ fmt.numero(res.ocultos_llm) }}</strong> artigo(s)'),
    ("literatura.html", '<strong class="em-linha">{{ fmt.numero(d.n_ocultos_llm) }}</strong> artigo(s)'),
    ("triagem_escopo.html", '<strong class="em-linha">{{ fmt.numero(res.ocultos) }}</strong> item(ns)'),
    ("metodologia.html", '<strong class="em-linha">Antes de usar este texto</strong>: {{ m.ressalvas|length }}'),
])
def test_os_quatro_avisos_que_comecam_frase(arquivo, trecho):
    assert trecho in (PAINEL / "templates" / arquivo).read_text(encoding="utf-8")


def test_os_titulos_continuam_sem_em_linha():
    titulos = {onde: atributos for onde, atributos, _, _ in _avisos()}
    em_linha = sorted(onde.split(":")[0] for onde, a in titulos.items() if 'class="em-linha"' in a)
    assert em_linha == ["artigos.html", "literatura.html", "metodologia.html", "triagem_escopo.html"]
