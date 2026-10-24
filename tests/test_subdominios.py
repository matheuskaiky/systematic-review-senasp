"""Dois paineis em subdominios proprios (vies.<dominio> e revisao.<dominio>), cada um num site do Firebase Hosting que
encaminha ao seu servico do Cloud Run: o Host que chega e o do run.app, so o cookie __session passa, e o navegador guarda o
cookie so para o subdominio que o gravou (sem Domain). Login, saida e CSRF de cada painel sem efeito no outro, mesmo com as
contas compartilhadas entre os dois."""
import re

import pytest
from fastapi.testclient import TestClient

from test_servidor_painel import _rodar, servidor  # noqa: F401  (fixture `servidor`: demonstracao com uvicorn trocado)

SENHA = "senha-boa-123456"
DOMINIO = "meudominio.exemplo"
VIES, REVISAO = f"vies.{DOMINIO}", f"revisao.{DOMINIO}"
RUN_VIES, RUN_REVISAO = "senasp-vies-sp-1.southamerica-east1.run.app", "senasp-painel-sp-1.southamerica-east1.run.app"
RECUSA_ORIGEM = "O pedido veio de outro site ou de outra porta, não deste painel."


def _servico(servidor, monkeypatch, run, publico, criar_admin):
    _, chamadas = servidor
    monkeypatch.setenv("PAINEL_HOSTS", run)
    monkeypatch.setenv("PAINEL_ORIGENS", f"https://{publico}")
    monkeypatch.delenv("PAINEL_BASE_PATH", raising=False)
    if criar_admin:
        respostas = iter([SENHA, SENHA])
        monkeypatch.setattr("getpass.getpass", lambda *a, **k: next(respostas))
        _rodar(monkeypatch, "usuario-admin", "--login", "chefe", "--nome", "Chefe", "--demo")
    _rodar(monkeypatch, "painel", "--demo", "--servidor")
    return chamadas[-1][0]


def _firebase(sites):
    """O Firebase Hosting em miniatura, um site por subdominio: troca o Host pelo do servico (como o rewrite para o Cloud
    Run), descarta os cookies que nao sao __session, acrescenta os cabecalhos de proxy; o dominio sem subdominio redireciona
    (302) ao painel de vies; outro host e 404."""
    async def app(scope, receive, send):
        if scope["type"] != "http":
            return
        cab = dict(scope["headers"])
        publico = cab.get(b"host", b"").decode()
        if publico == DOMINIO:
            await send({"type": "http.response.start", "status": 302,
                        "headers": [(b"location", f"https://{VIES}/".encode()), (b"content-length", b"0")]})
            await send({"type": "http.response.body", "body": b""})
            return
        if publico not in sites:
            await send({"type": "http.response.start", "status": 404, "headers": [(b"content-length", b"0")]})
            await send({"type": "http.response.body", "body": b""})
            return
        servico, run = sites[publico]
        headers = []
        for k, v in scope["headers"]:
            if k == b"host":
                v = run.encode()
            elif k == b"cookie":
                v = b"; ".join(p.strip() for p in v.split(b";") if p.strip().startswith(b"__session="))
                if not v:
                    continue
            headers.append((k, v))
        headers += [(b"x-forwarded-host", publico.encode()), (b"x-fh-requested-host", publico.encode())]
        await servico({**scope, "headers": headers, "server": (run, 443)}, receive, send)
    return app


@pytest.fixture
def navegador(servidor, monkeypatch):
    """Um navegador (um pote de cookies) que visita os dois subdominios."""
    vies = _servico(servidor, monkeypatch, RUN_VIES, VIES, True)
    revisao = _servico(servidor, monkeypatch, RUN_REVISAO, REVISAO, False)
    return TestClient(_firebase({VIES: (vies, RUN_VIES), REVISAO: (revisao, RUN_REVISAO)}), base_url=f"https://{VIES}")


def _csrf(cli, host):
    return re.search(r'name="csrf" value="([^"]+)"', cli.get(f"https://{host}/entrar").text).group(1)


def _entrar(cli, host, origem=None, csrf=None):
    dados = {"login": "chefe", "senha": SENHA, "proximo": "/", "csrf": _csrf(cli, host) if csrf is None else csrf}
    return cli.post(f"https://{host}/entrar", data=dados, headers={"Origin": origem or f"https://{host}"}, follow_redirects=False)


def _logado(cli, host):
    return cli.get(f"https://{host}/chamadas", follow_redirects=False).status_code == 200


def _set_cookies(r):
    return [v for k, v in r.headers.multi_items() if k == "set-cookie"]


def test_login_em_cada_subdominio_sem_valer_no_outro(navegador):
    r = _entrar(navegador, VIES)
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert _logado(navegador, VIES) and not _logado(navegador, REVISAO)
    assert _entrar(navegador, REVISAO).status_code == 303
    assert _logado(navegador, VIES) and _logado(navegador, REVISAO)
    por_host = {c.domain: c.value for c in navegador.cookies.jar if c.name == "__session"}
    assert set(por_host) == {VIES, REVISAO} and por_host[VIES] != por_host[REVISAO]


def test_sair_de_um_nao_derruba_o_outro(navegador):
    _entrar(navegador, VIES)
    _entrar(navegador, REVISAO)
    csrf = {c.domain: c.value for c in navegador.cookies.jar if c.name == "__session"}[VIES].split(".")[0]
    r = navegador.post(f"https://{VIES}/sair", data={"csrf": csrf}, headers={"Origin": f"https://{VIES}"}, follow_redirects=False)
    assert r.status_code == 303 and not _logado(navegador, VIES) and _logado(navegador, REVISAO)


def test_cookie_sem_domain_restrito_ao_subdominio(navegador):
    """Nenhum Set-Cookie leva Domain (o cookie fica so no host que o gravou); todos levam Secure, HttpOnly, SameSite=Strict
    e Path=/; o pote do navegador guarda cada um como cookie do proprio host."""
    respostas = [navegador.get(f"https://{VIES}/entrar"), _entrar(navegador, VIES)]
    csrf = {c.domain: c.value for c in navegador.cookies.jar if c.name == "__session"}[VIES].split(".")[0]
    respostas.append(navegador.post(f"https://{VIES}/sair", data={"csrf": csrf}, headers={"Origin": f"https://{VIES}"},
                                    follow_redirects=False))
    respostas.append(navegador.get(f"https://{REVISAO}/entrar"))
    cookies = [c for r in respostas for c in _set_cookies(r)]
    assert len(cookies) == 4
    for c in cookies:
        atributos = {p.strip().split("=")[0].lower() for p in c.split(";")[1:]}
        assert "domain" not in atributos and {"secure", "httponly", "samesite", "path"} <= atributos, c
        assert "Path=/;" in c or c.endswith("Path=/"), c
    assert all(not c.domain.startswith(".") and c.domain in (VIES, REVISAO) for c in navegador.cookies.jar)


@pytest.mark.parametrize("origem", [f"https://{REVISAO}", f"https://{DOMINIO}", f"https://x.{VIES}", f"http://{VIES}",
                                    f"https://{VIES}:8443", f"https://{RUN_REVISAO}", "null"])
def test_outro_subdominio_nao_envia_formulario(navegador, origem):
    """vies.<dominio> e revisao.<dominio> sao o mesmo site para o navegador (SameSite nao separa); a checagem de origem
    separa: cada servico so aceita o proprio endereco publico (PAINEL_ORIGENS) e o do proprio Cloud Run."""
    r = _entrar(navegador, VIES, origem=origem)
    assert r.status_code == 403 and RECUSA_ORIGEM in r.text and not _logado(navegador, VIES)


def test_cabecalhos_de_proxy_nao_contam(navegador):
    """O emulador manda X-Forwarded-Host e X-Fh-Requested-Host com o host publico; mesmo forjados com o outro subdominio,
    a origem continua decidindo."""
    dados = {"login": "chefe", "senha": SENHA, "proximo": "/", "csrf": _csrf(navegador, VIES)}
    r = navegador.post(f"https://{VIES}/entrar", data=dados, follow_redirects=False,
                       headers={"Origin": f"https://{REVISAO}", "X-Forwarded-Host": REVISAO, "X-Fh-Requested-Host": REVISAO})
    assert r.status_code == 403 and RECUSA_ORIGEM in r.text


def test_so_o_cookie_session_e_preciso(navegador):
    """O Firebase descarta os outros cookies: com o tema gravado no navegador, o login e a sessao seguem funcionando."""
    navegador.cookies.set("tema", "dark", domain=VIES)
    assert _entrar(navegador, VIES).status_code == 303 and _logado(navegador, VIES)


def test_dominio_sem_subdominio_vai_para_o_vies(navegador):
    r = navegador.get(f"https://{DOMINIO}/", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == f"https://{VIES}/"
