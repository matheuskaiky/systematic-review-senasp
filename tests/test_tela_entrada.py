"""Tela de entrada (GET e POST /entrar) no desenho Observatório: painel de apresentação, cartão, recados de contexto,
recusas sem pista, token novo a cada entrada e nada guardado em cache. Os comportamentos de conta, sessão e bloqueio
continuam os de test_autenticacao.py."""
import re
import socket
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from test_autenticacao import SENHA, _criar, _csrf, _entrar, painel  # noqa: F401
from test_painel import demo  # noqa: F401

RAIZ = Path(__file__).resolve().parent.parent
CSS = (RAIZ / "painel" / "static" / "painel.css").read_text(encoding="utf-8")
JS = (RAIZ / "painel" / "static" / "painel.js").read_text(encoding="utf-8")


def _sem_visitante(contas_db):
    c = sqlite3.connect(contas_db)
    c.execute("DELETE FROM grupo_permissoes WHERE grupo_id=(SELECT grupo_id FROM grupos WHERE nome='Visitante')")
    c.commit()


# ====================== primeira visita ======================
TEXTOS_DA_TELA = [
    "<title>Entrar · IA na Segurança Pública</title>",
    '<div class="layout layout-entrada">',
    '<nav class="menu menu-entrada" aria-label="Principal">',
    '<aside class="entrada-apresentacao" aria-label="Sobre o levantamento">',
    '<p class="entrada-chamada">Cada achado passa por uma pessoa antes de virar resultado.</p>',
    '<p class="entrada-texto">O levantamento reúne onde a inteligência artificial já é usada na segurança pública brasileira. '
    "Entre para revisar os achados e triar os artigos da literatura.</p>",
    '<div><strong>Triagem de artigos</strong><span>Leia o título e o resumo e decida o que entra na revisão sistemática.</span></div>',
    '<div><strong>Revisão de achados</strong><span>Confirme ou descarte cada achado a partir do trecho da notícia.</span></div>',
    '<div><strong>Decisão com autoria</strong><span>Cada decisão guarda o nome de quem decidiu, para a pesquisa poder ser auditada.</span></div>',
    '<section class="entrada-cartao" aria-labelledby="t-entrar">',
    '<h1 id="t-entrar">Entrar</h1>',
    '<p class="sub">Use o login e a senha enviados pela coordenação da pesquisa.</p>',
    '<form class="entrada-formulario" method="post" action="/entrar" data-entrada>',
    '<input type="hidden" name="proximo" value="/">',
    '<label for="login">Login</label>',
    '<div class="campo-controle" data-ic="user">',
    '<input id="login" name="login" type="text" value="" autocomplete="username" autocapitalize="none" spellcheck="false" required>',
    '<label for="senha">Senha</label>',
    '<div class="campo-controle" data-ic="lock">',
    '<input id="senha" name="senha" type="password" autocomplete="current-password" required>',
    '<button type="submit" class="botao grande cheio">Entrar</button>',
    '<p class="so-leitor" id="estado-envio" role="status"></p>',
    '<p class="entrada-ajuda">Esqueceu a senha ou ainda não tem acesso? Fale com a coordenação da pesquisa.</p>',
    '<p class="entrada-credito">Pesquisa desenvolvida na UFPI para a SENASP.</p>',
    '<span class="banner-detalhe"></span>',
]


@pytest.mark.parametrize("texto", TEXTOS_DA_TELA)
def test_primeira_visita_mostra_a_tela_inteira(painel, texto):
    cli, _, _, _ = painel
    r = cli.get("/entrar")
    assert r.status_code == 200 and texto in r.text


def test_primeira_visita_sem_menu_sem_conta_sem_estilo_embutido_e_sem_cache(painel):
    cli, _, _, _ = painel
    r = cli.get("/entrar")
    h = r.text
    assert r.headers.get("cache-control") == "no-store"
    assert 'class="menu-lista"' not in h and 'class="conta"' not in h and "conta-entrar" not in h
    assert h.count("<h1") == 1 and " style=" not in h and "<style" not in h
    assert re.findall(r"<script[^>]*>", h) == ['<script src="/static/painel.js" defer>']
    assert h.count('<link rel="stylesheet"') == 1
    assert 'aria-invalid' not in h and 'id="erro-login"' not in h and 'role="alert"' not in h
    assert "Sua sessão expirou." not in h and "Você saiu." not in h


def test_as_outras_paginas_continuam_com_menu_conta_detalhe_e_sem_no_store(painel):
    cli, _, copia, _ = painel
    r = cli.get("/")
    h = r.text
    assert '<div class="layout">\n  <nav class="menu" aria-label="Principal">' in h and '</nav>\n  <main id="conteudo"' in h
    assert '<div class="layout">' in h and 'class="menu-lista"' in h and '<a class="conta-entrar" href="/entrar">Entrar</a>' in h
    assert f'<span class="banner-detalhe">{copia.name}</span>' in h
    assert "no-store" not in r.headers.get("cache-control", "")


@pytest.mark.parametrize("metodo,caminho", [("get", "/static/painel.css"), ("get", "/entrarx"), ("get", "/entrar/x"), ("post", "/sair")])
def test_no_store_so_no_caminho_exato_da_entrada(painel, metodo, caminho):
    cli, _, _, _ = painel
    dados = {"data": {"csrf": _csrf(cli)}} if metodo == "post" else {}
    r = getattr(cli, metodo)(caminho, follow_redirects=False, **dados)
    assert "no-store" not in r.headers.get("cache-control", "")


# ====================== recados de contexto (lista fechada) ======================
@pytest.mark.parametrize("consulta,esperado", [
    ("", None),
    ("?aviso=expirada", '<div class="aviso" data-ic="clock" role="status"><strong>Sua sessão expirou.</strong> Entre de novo para continuar de onde parou.</div>'),
    ("?aviso=saiu", '<div class="aviso ok" role="status"><strong>Você saiu.</strong> Para voltar à revisão, entre de novo.</div>'),
    ("?aviso=SAIU", None), ("?aviso=%20saiu", None), ("?aviso=outro", None), ("?aviso=", None),
    ("?aviso=outro&aviso=saiu", '<div class="aviso ok" role="status"><strong>Você saiu.</strong> Para voltar à revisão, entre de novo.</div>'),
    ("?aviso=saiu&aviso=outro", None),
    ("?aviso=saiu&proximo=%2Fchamadas", '<div class="aviso ok" role="status"><strong>Você saiu.</strong> Para voltar à revisão, entre de novo.</div>'),
])
def test_recado_de_contexto_so_da_lista_fechada(painel, consulta, esperado):
    cli, _, _, _ = painel
    h = cli.get("/entrar" + consulta).text
    recados = re.findall(r'<div class="aviso[^"]*"[^>]*role="status">.*?</div>', h)
    recados = [x for x in recados if "Nenhum administrador" not in x]
    assert recados == ([] if esperado is None else [esperado])


def test_proximo_valido_vai_no_campo_escondido(painel):
    cli, _, _, _ = painel
    assert '<input type="hidden" name="proximo" value="/chamadas?pagina=2">' in cli.get("/entrar?proximo=%2Fchamadas%3Fpagina%3D2").text
    assert '<input type="hidden" name="proximo" value="/">' in cli.get("/entrar?proximo=%2F%2Fmal.example").text


# ====================== acesso de visitante ======================
def test_ver_os_dados_sem_entrar_so_quando_o_visitante_abre_a_visao_geral(painel):
    cli, _, _, contas_db = painel
    botao = '<p class="entrada-publico"><a class="botao secundario" href="/">Ver os dados sem entrar</a></p>'
    assert botao in cli.get("/entrar").text
    _sem_visitante(contas_db)
    assert "Ver os dados sem entrar" not in cli.get("/entrar").text


def test_aviso_de_administrador_ausente_fica_no_cartao(painel):
    cli, _, _, _ = painel
    h = cli.get("/entrar").text
    assert ('<div class="aviso" role="status"><strong>Nenhum administrador cadastrado.</strong> Crie um com: '
            "<code>python main.py usuario-admin --login &lt;login&gt; --nome &lt;nome&gt;</code></div>") in h
    _criar(painel, "chefe", "Administrador")
    assert "Nenhum administrador cadastrado." not in cli.get("/entrar").text


# ====================== recusas ======================
ERRO_CREDENCIAIS = ('<div class="aviso erro" id="erro-login" role="alert"><strong>Login ou senha incorretos.</strong> '
                    "Confira os dois campos e tente de novo.</div>")


@pytest.mark.parametrize("login,senha,valor_devolvido", [
    ("maria", "errada-errada", "maria"),            # senha errada
    ("ninguem", "errada-errada", "ninguem"),        # login que nao existe: mesma resposta
    ("  maria  ", "errada-errada", "maria"),        # pontas aparadas
    ("Maria", SENHA, "Maria"),                      # formato invalido (maiuscula)
    ("maria", "", "maria"),                         # senha vazia
    ("", "qualquer-coisa", ""),                     # login vazio
    ("<b>x</b>", "errada-errada", "&lt;b&gt;x&lt;/b&gt;"),   # escapado
    ("a" * 300, "errada-errada", "a" * 200),        # devolve no maximo 200 caracteres
    (" " * 5 + "a" * 300, "errada-errada", "a" * 200),          # apara antes de cortar
    ("a" * 199 + "<b", "errada-errada", "a" * 199 + "&lt;"),    # corta antes de escapar
    ('x" autofocus onfocus="a', "errada-errada", "x&#34; autofocus onfocus=&#34;a"),   # aspas nao saem do atributo
])
def test_recusa_de_credenciais_e_unica_e_devolve_o_login_aparado(painel, login, senha, valor_devolvido):
    cli, _, _, _ = painel
    _criar(painel, "maria", "Revisor")
    r = _entrar(cli, login, senha)
    h = r.text
    assert r.status_code == 400 and r.headers.get("cache-control") == "no-store"
    assert "<title>Erro ao entrar · IA na Segurança Pública</title>" in h
    assert ERRO_CREDENCIAIS in h and h.count('role="alert"') == 1
    assert (f'<input id="login" name="login" type="text" value="{valor_devolvido}" autocomplete="username" autocapitalize="none" '
            'spellcheck="false" required aria-invalid="true" aria-describedby="erro-login">') in h
    assert ('<input id="senha" name="senha" type="password" autocomplete="current-password" required aria-invalid="true" '
            'aria-describedby="erro-login">') in h
    assert (senha == "" or senha not in h) and SENHA not in h


def test_recado_de_contexto_nao_aparece_junto_com_a_recusa(painel):
    cli, _, _, _ = painel
    csrf = _csrf(cli)
    r = cli.post("/entrar?aviso=saiu", data={"login": "maria", "senha": "x", "proximo": "/", "csrf": csrf}, follow_redirects=False)
    assert r.status_code == 400 and "Você saiu." not in r.text and ERRO_CREDENCIAIS in r.text


def test_bloqueio_mostra_a_placa_com_o_prazo_e_sem_campo_invalido(painel):
    cli, _, _, _ = painel
    _criar(painel, "maria", "Revisor")
    for _ in range(5):
        assert _entrar(cli, "maria", "errada-errada").status_code == 400
    r = _entrar(cli, "maria")
    h = r.text
    assert r.status_code == 429 and r.headers.get("cache-control") == "no-store"
    assert ('<div class="retorno bloqueio" id="erro-login" role="alert"><p class="retorno-texto"><strong>Muitas tentativas. Tente de novo em '
            "alguns minutos.</strong><small>Por segurança, o acesso fica bloqueado por 5 minutos depois de 5 senhas erradas seguidas.</small></p></div>") in h
    assert "aria-invalid" not in h and "Login ou senha incorretos." not in h
    assert '<title>Erro ao entrar · IA na Segurança Pública</title>' in h
    assert 'value="maria"' in h


# ====================== sucesso, saida e sessao vencida ======================
def test_entrada_certa_troca_o_token_e_nao_guarda_cache(painel):
    cli, _, _, _ = painel
    _criar(painel, "maria", "Revisor")
    antigo = _csrf(cli)
    r = cli.post("/entrar", data={"login": "maria", "senha": SENHA, "proximo": "/chamadas", "csrf": antigo}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/chamadas" and r.headers.get("cache-control") == "no-store"
    novo = r.cookies.get("csrf")
    assert novo and novo != antigo and len(novo) >= 40 and r.cookies.get("sessao")
    cabecalhos = [v for k, v in r.headers.multi_items() if k == "set-cookie"]
    csrf = [v for v in cabecalhos if v.startswith("csrf=")]
    assert len(csrf) == 1 and "HttpOnly" in csrf[0] and "SameSite=strict" in csrf[0]
    h = cli.get("/chamadas").text
    assert f'name="csrf" value="{novo}"' in h and f'value="{antigo}"' not in h


def test_sair_volta_para_a_entrada_com_o_recado(painel):
    cli, _, _, _ = painel
    _criar(painel, "maria", "Revisor")
    _entrar(cli, "maria")
    r = cli.post("/sair", data={"csrf": _csrf(cli)}, follow_redirects=True)
    assert r.url.path == "/entrar" and "Você saiu." in r.text


@pytest.mark.parametrize("metodo,caminho,local", [
    ("get", "/chamadas", "/entrar?proximo=%2Fchamadas&aviso=expirada"),
    ("get", "/estados?uf=PI", "/entrar?proximo=%2Festados%3Fuf%3DPI&aviso=expirada"),
    ("post", "/achados/1/verificar", "/entrar?proximo=%2F&aviso=expirada"),
])
def test_sessao_vencida_leva_a_entrada_com_o_recado(painel, metodo, caminho, local):
    cli, _, _, contas_db = painel
    _criar(painel, "maria", "Revisor")
    _entrar(cli, "maria")
    _sem_visitante(contas_db)
    c = sqlite3.connect(contas_db)
    c.execute("DELETE FROM sessoes")
    c.commit()
    r = getattr(cli, metodo)(caminho, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == local
    apagado = [v for k, v in r.headers.multi_items() if k == "set-cookie" and v.startswith("sessao=")]
    assert len(apagado) == 1 and ("Max-Age=0" in apagado[0] or "expires=Thu, 01 Jan 1970" in apagado[0])
    assert not cli.cookies.get("sessao")
    r = cli.get("/chamadas", follow_redirects=False)
    assert r.headers["location"] == "/entrar?proximo=%2Fchamadas"          # o recado aparece uma vez so


def test_cookie_de_sessao_vazio_nao_gera_recado(painel):
    cli, _, _, contas_db = painel
    _sem_visitante(contas_db)
    cli.cookies.set("sessao", "")
    r = cli.get("/chamadas", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/entrar?proximo=%2Fchamadas"


def test_quem_ja_entrou_nao_recebe_recado_na_entrada(painel):
    cli, _, _, _ = painel
    _criar(painel, "maria", "Revisor")
    _entrar(cli, "maria")
    for consulta in ("?aviso=saiu", "?aviso=expirada"):
        h = cli.get("/entrar" + consulta).text
        assert "Você saiu." not in h and "Sua sessão expirou." not in h


def test_sem_cookie_de_sessao_o_redirecionamento_nao_tem_recado(painel):
    cli, _, _, contas_db = painel
    _sem_visitante(contas_db)
    r = cli.get("/chamadas", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/entrar?proximo=%2Fchamadas"


# ====================== CSS e JavaScript ======================
@pytest.mark.parametrize("trecho", [
    ".layout-entrada { grid-template-columns: minmax(24rem, 5fr) minmax(0, 7fr);",
    ".entrada-cartao { width: min(100%, 28rem);",
    ".banner-detalhe:empty { display: none; }",
    ".aviso.ok::before { color: var(--inclusao-solido-texto); }",
    ".menu a:focus-visible, .menu summary:focus-visible { outline-color: var(--menu-texto); }",
    ".entrada-lateral, .campo-mostrar { display: none !important; }",
    ".retorno, .vazio, .entrada-cartao { box-shadow: none; }",
])
def test_css_publicado_tem_a_tela_de_entrada_e_as_duas_correcoes(trecho):
    assert trecho in CSS


def test_css_sem_a_regra_antiga_do_formulario_de_entrada():
    assert ".form-entrar" not in CSS
    assert (RAIZ / "design" / "src" / "painel" / "65_login.css").is_file()


def test_painel_js_tem_o_trecho_da_entrada_sobre_o_campo_login():
    assert JS.count('document.querySelector("form[data-entrada]")') == 1
    assert 'form.querySelector("#login")' in JS and "#usuario" not in JS
    for trecho in ('"Entrando…"', 'botao.className = "campo-mostrar"', 'botao.setAttribute("aria-controls", "senha")',
                   '"(pointer: fine)"', 'window.addEventListener("pageshow"'):
        assert trecho in JS, trecho


# ====================== no navegador (pulado, com motivo, se nao houver Chromium) ======================
@pytest.fixture
def navegador_entrada(painel):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("Playwright não está instalado neste ambiente: a tela de entrada não foi conferida no navegador.")
    import uvicorn
    cli, _, _, _ = painel
    _criar(painel, "maria", "Revisor")
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    porta = s.getsockname()[1]
    s.close()
    app = cli.app
    for m in app.user_middleware:
        if m.cls.__name__ == "TrustedHostMiddleware":
            m.kwargs["allowed_hosts"] = ["127.0.0.1"]
    app.middleware_stack = app.build_middleware_stack()
    servidor = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=porta, log_level="error"))
    fio = threading.Thread(target=servidor.run, daemon=True)
    fio.start()
    for _ in range(200):                                 # ate 10 s; um servidor que nao sobe falha o teste, nao trava a bateria
        if servidor.started:
            break
        time.sleep(0.05)
    assert servidor.started, "o servidor do teste nao subiu em 10 s"
    with sync_playwright() as p:
        try:
            chromium = p.chromium.launch()
        except Exception as erro:
            servidor.should_exit = True
            pytest.skip(f"Chromium não pôde ser aberto ({str(erro).splitlines()[0][:120]}): a tela de entrada não foi conferida no navegador.")
        yield chromium, f"http://127.0.0.1:{porta}"
        chromium.close()
    servidor.should_exit = True
    fio.join(timeout=5)


def test_navegador_foco_mostrar_senha_recusa_e_envio_unico(navegador_entrada):
    chromium, base = navegador_entrada
    ctx = chromium.new_context(viewport={"width": 1440, "height": 900})
    pg = ctx.new_page()
    erros = []
    pg.on("console", lambda m: m.type == "error" and erros.append(m.text))
    pg.goto(base + "/entrar")
    pg.wait_for_function("document.documentElement.classList.contains('icones-ok')")
    assert pg.evaluate("document.activeElement.id") == "login"
    assert pg.evaluate("document.documentElement.scrollHeight <= window.innerHeight")
    mostrar = pg.locator("button.campo-mostrar")
    assert mostrar.count() == 1 and mostrar.get_attribute("aria-label") == "Mostrar senha"
    pg.fill("#senha", "errada-errada")
    mostrar.click()
    assert pg.get_attribute("#senha", "type") == "text" and mostrar.get_attribute("aria-label") == "Ocultar senha"
    assert pg.evaluate("document.activeElement.id") == "senha"
    pg.fill("#login", "maria")
    pg.click("button[type=submit]")
    pg.wait_for_load_state()
    assert pg.locator("#erro-login").count() == 1
    assert pg.evaluate("document.activeElement.id") == "senha" and pg.get_attribute("#senha", "type") == "password"
    pg.fill("#senha", SENHA)
    mostrar.click()                                                   # senha visivel antes de enviar
    # depois dos ouvintes do formulario, conta os envios que o painel.js deixou passar e segura a navegacao
    pg.evaluate("window.__envios = 0; window.addEventListener('submit', e => { if (!e.defaultPrevented) window.__envios++; e.preventDefault(); })")
    pg.evaluate("document.querySelector('form[data-entrada]').requestSubmit()")
    assert pg.get_attribute("form[data-entrada]", "data-enviando") == "true"
    assert pg.get_attribute("form[data-entrada]", "aria-busy") == "true"
    assert pg.evaluate("document.querySelector('button[type=submit]').disabled") is True
    assert pg.inner_text("button[type=submit]") == "Entrando…" and pg.inner_text("#estado-envio") == "Entrando…"
    assert pg.get_attribute("#senha", "type") == "password"           # volta a ocultar ao enviar
    pg.evaluate("document.querySelector('form[data-entrada]').requestSubmit()")
    assert pg.evaluate("window.__envios") == 1                        # o segundo envio foi barrado pelo painel.js
    assert [e for e in erros if "status of 400" not in e] == []     # a recusa (400) o Chromium registra como erro de carga; nada mais
    ctx.close()


@pytest.mark.parametrize("largura,altura,tema", [(390, 844, "light"), (320, 640, "dark"), (768, 1024, "light")])
def test_navegador_tela_estreita_sem_rolagem_horizontal(navegador_entrada, largura, altura, tema):
    chromium, base = navegador_entrada
    ctx = chromium.new_context(viewport={"width": largura, "height": altura}, color_scheme=tema, has_touch=True, is_mobile=True)
    pg = ctx.new_page()
    pg.goto(base + "/entrar")
    pg.wait_for_function("document.documentElement.classList.contains('icones-ok')")
    assert pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert pg.locator(".entrada-apresentacao").count() == 1
    assert pg.evaluate("getComputedStyle(document.querySelector('.entrada-apresentacao')).display") == "none"
    assert pg.evaluate("document.activeElement.id") != "login"     # sem foco automatico em tela de toque
    ctx.close()
