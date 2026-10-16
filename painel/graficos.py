"""Graficos em SVG gerados no servidor: funcoes puras que devolvem texto. Cores e fontes vem do CSS (classes)."""
from html import escape

from painel import mapa_ufs


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


def mapa_do_brasil(estados, titulo, descricao):
    """estados = {uf: (classe_css, texto_do_tooltip)}. O contorno de cada UF vem de `mapa_ufs.CAMINHOS` (cada UF e um link para
    /estados/{uf}). O credito do mapa (`mapa_ufs.CREDITO`) deve aparecer junto, na pagina que o mostra."""
    partes = [f'<svg class="mapa" viewBox="{mapa_ufs.VIEWBOX}" role="img" aria-labelledby="mt md">'
              f'<title id="mt">{escape(titulo)}</title><desc id="md">{escape(descricao)}</desc>']
    for uf, caminho in mapa_ufs.CAMINHOS.items():
        classe, dica = estados.get(uf, ("sem-dados", "sem dados"))
        x, y, fonte, ancora, guia = mapa_ufs.ROTULOS[uf]
        linha = (f'<line class="bloco-guia" x1="{guia[0]}" y1="{guia[1]}" x2="{x - 2}" y2="{y}"/>' if guia else "")
        partes.append(f'<a href="/estados/{uf}"><g class="bloco {escape(classe)}"><path d="{caminho}"/>{linha}'
                      f'<text x="{x}" y="{y}" text-anchor="{ancora}" dominant-baseline="central" font-size="{fonte}">{uf}</text>'
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


def colunas(itens, titulo, descricao, rotulo_x="", rotulo_y=""):
    """itens = [(rotulo, valor)]: colunas verticais com o valor em cima de cada uma."""
    if not itens:
        return ""
    maximo = max((v or 0) for _, v in itens) or 1
    largura_col, folga, altura, margem_base, margem_topo, margem_esq = 46, 14, 180, 40, 22, 44
    larg = margem_esq + len(itens) * (largura_col + folga) + 10
    h = altura + margem_base + margem_topo
    partes = [f'<svg class="grafico" viewBox="0 0 {larg} {h}" role="img" aria-labelledby="ct cd"><title id="ct">{escape(titulo)}</title>'
              f'<desc id="cd">{escape(descricao)}</desc>',
              f'<text class="gr-eixo" x="12" y="{margem_topo + altura / 2}" transform="rotate(-90 12 {margem_topo + altura / 2})" text-anchor="middle">{escape(rotulo_y)}</text>']
    for i, (rot, valor) in enumerate(itens):
        x = margem_esq + i * (largura_col + folga)
        alt = (valor or 0) / maximo * altura
        y = margem_topo + altura - alt
        partes.append(f'<rect class="gr-barra" x="{x}" y="{y:.1f}" width="{largura_col}" height="{alt:.1f}" rx="3"><title>{escape(str(rot))}: {valor}</title></rect>'
                      f'<text class="gr-valor" x="{x + largura_col / 2}" y="{y - 5:.1f}" text-anchor="middle">{valor}</text>'
                      f'<text class="gr-rotulo" x="{x + largura_col / 2}" y="{margem_topo + altura + 18}" text-anchor="middle">{escape(str(rot))}</text>')
    partes.append(f'<text class="gr-eixo" x="{larg / 2}" y="{h - 4}" text-anchor="middle">{escape(rotulo_x)}</text></svg>')
    return "".join(partes)


def mapa_de_calor(rotulos, valores, titulo, descricao, dicas=None):
    """Matriz simetrica de contagens. `valores` = {(a, b): n} com a != b; a diagonal usa {(a, a): n}. Cinco niveis de cor por classe."""
    if not rotulos:
        return ""
    lado, margem = 17, 34
    maximo = max([v for (a, b), v in valores.items() if a != b] or [1]) or 1
    n = len(rotulos)
    tam = margem + n * lado + 4
    partes = [f'<svg class="calor" viewBox="0 0 {tam} {tam}" role="img" aria-labelledby="ht hd"><title id="ht">{escape(titulo)}</title><desc id="hd">{escape(descricao)}</desc>']
    for i, r in enumerate(rotulos):
        partes.append(f'<text class="gr-calor-rot" x="{margem - 4}" y="{margem + i * lado + 12}" text-anchor="end">{escape(r)}</text>'
                      f'<text class="gr-calor-rot" x="{margem + i * lado + lado / 2}" y="{margem - 6}" text-anchor="start" '
                      f'transform="rotate(-90 {margem + i * lado + lado / 2} {margem - 6})">{escape(r)}</text>')
    for i, a in enumerate(rotulos):
        for j, b in enumerate(rotulos):
            v = valores.get((a, b), valores.get((b, a), 0))
            if i == j:
                classe = "calor-diag"
            else:
                nivel = 0 if v == 0 else min(1 + int(4 * (v - 1) / max(maximo - 1, 1)), 4) if maximo > 1 else 4
                classe = f"calor-{nivel}"
            dica = f"{a} × {b}: {v}" if i != j else f"{a}: {v} artigos"
            if dicas and i == j and a in dicas:
                dica += f" ({dicas[a]})"
            partes.append(f'<rect class="{classe}" x="{margem + j * lado}" y="{margem + i * lado}" width="{lado - 1}" height="{lado - 1}"><title>{escape(dica)}</title></rect>')
    partes.append("</svg>")
    return "".join(partes)
