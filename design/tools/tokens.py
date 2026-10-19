#!/usr/bin/env python3
"""Fonte única dos tokens de cor do painel (versão 5, "Observatório").

Tudo o que muda de valor entre temas mora aqui; `gerar_painel_css.py` lê este módulo e escreve os quatro lugares de troca de tema
(:root, @media (prefers-color-scheme: dark), @media screen [data-theme], @media print) em painel.css. `verifica_tema.py` e
`test_tema_deriva.py` conferem depois, no CSS pronto, que nada divergiu.

Camada 1 (PRIM): escalas estáticas; nenhum tema mexe nelas.
Camada 2 (SEM_CLARO / SEM_ESCURO): os nomes que os componentes usam, apontando para a camada 1 com var(). NUNCA para outro token da camada 2:
toda cadeia de cor tem no máximo UM salto até o hexadecimal (var(--primitivo)). Nomes que valem o mesmo que outro (--ok = --inclusao) são ESPELHOS:
recebem o mesmo primitivo do original, não var(--original).
Os tokens de LITERAIS (os que testes comparam entre arquivos ou entre blocos, como texto) saem como #rrggbb nos blocos :root simples (claro, escuro do
sistema e impressão) e como var(--primitivo) nos blocos do botão de tema, que não podem ter hexadecimal. Os poucos valores fixos (banner) vão direto como #rrggbb.
"""
import re, sys

# ------------------------------------------------------------------ camada 1: primitivos
PRIM = {
    # neutros "tinta" (azul-acinzentado frio; do papel ao grafite)
    "tinta-0": "#ffffff", "tinta-25": "#fbfcfe", "tinta-50": "#f2f5fa", "tinta-75": "#e9eef6", "tinta-100": "#dfe6f1",
    "tinta-150": "#cfd8e6", "tinta-200": "#b6c2d6", "tinta-300": "#7e8ca6", "tinta-400": "#5f6d87", "tinta-500": "#475570",
    "tinta-700": "#27324a", "tinta-900": "#121a2c",
    "noite-0": "#e8edf7", "noite-100": "#c5cfe2", "noite-200": "#a3afc6", "noite-300": "#8995ae", "noite-400": "#66769a",
    "noite-500": "#2c3c5e", "noite-600": "#223250", "noite-700": "#1a2744", "noite-800": "#141e36", "noite-850": "#101828",
    "noite-900": "#0c1424", "noite-950": "#080e1b",
    # cobalto (marca e ação)
    "cobalto-50": "#e7eefd", "cobalto-100": "#d3e0fb", "cobalto-200": "#b6caf7", "cobalto-300": "#8fb0ff", "cobalto-500": "#3366e8",
    "cobalto-600": "#2a5bd7", "cobalto-700": "#1f47b0", "cobalto-900": "#1b2a55", "cobalto-950": "#0d1633",
    # petróleo (dados, estados, achados)
    "petroleo-50": "#dff5f2", "petroleo-100": "#c0ebe5", "petroleo-300": "#5fd6c8", "petroleo-500": "#10948a", "petroleo-700": "#0b6a64",
    "petroleo-900": "#0e3331", "petroleo-950": "#082422",
    # violeta (análises e qualidade)
    "violeta-50": "#ede9fc", "violeta-100": "#dad2f8", "violeta-300": "#b8a8ff", "violeta-500": "#7352e6", "violeta-700": "#5a39c2",
    "violeta-900": "#2a2150", "violeta-950": "#1a1438",
    # âmbar (operação, aviso, dúvida)
    "ambar-25": "#fffaf0", "ambar-50": "#fef3df", "ambar-100": "#fbe3b8", "ambar-300": "#f4b95c", "ambar-500": "#c9690a", "ambar-700": "#8f4a04",
    "ambar-800": "#6a4a14", "ambar-900": "#35260d", "ambar-950": "#271c0a",
    # rosa (literatura e leitura)
    "rosa-50": "#fce9f3", "rosa-100": "#f7cfe4", "rosa-300": "#f59ccb", "rosa-500": "#c02a82", "rosa-700": "#a0206a",
    "rosa-900": "#3d1731", "rosa-950": "#2a0f23",
    # semânticas da revisão: inclusão (verde-floresta), exclusão (terracota), perigo (vermelho)
    "esmeralda-25": "#f1faf5", "esmeralda-50": "#e2f6ec", "esmeralda-100": "#c4ecd8", "esmeralda-200": "#a5dfc2", "esmeralda-300": "#4fd39c",
    "esmeralda-600": "#0e8a5a", "esmeralda-700": "#0b7249", "esmeralda-750": "#1d6048", "esmeralda-800": "#075a3a", "esmeralda-850": "#07553a",
    "esmeralda-900": "#064431", "esmeralda-950": "#0c2a22",
    "terracota-50": "#fbede7", "terracota-200": "#f0cfc3", "terracota-300": "#ee9f87", "terracota-700": "#9a4128", "terracota-800": "#6e4338",
    "terracota-950": "#2f1f1b",
    "vermelho-50": "#fdebe9", "vermelho-300": "#f7a29b", "vermelho-700": "#b0231a", "vermelho-900": "#3a1c1d",
    # marca-texto do trecho citado
    "amarelo-100": "#f9efb5", "amarelo-300": "#e6c93a", "amarelo-500": "#cfae20", "amarelo-900": "#4a4219",
}

# ------------------------------------------------------------------ camada 2: semânticos
# Cada entrada: token -> nome do primitivo (vira var(--nome)) ou literal "#rrggbb"/valor CSS (começa com # ou contém espaço/parênteses).
TONS = ("cobalto", "petroleo", "violeta", "ambar", "rosa")

SEM_CLARO = {
    "--fundo": "tinta-50", "--superficie": "tinta-0", "--superficie-subtil": "tinta-75", "--superficie-elevada": "tinta-0",
    "--texto": "tinta-900", "--texto-suave": "tinta-500", "--texto-mutado": "tinta-400", "--texto-botao": "tinta-0",
    "--borda": "tinta-100", "--borda-forte": "tinta-150", "--borda-controle": "tinta-300",
    "--acento": "cobalto-600", "--acento-fundo": "cobalto-50", "--acento-borda": "cobalto-200",
    "--inclusao": "esmeralda-700", "--inclusao-fundo": "esmeralda-50", "--inclusao-borda": "esmeralda-200",
    "--exclusao": "terracota-700", "--exclusao-fundo": "terracota-50", "--exclusao-borda": "terracota-200",
    "--duvida": "ambar-700", "--duvida-fundo": "ambar-50", "--duvida-fundo-suave": "ambar-25", "--duvida-borda": "ambar-100",
    "--perigo": "vermelho-700", "--perigo-fundo": "vermelho-50",
    "--marca": "amarelo-100", "--marca-borda": "amarelo-500", "--marca-aprox": "cobalto-100",
    "--st-anunciado": "violeta-700", "--st-anunciado-fundo": "violeta-50",
    "--st-em_estudo": "petroleo-700", "--st-em_estudo-fundo": "petroleo-50",
    # solido da inclusão (botão "Incluir" quando escolhido)
    "--inclusao-solido": "esmeralda-700", "--inclusao-solido-hover": "esmeralda-800", "--inclusao-solido-borda": "esmeralda-800", "--inclusao-solido-texto": "esmeralda-25",
    # tons de página (cinco matizes): texto/ícone sobre superfície, fundo suave, borda do fundo suave, sólido de ladrilho e texto sobre o sólido
    "--tom-cobalto-tx": "cobalto-600", "--tom-cobalto-fundo": "cobalto-50", "--tom-cobalto-borda": "cobalto-200", "--tom-cobalto-solido": "cobalto-500", "--tom-cobalto-solido-tx": "tinta-0",
    "--tom-petroleo-tx": "petroleo-700", "--tom-petroleo-fundo": "petroleo-50", "--tom-petroleo-borda": "petroleo-100", "--tom-petroleo-solido": "petroleo-500", "--tom-petroleo-solido-tx": "tinta-0",
    "--tom-violeta-tx": "violeta-700", "--tom-violeta-fundo": "violeta-50", "--tom-violeta-borda": "violeta-100", "--tom-violeta-solido": "violeta-500", "--tom-violeta-solido-tx": "tinta-0",
    "--tom-ambar-tx": "ambar-700", "--tom-ambar-fundo": "ambar-50", "--tom-ambar-borda": "ambar-100", "--tom-ambar-solido": "ambar-500", "--tom-ambar-solido-tx": "tinta-0",
    "--tom-rosa-tx": "rosa-700", "--tom-rosa-fundo": "rosa-50", "--tom-rosa-borda": "rosa-100", "--tom-rosa-solido": "rosa-500", "--tom-rosa-solido-tx": "tinta-0",
    # barra lateral (escura nos dois temas)
    "--menu-fundo": "noite-800", "--menu-fundo-2": "noite-850", "--menu-texto": "noite-0", "--menu-suave": "noite-200", "--menu-rotulo": "noite-300",
    "--menu-borda": "noite-700", "--menu-hover": "noite-700", "--menu-ativo": "noite-600", "--menu-anel": "noite-400",
    # ornamentos (grade de levantamento e aura do topo da página)
    "--grade": "tinta-100", "--grade-forte": "tinta-150",
    # sombras e relevo
    "--sombra": "0 1px 2px rgba(18, 26, 44, .06), 0 2px 8px rgba(18, 26, 44, .04)",
    "--sombra-alta": "0 10px 28px rgba(18, 26, 44, .12), 0 2px 6px rgba(18, 26, 44, .06)",
    "--sombra-botao": "0 1px 1px rgba(18, 26, 44, .14), 0 1px 3px rgba(18, 26, 44, .08)",
    "--realce": "inset 0 1px 0 rgba(255, 255, 255, .7)", "--realce-solido": "inset 0 1px 0 rgba(255, 255, 255, .22)",
    # mapa de calor
    "--calor-1": "#cdeeea", "--calor-2": "#86d3ca", "--calor-3": "#2fa59a", "--calor-4": "#0b6560",
}

# o que o tema escuro troca (todo o resto herda do claro)
SEM_ESCURO = {
    "--fundo": "noite-900", "--superficie": "noite-850", "--superficie-subtil": "noite-800", "--superficie-elevada": "noite-700",
    "--texto": "noite-0", "--texto-suave": "noite-200", "--texto-mutado": "noite-300", "--texto-botao": "cobalto-950",
    "--borda": "noite-700", "--borda-forte": "noite-500", "--borda-controle": "noite-400",
    "--acento": "cobalto-300", "--acento-fundo": "cobalto-900", "--acento-borda": "cobalto-700",
    "--inclusao": "esmeralda-300", "--inclusao-fundo": "esmeralda-950", "--inclusao-borda": "esmeralda-750",
    "--exclusao": "terracota-300", "--exclusao-fundo": "terracota-950", "--exclusao-borda": "terracota-800",
    "--duvida": "ambar-300", "--duvida-fundo": "ambar-900", "--duvida-fundo-suave": "ambar-950", "--duvida-borda": "ambar-800",
    "--perigo": "vermelho-300", "--perigo-fundo": "vermelho-900",
    "--marca": "amarelo-900", "--marca-borda": "amarelo-300", "--marca-aprox": "cobalto-900",
    "--st-anunciado": "violeta-300", "--st-anunciado-fundo": "violeta-900",
    "--st-em_estudo": "petroleo-300", "--st-em_estudo-fundo": "petroleo-900",
    "--inclusao-solido": "esmeralda-900", "--inclusao-solido-hover": "esmeralda-850", "--inclusao-solido-borda": "esmeralda-600", "--inclusao-solido-texto": "esmeralda-100",
    "--tom-cobalto-tx": "cobalto-300", "--tom-cobalto-fundo": "cobalto-900", "--tom-cobalto-borda": "cobalto-700", "--tom-cobalto-solido": "cobalto-500", "--tom-cobalto-solido-tx": "tinta-0",
    "--tom-petroleo-tx": "petroleo-300", "--tom-petroleo-fundo": "petroleo-900", "--tom-petroleo-borda": "petroleo-700", "--tom-petroleo-solido": "petroleo-300", "--tom-petroleo-solido-tx": "petroleo-950",
    "--tom-violeta-tx": "violeta-300", "--tom-violeta-fundo": "violeta-900", "--tom-violeta-borda": "violeta-700", "--tom-violeta-solido": "violeta-500", "--tom-violeta-solido-tx": "tinta-0",
    "--tom-ambar-tx": "ambar-300", "--tom-ambar-fundo": "ambar-900", "--tom-ambar-borda": "ambar-800", "--tom-ambar-solido": "ambar-300", "--tom-ambar-solido-tx": "ambar-950",
    "--tom-rosa-tx": "rosa-300", "--tom-rosa-fundo": "rosa-900", "--tom-rosa-borda": "rosa-700", "--tom-rosa-solido": "rosa-300", "--tom-rosa-solido-tx": "rosa-950",
    "--menu-fundo": "noite-950", "--menu-fundo-2": "noite-950", "--menu-borda": "noite-800", "--menu-hover": "noite-800", "--menu-ativo": "noite-700",
    "--grade": "noite-800", "--grade-forte": "noite-700",
    "--sombra": "0 1px 2px rgba(0, 0, 0, .5), 0 2px 8px rgba(0, 0, 0, .25)",
    "--sombra-alta": "0 14px 36px rgba(0, 0, 0, .6), 0 2px 8px rgba(0, 0, 0, .4)",
    "--sombra-botao": "0 1px 0 rgba(0, 0, 0, .6)",
    "--realce": "inset 0 1px 0 rgba(255, 255, 255, .06)", "--realce-solido": "inset 0 1px 0 rgba(255, 255, 255, .16)",
    "--calor-1": "#143a3a", "--calor-2": "#1f6b66", "--calor-3": "#34a89c", "--calor-4": "#8de6da",
}

# impressão: igual ao claro, com quatro valores fixos que o teste exige (por valor, não por var())
FIXOS_IMPRESSAO = {"--fundo": "#ffffff", "--texto-suave": "#4a5462", "--borda": "#9aa3b0", "--borda-controle": "#5b6675"}

# tokens que valem igual nos dois temas e não são reatribuídos (contexto do banco e tipografia)
FIXOS = {
    "--banner-real": "#123a57", "--banner-simulado": "#5b4a00", "--banner-demo": "#53288a", "--texto-banner": "#ffffff",
}

# espelhos: nomes que o contrato exige (--ok, --alerta...) e que valem o mesmo que outro semântico. Cada um recebe o MESMO primitivo do original
# (em vez de var(--original), que seria uma cadeia de dois saltos até o hexadecimal).
ESPELHOS = {
    "--ok": "--inclusao", "--ok-fundo": "--inclusao-fundo",
    "--alerta": "--duvida", "--alerta-fundo": "--duvida-fundo", "--alerta-fundo-suave": "--duvida-fundo-suave",
    "--neutro": "--texto-suave", "--neutro-fundo": "--superficie", "--foco": "--acento",
}
for _tab in (SEM_CLARO, SEM_ESCURO):
    for _novo, _orig in ESPELHOS.items():
        if _orig in _tab:
            _tab[_novo] = _tab[_orig]

# tokens que saem como hexadecimal literal nos blocos :root simples. São os que os testes do contrato comparam como TEXTO, sem resolver var():
#   * os do mapa de calor, que analises.css repete (--an-calor1..4 == --calor-1..4, no claro e no escuro);
#   * os 9 que os literais de impressão de analises.css repetem (14 pares do contrato, seção 6.4);
#   * os que o contrato manda trocar no escuro (6.2): assim o valor escuro difere do claro também na comparação de texto.
# Nos blocos do botão de tema (:root[data-theme]), onde hexadecimal é proibido, os mesmos tokens usam var(--primitivo) de igual valor.
LITERAIS = (
    "--texto", "--superficie", "--acento", "--perigo", "--perigo-fundo", "--ok", "--ok-fundo", "--alerta", "--alerta-fundo",
    "--calor-1", "--calor-2", "--calor-3", "--calor-4",
)


# ------------------------------------------------------------------ resolução e contraste
def _hex(h):
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def lum(h):
    def f(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (f(c) for c in _hex(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contraste(a, b):
    la, lb = lum(a), lum(b)
    if la < lb:
        la, lb = lb, la
    return (la + 0.05) / (lb + 0.05)


def valor(token, tema):
    """Hex resolvido de um token semântico no tema ('claro', 'escuro', 'impressao')."""
    tab = dict(SEM_CLARO)
    if tema == "escuro":
        tab.update(SEM_ESCURO)
    if tema == "impressao":
        tab.update(FIXOS_IMPRESSAO)
    v = tab.get(token)
    if v is None:
        v = FIXOS[token]
    for _ in range(6):
        if v.startswith("#"):
            return v
        m = re.fullmatch(r"var\((--[\w-]+)\)", v)
        if m:
            v = tab.get(m.group(1)) or FIXOS.get(m.group(1))
            continue
        if v in PRIM:
            return PRIM[v]
        raise KeyError((token, v))
    raise RecursionError(token)


def tokens_do_tema(tema):
    ns = set(SEM_CLARO) | set(FIXOS)
    return {t: valor(t, tema) for t in ns if not valor_e_sombra(t)}


def valor_e_sombra(t):
    return t.startswith("--sombra") or t.startswith("--realce")


# ------------------------------------------------------------------ pares exigidos pelo contrato (seção 6.2) e pares próprios do v5
TEXTO_45 = [
    ("--texto", "--fundo"), ("--texto", "--superficie"), ("--texto", "--acento-fundo"), ("--texto", "--alerta-fundo"),
    ("--texto", "--marca"), ("--texto", "--marca-aprox"), ("--texto-suave", "--fundo"), ("--texto-suave", "--superficie"),
    ("--texto-suave", "--acento-fundo"), ("--acento", "--fundo"), ("--acento", "--superficie"), ("--acento", "--acento-fundo"),
    ("--ok", "--superficie"), ("--ok", "--ok-fundo"), ("--alerta", "--superficie"), ("--alerta", "--alerta-fundo"),
    ("--perigo", "--superficie"), ("--perigo", "--perigo-fundo"), ("--perigo", "--fundo"), ("--texto-botao", "--acento"),
]
COMPONENTE_3 = [("--borda-controle", "--fundo"), ("--borda-controle", "--superficie"), ("--acento", "--fundo"), ("--acento", "--superficie")]
PROPRIOS_45 = [
    # seletores de selo e botões (v4/v5)
    ("--st-anunciado", "--st-anunciado-fundo"), ("--st-em_estudo", "--st-em_estudo-fundo"), ("--ok", "--fundo"),
    ("--exclusao", "--exclusao-fundo"), ("--exclusao", "--superficie"), ("--duvida", "--duvida-fundo-suave"),
    ("--inclusao-solido-texto", "--inclusao-solido"), ("--texto-botao", "--acento"),
    ("--texto-banner", "--banner-real"), ("--texto-banner", "--banner-simulado"), ("--texto-banner", "--banner-demo"),
    ("--texto-suave", "--superficie-subtil"), ("--texto", "--superficie-subtil"), ("--texto-mutado", "--superficie"),
    ("--texto-mutado", "--fundo"), ("--acento", "--superficie-subtil"),
    # sidebar
    ("--menu-texto", "--menu-fundo"), ("--menu-suave", "--menu-fundo"), ("--menu-rotulo", "--menu-fundo"), ("--menu-texto", "--menu-ativo"),
    ("--menu-suave", "--menu-hover"), ("--menu-texto", "--menu-hover"),
]
for t in TONS:
    PROPRIOS_45 += [(f"--tom-{t}-tx", "--superficie"), (f"--tom-{t}-tx", f"--tom-{t}-fundo"), (f"--tom-{t}-tx", "--fundo"),
                    (f"--tom-{t}-tx", "--superficie-subtil")]
PROPRIOS_3 = [(f"--tom-{t}-solido-tx", f"--tom-{t}-solido") for t in TONS] + [("--tom-cobalto-solido", "--superficie")]


def relatorio(verbose=True):
    falhas = []
    for tema in ("claro", "escuro", "impressao"):
        for lista, minimo in ((TEXTO_45, 4.5), (COMPONENTE_3, 3.0), (PROPRIOS_45, 4.5), (PROPRIOS_3, 3.0)):
            for a, b in lista:
                if tema == "impressao" and (a.startswith("--menu") or b.startswith("--menu")):
                    continue
                try:
                    c = contraste(valor(a, tema), valor(b, tema))
                except KeyError as e:
                    falhas.append((tema, a, b, "ausente", e)); continue
                if c < minimo:
                    falhas.append((tema, a, b, round(c, 2), minimo))
    # calor: texto de cada nível (escolhido por contraste)
    for tema in ("claro", "escuro"):
        for i in range(1, 5):
            f = valor(f"--calor-{i}", tema)
            melhor = max(contraste(f, "#ffffff"), contraste(f, "#0b1620"))
            if melhor < 4.5:
                falhas.append((tema, f"--calor-{i}", "texto", round(melhor, 2), 4.5))
    # troca obrigatória entre temas (6.2): valor escuro diferente do claro
    for t in ("--fundo", "--superficie", "--texto", "--acento", "--ok", "--alerta", "--perigo", "--st-anunciado", "--calor-1", "--marca"):
        if valor(t, "claro") == valor(t, "escuro"):
            falhas.append(("escuro", t, "igual ao claro", 0, 0))
    if verbose:
        if not falhas:
            print("contraste: tudo certo")
        for f in falhas:
            print("FALHA", f)
    return falhas


if __name__ == "__main__":
    sys.exit(1 if relatorio() else 0)
