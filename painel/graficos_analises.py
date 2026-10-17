"""Gráficos da página /analises em SVG gerado no servidor: funções puras que recebem dados simples e devolvem texto.

Regras de todos os geradores (as mesmas de `painel/graficos.py`, mais as da política de segurança do painel):
- nada de `style=`, de script ou de `on*=`: cores, padrões e fontes vêm de `static/analises.css` (só classes);
- todo SVG tem `role="img"`, `<title>` e `<desc>`; os ids são derivados de um hash dos argumentos, então a saída é
  determinística e dois gráficos diferentes na mesma página não repetem ids;
- cor nunca é a única pista: há padrões de preenchimento (`<pattern>` dentro do próprio SVG) e glifos/textos;
- todo texto passa por `html.escape`; `href` só é aceito se for caminho relativo começando com "/" (senão é descartado);
- dados vazios ou nulos nunca levantam erro: a função devolve `<p class="vazio an-vazio">...</p>` (sem `<svg>`).

Sem sqlite3, sem adaptadores, sem config: a camada de dados da página entrega os números prontos.
"""
import hashlib
import math
from collections.abc import Mapping
from html import escape

from dominio.concordancia import interpretar_kappa
from painel import formatacao as fmt, rotulos

# ============================== utilidades comuns ==============================


def _t(x):
    """Texto seguro para HTML/atributos."""
    return escape("" if x is None else str(x), quote=True)


def _num(v, padrao=None):
    """float finito ou `padrao` (nunca levanta)."""
    if isinstance(v, bool):
        return padrao
    try:
        x = float(v)
    except (TypeError, ValueError):
        return padrao
    return x if math.isfinite(x) else padrao


def _pos(v):
    """float finito >= 0 (None, texto e negativos viram 0)."""
    x = _num(v, 0.0)
    return x if x > 0 else 0.0


def _f(x):
    """Coordenada compacta: uma casa decimal, sem '.0' e sem '-0'."""
    if abs(x) < 0.05:
        return "0"
    s = f"{x:.1f}"
    return s[:-2] if s.endswith(".0") else s


def _cortar(texto, n):
    s = "" if texto is None else str(texto)
    return s if len(s) <= n else s[:max(n - 1, 1)].rstrip() + "…"


def _quebrar(texto, largura, max_linhas=2):
    """Quebra em até `max_linhas` linhas de `largura` caracteres; o excesso vira reticências."""
    linhas, atual = [], ""
    for palavra in ("" if texto is None else str(texto)).split():
        if atual and len(atual) + 1 + len(palavra) > largura:
            linhas.append(atual)
            atual = palavra
        else:
            atual = f"{atual} {palavra}".strip()
    if atual:
        linhas.append(atual)
    if len(linhas) > max_linhas:
        linhas = linhas[:max_linhas]
        linhas[-1] = _cortar(linhas[-1] + "…", largura)
    return [_cortar(linha, largura) for linha in linhas]


def _href_seguro(href):
    """Só caminhos relativos do próprio painel ("/achados?uf=SP"). Esquemas, `//host`, barra invertida e espaços caem."""
    if not isinstance(href, str):
        return None
    h = href.strip()
    if not h.startswith("/") or h.startswith("//") or "\\" in h:
        return None
    if any(ord(c) < 33 or ord(c) == 127 for c in h):
        return None
    return h


def _link(href, rotulo, conteudo):
    """Envolve `conteudo` (SVG) em `<a>` quando o href é seguro; senão devolve o conteúdo sem link."""
    h = _href_seguro(href)
    if not h:
        return conteudo
    return f'<a class="an-link" href="{_t(h)}" aria-label="{_t(rotulo)} (ver os registros)">{conteudo}</a>'


def _uid(*partes):
    return hashlib.sha1(repr(partes).encode("utf-8")).hexdigest()[:8]


def _vazio(mensagem="Sem dados para exibir."):
    return f'<p class="vazio an-vazio">{_t(mensagem)}</p>'


def _svg(classe, largura, altura, titulo, descricao, corpo, uid, defs=""):
    titulo = titulo or "Gráfico"
    descricao = descricao or titulo
    return (f'<svg class="an-svg {classe}" viewBox="0 0 {_f(largura)} {_f(altura)}" role="img" '
            f'aria-labelledby="at-{uid} ad-{uid}"><title id="at-{uid}">{_t(titulo)}</title>'
            f'<desc id="ad-{uid}">{_t(descricao)}</desc>{defs}{corpo}</svg>')


def _norm(itens):
    """Normaliza linhas/colunas: str, (chave, rotulo[, grupo]) ou {"chave", "rotulo", "grupo"} -> lista de dicts."""
    saida = []
    for it in itens or []:
        if isinstance(it, Mapping):
            chave = it.get("chave", it.get("rotulo"))
            rotulo, grupo = it.get("rotulo", chave), it.get("grupo")
        elif isinstance(it, (tuple, list)) and it:
            chave = it[0]
            rotulo = it[1] if len(it) > 1 else chave
            grupo = it[2] if len(it) > 2 else None
        else:
            chave = rotulo = it
            grupo = None
        saida.append({"chave": chave, "rotulo": "" if rotulo is None else str(rotulo), "grupo": grupo})
    return saida


def _escala(d0, d1, r0, r1):
    span = (d1 - d0) or 1.0
    return lambda v: r0 + (v - d0) / span * (r1 - r0)


def _ticks(minimo, maximo, alvo=5):
    """Valores 'redondos' (1, 2, 2,5, 5 x 10^k) entre minimo e maximo; devolve (valores, passo)."""
    if maximo <= minimo:
        maximo = minimo + 1
    bruto = (maximo - minimo) / max(alvo, 1)
    base = 10 ** math.floor(math.log10(bruto))
    passo = base
    for m in (1, 2, 2.5, 5, 10):
        passo = m * base
        if passo >= bruto:
            break
    v = math.ceil(minimo / passo - 1e-9) * passo
    valores = []
    while v <= maximo + passo * 1e-9 and len(valores) < 60:
        valores.append(round(v, 10))
        v += passo
    return valores, passo


def _rot_tick(v, passo):
    if abs(v - round(v)) < 1e-9 and passo >= 1:
        return fmt.numero(round(v))
    casas = max(1, -math.floor(math.log10(passo) + 1e-9)) if passo < 1 else 1
    return fmt.decimal(v, casas)


def _topo_y(maximo):
    """Maior valor 'redondo' que contém `maximo` (para o eixo y começar em 0)."""
    if maximo <= 0:
        return 1.0, [0.0, 1.0], 1.0
    valores, passo = _ticks(0, maximo)
    topo = math.ceil(maximo / passo - 1e-9) * passo
    valores, passo = _ticks(0, topo)
    return topo, valores, passo


def _pct_txt(taxa):
    """0,004 -> '0,4%'; 0,02 -> '2%'; 0,35 -> '35%' (taxa em fração)."""
    v = 100 * taxa
    s = f"{v:.0f}" if v >= 10 else f"{v:.2f}".rstrip("0").rstrip(".")
    return s.replace(".", ",") + "%"


def _pct_inteiro(parte, total):
    return "—" if not total else f"{100 * parte / total:.0f}%"


# ---------- padrões de preenchimento (definidos dentro de cada SVG; as cores vêm de classes `an-bg-*` / `an-ln-*`) ----------

_TIPOS = {
    "solido": (1, None, ""),
    "diag": (6, "M-1 1 L1 -1 M0 6 L6 0 M5 7 L7 5", ' stroke-width="1.3"'),
    "diag2": (6, "M-1 5 L1 7 M0 0 L6 6 M5 -1 L7 1", ' stroke-width="1.3"'),
    "pontos": (6, "M3 3 h.01", ' stroke-width="2.2" stroke-linecap="round"'),
    "horiz": (5, "M0 2.5 H5", ' stroke-width="1.2"'),
    "vert": (5, "M2.5 0 V5", ' stroke-width="1.2"'),
    "xadrez": (6, "M0 0 L6 6 M6 0 L0 6", ' stroke-width="1.1"'),
}
# séries categóricas: cor (s0..s7 em analises.css) + padrão, para o gráfico funcionar em escala de cinza
_SERIES = [("s0", "solido"), ("s1", "diag"), ("s2", "pontos"), ("s3", "horiz"), ("s4", "diag2"), ("s5", "vert"),
           ("s6", "xadrez"), ("s7", "solido")]


def _serie(i):
    return _SERIES[i % len(_SERIES)]


def _defs(uid, padroes=(), glifos=()):
    """`padroes` = [(variante, tipo)]; `glifos` = [status]. Devolve o `<defs>` (ou "" se vazio)."""
    itens, vistos = [], set()
    for variante, tipo in padroes:
        if variante in vistos:
            continue
        vistos.add(variante)
        tam, d, extra = _TIPOS[tipo]
        traco = f'<path class="an-ln an-ln-{variante}" d="{d}" fill="none"{extra}/>' if d else ""
        itens.append(f'<pattern id="pt-{uid}-{variante}" width="{tam}" height="{tam}" patternUnits="userSpaceOnUse">'
                     f'<rect class="an-bg an-bg-{variante}" width="{tam}" height="{tam}"/>{traco}</pattern>')
    for status in glifos:
        itens.append(f'<symbol id="gl-{uid}-{status}" viewBox="0 0 12 12" stroke-width="1.4" stroke-linecap="round" '
                     f'stroke-linejoin="round">{_GLIFOS[status]}</symbol>')
    return f"<defs>{''.join(itens)}</defs>" if itens else ""


def _fill(uid, variante):
    return f"url(#pt-{uid}-{variante})"


# ---------- estágios de adoção (seção 2.1 do plano) ----------

STATUS_ORDEM = ["em_uso", "piloto", "licitacao", "anunciado", "em_estudo", "apenas_citado", "descartado"]
_PESO = {"em_uso": 5, "piloto": 4, "licitacao": 3, "anunciado": 2, "em_estudo": 1, "apenas_citado": 0}
_STATUS_CURTO = {"em_uso": "Em uso", "piloto": "Piloto", "licitacao": "Licitação", "anunciado": "Anunciado",
                 "em_estudo": "Em estudo", "apenas_citado": "Citado", "descartado": "Descartado"}
_STATUS_LEGENDA = {"em_uso": "Em uso operacional", "piloto": "Projeto piloto", "licitacao": "Licitação/contrato",
                   "anunciado": "Anunciado", "em_estudo": "Em estudo", "apenas_citado": "Apenas citado",
                   "descartado": "Descartado"}
_STATUS_PADRAO = {"em_uso": "solido", "piloto": "diag", "licitacao": "xadrez", "anunciado": "pontos",
                  "em_estudo": "horiz", "apenas_citado": "solido", "descartado": "diag2"}
# glifos de 12x12 (escudo, frasco, documento, megafone, lupa, traço tracejado, X)
_GLIFOS = {
    "em_uso": '<path d="M6 .8 L11 2.6 V6 C11 8.8 8.6 10.7 6 11.5 C3.4 10.7 1 8.8 1 6 V2.6 Z"/>',
    "piloto": '<path d="M4.4 1 H7.6 M5 1 V4.6 L1.8 10.6 H10.2 L7 4.6 V1"/>',
    "licitacao": '<path d="M2.5 1 H7.4 L9.5 3.1 V11 H2.5 Z M4.2 6 H7.8 M4.2 8.4 H7.8"/>',
    "anunciado": '<path d="M1 4.5 H3.6 L9.4 1.6 V10.4 L3.6 7.5 H1 Z M4 7.8 L4.8 10.6"/>',
    "em_estudo": '<circle cx="5" cy="5" r="3.3"/><path d="M7.5 7.5 L10.8 10.8"/>',
    "apenas_citado": '<path d="M1 6 H11" stroke-dasharray="2 2"/>',
    "descartado": '<path d="M2 2 L10 10 M10 2 L2 10"/>',
}


def status_mais_avancado(valor):
    """Escolhe o estágio de maior peso (em_uso 5 ... apenas_citado 0). `descartado` só vale se for o único.

    `valor`: None, um status (str), uma lista de status ou {status: n} (status com n <= 0 são ignorados).
    Devolve a chave do status ou None.
    """
    if valor is None:
        return None
    if isinstance(valor, str):
        presentes = [valor]
    elif isinstance(valor, Mapping):
        presentes = [k for k, v in valor.items() if _pos(v) > 0]
    else:
        try:
            presentes = list(valor)
        except TypeError:
            return None
    validos = [s for s in presentes if s in _PESO]
    if validos:
        return max(validos, key=_PESO.get)
    return "descartado" if "descartado" in presentes else None


def _ler_celula(c):
    """-> (status | None, n, href)."""
    if c is None:
        return None, 0, None
    if isinstance(c, str):
        s = status_mais_avancado(c)
        return s, 0, None
    if isinstance(c, Mapping):
        contagens = c.get("contagens")
        if "status" in c:
            status = c["status"] if c["status"] in _STATUS_CURTO else None
        else:
            status = status_mais_avancado(contagens) if contagens else None
        n = c.get("n")
        if n is None and isinstance(contagens, Mapping):
            n = sum(_pos(v) for v in contagens.values())
        return status, int(_pos(n)), c.get("href")
    return None, 0, None


# ============================== 1. matriz de maturidade ==============================


def matriz_maturidade(linhas, colunas, celulas, titulo="Estágio mais avançado de adoção por UF e tecnologia", descricao=None):
    """Grade UF x tecnologia pintada pelo estágio mais avançado (escala da seção 2.1), com legenda.

    linhas  = [{"chave": "SP", "rotulo": "SP", "grupo": "Sudeste"}] (também aceita str ou (chave, rotulo, grupo)); quando
              o `grupo` muda, entra uma linha separadora com o nome da região.
    colunas = [{"chave": "reconhecimento_facial", "rotulo": "Reconhecimento facial"}].
    celulas = {(chave_linha, chave_coluna): X} com X = um status (str) | {"status": "em_uso", "n": 3, "href": "/achados?..."}
              | {"contagens": {"em_uso": 1, "piloto": 9}, "href": ...}. Com `contagens`, vale o status de MAIOR PESO
              (não o mais frequente). `n` (achados) aparece só na dica. Célula ausente = "sem dados".
    """
    L, C = _norm(linhas), _norm(colunas)
    if not L or not C:
        return _vazio()
    celulas = celulas if isinstance(celulas, Mapping) else {}
    uid = _uid("matriz", titulo, L, C, celulas)
    ROT_W, CEL_W, CEL_H, GAP, CAB_H, GRP_H = 84, 120, 24, 3, 54, 22
    larg = ROT_W + len(C) * (CEL_W + GAP)
    corpo = []
    for j, c in enumerate(C):
        cx = ROT_W + j * (CEL_W + GAP) + CEL_W / 2
        ls = _quebrar(c["rotulo"], 18, 3)
        for i, linha in enumerate(ls):
            corpo.append(f'<text class="an-cab" x="{_f(cx)}" y="{_f(CAB_H - 8 - (len(ls) - 1 - i) * 13)}" '
                         f'text-anchor="middle">{_t(linha)}</text>')
    y, grupo_atual, com_dados = CAB_H, object(), 0
    for lin in L:
        if lin["grupo"] is not None and lin["grupo"] != grupo_atual:
            grupo_atual = lin["grupo"]
            corpo.append(f'<text class="an-grupo" x="0" y="{_f(y + 14)}">{_t(grupo_atual)}</text>'
                         f'<line class="an-sep" x1="0" x2="{larg}" y1="{_f(y + 19)}" y2="{_f(y + 19)}"/>')
            y += GRP_H
        corpo.append(f'<text class="an-rot" x="{ROT_W - 8}" y="{_f(y + CEL_H / 2 + 4)}" text-anchor="end">'
                     f'{_t(_cortar(lin["rotulo"], 12))}</text>')
        for j, c in enumerate(C):
            x = ROT_W + j * (CEL_W + GAP)
            status, n, href = _ler_celula(celulas.get((lin["chave"], c["chave"])))
            nome = f'{lin["rotulo"]} × {c["rotulo"]}'
            if status is None:
                dica = f"{nome}: sem dados"
                forma = (f'<rect class="an-c an-c-sem" x="{x}" y="{_f(y)}" width="{CEL_W}" height="{CEL_H}" rx="4"/>'
                         f'<text class="an-ct an-t-sem" x="{x + CEL_W / 2}" y="{_f(y + 16)}" text-anchor="middle">—</text>')
            else:
                com_dados += 1
                dica = f"{nome}: {_STATUS_LEGENDA[status]}" + (f" ({fmt.numero(n)} achados)" if n else "")
                forma = (f'<rect class="an-c an-c-{status}" x="{x}" y="{_f(y)}" width="{CEL_W}" height="{CEL_H}" rx="4" '
                         f'fill="{_fill(uid, status)}"/>'
                         f'<use class="an-gl an-gl-{status}" href="#gl-{uid}-{status}" x="{x + 6}" y="{_f(y + 6)}" '
                         f'width="12" height="12"/>'
                         f'<text class="an-ct an-t-{status}" x="{x + 23}" y="{_f(y + 16)}">{_t(_STATUS_CURTO[status])}</text>')
            corpo.append(_link(href, dica, f"<g><title>{_t(dica)}</title>{forma}</g>"))
        y += CEL_H + GAP
    # legenda
    por_linha = max(int(larg // 150), 1)
    y += 8
    itens = [*sorted(_PESO, key=_PESO.get, reverse=True), "descartado", None]
    for k, status in enumerate(itens):
        lx, ly = (k % por_linha) * 150, y + (k // por_linha) * 22
        if status is None:
            corpo.append(f'<rect class="an-c an-c-sem" x="{lx}" y="{ly}" width="22" height="16" rx="3"/>'
                         f'<text class="an-leg" x="{lx + 28}" y="{ly + 12}">Sem dados</text>')
        else:
            corpo.append(f'<rect class="an-c an-c-{status}" x="{lx}" y="{ly}" width="22" height="16" rx="3" fill="{_fill(uid, status)}"/>'
                         f'<use class="an-gl an-gl-{status}" href="#gl-{uid}-{status}" x="{lx + 5}" y="{ly + 2}" width="12" height="12"/>'
                         f'<text class="an-leg" x="{lx + 28}" y="{ly + 12}">{_t(_STATUS_LEGENDA[status])}</text>')
    altura = y + ((len(itens) - 1) // por_linha + 1) * 22 + 4
    if descricao is None:
        descricao = (f"Grade com {len(L)} linhas e {len(C)} colunas; cada célula mostra o estágio mais avançado de adoção "
                     f"(do apenas citado ao em uso operacional). {com_dados} células têm dados.")
    defs = _defs(uid, [(s, _STATUS_PADRAO[s]) for s in STATUS_ORDEM], STATUS_ORDEM)
    return _svg("an-matriz", larg, altura, titulo, descricao, "".join(corpo), uid, defs)


# ============================== 2. barras de proporção ==============================


def barras_proporcao(itens, titulo, descricao, rotulo_parte="Parte", rotulo_resto="Restante"):
    """Barras horizontais de 100%: a barra inteira é o `total` e a fatia verde é a `parte`.

    itens = [{"rotulo": "Reconhecimento facial", "total": 25, "parte": 3, "href": "/achados?..."}] (href opcional).
    O texto ao lado diz "parte de total (xx%)"; total 0 mostra "sem casos".
    """
    itens = [i for i in (itens or []) if isinstance(i, Mapping)]
    if not itens:
        return _vazio()
    uid = _uid("proporcao", titulo, descricao, itens)
    ROT, BAR, ALT, TXT = 240, 230, 28, 170
    larg = ROT + BAR + 10 + TXT
    corpo = []
    for i, it in enumerate(itens):
        y = 6 + i * ALT
        rotulo = str(it.get("rotulo", ""))
        total = int(_pos(it.get("total")))
        parte = min(int(_pos(it.get("parte"))), total)
        w = BAR * parte / total if total else 0
        if parte and w < 2:
            w = 2
        texto = (f"{fmt.numero(parte)} de {fmt.numero(total)} ({_pct_inteiro(parte, total)})" if total else "sem casos")
        dica = f"{rotulo}: {texto}"
        barra = (f'<rect class="an-bar-fundo" x="{ROT}" y="{y + 4}" width="{BAR}" height="18" rx="3"/>'
                 + (f'<rect class="an-bar-parte" x="{ROT}" y="{y + 4}" width="{_f(w)}" height="18" rx="3"/>' if w else ""))
        conteudo = (f'<g><title>{_t(dica)}</title><text class="an-rot" x="{ROT - 10}" y="{y + 18}" text-anchor="end">'
                    f'{_t(_cortar(rotulo, 34))}</text>{barra}'
                    f'<text class="an-val" x="{ROT + BAR + 10}" y="{y + 18}">{_t(texto)}</text></g>')
        corpo.append(_link(it.get("href"), dica, conteudo))
    y = 6 + len(itens) * ALT + 6
    corpo.append(f'<rect class="an-bar-parte" x="{ROT}" y="{y}" width="14" height="12" rx="2"/>'
                 f'<text class="an-leg" x="{ROT + 20}" y="{y + 10}">{_t(rotulo_parte)}</text>'
                 f'<rect class="an-bar-fundo" x="{ROT + 130}" y="{y}" width="14" height="12" rx="2"/>'
                 f'<text class="an-leg" x="{ROT + 150}" y="{y + 10}">{_t(rotulo_resto)}</text>')
    return _svg("an-proporcao", larg, y + 20, titulo, descricao, "".join(corpo), uid)


# ============================== 3. funil comparativo ==============================


def funil_comparativo(funis, titulo, descricao):
    """Um ou dois funis lado a lado, na mesma escala (o maior valor de todos), com a conversão entre degraus.

    funis = [{"rotulo": "Perplexity", "etapas": [("Links encontrados", 1000), ("Links inéditos", 600, "/chamadas?..."), ...]}]
    Cada etapa é (nome, n) ou (nome, n, href). Os nomes dos degraus vêm do primeiro funil; funis sem etapas são ignorados.
    A conversão "▼ 45%" é n(degrau) / n(degrau anterior); abaixo de 10% ela é destacada.
    """
    lista = []
    for f in (funis or []):
        if not isinstance(f, Mapping) or not f.get("etapas"):
            continue
        etapas = [(str(e[0]), _pos(e[1]), e[2] if len(e) > 2 else None) for e in f["etapas"]
                  if isinstance(e, (tuple, list)) and len(e) >= 2]
        if etapas:
            lista.append((str(f.get("rotulo", "")), etapas))
    lista = lista[:2]
    if not lista:
        return _vazio()
    uid = _uid("funil", titulo, descricao, lista)
    maximo = max(n for _, et in lista for _, n, _ in et) or 1
    n_et = max(len(et) for _, et in lista)
    nomes = [lista[0][1][i][0] if i < len(lista[0][1]) else lista[1][1][i][0] for i in range(n_et)]
    ROT_W, COL_W, TOPO, PASSO, ALT = 190, 230, 26, 50, 26
    larg = ROT_W + len(lista) * COL_W + 10
    corpo = []
    for i, nome in enumerate(nomes):
        ls = _quebrar(nome, 24, 3)
        for k, linha in enumerate(ls):
            corpo.append(f'<text class="an-rot" x="{ROT_W - 12}" y="{_f(TOPO + i * PASSO + ALT / 2 + 4 - 6.5 * (len(ls) - 1) + k * 13)}" '
                         f'text-anchor="end">{_t(linha)}</text>')
    for j, (rotulo, etapas) in enumerate(lista):
        cx = ROT_W + j * COL_W + COL_W / 2
        corpo.append(f'<text class="an-cab" x="{_f(cx)}" y="14" text-anchor="middle">{_t(_cortar(rotulo, 30))}</text>')
        for i, (nome, n, href) in enumerate(etapas):
            y = TOPO + i * PASSO
            w = max(n / maximo * (COL_W - 24), 3 if n else 0)
            dica = f"{rotulo}: {nome}: {fmt.numero(n)}"
            fundo = f'class="an-fn0"' if j == 0 else f'class="an-fn1" fill="{_fill(uid, "f1")}"'
            barra = f'<rect {fundo} x="{_f(cx - w / 2)}" y="{y}" width="{_f(w)}" height="{ALT}" rx="3"/>'
            if w >= 46:
                valor = f'<text class="an-val-dentro" x="{_f(cx)}" y="{y + 17}" text-anchor="middle">{fmt.numero(n)}</text>'
            else:
                valor = f'<text class="an-val" x="{_f(cx + w / 2 + 6)}" y="{y + 17}">{fmt.numero(n)}</text>'
            corpo.append(_link(href, dica, f"<g><title>{_t(dica)}</title>{barra}{valor}</g>"))
            if i + 1 < len(etapas):
                prox = etapas[i + 1][1]
                if n > 0:
                    taxa = prox / n
                    txt = "▼ <1%" if 0 < taxa < 0.01 else f"▼ {100 * taxa:.0f}%"
                    classe = "an-conv an-conv-baixa" if taxa < 0.10 else "an-conv"
                    explica = f"De {fmt.numero(n)} para {fmt.numero(prox)} ({100 * taxa:.1f}% passam para o degrau seguinte)".replace(".", ",")
                else:
                    txt, classe, explica = "▼ —", "an-conv", "Sem base para calcular a passagem"
                corpo.append(f'<text class="{classe}" x="{_f(cx)}" y="{y + ALT + 16}" text-anchor="middle">'
                             f'<title>{_t(explica)}</title>{_t(txt)}</text>')
    altura = TOPO + n_et * PASSO
    return _svg("an-funil", larg, altura, titulo, descricao, "".join(corpo), uid, _defs(uid, [("f1", "diag")]))


# ============================== 4. linha com corte e teto ==============================


def linha_com_corte(pontos, titulo, descricao, rotulo_x="", rotulo_y="", corte=None, teto=None,
                    rotulo_corte="", rotulo_teto=""):
    """Linha (x, y) com uma linha vertical tracejada opcional (`corte`, valor de x) e um teto horizontal opcional (`teto`, valor de y).

    pontos = [(posicao, achados)] ordenados ou não (ex.: retorno por posição, ou buscas x artigos únicos acumulados).
    Usos: retorno por posição (corte = posição onde o retorno some) e curva de saturação (teto = K estimado).
    """
    pts = sorted((x, y) for x, y in ((_num(p[0]), _num(p[1])) for p in (pontos or []) if isinstance(p, (tuple, list)) and len(p) >= 2)
                 if x is not None and y is not None)
    if not pts:
        return _vazio()
    corte, teto = _num(corte), _num(teto)
    uid = _uid("linha", titulo, descricao, pts, corte, teto, rotulo_x, rotulo_y)
    X0, X1, Y0, Y1, LARG, ALT = 58, 616, 18, 252, 640, 300
    xmin, xmax = pts[0][0], pts[-1][0]
    if corte is not None:
        xmin, xmax = min(xmin, corte), max(xmax, corte)
    if xmax <= xmin:
        xmax = xmin + 1
    ytopo, yticks, ypasso = _topo_y(max(max(y for _, y in pts), teto or 0))
    sx, sy = _escala(xmin, xmax, X0, X1), _escala(0, ytopo, Y1, Y0)
    corpo = []
    for v in yticks:
        corpo.append(f'<line class="an-grade" x1="{X0}" x2="{X1}" y1="{_f(sy(v))}" y2="{_f(sy(v))}"/>'
                     f'<text class="an-eixo-val" x="{X0 - 6}" y="{_f(sy(v) + 4)}" text-anchor="end">{_t(_rot_tick(v, ypasso))}</text>')
    xticks, xpasso = _ticks(xmin, xmax, 7)
    for v in xticks:
        corpo.append(f'<line class="an-eixo" x1="{_f(sx(v))}" x2="{_f(sx(v))}" y1="{Y1}" y2="{Y1 + 4}"/>'
                     f'<text class="an-eixo-val" x="{_f(sx(v))}" y="{Y1 + 17}" text-anchor="middle">{_t(_rot_tick(v, xpasso))}</text>')
    corpo.append(f'<line class="an-eixo" x1="{X0}" x2="{X1}" y1="{Y1}" y2="{Y1}"/>'
                 f'<text class="an-eixo-tit" x="{(X0 + X1) / 2}" y="{ALT - 8}" text-anchor="middle">{_t(rotulo_x)}</text>'
                 f'<text class="an-eixo-tit" x="14" y="{(Y0 + Y1) / 2}" text-anchor="middle" '
                 f'transform="rotate(-90 14 {(Y0 + Y1) / 2})">{_t(rotulo_y)}</text>')
    if len(pts) > 1:
        linha = " ".join(f"{_f(sx(x))},{_f(sy(y))}" for x, y in pts)
        corpo.append(f'<polygon class="an-area" points="{_f(sx(pts[0][0]))},{Y1} {linha} {_f(sx(pts[-1][0]))},{Y1}"/>'
                     f'<polyline class="an-linha" points="{linha}"/>')
    if len(pts) <= 80:
        for x, y in pts:
            corpo.append(f'<circle class="an-pt" cx="{_f(sx(x))}" cy="{_f(sy(y))}" r="2.6">'
                         f'<title>{_t(rotulo_x or "x")} {_t(fmt.decimal(x, 0) if x == int(x) else fmt.decimal(x, 2))}: '
                         f'{_t(fmt.decimal(y, 0) if y == int(y) else fmt.decimal(y, 2))}</title></circle>')
    if teto is not None:
        rot = f"{rotulo_teto or 'Teto estimado'} ({fmt.numero(teto) if teto == int(teto) else fmt.decimal(teto, 1)})"
        corpo.append(f'<line class="an-teto" x1="{X0}" x2="{X1}" y1="{_f(sy(teto))}" y2="{_f(sy(teto))}"/>'
                     f'<text class="an-rotulo-linha" x="{X1}" y="{_f(sy(teto) - 5)}" text-anchor="end">{_t(rot)}</text>')
    if corte is not None:
        rot = rotulo_corte or "Ponto de corte"
        direita = sx(corte) < (X0 + X1) / 2
        corpo.append(f'<line class="an-corte" x1="{_f(sx(corte))}" x2="{_f(sx(corte))}" y1="{Y0}" y2="{Y1}"/>'
                     f'<text class="an-rotulo-linha" x="{_f(sx(corte) + (6 if direita else -6))}" y="{Y0 + 12}" '
                     f'text-anchor="{"start" if direita else "end"}">{_t(rot)}</text>')
    return _svg("an-linha-corte", LARG, ALT, titulo, descricao, "".join(corpo), uid)


# ============================== 5. áreas empilhadas ==============================


def areas_empilhadas(anos, series, titulo, descricao):
    """Áreas empilhadas por ano x grupo (linha do tempo).

    anos   = [2018, 2019, ...] (ordem do eixo; com um único ano vira uma coluna empilhada).
    series = [{"rotulo": "Reconhecimento facial", "valores": [n_por_ano...], "href": "/artigos?termo=..."}] na ordem
             de baixo para cima; `valores` mais curto que `anos` é completado com 0. Cada série tem cor + padrão.
    """
    anos = [str(a) for a in (anos or [])]
    series = [s for s in (series or []) if isinstance(s, Mapping)]
    n = len(anos)
    if not n or not series:
        return _vazio()
    dados = []
    for s in series:
        vals = [_pos(v) for v in list(s.get("valores") or [])[:n]]
        dados.append((str(s.get("rotulo", "")), vals + [0.0] * (n - len(vals)), s.get("href")))
    totais = [sum(d[1][i] for d in dados) for i in range(n)]
    if not any(totais):
        return _vazio()
    uid = _uid("areas", titulo, descricao, anos, dados)
    X0, X1, Y0, Y1, LARG = 52, 620, 14, 236, 640
    ytopo, yticks, ypasso = _topo_y(max(totais))
    sy = _escala(0, ytopo, Y1, Y0)

    def sx(i):
        return X0 + (i * (X1 - X0) / (n - 1) if n > 1 else (X1 - X0) / 2)

    corpo = []
    for v in yticks:
        corpo.append(f'<line class="an-grade" x1="{X0}" x2="{X1}" y1="{_f(sy(v))}" y2="{_f(sy(v))}"/>'
                     f'<text class="an-eixo-val" x="{X0 - 6}" y="{_f(sy(v) + 4)}" text-anchor="end">{_t(_rot_tick(v, ypasso))}</text>')
    passo_rot = max(math.ceil(n / 12), 1)
    for i, ano in enumerate(anos):
        if i % passo_rot == 0 or i == n - 1 and passo_rot == 1:
            corpo.append(f'<text class="an-eixo-val" x="{_f(sx(i))}" y="{Y1 + 16}" text-anchor="middle">{_t(ano)}</text>')
    base = [0.0] * n
    padroes = []
    for k, (rotulo, vals, href) in enumerate(dados):
        var, tipo = _serie(k)
        padroes.append((var, tipo))
        topo = [base[i] + vals[i] for i in range(n)]
        if sum(vals):
            dica = f"{rotulo}: {fmt.numero(sum(vals))} no período"
            if n > 1:
                pts = [(sx(i), sy(topo[i])) for i in range(n)] + [(sx(i), sy(base[i])) for i in range(n - 1, -1, -1)]
                forma = f'<polygon class="an-area-s" points="{" ".join(f"{_f(x)},{_f(y)}" for x, y in pts)}" fill="{_fill(uid, var)}"/>'
            else:
                forma = (f'<rect class="an-area-s" x="{_f(sx(0) - 32)}" y="{_f(sy(topo[0]))}" width="64" '
                         f'height="{_f(sy(base[0]) - sy(topo[0]))}" fill="{_fill(uid, var)}"/>')
            corpo.append(_link(href, dica, f"<g><title>{_t(dica)}</title>{forma}</g>"))
        base = topo
    # legenda (mesma ordem da pilha)
    por_linha, y = 4, Y1 + 30
    for k, (rotulo, vals, href) in enumerate(dados):
        var, _ = _serie(k)
        lx, ly = 4 + (k % por_linha) * 158, y + (k // por_linha) * 20
        item = (f'<g><title>{_t(rotulo)}: {_t(fmt.numero(sum(vals)))}</title>'
                f'<rect class="an-area-s" x="{lx}" y="{ly}" width="18" height="12" rx="2" fill="{_fill(uid, var)}"/>'
                f'<text class="an-leg" x="{lx + 24}" y="{ly + 10}">{_t(_cortar(rotulo, 21))}</text></g>')
        corpo.append(_link(href, rotulo, item))
    altura = y + ((len(dados) - 1) // por_linha + 1) * 20 + 4
    return _svg("an-areas", LARG, altura, titulo, descricao, "".join(corpo), uid, _defs(uid, padroes))


# ============================== 6. régua de kappa ==============================

# Escala única do projeto (Landis e Koch, 1977), a mesma de `dominio.concordancia.interpretar_kappa`: 5 faixas positivas.
# kappa < 0 não tem faixa na régua: ganha um marcador próprio e o rótulo "pior que o acaso".
_FAIXAS_KAPPA = [("fraca", "Fraca", "0 a 0,20", 0.0, 0.20, "diag"), ("razoavel", "Razoável", "0,20 a 0,40", 0.20, 0.40, "xadrez"),
                 ("moderada", "Moderada", "0,40 a 0,60", 0.40, 0.60, "pontos"),
                 ("substancial", "Substancial", "0,60 a 0,80", 0.60, 0.80, "horiz"),
                 ("quase", "Quase perfeita", "> 0,80", 0.80, 1.0, "solido")]
_CHAVE_KAPPA = {"pior que o acaso": "pior", "fraca": "fraca", "razoável": "razoavel", "moderada": "moderada",
                "substancial": "substancial", "quase perfeita": "quase"}


def faixa_kappa(valor):
    """(chave, rótulo) da faixa do kappa, pela MESMA escala de `dominio.concordancia.interpretar_kappa` (importada, não
    duplicada): < 0 "pior que o acaso" (chave "pior"); até 0,20 fraca; até 0,40 razoável; até 0,60 moderada; até 0,80
    substancial; acima quase perfeita (chave "quase"). None ou valor não numérico -> None."""
    v = _num(valor)
    if v is None:
        return None
    texto = interpretar_kappa(v)
    return _CHAVE_KAPPA[texto], texto.capitalize()


def regua_kappa(valor, ic=None, titulo="Concordância (kappa de Cohen)"):
    """Régua horizontal com as 5 faixas de interpretação, ponteiro no valor e, opcionalmente, bigode do IC 95%.

    valor = kappa (float; abaixo de 0 o ponteiro fica no início, com marcador vermelho e o rótulo "pior que o acaso";
    acima de 1 no fim; o texto mostra o valor real).
    ic    = (inferior, superior) ou None. `valor` None -> mensagem neutra "sem dados".
    """
    v = _num(valor)
    if v is None:
        return _vazio("Sem dados para calcular a concordância (kappa).")
    chave, nome = faixa_kappa(v)
    intervalo = None
    if isinstance(ic, (tuple, list)) and len(ic) == 2 and None not in ic:
        a, b = _num(ic[0]), _num(ic[1])
        if a is not None and b is not None:
            intervalo = (min(a, b), max(a, b))
    uid = _uid("kappa", titulo, v, intervalo)
    X0, LARG_B, YB, ALT_B = 20, 600, 46, 26
    negativo = v < 0

    def sx(k):
        return X0 + min(max(k, 0.0), 1.0) * LARG_B

    corpo = []
    for ch, rot, faixa, ini, fim, tipo in _FAIXAS_KAPPA:
        atual = " an-faixa-atual" if ch == chave else ""
        corpo.append(f'<g><title>{_t(rot)} ({_t(faixa)})</title>'
                     f'<rect class="an-faixa an-faixa-{ch}{atual}" x="{_f(sx(ini))}" y="{YB}" width="{_f(sx(fim) - sx(ini))}" '
                     f'height="{ALT_B}" fill="{_fill(uid, "k-" + ch)}"/></g>'
                     f'<text class="an-faixa-rot{atual}" x="{_f((sx(ini) + sx(fim)) / 2)}" y="{YB + ALT_B + 16}" text-anchor="middle">{_t(rot)}</text>'
                     f'<text class="an-leg" x="{_f((sx(ini) + sx(fim)) / 2)}" y="{YB + ALT_B + 30}" text-anchor="middle">{_t(faixa)}</text>')
    px = sx(v)
    texto = f"κ = {fmt.decimal(v, 2)}"
    corpo.append(f'<polygon class="an-ponteiro" points="{_f(px - 7)},{YB - 14} {_f(px + 7)},{YB - 14} {_f(px)},{YB - 2}"/>'
                 f'<line class="an-ponteiro-haste" x1="{_f(px)}" x2="{_f(px)}" y1="{YB - 2}" y2="{YB + ALT_B}"/>'
                 f'<text class="an-valor-grande" x="{_f(min(max(px, 44), X0 + LARG_B - 44))}" y="{YB - 20}" text-anchor="middle">{_t(texto)}</text>')
    if negativo:
        corpo.append(f'<g><title>κ abaixo de zero: pior que o acaso</title>'
                     f'<line class="an-limite" x1="{X0}" x2="{X0}" y1="{YB - 4}" y2="{YB + ALT_B + 4}"/></g>'
                     f'<text class="an-limite-rot" x="{X0}" y="{YB + ALT_B + 52}">✕ pior que o acaso (κ &lt; 0): concordância abaixo da esperada ao acaso</text>')
        desc = f"Kappa de {fmt.decimal(v, 2)}: concordância pior que o acaso (abaixo de zero); o ponteiro fica no início da régua."
    else:
        desc = f"Kappa de {fmt.decimal(v, 2)}: concordância {nome.lower()}."
    if intervalo:
        ym = YB + ALT_B / 2
        a, b = sx(intervalo[0]), sx(intervalo[1])
        corpo.append(f'<g class="an-ic"><title>IC 95%: de {_t(fmt.decimal(intervalo[0], 2))} a {_t(fmt.decimal(intervalo[1], 2))}</title>'
                     f'<line class="an-ic-halo" x1="{_f(a)}" x2="{_f(b)}" y1="{ym}" y2="{ym}"/>'
                     f'<line class="an-ic-linha" x1="{_f(a)}" x2="{_f(b)}" y1="{ym}" y2="{ym}"/>'
                     f'<line class="an-ic-linha" x1="{_f(a)}" x2="{_f(a)}" y1="{ym - 6}" y2="{ym + 6}"/>'
                     f'<line class="an-ic-linha" x1="{_f(b)}" x2="{_f(b)}" y1="{ym - 6}" y2="{ym + 6}"/></g>')
        desc += f" Intervalo de confiança de 95%: de {fmt.decimal(intervalo[0], 2)} a {fmt.decimal(intervalo[1], 2)}."
    defs = _defs(uid, [("k-" + ch, tipo) for ch, _, _, _, _, tipo in _FAIXAS_KAPPA])
    return _svg("an-kappa", 640, YB + ALT_B + (62 if negativo else 40), titulo, desc, "".join(corpo), uid, defs)


# ============================== 7. semáforo do limite (escudo de 2%) ==============================

_VEREDITOS = ("ok", "incerto", "acima")


def veredito_limite(ic_inferior, ic_superior, limite):
    """'ok' se o intervalo inteiro está abaixo do limite; 'acima' se inteiro acima; 'incerto' se atravessa; None se faltar dado."""
    a, b, lim = _num(ic_inferior), _num(ic_superior), _num(limite)
    if a is None or b is None or lim is None:
        return None
    a, b = min(a, b), max(a, b)
    if b < lim:
        return "ok"
    if a > lim:
        return "acima"
    return "incerto"


def semaforo_limite(taxa, ic_inferior, ic_superior, limite, titulo, rotulo_ok, rotulo_alerta,
                    rotulo_incerto="Resultado inconclusivo: o intervalo de confiança atravessa o limite. "
                                   "A amostra ainda é pequena para garantir segurança.", n=None, unilateral=False):
    """Barra da taxa observada com a "margem de segurança" sombreada (IC de Wilson) e a linha vermelha do limite.

    `unilateral=True`: o intervalo passado é (taxa observada, limite superior unilateral); a parte sombreada e os textos
    dizem "até no máximo X" em vez de "intervalo de 95%: A a B" (o veredito é o mesmo cálculo: limite superior < limite).

    Todas as taxas em FRAÇÃO (0,004 = 0,4%): taxa, ic_inferior, ic_superior, limite (ex.: 0,02). `n` opcional (tamanho da amostra).
    Veredito: intervalo todo abaixo do limite -> `rotulo_ok` (classe an-veredito-ok); todo acima -> `rotulo_alerta`
    (an-veredito-acima); atravessando -> `rotulo_incerto` (an-veredito-incerto). Falta algum número -> mensagem neutra.
    """
    t, lim = _num(taxa), _num(limite)
    veredito = veredito_limite(ic_inferior, ic_superior, limite)
    if t is None or lim is None or lim <= 0 or veredito is None:
        return _vazio("Sem dados para avaliar o limite de segurança.")
    a, b = sorted((_num(ic_inferior), _num(ic_superior)))
    a, b, t = max(a, 0.0), max(b, 0.0), max(t, 0.0)
    uid = _uid("semaforo", titulo, t, a, b, lim, rotulo_ok, rotulo_alerta, rotulo_incerto, n, *(("unilateral",) if unilateral else ()))
    X0, LARG_B = 20, 600
    vmax = max(lim * 2, b * 1.15, t * 1.15)
    ticks, passo = _ticks(0, vmax, 5)
    vmax = max(vmax, ticks[-1] if ticks else vmax)

    def sx(v):
        return X0 + v / vmax * LARG_B

    corpo = [f'<rect class="an-faixa-fundo" x="{X0}" y="52" width="{LARG_B}" height="26" rx="4"/>']
    for v in ticks:
        corpo.append(f'<line class="an-eixo" x1="{_f(sx(v))}" x2="{_f(sx(v))}" y1="86" y2="91"/>'
                     f'<text class="an-eixo-val" x="{_f(sx(v))}" y="105" text-anchor="middle">{_t(_pct_txt(v))}</text>')
    corpo.append(f'<rect class="an-obs-barra" x="{X0}" y="56" width="{_f(max(sx(t) - X0, 2 if t > 0 else 0))}" height="18" rx="3">'
                 f'<title>Taxa observada: {_t(_pct_txt(t))}</title></rect>'
                 f'<rect class="an-ic-sombra" x="{_f(sx(a))}" y="44" width="{_f(max(sx(b) - sx(a), 2))}" height="42" fill="{_fill(uid, "ic")}">'
                 f'<title>{_t(f"Até no máximo {_pct_txt(b)} (limite superior unilateral de 95%)" if unilateral else f"Margem de segurança (IC 95%): de {_pct_txt(a)} a {_pct_txt(b)}")}</title></rect>'
                 f'<line class="an-limite" x1="{_f(sx(lim))}" x2="{_f(sx(lim))}" y1="34" y2="96"/>'
                 f'<text class="an-limite-rot" x="{_f(sx(lim) + 6)}" y="30">Limite: {_t(_pct_txt(lim))}</text>')
    amostra = f" · amostra de {fmt.numero(n)}" if n is not None and _num(n) is not None else ""
    faixa_txt = (f"até no máximo {_pct_txt(b)}, limite superior unilateral de 95%" if unilateral
                 else f"intervalo de 95%: {_pct_txt(a)} a {_pct_txt(b)}")
    corpo.append(f'<text class="an-texto-med" x="{X0}" y="128">Taxa observada: <tspan class="an-forte">{_t(_pct_txt(t))}</tspan> '
                 f'({_t(faixa_txt)}){_t(amostra)}</text>')
    texto = {"ok": rotulo_ok, "incerto": rotulo_incerto, "acima": rotulo_alerta}[veredito]
    linhas = _quebrar(texto, 62, 4) or [""]
    h_caixa = len(linhas) * 18 + 18
    glifo = {"ok": '<path d="M4 10 L8.5 14.5 L16 5"/>',
             "incerto": '<path d="M10 2.5 L18 17 H2 Z M10 7.5 V12 M10 14.6 h.01"/>',
             "acima": '<path d="M4 4 L16 16 M16 4 L4 16"/>'}[veredito]
    corpo.append(f'<g class="an-veredito an-veredito-{veredito}"><rect class="an-veredito-caixa" x="{X0}" y="142" width="{LARG_B}" '
                 f'height="{h_caixa}" rx="6"/><g class="an-veredito-glifo" transform="translate({X0 + 12} {142 + h_caixa / 2 - 10})">{glifo}</g>'
                 + "".join(f'<text class="an-veredito-texto" x="{X0 + 44}" y="{_f(142 + 22 + i * 18)}">{_t(l)}</text>' for i, l in enumerate(linhas))
                 + "</g>")
    desc = (f"Taxa observada de {_pct_txt(t)} ({faixa_txt}) contra o limite de {_pct_txt(lim)}. "
            f"{texto}")
    return _svg("an-semaforo", 640, 142 + h_caixa + 8, titulo, desc, "".join(corpo), uid, _defs(uid, [("ic", "diag")]))


# ============================== 8. barras de calibração ==============================


def barras_calibracao(grupos, titulo):
    """Colunas grandes (confiança alta / média / baixa) com a taxa de concordância humana e o bigode do IC de Wilson.

    grupos = [{"chave": "alta", "rotulo": "IA disse: confiança alta", "n": 25, "concordam": 23, "ic_inf": 0.76, "ic_sup": 0.98,
               "href": "/achados?confianca=alta&verificacao=confirmado"}]. `taxa` pode vir pronta; senão é concordam / n.
    ic_inf/ic_sup (frações) são opcionais. n = 0 -> coluna tracejada "sem verificação humana ainda". `chave` em
    {alta, media, baixa} usa a cor/padrão do nível; outras chaves usam a série categórica.
    """
    grupos = [g for g in (grupos or []) if isinstance(g, Mapping)]
    if not grupos:
        return _vazio()
    uid = _uid("calibracao", titulo, grupos)
    X0, X1, Y0, Y1 = 52, 628, 34, 224
    slot = (X1 - X0) / len(grupos)
    larg_col = min(slot * 0.55, 120)
    sy = _escala(0, 1, Y1, Y0)
    corpo, padroes = [], []
    for v in (0, 0.25, 0.5, 0.75, 1):
        corpo.append(f'<line class="an-grade" x1="{X0}" x2="{X1}" y1="{_f(sy(v))}" y2="{_f(sy(v))}"/>'
                     f'<text class="an-eixo-val" x="{X0 - 6}" y="{_f(sy(v) + 4)}" text-anchor="end">{int(v * 100)}%</text>')
    resumo = []
    for i, g in enumerate(grupos):
        cx = X0 + slot * (i + 0.5)
        x = cx - larg_col / 2
        rotulo = str(g.get("rotulo", g.get("chave", "")))
        total = int(_pos(g.get("n")))
        chave = g.get("chave")
        var, tipo = (f"cal-{chave}", {"alta": "solido", "media": "diag", "baixa": "pontos"}[chave]) \
            if chave in ("alta", "media", "baixa") else _serie(i)
        corpo.append(f'<text class="an-rot an-rot-forte" x="{_f(cx)}" y="{Y1 + 18}" text-anchor="middle">{_t(_cortar(rotulo, 30))}</text>')
        if total <= 0:
            for k, linha in enumerate(_quebrar("sem verificação humana ainda", 17, 3)):
                corpo.append(f'<text class="an-leg an-centro" x="{_f(cx)}" y="{_f((Y0 + Y1) / 2 - 8 + k * 14)}" text-anchor="middle">{_t(linha)}</text>')
            corpo.append(f'<rect class="an-col-vazia" x="{_f(x)}" y="{Y0}" width="{_f(larg_col)}" height="{Y1 - Y0}" rx="4"/>'
                         f'<text class="an-leg" x="{_f(cx)}" y="{Y1 + 34}" text-anchor="middle">n = 0</text>')
            resumo.append(f"{rotulo}: sem verificação humana")
            continue
        concordam = _pos(g.get("concordam"))
        taxa = _num(g.get("taxa"))
        if taxa is None:
            taxa = concordam / total
        taxa = min(max(taxa, 0.0), 1.0)
        padroes.append((var, tipo))
        topo = sy(taxa)
        dica = f"{rotulo}: {_pct_txt(taxa)} de concordância humana (n = {fmt.numero(total)})"
        ic_i, ic_s = _num(g.get("ic_inf")), _num(g.get("ic_sup"))
        whisker = ""
        if ic_i is not None and ic_s is not None:
            ya, yb = sy(min(max(ic_s, 0), 1)), sy(min(max(ic_i, 0), 1))
            whisker = (f'<g class="an-ic"><line class="an-ic-halo" x1="{_f(cx)}" x2="{_f(cx)}" y1="{_f(ya)}" y2="{_f(yb)}"/>'
                       f'<line class="an-ic-linha" x1="{_f(cx)}" x2="{_f(cx)}" y1="{_f(ya)}" y2="{_f(yb)}"/>'
                       f'<line class="an-ic-linha" x1="{_f(cx - 8)}" x2="{_f(cx + 8)}" y1="{_f(ya)}" y2="{_f(ya)}"/>'
                       f'<line class="an-ic-linha" x1="{_f(cx - 8)}" x2="{_f(cx + 8)}" y1="{_f(yb)}" y2="{_f(yb)}"/></g>')
            dica += f"; IC 95%: {_pct_txt(min(max(ic_i, 0), 1))} a {_pct_txt(min(max(ic_s, 0), 1))}"
        ytxt = (sy(min(max(ic_s, 0), 1)) if whisker else topo) - 6
        conteudo = (f'<g><title>{_t(dica)}</title><rect class="an-col" x="{_f(x)}" y="{_f(topo)}" width="{_f(larg_col)}" '
                    f'height="{_f(Y1 - topo)}" rx="3" fill="{_fill(uid, var)}"/>{whisker}'
                    f'<text class="an-valor-grande" x="{_f(cx)}" y="{_f(max(ytxt, 16))}" text-anchor="middle">{_t(_pct_txt(taxa))}</text>'
                    f'<text class="an-leg" x="{_f(cx)}" y="{Y1 + 34}" text-anchor="middle">n = {fmt.numero(total)}</text></g>')
        corpo.append(_link(g.get("href"), dica, conteudo))
        resumo.append(f"{rotulo}: {_pct_txt(taxa)} (n = {fmt.numero(total)})")
    desc = "Concordância humana por nível de confiança da IA. " + "; ".join(resumo) + "."
    return _svg("an-calibracao", 640, Y1 + 44, titulo, desc, "".join(corpo), uid, _defs(uid, padroes))


# ============================== 9. floresta de odds ratios ==============================

_TICKS_OR = [0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 10000]


def _vezes(v):
    if v >= 10:
        return f"{v:.0f}x"
    return (f"{v:.1f}".rstrip("0").rstrip(".")).replace(".", ",") + "x"


def floresta_odds(linhas, titulo):
    """Forest plot simplificado de razões de chances (odds ratio) com IC 95% em escala logarítmica e linha de referência "1x".

    linhas = [{"rotulo": "Citação literal confere", "or_": 8.5, "ic_inf": 6.0, "ic_sup": 11.2, "href": "/achados?..."}]
    IC todo acima de 1 = "aumenta a chance" (quadrado, ▲); todo abaixo = "reduz" (losango, ▼); atravessa 1 = sem efeito
    comprovado (círculo vazado, ●). `or_` None ou <= 0 mostra "sem estimativa". ic_sup infinito ou ic_inf 0 são cortados na borda do eixo.
    """
    itens = []
    for r in (linhas or []):
        if not isinstance(r, Mapping):
            continue
        est = _num(r.get("or_"))
        inf = _num(r.get("ic_inf"))
        sup = r.get("ic_sup")
        sup = float("inf") if isinstance(sup, float) and math.isinf(sup) else _num(sup)
        valido = est is not None and est > 0 and inf is not None and sup is not None
        itens.append({"rotulo": str(r.get("rotulo", "")), "est": est if valido else None, "inf": inf, "sup": sup, "href": r.get("href")})
    if not itens:
        return _vazio()
    positivos = [1.0]
    for it in itens:
        if it["est"] is not None:
            positivos += [v for v in (it["est"], it["inf"], it["sup"]) if v is not None and 0 < v < float("inf")]
    if len(positivos) == 1 and not any(it["est"] is not None for it in itens):
        return _vazio("Sem estimativas de razão de chances para exibir.")
    uid = _uid("floresta", titulo, itens)
    lo, hi = math.log10(min(positivos)) - 0.12, math.log10(max(positivos)) + 0.12
    LAB, X0, X1, TOPO, PASSO, LARG = 232, 244, 464, 8, 36, 720
    sx = _escala(lo, hi, X0, X1)

    def px(v):
        return sx(min(max(math.log10(v), lo), hi)) if v > 0 else X0

    corpo = []
    n = len(itens)
    ybase = TOPO + n * PASSO
    for t in _TICKS_OR:
        if lo <= math.log10(t) <= hi:
            corpo.append(f'<line class="an-grade" x1="{_f(px(t))}" x2="{_f(px(t))}" y1="{TOPO}" y2="{ybase}"/>'
                         f'<text class="an-eixo-val" x="{_f(px(t))}" y="{ybase + 16}" text-anchor="middle">{_t(_vezes(t))}</text>')
    corpo.append(f'<line class="an-ref" x1="{_f(px(1))}" x2="{_f(px(1))}" y1="{TOPO - 2}" y2="{ybase}"><title>1x = sem efeito</title></line>'
                 f'<text class="an-eixo-tit" x="{_f((X0 + X1) / 2)}" y="{ybase + 34}" text-anchor="middle">'
                 f'← menos chance · 1x = sem efeito · mais chance →</text>')
    resumo = []
    for i, it in enumerate(itens):
        y = TOPO + i * PASSO
        ym = y + PASSO / 2
        rotulo_linhas = _quebrar(it["rotulo"], 36, 2)
        for k, linha in enumerate(rotulo_linhas):
            corpo.append(f'<text class="an-rot" x="{LAB}" y="{_f(ym + 4 - 7 * (len(rotulo_linhas) - 1) + k * 14)}" text-anchor="end">{_t(linha)}</text>')
        if it["est"] is None:
            corpo.append(f'<text class="an-leg" x="{X1 + 16}" y="{_f(ym + 4)}">sem estimativa</text>')
            resumo.append(f"{it['rotulo']}: sem estimativa")
            continue
        est, inf, sup = it["est"], it["inf"], it["sup"]
        if inf > 1:
            classe, glifo, forma = "an-or-mais", "▲", "mais"
        elif sup < 1:
            classe, glifo, forma = "an-or-menos", "▼", "menos"
        else:
            classe, glifo, forma = "an-or-neutro", "●", "neutro"
        xa, xb, xm = px(inf), px(sup), px(est)
        if forma == "mais":
            marca = f'<rect class="an-marca" x="{_f(xm - 5)}" y="{_f(ym - 5)}" width="10" height="10"/>'
        elif forma == "menos":
            marca = f'<polygon class="an-marca" points="{_f(xm)},{_f(ym - 6.5)} {_f(xm + 6.5)},{_f(ym)} {_f(xm)},{_f(ym + 6.5)} {_f(xm - 6.5)},{_f(ym)}"/>'
        else:
            marca = f'<circle class="an-marca" cx="{_f(xm)}" cy="{_f(ym)}" r="5"/>'
        sup_txt = "∞" if math.isinf(sup) else _vezes(sup)
        texto = f"{_vezes(est)} (IC 95%: {_vezes(inf) if inf > 0 else '0x'} a {sup_txt})"
        dica = f"{it['rotulo']}: {texto}"
        resumo.append(dica)
        conteudo = (f'<g class="{classe}"><title>{_t(dica)}</title>'
                    f'<line class="an-ic-linha" x1="{_f(xa)}" x2="{_f(xb)}" y1="{_f(ym)}" y2="{_f(ym)}"/>'
                    f'<line class="an-ic-linha" x1="{_f(xa)}" x2="{_f(xa)}" y1="{_f(ym - 5)}" y2="{_f(ym + 5)}"/>'
                    f'<line class="an-ic-linha" x1="{_f(xb)}" x2="{_f(xb)}" y1="{_f(ym - 5)}" y2="{_f(ym + 5)}"/>{marca}'
                    f'<text class="an-or-texto" x="{X1 + 16}" y="{_f(ym + 4)}">{glifo} {_t(texto)}</text></g>')
        corpo.append(_link(it["href"], dica, conteudo))
    desc = "Razões de chances com intervalo de 95% em escala logarítmica; a linha 1x indica ausência de efeito. " + "; ".join(resumo) + "."
    return _svg("an-floresta", LARG, ybase + 42, titulo, desc, "".join(corpo), uid)


# ============================== 10. mosaico e mapa de calor ==============================

_RES_NIVEIS = [("res-mais3", "diag", "Muito acima do esperado (+)"), ("res-mais2", "diag", "Acima do esperado (+)"),
               ("res-zero", "solido", "Dentro do esperado"),
               ("res-menos2", "diag2", "Abaixo do esperado (−)"), ("res-menos3", "diag2", "Muito abaixo do esperado (−)")]


def _nivel_residuo(z, limiar, forte):
    if z is None:
        return "res-zero"
    if z >= forte:
        return "res-mais3"
    if z >= limiar:
        return "res-mais2"
    if z <= -forte:
        return "res-menos3"
    if z <= -limiar:
        return "res-menos2"
    return "res-zero"


def mosaico(tabela, linhas, colunas, titulo, residuos=None, descricao=None, hrefs=None, limiar=2.0, limiar_forte=3.0):
    """Mosaico proporcional (ex.: região x tecnologia): a LARGURA de cada coluna é o total da linha; a ALTURA do segmento é a fatia.

    tabela  = {(chave_linha, chave_coluna): n}; linhas = regiões (viram as colunas do mosaico); colunas = tecnologias
              (viram as fatias). Cada um é [{"chave", "rotulo"}] (ou str). Linhas com total 0 são omitidas.
    residuos = {(chave_linha, chave_coluna): z} opcional (resíduos padronizados). Com ele, o segmento é pintado por excesso
               (azul, padrão "/", sinal +) ou falta (laranja, padrão "\\", sinal −): |z| >= `limiar` (2) e >= `limiar_forte` (3).
               Sem ele, cada tecnologia tem cor + padrão próprios e legenda.
    hrefs   = {(chave_linha, chave_coluna): "/achados?..."} opcional (cada segmento vira link).
    """
    L, C = _norm(linhas), _norm(colunas)
    tabela = tabela if isinstance(tabela, Mapping) else {}
    if not L or not C:
        return _vazio()
    n = {(l["chave"], c["chave"]): _pos(tabela.get((l["chave"], c["chave"]))) for l in L for c in C}
    totais = {l["chave"]: sum(n[(l["chave"], c["chave"])] for c in C) for l in L}
    visiveis = [l for l in L if totais[l["chave"]] > 0]
    geral = sum(totais.values())
    if not visiveis:
        return _vazio()
    residuos = residuos if isinstance(residuos, Mapping) else None
    hrefs = hrefs if isinstance(hrefs, Mapping) else {}
    uid = _uid("mosaico", titulo, L, C, sorted(n.items(), key=repr), sorted((residuos or {}).items(), key=repr), sorted(hrefs.items(), key=repr))
    X0, PL, Y0, PH, GAP, LARG = 8, 624, 8, 250, 4, 640
    util = PL - GAP * (len(visiveis) - 1)
    corpo, padroes, x = [], [], X0
    for l in visiveis:
        tot = totais[l["chave"]]
        w = tot / geral * util
        y = Y0
        for j, c in enumerate(C):
            v = n[(l["chave"], c["chave"])]
            if v <= 0:
                continue
            h = v / tot * PH
            if residuos is not None:
                z = _num(residuos.get((l["chave"], c["chave"])))
                var = _nivel_residuo(z, limiar, limiar_forte)
                tipo = next(t for k, t, _ in _RES_NIVEIS if k == var)
                sinal = "+ " if var.startswith("res-mais") else "− " if var.startswith("res-menos") else ""
                extra = f"; resíduo padronizado {fmt.decimal(z, 1)}" if z is not None else ""
            else:
                var, tipo = _serie(j)
                sinal, extra = "", ""
            padroes.append((var, tipo))
            dica = (f'{l["rotulo"]} × {c["rotulo"]}: {fmt.numero(v)} '
                    f'({_pct_inteiro(v, tot)} do total de {l["rotulo"]}{extra})')
            rotulo_seg = ""
            if w >= 58 and h >= 16:
                rotulo_seg = (f'<text class="an-halo an-leg" x="{_f(x + w / 2)}" y="{_f(y + h / 2 + 4 - (6 if h >= 32 else 0))}" text-anchor="middle">'
                              f'{_t(sinal)}{_t(_cortar(c["rotulo"], int(w / 6.3)))}</text>')
                if h >= 32:
                    rotulo_seg += (f'<text class="an-halo an-leg" x="{_f(x + w / 2)}" y="{_f(y + h / 2 + 10)}" text-anchor="middle">'
                                   f'{_pct_inteiro(v, tot)}</text>')
            seg = (f'<g><title>{_t(dica)}</title><rect class="an-seg an-seg-{var}" x="{_f(x)}" y="{_f(y)}" width="{_f(w)}" '
                   f'height="{_f(h)}" fill="{_fill(uid, var)}"/>{rotulo_seg}</g>')
            corpo.append(_link(hrefs.get((l["chave"], c["chave"])), dica, seg))
            y += h
        chars = int((w + GAP) / 6.2)
        if chars >= 3:
            corpo.append(f'<text class="an-rot an-centro" x="{_f(x + w / 2)}" y="{Y0 + PH + 14}" text-anchor="middle">{_t(_cortar(l["rotulo"], chars))}</text>'
                         f'<text class="an-leg" x="{_f(x + w / 2)}" y="{Y0 + PH + 27}" text-anchor="middle">n = {_t(fmt.numero(tot))}</text>')
        x += w + GAP
    ly = Y0 + PH + 40
    if residuos is not None:
        por_linha, itens = 3, [(k, t, r) for k, t, r in _RES_NIVEIS]
        passo_x = 212
        for k, (var, tipo, rot) in enumerate(itens):
            padroes.append((var, tipo))
            lx, yy = 4 + (k % por_linha) * passo_x, ly + (k // por_linha) * 22
            corpo.append(f'<rect class="an-seg an-seg-{var}" x="{lx}" y="{yy}" width="20" height="14" rx="2" fill="{_fill(uid, var)}"/>'
                         f'<text class="an-leg" x="{lx + 26}" y="{yy + 11}">{_t(rot)}</text>')
        linhas_leg = 2
    else:
        por_linha = 4
        for j, c in enumerate(C):
            var, tipo = _serie(j)
            padroes.append((var, tipo))
            lx, yy = 4 + (j % por_linha) * 158, ly + (j // por_linha) * 22
            corpo.append(f'<rect class="an-seg an-seg-{var}" x="{lx}" y="{yy}" width="20" height="14" rx="2" fill="{_fill(uid, var)}"/>'
                         f'<text class="an-leg" x="{lx + 26}" y="{yy + 11}">{_t(_cortar(c["rotulo"], 20))}</text>')
        linhas_leg = (len(C) - 1) // por_linha + 1
    if descricao is None:
        descricao = (f"Mosaico com {len(visiveis)} colunas (largura proporcional ao total de cada linha) e {len(C)} fatias; "
                     f"{fmt.numero(geral)} ocorrências no total."
                     + (" Segmentos pintados por excesso ou falta em relação ao esperado." if residuos is not None else ""))
    return _svg("an-mosaico", LARG, ly + linhas_leg * 22 + 4, titulo, descricao, "".join(corpo), uid, _defs(uid, padroes))


def _formato_padrao(v):
    if float(v) == int(v):
        return fmt.numero(int(v))
    return fmt.decimal(v, 1)


def mapa_de_calor_assimetrico(linhas, colunas, valores, titulo, formato=None, descricao=None, hrefs=None):
    """Mapa de calor de uma matriz qualquer (linhas e colunas diferentes): tabelas de confusão, status x status etc.

    linhas/colunas = [{"chave", "rotulo"}] (ou str); valores = {(chave_linha, chave_coluna): número | None};
    formato = função número -> texto (padrão: inteiro com ponto de milhar ou 1 casa decimal); hrefs = {(l, c): "/achados?..."}.
    Cinco níveis de cor proporcionais ao maior valor; o número aparece sempre dentro da célula (cor nunca é a única pista).
    Célula sem valor (None/ausente) fica vazia com "—".
    """
    L, C = _norm(linhas), _norm(colunas)
    valores = valores if isinstance(valores, Mapping) else {}
    hrefs = hrefs if isinstance(hrefs, Mapping) else {}
    if not L or not C:
        return _vazio()
    formato = formato or _formato_padrao
    dados = {(l["chave"], c["chave"]): _num(valores.get((l["chave"], c["chave"]))) for l in L for c in C}
    presentes = [v for v in dados.values() if v is not None]
    if not presentes:
        return _vazio()
    maximo = max(max(presentes), 0) or 1
    uid = _uid("calor", titulo, L, C, sorted(dados.items(), key=repr), sorted(hrefs.items(), key=repr))
    ROT_W, CEL_W, CEL_H, CAB_H = 150, 76, 26, 46
    larg = ROT_W + len(C) * CEL_W + 4
    corpo = []
    for j, c in enumerate(C):
        ls = _quebrar(c["rotulo"], 12, 3)
        for i, linha in enumerate(ls):
            corpo.append(f'<text class="an-cab" x="{ROT_W + j * CEL_W + CEL_W / 2}" y="{CAB_H - 6 - (len(ls) - 1 - i) * 12}" '
                         f'text-anchor="middle">{_t(linha)}</text>')
    for i, l in enumerate(L):
        y = CAB_H + i * CEL_H
        corpo.append(f'<text class="an-rot" x="{ROT_W - 8}" y="{y + CEL_H / 2 + 4}" text-anchor="end">{_t(_cortar(l["rotulo"], 24))}</text>')
        for j, c in enumerate(C):
            x = ROT_W + j * CEL_W
            v = dados[(l["chave"], c["chave"])]
            if v is None:
                forma = (f'<rect class="an-c an-c-sem" x="{x}" y="{y}" width="{CEL_W - 2}" height="{CEL_H - 2}" rx="3"/>'
                         f'<text class="an-ct an-t-sem" x="{x + CEL_W / 2 - 1}" y="{y + 17}" text-anchor="middle">—</text>')
                dica = f'{l["rotulo"]} × {c["rotulo"]}: sem valor'
            else:
                nivel = 0 if v <= 0 else min(1 + int(4 * v / maximo - 1e-9), 4) if v < maximo else 4
                nivel = max(nivel, 1) if v > 0 else 0
                texto = formato(v)
                forma = (f'<rect class="an-c an-calor-{nivel}" x="{x}" y="{y}" width="{CEL_W - 2}" height="{CEL_H - 2}" rx="3"/>'
                         f'<text class="an-ct an-calor-t-{nivel}" x="{x + CEL_W / 2 - 1}" y="{y + 17}" text-anchor="middle">{_t(texto)}</text>')
                dica = f'{l["rotulo"]} × {c["rotulo"]}: {texto}'
            corpo.append(_link(hrefs.get((l["chave"], c["chave"])), dica, f"<g><title>{_t(dica)}</title>{forma}</g>"))
    altura = CAB_H + len(L) * CEL_H + 6
    if descricao is None:
        descricao = f"Mapa de calor com {len(L)} linhas e {len(C)} colunas; valores de {formato(min(presentes))} a {formato(max(presentes))}."
    return _svg("an-calor", larg, altura, titulo, descricao, "".join(corpo), uid)


# ============================== 11. fluxo de duas colunas ==============================


def fluxo_duas_colunas(origens, destinos, fluxos, destaques, titulo, hrefs=None, rotulo_destaque="Fluxo destacado em vermelho"):
    """Fluxo simples (estilo Sankey) entre duas colunas; a espessura de cada fita é proporcional à quantidade.

    origens/destinos = [{"chave", "rotulo"}] (ou str), na ordem de cima para baixo.
    fluxos    = {(chave_origem, chave_destino): n}; destaques = lista/conjunto de (chave_origem, chave_destino) a pintar de
                vermelho (classe an-fluxo-alerta, com padrão e contorno). Fitas muito finas ganham 2px para continuarem visíveis.
    hrefs     = {(origem, destino): "/artigos?..."} opcional. Embaixo vai o resumo do que foi destacado (n e %).
    """
    O, D = _norm(origens), _norm(destinos)
    fluxos = fluxos if isinstance(fluxos, Mapping) else {}
    hrefs = hrefs if isinstance(hrefs, Mapping) else {}
    fl = {(o["chave"], d["chave"]): _pos(fluxos.get((o["chave"], d["chave"]))) for o in O for d in D}
    total = sum(fl.values())
    if not O or not D or total <= 0:
        return _vazio()
    marcados = {tuple(x) for x in (destaques or []) if isinstance(x, (tuple, list)) and len(x) == 2}
    uid = _uid("fluxo", titulo, O, D, sorted(fl.items(), key=repr), sorted(marcados, key=repr), sorted(hrefs.items(), key=repr))
    XL, XR, LARG, NO_W, MARG, GAP = 200, 484, 700, 14, 12, 12
    saidas = {o["chave"]: sum(fl[(o["chave"], d["chave"])] for d in D) for o in O}
    entradas = {d["chave"]: sum(fl[(o["chave"], d["chave"])] for o in O) for d in D}
    escala = min((280 - GAP * (len(lado) - 1)) / total for lado in (O, D))
    escala = max(escala, 0.01)

    def empilhar(itens, tot):
        pos, y = {}, MARG
        for it in itens:
            h = tot[it["chave"]] * escala
            slot = max(h, 16)
            pos[it["chave"]] = (y, h, slot)
            y += slot + GAP
        return pos, y - GAP

    po, fim_o = empilhar(O, saidas)
    pd, fim_d = empilhar(D, entradas)
    alt_plot = max(fim_o, fim_d) + MARG

    def topo(pos, chave):
        y, h, slot = pos[chave]
        return y + (slot - h) / 2

    def desloc(pos):
        return {k: topo(pos, k) for k in pos}

    cur_o, cur_d = desloc(po), desloc(pd)
    fitas, destacadas, soma_dest = [], [], 0.0
    xm = (XL + NO_W + XR) / 2
    for o in O:
        for d in D:
            v = fl[(o["chave"], d["chave"])]
            if v <= 0:
                continue
            h = v * escala
            ya, yb = cur_o[o["chave"]], cur_d[d["chave"]]
            cur_o[o["chave"]] += h
            cur_d[d["chave"]] += h
            hh = max(h, 2.0)
            ya0, yb0 = ya + h / 2 - hh / 2, yb + h / 2 - hh / 2
            x0, x1 = XL + NO_W, XR
            forma = (f"M{x0} {_f(ya0)} C{_f(xm)} {_f(ya0)} {_f(xm)} {_f(yb0)} {x1} {_f(yb0)} "
                     f"L{x1} {_f(yb0 + hh)} C{_f(xm)} {_f(yb0 + hh)} {_f(xm)} {_f(ya0 + hh)} {x0} {_f(ya0 + hh)} Z")
            marcado = (o["chave"], d["chave"]) in marcados
            dica = f'{o["rotulo"]} → {d["rotulo"]}: {fmt.numero(v)} ({fmt.decimal(100 * v / total, 1)}% do total)'
            if marcado:
                soma_dest += v
                path = f'<path class="an-fluxo an-fluxo-alerta" d="{forma}" fill="{_fill(uid, "fx")}"/>'
                destacadas.append(_link(hrefs.get((o["chave"], d["chave"])), dica, f"<g><title>{_t(dica)} (destacado)</title>{path}</g>"))
            else:
                path = f'<path class="an-fluxo" d="{forma}"/>'
                fitas.append(_link(hrefs.get((o["chave"], d["chave"])), dica, f"<g><title>{_t(dica)}</title>{path}</g>"))
    corpo = list(fitas) + destacadas
    for lado, pos, tot, x, ancora, dx in ((O, po, saidas, XL, "end", -8), (D, pd, entradas, XR, "start", NO_W + 8)):
        for it in lado:
            y, h, slot = pos[it["chave"]]
            yc = y + slot / 2
            corpo.append(f'<rect class="an-no" x="{x}" y="{_f(topo(pos, it["chave"]))}" width="{NO_W}" height="{_f(max(h, 2))}">'
                         f'<title>{_t(it["rotulo"])}: {_t(fmt.numero(tot[it["chave"]]))}</title></rect>'
                         f'<text class="an-rot" x="{x + dx}" y="{_f(yc - 1)}" text-anchor="{ancora}">{_t(_cortar(it["rotulo"], 30))}</text>'
                         f'<text class="an-leg" x="{x + dx}" y="{_f(yc + 12)}" text-anchor="{ancora}">'
                         f'{_t(fmt.numero(tot[it["chave"]]))} ({_pct_inteiro(tot[it["chave"]], total)})</text>')
    if marcados:
        resumo = (f"{rotulo_destaque}: {fmt.numero(soma_dest)} de {fmt.numero(total)} "
                  f"({fmt.decimal(100 * soma_dest / total, 1)}% do fluxo total)." if soma_dest else
                  f"{rotulo_destaque}: nenhum caso (0 de {fmt.numero(total)}).")
        corpo.append(f'<rect class="an-fluxo an-fluxo-alerta" x="4" y="{_f(alt_plot + 6)}" width="22" height="10" fill="{_fill(uid, "fx")}"/>'
                     f'<text class="an-texto-med" x="32" y="{_f(alt_plot + 15)}">{_t(resumo)}</text>')
        alt_plot += 22
    else:
        resumo = ""
    desc = (f"Fluxo de {fmt.numero(total)} casos entre {len(O)} origens e {len(D)} destinos." + (f" {resumo}" if resumo else ""))
    return _svg("an-fluxo-svg", LARG, alt_plot + 4, titulo, desc, "".join(corpo), uid, _defs(uid, [("fx", "diag")]))


# ============================== 12. dispersão ==============================


def dispersao(pontos, titulo, descricao, rotulo_x="", rotulo_y="", corte_x=None, curva=None, log_x=False, rotulo_corte=""):
    """Gráfico de dispersão com corte vertical opcional (ex.: 60.000 caracteres) e curva suave pré-calculada opcional.

    pontos = [(x, y)] ou [(x, y, dica)] ou [(x, y, dica, href)]; curva = [(x, y)] já suavizada (ex.: LOWESS).
    log_x = True usa escala logarítmica em x (pontos com x <= 0 são ignorados). Acima de 400 pontos as dicas
    individuais são omitidas e acima de 4.000 a amostra é reduzida de forma determinística, para o SVG não pesar.
    """
    pts = []
    for p in (pontos or []):
        if isinstance(p, (tuple, list)) and len(p) >= 2:
            x, y = _num(p[0]), _num(p[1])
            if x is None or y is None or (log_x and x <= 0):
                continue
            pts.append((x, y, p[2] if len(p) > 2 else None, p[3] if len(p) > 3 else None))
    if not pts:
        return _vazio()
    total_original = len(pts)
    if len(pts) > 4000:
        passo = math.ceil(len(pts) / 4000)
        pts = pts[::passo]
    cv = sorted((x, y) for x, y in ((_num(p[0]), _num(p[1])) for p in (curva or []) if isinstance(p, (tuple, list)) and len(p) >= 2)
                if x is not None and y is not None and not (log_x and x <= 0))
    corte = _num(corte_x)
    if log_x and corte is not None and corte <= 0:
        corte = None
    uid = _uid("dispersao", titulo, descricao, pts, cv, corte, log_x, rotulo_x, rotulo_y)
    X0, X1, Y0, Y1, LARG, ALT = 58, 600, 14, 250, 640, 304
    xs = [x for x, *_ in pts] + [x for x, _ in cv] + ([corte] if corte is not None else [])
    ys = [y for _, y, *_ in pts] + [y for _, y in cv]
    ymin = min(0.0, min(ys))
    ytopo, yticks, ypasso = _topo_y(max(max(ys), 0))
    if ymin < 0:
        yticks, ypasso = _ticks(ymin, ytopo)
    sy = _escala(ymin, ytopo, Y1, Y0)
    corpo = []
    if log_x:
        lo, hi = math.floor(math.log10(min(xs))), math.ceil(math.log10(max(xs)))
        if lo == hi:
            hi += 1
        sx0 = _escala(lo, hi, X0, X1)

        def sx(v):
            return sx0(math.log10(v))

        xticks = [(10 ** k, fmt.numero(10 ** k)) for k in range(lo, hi + 1)]
    else:
        xmin, xmax = min(xs), max(xs)
        if xmax <= xmin:
            xmax = xmin + 1
        sx = _escala(xmin, xmax, X0, X1)
        vals, xpasso = _ticks(xmin, xmax, 7)
        xticks = [(v, _rot_tick(v, xpasso)) for v in vals]
    for v in yticks:
        corpo.append(f'<line class="an-grade" x1="{X0}" x2="{X1}" y1="{_f(sy(v))}" y2="{_f(sy(v))}"/>'
                     f'<text class="an-eixo-val" x="{X0 - 6}" y="{_f(sy(v) + 4)}" text-anchor="end">{_t(_rot_tick(v, ypasso))}</text>')
    for v, rot in xticks:
        corpo.append(f'<line class="an-eixo" x1="{_f(sx(v))}" x2="{_f(sx(v))}" y1="{Y1}" y2="{Y1 + 4}"/>'
                     f'<text class="an-eixo-val" x="{_f(sx(v))}" y="{Y1 + 17}" text-anchor="middle">{_t(rot)}</text>')
    corpo.append(f'<line class="an-eixo" x1="{X0}" x2="{X1}" y1="{Y1}" y2="{Y1}"/>'
                 f'<text class="an-eixo-tit" x="{(X0 + X1) / 2}" y="{ALT - 8}" text-anchor="middle">{_t(rotulo_x)}</text>'
                 f'<text class="an-eixo-tit" x="14" y="{(Y0 + Y1) / 2}" text-anchor="middle" transform="rotate(-90 14 {(Y0 + Y1) / 2})">{_t(rotulo_y)}</text>')
    com_dica = len(pts) <= 400
    for x, y, dica, href in pts:
        txt = str(dica) if dica else f"{_rot_tick(x, 1)}; {fmt.decimal(y, 1)}"
        circulo = f'<circle class="an-ponto" cx="{_f(sx(x))}" cy="{_f(sy(y))}" r="2.8">' + (f"<title>{_t(txt)}</title>" if com_dica else "") + "</circle>"
        corpo.append(_link(href, txt, circulo))
    if len(cv) > 1:
        corpo.append(f'<polyline class="an-curva" points="{" ".join(f"{_f(sx(x))},{_f(sy(y))}" for x, y in cv)}"><title>Tendência suavizada</title></polyline>')
    if corte is not None:
        direita = sx(corte) < (X0 + X1) / 2
        rot = rotulo_corte or f"Corte: {fmt.numero(corte)}"
        corpo.append(f'<line class="an-corte" x1="{_f(sx(corte))}" x2="{_f(sx(corte))}" y1="{Y0}" y2="{Y1}"/>'
                     f'<text class="an-rotulo-linha" x="{_f(sx(corte) + (6 if direita else -6))}" y="{Y0 + 12}" '
                     f'text-anchor="{"start" if direita else "end"}">{_t(rot)}</text>')
    desc = descricao or titulo
    if total_original > len(pts):
        desc += f" (amostra de {fmt.numero(len(pts))} entre {fmt.numero(total_original)} pontos)"
    return _svg("an-dispersao", LARG, ALT, titulo, desc, "".join(corpo), uid)


# ============================== 13. ranking de bloqueios ==============================


def nivel_bloqueio(taxa, limiares=(0.2, 0.5)):
    """'aberto' (< 20%), 'parcial' (20% a < 50%) ou 'fechado' (>= 50%); taxa em fração."""
    if taxa < limiares[0]:
        return "aberto"
    return "parcial" if taxa < limiares[1] else "fechado"


_NIVEL_ROTULO = {"aberto": "Aberto", "parcial": "Parcial", "fechado": "Fechado"}
_NIVEL_PADRAO = {"aberto": "solido", "parcial": "diag", "fechado": "xadrez"}


def _selo_motivo(tipo, n):
    """Selo de um motivo de bloqueio do download: 'proibido' (robots.txt lido e proíbe: alerta forte, ✕) ou 'preventivo' (robots.txt
    indisponível, bloqueio pela RFC 9309: âmbar, ⚠). Mostra a contagem `n`; zero fica apagado e sem selo."""
    classe, glifo = ("robots-proibido", "✕") if tipo == "proibido" else ("robots-preventivo", "⚠")
    if not n:
        return '<span class="an-zero">0</span>'
    return f'<span class="selo {classe}"><span aria-hidden="true">{glifo}</span> {_t(fmt.numero(n))}</span>'


def ranking_semaforo(linhas, titulo, limiares=(0.2, 0.5)):
    """Tabela HTML de portais (domínios) ordenada pela fatia de páginas bloqueadas, com barra SVG, % e situação em texto.

    linhas = [{"dominio": "ssp.ba.gov.br", "total": 40, "bloqueadas": 28, "href": "/chamadas?q=ssp.ba.gov.br"}]
    `bloqueadas` = proibidas pelo site. Opcional, `inacessiveis` = páginas não baixadas porque o robots.txt do site estava
    inacessível (bloqueio pela política, não proibição do site): ganha uma coluna própria, que só aparece se alguma linha o trouxer;
    não entra na fatia nem na situação.
    Situação por limiares (fração bloqueada): aberto < 20%, parcial < 50%, fechado >= 50% (classes an-nivel-aberto|parcial|fechado,
    cada uma com padrão e texto próprios). Ordem: maior fatia, depois maior total, depois nome (determinística).
    """
    itens = []
    for r in (linhas or []):
        if not isinstance(r, Mapping):
            continue
        total = int(_pos(r.get("total")))
        bloq = min(int(_pos(r.get("bloqueadas"))), total)
        itens.append((str(r.get("dominio", "")), total, bloq, r.get("href"), int(_pos(r.get("inacessiveis")))))
    if not itens:
        return _vazio()
    itens.sort(key=lambda i: (-(i[2] / i[1] if i[1] else 0), -i[1], i[0]))
    com_inacessiveis = any("inacessiveis" in r for r in linhas if isinstance(r, Mapping))
    linhas_html = []
    for dominio, total, bloq, href, inacessiveis in itens:
        taxa = bloq / total if total else 0.0
        nivel = nivel_bloqueio(taxa, limiares)
        uid = _uid("rank", dominio, total, bloq)
        txt = f"{_pct_inteiro(bloq, total)} bloqueadas" if total else "sem páginas"
        barra_svg = _svg(f"an-barra-semaforo an-nivel-{nivel}", 120, 12, f"{dominio}: {txt}",
                         f"{fmt.numero(bloq)} de {fmt.numero(total)} páginas bloqueadas ({_NIVEL_ROTULO[nivel].lower()})",
                         f'<rect class="an-bar-fundo" x="0" y="0" width="120" height="12" rx="3"/>'
                         + (f'<rect class="an-barra-nivel" x="0" y="0" width="{_f(max(120 * taxa, 2) if bloq else 0)}" height="12" rx="3" '
                            f'fill="{_fill(uid, "nv-" + nivel)}"/>' if bloq else ""),
                         uid, _defs(uid, [("nv-" + nivel, _NIVEL_PADRAO[nivel])]))
        nome = f'<a href="{_t(_href_seguro(href))}">{_t(dominio)}</a>' if _href_seguro(href) else _t(dominio)
        linhas_html.append(f'<tr class="an-nivel-{nivel}"><th scope="row">{nome}</th><td class="num">{_t(fmt.numero(total))}</td>'
                           f'<td class="num">{_selo_motivo("proibido", bloq)}</td>'
                           + (f'<td class="num">{_selo_motivo("preventivo", inacessiveis)}</td>' if com_inacessiveis else "")
                           + f'<td class="an-celula-barra">{barra_svg}</td>'
                           f'<td class="num">{_t(_pct_inteiro(bloq, total))}</td><td><span class="an-situacao an-situacao-{nivel}">'
                           f'{_t(_NIVEL_ROTULO[nivel])}</span></td></tr>')
    cab = ("<tr><th scope=\"col\">Domínio</th><th scope=\"col\" class=\"num\">Páginas</th>"
           "<th scope=\"col\" class=\"num\">Proibidas pelo site <span class=\"an-glifo-proibido\" aria-hidden=\"true\">✕</span>"
           "<small class=\"an-nota-coluna\">Disallow do robots.txt ou HTTP 401/403/429</small></th>"
           + ("<th scope=\"col\" class=\"num\">Bloqueio preventivo (RFC 9309) <span class=\"an-glifo-preventivo\" aria-hidden=\"true\">⚠</span>"
              "<small class=\"an-nota-coluna\">robots.txt do site indisponível</small></th>" if com_inacessiveis else "")
           + "<th scope=\"col\">Fatia bloqueada</th><th scope=\"col\" class=\"num\">%</th><th scope=\"col\">Situação</th></tr>")
    return (f'<div class="tabela-rolavel"><table class="an-ranking"><caption class="so-leitor">{_t(titulo)}</caption>'
            f'<thead>{cab}</thead><tbody>{"".join(linhas_html)}</tbody></table></div>')


# ============================== barra de progresso (prontidão metodológica) ==============================


def barra_progresso(n, minimo, rotulo):
    """Barra de progresso acessível (`role="img"`, `<title>` e `<desc>` com o valor e o mínimo, como todo SVG do painel) de `n` contra `minimo`.

    A cor vem só de classes de `painel.css` (azul em andamento, verde ao atingir o mínimo); o texto "n / mínimo" acompanha a
    barra na página, então a cor não é a única pista. `n` acima do mínimo enche a barra, mas o texto mostra o valor real."""
    n, minimo = int(_pos(n)), max(int(_pos(minimo)), 1)
    atual = min(n, minimo)
    texto = f"{fmt.numero(n)} / {fmt.numero(minimo)}"
    classe = "be-conf" if n >= minimo else "be-prog"
    largura = 1000 * atual / minimo
    parte = f'<rect class="{classe}" x="0" y="0" width="{_f(largura)}" height="20"/>' if largura else ""
    return (f'<svg class="barra-progresso" viewBox="0 0 1000 20" preserveAspectRatio="none" role="img">'
            f'<title>{_t(rotulo)}: {_t(texto)}</title><desc>Progresso de {_t(rotulo)}: {_t(texto)} (mínimo {fmt.numero(minimo)}).</desc>'
            f'<rect class="be-fundo" x="0" y="0" width="1000" height="20" rx="6"/>{parte}</svg>')
