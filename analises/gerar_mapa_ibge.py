"""Gera `painel/mapa_ufs.py` (contorno das 27 UFs e ponto do rotulo de cada uma) a partir da malha oficial do IBGE.

Uso (so a biblioteca padrao; o painel nao importa este arquivo e os testes nao o executam):

    python analises/gerar_mapa_ibge.py --baixar RAIZ/ibge_uf_minima.geojson     # baixa (GET, gratis) e gera
    python analises/gerar_mapa_ibge.py --geojson RAIZ/ibge_uf_minima.geojson     # gera de um arquivo ja baixado

Fonte (API de malhas do IBGE, versao 3, documentada em https://servicodados.ibge.gov.br/api/docs/malhas):
    https://servicodados.ibge.gov.br/api/v3/malhas/paises/BR?formato=application/vnd.geo+json&qualidade=minima&intrarregiao=UF
Cada feicao traz `properties.codarea` com o codigo IBGE da UF (11 RO ... 53 DF).

Passos (todos deterministicos, os mesmos dados dao o mesmo arquivo):
  1. Projecao: Albers de area igual, conica, esferica (raio 6.371 km), com os parametros usuais para o Brasil: paralelos padrao
     -2 e -22, latitude de origem -12, meridiano central -54. Implementada com `math`.
  2. Ajuste: o maior lado do Brasil vira 700 unidades; o canto superior esquerdo fica em (0, 0); o eixo y cresce para baixo.
  3. Simplificacao: Douglas-Peucker por anel, tolerancia de TOLERANCIA unidades. Aneis com area menor que AREA_MINIMA (ilhotas
     que nao se enxergam) sao descartados, exceto o maior anel de cada UF. A malha de qualidade minima nao traz ilhas oceanicas
     (Fernando de Noronha nao esta nela), e elas ficam fora do desenho.
  4. Coordenadas com uma casa decimal.
  5. Rotulo: centroide do maior poligono; se cair fora do poligono ou perto demais da borda, usa-se o ponto interno mais
     afastado da borda (busca em grade). UFs pequenas (UFS_NO_MAR) levam o rotulo para o mar, em coluna, com linha-guia."""
import argparse
import json
import math
import sys
import urllib.request
from datetime import date
from pathlib import Path

URL = ("https://servicodados.ibge.gov.br/api/v3/malhas/paises/BR"
       "?formato=application/vnd.geo+json&qualidade=minima&intrarregiao=UF")
CODIGOS = {"11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO", "21": "MA", "22": "PI",
           "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL", "28": "SE", "29": "BA", "31": "MG", "32": "ES",
           "33": "RJ", "35": "SP", "41": "PR", "42": "SC", "43": "RS", "50": "MS", "51": "MT", "52": "GO", "53": "DF"}
LADO = 700.0
TOLERANCIA = 0.45
AREA_MINIMA = 6.0
FONTE_GRANDE, FONTE_MAR, FONTE_DF = 22.5, 17, 11
UFS_NO_MAR = ("RN", "PB", "PE", "AL", "SE", "ES")
ESPACO_MAR = 26.0          # distancia vertical minima entre rotulos da coluna do mar
SAIDA = Path(__file__).resolve().parent.parent / "painel" / "mapa_ufs.py"


def albers(lon, lat, lat1=-2.0, lat2=-22.0, lat0=-12.0, lon0=-54.0, raio=6371.0):
    """Albers conica de area igual, esferica. Devolve (x, y) em km."""
    r = math.radians
    n = (math.sin(r(lat1)) + math.sin(r(lat2))) / 2
    c = math.cos(r(lat1)) ** 2 + 2 * n * math.sin(r(lat1))
    rho0 = raio * math.sqrt(c - 2 * n * math.sin(r(lat0))) / n
    rho = raio * math.sqrt(c - 2 * n * math.sin(r(lat))) / n
    teta = n * r(lon - lon0)
    return rho * math.sin(teta), rho0 - rho * math.cos(teta)


def _distancia_ao_segmento(p, a, b):
    ax, ay = a
    dx, dy = b[0] - ax, b[1] - ay
    t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(p[0] - ax - t * dx, p[1] - ay - t * dy)


def douglas_peucker(pontos, tol):
    """Simplifica uma linha aberta (lista de (x, y)); mantem os extremos."""
    if len(pontos) < 3:
        return list(pontos)
    manter = {0, len(pontos) - 1}
    pilha = [(0, len(pontos) - 1)]
    while pilha:
        i, j = pilha.pop()
        melhor, k = -1.0, None
        for m in range(i + 1, j):
            d = _distancia_ao_segmento(pontos[m], pontos[i], pontos[j])
            if d > melhor:
                melhor, k = d, m
        if k is not None and melhor > tol:
            manter.add(k)
            pilha += [(i, k), (k, j)]
    return [pontos[i] for i in sorted(manter)]


def simplificar_anel(anel, tol):
    """Anel fechado (o primeiro ponto nao se repete no fim): divide no ponto mais distante do primeiro e simplifica as duas metades."""
    if len(anel) < 4:
        return list(anel)
    k = max(range(len(anel)), key=lambda i: math.hypot(anel[i][0] - anel[0][0], anel[i][1] - anel[0][1]))
    a = douglas_peucker(anel[:k + 1], tol)
    b = douglas_peucker(anel[k:] + [anel[0]], tol)
    return a[:-1] + b[:-1]


def area_assinada(anel):
    return sum(anel[i][0] * anel[(i + 1) % len(anel)][1] - anel[(i + 1) % len(anel)][0] * anel[i][1] for i in range(len(anel))) / 2


def centroide(anel):
    a = area_assinada(anel)
    cx = cy = 0.0
    for i in range(len(anel)):
        x0, y0, x1, y1 = *anel[i], *anel[(i + 1) % len(anel)]
        w = x0 * y1 - x1 * y0
        cx += (x0 + x1) * w
        cy += (y0 + y1) * w
    return cx / (6 * a), cy / (6 * a)


def dentro(p, anel):
    x, y, ok = p[0], p[1], False
    for i in range(len(anel)):
        (x0, y0), (x1, y1) = anel[i], anel[(i + 1) % len(anel)]
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
            ok = not ok
    return ok


def folga(p, anel):
    """Distancia do ponto a borda do anel (positiva dentro, negativa fora)."""
    d = min(_distancia_ao_segmento(p, anel[i], anel[(i + 1) % len(anel)]) for i in range(len(anel)))
    return d if dentro(p, anel) else -d


def ponto_interno(anel, passo=1.0):
    xs, ys = [p[0] for p in anel], [p[1] for p in anel]
    melhor, ponto = -1e9, None
    y = min(ys)
    while y <= max(ys):
        x = min(xs)
        while x <= max(xs):
            f = folga((x, y), anel)
            if f > melhor:
                melhor, ponto = f, (x, y)
            x += passo
        y += passo
    return ponto


def ler_ufs(geojson):
    """{uf: [aneis externos em (lon, lat)]}"""
    ufs = {}
    for f in geojson["features"]:
        uf = CODIGOS[f["properties"]["codarea"]]
        g = f["geometry"]
        poligonos = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        ufs[uf] = [[tuple(p) for p in pol[0]] for pol in poligonos]
    if set(ufs) != set(CODIGOS.values()):
        raise SystemExit("A malha nao traz exatamente as 27 UFs.")
    return ufs


def projetar(ufs):
    """Projeta e ajusta ao quadrado de LADO unidades. Devolve {uf: [aneis (x, y)]}."""
    proj = {uf: [[albers(lon, lat) for lon, lat in anel] for anel in aneis] for uf, aneis in ufs.items()}
    todos = [p for aneis in proj.values() for anel in aneis for p in anel]
    x0, x1 = min(p[0] for p in todos), max(p[0] for p in todos)
    y0, y1 = min(p[1] for p in todos), max(p[1] for p in todos)
    k = LADO / max(x1 - x0, y1 - y0)
    return {uf: [[((x - x0) * k, (y1 - y) * k) for x, y in anel[:-1]] for anel in aneis] for uf, aneis in proj.items()}


def montar(ufs):
    """Devolve (caminhos, rotulos) a partir de {uf: [aneis (x, y)]}."""
    caminhos, rotulos, grandes = {}, {}, {}
    for uf, aneis in sorted(ufs.items()):
        maior = max(aneis, key=lambda a: abs(area_assinada(a)))
        mantidos = [simplificar_anel(a, TOLERANCIA) for a in aneis if a is maior or abs(area_assinada(a)) >= AREA_MINIMA]
        mantidos = [a for a in mantidos if len(a) >= 3]
        caminhos[uf] = " ".join("M" + " ".join(f"{x:.1f},{y:.1f}" for x, y in a) + " Z" for a in mantidos)
        grande = max(mantidos, key=lambda a: abs(area_assinada(a)))
        grandes[uf] = grande
        c = centroide(grande)
        if folga(c, grande) < 7:
            c = ponto_interno(grande)
        rotulos[uf] = c
    # rotulos no mar: coluna a direita do desenho, em ordem de latitude, sem se sobrepor
    saida = {}
    xmar = LADO + 16
    sobe = sorted(UFS_NO_MAR, key=lambda u: rotulos[u][1])
    guias = {}
    for uf in sobe:
        leste = max(grandes[uf], key=lambda p: p[0])
        guias[uf] = (leste[0] - 3, leste[1])
    ys, ultimo = {}, -1e9
    coluna = [u for u in sobe if u != "ES"]            # o ES fica sozinho, na altura da propria costa
    for uf in coluna:
        ys[uf] = max(guias[uf][1], ultimo + ESPACO_MAR)
        ultimo = ys[uf]
    deslocamento = sum(guias[u][1] - ys[u] for u in coluna) / len(coluna)      # centra a coluna em torno das linhas-guia
    ys = {u: y + deslocamento for u, y in ys.items()}
    ys["ES"] = guias["ES"][1]
    for uf in sorted(ufs):
        if uf in UFS_NO_MAR:
            x = xmar if uf != "ES" else max(p[0] for p in grandes[uf]) + 40
            saida[uf] = (round(x, 1), round(ys[uf], 1), FONTE_MAR, "start", (round(guias[uf][0], 1), round(guias[uf][1], 1)))
        else:
            x, y = rotulos[uf]
            saida[uf] = (round(x, 1), round(y, 1), FONTE_DF if uf == "DF" else FONTE_GRANDE, "middle", None)
    return caminhos, saida


def escrever(caminhos, rotulos, destino, baixado_em):
    linhas = ['"""Mapa do Brasil por UF: o contorno de cada estado e onde fica o rotulo.',
              "",
              "GERADO por `analises/gerar_mapa_ibge.py` a partir da malha territorial oficial do IBGE (API de malhas, versao 3),",
              f"baixada em {baixado_em} de:",
              f"{URL}",
              f"Projecao Albers de area igual (paralelos -2 e -22, origem -12, meridiano central -54), maior lado = {LADO:.0f}.",
              f"Douglas-Peucker com tolerancia {TOLERANCIA}; aneis menores que {AREA_MINIMA} unidades quadradas descartados;",
              "uma casa decimal. A malha de qualidade minima nao inclui ilhas oceanicas. Ficam guardados so o caminho (`d`) de",
              "cada UF e o ponto do rotulo. Nada e baixado em tempo de execucao: o painel nao carrega nada de fora (politica",
              "de seguranca do navegador).",
              "",
              "CREDITO (aparece junto de todo mapa): Fonte: IBGE. O IBGE avisa, nas notas das suas malhas, que os limites sao",
              "aproximados e nao constituem a divisao politico-administrativa oficial; o desenho aqui e simplificado e serve",
              'para ilustrar, nao para medir."""',
              "",
              f'FONTE = "{URL}"',
              'CREDITO = "Fonte: IBGE, malha territorial (desenho simplificado, limites aproximados)."',
              'VIEWBOX = "-10 -10 780 720"',
              "",
              "# uf -> caminho SVG (coordenadas absolutas)",
              "CAMINHOS = {"]
    linhas += [f'    "{uf}": "{c}",' for uf, c in sorted(caminhos.items())]
    linhas += ["}", "",
               "# uf -> (x, y, tamanho da fonte, ancora do texto, ponto da linha-guia ou None)",
               "ROTULOS = {"]
    linhas += [f'    "{uf}": {r!r},'.replace("'", '"') for uf, r in sorted(rotulos.items())]
    linhas += ["}", ""]
    Path(destino).write_text("\n".join(linhas), encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--baixar", metavar="ARQUIVO", help="baixa a malha (GET) para ARQUIVO e gera o mapa")
    g.add_argument("--geojson", metavar="ARQUIVO", help="usa um GeoJSON ja baixado")
    ap.add_argument("--saida", default=str(SAIDA))
    a = ap.parse_args(argv)
    if a.baixar:
        with urllib.request.urlopen(URL, timeout=120) as r:
            Path(a.baixar).write_bytes(r.read())
        origem = a.baixar
    else:
        origem = a.geojson
    baixado_em = date.fromtimestamp(Path(origem).stat().st_mtime).strftime("%d/%m/%Y")
    caminhos, rotulos = montar(projetar(ler_ufs(json.loads(Path(origem).read_text(encoding="utf-8")))))
    escrever(caminhos, rotulos, a.saida, baixado_em)
    print(f"escrito {a.saida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
