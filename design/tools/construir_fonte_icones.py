#!/usr/bin/env python3
"""Constrói static/fonts/observatorio-icones-v1.woff2 a partir dos SVG do Phosphor Icons (MIT) mais a marca própria.

Uso:  python3 construir_fonte_icones.py  <pasta assets do @phosphor-icons/core>  <lista.txt>  <saida.woff2>  <saida.json>

Cada ícone vira até três glifos (UPM 1024; o quadrado do SVG de 256 vale 1em):
  nome      contorno (peso "regular")
  nome.f    cheio ("fill")
  nome.d    camada de fundo do "duotone" (o contorno do duotone é igual ao regular, então não se repete)
A marca (mira de levantamento) é desenhada aqui mesmo, em duas camadas: marca (anel e quatro marcas) e marca.d (ponto central).
Código dos glifos: área de uso privado, a partir de U+E000, na ordem da lista. O JSON guarda o mapa nome -> códigos para gerar o CSS.
Requer: pip install fonttools brotli
"""
import json, math, re, sys
from pathlib import Path
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.svgLib.path import parse_path

UPM = 1024
ESCALA = UPM / 256.0


def caminhos(svg_texto):
    """Devolve (lista de d com opacity, lista de d sem opacity) do SVG."""
    fundo, frente = [], []
    for m in re.finditer(r"<path\b([^>]*)/?>", svg_texto):
        atrib = m.group(1)
        d = re.search(r'\bd="([^"]+)"', atrib).group(1)
        (fundo if "opacity=" in atrib else frente).append(d)
    return fundo, frente


def glifo(ds):
    pen = TTGlyphPen(None)
    tpen = TransformPen(Cu2QuPen(pen, 1.0, reverse_direction=False), (ESCALA, 0, 0, -ESCALA, 0, UPM))
    for d in ds:
        parse_path(d, tpen)
    return pen.glyph()


def vazio():
    return TTGlyphPen(None).glyph()


# ---------- marca própria: mira de levantamento (anel partido em quatro, quatro marcas e o ponto observado) ----------
def _p(cx, cy, r, a):
    return cx + r * math.cos(a), cy + r * math.sin(a)


def marca_camadas():
    cx = cy = 128.0
    r_ext, r_int = 100.0, 82.0
    meia_folga = math.radians(15)           # metade da folga em cada ponto cardeal
    d_anel = []
    for k in range(4):
        centro = math.radians(45 + 90 * k)
        a0, a1 = centro - (math.radians(45) - meia_folga), centro + (math.radians(45) - meia_folga)
        x0, y0 = _p(cx, cy, r_ext, a0); x1, y1 = _p(cx, cy, r_ext, a1)
        x2, y2 = _p(cx, cy, r_int, a1); x3, y3 = _p(cx, cy, r_int, a0)
        d_anel.append(f"M{x0:.2f},{y0:.2f}A{r_ext},{r_ext},0,0,1,{x1:.2f},{y1:.2f}L{x2:.2f},{y2:.2f}A{r_int},{r_int},0,0,0,{x3:.2f},{y3:.2f}Z")
    d_marcas = []
    for k in range(4):
        a = math.radians(90 * k)
        pts = []
        for r, lado in ((56, -9), (120, -9), (120, 9), (56, 9)):
            x = cx + r * math.cos(a) - lado * math.sin(a)
            y = cy + r * math.sin(a) + lado * math.cos(a)
            pts.append((x, y))
        d_marcas.append("M" + "L".join(f"{x:.2f},{y:.2f}" for x, y in pts) + "Z")
    d_ponto = f"M{cx - 22},{cy}A22,22,0,1,1,{cx + 22},{cy}A22,22,0,1,1,{cx - 22},{cy}Z"
    return d_anel + d_marcas, [d_ponto]


def principal(pasta_assets, lista, saida_woff2, saida_json):
    base = Path(pasta_assets)
    nomes = [n for l in Path(lista).read_text(encoding="utf-8").splitlines() if l.strip() and not l.lstrip().startswith("#") for n in l.split()]
    ordem, glifos, cmap, mapa = [".notdef"], {".notdef": vazio()}, {}, {}
    proximo = 0xE000

    def adicionar(nome_glifo, g):
        nonlocal proximo
        ordem.append(nome_glifo); glifos[nome_glifo] = g
        cmap[proximo] = nome_glifo
        proximo += 1
        return proximo - 1

    # marca primeiro (códigos fixos: e000 anel/marcas, e001 ponto)
    frente, fundo = marca_camadas()
    cod = {"r": adicionar("marca", glifo(frente)), "d": adicionar("marca.d", glifo(fundo))}
    mapa["marca"] = {k: f"{v:04x}" for k, v in cod.items()}

    for nome in nomes:
        reg = base / "regular" / f"{nome}.svg"
        cheio = base / "fill" / f"{nome}-fill.svg"
        duo = base / "duotone" / f"{nome}-duotone.svg"
        if not (reg.exists() and cheio.exists() and duo.exists()):
            sys.exit(f"ícone ausente no Phosphor: {nome}")
        _, f_reg = caminhos(reg.read_text())
        _, f_cheio = caminhos(cheio.read_text())
        f_fundo, _ = caminhos(duo.read_text())
        entrada = {"r": adicionar(nome, glifo(f_reg)), "f": adicionar(nome + ".f", glifo(f_cheio))}
        if f_fundo:
            entrada["d"] = adicionar(nome + ".d", glifo(f_fundo))
        mapa[nome] = {k: f"{v:04x}" for k, v in entrada.items()}

    fb = FontBuilder(UPM, isTTF=True)
    fb.setupGlyphOrder(ordem)
    fb.setupCharacterMap(cmap)
    fb.setupGlyf(glifos)
    fb.setupHorizontalMetrics({g: (UPM, 0) for g in ordem})
    fb.setupHorizontalHeader(ascent=UPM, descent=0, lineGap=0)
    fb.setupNameTable({"familyName": "Observatorio Icones", "styleName": "Regular", "uniqueFontIdentifier": "Observatorio Icones v1",
                       "fullName": "Observatorio Icones Regular", "psName": "ObservatorioIcones-Regular", "version": "Version 1.0",
                       "licenseDescription": "Glifos derivados do Phosphor Icons (MIT, Copyright 2023 Phosphor Icons). Marca propria do projeto."})
    fb.setupOS2(sTypoAscender=UPM, sTypoDescender=0, sTypoLineGap=0, usWinAscent=UPM, usWinDescent=0, fsType=0, fsSelection=0x80 | 0x40)
    fb.font["OS/2"].version = 4   # fsSelection com os bits 6 e 7 só vale na versão 4 da tabela
    fb.setupPost(isFixedPitch=1)
    fb.font.flavor = "woff2"
    fb.save(saida_woff2)
    Path(saida_json).write_text(json.dumps(mapa, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(nomes)} ícones + marca, {len(ordem) - 1} glifos, {Path(saida_woff2).stat().st_size} bytes")


if __name__ == "__main__":
    if len(sys.argv) != 5:
        sys.exit(__doc__)
    principal(*sys.argv[1:])
