"""Corrige o recuo esquerdo (lsb) de cada glifo de uma fonte de ícones já construída: lsb = início real do desenho (xMin).

Por que existe: a v1 da fonte gravou lsb 0 em todos os glifos, mas o desenho do Phosphor começa depois da margem interna
(xMin > 0). O navegador posiciona o contorno de modo que xMin caia no lsb, então cada ícone saía deslocado para a esquerda
pela própria margem (até 12 px na marca, cerca de 2,6 px nos títulos). O construtor (`construir_fonte_icones.py`) já grava o
lsb certo; este script refaz a fonte publicada sem precisar dos SVG originais do Phosphor, que não ficam no repositório.

Uso:  python3 corrigir_recuo_fonte.py  <entrada.woff2>  <saida.woff2>
"""
import sys

from fontTools.ttLib import TTFont

VERSAO = "2"


def corrigir(entrada, saida):
    fonte = TTFont(entrada, recalcTimestamp=False)   # mantem a data interna da entrada: a mesma entrada gera os mesmos bytes
    glyf, hmtx = fonte["glyf"], fonte["hmtx"]
    for nome in fonte.getGlyphOrder():
        glifo = glyf[nome]
        avanco, _ = hmtx[nome]
        hmtx[nome] = (avanco, glifo.xMin if glifo.numberOfContours else 0)
    for registro in fonte["name"].names:
        if registro.nameID == 3:
            registro.string = f"Observatorio Icones v{VERSAO}"
        elif registro.nameID == 5:
            registro.string = f"Version {VERSAO}.0"
    fonte.flavor = "woff2"
    fonte.save(saida)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("Uso: python3 corrigir_recuo_fonte.py <entrada.woff2> <saida.woff2>")
    corrigir(sys.argv[1], sys.argv[2])
