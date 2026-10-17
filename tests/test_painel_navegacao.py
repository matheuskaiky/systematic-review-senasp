"""Navegacao do painel (tres grupos recolhiveis), tokens de design e folha de impressao.

O menu e HTML puro: <details>/<summary> nativos, sem depender de JavaScript. Os testes de CSS leem os arquivos de painel/static como texto."""
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent))
from test_painel import _app, demo  # noqa: E402,F401  (a fixture `demo` e a mesma dos testes do painel)
from test_painel_acessibilidade import _blocos, _declaracoes, _ids, _sem_comentarios, verificar  # noqa: E402

from painel import navegacao  # noqa: E402

ESTATICOS = Path(__file__).resolve().parent.parent / "painel" / "static"
GRUPOS = {"Revisão sistemática": ["/", "/literatura/prisma", "/estados", "/achados", "/revisao/achados", "/literatura/artigos", "/literatura", "/literatura/triagem"],
          "Análises e qualidade": ["/analises", "/triagem-escopo", "/classificadores", "/execucoes/comparar", "/solucoes"],
          "Auditoria e operação": ["/buscar-texto", "/execucoes", "/chamadas", "/metodologia", "/sobre"]}
TODOS_OS_LINKS = [h for hs in GRUPOS.values() for h in hs]


@pytest.fixture(scope="module")
def cliente(demo, tmp_path_factory):
    banco, raw = demo
    app, _ = _app(banco, raw, tmp_path_factory.mktemp("navegacao"))
    return TestClient(app, raise_server_exceptions=False), _ids(banco)


def _menu(html):
    """Devolve [(nome_do_grupo, aberto, [(href, atual, texto)])] lido do <nav class="menu"> do HTML."""
    nav = re.search(r'<nav class="menu"[^>]*>(.*?)</nav>', html, re.S).group(1)
    saida = []
    for abertura, corpo in re.findall(r"<details ([^>]*)>(.*?)</details>", nav, re.S):
        nome = re.sub(r"\s+", " ", re.search(r"<summary>(.*?)</summary>", corpo, re.S).group(1)).strip()
        links = [(h, 'aria-current="page"' in extra, texto) for h, extra, texto in re.findall(r'<a href="([^"]+)"([^>]*)>(.*?)</a>', corpo, re.S)]
        saida.append((nome, bool(re.search(r"(^|\s)open(\s|$)", abertura)), links))
    return saida


# ============================== estrutura do menu ==============================
def test_os_tres_grupos_e_todos_os_links_aparecem_uma_vez_cada(cliente):
    cli, _ = cliente
    menu = _menu(cli.get("/").text)
    assert [g[0] for g in menu] == list(GRUPOS)
    for nome, _, links in menu:
        assert [h for h, _, _ in links] == GRUPOS[nome], nome
    todos = [h for _, _, links in menu for h, _, _ in links]
    assert sorted(todos) == sorted(TODOS_OS_LINKS) and len(todos) == len(set(todos)) == 18


def test_a_marca_continua_levando_a_visao_geral(cliente):
    cli, _ = cliente
    html = cli.get("/estados").text
    assert '<a class="marca" href="/">Levantamento<br><small>IA na Segurança Pública</small></a>' in html


def test_todo_endereco_do_menu_existe_na_aplicacao(cliente):
    cli, _ = cliente
    assert sorted(navegacao.enderecos()) == sorted(TODOS_OS_LINKS)
    for rota in TODOS_OS_LINKS:
        r = cli.get(rota, follow_redirects=False)
        assert r.status_code in (200, 303), (rota, r.status_code)


def test_comparar_execucoes_sem_parametros_e_a_pagina_de_escolha(cliente):
    cli, _ = cliente
    r = cli.get("/execucoes/comparar")
    assert r.status_code == 200 and 'name="a"' in r.text and 'name="b"' in r.text


def _rotas_com_grupo(ids):
    return [("/", "Revisão sistemática", "/"), ("/estados", "Revisão sistemática", "/estados"), ("/estados/SP", "Revisão sistemática", "/estados"),
            ("/achados", "Revisão sistemática", "/achados"), (f"/achados/{ids['achado']}", "Revisão sistemática", "/achados"),
            ("/revisao/achados", "Revisão sistemática", None),
            ("/literatura", "Revisão sistemática", "/literatura"), ("/literatura/artigos", "Revisão sistemática", "/literatura/artigos"),
            (f"/literatura/artigos/{ids['artigo']}", "Revisão sistemática", "/literatura/artigos"),
            ("/literatura/prisma", "Revisão sistemática", "/literatura/prisma"),
            ("/analises", "Análises e qualidade", "/analises"), ("/analises?secao=termos", "Análises e qualidade", "/analises"),
            ("/triagem-escopo", "Análises e qualidade", "/triagem-escopo"), ("/classificadores", "Análises e qualidade", "/classificadores"),
            ("/solucoes", "Análises e qualidade", "/solucoes"),
            ("/execucoes/comparar", "Análises e qualidade", "/execucoes/comparar"),
            (f"/execucoes/comparar?a={ids['run']}&b={ids['run']}", "Análises e qualidade", "/execucoes/comparar"),
            ("/execucoes", "Auditoria e operação", "/execucoes"), (f"/execucoes/{ids['run']}", "Auditoria e operação", "/execucoes"),
            ("/chamadas", "Auditoria e operação", "/chamadas"), (f"/chamadas/{ids['chamada']}", "Auditoria e operação", "/chamadas"),
            ("/buscar-texto", "Auditoria e operação", "/buscar-texto"), ("/metodologia", "Auditoria e operação", "/metodologia"),
            ("/sobre", "Auditoria e operação", "/sobre")]


def test_a_pagina_atual_leva_aria_current_e_o_grupo_dela_vem_aberto(cliente):
    cli, ids = cliente
    for rota, grupo, atual in _rotas_com_grupo(ids):
        r = cli.get(rota, follow_redirects=True)
        assert r.status_code == 200, rota
        menu = _menu(r.text)
        marcados = [h for _, _, links in menu for h, a, _ in links if a]
        if atual is None:                                     # /revisao/achados redireciona para um achado: vale o destino
            assert marcados == ["/achados"], rota
            continue
        assert marcados == [atual], (rota, marcados)          # exatamente um link marcado no menu
        abertos = [nome for nome, aberto, _ in menu if aberto]
        assert abertos == [grupo], (rota, abertos)            # so o grupo da pagina atual vem aberto do servidor


def test_pagina_sem_item_no_menu_nao_marca_nada_e_deixa_os_grupos_fechados(cliente):
    cli, _ = cliente
    r = cli.get("/pagina-que-nao-existe")
    assert r.status_code == 404
    menu = _menu(r.text)
    assert [g[0] for g in menu] == list(GRUPOS) and not any(a for _, aberto, links in menu for _, a, _ in links) and not any(g[1] for g in menu)


def test_funcoes_de_navegacao_sao_puras():
    assert [g["aberto"] for g in navegacao.grupos("/estados/SP")] == [True, False, False]
    assert [g["aberto"] for g in navegacao.grupos("/execucoes/comparar")] == [False, True, False]
    assert [g["aberto"] for g in navegacao.grupos("/execucoes/abc")] == [False, False, True]
    assert [g["aberto"] for g in navegacao.grupos(None)] == [False, False, False]
    assert not any(i["atual"] for g in navegacao.grupos("/estadosX") for i in g["itens"])        # prefixo so vale em fronteira de caminho


def test_grupos_sao_details_nativos_que_funcionam_sem_javascript(cliente):
    """Sem JavaScript o leitor ainda abre e fecha cada grupo (summary) e todos os links estao no HTML do servidor, abertos ou nao."""
    cli, _ = cliente
    html = cli.get("/sobre").text
    nav = re.search(r'<nav class="menu"[^>]*>(.*?)</nav>', html, re.S).group(1)
    assert nav.count("<details") == 3 and nav.count("<summary>") == 3
    assert 'aria-expanded' not in nav and "hidden" not in nav and "onclick" not in nav
    assert nav.count("<li><a href=") == 18
    for nome in GRUPOS:
        assert f'aria-label="{nome}"' in nav                  # cada lista tem nome acessivel
    assert '<nav class="menu" aria-label="Principal">' in html


def test_menu_ajuda_de_javascript_e_opcional_e_guarda_o_estado_com_seguranca():
    js = (ESTATICOS / "painel.js").read_text(encoding="utf-8")
    trecho = js[js.index("Menu lateral"):]
    assert "details.menu-grupo[data-grupo]" in trecho and "localStorage" in trecho and "toggle" in trecho
    assert trecho.count("try {") >= 2 and trecho.count("catch (e)") >= 2          # leitura e escrita do armazenamento nunca estouram
    assert "contemAtual" in trecho                                                 # o grupo da pagina atual nao e sobrescrito pelo estado salvo


def test_paginas_sem_script_nem_estilo_embutido_e_estruturalmente_acessiveis(cliente):
    cli, ids = cliente
    for rota, _, _ in _rotas_com_grupo(ids):
        html = cli.get(rota, follow_redirects=True).text
        assert not re.search(r"<script(?![^>]*\bsrc=)", html), rota
        assert " style=" not in html and "<style" not in html, rota
        assert not re.search(r"\son[a-z]+=", html), rota
        assert not [p for p in verificar(html) if "tabela fora" not in p], (rota, verificar(html))
    csp = cli.get("/").headers["content-security-policy"]
    assert "script-src 'self'" in csp and "style-src 'self'" in csp and "unsafe-inline" not in csp


def test_ordem_do_foco_e_a_ordem_do_menu_marca_depois_grupos_depois_conteudo(cliente):
    cli, _ = cliente
    html = cli.get("/estados").text
    ordem = [html.index(t) for t in ('class="pular"', 'class="marca"', "<summary>Revisão sistemática", "<summary>Análises e qualidade",
                                      "<summary>Auditoria e operação", '<main id="conteudo"')]
    assert ordem == sorted(ordem)
    assert "tabindex" not in re.search(r'<nav class="menu".*?</nav>', html, re.S).group(0)      # nenhum tabindex positivo bagunçando o foco


# ============================== tokens de design ==============================
def _css(nome):
    return _sem_comentarios((ESTATICOS / nome).read_text(encoding="utf-8"))


def _raiz(css, dentro=None):
    """Tokens do primeiro bloco `:root` (ou do `:root` dentro do @media que casa com `dentro`)."""
    for prefixo, corpo in _blocos(css):
        if dentro is None and prefixo == ":root":
            return {k: v for k, v in _declaracoes(corpo).items() if k.startswith("--")}
        if dentro and prefixo.startswith(dentro):
            return {k: v for k, v in _declaracoes(_blocos(corpo)[0][1]).items() if k.startswith("--")}
    raise AssertionError(dentro or ":root")


TOKENS_OBRIGATORIOS = [
    "--fundo", "--superficie", "--texto", "--texto-suave", "--texto-botao", "--borda", "--borda-controle", "--acento", "--acento-fundo",
    "--ok", "--ok-fundo", "--alerta", "--alerta-fundo", "--perigo", "--perigo-fundo", "--neutro", "--neutro-fundo", "--marca", "--marca-borda", "--marca-aprox",
    "--foco", "--foco-largura", "--foco-recuo", "--banner-real", "--banner-simulado", "--banner-demo", "--texto-banner",
    "--st-anunciado", "--st-anunciado-fundo", "--st-em_estudo", "--st-em_estudo-fundo", "--calor-1", "--calor-2", "--calor-3", "--calor-4",
    "--fonte-base", "--fonte-mono", "--fs-xs", "--fs-sm", "--fs-md", "--fs-base", "--fs-lg", "--fs-xl", "--fs-2xl", "--lh-tight", "--lh-base", "--lh-solto",
    "--esp-1", "--esp-2", "--esp-3", "--esp-4", "--esp-5", "--esp-6", "--esp-7", "--esp-8",
    "--raio-xs", "--raio-sm", "--raio-md", "--raio", "--raio-pilula", "--sombra", "--indicador"]


def test_painel_css_define_todos_os_tokens_semanticos_e_documenta_os_grupos():
    bruto = (ESTATICOS / "painel.css").read_text(encoding="utf-8")
    assert bruto.lstrip().startswith("/* ===== Tokens de design")
    tokens = _raiz(_css("painel.css"))
    assert not [t for t in TOKENS_OBRIGATORIOS if t not in tokens], [t for t in TOKENS_OBRIGATORIOS if t not in tokens]
    escuro = _raiz(_css("painel.css"), "@media (prefers-color-scheme: dark)")
    for t in ("--fundo", "--superficie", "--texto", "--acento", "--ok", "--alerta", "--perigo", "--st-anunciado", "--calor-1", "--marca"):
        assert escuro[t] != tokens[t], t                       # o tema escuro troca as cores


def _fora_dos_blocos_de_token(css):
    """CSS sem os blocos `:root` (claro, escuro e impressao): sobra so o que CONSOME tokens."""
    def sem_raiz(texto):
        saida = []
        for prefixo, corpo in _blocos(texto):
            if prefixo == ":root":
                continue
            if prefixo.startswith("@media"):
                interno = sem_raiz(corpo)
                if interno.strip():
                    saida.append(prefixo + " {" + interno + "}")
                continue
            saida.append(prefixo + " {" + corpo + "}")
        return "\n".join(saida)
    return sem_raiz(css)


@pytest.mark.parametrize("nome", ["painel.css", "solucoes.css", "classificadores.css", "metodologia.css", "relevancia.css", "triagem_escopo.css"])
def test_folhas_de_estilo_consomem_tokens_em_vez_de_repetir_cores(nome):
    consumo = _fora_dos_blocos_de_token(_css(nome))
    assert not re.findall(r"#[0-9a-fA-F]{3,8}\b", consumo), re.findall(r"#[0-9a-fA-F]{3,8}\b", consumo)
    assert not re.findall(r"rgba?\(", consumo.replace("rgba(0, 0, 0", "")) or nome == "painel.css"


def test_analises_css_so_tem_cor_literal_nos_tokens_an():
    consumo = _fora_dos_blocos_de_token(_css("analises.css"))
    assert not re.findall(r"#[0-9a-fA-F]{3,8}\b", consumo), re.findall(r"#[0-9a-fA-F]{3,8}\b", consumo)
    claro = _raiz(_css("analises.css"))
    for t in ("--an-texto", "--an-suave", "--an-borda", "--an-fundo", "--an-acento", "--an-ok", "--an-ok-fundo", "--an-perigo", "--an-perigo-fundo",
              "--an-alerta", "--an-alerta-fundo", "--an-k-quase", "--an-cal-alta", "--an-descartado-ln"):
        assert claro[t].startswith("var(--") and "," not in claro[t], t                # derivados, sem cor de reserva
    assert not [t for t in claro if not t.startswith("--an-")]


def test_mapa_de_calor_de_painel_e_o_de_analises_tem_os_mesmos_valores():
    p_claro, p_escuro = _raiz(_css("painel.css")), _raiz(_css("painel.css"), "@media (prefers-color-scheme: dark)")
    a_claro, a_escuro = _raiz(_css("analises.css")), _raiz(_css("analises.css"), "@media (prefers-color-scheme: dark)")
    for i in range(1, 5):
        assert p_claro[f"--calor-{i}"] == a_claro[f"--an-calor{i}"], i
        assert p_escuro[f"--calor-{i}"] == a_escuro[f"--an-calor{i}"], i


# ============================== impressao ==============================
def _impressao(css):
    return next(corpo for prefixo, corpo in _blocos(css) if prefixo == "@media print")


def test_impressao_esconde_menu_e_controles_e_evita_quebras_dentro_de_blocos():
    imp = _impressao(_css("painel.css"))
    regras = {}
    for prefixo, corpo in _blocos(imp):
        for s in prefixo.split(","):
            regras.setdefault(s.strip(), {}).update(_declaracoes(corpo))
    escondidos = [s for s, d in regras.items() if d.get("display", "").startswith("none")]
    for seletor in (".menu", ".pular", ".filtros", ".paginacao", "button", ".botao"):
        assert seletor in escondidos, seletor
    assert regras["thead"]["display"] == "table-header-group"
    quebra = [s for s, d in regras.items() if d.get("break-inside") == "avoid"]
    for seletor in ("svg", "figure", ".cartao", "tr"):
        assert seletor in quebra, seletor
    assert ".banner" in regras and regras[".banner"]["background"] == "none"             # a faixa do banco aparece, sem cor de fundo
    assert ".banner" not in escondidos and "h1" not in escondidos
    assert regras[".layout"]["display"] == "block" and regras["main"]["max-width"] == "none"
    assert ".tabela-rolavel" in regras and regras[".tabela-rolavel"]["overflow"] == "visible"


def test_impressao_forca_cores_claras_iguais_as_do_tema_claro():
    css = _css("painel.css")
    claro, imp = _raiz(css), _raiz(css, "@media print")
    # papel branco e traços um pouco mais escuros que na tela: exceções documentadas no comentário do bloco, com os valores esperados
    excecoes = {"--fundo": "#ffffff", "--texto-suave": "#4a5462", "--borda": "#9aa3b0", "--borda-controle": "#5b6675"}
    for token, valor in imp.items():
        assert valor == excecoes.get(token, claro[token]), (token, valor, claro[token])
    assert "color-scheme: light" in _impressao(css)
    escuro = _raiz(css, "@media (prefers-color-scheme: dark)")
    assert set(escuro) <= set(imp)                         # tudo o que o tema escuro troca volta a claro na impressao


def test_impressao_de_analises_repete_os_literais_das_cores_de_painel():
    """O bloco de impressao de analises.css precisa de literais (teste de graficos); aqui garantimos que nao divergem de painel.css."""
    painel_imp = _raiz(_css("painel.css"), "@media print")
    painel_claro = _raiz(_css("painel.css"))
    analises_imp = _raiz(_css("analises.css"), "@media print")
    pares = {"--an-texto": "--texto", "--an-suave": "--texto-suave", "--an-borda": "--borda", "--an-fundo": "--superficie", "--an-acento": "--acento",
             "--an-perigo": "--perigo", "--an-ok": "--ok", "--an-ok-fundo": "--ok-fundo", "--an-perigo-fundo": "--perigo-fundo",
             "--an-alerta": "--alerta", "--an-alerta-fundo": "--alerta-fundo", "--an-k-quase": "--ok", "--an-cal-alta": "--ok", "--an-descartado-ln": "--perigo"}
    for an, base in pares.items():
        assert analises_imp[an] == painel_imp[base], (an, analises_imp[an], painel_imp[base])
    assert painel_imp["--ok"] == painel_claro["--ok"]


def test_relatorio_estatico_continua_claro_com_os_tokens():
    m = _css("metodologia.css")
    assert "body.relatorio { background: var(--superficie); color: var(--texto); color-scheme: light; }" in m
