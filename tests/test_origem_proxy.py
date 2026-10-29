"""Painel atras de um proxy com outro endereco publico (Firebase Hosting na frente do Cloud Run): origens publicas vindas de
PAINEL_ORIGENS, comparacao exata da origem (esquema, nome e porta), cabecalhos de proxy sem efeito, CSRF exigido e um cookie
so (`__session`, o unico que o Firebase Hosting repassa) com o token de CSRF e o de sessao."""
import re

import pytest
from fastapi.testclient import TestClient

from test_servidor_painel import _rodar, servidor  # noqa: F401  (fixture `servidor`: demonstracao com uvicorn trocado)

SENHA = "senha-boa-123456"
RUN = "painel-teste-123.southamerica-east1.run.app"        # o Host que o Cloud Run recebe (PAINEL_HOSTS)
FIREBASE = "https://projeto-x.web.app"
FIREBASE2 = "https://projeto-x.firebaseapp.com"
PROPRIO = "https://revisao.exemplo.br"                     # dominio proprio futuro, ligado ao Firebase Hosting
TOKEN = r"[A-Za-z0-9_-]{43}"
FONTE = "inter-latin-wght-normal.woff2"
RECUSA_ORIGEM = "O pedido veio de outro site ou de outra porta, não deste painel."
RECUSA_TOKEN = "O token de segurança não confere. Recarregue a página e tente de novo."


def _app(servidor, monkeypatch, origens=f" {FIREBASE} , {FIREBASE2} ,"):
    _, chamadas = servidor
    monkeypatch.setenv("PAINEL_HOSTS", RUN)
    if origens is None:
        monkeypatch.delenv("PAINEL_ORIGENS", raising=False)
    else:
        monkeypatch.setenv("PAINEL_ORIGENS", origens)
    respostas = iter([SENHA, SENHA])
    monkeypatch.setattr("getpass.getpass", lambda *a, **k: next(respostas))
    _rodar(monkeypatch, "usuario-admin", "--login", "chefe", "--nome", "Chefe", "--demo")
    _rodar(monkeypatch, "painel", "--demo", "--servidor")
    return chamadas[-1][0]


def _csrf(cli):
    return re.search(r'name="csrf" value="([^"]+)"', cli.get("/entrar").text).group(1)


def _entrar(cli, cabecalhos=None, csrf=None):
    dados = {"login": "chefe", "senha": SENHA, "proximo": "/", "csrf": _csrf(cli) if csrf is None else csrf}
    return cli.post("/entrar", data=dados, headers=cabecalhos or {}, follow_redirects=False)


def _set_cookies(r):
    return [v for k, v in r.headers.multi_items() if k == "set-cookie"]


def _logado(cli):
    return cli.get("/chamadas", follow_redirects=False).status_code == 200


# ---------- a origem: tabela (Host = endereco do Cloud Run, em https) ----------
EVIL = "https://evil.example"
PROXY_FALSO = {"X-Forwarded-Host": "projeto-x.web.app", "X-Fh-Requested-Host": "projeto-x.web.app",
               "Forwarded": "host=projeto-x.web.app;proto=https", "X-Forwarded-Proto": "https", "X-Original-Host": "projeto-x.web.app"}


@pytest.mark.parametrize("cabecalhos,aceito", [
    ({"Origin": f"https://{RUN}"}, True),                                  # direto no Cloud Run, origem igual
    ({"Origin": FIREBASE}, True),                                          # pelo Firebase
    ({"Origin": FIREBASE2}, True),                                         # o outro dominio padrao do Firebase
    ({"Origin": EVIL}, False),                                             # outro site
    ({"Origin": "null"}, False),
    ({"Origin": ""}, False),
    ({"Origin": FIREBASE + "/"}, False),                                   # malformado: so a origem exata vale
    ({"Origin": FIREBASE + "/entrar"}, False),
    ({"Origin": "http://projeto-x.web.app"}, False),                       # outro esquema
    ({"Origin": FIREBASE + ":8443"}, False),                               # outra porta
    ({"Origin": FIREBASE + ":443"}, False),                                # o navegador nunca manda a porta padrao
    ({"Origin": f"https://{RUN}:8443"}, False),
    ({"Origin": f"http://{RUN}"}, False),                                  # no servidor o proprio endereco so em https
    ({"Origin": "https://PROJETO-X.web.app"}, False),                      # comparacao exata (o navegador manda minusculas)
    ({"Origin": "https://sub.projeto-x.web.app"}, False),                  # subdominio nao herda
    ({"Origin": "https://projeto-x.web.app.evil.example"}, False),
    ({"Origin": "https://x-projeto-x.web.app"}, False),
    ({"Origin": f"{FIREBASE}, {EVIL}"}, False),
    ({"Origin": f"https://user@{RUN}"}, False),
    ({"Referer": f"{FIREBASE}/entrar?proximo=%2F"}, True),                 # sem Origin, Referer igual
    ({"Referer": f"https://{RUN}/entrar"}, True),
    ({"Referer": f"{EVIL}/entrar"}, False),                                # sem Origin, Referer externo
    ({"Referer": f"https://user@{RUN}/entrar"}, False),
    ({"Referer": "https://[::1"}, False),                                  # Referer que nem se decompoe
    ({"Referer": "null"}, False),
    ({"Referer": ""}, False),
    ({"Referer": f"{FIREBASE}:8443/entrar"}, False),
    ({"Origin": FIREBASE, "Referer": f"{EVIL}/x"}, True),                  # inconsistentes: o Origin decide sozinho
    ({"Origin": EVIL, "Referer": f"{FIREBASE}/entrar"}, False),
    ({"Origin": "null", "Referer": f"{FIREBASE}/entrar"}, False),
    ({"Origin": EVIL, **PROXY_FALSO}, False),                              # cabecalhos de proxy falsificados nao contam
    ({"Origin": "https://projeto-x.web.app.evil.example", **PROXY_FALSO}, False),
    ({"Referer": f"{EVIL}/x", **PROXY_FALSO}, False),
    ({"Origin": FIREBASE, **PROXY_FALSO}, True),
    ({}, True),                                                            # cliente que nao e navegador: so o token decide
])
def test_origem_do_pedido(servidor, monkeypatch, cabecalhos, aceito):
    cli = TestClient(_app(servidor, monkeypatch), base_url=f"https://{RUN}")
    r = _entrar(cli, cabecalhos)
    if aceito:
        assert r.status_code == 303 and r.headers["location"] == "/" and _logado(cli), cabecalhos
    else:
        assert r.status_code == 403 and RECUSA_ORIGEM in r.text and not _logado(cli), cabecalhos
        assert not any(v.startswith("__session=") and "." in v.split(";")[0] for v in _set_cookies(r))


def test_dominio_proprio_futuro_so_com_a_configuracao(servidor, monkeypatch):
    sem = TestClient(_app(servidor, monkeypatch), base_url=f"https://{RUN}")
    assert _entrar(sem, {"Origin": PROPRIO}).status_code == 403
    com = TestClient(_app(servidor, monkeypatch, f"{FIREBASE},{PROPRIO}"), base_url=f"https://{RUN}")
    assert _entrar(com, {"Origin": PROPRIO}).status_code == 303 and _logado(com)


def test_sem_painel_origens_so_vale_o_proprio_endereco(servidor, monkeypatch):
    for origens in (None, "", " , "):
        cli = TestClient(_app(servidor, monkeypatch, origens), base_url=f"https://{RUN}")
        assert _entrar(cli, {"Origin": FIREBASE}).status_code == 403, origens
        assert _entrar(cli, {"Origin": f"https://{RUN}"}).status_code == 303, origens


@pytest.mark.parametrize("base", [f"http://{RUN}", "http://127.0.0.1:8080", "http://localhost:8080"])
def test_em_http_o_servidor_recusa_ate_a_propria_origem(servidor, monkeypatch, base):
    """No servidor so vale https (o esquema vem do proxy de frente, por X-Forwarded-Proto): sem ele, nem o acesso local escreve."""
    cli = TestClient(_app(servidor, monkeypatch), base_url=base)
    r = _entrar(cli, {"Origin": base})
    assert r.status_code == 403 and RECUSA_ORIGEM in r.text


@pytest.mark.parametrize("host,esperado", [(RUN, 200), ("localhost", 200), ("127.0.0.1", 200), ("projeto-x.web.app", 400),
                                           ("evil.example", 400), (RUN + ".evil.example", 400)])
def test_host_continua_so_o_de_painel_hosts(servidor, monkeypatch, host, esperado):
    """PAINEL_ORIGENS nao amplia os Hosts aceitos: o TrustedHostMiddleware segue so com PAINEL_HOSTS e o acesso local."""
    cli = TestClient(_app(servidor, monkeypatch), base_url=f"https://{host}")
    assert cli.get("/entrar", headers={"Origin": FIREBASE}).status_code == esperado


# ---------- PAINEL_ORIGENS: so endereços https://<dominio>, exatos ----------
MSG_ORIGENS = "PAINEL_ORIGENS aceita só endereços https://<domínio>, sem porta, caminho, barra final ou '*': "


@pytest.mark.parametrize("valor,ruim", [
    ("*", "*"), ("https://*.web.app", "https://*.web.app"), ("http://projeto-x.web.app", "http://projeto-x.web.app"),
    ("https://projeto-x.web.app/", "https://projeto-x.web.app/"), ("https://projeto-x.web.app/x", "https://projeto-x.web.app/x"),
    ("https://projeto-x.web.app:443", "https://projeto-x.web.app:443"), ("https://projeto-x.web.app:8443", "https://projeto-x.web.app:8443"),
    ("projeto-x.web.app", "projeto-x.web.app"), ("https://user@projeto-x.web.app", "https://user@projeto-x.web.app"),
    ("https://projeto..app", "https://projeto..app"), ("https://-projeto.app", "https://-projeto.app"), ("null", "null"),
    (f"{FIREBASE},*", "*"), ("https://exem plo.br", "https://exem plo.br"), ("https://exemİ.br", "https://exemi̇.br"),
    ("https://projeto-x.web.app?x=1", "https://projeto-x.web.app?x=1"), ("https://", "https://"),
    ("HTTPS://PROJETO-X.WEB.APP:8443", "https://projeto-x.web.app:8443"),
])
def test_painel_origens_invalido_e_recusado(servidor, monkeypatch, valor, ruim):
    _, chamadas = servidor
    monkeypatch.setenv("PAINEL_HOSTS", RUN)
    monkeypatch.setenv("PAINEL_ORIGENS", valor)
    with pytest.raises(SystemExit) as e:
        _rodar(monkeypatch, "painel", "--demo", "--servidor")
    assert str(e.value) == MSG_ORIGENS + ruim and chamadas == []


def test_painel_origens_em_maiusculas_vale_em_minusculas(servidor, monkeypatch):
    cli = TestClient(_app(servidor, monkeypatch, "HTTPS://Projeto-X.Web.App"), base_url=f"https://{RUN}")
    assert _entrar(cli, {"Origin": FIREBASE}).status_code == 303


def test_fora_do_servidor_painel_origens_nao_e_lido(servidor, monkeypatch):
    """O painel local (sem --servidor) ignora a variavel, ate invalida, e continua aceitando so a propria origem."""
    _, chamadas = servidor
    monkeypatch.setenv("PAINEL_ORIGENS", "*")
    _rodar(monkeypatch, "painel", "--demo")
    cli = TestClient(chamadas[-1][0], base_url="http://127.0.0.1:8000")
    h = cli.get("/achados/1").text
    dados = {"csrf": re.search(r'name="csrf" value="([^"]+)"', h).group(1), "status_final": "em_uso", "revisor": "Ana",
             "observacao": "", "versao": re.search(r'name="versao" value="([^"]*)"', h).group(1)}
    r = cli.post("/achados/1/verificar", data=dados, headers={"Origin": FIREBASE}, follow_redirects=False)
    assert r.status_code == 403 and RECUSA_ORIGEM in r.text
    r = cli.post("/achados/1/verificar", data=dados, headers={"Origin": "http://127.0.0.1:8000"}, follow_redirects=False)
    assert r.status_code == 303


# ---------- token de CSRF ----------
@pytest.mark.parametrize("csrf", ["", "errado", "x" * 43])
def test_token_de_csrf_errado_ou_ausente_e_recusado(servidor, monkeypatch, csrf):
    cli = TestClient(_app(servidor, monkeypatch), base_url=f"https://{RUN}")
    _csrf(cli)
    r = _entrar(cli, {"Origin": FIREBASE}, csrf=csrf)
    assert r.status_code == 403 and RECUSA_TOKEN in r.text and not _logado(cli)


def test_token_de_outro_navegador_e_recusado(servidor, monkeypatch):
    app = _app(servidor, monkeypatch)
    a, b = TestClient(app, base_url=f"https://{RUN}"), TestClient(app, base_url=f"https://{RUN}")
    r = _entrar(b, {"Origin": FIREBASE}, csrf=_csrf(a))
    assert r.status_code == 403 and RECUSA_TOKEN in r.text


# ---------- um cookie so: __session ----------
def test_entrar_e_sair_so_com_o_cookie_que_o_firebase_repassa(servidor, monkeypatch):
    cli = TestClient(_app(servidor, monkeypatch), base_url=f"https://{RUN}")
    primeiro = cli.get("/entrar")
    assert [c.split("=")[0] for c in _set_cookies(primeiro)] == ["__session"]
    r = _entrar(cli, {"Origin": FIREBASE})
    assert r.status_code == 303
    assert set(cli.cookies.keys()) == {"__session"}                        # nada mais e preciso: o Firebase descarta o resto
    valor = cli.cookies["__session"]
    assert re.fullmatch(TOKEN + r"\." + TOKEN, valor)
    assert _logado(cli)
    csrf = re.search(r'name="csrf" value="([^"]+)"', cli.get("/conta").text).group(1)
    assert csrf == valor.split(".")[0]
    r = cli.post("/sair", data={"csrf": csrf}, headers={"Origin": FIREBASE}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/entrar?aviso=saiu" and r.headers["cache-control"] == "no-store"
    novo = cli.cookies["__session"]
    assert re.fullmatch(TOKEN, novo) and novo != csrf and not _logado(cli)   # sem sessao e com token de CSRF novo
    assert _entrar(cli, {"Origin": FIREBASE2}).status_code == 303 and _logado(cli)


def test_sair_exige_origem_e_token(servidor, monkeypatch):
    cli = TestClient(_app(servidor, monkeypatch), base_url=f"https://{RUN}")
    _entrar(cli, {"Origin": FIREBASE})
    csrf = cli.cookies["__session"].split(".")[0]
    r = cli.post("/sair", data={"csrf": csrf}, headers={"Origin": EVIL}, follow_redirects=False)
    assert r.status_code == 403 and RECUSA_ORIGEM in r.text and _logado(cli)
    r = cli.post("/sair", data={"csrf": "errado"}, headers={"Origin": FIREBASE}, follow_redirects=False)
    assert r.status_code == 403 and RECUSA_TOKEN in r.text and _logado(cli)


def test_cookie_seguro_httponly_samesite_e_sem_cache(servidor, monkeypatch):
    cli = TestClient(_app(servidor, monkeypatch), base_url=f"https://{RUN}")
    for r in (cli.get("/entrar"), _entrar(cli, {"Origin": FIREBASE})):
        cookie, = _set_cookies(r)
        assert cookie.startswith("__session=")
        partes = {p.strip().lower() for p in cookie.split(";")[1:]}
        assert {"httponly", "secure", "path=/", "samesite=strict"} <= partes, cookie
        assert r.headers["cache-control"] == "no-store"


def test_cookie_e_seguro_no_servidor_mesmo_sem_https_no_pedido(servidor, monkeypatch):
    for base in (f"https://{RUN}", "http://localhost"):
        r = TestClient(_app(servidor, monkeypatch), base_url=base).get("/entrar")
        cookie, = _set_cookies(r)
        assert "secure" in cookie.lower(), base


def test_estatico_nunca_grava_o_cookie_e_mantem_o_cache(servidor, monkeypatch):
    """Arquivo estatico nao leva token: sai sem Set-Cookie (o CDN pode guarda-lo) e com a politica de cache de sempre."""
    app = _app(servidor, monkeypatch)
    for caminho in ("/static/fonts/" + FONTE, "/static/painel.css", "/static/nao-existe.css"):
        r = TestClient(app, base_url=f"https://{RUN}").get(caminho)
        assert not _set_cookies(r), caminho
    r = TestClient(app, base_url=f"https://{RUN}").get("/static/fonts/" + FONTE)
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"


@pytest.mark.parametrize("valor", ["", ".", "abc.", ".abc", "a.b.c", "abc def", "x" * 129, "çã", "a+b", "a/b", "a=b",
                                   "abc." + "y" * 129])
def test_cookie_fora_do_formato_vale_como_ausente(servidor, monkeypatch, valor):
    """O valor vai cru no cabecalho Cookie (o pote de cookies do cliente de teste recodificaria alguns)."""
    cli = TestClient(_app(servidor, monkeypatch), base_url=f"https://{RUN}")
    r = cli.get("/entrar", headers={"Cookie": ("__session=" + valor).encode("utf-8")})
    cookie, = _set_cookies(r)
    assert re.fullmatch("__session=" + TOKEN, cookie.split(";")[0]), valor


def test_cookie_valido_sem_login_nao_e_regravado(servidor, monkeypatch):
    cli = TestClient(_app(servidor, monkeypatch), base_url=f"https://{RUN}")
    cli.cookies.set("__session", "x" * 128)
    r = cli.get("/entrar")
    assert _set_cookies(r) == [] and 'name="csrf" value="' + "x" * 128 + '"' in r.text


def test_cookies_antigos_sessao_e_csrf_nao_valem(servidor, monkeypatch):
    cli = TestClient(_app(servidor, monkeypatch), base_url=f"https://{RUN}")
    _entrar(cli, {"Origin": FIREBASE})
    csrf, sessao = cli.cookies["__session"].split(".")
    cli.cookies.clear()
    cli.cookies.set("sessao", sessao)
    cli.cookies.set("csrf", csrf)
    assert not _logado(cli)
    r = cli.post("/entrar", data={"login": "chefe", "senha": SENHA, "proximo": "/", "csrf": csrf}, headers={"Origin": FIREBASE},
                 follow_redirects=False)
    assert r.status_code == 403 and RECUSA_TOKEN in r.text


def test_sessao_vencida_mantem_o_csrf_e_tira_so_a_sessao(servidor, monkeypatch):
    cli = TestClient(_app(servidor, monkeypatch), base_url=f"https://{RUN}")
    cli.cookies.set("__session", "c" * 43 + "." + "s" * 43)
    r = cli.get("/chamadas", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/entrar?proximo=%2Fchamadas&aviso=expirada"
    cookie, = _set_cookies(r)
    assert cookie.split(";")[0] == "__session=" + "c" * 43 and r.headers["cache-control"] == "no-store"


def test_entrar_de_novo_fecha_a_sessao_anterior(servidor, monkeypatch):
    app = _app(servidor, monkeypatch)
    cli = TestClient(app, base_url=f"https://{RUN}")
    _entrar(cli, {"Origin": FIREBASE})
    antigo = cli.cookies["__session"]
    _entrar(cli, {"Origin": FIREBASE})
    novo = cli.cookies["__session"]
    assert novo.split(".")[1] != antigo.split(".")[1] and novo.split(".")[0] != antigo.split(".")[0]
    outro = TestClient(app, base_url=f"https://{RUN}")
    outro.cookies.set("__session", antigo)
    assert not _logado(outro)


@pytest.mark.parametrize("cabecalho", ["__session={a}; __session={b}", "__session={a};__session={a}", "x=1; __session={a}; __session={b}"])
def test_cookie_repetido_vale_como_ausente(servidor, monkeypatch, cabecalho):
    """Dois `__session` no pedido (outro subdominio ou outro caminho gravou um igual): nenhum vale, nem a sessao."""
    app = _app(servidor, monkeypatch)
    cli = TestClient(app, base_url=f"https://{RUN}")
    _entrar(cli, {"Origin": FIREBASE})
    valor = cli.cookies["__session"]
    outro = TestClient(app, base_url=f"https://{RUN}")
    cab = {"Cookie": cabecalho.format(a=valor, b="b" * 43)}
    assert outro.get("/chamadas", headers=cab, follow_redirects=False).status_code == 303
    r = outro.get("/entrar", headers=cab)
    cookie, = _set_cookies(r)
    novo = cookie.split(";")[0].split("=", 1)[1]
    assert re.fullmatch(TOKEN, novo) and novo != valor.split(".")[0]
    assert outro.get("/chamadas", headers={"Cookie": "__session=" + valor}, follow_redirects=False).status_code == 200


def test_toda_resposta_que_grava_o_cookie_sai_sem_cache(servidor, monkeypatch):
    """O CDN do Firebase guarda respostas 404 por 10 minutos e usa `__session` na chave: quem chega sem o cookie nunca pode
    receber de cache o token de outra pessoa. Com o cookie ja gravado, so a pagina de entrada continua sem cache."""
    app = _app(servidor, monkeypatch)
    # painel novo, sem politica de divulgacao gravada: fechado ao publico (D145); toda resposta continua sem cache
    for caminho, status in (("/", 303), ("/nao-existe", 303), ("/achados/0", 303), ("/entrar", 200), ("/chamadas", 303)):
        r = TestClient(app, base_url=f"https://{RUN}").get(caminho, follow_redirects=False)
        assert r.status_code == status and _set_cookies(r) and r.headers["cache-control"] == "no-store", caminho
    cli = TestClient(app, base_url=f"https://{RUN}")
    _entrar(cli, {"Origin": FIREBASE})
    for caminho in ("/", "/nao-existe", "/chamadas"):
        r = cli.get(caminho, follow_redirects=False)
        assert not _set_cookies(r) and "no-store" not in r.headers.get("cache-control", ""), caminho
    assert cli.get("/entrar").headers["cache-control"] == "no-store"
