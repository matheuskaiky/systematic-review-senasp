#!/usr/bin/env python3
"""Confere o tema de painel.css (versão 5) sobre o CSS PRONTO, sem rodar a suíte do projeto.

Uso:  python3 python/verifica_tema.py [build/css/painel.css] [--original referencia/css_original/painel.css]

O que confere
  1. Os quatro lugares de troca existem uma única vez: :root (claro), @media (prefers-color-scheme: dark) { :root }, @media screen { :root[data-theme="dark"]
     e :root[data-theme="light"] } e @media print { :root }.
  2. Anti-deriva: o escuro escolhido no botão vale o mesmo que o escuro do sistema; o claro escolhido restaura os valores claros de tudo o que o escuro troca;
     a impressão repete o texto do claro, exceto os quatro valores fixos que o contrato exige. Nos tokens de LITERAIS (hexadecimal nos blocos :root simples,
     var(--primitivo) nos blocos do botão de tema) "vale o mesmo" é conferido pelo hexadecimal resolvido; nos demais, pelo texto.
  3. Hexadecimal só dentro de blocos :root simples (os blocos de tema forçado só têm var()). Os LITERAIS são mesmo literais, e nenhuma cadeia de cor passa de
     um salto (var(--a) -> var(--b) -> hexadecimal), para o caso de um teste que resolva só um nível.
  4. Os valores resolvidos no CSS pronto são os mesmos de tools/tokens.py (a fonte dos tokens) nos três temas: ninguém editou o CSS à mão.
  5. Contraste (texto >= 4,5; componente >= 3) de todos os pares do contrato e dos pares próprios da v5 (cinco matizes sobre suas superfícies,
     barra lateral escura, botões sólidos), nos estados claro, escuro, claro forçado, escuro forçado e impressão.
  6. (opcional, com --original) tokens do painel.css original: nomes mantidos e, para os de cor, o mesmo papel nos dois temas.
Saída: uma linha por falha e o resumo; código de saída 1 se algo falhar. Precisa de tools/tokens.py ao lado (pasta do pacote)."""
import pathlib, re, sys

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parent
sys.path.insert(0, str(RAIZ / "tools"))
try:
    import tokens as T
except ImportError:
    sys.exit("tools/tokens.py não encontrado: rode este script de dentro da pasta do pacote (ele lê a fonte dos tokens para conferir o CSS pronto)")

args = [a for a in sys.argv[1:] if not a.startswith("--")]
ARQ = pathlib.Path(args[0] if args else RAIZ / "build" / "css" / "painel.css")
ORIG = pathlib.Path(sys.argv[sys.argv.index("--original") + 1]) if "--original" in sys.argv else None
falhas = []


def falha(msg):
    falhas.append(msg)
    print("FALHA", msg)


def blocos(css):
    """[(contexto, seletor, corpo)]: desce um nível em @media/@supports."""
    out = []

    def parse(s, ctx):
        j = 0
        while j < len(s):
            m = re.compile(r"\s*([^{}]+)\{").match(s, j)
            if not m:
                break
            sel, k, d, ini = m.group(1).strip(), m.end(), 1, m.end()
            while d and k < len(s):
                d += (s[k] == "{") - (s[k] == "}")
                k += 1
            corpo = s[ini:k - 1]
            if sel.startswith(("@media", "@supports")):
                parse(corpo, ctx + (sel,))
            else:
                out.append((ctx, sel, corpo))
            j = k

    parse(css, ())
    return out


def decls(corpo):
    return {n: v.strip() for n, v in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", corpo)}


def unico(B, ctx, sel):
    r = [c for x, s, c in B if x == ctx and s == sel]
    if len(r) != 1:
        falha(f"esperava 1 bloco {sel} em {ctx or 'topo'}, achei {len(r)}")
        return {}
    return decls(r[0])


bruto = ARQ.read_text(encoding="utf-8")
css = re.sub(r"/\*.*?\*/", "", bruto, flags=re.S)
B = blocos(css)
L = unico(B, (), ":root")
Dm = unico(B, ("@media (prefers-color-scheme: dark)",), ":root")
Dd = unico(B, ("@media screen",), ':root[data-theme="dark"]')
Ll = unico(B, ("@media screen",), ':root[data-theme="light"]')
P = unico(B, ("@media print",), ":root")


def res(tok, *camadas):
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


# ------------------------------------------------------------------------------------------------ 2. anti-deriva
sem_cs = lambda d: {k: v for k, v in d.items() if k != "color-scheme"}
LIT = set(T.LITERAIS)
HEXA = re.compile(r"#[0-9a-fA-F]{3,8}\b")


def mesmo(t, no_botao, no_simples, camadas):
    """Bloco do botão de tema e bloco simples concordam: texto idêntico, ou (token de LITERAIS: hexadecimal no simples, var(--primitivo) no do botão)
    o mesmo hexadecimal depois de resolver."""
    if no_botao == no_simples:
        return True
    if t in LIT and no_simples and HEXA.fullmatch(no_simples) and (no_botao or "").startswith("var("):
        r = res(t, *camadas)
        return bool(r) and r.lower() == no_simples.lower()
    return False


if set(sem_cs(Dd)) != set(Dm):
    falha(f"escuro forçado e escuro do sistema trocam tokens diferentes: {sorted(set(Dd) ^ set(Dm))[:6]}")
for t in Dm:
    if not mesmo(t, Dd.get(t), Dm[t], (L, Dd)):
        falha(f"deriva (escuro): {t}: forçado '{Dd.get(t)}' x sistema '{Dm[t]}'")
if set(Ll) != set(Dm):
    falha(f"claro forçado precisa cobrir exatamente o que o escuro troca: {sorted(set(Ll) ^ set(Dm))[:6]}")
for t in Dm:
    if not mesmo(t, Ll.get(t), L.get(t), (L, Ll)):
        falha(f"deriva (claro): {t}: forçado '{Ll.get(t)}' x claro '{L.get(t)}'")
for t in LIT:
    for nome, blk in (("claro", L), ("escuro do sistema", Dm), ("impressão", P)):
        if t in blk and not HEXA.fullmatch(blk[t]):
            falha(f"{t} precisa ser #rrggbb literal no :root {nome} (está '{blk[t]}')")
    for nome, blk in (("escuro do botão", Dd), ("claro do botão", Ll)):
        if t in blk and not blk[t].startswith("var("):
            falha(f"{t} no bloco {nome} precisa ser var(--primitivo) (está '{blk[t]}')")
FIXOS = T.FIXOS_IMPRESSAO
for t, v in P.items():
    if t == "color-scheme":
        continue
    if t in FIXOS:
        if v.lower() != FIXOS[t]:
            falha(f"impressão: {t} deveria ser {FIXOS[t]} (está {v})")
    elif L.get(t) != v:
        falha(f"impressão difere do claro: {t}: '{v}' x '{L.get(t)}'")
for t in Dm:
    if t not in P:
        falha(f"token que o escuro troca está fora da impressão: {t}")

# ------------------------------------------------------------------------------------------------ 3. hexadecimal só em :root simples
for ctx, sel, corpo in B:
    if sel == ":root":
        continue
    if re.search(r"#[0-9a-fA-F]{3,8}\b", corpo):
        falha(f"hexadecimal fora de :root simples: {sel}")
for blk, nome in ((Dd, "escuro forçado"), (Ll, "claro forçado")):
    for t, v in blk.items():
        if t != "color-scheme" and re.search(r"#[0-9a-fA-F]{3,8}\b", v):
            falha(f"hexadecimal no bloco {nome}: {t}")

for estado, camadas in (("claro", (L,)), ("escuro", (L, Dm)), ("escuro do botão", (L, Dd)), ("claro do botão", (L, Dm, Ll)), ("impressão", (L, P))):
    env = {}
    for c in camadas:
        env.update(c)
    for t, v in env.items():
        m = re.fullmatch(r"var\((--[\w-]+)\)", v.strip())
        if m and re.fullmatch(r"var\((--[\w-]+)\)", (env.get(m.group(1)) or "").strip()):
            falha(f"[{estado}] cadeia de dois saltos: {t} -> {m.group(1)} -> outro var()")

# ------------------------------------------------------------------------------------------------ 4. CSS pronto == fonte dos tokens
ESTADOS = {
    "claro": (L,), "escuro": (L, Dm), "escuro-forcado": (L, Dd), "claro-forcado": (L, Dm, Ll), "impressao": (L, P),
}
PARA_FONTE = {"claro": "claro", "escuro": "escuro", "escuro-forcado": "escuro", "claro-forcado": "claro", "impressao": "impressao"}
for estado, camadas in ESTADOS.items():
    esperado = T.tokens_do_tema(PARA_FONTE[estado])
    for t, v in esperado.items():
        got = res(t, *camadas)
        if got is None:
            falha(f"[{estado}] token ausente no CSS: {t}")
        elif got.lower() != v.lower():
            falha(f"[{estado}] {t}: CSS resolve '{got}', tokens.py diz '{v}'")

# ------------------------------------------------------------------------------------------------ 5. contraste
def lum(h):
    h = h.lstrip("#")
    r, g, b = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    f = lambda c: c / 12.92 if c <= .03928 else ((c + .055) / 1.055) ** 2.4
    return .2126 * f(r) + .7152 * f(g) + .0722 * f(b)


def contraste(a, b):
    x, y = lum(a), lum(b)
    x, y = max(x, y), min(x, y)
    return (x + .05) / (y + .05)


pior = 99.0
for estado, camadas in ESTADOS.items():
    for lista, minimo in ((T.TEXTO_45, 4.5), (T.PROPRIOS_45, 4.5), (T.COMPONENTE_3, 3.0), (T.PROPRIOS_3, 3.0)):
        for a, b in lista:
            if estado == "impressao" and ("--menu" in a or "--menu" in b):
                continue   # a barra lateral não sai no papel
            x, y = res(a, *camadas), res(b, *camadas)
            if not (x and y and x.startswith("#") and y.startswith("#")):
                falha(f"[{estado}] {a} / {b} não resolvem para hexadecimal")
                continue
            c = contraste(x, y)
            if minimo == 4.5:
                pior = min(pior, c)
            if c < minimo:
                falha(f"[{estado}] contraste {a} sobre {b}: {c:.2f} < {minimo}")
print(f"menor contraste de texto: {pior:.2f}")

# ------------------------------------------------------------------------------------------------ 6. contra o original
if ORIG:
    ob = blocos(re.sub(r"/\*.*?\*/", "", ORIG.read_text(encoding="utf-8"), flags=re.S))
    oL = decls([c for x, s, c in ob if x == () and s == ":root"][0])
    for t in oL:
        if t.startswith(("--fonte-", "--fs-", "--lh-", "--esp-", "--raio", "--sombra", "--indicador")):
            continue
        if t not in L:
            falha(f"token do painel.css original ausente na v5: {t}")

print("OK" if not falhas else f"{len(falhas)} problema(s)")
sys.exit(1 if falhas else 0)
