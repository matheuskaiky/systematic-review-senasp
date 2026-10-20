"""Token de envio por usuario (D98): regras do dominio, gravacao nas contas (SQLite e PostgreSQL), pagina Minha conta e
administracao dos tokens. O token aparece uma unica vez, na resposta que o gera; o banco guarda so o hash e o comeco."""
import hashlib
import re
import sqlite3

import pytest

from adaptadores.contas_sqlite import ContasSQLite
from dominio import autenticacao as A
from test_admin import SENHA, _agora, _criar, _csrf, _entrar, _gid, _sair, _uid, adm  # noqa: F401
from test_painel import demo  # noqa: F401

FORMATO = re.compile(r"srsp_[A-Za-z0-9_-]{43}")


# ---------- dominio ----------
def test_token_gerado_tem_formato_fixo_e_nunca_se_repete():
    tokens = {A.gerar_token_api() for _ in range(200)}
    assert len(tokens) == 200 and all(FORMATO.fullmatch(t) and len(t) == 48 for t in tokens)


def test_hash_e_inicio_do_token():
    t = "srsp_" + "a" * 43
    assert A.hash_token(t) == hashlib.sha256(t.encode()).hexdigest() and A.inicio_do_token(t) == "srsp_aaaaaaa"


@pytest.mark.parametrize("metodo,caminho,esperado", [
    ("GET", "/conta", "_logado"), ("POST", "/conta/token", "enviar_coletas"), ("POST", "/conta/token/revogar", "_logado"),
    ("POST", "/conta", A.SO_ADMIN), ("GET", "/conta/token", "ver_painel"), ("GET", "/conta/", "ver_painel"),
    ("POST", "/conta/token/", A.SO_ADMIN), ("POST", "/conta/token/revogar/", A.SO_ADMIN)])
def test_permissao_das_rotas_da_conta(metodo, caminho, esperado):
    assert A.permissao_exigida(metodo, caminho) == esperado


def test_logado_e_enviar_coletas():
    assert getattr(A, "LOGADO", None) == "_logado"
    assert not A.pode("Visitante", set(A.PERMISSOES), A.LOGADO)                  # o visitante anonimo nao tem conta
    assert A.pode("Leitor", set(), A.LOGADO) and A.pode("Administrador", set(), A.LOGADO)
    assert not A.pode("Visitante", {"enviar_coletas"}, "enviar_coletas")         # visitante nunca envia
    assert not A.pode("Revisor", set(A.GRUPOS_PADRAO["Revisor"]), "enviar_coletas")  # o padrao do revisor nao envia
    assert A.pode("Revisor", {"enviar_coletas"}, "enviar_coletas") and "enviar_coletas" in A.GRUPOS_PADRAO["Administrador"]


# ---------- contas (SQLite; o mesmo contrato no PostgreSQL) ----------
@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)])
def contas(request, tmp_path):
    if request.param == "sqlite":
        c = ContasSQLite(tmp_path / "contas.db")
        c.garantir_padrao()
        yield c
        return
    from adaptadores import migrador_postgres as M
    from adaptadores.contas_postgres import ContasPostgres
    from adaptadores.postgres.conexao import chaves_do_banco, criar_pool
    url = request.getfixturevalue("pg_url")
    M.aplicar(url)
    pool = criar_pool(url)
    c = ContasPostgres(pool, chaves_do_banco(pool))
    c.garantir_padrao()
    yield c
    pool.close()


def _usuario(c, login="maria"):
    gid = next(g["grupo_id"] for g in c.grupos() if g["nome"] == "Revisor")
    return c.criar_usuario(login, login.title(), gid, A.hash_senha(SENHA), _agora())


def _acoes(c):
    return [(a["admin_login"], a["acao"], a["alvo"], a["detalhe"]) for a in reversed(c.auditoria())]


def test_gravar_trocar_e_revogar_token(contas):
    uid = _usuario(contas)
    assert contas.token_do_usuario(uid) is None
    assert contas.gravar_token(uid, "h1", "srsp_aaaaaaa", "2026-10-20T10:00:00+00:00",
                               auditoria=("maria", "gerar_token", "maria", None, _agora())) is False
    assert contas.token_do_usuario(uid) == {"inicio": "srsp_aaaaaaa", "criado_em": "2026-10-20T10:00:00+00:00", "ultimo_uso": None}
    assert contas.gravar_token(uid, "h2", "srsp_bbbbbbb", "2026-10-20T11:00:00+00:00",
                               auditoria=("maria", "gerar_token", "maria", None, _agora())) is True
    assert contas.token_do_usuario(uid)["inicio"] == "srsp_bbbbbbb"
    assert contas.revogar_token(uid, auditoria=("maria", "revogar_token", "maria", None, _agora())) is True
    assert contas.token_do_usuario(uid) is None
    assert contas.revogar_token(uid, auditoria=("maria", "revogar_token", "maria", None, _agora())) is False   # nada a revogar
    assert _acoes(contas) == [("maria", "gerar_token", "maria", None), ("maria", "gerar_token", "maria", "substituiu o token anterior"),
                              ("maria", "revogar_token", "maria", None)]


@pytest.mark.parametrize("situacao", ["desativada", "inexistente"])
def test_conta_desativada_ou_inexistente_nao_tem_token(contas, situacao):
    uid = _usuario(contas)
    if situacao == "desativada":
        contas.definir_ativo(uid, 0)
    alvo = uid if situacao == "desativada" else uid + 1000
    with pytest.raises(ValueError) as e:
        contas.gravar_token(alvo, "h1", "srsp_aaaaaaa", _agora(), auditoria=("maria", "gerar_token", "maria", None, _agora()))
    assert str(e.value) == "Conta inexistente ou desativada: não pode ter token."
    assert contas.token_do_usuario(alvo) is None and _acoes(contas) == []


def test_desativar_apaga_o_token_e_reativar_nao_o_devolve(contas):
    uid = _usuario(contas)
    contas.gravar_token(uid, "h1", "srsp_aaaaaaa", _agora())
    contas.definir_ativo(uid, 0)
    assert contas.token_do_usuario(uid) is None
    contas.definir_ativo(uid, 1)
    assert contas.token_do_usuario(uid) is None


def test_hash_repetido_e_recusado_e_o_primeiro_fica(contas):
    uid, outro = _usuario(contas), _usuario(contas, "joao")
    contas.gravar_token(uid, "mesmo-hash", "srsp_aaaaaaa", _agora())
    with pytest.raises(sqlite3.IntegrityError):
        contas.gravar_token(outro, "mesmo-hash", "srsp_aaaaaaa", _agora())
    assert contas.token_do_usuario(uid)["inicio"] == "srsp_aaaaaaa" and contas.token_do_usuario(outro) is None


@pytest.mark.parametrize("como", ["redefinir_senha", "definir_admin"])
def test_senha_nova_apaga_o_token(contas, como):
    uid = _usuario(contas)
    contas.gravar_token(uid, "h1", "srsp_aaaaaaa", _agora())
    if como == "redefinir_senha":
        contas.redefinir_senha(uid, A.hash_senha("outra-senha-123"))
    else:
        contas.definir_admin("maria", "Maria", A.hash_senha("outra-senha-123"), _agora())
    assert contas.token_do_usuario(uid) is None


def test_listagem_e_ficha_mostram_o_token_sem_o_hash(contas):
    uid = _usuario(contas)
    outro = _usuario(contas, "joao")
    contas.gravar_token(uid, "hash-secreto", "srsp_aaaaaaa", "2026-10-20T10:00:00+00:00")
    por_login = {u["login"]: u for u in contas.listar_usuarios()}
    assert por_login["maria"]["token"] == {"inicio": "srsp_aaaaaaa", "criado_em": "2026-10-20T10:00:00+00:00", "ultimo_uso": None}
    assert por_login["joao"]["token"] is None and contas.usuario(outro)["token"] is None
    assert contas.usuario(uid)["token"]["inicio"] == "srsp_aaaaaaa" and "hash-secreto" not in repr(contas.usuario(uid))


# ---------- pagina Minha conta e admin ----------
def _permitir_envio(contas, contas_db):
    gid = _gid(contas_db, "Revisor")
    contas.definir_permissoes(gid, set(A.GRUPOS_PADRAO["Revisor"]) | {"enviar_coletas"})


def _como_maria(cli, contas_db):
    assert _criar(cli, contas_db).status_code == 303
    _sair(cli)
    assert _entrar(cli, "maria").status_code == 303


def _hash_gravado(contas_db, login):
    r = sqlite3.connect(contas_db).execute("SELECT t.token_hash, t.inicio FROM tokens_api t JOIN usuarios u USING (usuario_id) "
                                           "WHERE u.login = ?", (login,)).fetchall()
    return r


def _gerar(cli):
    return cli.post("/conta/token", data={"csrf": _csrf(cli, "/conta")}, follow_redirects=False)


def test_conta_exige_login(adm):
    cli, _, _, _ = adm
    _sair(cli)
    r = cli.get("/conta", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/entrar?proximo=%2Fconta"
    r = cli.post("/conta/token", data={"csrf": _csrf(cli, "/entrar")}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/entrar?proximo=%2F"
    r = cli.post("/conta/token/revogar", data={"csrf": _csrf(cli, "/entrar")}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/entrar?proximo=%2F"


def test_nome_no_topo_leva_a_minha_conta(adm):
    cli, _, _, _ = adm
    assert '<a class="conta-nome" href="/conta" title="Minha conta">Chefe</a>' in cli.get("/").text
    assert '<a class="conta-nome" href="/conta" title="Minha conta" aria-current="page">Chefe</a>' in cli.get("/conta").text


def test_sem_permissao_nao_ve_o_token_nem_gera(adm):
    cli, contas, contas_db, _ = adm
    _como_maria(cli, contas_db)
    h = cli.get("/conta").text
    assert "<h1>Minha conta</h1>" in h and "<dd>Maria Souza</dd>" in h and "<dd>maria</dd>" in h and "<dd>Revisor</dd>" in h
    assert "Token de envio" not in h and 'action="/conta/token"' not in h
    r = _gerar(cli)
    assert r.status_code == 403 and "Seu grupo não tem permissão para esta página ou ação." in r.text
    assert _hash_gravado(contas_db, "maria") == []


def test_gerar_mostra_o_token_uma_vez_e_grava_so_o_hash(adm):
    cli, contas, contas_db, _ = adm
    _permitir_envio(contas, contas_db)
    _como_maria(cli, contas_db)
    h = cli.get("/conta").text
    assert "Você não tem token ativo." in h and '<button class="botao" type="submit">Gerar token</button>' in h
    r = _gerar(cli)
    assert r.status_code == 200 and r.headers.get("cache-control") == "no-store"
    achados = FORMATO.findall(r.text)
    assert len(set(achados)) == 1
    token = achados[0]
    assert f'<code id="token-novo" class="token-novo">{token}</code>' in r.text and r.text.count(token) == 1
    assert "Copie o token agora: ele não aparece de novo.</strong> Não recarregue esta página: recarregar gera outro token." in r.text
    caixa = r.text[r.text.rindex("<div", 0, r.text.index('id="token-novo"')):r.text.index('id="token-novo"')]
    assert caixa.startswith('<div class="aviso ok">') and "role=" not in caixa and "aria-live" not in caixa  # o leitor de tela nao le o token
    assert 'data-copiar="token-novo" data-aviso="token-aviso" hidden>Copiar token</button>' in r.text
    assert 'src="/static/copiar.js"' in r.text and token not in str(r.cookies) and "location" not in r.headers
    assert _hash_gravado(contas_db, "maria") == [(hashlib.sha256(token.encode()).hexdigest(), token[:12])]
    depois = cli.get("/conta")
    assert token not in depois.text and depois.headers.get("cache-control") == "no-store"
    assert f"Ativo, começa com <code>{token[:12]}</code>" in depois.text and "<dd>nunca usado</dd>" in depois.text
    assert '<button class="botao" type="submit">Gerar outro token (o atual deixa de valer)</button>' in depois.text
    outro = FORMATO.findall(_gerar(cli).text)[0]
    assert outro != token and _hash_gravado(contas_db, "maria") == [(hashlib.sha256(outro.encode()).hexdigest(), outro[:12])]


def test_gerar_sem_formulario_valido_e_recusado(adm):
    cli, contas, contas_db, _ = adm
    _permitir_envio(contas, contas_db)
    _como_maria(cli, contas_db)
    r = cli.post("/conta/token", data={"csrf": "errado"}, follow_redirects=False)
    assert r.status_code == 403 and "O token de segurança não confere." in r.text and r.headers.get("cache-control") == "no-store"
    r = cli.post("/conta/token/revogar", data={"csrf": "errado"}, follow_redirects=False)
    assert r.status_code == 403 and r.headers.get("cache-control") == "no-store"
    r = cli.post("/conta/token", data={"csrf": _csrf(cli, "/conta")}, headers={"Origin": "https://outro-site.example"},
                 follow_redirects=False)
    assert r.status_code == 403 and "O pedido veio de outro site ou de outra porta, não deste painel." in r.text
    assert _hash_gravado(contas_db, "maria") == []


def test_revogar_o_proprio_token(adm):
    cli, contas, contas_db, _ = adm
    _permitir_envio(contas, contas_db)
    _como_maria(cli, contas_db)
    _gerar(cli)
    r = cli.post("/conta/token/revogar", data={"csrf": _csrf(cli, "/conta")}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/conta?ok=revogado" and r.headers.get("cache-control") == "no-store"
    assert "Token revogado: ele não envia mais nada." in cli.get("/conta?ok=revogado").text and _hash_gravado(contas_db, "maria") == []
    r = cli.post("/conta/token/revogar", data={"csrf": _csrf(cli, "/conta")}, follow_redirects=False)
    assert r.headers["location"] == "/conta?ok=sem-token" and "Você não tinha token ativo." in cli.get("/conta?ok=sem-token").text
    assert "Token revogado" not in cli.get("/conta?ok=outra-coisa").text


def test_quem_perdeu_a_permissao_ainda_revoga(adm):
    cli, contas, contas_db, _ = adm
    _permitir_envio(contas, contas_db)
    _como_maria(cli, contas_db)
    _gerar(cli)
    contas.definir_permissoes(_gid(contas_db, "Revisor"), set(A.GRUPOS_PADRAO["Revisor"]))
    h = cli.get("/conta").text
    assert "Seu grupo não tem mais a permissão de enviar coletas: o token não envia nada. Você pode revogá-lo." in h
    assert 'action="/conta/token"' not in h and 'action="/conta/token/revogar"' in h
    assert _gerar(cli).status_code == 403
    r = cli.post("/conta/token/revogar", data={"csrf": _csrf(cli, "/conta")}, follow_redirects=False)
    assert r.status_code == 303 and _hash_gravado(contas_db, "maria") == []


def test_admin_ve_e_revoga_sem_ver_o_valor(adm):
    cli, contas, contas_db, _ = adm
    _permitir_envio(contas, contas_db)
    _como_maria(cli, contas_db)
    token = FORMATO.findall(_gerar(cli).text)[0]
    _sair(cli)
    _entrar(cli, "chefe")
    uid = _uid(contas_db, "maria")
    lista = cli.get("/admin/usuarios").text
    assert '<th scope="col">Token de envio</th>' in lista
    linhas = {re.search(r'href="/admin/usuarios/\d+">([^<]+)</a>', l).group(1): re.findall(r"<td>([^<]*)</td>", l)[-1]
              for l in re.findall(r"<tr>\s*<td><a href=\"/admin/usuarios/\d+\">.*?</tr>", lista, re.S)}
    assert re.fullmatch(r"desde \d{2}/\d{2}/\d{4} \d{2}:\d{2}", linhas["maria"]) and linhas["chefe"] == "—"
    ficha = cli.get(f"/admin/usuarios/{uid}").text
    assert f"Ativo, começa com <code>{token[:12]}</code>" in ficha and token not in ficha and token not in lista
    r = cli.post(f"/admin/usuarios/{uid}", data={"acao": "revogar_token", "csrf": _csrf(cli, f"/admin/usuarios/{uid}")},
                 follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/admin/usuarios/{uid}?ok=1"
    assert _hash_gravado(contas_db, "maria") == []
    assert "Sem token ativo." in cli.get(f"/admin/usuarios/{uid}").text
    acoes = sqlite3.connect(contas_db).execute("SELECT admin_login, acao, alvo FROM auditoria_admin WHERE acao LIKE '%token' "
                                               "ORDER BY id").fetchall()
    assert acoes == [("maria", "gerar_token", "maria"), ("chefe", "revogar_token", "maria")]
    r = cli.post(f"/admin/usuarios/{uid}", data={"acao": "revogar_token", "csrf": _csrf(cli, f"/admin/usuarios/{uid}")},
                 follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/admin/usuarios/{uid}?ok=sem-token"
    assert "O usuário não tinha token ativo." in cli.get(r.headers["location"]).text
    assert len(sqlite3.connect(contas_db).execute(
        "SELECT 1 FROM auditoria_admin WHERE acao = 'revogar_token'").fetchall()) == 1   # revogar sem token nao audita


def test_admin_textos_sem_token(adm):
    cli, contas, contas_db, _ = adm
    _criar(cli, contas_db)
    uid, chefe = _uid(contas_db, "maria"), _uid(contas_db, "chefe")
    assert "Sem token ativo. Gere o seu na página <a href=\"/conta\">Minha conta</a>." in cli.get(f"/admin/usuarios/{chefe}").text
    assert "O próprio usuário gera o token na página Minha conta" in cli.get(f"/admin/usuarios/{uid}").text
    contas.definir_ativo(uid, 0)
    assert "Sem token ativo. Conta desativada: não pode ter token." in cli.get(f"/admin/usuarios/{uid}").text


def test_banco_de_contas_ocupado(adm, monkeypatch):
    cli, contas, contas_db, _ = adm
    _permitir_envio(contas, contas_db)
    _como_maria(cli, contas_db)
    csrf = _csrf(cli, "/conta")

    def ocupado(*a, **k):
        raise A.ContasOcupadas("ocupado")
    monkeypatch.setattr(type(contas), "token_do_usuario", ocupado)
    r = cli.get("/conta")
    assert r.status_code == 503 and r.headers.get("cache-control") == "no-store"
    assert "O banco de contas está ocupado. Tente de novo em alguns segundos." in r.text
    r = cli.post("/conta/token", data={"csrf": csrf}, follow_redirects=False)   # gravou: mostra sem ler de novo
    token = FORMATO.findall(r.text)[0]
    assert r.status_code == 200 and f"Ativo, começa com <code>{token[:12]}</code>" in r.text
    assert _hash_gravado(contas_db, "maria") == [(hashlib.sha256(token.encode()).hexdigest(), token[:12])]
    monkeypatch.setattr(type(contas), "gravar_token", ocupado)
    r = cli.post("/conta/token", data={"csrf": csrf}, follow_redirects=False)
    assert r.status_code == 503 and r.headers.get("cache-control") == "no-store"
    monkeypatch.setattr(type(contas), "revogar_token", ocupado)
    r = cli.post("/conta/token/revogar", data={"csrf": csrf}, follow_redirects=False)
    assert r.status_code == 503 and r.headers.get("cache-control") == "no-store"


def test_conta_desativada_no_meio_do_caminho(adm, monkeypatch):
    cli, contas, contas_db, _ = adm
    _permitir_envio(contas, contas_db)
    _como_maria(cli, contas_db)

    def desativada(*a, **k):
        raise ValueError("Conta inexistente ou desativada: não pode ter token.")
    monkeypatch.setattr(type(contas), "gravar_token", desativada)
    r = _gerar(cli)
    assert r.status_code == 403 and "Esta conta foi desativada e não pode ter token." in r.text and not FORMATO.search(r.text)
    assert r.headers.get("cache-control") == "no-store"


@pytest.mark.postgres
def test_importador_nunca_copia_tokens(pg_url, copiar_demo, tmp_path):
    import psycopg
    from adaptadores import migrador_postgres as M
    from adaptadores.postgres import importador as I
    banco, _ = copiar_demo("token_importador")
    contas = ContasSQLite(tmp_path / "contas.db")
    contas.garantir_padrao()
    uid = _usuario(contas)
    contas.gravar_token(uid, "h1", "srsp_aaaaaaa", _agora())
    M.aplicar(pg_url)
    relatorio = I.importar(banco, pg_url, tmp_path / "contas.db")
    assert "tokens_api" not in relatorio and relatorio["usuarios"] == (1, 1)
    with psycopg.connect(pg_url) as c:
        assert c.execute("SELECT COUNT(*) FROM tokens_api").fetchone()[0] == 0


def test_admin_desativar_apaga_o_token(adm):
    cli, contas, contas_db, _ = adm
    _permitir_envio(contas, contas_db)
    _como_maria(cli, contas_db)
    _gerar(cli)
    _sair(cli)
    _entrar(cli, "chefe")
    uid = _uid(contas_db, "maria")
    cli.post(f"/admin/usuarios/{uid}", data={"acao": "desativar", "csrf": _csrf(cli, f"/admin/usuarios/{uid}")}, follow_redirects=False)
    assert _hash_gravado(contas_db, "maria") == []


def test_painel_sem_login_nao_tem_minha_conta(demo, tmp_path):
    import shutil
    from fastapi.testclient import TestClient
    from adaptadores.bruto_local import BrutoLocal
    from adaptadores.leitura_sqlite import LeituraPainelSQLite
    from adaptadores.repositorio_sqlite import RepositorioSQLite
    from config import consultas as C, vocabulario as V
    from painel.app import Contexto, criar_app
    banco, raw = demo
    copia = tmp_path / "demo.db"
    shutil.copy(banco, copia)
    ctx = Contexto(banco="demo", nome_banco=copia.name, somente_leitura=False, pasta_backup=tmp_path / "b", ufs=dict(C.UFS),
                   status_permitidos=set(V.STATUS) | set(V.STATUS_FINAL_EXTRA), status_definicoes=dict(V.STATUS),
                   hosts_permitidos=("testserver",), autenticacao=False)
    cli = TestClient(criar_app(LeituraPainelSQLite(copia), lambda: RepositorioSQLite(copia), BrutoLocal(raw), ctx))
    assert cli.get("/conta").status_code == 404


def test_uma_so_resposta_para_contas_ocupadas():
    """A resposta do banco de contas ocupado existe uma vez (app.py) e as rotas extras a recebem pronta."""
    import inspect
    from painel import app as modulo_app
    from painel.rotas_extras import admin, conta
    textos = [inspect.getsource(m) for m in (modulo_app, admin, conta)]
    assert sum(t.count('"Banco de contas ocupado"') for t in textos) == 1 and '"Banco de contas ocupado"' in textos[0]
    assert "c.contas_ocupadas" in textos[1] and "c.contas_ocupadas" in textos[2]

