"""Acessibilidade do painel (WCAG AA): estrutura do HTML em todas as paginas da demonstracao e contraste das cores do CSS."""
import re
import sqlite3
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent))
from test_painel import _app, demo  # noqa: E402,F401  (a fixture `demo` e a mesma dos testes do painel)

CSS = Path(__file__).resolve().parent.parent / "painel" / "static" / "painel.css"


# ============================== verificador de HTML (so biblioteca padrao) ==============================
class Verificador(HTMLParser):
    VAZIOS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.pilha, self.problemas = [], []
        self.h1, self.niveis, self.ids, self.rotulos_for, self.controles = 0, [], [], set(), []
        self.th = self.tabelas = 0
        self.lang = None
        self.skip = self.main = False
        self.landmarks = set()

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id"):
            self.ids.append(a["id"])
        if tag == "html":
            self.lang = a.get("lang")
        if tag in self.VAZIOS:
            if tag == "img" and "alt" not in a:
                self.problemas.append("img sem alt")
            if tag == "input" and a.get("type", "text") not in ("hidden", "submit", "button", "reset", "image"):
                dentro_de_label = any(e["tag"] == "label" for e in self.pilha)
                self.controles.append((tag, a.get("id"), dentro_de_label, bool(a.get("aria-label") or a.get("aria-labelledby") or a.get("title"))))
            return
        elemento = {"tag": tag, "attrs": a, "texto": "", "tem_filho_visivel": False}
        if tag in ("select", "textarea"):
            dentro_de_label = any(e["tag"] == "label" for e in self.pilha)
            self.controles.append((tag, a.get("id"), dentro_de_label, bool(a.get("aria-label") or a.get("aria-labelledby") or a.get("title"))))
        if tag == "label" and a.get("for"):
            self.rotulos_for.add(a["for"])
        if tag == "h1":
            self.h1 += 1
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.niveis.append(int(tag[1]))
        if tag == "table":
            self.tabelas += 1
            if not any("tabela-rolavel" in e["attrs"].get("class", "").split() for e in self.pilha):
                self.problemas.append("tabela fora de um .tabela-rolavel (estoura a largura em telas estreitas)")
        if tag == "th":
            self.th += 1
        if tag == "main":
            self.main = a.get("id") == "conteudo"
        if tag in ("header", "nav", "main"):
            self.landmarks.add(tag)
        if tag == "a" and "pular" in a.get("class", "").split() and a.get("href") == "#conteudo":
            self.skip = True
        if tag == "svg" or tag == "img":
            for e in self.pilha:
                e["tem_filho_visivel"] = True
        self.pilha.append(elemento)

    def handle_endtag(self, tag):
        for i in range(len(self.pilha) - 1, -1, -1):
            if self.pilha[i]["tag"] == tag:
                e = self.pilha.pop(i)
                if tag in ("a", "button") and not e["texto"].strip() and not e["tem_filho_visivel"] \
                        and not (e["attrs"].get("aria-label") or e["attrs"].get("title")):
                    self.problemas.append(f"<{tag}> sem texto acessivel ({e['attrs'].get('href', '')})")
                if tag in ("h1", "h2", "h3") and not e["texto"].strip():
                    self.problemas.append(f"<{tag}> vazio")
                break

    def handle_data(self, dados):
        for e in self.pilha:
            e["texto"] += dados


def verificar(html):
    v = Verificador()
    v.feed(html)
    problemas = list(v.problemas)
    if v.lang != "pt-BR":
        problemas.append(f"html lang={v.lang!r}")
    if v.h1 != 1:
        problemas.append(f"{v.h1} elementos h1")
    if not v.skip:
        problemas.append("falta o link 'Ir para o conteudo'")
    if not v.main:
        problemas.append("falta <main id=conteudo>")
    for esperado in ("header", "nav"):
        if esperado not in v.landmarks:
            problemas.append(f"falta <{esperado}>")
    duplicados = {i for i in v.ids if v.ids.count(i) > 1}
    if duplicados:
        problemas.append(f"ids duplicados: {sorted(duplicados)[:5]}")
    for tag, id_, dentro, aria in v.controles:
        if not (dentro or aria or (id_ and id_ in v.rotulos_for)):
            problemas.append(f"<{tag} id={id_!r}> sem rotulo")
    if v.tabelas and not v.th:
        problemas.append("tabela sem <th>")
    # ordem dos titulos: nunca pular niveis para baixo (h1 -> h3)
    for anterior, atual in zip(v.niveis, v.niveis[1:]):
        if atual - anterior > 1:
            problemas.append(f"titulos pulam de h{anterior} para h{atual}")
            break
    return problemas


# ============================== paginas da demonstracao ==============================
def _ids(banco):
    c = sqlite3.connect(banco)
    try:
        return {"achado": c.execute("SELECT MIN(achado_id) FROM achados").fetchone()[0],
                "run": c.execute("SELECT run_id FROM execucoes ORDER BY iniciado_em LIMIT 1").fetchone()[0],
                "chamada": c.execute("SELECT MIN(chamada_id) FROM chamadas WHERE raw_path IS NOT NULL").fetchone()[0],
                "artigo": c.execute("SELECT MIN(artigo_id) FROM artigos").fetchone()[0]}
    finally:
        c.close()


@pytest.fixture(scope="module")
def cliente(demo, tmp_path_factory):
    banco, raw = demo
    tmp = tmp_path_factory.mktemp("acessibilidade")
    app, _ = _app(banco, raw, tmp)
    return TestClient(app, raise_server_exceptions=False), _ids(banco)


def _rotas(ids):
    return ["/", "/estados", "/estados/SP", "/estados/AC", "/achados", "/achados?uf=SP&verificacao=pendente",
            f"/achados/{ids['achado']}", f"/achados/{ids['achado']}?fila=1", "/execucoes", f"/execucoes/{ids['run']}",
            "/execucoes/comparar", f"/execucoes/comparar?a={ids['run']}&b={ids['run']}", "/chamadas", f"/chamadas/{ids['chamada']}",
            "/literatura", "/literatura/artigos", f"/literatura/artigos/{ids['artigo']}", f"/literatura/artigos/{ids['artigo']}?fila=1",
            "/literatura/prisma", "/sobre", "/pagina-que-nao-existe", "/achados/99999999", "/estados/ZZ"]


def test_estrutura_acessivel_em_todas_as_paginas_da_demo(cliente):
    cli, ids = cliente
    falhas = {}
    for rota in _rotas(ids):
        r = cli.get(rota)
        assert r.status_code in (200, 404), (rota, r.status_code)
        if "text/html" not in r.headers["content-type"]:
            continue
        problemas = verificar(r.text)
        if problemas:
            falhas[rota] = problemas
    assert not falhas, "\n".join(f"{rota}: {p}" for rota, p in falhas.items())


def test_paginas_de_outros_modulos_quando_existirem(cliente):
    """/classificadores e /metodologia vem de outros modulos: entram na checagem so se responderem 200."""
    cli, _ = cliente
    falhas = {}
    for rota in ("/classificadores", "/metodologia"):
        r = cli.get(rota)
        if r.status_code == 200:
            problemas = verificar(r.text)
            if problemas:
                falhas[rota] = problemas
    assert not falhas, falhas


def test_pagina_sem_banco_e_pagina_de_erro_sao_acessiveis(tmp_path):
    app, _ = _app(tmp_path / "nao_existe.db", tmp_path / "raw", tmp_path)
    r = TestClient(app).get("/")
    assert r.status_code == 503
    assert verificar(r.text) == []


def test_o_verificador_pega_defeitos_conhecidos():
    ruim = ('<html lang="en"><body><h1>a</h1><h1>b</h1><h3>c</h3><a href="/x"></a><input name="q"><img src="x.png">'
            '<table><tr><td>1</td></tr></table><p id="x"></p><p id="x"></p></body></html>')
    texto = " | ".join(verificar(ruim))
    for trecho in ("lang", "2 elementos h1", "pulam", "sem texto acessivel", "sem rotulo", "img sem alt", "tabela sem <th>", "tabela fora de um .tabela-rolavel", "ids duplicados", "Ir para o conteudo"):
        assert trecho.lower() in texto.lower(), trecho


def test_menu_marca_a_pagina_atual_com_aria_current(cliente):
    cli, _ = cliente
    html = cli.get("/estados").text
    assert re.search(r'<a href="/estados" aria-current="page">', html)
    assert html.count('aria-current="page"') == 1
    # o menu agora e feito de tres grupos <details>; o grupo da pagina atual ja vem aberto do servidor
    assert re.search(r'<details class="menu-grupo" data-grupo="revisao" open>\s*<summary>Revisão sistemática</summary>', html)
    assert html.count("<details class=\"menu-grupo\"") == 3 and html.count(" open>") == 1


# ============================== contraste (WCAG 2.x) ==============================
def _sem_comentarios(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _blocos(css):
    """Divide `css` (sem comentarios) em [(prefixo, corpo)] no nivel de topo, respeitando chaves aninhadas."""
    saida, i = [], 0
    while True:
        a = css.find("{", i)
        if a < 0:
            return saida
        nivel, j = 1, a + 1
        while nivel and j < len(css):
            nivel += {"{": 1, "}": -1}.get(css[j], 0)
            j += 1
        saida.append((css[i:a].strip(), css[a + 1:j - 1]))
        i = j


def _declaracoes(corpo):
    return {k.strip(): v.strip() for k, v in re.findall(r"([\w-]+)\s*:\s*([^;]+);?", corpo)}


def _regras(css):
    """{seletor: {propriedade: valor}}; regras repetidas se fundem na ordem do arquivo; ignora blocos @."""
    regras = {}
    for prefixo, corpo in _blocos(css):
        if prefixo.startswith("@"):
            continue
        for seletor in prefixo.split(","):
            regras.setdefault(seletor.strip(), {}).update(_declaracoes(corpo))
    return regras


def _temas():
    """Devolve (claro, escuro): cada tema e {'tokens': {...}, 'regras': {...}} com os valores efetivos."""
    css = _sem_comentarios(CSS.read_text(encoding="utf-8"))
    blocos = _blocos(css)
    claro_regras = _regras(css)
    escuro_regras = {}
    for prefixo, corpo in blocos:
        if re.match(r"@media\s*\(prefers-color-scheme:\s*dark\)", prefixo):
            for seletor, decl in _regras(corpo).items():
                escuro_regras.setdefault(seletor, {}).update(decl)
    tokens_claro = {k: v for k, v in claro_regras[":root"].items() if k.startswith("--")}
    tokens_escuro = {**tokens_claro, **{k: v for k, v in escuro_regras.get(":root", {}).items() if k.startswith("--")}}
    regras_escuro = {s: {**claro_regras.get(s, {}), **escuro_regras.get(s, {})} for s in set(claro_regras) | set(escuro_regras)}
    return ({"tokens": tokens_claro, "regras": claro_regras}, {"tokens": tokens_escuro, "regras": regras_escuro})


def _hex(valor, tokens):
    valor = valor.strip()
    m = re.fullmatch(r"var\((--[\w-]+)\)", valor)
    if m:
        return _hex(tokens[m.group(1)], tokens)
    m = re.fullmatch(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})", valor)
    assert m, f"cor nao reconhecida: {valor!r}"
    h = m.group(1)
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def luminancia(rgb):
    def canal(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (canal(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contraste(a, b):
    la, lb = sorted((luminancia(a), luminancia(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _cor(tema, ref):
    """`--token`, `#hex` ou `seletor|propriedade` (valor efetivo da regra no tema)."""
    if "|" in ref:
        seletor, prop = ref.split("|")
        return _hex(tema["regras"][seletor][prop], tema["tokens"])
    return _hex(ref, tema["tokens"]) if ref.startswith("#") else _hex(f"var({ref})", tema["tokens"])


def _misturar(frente, fundo, alfa):
    return tuple(round(alfa * f + (1 - alfa) * g) for f, g in zip(frente, fundo))


# texto normal: pares (texto, fundo) que aparecem de fato nas telas
PARES_TEXTO = [
    ("--texto", "--fundo"), ("--texto", "--superficie"), ("--texto", "--acento-fundo"), ("--texto", "--alerta-fundo"),
    ("--texto", "--marca"), ("--texto", "--marca-aprox"),
    ("--texto-suave", "--fundo"), ("--texto-suave", "--superficie"), ("--texto-suave", "--acento-fundo"),
    ("--acento", "--fundo"), ("--acento", "--superficie"), ("--acento", "--acento-fundo"),
    ("--ok", "--superficie"), ("--ok", "--ok-fundo"), ("--alerta", "--superficie"), ("--alerta", "--alerta-fundo"),
    ("--perigo", "--superficie"), ("--perigo", "--perigo-fundo"), ("--perigo", "--fundo"),
    ("--texto-botao", "--acento"),
]


@pytest.mark.parametrize("indice,nome", [(0, "claro"), (1, "escuro")])
def test_contraste_de_texto_dos_tokens_tem_pelo_menos_4_5(indice, nome):
    tema = _temas()[indice]
    ruins = []
    for frente, fundo in PARES_TEXTO:
        c = contraste(_cor(tema, frente), _cor(tema, fundo))
        if c < 4.5:
            ruins.append(f"{frente} sobre {fundo}: {c:.2f}")
    assert not ruins, f"tema {nome}: " + "; ".join(ruins)


@pytest.mark.parametrize("indice,nome", [(0, "claro"), (1, "escuro")])
def test_contraste_dos_selos_de_status_e_confianca(indice, nome):
    tema = _temas()[indice]
    regras = tema["regras"]
    ruins, vistos = [], 0
    base_selo = regras[".selo"]["background"]
    for seletor, decl in regras.items():
        if not re.fullmatch(r"\.(st|cf)-[\w]+", seletor) or "color" not in decl:
            continue
        fundo = decl.get("background", base_selo)
        for fundo_ref in ([fundo] if seletor.startswith(".st") else [base_selo]):
            vistos += 1
            c = contraste(_hex(decl["color"], tema["tokens"]), _hex(fundo_ref, tema["tokens"]))
            if c < 4.5:
                ruins.append(f"{seletor} ({decl['color']} sobre {fundo_ref}): {c:.2f}")
    assert vistos >= 10, "o parser nao encontrou os selos .st-* e .cf-*"
    assert not ruins, f"tema {nome}: " + "; ".join(ruins)


@pytest.mark.parametrize("indice,nome", [(0, "claro"), (1, "escuro")])
def test_contraste_de_selos_de_resultado_e_banners(indice, nome):
    tema = _temas()[indice]
    regras, ruins = tema["regras"], []
    for seletor in (".selo.ok", ".selo.alerta"):
        d = regras[seletor]
        c = contraste(_hex(d["color"], tema["tokens"]), _hex(d["background"], tema["tokens"]))
        if c < 4.5:
            ruins.append(f"{seletor}: {c:.2f}")
    c = contraste(_cor(tema, ".selo.neutro|color"), _cor(tema, ".selo|background"))
    if c < 4.5:
        ruins.append(f".selo.neutro: {c:.2f}")
    for banner in (".banner-real", ".banner-simulado", ".banner-demo"):
        fundo, texto = _cor(tema, f"{banner}|background"), _cor(tema, f"{banner}|color")
        if contraste(texto, fundo) < 4.5:
            ruins.append(f"{banner}: {contraste(texto, fundo):.2f}")
        opacidade = float(regras[".banner-detalhe"]["opacity"])
        mistura = _misturar(texto, fundo, opacidade)
        if contraste(mistura, fundo) < 4.5:
            ruins.append(f"{banner} .banner-detalhe: {contraste(mistura, fundo):.2f}")
    assert not ruins, f"tema {nome}: " + "; ".join(ruins)


@pytest.mark.parametrize("indice,nome", [(0, "claro"), (1, "escuro")])
def test_contraste_de_componentes_de_interface_tem_pelo_menos_3(indice, nome):
    """WCAG 1.4.11: a borda dos campos e o foco precisam de 3:1 contra o fundo."""
    tema = _temas()[indice]
    ruins = []
    for borda, fundo in (("--borda-controle", "--fundo"), ("--borda-controle", "--superficie"),
                         ("--acento", "--fundo"), ("--acento", "--superficie")):
        c = contraste(_cor(tema, borda), _cor(tema, fundo))
        if c < 3:
            ruins.append(f"{borda} sobre {fundo}: {c:.2f}")
    assert not ruins, f"tema {nome}: " + "; ".join(ruins)


def test_css_tem_foco_visivel_movimento_reduzido_e_link_de_pular():
    css = _sem_comentarios(CSS.read_text(encoding="utf-8"))
    assert "prefers-reduced-motion" in css
    assert ".pular" in css and ".pular:focus" in css
    assert ".so-leitor" in css
    assert "outline: none" not in css and "outline:none" not in css      # nunca remove o foco sem substituto
    assert ":focus-visible" in css and "summary:focus-visible" in css.replace("\n", " ")


def test_css_nao_deixa_o_conteudo_alargar_a_pagina_em_telas_estreitas():
    css = _sem_comentarios(CSS.read_text(encoding="utf-8"))
    estreito = next(corpo for prefixo, corpo in _blocos(css) if re.match(r"@media\s*\(max-width:\s*900px\)", prefixo))
    assert "minmax(0, 1fr)" in _regras(estreito)[".layout"]["grid-template-columns"]       # `1fr` puro cresce com o conteudo
    assert _regras(css)["main"].get("min-width") == "0"
    assert "overflow-x" in _regras(css)[".tabela-rolavel"]


def test_o_parser_de_css_acha_os_tokens_dos_dois_temas():
    claro, escuro = _temas()
    assert claro["tokens"]["--fundo"] != escuro["tokens"]["--fundo"]
    assert contraste((0, 0, 0), (255, 255, 255)) == pytest.approx(21)
    assert contraste((255, 255, 255), (255, 255, 255)) == pytest.approx(1)


# ---------- Etapa 4 do front-end: navegação em grupos e destaque da busca ----------
def test_navegacao_em_tres_grupos_com_grupo_atual_aberto_em_toda_pagina_principal(cliente):
    cli_demo = cliente[0]
    import re
    for rota in ("/", "/estados", "/achados", "/analises", "/solucoes", "/buscar-texto", "/chamadas", "/execucoes", "/sobre"):
        pagina = cli_demo.get(rota).text
        html = re.search(r'<nav class="menu".*?</nav>', pagina, re.S).group(0)     # so o menu lateral (as abas de /analises tem o proprio aria-current)
        assert html.count("<details") >= 3, rota
        assert len(re.findall(r'aria-current="page"', html)) == 1, rota
        assert re.search(r"<details[^>]*\sopen[^>]*>(?:(?!</details>).)*aria-current=\"page\"", html, re.S), rota


def test_busca_no_texto_destaca_com_mark_e_nao_usa_html_do_usuario(cliente):
    cli_demo = cliente[0]
    html = cli_demo.get("/buscar-texto?q=reconhecimento").text
    assert "<mark>" in html
    assert "<script" not in html.split("</head>")[1].replace('<script src="/static/painel.js" defer></script>', "")
    assert cli_demo.get("/buscar-texto?q=%3Cscript%3Ealert(1)%3C%2Fscript%3E").status_code in (200, 400)
