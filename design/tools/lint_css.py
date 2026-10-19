#!/usr/bin/env python3
"""Verificador estático dos CSS do painel (versão 5).

Refaz, sobre os arquivos, as leituras que os testes do projeto fazem (contrato, seção 6) e acrescenta as regras de desenho da v5. Não substitui a suíte
(2.000+ testes): serve para pegar o erro de CSS em segundos, antes de rodar tudo.

Uso:   python3 lint_css.py <pasta com painel.css e as demais folhas> [--original <pasta com os CSS do handoff original>]
Saída: uma linha por falha ("[código] mensagem") e, no fim, o resumo. Código de saída 0 só se nada falhou.

Famílias de checagem
  NA/AC/SV/IN/DS/GA/RL  contrato dos testes (estrutura do arquivo, tokens, contraste, impressão, selos, ordenação, relatório estático, analises.css)
  V5                    regras de desenho: nenhuma barra de destaque num lado só (borda, sombra interna, sombra externa ou tira pseudo-elemento)
  COB                   cobertura: toda classe do CSS original que ainda aparece no HTML tem regra (só com --original)
"""
import re, sys
from pathlib import Path

args = [a for a in sys.argv[1:] if not a.startswith("--")]
PASTA = Path(args[0] if args else ".").resolve()
ORIG = None
if "--original" in sys.argv:
    i = sys.argv.index("--original")
    ORIG = Path(sys.argv[i + 1]).resolve()

FALHAS, NOTAS = [], []


def falha(cod, msg):
    FALHAS.append(f"[{cod}] {msg}")


def exige(cond, cod, msg):
    if not cond:
        falha(cod, msg)
    return bool(cond)


# ------------------------------------------------------------------------------------------------------------- parser caseiro (igual ao dos testes, em espírito)
def sem_coment(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def blocos(css):
    """[(prefixo, corpo)] no nível do texto dado. Prefixo = texto depois do bloco anterior."""
    out, i, n = [], 0, len(css)
    while True:
        j = css.find("{", i)
        if j < 0:
            break
        d, k = 1, j + 1
        while d and k < n:
            d += (css[k] == "{") - (css[k] == "}")
            k += 1
        out.append((css[i:j].strip(), css[j + 1:k - 1]))
        i = k
    return out


def achatar(css, ctx=()):
    for pre, corpo in blocos(css):
        if pre.startswith("@media") or pre.startswith("@supports"):
            yield from achatar(corpo, ctx + (pre,))
        else:
            yield ctx, pre, corpo


def decls(corpo):
    return [(n, v.strip()) for n, v in re.findall(r"([\w-]+)\s*:\s*([^;]+);?", corpo)]


def tokens(corpo):
    return {n: v for n, v in decls(corpo) if n.startswith("--")}


def seletores(sel):
    return [s.strip() for s in sel.split(",") if s.strip()]


def acha_regra(regras, seletor, ctx=()):
    """Todas as regras cujo seletor (separado por vírgula) contém `seletor` exatamente."""
    return [(c, s, d) for c, s, d in regras if c == ctx and seletor in seletores(s)]


def decl_de(corpo, nome):
    r = [v for n, v in decls(corpo) if n == nome]
    return r[-1] if r else None


# ------------------------------------------------------------------------------------------------------------- cores e contraste
HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")


def resolve(tok, *camadas):
    env = {}
    for c in camadas:
        env.update(c)
    v = env.get(tok)
    for _ in range(14):
        if v is None:
            return None
        m = re.fullmatch(r"var\((--[\w-]+)\)", v.strip())
        if not m:
            return v.strip()
        v = env.get(m.group(1))
    return None


def cor(valor, *camadas):
    """Valor de uma declaração de cor -> #rrggbb (ou None se não resolver)."""
    if valor is None:
        return None
    valor = valor.strip()
    m = re.fullmatch(r"var\((--[\w-]+)\)", valor)
    if m:
        valor = resolve(m.group(1), *camadas)
        if valor is None:
            return None
    if re.fullmatch(r"#[0-9a-fA-F]{3}", valor):
        valor = "#" + "".join(c * 2 for c in valor[1:])
    return valor.lower() if re.fullmatch(r"#[0-9a-fA-F]{6}", valor) else None


def lum(h):
    h = h.lstrip("#")
    r, g, b = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    f = lambda c: c / 12.92 if c <= .03928 else ((c + .055) / 1.055) ** 2.4
    return .2126 * f(r) + .7152 * f(g) + .0722 * f(b)


def contraste(a, b):
    x, y = lum(a), lum(b)
    x, y = max(x, y), min(x, y)
    return (x + .05) / (y + .05)


def mistura(fg, bg, alfa):
    f = [int(fg[i:i + 2], 16) for i in (1, 3, 5)]
    g = [int(bg[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(alfa * a + (1 - alfa) * b):02x}" for a, b in zip(f, g))


# ------------------------------------------------------------------------------------------------------------- leitura
def ler(nome):
    p = PASTA / nome
    if not p.exists():
        falha("NA", f"{nome} não existe em {PASTA}")
        return None
    return p.read_text(encoding="utf-8")


PROIBIDOS = ("<script", "javascript:", "onclick", "onerror", "src=", "<link", "@import", "url(", "<iframe", "<img", "<object", "http")

TOKENS_62 = ("--fundo --superficie --texto --texto-suave --texto-botao --borda --borda-controle --acento --acento-fundo --ok --ok-fundo --alerta --alerta-fundo "
             "--perigo --perigo-fundo --neutro --neutro-fundo --marca --marca-borda --marca-aprox --foco --foco-largura --foco-recuo --banner-real --banner-simulado "
             "--banner-demo --texto-banner --st-anunciado --st-anunciado-fundo --st-em_estudo --st-em_estudo-fundo --calor-1 --calor-2 --calor-3 --calor-4 --fonte-base "
             "--fonte-mono --fs-xs --fs-sm --fs-md --fs-base --fs-lg --fs-xl --fs-2xl --lh-tight --lh-base --lh-solto --esp-1 --esp-2 --esp-3 --esp-4 --esp-5 --esp-6 "
             "--esp-7 --esp-8 --raio-xs --raio-sm --raio-md --raio --raio-pilula --sombra --indicador").split()
TROCAM_NO_ESCURO = "--fundo --superficie --texto --acento --ok --alerta --perigo --st-anunciado --calor-1 --marca".split()
TEXTO_45 = [("--texto", "--fundo"), ("--texto", "--superficie"), ("--texto", "--acento-fundo"), ("--texto", "--alerta-fundo"), ("--texto", "--marca"),
            ("--texto", "--marca-aprox"), ("--texto-suave", "--fundo"), ("--texto-suave", "--superficie"), ("--texto-suave", "--acento-fundo"), ("--acento", "--fundo"),
            ("--acento", "--superficie"), ("--acento", "--acento-fundo"), ("--ok", "--superficie"), ("--ok", "--ok-fundo"), ("--alerta", "--superficie"),
            ("--alerta", "--alerta-fundo"), ("--perigo", "--superficie"), ("--perigo", "--perigo-fundo"), ("--perigo", "--fundo"), ("--texto-botao", "--acento")]
COMPONENTE_3 = [("--borda-controle", "--fundo"), ("--borda-controle", "--superficie"), ("--acento", "--fundo"), ("--acento", "--superficie")]
QUATRO_FIXOS = {"--fundo": "#ffffff", "--texto-suave": "#4a5462", "--borda": "#9aa3b0", "--borda-controle": "#5b6675"}
# tokens que os testes comparam como TEXTO (sem resolver var()): têm de ser #rrggbb literal nos blocos :root simples (claro, escuro do sistema, impressão).
# Mesma lista de LITERAIS em tools/tokens.py.
LITERAIS = "--texto --superficie --acento --perigo --perigo-fundo --ok --ok-fundo --alerta --alerta-fundo --calor-1 --calor-2 --calor-3 --calor-4".split()
UM_SALTO = re.compile(r"var\((--[\w-]+)\)")


def remover_bloco(css, prefixo):
    """Tira do texto o bloco `prefixo { ... }` (casando as chaves)."""
    i = css.find(prefixo)
    while i >= 0:
        j = css.find("{", i)
        d, k = 1, j + 1
        while d and k < len(css):
            d += (css[k] == "{") - (css[k] == "}")
            k += 1
        css = css[:i] + css[k:]
        i = css.find(prefixo)
    return css


# ------------------------------------------------------------------------------------------------------------- painel.css
def checar_painel(raw):
    css = sem_coment(raw)
    exige(raw.lstrip().startswith("/* ===== Tokens de design"), "NA", "painel.css precisa abrir com o comentário '/* ===== Tokens de design'")
    exige(css.count("{") == css.count("}"), "AC", "chaves desbalanceadas em painel.css")
    baixo = raw.lower()
    for s in PROIBIDOS:
        exige(s not in baixo, "RL", f"'{s}' aparece em painel.css (nem em comentário: o relatório estático embute o arquivo)")
    exige("<" not in raw, "RL", "'<' aparece em painel.css (vira tag quando o arquivo é embutido no relatório)")
    sem_escuro = remover_bloco(raw, "@media (prefers-color-scheme: dark)")
    exige("prefers-color-scheme" not in sem_escuro, "RL", "a palavra 'prefers-color-scheme' aparece fora do bloco escuro (inclusive em comentário)")

    # --- estrutura dos três blocos de tema
    exige(":root {" in css, "DS", "falta a literal ':root {'")
    if ":root {" not in css:
        return
    resto = css.split(":root {", 1)[1]
    corpo_raiz, depois = resto.split("}", 1)
    L = tokens(corpo_raiz)
    exige(depois.lstrip().startswith("@media (prefers-color-scheme: dark) {"), "DS",
          "o bloco '@media (prefers-color-scheme: dark) {' precisa vir logo depois do primeiro :root (o trecho entre os dois fica vazio)")
    bl = blocos(depois)
    D = {}
    if bl and bl[0][0] == "@media (prefers-color-scheme: dark)":
        ib = blocos(bl[0][1])
        exige(ib and ib[0][0] == ":root", "NA", "o primeiro bloco interno do tema escuro precisa ser :root")
        if ib:
            D = tokens(ib[0][1])
    prints = [c for p, c in blocos(css) if p == "@media print"]
    exige(css.count("@media print {") == 1 and len(prints) == 1, "IN", "precisa haver UM único '@media print {' (grafia exata)")
    P = {}
    corpo_print = prints[0] if prints else ""
    if prints:
        ib = blocos(corpo_print)
        exige(ib and ib[0][0] == ":root", "NA", "o primeiro bloco interno do bloco de impressão precisa ser :root")
        if ib and ib[0][0] == ":root":
            exige("color-scheme: light" in ib[0][1], "NA", "o :root de impressão precisa de 'color-scheme: light'")
            P = tokens(ib[0][1])

    # --- tokens
    for t in TOKENS_62:
        exige(t in L, "NA", f"token ausente no primeiro :root: {t}")
    exige(set(D) <= set(L), "NA", f"tema escuro redefine token que o claro não tem: {sorted(set(D) - set(L))}")
    for t in TROCAM_NO_ESCURO:
        a, b = resolve(t, L), resolve(t, L, D)
        exige(a and b and a.lower() != b.lower(), "NA", f"o tema escuro precisa trocar {t} (claro {a}, escuro {b})")
    # impressão: strings iguais ao claro, exceto os quatro fixos; o conjunto do escuro cabe no da impressão
    for t, v in P.items():
        if t in QUATRO_FIXOS:
            exige(v.lower() == QUATRO_FIXOS[t], "NA", f"impressão: {t} precisa ser {QUATRO_FIXOS[t]} (está {v})")
        else:
            exige(L.get(t) == v, "NA", f"impressão: {t} difere do claro ('{v}' x '{L.get(t)}')")
    exige(set(D) <= set(P), "NA", f"tokens do escuro ausentes na impressão: {sorted(set(D) - set(P))}")
    # blocos de tema forçado (v5): só var(), iguais ao escuro/claro
    sc = [c for p, c in blocos(css) if p == "@media screen"]
    if sc:
        fb = {p: tokens(c) for p, c in blocos(sc[0])}
        fd, fl = fb.get(':root[data-theme="dark"]', {}), fb.get(':root[data-theme="light"]', {})
        exige(fd and fl, "V5", "faltam os blocos :root[data-theme=...] dentro de '@media screen'")

        def mesmo_valor(t, no_botao, no_simples, camadas):
            """O bloco do botão de tema concorda com o bloco simples: texto idêntico ou, nos tokens de LITERAIS (hexadecimal no bloco simples, var(--primitivo) no
            do botão, onde hexadecimal é proibido), o mesmo hexadecimal depois de resolver."""
            if no_botao == no_simples:
                return True
            if no_simples and HEX.fullmatch(no_simples) and (no_botao or "").startswith("var("):
                r = resolve(t, *camadas)
                return bool(r) and r.lower() == no_simples.lower()
            return False

        for t, v in D.items():
            exige(mesmo_valor(t, fd.get(t), v, (L, fd)), "V5", f"deriva: [data-theme=dark] {t} difere do escuro do sistema")
            exige(mesmo_valor(t, fl.get(t), L.get(t), (L, fl)), "V5", f"deriva: [data-theme=light] {t} difere do claro")
        for t in LITERAIS:
            if t in fd:
                exige(fd[t].startswith("var(") and fl.get(t, "").startswith("var("), "V5", f"{t}: nos blocos do botão de tema só var() (está '{fd[t]}' / '{fl.get(t)}')")
    else:
        fd, fl = {}, {}
        exige(False, "V5", "falta '@media screen { :root[data-theme=...] }' (botão de tema)")

    # --- o teste pode comparar tokens como TEXTO, sem resolver var(): confira também assim (o pior caso)
    for t in LITERAIS:
        for nome, blk in (("claro", L), ("escuro do sistema", D), ("impressão", P)):
            if t in blk:
                exige(HEX.fullmatch(blk[t]) is not None, "NA", f"{t} precisa ser #rrggbb literal no :root {nome}, para testes que comparam texto (está '{blk[t]}')")
    for t in TROCAM_NO_ESCURO:
        exige(t in D and D[t] != L.get(t), "NA", f"o escuro precisa trocar {t} também na comparação de texto (claro '{L.get(t)}', escuro '{D.get(t)}')")
    # nenhuma cadeia de cor passa de um salto (var(--a) -> var(--b) -> hexadecimal): resolvedor de um nível erraria
    for estado, env in (("claro", dict(L)), ("escuro do sistema", {**L, **D}), ("escuro do botão", {**L, **fd}), ("claro do botão", {**L, **D, **fl}), ("impressão", {**L, **P})):
        for t, v in env.items():
            m = UM_SALTO.fullmatch(v.strip())
            if m and UM_SALTO.fullmatch((env.get(m.group(1)) or "").strip()):
                falha("NA", f"[{estado}] {t} -> {m.group(1)} -> outro var(): cadeia de dois saltos (use direto o primitivo)")

    # --- hexadecimal fora de :root simples; rgb() só rgba
    fora = re.sub(r":root\s*\{[^}]*\}", "", css)
    for m in HEX.finditer(fora):
        ctx = fora[max(0, m.start() - 60):m.end() + 20].replace("\n", " ")
        falha("NA", f"hexadecimal fora de :root: ...{ctx}...")
    exige(not re.search(r"\b(rgb|hsl|hsla|oklch|oklab|color-mix)\(", css), "NA", "rgb()/hsl()/oklch()/color-mix() em painel.css (só rgba() é tolerado em painel.css)")

    # --- foco, movimento, rolagem
    plano = raw.replace("\n", " ")
    for s in ("prefers-reduced-motion", ".pular", ".pular:focus", ".so-leitor", ":focus-visible", "summary:focus-visible"):
        exige(s in plano, "AC", f"falta '{s}'")
    exige("outline: none" not in raw and "outline:none" not in raw, "AC", "'outline: none' proibido")

    regras = list(achatar(css))
    topo = [(c, s, d) for c, s, d in regras if c == ()]
    mq900 = [c for p, c in blocos(css) if p == "@media (max-width: 900px)"]
    if exige(mq900, "AC", "falta '@media (max-width: 900px)'"):
        r = [d for c, s, d in achatar(mq900[0]) if ".layout" in seletores(s)]
        exige(any("minmax(0, 1fr)" in (decl_de(d, "grid-template-columns") or "") for d in r), "AC", "no primeiro @media (max-width: 900px): '.layout' com grid-template-columns: minmax(0, 1fr)")
    exige(any("main" in seletores(s) and re.search(r"min-width:\s*0\b", d) for c, s, d in topo), "AC", "regra 'main' com min-width: 0")
    exige(any(".tabela-rolavel" in seletores(s) and "overflow-x" in d for c, s, d in topo), "AC", "regra '.tabela-rolavel' com overflow-x")

    # --- svg
    antes_print = css.split("@media print {")[0]
    rg_antes = list(achatar(antes_print))
    for s in ("svg.grafico", "svg.mapa", "svg.barra-empilhada"):
        exige(any(s in seletores(sl) and "width: 100%" in d for c, sl, d in rg_antes), "SV", f"'{s}' precisa de uma regra com 'width: 100%'")
    exige(re.search(r"svg\.calor\s*\{[^}]*width:\s*100%[^}]*max-width:\s*900px", antes_print), "SV", "svg.calor { width: 100% ... max-width: 900px } nessa ordem")
    for c, s, d in regras:
        if "svg" in s and re.search(r"(?<![\w-])width:\s*\d+(\.\d+)?px", d):
            falha("SV", f"regra com 'svg' fixa width em px: {s}")
    exige(re.search(r"\.selo\.selo-longo\s*\{[^}]*white-space:\s*normal", css) and
          re.search(r"\.selo\.selo-longo\s*\{[^}]*max-width:\s*100%[^}]*overflow-wrap:\s*anywhere", css), "SV", ".selo.selo-longo: white-space: normal e depois max-width: 100% + overflow-wrap: anywhere")

    # --- selos, banners, contraste
    LC = (L,)
    DC = (L, D)
    por_sel = {}
    for c, s, d in topo:
        for sel in seletores(s):
            por_sel.setdefault(sel, []).append(d)

    def prop(sel, nome):
        for d in reversed(por_sel.get(sel, [])):
            v = decl_de(d, nome)
            if v:
                return v
        return None

    selos = [s for s in por_sel if re.fullmatch(r"\.(st|cf)-[\w-]+", s)]
    exige(len([s for s in selos if prop(s, "color")]) >= 10, "AC", f"precisa de ≥10 regras '.st-*'/'.cf-*' com color (há {len(selos)})")
    exige(prop(".selo", "background") is not None, "AC", "'.selo' precisa de background")
    for tema, cam in (("claro", LC), ("escuro", DC)):
        fundo_selo = cor(prop(".selo", "background"), *cam)
        for s in selos:
            c = cor(prop(s, "color"), *cam)
            f = cor(prop(s, "background"), *cam) if s.startswith(".st-") and prop(s, "background") else fundo_selo
            if c and f:
                exige(contraste(c, f) >= 4.5, "AC", f"contraste {s} ({tema}): {contraste(c, f):.2f} < 4,5")
            else:
                falha("AC", f"{s}: cor ou fundo não resolve para hexadecimal ({tema})")
        for sel in (".selo.ok", ".selo.alerta", ".selo.solucao-nomeada", ".selo.texto-completo", ".selo.robots-proibido", ".selo.robots-preventivo"):
            c, f = cor(prop(sel, "color"), *cam), cor(prop(sel, "background"), *cam)
            if exige(c and f, "AC", f"{sel}: color/background precisam resolver para hexadecimal ({tema})"):
                exige(contraste(c, f) >= 4.5, "AC", f"contraste {sel} ({tema}): {contraste(c, f):.2f} < 4,5")
        c = cor(prop(".selo.neutro", "color"), *cam)
        if exige(c and fundo_selo, "AC", f".selo.neutro ({tema})"):
            exige(contraste(c, fundo_selo) >= 4.5, "AC", f"contraste .selo.neutro ({tema})")
        for b in (".banner-real", ".banner-simulado", ".banner-demo"):
            c, f = cor(prop(b, "color"), *cam), cor(prop(b, "background"), *cam)
            if exige(c and f, "AC", f"{b}: color/background ({tema})"):
                exige(contraste(c, f) >= 4.5, "AC", f"contraste {b} ({tema}): {contraste(c, f):.2f}")
                op = prop(".banner-detalhe", "opacity")
                if op:
                    exige(contraste(mistura(c, f, float(op)), f) >= 4.5, "AC", f".banner-detalhe sobre {b} ({tema}) com opacity {op}")
        for a, b in TEXTO_45:
            x, y = cor(f"var({a})", *cam), cor(f"var({b})", *cam)
            if exige(x and y, "AC", f"{a}/{b} não resolvem ({tema})"):
                exige(contraste(x, y) >= 4.5, "AC", f"contraste {a} sobre {b} ({tema}): {contraste(x, y):.2f}")
        for a, b in COMPONENTE_3:
            x, y = cor(f"var({a})", *cam), cor(f"var({b})", *cam)
            if x and y:
                exige(contraste(x, y) >= 3, "AC", f"contraste de componente {a} sobre {b} ({tema}): {contraste(x, y):.2f} < 3")
    exige("solid" in (prop(".selo.robots-proibido", "border") or ""), "DS", ".selo.robots-proibido: border com 'solid'")
    exige("dashed" in (prop(".selo.robots-preventivo", "border") or ""), "DS", ".selo.robots-preventivo: border com 'dashed'")
    exige(prop(".selo.robots-proibido", "color") != prop(".selo.robots-preventivo", "color") and prop(".selo.robots-proibido", "background") != prop(".selo.robots-preventivo", "background"),
          "DS", "as duas razões de robots precisam diferir em cor e em fundo")

    # --- ordenação
    linhas = [l for l in raw.split("\n") if re.search(r"ordenar|aria-sort|atalho-dica", l)]
    exige(len(linhas) >= 8, "IN", f"precisa de ≥8 linhas físicas com ordenar/aria-sort/atalho-dica (há {len(linhas)})")
    exige(not any(HEX.search(l) for l in linhas), "IN", "linha de ordenação com hexadecimal")
    juntas = " ".join(linhas)
    exige("var(--acento)" in juntas and "var(--texto)" in juntas, "IN", "as linhas de ordenação precisam citar var(--acento) e var(--texto)")

    # --- impressão
    pr = list(achatar(corpo_print))
    def imp(sel):
        return [d for c, s, d in pr if sel in seletores(s)]
    for sel in (".menu", ".pular", ".filtros", ".paginacao", "button", ".botao"):
        exige(any((decl_de(d, "display") or "").startswith("none") for d in imp(sel)), "NA", f"impressão: '{sel}' com display: none")
    exige(any((decl_de(d, "display") or "") == "table-header-group" for d in imp("thead")), "NA", "impressão: thead { display: table-header-group }")
    for sel in ("svg", "figure", ".cartao", "tr"):
        exige(any((decl_de(d, "break-inside") or "") == "avoid" for d in imp(sel)), "NA", f"impressão: break-inside: avoid em {sel}")
    exige(any((decl_de(d, "background") or "") == "none" for d in imp(".banner")), "NA", "impressão: .banner com background: none")
    exige(not any((decl_de(d, "display") or "").startswith("none") for sel in (".banner", "h1") for d in imp(sel)), "NA", "impressão: .banner e h1 não podem sumir")
    exige(any((decl_de(d, "display") or "") == "block" for d in imp(".layout")), "NA", "impressão: .layout { display: block }")
    exige(any((decl_de(d, "max-width") or "") == "none" for d in imp("main")), "NA", "impressão: main { max-width: none }")
    exige(any((decl_de(d, "overflow") or "") == "visible" for d in imp(".tabela-rolavel")), "NA", "impressão: .tabela-rolavel { overflow: visible }")
    for s in ("th button.ordenar", ".ordenar-seta", "display: none !important"):
        exige(s in corpo_print, "IN", f"impressão: falta '{s}'")
    return dict(L=L, D=D, P=P, regras=regras)


# ------------------------------------------------------------------------------------------------------------- folhas satélites
def checar_satelite(nome, raw, painel):
    css = sem_coment(raw)
    exige(css.count("{") == css.count("}"), "AC", f"{nome}: chaves desbalanceadas")
    fora = re.sub(r":root\s*\{[^}]*\}", "", css)
    for m in HEX.finditer(fora):
        falha("NA", f"{nome}: hexadecimal fora de :root: ...{fora[max(0, m.start() - 50):m.end() + 10].strip()}...")
    for m in re.finditer(r"\brgba?\(\s*([^)]*)\)", fora):
        if nome != "painel.css" and not m.group(0).startswith("rgba(0, 0, 0"):
            falha("NA", f"{nome}: {m.group(0)} (só rgba(0, 0, 0 é tolerado fora de painel.css)")
    exige("outline: none" not in raw and "outline:none" not in raw, "AC", f"{nome}: outline: none")
    if nome == "solucoes.css":
        for l in raw.split("\n"):
            if re.search(r"solucao-|robots-|texto-completo|indicador|presenca|sem-nome|legenda-", l) and HEX.search(l):
                falha("DS", f"solucoes.css: hexadecimal em linha de seletor protegido: {l.strip()[:90]}")
    if nome in ("metodologia.css",):
        exige("body.relatorio { background: var(--superficie); color: var(--texto); color-scheme: light; }" in raw, "NA", "metodologia.css: falta a literal de body.relatorio")
        baixo = raw.lower()
        for s in PROIBIDOS:
            exige(s not in baixo, "RL", f"metodologia.css contém '{s}'")
        exige("<" not in raw, "RL", "metodologia.css contém '<'")
        exige("prefers-color-scheme" not in remover_bloco(raw, "@media (prefers-color-scheme: dark)"), "RL", "metodologia.css: 'prefers-color-scheme' fora do bloco escuro")
        exige("@media print" in raw and "color-scheme: light" in raw, "RL", "metodologia.css: precisa de @media print e color-scheme: light")


def checar_analises(raw, painel):
    css = sem_coment(raw)
    nome = "analises.css"
    exige(css.count("{") == css.count("}"), "GA", "analises.css: chaves desbalanceadas")
    for s in ("@import", "http", "expression(", "javascript:"):
        exige(s not in raw, "GA", f"analises.css contém '{s}'")
    exige("outline: none" not in raw and "outline:none" not in raw, "GA", "analises.css: outline: none")
    for s in ("prefers-color-scheme: dark", "@media print", ":focus-visible"):
        exige(s in raw, "GA", f"analises.css: falta '{s}'")
    fora = re.sub(r":root\s*\{[^}]*\}", "", css)
    for m in HEX.finditer(fora):
        falha("NA", f"analises.css: hexadecimal fora de :root: ...{fora[max(0, m.start() - 50):m.end() + 10].strip()}...")
    exige(not re.search(r"\brgba?\(", fora) or all(m.group(0).startswith("rgba(0, 0, 0") for m in re.finditer(r"\brgba?\([^)]*\)", fora)), "NA", "analises.css: rgb()/rgba() fora do :root")
    bl = blocos(css)
    primeiro_raiz = next((c for p, c in bl if p == ":root"), None)
    if not exige(primeiro_raiz is not None, "NA", "analises.css: falta :root"):
        return
    T1 = tokens(primeiro_raiz)
    exige(all(k.startswith("--an-") for k in T1), "NA", f"analises.css: o primeiro :root só pode ter --an-*: {[k for k in T1 if not k.startswith('--an-')]}")
    for t in "texto suave borda fundo acento ok ok-fundo perigo perigo-fundo alerta alerta-fundo k-quase cal-alta descartado-ln".split():
        v = T1.get(f"--an-{t}")
        exige(v is not None and re.fullmatch(r"var\(--[\w-]+\)", v), "NA", f"analises.css: --an-{t} precisa ser var(--...) sem reserva (está {v})")
    dk = next((c for p, c in bl if p == "@media (prefers-color-scheme: dark)"), "")
    D2 = {}
    for p, c in blocos(dk):
        if p == ":root":
            D2 = tokens(c)
    pr = next((c for p, c in bl if p == "@media print"), "")
    P2 = {}
    for p, c in blocos(pr):
        if p == ":root":
            P2 = tokens(c)
    L, D, P = painel["L"], painel["D"], painel["P"]
    for i in range(1, 5):
        exige(resolve(f"--an-calor{i}", T1, L) == resolve(f"--calor-{i}", L), "NA", f"--an-calor{i} difere de --calor-{i} (claro)")
        exige(resolve(f"--an-calor{i}", T1, D2, L, D) == resolve(f"--calor-{i}", L, D), "NA", f"--an-calor{i} difere de --calor-{i} (escuro)")
        # o teste pode comparar o TEXTO dos dois tokens, sem resolver var(): precisa dar igual assim também
        exige((T1.get(f"--an-calor{i}") or "").lower() == (L.get(f"--calor-{i}") or "").lower(), "NA", f"--an-calor{i} e --calor-{i} diferem como texto (claro)")
        exige((D2.get(f"--an-calor{i}") or "").lower() == (D.get(f"--calor-{i}") or "").lower(), "NA", f"--an-calor{i} e --calor-{i} diferem como texto (escuro)")
    # estágios e níveis: hexadecimal de 6 dígitos com contraste >= 4,5 nos dois temas
    for tema, camadas in (("claro", (T1,)), ("escuro", (T1, D2))):
        env = {}
        for c in camadas:
            env.update(c)
        for k in [k for k in env if re.fullmatch(r"--an-(?!calor)[\w]+-tx", k)]:
            base = k[:-3]
            if base in env:
                f, t = env[base], env[k]
                if HEX.fullmatch(f) and HEX.fullmatch(t):
                    exige(contraste(f.lower(), t.lower()) >= 4.5, "GA", f"contraste {k} sobre {base} ({tema}): {contraste(f.lower(), t.lower()):.2f}")
        for i in range(0, 5):
            f, t = env.get(f"--an-calor{i}"), env.get(f"--an-calor-tx{i}")
            if f and t:
                fr = resolve(f"--an-calor{i}", env, L) if not HEX.fullmatch(f) else f
                tr = resolve(f"--an-calor-tx{i}", env, L) if not HEX.fullmatch(t) else t
                if tema == "escuro":
                    fr = resolve(f"--an-calor{i}", env, L, D) if not HEX.fullmatch(f) else f
                if fr and tr and HEX.fullmatch(fr) and HEX.fullmatch(tr):
                    exige(contraste(fr.lower(), tr.lower()) >= 4.5, "GA", f"contraste --an-calor-tx{i} ({tema}): {contraste(fr.lower(), tr.lower()):.2f}")
    # impressão: sem var(), mesmo conjunto do claro, e literais iguais aos de painel.css nos 14 pares
    exige(P2 and not any("var(" in v for v in P2.values()), "GA", "analises.css: o :root de impressão não pode ter var()")
    exige(set(T1) <= set(P2), "GA", f"analises.css: tokens do claro ausentes na impressão: {sorted(set(T1) - set(P2))[:6]}")
    pares = {"--an-texto": "--texto", "--an-suave": "--texto-suave", "--an-borda": "--borda", "--an-fundo": "--superficie", "--an-acento": "--acento", "--an-perigo": "--perigo",
             "--an-ok": "--ok", "--an-ok-fundo": "--ok-fundo", "--an-perigo-fundo": "--perigo-fundo", "--an-alerta": "--alerta", "--an-alerta-fundo": "--alerta-fundo",
             "--an-k-quase": "--ok", "--an-cal-alta": "--ok", "--an-descartado-ln": "--perigo"}
    for a, b in pares.items():
        va = (P2.get(a) or "").lower()
        vb = (resolve(b, L, P) or "").lower()
        exige(va == vb, "NA", f"impressão de analises.css: {a} = {va} mas {b} da impressão de painel.css = {vb}")
        # o teste pode comparar o TEXTO do token de impressão de painel.css (sem resolver var()): então ele tem de ser o mesmo hexadecimal
        exige(va == (P.get(b) or "").lower(), "NA", f"impressão: {b} de painel.css é '{P.get(b)}' (não é o literal {va} de {a}): um teste que compara texto falharia")
    # comentários que o teste DS procura, em ordem, sem hexadecimal entre eles
    i1 = raw.find("razões de bloqueio pelo robots.txt")
    i2 = raw.find("selos estatísticos")
    if exige(i1 >= 0 and i2 > i1, "DS", "analises.css: faltam os comentários 'razões de bloqueio pelo robots.txt' e depois 'selos estatísticos'"):
        exige(not HEX.search(raw[i1:i2]), "DS", "analises.css: hexadecimal entre os comentários 'razões de bloqueio...' e 'selos estatísticos'")
    for s in (".an-seg ", ".an-seg{", ".an-area-s ", ".an-c ", ".an-col "):
        for m in re.finditer(re.escape(s) + r"[^{]*\{([^}]*)\}", css):
            exige("fill:" not in m.group(1), "GA", f"analises.css: regra de '{s.strip()}' declara fill:")
    exige(re.search(r"\.an-svg\s*\{[^}]*width:\s*100%[^}]*height:\s*auto", css), "SV", "analises.css: .an-svg { width: 100% ... height: auto }")
    for c, s, d in achatar(css):
        if "svg" in s and re.search(r"(?<![\w-])width:\s*\d+(\.\d+)?px", d):
            falha("SV", f"analises.css: regra com 'svg' fixa width em px: {s}")
    classes = set(re.findall(r"\.([a-zA-Z_][\w-]*)", " ".join(s for c, s, d in achatar(css))))
    for c in ("ev-forte", "ev-moderada", "ev-insuficiente", "ev-sem"):
        exige(c in classes, "GA", f"analises.css: falta a classe .{c}")


# ------------------------------------------------------------------------------------------------------------- V5: nada de barra de destaque num lado só
LADOS = r"(left|right|top|bottom|inline-start|inline-end|block-start|block-end)"
SEMANTICAS = ("--acento", "--tom-", "--inclusao", "--exclusao", "--duvida", "--perigo", "--ok", "--alerta", "--st-", "--marca", "--menu-anel", "--foco", "--an-acento", "--an-ok", "--an-perigo", "--an-alerta")
COMPRIMENTO = re.compile(r"(-?\d*\.?\d+)(px|rem|em)\b")


def px(txt):
    m = COMPRIMENTO.search(txt)
    if not m:
        return None
    n = float(m.group(1))
    return n * (16 if m.group(2) in ("rem", "em") else 1)


def checar_barras(nome, raw):
    css = sem_coment(raw)
    for ctx, sel, corpo in achatar(css):
        if sel.startswith("@") or sel.startswith(":root"):
            continue
        d = dict(decls(corpo))
        for prop_, val in decls(corpo):
            m = re.fullmatch(rf"border-{LADOS}(-width)?", prop_)
            if m:
                if val.strip() in ("0", "none", "0px"):
                    continue
                larg = px(val)
                if larg is not None and larg >= 2:
                    falha("V5", f"{nome}: '{sel}' tem {prop_}: {val} (barra de destaque num lado só)")
                elif prop_.endswith("-width") is False and any(s in val for s in SEMANTICAS):
                    falha("V5", f"{nome}: '{sel}' tem {prop_}: {val} (filete de cor semântica num lado só)")
            if prop_ == "box-shadow":
                for sombra in re.split(r",(?![^()]*\))", val):
                    t = sombra.strip()
                    if not t or t == "none":
                        continue
                    sem_cor = re.sub(r"rgba?\([^)]*\)", "", t)
                    nums = [px(x) if x not in ("0",) else 0 for x in re.findall(r"-?\d*\.?\d+(?:px|rem|em)?", sem_cor)]
                    nums = [(0 if n is None else n) for n in nums]
                    if len(nums) < 2:
                        continue
                    x, y = nums[0], nums[1]
                    blur = nums[2] if len(nums) > 2 else 0
                    spread = nums[3] if len(nums) > 3 else 0
                    so_um_eixo = (x == 0) != (y == 0)
                    neutra = ("rgba(255, 255, 255" in t) or ("rgba(0, 0, 0" in t) or ("var(--borda" in t) or ("var(--realce" in t) or ("var(--sombra" in t) or ("var(--menu-borda" in t)
                    if so_um_eixo and blur == 0 and max(abs(x), abs(y)) >= 2 and not neutra:
                        falha("V5", f"{nome}: '{sel}' tem box-shadow de barra num lado só: {t}")
                    elif so_um_eixo and blur == 0 and spread == 0 and not neutra and any(s in t for s in SEMANTICAS):
                        falha("V5", f"{nome}: '{sel}' tem filete de sombra num lado só em cor semântica: {t}")
        # tira pseudo-elemento fina colada numa aresta
        if re.search(r"::(before|after)\s*$", sel) or re.search(r"::(before|after),", sel):
            if d.get("position") == "absolute" and d.get("background") and d.get("content") in ('""', "''"):
                w, h = px(d.get("width", "")), px(d.get("height", ""))
                t0 = lambda k: d.get(k, "").strip() in ("0", "0px")
                if w is not None and w <= 6 and (t0("top") and t0("bottom") or d.get("height", "").strip() == "100%") and (t0("left") or t0("right")):
                    falha("V5", f"{nome}: '{sel}' é uma tira vertical colada na borda (barra de destaque)")
                if h is not None and h <= 6 and t0("left") and t0("right") and (t0("top") or t0("bottom")) and "gradient" not in d["background"]:
                    falha("V5", f"{nome}: '{sel}' é uma tira horizontal colada na borda (barra de destaque)")


# ------------------------------------------------------------------------------------------------------------- cobertura contra o CSS original
def classes_de_seletores(css):
    css = sem_coment(css)
    alvo = []
    for c, s, d in achatar(css):
        if s.startswith("@") or s.startswith(":root"):
            continue
        alvo.append(s)
    return set(re.findall(r"\.([a-zA-Z_][\w-]*)", " ".join(alvo)))


def cobertura():
    if not ORIG:
        return
    novas = set()
    for p in PASTA.glob("*.css"):
        novas |= classes_de_seletores(p.read_text(encoding="utf-8"))
    sumiram = {}
    for p in sorted(ORIG.glob("*.css")):
        antigas = classes_de_seletores(p.read_text(encoding="utf-8"))
        falt = sorted(antigas - novas)
        if falt:
            sumiram[p.name] = falt
    for nome, lst in sumiram.items():
        NOTAS.append(f"[COB] {nome}: {len(lst)} classe(s) do original sem regra na v5: {', '.join(lst)}")


def main():
    arqs = {}
    for nome in ("painel.css", "analises.css", "solucoes.css", "classificadores.css", "metodologia.css", "relevancia.css", "triagem_escopo.css"):
        arqs[nome] = ler(nome)
    painel = None
    if arqs["painel.css"]:
        painel = checar_painel(arqs["painel.css"])
    for nome, raw in arqs.items():
        if raw is None:
            continue
        if nome == "analises.css":
            if painel:
                checar_analises(raw, painel)
        elif nome != "painel.css":
            checar_satelite(nome, raw, painel)
        checar_barras(nome, raw)
    cobertura()
    for f in FALHAS:
        print("FALHA", f)
    for n in NOTAS:
        print("NOTA ", n)
    print(f"\nlint_css: {len(FALHAS)} falha(s), {len(NOTAS)} nota(s) — pasta {PASTA}")
    return 1 if FALHAS else 0


if __name__ == "__main__":
    sys.exit(main())
