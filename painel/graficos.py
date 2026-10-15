"""Graficos em SVG gerados no servidor: funcoes puras que devolvem texto. Cores e fontes vem do CSS (classes)."""
from html import escape

from painel.mapa_ufs import POSICOES


def barras_horizontais(itens, titulo, descricao, formatar=str):
    """itens = [(rotulo, valor)]. Barra proporcional ao maior valor; o texto acompanha cada barra."""
    if not itens:
        return ""
    maximo = max((v or 0) for _, v in itens) or 1
    altura_linha, margem_esq, largura = 30, 175, 620
    h = altura_linha * len(itens) + 8
    partes = [f'<svg class="grafico" viewBox="0 0 {largura} {h}" role="img" aria-labelledby="gt gd">',
              f'<title id="gt">{escape(titulo)}</title><desc id="gd">{escape(descricao)}</desc>']
    for i, (rot, valor) in enumerate(itens):
        y = 4 + i * altura_linha
        w = max((valor or 0) / maximo * (largura - margem_esq - 70), 2 if valor else 0)
        partes.append(f'<text class="gr-rotulo" x="{margem_esq - 10}" y="{y + 19}" text-anchor="end">{escape(str(rot))}</text>'
                      f'<rect class="gr-barra" x="{margem_esq}" y="{y + 3}" width="{w:.1f}" height="21" rx="3">'
                      f'<title>{escape(str(rot))}: {escape(formatar(valor))}</title></rect>'
                      f'<text class="gr-valor" x="{margem_esq + w + 8:.1f}" y="{y + 19}">{escape(formatar(valor))}</text>')
    partes.append("</svg>")
    return "".join(partes)


def mapa_de_blocos(estados, titulo, descricao):
    """estados = {uf: (classe_css, texto_do_tooltip)}. Uma celula por UF, na posicao de `mapa_ufs.POSICOES`."""
    lado, folga = 56, 6
    colunas, linhas = max(c for c, _ in POSICOES.values()) + 1, max(l for _, l in POSICOES.values()) + 1
    partes = [f'<svg class="mapa" viewBox="0 0 {colunas * (lado + folga)} {linhas * (lado + folga)}" role="img" '
              f'aria-labelledby="mt md"><title id="mt">{escape(titulo)}</title><desc id="md">{escape(descricao)}</desc>']
    for uf, (col, lin) in POSICOES.items():
        classe, dica = estados.get(uf, ("sem-dados", "sem dados"))
        x, y = col * (lado + folga), lin * (lado + folga)
        partes.append(f'<a href="/estados/{uf}"><g class="bloco {escape(classe)}"><rect x="{x}" y="{y}" width="{lado}" '
                      f'height="{lado}" rx="8"/><text x="{x + lado / 2}" y="{y + lado / 2 + 6}" text-anchor="middle">{uf}</text>'
                      f'<title>{uf}: {escape(dica)}</title></g></a>')
    partes.append("</svg>")
    return "".join(partes)


def barra_empilhada(segmentos, total, descricao):
    """segmentos = [(valor, classe_css, rotulo)]. Uma barra horizontal; o que falta para `total` fica como fundo."""
    partes = [f'<svg class="barra-empilhada" viewBox="0 0 1000 20" preserveAspectRatio="none" role="img" '
              f'aria-label="{escape(descricao)}"><rect class="be-fundo" x="0" y="0" width="1000" height="20" rx="6"/>']
    x = 0.0
    for valor, classe, rotulo in segmentos:
        w = (valor / total * 1000) if total else 0
        if w > 0:
            partes.append(f'<rect class="{escape(classe)}" x="{x:.1f}" y="0" width="{w:.1f}" height="20"><title>{escape(rotulo)}: {valor}</title></rect>')
            x += w
    partes.append("</svg>")
    return "".join(partes)
