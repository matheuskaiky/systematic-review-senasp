#!/usr/bin/env python3
"""Monta os CSS do painel (versão 5) a partir de src/ + tokens.py + build/icones.json.

Uso:  python3 gerar_painel_css.py <raiz v5>      (escreve em <raiz>/build/css/)

O que acontece:
  1. Lê src/painel/*.css na ordem do nome (00_, 10_, 20_...), troca os marcadores de ícone e as listas geradas por tabelas, e põe o
     bloco de tokens (gerado de tokens.py) no topo.
  2. Faz o mesmo para analises.css, solucoes.css, classificadores.css, metodologia.css, relevancia.css e triagem_escopo.css.
Marcadores aceitos nas fontes:
  %ic(nome)%   -> "\\eXXX"  glifo de contorno          %icf(nome)%  glifo cheio          %icd(nome)%  camada de fundo do duotone
  /*@GERADO:mapa-icones*/  /*@GERADO:menu*/  /*@GERADO:tons-de-pagina*/  /*@GERADO:icones-de-pagina*/  tabelas montadas aqui
  3. Todo "content:" que carrega um glifo da fonte de ícones ganha uma SEGUNDA declaração com texto alternativo vazio ('content: X; content: X / ""'), para o leitor
     de tela não anunciar o glifo. A primeira declaração é a reserva dos navegadores que não conhecem a sintaxe com texto alternativo.
O resultado (build/css/*.css) é o que vai para painel/static/. As fontes e este script ficam no pacote só para manutenção.
"""
import json, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tokens as T
import tokens_analises as TA

RAIZ = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
ICONES = json.loads((RAIZ / "build" / "icones.json").read_text(encoding="utf-8"))

# ---------------------------------------------------------------------------------------------- tabelas do menu e das páginas
# href, ícone, tom. A marcação do menu é fixada pelos testes, então ícone e matiz entram por CSS, pelo href.
MENU = [
    ("/", "squares-four", "cobalto"), ("/literatura/prisma", "flow-arrow", "cobalto"), ("/estados", "map-trifold", "petroleo"),
    ("/achados", "binoculars", "petroleo"), ("/revisao/achados", "seal-check", "petroleo"), ("/literatura/artigos", "article", "rosa"),
    ("/literatura", "books", "rosa"), ("/literatura/triagem", "funnel", "rosa"),
    ("/analises", "chart-line-up", "violeta"), ("/triagem-escopo", "robot", "violeta"), ("/classificadores", "tag", "violeta"),
    ("/execucoes/comparar", "git-diff", "violeta"), ("/solucoes", "lightbulb", "ambar"),
    ("/buscar-texto", "magnifying-glass", "petroleo"), ("/execucoes", "play-circle", "ambar"), ("/chamadas", "plugs-connected", "ambar"),
    ("/metodologia", "flask", "cobalto"), ("/sobre", "database", "cobalto"),
]
GRUPOS = [("revisao", "list-checks", "cobalto"), ("analises", "chart-bar", "violeta"), ("auditoria", "gear-six", "ambar")]
# a marca do menu (fixada pelo teste NA) não leva ícone de página; o hero de /revisao/achados e de /achados/{id} herda o de /achados.


def glifo(nome, variante="r"):
    if nome not in ICONES:
        sys.exit(f"ícone fora da fonte: {nome}")
    cod = ICONES[nome].get(variante)
    if not cod:
        sys.exit(f"ícone sem variante {variante}: {nome}")
    return '"\\' + cod + '"'


def trocar_icones(txt):
    txt = re.sub(r"%ic\(([\w-]+)\)%", lambda m: glifo(m.group(1), "r"), txt)
    txt = re.sub(r"%icf\(([\w-]+)\)%", lambda m: glifo(m.group(1), "f"), txt)
    txt = re.sub(r"%icd\(([\w-]+)\)%", lambda m: glifo(m.group(1), "d"), txt)
    return txt


# glifos de ícone são decoração: o texto alternativo vazio (content: X / "") tira o glifo da árvore de acessibilidade, como o aria-hidden faz nos
# glifos escritos na marcação. Só entram o glifo literal da fonte de ícones e as variáveis que o carregam; o resto (aspas, setas de ordenação, "Mostrar") fica como está.
_VARS_ICONE = ("--ic", "--ic-f", "--mi", "--mi-f", "--av-ic", "--pg-ic", "--pg-ic-f", "--bl-ic", "--ab-ic", "--ab-icf")
_RE_CONTENT = re.compile(r"(content:\s*)([^;}]+?)(\s*)(?=[;}])")


def ocultar_do_leitor(txt):
    def uma(m):
        valor = m.group(2)
        if valor.rstrip().endswith('/ ""'):
            return m.group(0)
        eh_icone = re.search(r'"\\e[0-9a-f]{3}"', valor) or any(f"var({v}" in valor for v in _VARS_ICONE)
        # a declaração simples vem ANTES da com texto alternativo: navegador que não entende a sintaxe "content: X / alt" (Safari < 17.4, Firefox < 128) descarta só a segunda
        # e continua mostrando o glifo; os que entendem ficam com a segunda (a última declaração válida vence).
        return f'{m.group(1)}{valor}; {m.group(1)}{valor} / ""{m.group(3)}' if eh_icone else m.group(0)
    return _RE_CONTENT.sub(uma, txt)


# ---------------------------------------------------------------------------------------------- blocos gerados
# matiz de partida de cada ícone (para o atributo data-ic sozinho já dar variedade). data-tom="..." no mesmo elemento sobrepõe.
TOM_DOS_ICONES = {
    "cobalto": "squares-four flow-arrow flask database info gear-six sliders-horizontal list-checks check-circle check-square stack columns rows sidebar-simple house "
               "terminal code keyboard lifebuoy question hash text-aa list-bullets",
    "petroleo": "map-pin map-trifold binoculars link globe compass magnifying-glass magnifying-glass-plus list-magnifying-glass target crosshair buildings bank "
                "share-network tree-structure path police-car video-camera camera fingerprint identification-badge eye",
    "violeta": "chart-line-up chart-bar chart-line chart-donut chart-pie-slice chart-scatter robot brain tag git-diff git-branch scales sparkle cpu graph pulse trend-up "
               "percent gauge seal-check seal-question seal shield-star shield-check shield",
    "ambar": "lightbulb play-circle plugs-connected plug coins currency-circle-dollar clock timer hourglass lightning receipt warning warning-circle warning-diamond "
             "warning-octagon siren bell megaphone flag",
    "rosa": "article books book-open-text bookmark-simple bookmarks funnel file-text files notebook quotes graduation-cap scroll note-pencil clipboard-text user users "
            "user-check chat-text calendar-blank star",
}


def mapa_icones():
    """[data-ic="nome"] define as variáveis do glifo e a cor de partida; [data-tom="matiz"] sobrepõe. Qualquer elemento ganha ícone só com o atributo."""
    out = ["/* Mapa de ícones. Acrescente data-ic=\"nome\" a h2, h3, summary, .kpi, .aviso, .vazio, a, button, .botao ou .selo; acrescente data-tom=\"cobalto|petroleo|violeta|ambar|rosa\" para trocar o matiz do ladrilho.",
           "   Sem data-tom vale o matiz de partida do ícone (listas abaixo) e, para ícones fora delas, o matiz da página. */"]
    for nome in sorted(n for n in ICONES if n != "marca"):
        e = ICONES[nome]
        partes = [f'--ic: "\\{e["r"]}";']
        if "f" in e:
            partes.append(f'--ic-f: "\\{e["f"]}";')
        if "d" in e:
            partes.append(f'--ic-d: "\\{e["d"]}";')
        out.append(f'[data-ic="{nome}"] {{ {" ".join(partes)} }}')
    for tom, nomes in TOM_DOS_ICONES.items():
        lista = [n for n in nomes.split() if n in ICONES]
        sel = ",\n".join(f'[data-ic="{n}"]' for n in lista)
        out.append(f"{sel} {{ --ic-tx: var(--tom-{tom}-tx); --ic-fundo: var(--tom-{tom}-fundo); --ic-borda: var(--tom-{tom}-borda); --ic-solido: var(--tom-{tom}-solido); --ic-solido-tx: var(--tom-{tom}-solido-tx); }}")
    for tom in T.TONS:
        out.append(f'[data-tom="{tom}"] {{ --ic-tx: var(--tom-{tom}-tx); --ic-fundo: var(--tom-{tom}-fundo); --ic-borda: var(--tom-{tom}-borda); --ic-solido: var(--tom-{tom}-solido); --ic-solido-tx: var(--tom-{tom}-solido-tx); }}')
    return "\n".join(out)


def menu_css():
    out = ["/* Ícone e matiz de cada item do menu (a marcação do menu não muda: o seletor é o href). Gerado de MENU em gerar_painel_css.py. */"]
    for href, ic, tom in MENU:
        e = ICONES[ic]
        out.append(f'.menu-lista a[href=\'{href}\'] {{ --mi: "\\{e["r"]}"; --mi-f: "\\{e["f"]}"; --mt-fundo: var(--menu-{tom}-fundo); --mt-tx: var(--menu-{tom}-tx); --mt-solido: var(--menu-{tom}-solido); }}')
    for chave, ic, tom in GRUPOS:
        e = ICONES[ic]
        out.append(f'.menu-grupo[data-grupo="{chave}"] > summary {{ --mi: "\\{e["r"]}"; --mt-tx: var(--menu-{tom}-tx); }}')
    return "\n".join(out)


def tons_de_pagina():
    """Cada página aponta o próprio matiz (--tom-*) pelo item marcado com aria-current no menu."""
    por_tom = {}
    for href, ic, tom in MENU:
        por_tom.setdefault(tom, []).append(href)
    out = ["/* Matiz da página = matiz do item atual do menu. Sem item atual (404, erro): cobalto, definido em .layout. */"]
    for tom, hrefs in por_tom.items():
        sel = ",\n".join(f'.layout:has(.menu-lista a[href=\'{h}\'][aria-current="page"])' for h in hrefs)
        out.append(f"{sel} {{ --tom-tx: var(--tom-{tom}-tx); --tom-fundo: var(--tom-{tom}-fundo); --tom-borda: var(--tom-{tom}-borda); --tom-solido: var(--tom-{tom}-solido); --tom-solido-tx: var(--tom-{tom}-solido-tx); }}")
    return "\n".join(out)


def icones_de_pagina():
    out = ["/* Ícone do título da página (ladrilho antes do h1) = ícone do item atual do menu. */"]
    for href, ic, tom in MENU:
        e = ICONES[ic]
        out.append(f'.layout:has(.menu-lista a[href=\'{href}\'][aria-current="page"]) {{ --pg-ic: "\\{e["r"]}"; --pg-ic-f: "\\{e["f"]}"; --pg-ic-d: "\\{ICONES[ic].get("d", e["r"])}"; }}')
    return "\n".join(out)


def _empacotar(itens, indent="  ", largura=150):
    """['--a: 1;', ...] -> linhas de até `largura` colunas."""
    out, cur = [], indent
    for it in itens:
        if len(cur) + len(it) + 1 > largura and cur.strip():
            out.append(cur.rstrip())
            cur = indent
        cur += it + " "
    if cur.strip():
        out.append(cur.rstrip())
    return "\n".join(out)


def an_tokens():
    """Os quatro blocos de tokens --an-* de analises.css, na ordem que o teste lê: :root, escuro, (botão de tema), impressão.
    O botão de tema grava data-theme no html. Como o hexadecimal só pode ficar em blocos :root simples, as duas paletas de dados ficam guardadas no
    primeiro :root (--an-claro-* e --an-escuro-*) e os blocos :root[data-theme] só repetem var() delas."""
    c, e, p = TA.claro(), TA.escuro(), TA.impressao()
    trocam = [k for k in c if k in e]            # o que o tema escuro troca (os var() de painel.css se ajustam sozinhos)
    var = [f"--an-{k}: var({tok});" for k, tok in TA.VARS.items()]
    lit = [f"--an-{k}: {v};" for k, v in c.items()]
    prim_c = [f"--an-claro-{k}: {c[k]};" for k in trocam]
    prim_e = [f"--an-escuro-{k}: {e[k]};" for k in trocam]
    claro = "\n".join([
        ":root {",
        _empacotar(var), _empacotar(lit),
        "  /* guarda das duas paletas de dados: os blocos do botão de tema (data-theme) só podem usar var(), nunca hexadecimal */",
        _empacotar(prim_c), _empacotar(prim_e), "}"])
    escuro = "@media (prefers-color-scheme: dark) {\n  :root {\n" + _empacotar([f"--an-{k}: {e[k]};" for k in trocam], indent="    ") + "\n  }\n}"
    forcado = ("/* Escolha explícita no botão de tema. Só em tela: no papel manda o bloco de impressão, que é sempre claro. */\n@media screen {\n"
               "  :root[data-theme=\"dark\"] {\n" + _empacotar([f"--an-{k}: var(--an-escuro-{k});" for k in trocam], indent="    ") + "\n  }\n"
               "  :root[data-theme=\"light\"] {\n" + _empacotar([f"--an-{k}: var(--an-claro-{k});" for k in trocam], indent="    ") + "\n  }\n}")
    imp_itens = [f"--an-{k}: {p[k]};" for k in TA.VARS] + [f"--an-{k}: {p[k]};" for k in c] + prim_c + prim_e
    imp = "@media print {\n  :root {\n" + _empacotar(imp_itens, indent="    ") + "\n  }\n}"
    return "\n".join([claro, escuro, forcado, imp])


GERADOS = {"an-tokens": an_tokens, "mapa-icones": mapa_icones, "menu": menu_css, "tons-de-pagina": tons_de_pagina, "icones-de-pagina": icones_de_pagina}


def expandir(txt):
    return re.sub(r"/\*@GERADO:([\w-]+)\*/", lambda m: GERADOS[m.group(1)](), txt)


# ---------------------------------------------------------------------------------------------- bloco de tokens
PRIMITIVOS_EXTRA = {   # escalas só do calor (ficam na camada 1 para que os blocos de tema forçado usem só var())
    "calor-c1": "#cdeeea", "calor-c2": "#86d3ca", "calor-c3": "#2fa59a", "calor-c4": "#0b6560",
    "calor-e1": "#143a3a", "calor-e2": "#1f6b66", "calor-e3": "#34a89c", "calor-e4": "#8de6da",
}


def _sem(tab, simples=False):
    """token -> texto CSS. Nome da camada 1 vira var(--primitivo); em bloco :root SIMPLES (simples=True) os tokens de T.LITERAIS saem como #rrggbb
    (hexadecimal é permitido ali e só ali); nos blocos do botão de tema fica sempre var(--primitivo). Valor que não é primitivo (sombra) sai como está."""
    prim = {**T.PRIM, **PRIMITIVOS_EXTRA}
    out = {}
    for k, v in tab.items():
        if v in prim:
            out[k] = prim[v] if (simples and k in T.LITERAIS) else f"var(--{v})"
        else:
            out[k] = v
    return out


def bloco_tokens():
    claro = dict(T.SEM_CLARO)
    escuro = dict(T.SEM_ESCURO)
    # calor entra como primitivo
    for i in range(1, 5):
        claro[f"--calor-{i}"] = f"calor-c{i}"
        escuro[f"--calor-{i}"] = f"calor-e{i}"
    # sidebar: tile de cada matiz (a barra lateral é escura nos dois temas)
    for t in T.TONS:
        claro[f"--menu-{t}-fundo"] = f"{t}-900"
        claro[f"--menu-{t}-tx"] = f"{t}-300"
        claro[f"--menu-{t}-solido"] = f"{t}-500"
    c, e = _sem(claro, True), _sem(escuro, True)     # blocos :root simples: claro, escuro do sistema e impressão
    cv, ev = _sem(claro), _sem(escuro)               # blocos do botão de tema: só var()
    prim = {**T.PRIM, **PRIMITIVOS_EXTRA}

    def linhas(d, ordem=None, indent="  ", largura=140):
        itens = [f"{k}: {d[k]};" for k in (ordem or d)]
        out, cur = [], indent
        for it in itens:
            if len(cur) + len(it) + 1 > largura and cur.strip():
                out.append(cur.rstrip()); cur = indent
            cur += it + " "
        if cur.strip():
            out.append(cur.rstrip())
        return "\n".join(out)

    prim_txt = linhas({f"--{k}": v for k, v in prim.items()}, indent="  ")
    corpo_claro = linhas(c, indent="  ")
    fixos = linhas(T.FIXOS, indent="  ")
    corpo_escuro = linhas(e, indent="    ")
    # tema forçado claro: só o que o escuro troca, com o valor claro (sem hex: var() ou sombras)
    forcado_claro = linhas({k: cv[k] for k in e}, indent="    ")
    forcado_escuro = linhas(ev, indent="    ")
    # impressão: tudo o que o escuro troca e os 4 valores fixos; o resto, texto idêntico ao do claro (o teste compara como texto)
    imp = {k: c[k] for k in e}
    imp.update(T.FIXOS_IMPRESSAO)
    imp_txt = linhas(imp, indent="    ")
    cabecalho = (RAIZ / "src" / "painel" / "00_cabecalho.css").read_text(encoding="utf-8").rstrip() + "\n"
    estatico = (RAIZ / "src" / "painel" / "01_tokens_estaticos.css").read_text(encoding="utf-8").rstrip()
    css = f"""{cabecalho}:root {{
  /* ---- Camada 1: primitivos (estáticos; nenhum tema mexe aqui) ---- */
{prim_txt}

  /* ---- Camada 2: semânticos, TEMA CLARO (padrão) ---- */
  color-scheme: light dark;
{corpo_claro}
  /* iguais nos dois temas (contexto do banco): valor direto */
{fixos}
{estatico}
}}
@media (prefers-color-scheme: dark) {{
  :root {{
{corpo_escuro}
  }}
}}
/* Escolha explícita da pessoa (botão de tema). Só em tela: no papel manda o bloco de impressão. Só var() aqui: nenhum hexadecimal fora do :root simples. */
@media screen {{
  :root[data-theme="dark"] {{
    color-scheme: dark;
{forcado_escuro}
  }}
  :root[data-theme="light"] {{
    color-scheme: light;
{forcado_claro}
  }}
}}
"""
    return css, imp_txt


# ---------------------------------------------------------------------------------------------- montagem
def montar_painel():
    css_tokens, imp_txt = bloco_tokens()
    partes = sorted((RAIZ / "src" / "painel").glob("[1-9]*.css"))
    corpo = []
    for p in partes:
        txt = p.read_text(encoding="utf-8")
        if "/*@IMPRESSAO:raiz*/" in txt:
            txt = txt.replace("/*@IMPRESSAO:raiz*/", f"  :root {{\n    color-scheme: light;\n{imp_txt}\n  }}")
        corpo.append(ocultar_do_leitor(expandir(trocar_icones(txt))).rstrip() + "\n")
    return css_tokens + "\n" + "\n".join(corpo)


def montar_simples(nome):
    p = RAIZ / "src" / nome
    return ocultar_do_leitor(expandir(trocar_icones(p.read_text(encoding="utf-8"))))


if __name__ == "__main__":
    out = RAIZ / "build" / "css"
    out.mkdir(parents=True, exist_ok=True)
    (out / "painel.css").write_text(montar_painel(), encoding="utf-8")
    for nome in ("analises", "solucoes", "classificadores", "metodologia", "relevancia", "triagem_escopo"):
        f = RAIZ / "src" / f"{nome}.css"
        if f.exists():
            (out / f"{nome}.css").write_text(montar_simples(f"{nome}.css"), encoding="utf-8")
    for f in sorted(out.glob("*.css")):
        print(f"{f.name}: {f.stat().st_size} bytes, {f.read_text(encoding='utf-8').count(chr(10))} linhas")
