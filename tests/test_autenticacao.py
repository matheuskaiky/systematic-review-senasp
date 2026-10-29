"""RB16 (D76, D78): contas em banco proprio, sessao, grupo Visitante (modo publico) e permissoes por grupo em cada rota do painel.

A autenticacao so vale com `Contexto.autenticacao=True` (comando `painel`); a demonstracao e os demais testes seguem sem ela.
"""
import hashlib
import re
import shutil
import sqlite3
import sys
from apoio_divulgacao import gravar_politica
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from adaptadores.bruto_local import BrutoLocal
from adaptadores.contas_sqlite import ContasSQLite
from adaptadores.leitura_sqlite import LeituraPainelSQLite
from adaptadores.repositorio_sqlite import RepositorioSQLite
from config import consultas as C, vocabulario as V
from dominio import autenticacao as A
from painel.app import Contexto, criar_app
from test_painel import demo  # noqa: F401

SENHA = "senha-de-teste-123"
MSG_LOGIN = "O login deve ter de 3 a 40 caracteres: letras minúsculas, números, ponto, hífen ou sublinhado."


def _agora(**delta):
    return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat()


# ====================== dominio ======================
def test_hash_com_vetor_fixo_e_sal_aleatorio():
    assert A.hash_senha(SENHA, sal=bytes(range(16))) == (
        "scrypt$16384$8$1$000102030405060708090a0b0c0d0e0f$1d75871d7cbfc7bf6094db9ab75c234c20183fe938ab8b01c4dcf15dae076c17")
    h = A.hash_senha(SENHA)
    assert h != A.hash_senha(SENHA) and A.hash_senha(SENHA, sal=b"") != A.hash_senha(SENHA, sal=b"")
    assert A.conferir_senha(SENHA, h) and not A.conferir_senha(SENHA + "x", h)


@pytest.mark.parametrize("guardado", [
    "lixo", None, 7, "scrypt$16384$8$1$$", "scrypt$1048576$8$1$" + "00" * 16 + "$" + "00" * 32,
    "scrypt$3$8$1$" + "00" * 16 + "$" + "00" * 32, "scrypt$16384$8$1$" + "AA" * 16 + "$" + "00" * 32,
    "scrypt$16384$8$1$" + "00" * 16 + "$" + "00" * 32 + "$x", "bcrypt$16384$8$1$" + "00" * 16 + "$" + "00" * 32])
def test_conferir_senha_nunca_quebra(guardado):
    assert A.conferir_senha(SENHA, guardado) is False


@pytest.mark.parametrize("senha,erros", [
    ("", ["A senha precisa ter pelo menos 10 caracteres."]), ("x" * 9, ["A senha precisa ter pelo menos 10 caracteres."]),
    ("x" * 10, []), ("x" * 200, []), ("x" * 201, ["A senha pode ter no máximo 200 caracteres."]), (" " * 10, []), ("ç" * 10, [])])
def test_regras_de_senha(senha, erros):
    assert A.validar_senha(senha) == erros


@pytest.mark.parametrize("login,valido", [
    ("abc", True), ("...", True), ("a" * 40, True), ("maria.silva-2_x", True), ("ab", False), ("Maria", False),
    ("maria silva", False), ("a" * 41, False), ("joão", False), ("abc\n", False), ("a" * 40 + "\n", False), ("", False),
    ("   ", False), ("abc ", False)])
def test_regras_de_login(login, valido):
    assert A.validar_login(login) == ([] if valido else [MSG_LOGIN])


@pytest.mark.parametrize("nome,erros", [
    ("Maria", []), ("  Maria  ", []), ("", ["O nome não pode ficar vazio."]), ("   ", ["O nome não pode ficar vazio."]),
    ("x" * 80, []), ("x" * 81, ["O nome pode ter no máximo 80 caracteres."])])
def test_regras_de_nome(nome, erros):
    assert A.validar_nome(nome) == erros


def test_catalogo_e_grupos_padrao():
    assert list(A.PERMISSOES) == ["ver_painel", "ver_nomes_revisores", "ver_chamadas", "verificar_achados", "revogar_verificacao",
                                  "triar_artigos", "triar_texto_completo", "ver_estatisticas_usuarios", "enviar_coletas",
                                  "ver_registros_revisao", "ver_custos"]
    assert A.PERMISSOES_ESCRITA == {"verificar_achados", "revogar_verificacao", "triar_artigos", "triar_texto_completo"}
    assert A.GRUPOS_PADRAO == {
        "Administrador": set(A.PERMISSOES), "Visitante": {"ver_painel"},
        "Leitor": {"ver_painel", "ver_nomes_revisores", "ver_registros_revisao", "ver_custos"},
        "Revisor": {"ver_painel", "ver_nomes_revisores", "ver_chamadas", "verificar_achados", "triar_artigos", "triar_texto_completo",
                    "ver_registros_revisao", "ver_custos"}}


@pytest.mark.parametrize("metodo,caminho,esperado", [
    ("GET", "/static/painel.css", None), ("GET", "/entrar", None), ("POST", "/entrar", None), ("POST", "/sair", None),
    ("GET", "/", "ver_painel"), ("GET", "/literatura/artigos/3", "ver_painel"), ("GET", "/sobre", "ver_painel"),
    ("GET", "/administracao", "ver_painel"), ("GET", "/entrar/", "ver_painel"),
    ("GET", "/execucoes", "ver_chamadas"), ("GET", "/execucoes/x/y", "ver_chamadas"), ("GET", "/chamadas/9/bruto", "ver_chamadas"),
    ("POST", "/achados/5/verificar", "verificar_achados"), ("POST", "/achados/5/desfazer", "verificar_achados"),
    ("POST", "/execucoes/x/verificar", A.SO_ADMIN), ("POST", "/achados/5/revogar", "revogar_verificacao"),
    ("POST", "/literatura/artigos/5/triar", "triar_artigos"), ("GET", "/admin", A.SO_ADMIN), ("GET", "/admin/usuarios", A.SO_ADMIN),
    ("POST", "/admin/x/verificar", A.SO_ADMIN), ("POST", "/chamadas/1", A.SO_ADMIN), ("POST", "/achados/5/verificar/", A.SO_ADMIN),
    ("HEAD", "/", "ver_painel"), ("PUT", "/achados/5/verificar", A.SO_ADMIN), ("POST", "/qualquer/outra", A.SO_ADMIN)])
def test_permissao_exigida_por_rota(metodo, caminho, esperado):
    assert A.permissao_exigida(metodo, caminho) == esperado


def test_pode():
    assert A.pode("Administrador", set(), A.SO_ADMIN) and A.pode("Administrador", set(), "ver_chamadas")
    assert not A.pode("Revisor", set(A.PERMISSOES), A.SO_ADMIN)
    assert A.pode("Leitor", {"ver_painel"}, "ver_painel") and not A.pode("Leitor", {"ver_painel"}, "ver_chamadas")
    assert A.pode("Visitante", {"ver_painel"}, None)
    assert not A.pode("Visitante", set(A.PERMISSOES), "verificar_achados")              # visitante nunca escreve
    assert A.pode("Visitante", {"ver_nomes_revisores"}, "ver_nomes_revisores")


@pytest.mark.parametrize("proximo,esperado", [
    ("/chamadas", "/chamadas"), ("/estados?uf=PI", "/estados?uf=PI"), ("//mal.example", "/"), ("http://mal.example/", "/"),
    ("javascript:x", "/"), ("", "/"), ("entrar", "/"), ("/entrar?proximo=/x", "/"), ("/\\mal.example", "/"),
    ("/\t/mal.example", "/"), ("/\n/mal.example", "/"), ("/" + "a" * 1999, "/" + "a" * 1999), ("/" + "a" * 2000, "/")])
def test_proximo_seguro(proximo, esperado):
    assert A.proximo_seguro(proximo) == esperado


# ====================== banco de contas ======================
@pytest.fixture
def contas(tmp_path):
    c = ContasSQLite(tmp_path / "contas" / "contas.db")
    c.garantir_padrao()
    return c, tmp_path / "contas" / "contas.db"


def _con(caminho):
    return sqlite3.connect(caminho)


def test_garantir_padrao_e_idempotente_mesmo_depois_de_editar(contas):
    c, caminho = contas
    con = _con(caminho)
    assert sorted(r[0] for r in con.execute("SELECT nome FROM grupos")) == ["Administrador", "Leitor", "Revisor", "Visitante"]
    con.execute("DELETE FROM grupo_permissoes WHERE grupo_id=(SELECT grupo_id FROM grupos WHERE nome='Visitante')")
    con.commit()
    antes = con.execute("SELECT COUNT(*) FROM grupo_permissoes").fetchone()[0]
    c.garantir_padrao()
    assert c.permissoes_do_grupo("Visitante") == set() and _con(caminho).execute("SELECT COUNT(*) FROM grupo_permissoes").fetchone()[0] == antes
    assert c.permissoes_do_grupo("Inexistente") == set()


def test_login_e_nome_unicos_e_grupo_existente(contas):
    c, caminho = contas
    g = _con(caminho).execute("SELECT grupo_id FROM grupos WHERE nome='Revisor'").fetchone()[0]
    c.criar_usuario("maria", "Maria Souza", g, A.hash_senha(SENHA), _agora())
    with pytest.raises(ValueError, match="Login já existe: maria"):
        c.criar_usuario("maria", "Outra", g, A.hash_senha(SENHA), _agora())
    with pytest.raises(ValueError, match="Nome já existe: MARIA souza"):
        c.criar_usuario("maria2", "MARIA souza", g, A.hash_senha(SENHA), _agora())
    with pytest.raises(ValueError, match="Grupo não existe: 999"):
        c.criar_usuario("joao", "João", 999, A.hash_senha(SENHA), _agora())


def _usuario(c, caminho, login="maria", grupo="Revisor", nome=None):
    g = _con(caminho).execute("SELECT grupo_id FROM grupos WHERE nome=?", (grupo,)).fetchone()[0]
    return c.criar_usuario(login, nome or login.title(), g, A.hash_senha(SENHA), _agora())


def test_sessao_expira_em_12h_e_atualiza_so_depois_de_60s(contas):
    c, caminho = contas
    uid = _usuario(c, caminho)
    t0 = datetime.now(timezone.utc)
    c.abrir_sessao(uid, "h1", t0.isoformat())
    assert c.usuario_da_sessao("h1", (t0 + timedelta(seconds=60)).isoformat())["login"] == "maria"
    assert _con(caminho).execute("SELECT ultimo_uso FROM sessoes").fetchone()[0] == t0.isoformat()
    c.usuario_da_sessao("h1", (t0 + timedelta(seconds=61)).isoformat())
    assert _con(caminho).execute("SELECT ultimo_uso FROM sessoes").fetchone()[0] == (t0 + timedelta(seconds=61)).isoformat()
    t1 = t0 + timedelta(seconds=61)
    assert c.usuario_da_sessao("h1", (t1 + timedelta(hours=11, minutes=59)).isoformat()) is not None
    t2 = t1 + timedelta(hours=11, minutes=59)
    assert c.usuario_da_sessao("h1", (t2 + timedelta(hours=12)).isoformat()) is None
    assert _con(caminho).execute("SELECT COUNT(*) FROM sessoes").fetchone()[0] == 0


def test_definir_admin_cria_atualiza_e_derruba_sessoes(contas):
    c, caminho = contas
    assert c.definir_admin("chefe", "Chefe", A.hash_senha(SENHA), _agora()) == "criado"
    uid = _con(caminho).execute("SELECT usuario_id FROM usuarios").fetchone()[0]
    c.abrir_sessao(uid, "h1", _agora())
    assert c.definir_admin("chefe", "Chefe", A.hash_senha("outra-senha-boa"), _agora()) == "atualizado"
    assert _con(caminho).execute("SELECT COUNT(*) FROM sessoes").fetchone()[0] == 0
    assert c.existe_admin_ativo()


# ====================== painel com autenticacao ======================
@pytest.fixture
def painel(demo, tmp_path):
    banco, raw = demo
    copia = tmp_path / "demo.db"
    shutil.copy(banco, copia)
    ctx = Contexto(banco="real", nome_banco=copia.name, somente_leitura=False, pasta_backup=tmp_path / "backups",
                   ufs=dict(C.UFS), status_permitidos=set(V.STATUS) | set(V.STATUS_FINAL_EXTRA),
                   status_definicoes=dict(V.STATUS), hosts_permitidos=("testserver",), autenticacao=True)
    contas_db = tmp_path / "contas.db"
    contas = ContasSQLite(contas_db)
    gravar_politica(contas, "real")                   # pesquisa divulgada, como o Visitante via antes do controle (D145)
    app = criar_app(LeituraPainelSQLite(copia), lambda: RepositorioSQLite(copia), BrutoLocal(raw), ctx, contas=contas)
    return TestClient(app), contas, copia, contas_db


def _criar(painel, login, grupo, nome=None):
    _, contas, _, contas_db = painel
    return _usuario(contas, contas_db, login, grupo, nome)


def _csrf(cli):
    return re.search(r'name="csrf" value="([^"]+)"', cli.get("/entrar").text).group(1)


def _entrar(cli, login, senha=SENHA, proximo="/"):
    return cli.post("/entrar", data={"login": login, "senha": senha, "proximo": proximo, "csrf": _csrf(cli)}, follow_redirects=False)


def test_criar_app_exige_contas_com_autenticacao(demo, tmp_path):
    banco, raw = demo
    ctx = Contexto(banco="real", nome_banco="x", somente_leitura=False, pasta_backup=tmp_path, ufs={}, status_permitidos=set(),
                   status_definicoes={}, autenticacao=True)
    with pytest.raises(ValueError, match="contas é obrigatório com autenticação"):
        criar_app(LeituraPainelSQLite(banco), lambda: RepositorioSQLite(banco), BrutoLocal(raw), ctx)


def test_contas_ficam_fora_do_banco_da_pesquisa(painel):
    _, _, copia, contas_db = painel
    tabelas = {r[0] for r in sqlite3.connect(copia).execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert not tabelas & {"usuarios", "sessoes", "grupos", "grupo_permissoes", "auditoria_admin"}
    assert contas_db.exists()


def test_visitante_ve_o_painel_mas_nao_chamadas_nem_escreve(painel):
    cli, _, copia, _ = painel
    assert cli.get("/").status_code == 200
    r = cli.get("/chamadas", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/entrar?proximo=%2Fchamadas"
    assert "Content-Security-Policy" in r.headers
    r = cli.post("/achados/1/verificar", data={}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/entrar?proximo=%2F"


def test_visitante_nunca_escreve_mesmo_com_permissao_de_escrita(painel):
    cli, _, copia, contas_db = painel
    c = sqlite3.connect(contas_db)
    c.execute("INSERT INTO grupo_permissoes SELECT grupo_id, 'verificar_achados' FROM grupos WHERE nome='Visitante'")
    c.commit()
    antes = sqlite3.connect(copia).execute("SELECT COUNT(*) FROM achados WHERE verificado=1").fetchone()[0]
    r = cli.post("/achados/1/verificar", data={"status_final": list(V.STATUS)[0], "revisor": "X", "csrf": "x"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/entrar")
    assert sqlite3.connect(copia).execute("SELECT COUNT(*) FROM achados WHERE verificado=1").fetchone()[0] == antes


def test_sem_ver_painel_o_visitante_vai_para_a_entrada(painel):
    cli, _, _, contas_db = painel
    c = sqlite3.connect(contas_db)
    c.execute("DELETE FROM grupo_permissoes WHERE grupo_id=(SELECT grupo_id FROM grupos WHERE nome='Visitante')")
    c.commit()
    r = cli.get("/estados?uf=PI", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/entrar?proximo=%2Festados%3Fuf%3DPI"


def test_entrada_errada_bloqueio_e_desbloqueio(painel):
    cli, _, _, contas_db = painel
    _criar(painel, "maria", "Revisor")
    for login, senha in (("maria", "errada-errada"), ("ninguem", "errada-errada"), ("Maria", SENHA), ("maria", "")):
        r = _entrar(cli, login, senha)
        assert r.status_code == 400 and "Login ou senha incorretos." in r.text and SENHA not in r.text
    for _ in range(3):
        _entrar(cli, "maria", "errada-errada")                                    # com a primeira: 4 falhas
    assert _entrar(cli, "maria").status_code == 303                              # 4 falhas nao bloqueiam
    cli.post("/sair", data={"csrf": _csrf(cli)})
    for _ in range(4):
        _entrar(cli, "maria", "errada-errada")
    r = _entrar(cli, "maria", "errada-errada")
    assert r.status_code == 400                                                  # a quinta ainda e 400
    r = _entrar(cli, "maria")
    assert r.status_code == 429 and "Muitas tentativas. Tente de novo em alguns minutos." in r.text
    c = sqlite3.connect(contas_db)
    c.execute("UPDATE usuarios SET bloqueado_ate=?", (_agora(minutes=-1),))
    c.commit()
    assert _entrar(cli, "maria").status_code == 303


def test_login_com_espacos_nas_pontas_entra(painel):
    cli, _, _, _ = painel
    _criar(painel, "maria", "Revisor")
    assert _entrar(cli, " maria ").status_code == 303


def test_entrar_sem_csrf_e_recusado(painel):
    cli, _, _, _ = painel
    r = cli.post("/entrar", data={"login": "x", "senha": "y", "proximo": "/"}, follow_redirects=False)
    assert r.status_code == 403 and "Formulário recusado" in r.text


def test_revisor_decide_com_o_proprio_nome_sem_cookie_de_revisor(painel):
    cli, _, copia, _ = painel
    _criar(painel, "maria", "Revisor", nome="Maria Souza")
    r = _entrar(cli, "maria", proximo="/chamadas")
    assert r.status_code == 303 and r.headers["location"] == "/chamadas"
    sc = r.headers["set-cookie"].lower()
    assert "__session=" in sc and "httponly" in sc and "samesite=strict" in sc and "path=/" in sc and "max-age" not in sc and "secure" not in sc
    achado = sqlite3.connect(copia).execute("SELECT achado_id FROM v_achados_revisao WHERE verificado=0 LIMIT 1").fetchone()[0]
    h = cli.get(f"/achados/{achado}").text
    csrf = re.search(r'name="csrf" value="([^"]+)"', h).group(1)
    versao = re.search(r'name="versao" value="([^"]*)"', h).group(1)
    r = cli.post(f"/achados/{achado}/verificar", data={"status_final": list(V.STATUS)[0], "revisor": "Outro Nome",
                                                       "observacao": "", "versao": versao, "csrf": csrf}, follow_redirects=False)
    assert r.status_code == 303 and "revisor" not in r.cookies
    assert sqlite3.connect(copia).execute("SELECT verificado_por FROM achados WHERE achado_id=?", (achado,)).fetchone()[0] == "Maria Souza"
    r = cli.post(f"/achados/{achado}/revogar", data={"motivo": "x", "csrf": csrf, "versao": versao}, follow_redirects=False)
    assert r.status_code == 403 and "Seu grupo não tem permissão para esta página ou ação." in r.text


def test_so_o_autor_ou_o_admin_desfaz(painel):
    cli, _, copia, _ = painel
    _criar(painel, "maria", "Revisor", nome="Maria Souza")
    _criar(painel, "joao", "Revisor", nome="João Lima")
    _entrar(cli, "maria")
    achado = sqlite3.connect(copia).execute("SELECT achado_id FROM v_achados_revisao WHERE verificado=0 LIMIT 1").fetchone()[0]
    h = cli.get(f"/achados/{achado}").text
    csrf = re.search(r'name="csrf" value="([^"]+)"', h).group(1)
    versao = re.search(r'name="versao" value="([^"]*)"', h).group(1)
    cli.post(f"/achados/{achado}/verificar", data={"status_final": list(V.STATUS)[0], "observacao": "", "versao": versao, "csrf": csrf})
    cli.post("/sair", data={"csrf": csrf})
    _entrar(cli, "joao")
    r = cli.post(f"/achados/{achado}/desfazer", data={"csrf": _csrf(cli)}, follow_redirects=False)
    assert r.status_code == 403 and "Só quem tomou a decisão ou um administrador pode desfazê-la." in r.text
    assert sqlite3.connect(copia).execute("SELECT verificado FROM achados WHERE achado_id=?", (achado,)).fetchone()[0] == 1


def test_leitor_e_revisor_recebem_403_e_admin_entra(painel):
    cli, _, _, _ = painel
    _criar(painel, "leo", "Leitor")
    _entrar(cli, "leo")
    assert cli.get("/chamadas", follow_redirects=False).status_code == 403
    r = cli.post("/achados/1/verificar", data={"csrf": _csrf(cli)}, follow_redirects=False)
    assert r.status_code == 403
    cli.post("/sair", data={"csrf": _csrf(cli)})
    _criar(painel, "rev", "Revisor")
    _entrar(cli, "rev")
    assert cli.get("/admin", follow_redirects=False).status_code == 403
    cli.post("/sair", data={"csrf": _csrf(cli)})
    _criar(painel, "chefe", "Administrador")
    _entrar(cli, "chefe")
    assert cli.get("/chamadas").status_code == 200


def test_triar_texto_completo_exige_a_permissao(painel):
    cli, _, copia, contas_db = painel
    c = sqlite3.connect(contas_db)
    c.execute("INSERT INTO grupos (nome, fixo, criado_em) VALUES ('So titulo', 0, ?)", (_agora(),))
    c.execute("INSERT INTO grupo_permissoes SELECT grupo_id, p FROM grupos, (SELECT 'ver_painel' p UNION SELECT 'triar_artigos') "
              "WHERE nome='So titulo'")
    c.commit()
    _criar(painel, "tit", "So titulo")
    _entrar(cli, "tit")
    i = sqlite3.connect(copia).execute("SELECT artigo_id FROM r_artigos ORDER BY artigo_id LIMIT 1").fetchone()[0]
    h = cli.get(f"/literatura/artigos/{i}").text
    csrf = re.search(r'name="csrf" value="([^"]+)"', h).group(1)
    r = cli.post(f"/literatura/artigos/{i}/triar", data={"decisao": "incluir", "etapa": "texto_completo", "csrf": csrf},
                 follow_redirects=False)
    assert r.status_code == 403


def test_sair_encerra_e_aceita_sem_cookie(painel):
    cli, _, _, contas_db = painel
    _criar(painel, "maria", "Revisor")
    _entrar(cli, "maria")
    _entrar(cli, "maria")                                                      # o segundo login fecha a sessao anterior
    assert sqlite3.connect(contas_db).execute("SELECT COUNT(*) FROM sessoes").fetchone()[0] == 1
    r = cli.post("/sair", data={"csrf": _csrf(cli)}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/entrar?aviso=saiu"
    assert sqlite3.connect(contas_db).execute("SELECT COUNT(*) FROM sessoes").fetchone()[0] == 0
    r = cli.post("/sair", data={"csrf": _csrf(cli)}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/entrar?aviso=saiu"


def test_nomes_dos_revisores_ocultos_sem_a_permissao(painel):
    """Quem nao entrou nem abre o achado (D145); quem entrou sem ver_nomes_revisores ve o achado sem o nome de quem decidiu."""
    from apoio_divulgacao import cliente_so_painel
    cli, contas, copia, _ = painel
    nome = sqlite3.connect(copia).execute("SELECT verificado_por FROM achados WHERE verificado=1 AND verificado_por<>'' LIMIT 1").fetchone()
    assert nome, "a demonstracao precisa de um achado verificado"
    achado = sqlite3.connect(copia).execute("SELECT achado_id FROM achados WHERE verificado_por=? LIMIT 1", nome).fetchone()[0]
    assert cli.get(f"/achados/{achado}", follow_redirects=False).status_code == 303
    so, gid = cliente_so_painel(painel)
    h = so.get(f"/achados/{achado}").text
    assert nome[0] not in h and "Revisor" in h
    contas.definir_permissoes(gid, {"ver_painel", "ver_nomes_revisores"})
    assert nome[0] in so.get(f"/achados/{achado}").text


def test_faixa_da_conta_e_dica_de_admin(painel):
    cli, _, _, _ = painel
    h = cli.get("/").text
    assert 'href="/entrar"' in h and 'action="/sair"' not in h
    assert "python main.py usuario-admin --login" in cli.get("/entrar").text
    _criar(painel, "maria", "Revisor", nome="Maria Souza")
    _entrar(cli, "maria")
    h = cli.get("/").text
    assert "Maria Souza" in h and '<form method="post" action="/sair"' in h
    nav = h[h.index("<nav"):h.index("</nav>")]
    assert "/sair" not in nav and "/entrar" not in nav


def test_token_guardado_so_como_hash(painel):
    cli, _, _, contas_db = painel
    _criar(painel, "maria", "Revisor")
    token = _entrar(cli, "maria").cookies["__session"].split(".")[1]
    guardado = sqlite3.connect(contas_db).execute("SELECT token_hash FROM sessoes").fetchone()[0]
    assert guardado == hashlib.sha256(token.encode()).hexdigest()


def test_sem_autenticacao_tudo_como_antes(demo, tmp_path):
    from test_painel import _app
    banco, raw = demo
    copia = tmp_path / "d.db"
    shutil.copy(banco, copia)
    app, _ = _app(copia, raw, tmp_path)
    cli = TestClient(app)
    assert cli.get("/chamadas").status_code == 200 and 'href="/entrar"' not in cli.get("/").text
    for metodo in ("get", "post"):
        for caminho in ("/entrar", "/sair"):
            r = getattr(cli, metodo)(caminho)
            assert r.status_code == 404 and "Página não encontrada" in r.text


# ====================== linha de comando ======================
def _cli(monkeypatch, senhas, *args):
    import main
    it = iter(senhas)
    monkeypatch.setattr("getpass.getpass", lambda *a, **k: next(it))
    monkeypatch.setattr(sys, "argv", ["main.py", "usuario-admin", "--simulado", *args])
    main.main()


def test_usuario_admin_cria_e_redefine(ambiente_cli, monkeypatch, capsys):
    _cli(monkeypatch, [SENHA, SENHA], "--login", "chefe", "--nome", " Chefe ")
    assert capsys.readouterr().out.strip().endswith("Administrador criado: chefe")
    _cli(monkeypatch, ["outra-senha-boa", "outra-senha-boa"], "--login", "chefe", "--nome", "Chefe")
    assert capsys.readouterr().out.strip().endswith("Administrador atualizado: chefe")
    c = sqlite3.connect(ambiente_cli / "data" / "contas_simulado.db")
    login, nome, grupo, h = c.execute("SELECT u.login, u.nome, g.nome, u.senha_hash FROM usuarios u JOIN grupos g USING (grupo_id)").fetchone()
    assert (login, nome, grupo) == ("chefe", "Chefe", "Administrador") and A.conferir_senha("outra-senha-boa", h)


@pytest.mark.parametrize("senhas,args,mensagem", [
    (["curta", "curta"], ["--login", "chefe", "--nome", "Chefe"], "Nada foi gravado.\nA senha precisa ter pelo menos 10 caracteres."),
    ([SENHA, SENHA + "x"], ["--login", "chefe", "--nome", "Chefe"], "Nada foi gravado.\nAs senhas não conferem."),
    ([SENHA, SENHA + "x"], ["--login", "Chefe", "--nome", " "],
     "Nada foi gravado.\n" + MSG_LOGIN + "\nO nome não pode ficar vazio.\nAs senhas não conferem.")])
def test_usuario_admin_mensagens_exatas(ambiente_cli, monkeypatch, senhas, args, mensagem):
    with pytest.raises(SystemExit) as e:
        _cli(monkeypatch, senhas, *args)
    assert str(e.value) == mensagem
    db = ambiente_cli / "data" / "contas_simulado.db"
    assert not db.exists() or sqlite3.connect(db).execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 0


def test_usuario_admin_senha_nao_informada(ambiente_cli, monkeypatch):
    import main
    def interrompe(*a, **k):
        raise EOFError
    monkeypatch.setattr("getpass.getpass", interrompe)
    monkeypatch.setattr(sys, "argv", ["main.py", "usuario-admin", "--simulado", "--login", "chefe", "--nome", "Chefe"])
    with pytest.raises(SystemExit) as e:
        main.main()
    assert str(e.value) == "Nada foi gravado.\nSenha não informada."


# ====================== retrabalho R1 (laudo de 18/10/2026) ======================
def test_r1_banco_de_contas_ocupado_vira_503_formatado(painel, monkeypatch):
    cli, contas, _, _ = painel
    def ocupado(*a, **k):
        raise A.ContasOcupadas("ocupado")
    for metodo in ("usuario_da_sessao", "permissoes_do_grupo"):
        monkeypatch.setattr(contas, metodo, ocupado)
    for cookies in ({}, {"__session": "c" * 43 + "." + "s" * 43}):
        cli.cookies.clear()
        for k, v in cookies.items():
            cli.cookies.set(k, v)
        r = cli.get("/")
        assert r.status_code == 503 and "O banco de contas está ocupado. Tente de novo em alguns segundos." in r.text


def test_r1_adaptador_converte_operational_error(tmp_path):
    c = ContasSQLite(tmp_path / "contas.db")
    c.garantir_padrao()
    (tmp_path / "contas.db").unlink()
    (tmp_path / "contas.db").mkdir()                                           # um diretorio no lugar do arquivo: sqlite falha
    with pytest.raises(A.ContasOcupadas):
        c.permissoes_do_grupo("Visitante")


def test_r1_sair_com_banco_ocupado_nao_apaga_o_cookie(painel, monkeypatch):
    cli, contas, _, _ = painel
    _criar(painel, "maria", "Revisor")
    _entrar(cli, "maria")
    csrf = _csrf(cli)
    def ocupado(*a, **k):
        raise A.ContasOcupadas("ocupado")
    monkeypatch.setattr(contas, "fechar_sessao", ocupado)
    r = cli.post("/sair", data={"csrf": csrf}, follow_redirects=False)
    assert r.status_code == 503 and "set-cookie" not in r.headers


def test_r1_autor_pode_desfazer_a_propria_revogacao(painel):
    cli, _, copia, contas_db = painel
    c = sqlite3.connect(contas_db)
    c.execute("INSERT INTO grupos (nome, fixo, criado_em) VALUES ('Rev completo', 0, ?)", (_agora(),))
    c.execute("INSERT INTO grupo_permissoes SELECT grupo_id, p FROM grupos, (SELECT 'ver_painel' p UNION SELECT 'verificar_achados' "
              "UNION SELECT 'revogar_verificacao' UNION SELECT 'ver_nomes_revisores') WHERE nome='Rev completo'")
    c.commit()
    _criar(painel, "ana", "Rev completo", nome="Ana Lima")
    _entrar(cli, "ana")
    achado = sqlite3.connect(copia).execute("SELECT achado_id FROM v_achados_revisao WHERE verificado=0 LIMIT 1").fetchone()[0]
    def form():
        h = cli.get(f"/achados/{achado}").text
        return (re.search(r'name="csrf" value="([^"]+)"', h).group(1), re.search(r'name="versao" value="([^"]*)"', h).group(1))
    csrf, versao = form()
    cli.post(f"/achados/{achado}/verificar", data={"status_final": list(V.STATUS)[0], "observacao": "", "versao": versao, "csrf": csrf})
    csrf, versao = form()
    cli.post(f"/achados/{achado}/revogar", data={"motivo": "engano", "versao": versao, "csrf": csrf})
    r = cli.post(f"/achados/{achado}/desfazer", data={"csrf": _csrf(cli)}, follow_redirects=False)
    assert r.status_code == 303


def test_r1_conflito_nao_mostra_nome_sem_permissao(painel):
    cli, _, copia, contas_db = painel
    c = sqlite3.connect(contas_db)
    c.execute("INSERT INTO grupos (nome, fixo, criado_em) VALUES ('Sem nomes', 0, ?)", (_agora(),))
    c.execute("INSERT INTO grupo_permissoes SELECT grupo_id, p FROM grupos, (SELECT 'ver_painel' p UNION SELECT 'verificar_achados') "
              "WHERE nome='Sem nomes'")
    c.commit()
    _criar(painel, "zeca", "Sem nomes", nome="Zeca")
    _criar(painel, "priv", "Revisor", nome="Nome Privado")
    achado = sqlite3.connect(copia).execute("SELECT achado_id FROM v_achados_revisao WHERE verificado=0 LIMIT 1").fetchone()[0]
    _entrar(cli, "zeca")
    h = cli.get(f"/achados/{achado}").text
    csrf_z, versao_velha = re.search(r'name="csrf" value="([^"]+)"', h).group(1), re.search(r'name="versao" value="([^"]*)"', h).group(1)
    cli.post("/sair", data={"csrf": csrf_z})
    _entrar(cli, "priv")
    h = cli.get(f"/achados/{achado}").text
    cli.post(f"/achados/{achado}/verificar", data={"status_final": list(V.STATUS)[0], "observacao": "",
                                                   "versao": re.search(r'name="versao" value="([^"]*)"', h).group(1),
                                                   "csrf": re.search(r'name="csrf" value="([^"]+)"', h).group(1)})
    cli.post("/sair", data={"csrf": _csrf(cli)})
    _entrar(cli, "zeca")
    r = cli.post(f"/achados/{achado}/verificar", data={"status_final": list(V.STATUS)[0], "observacao": "", "versao": versao_velha,
                                                       "csrf": _csrf(cli)})
    assert r.status_code == 409 and "Nome Privado" not in r.text
    assert "Este achado foi alterado por outra pessoa depois que você abriu a página. Recarregue e decida de novo." in r.text


def test_r1_usuario_admin_sem_simulado_grava_ao_lado_do_banco_real(ambiente_cli, monkeypatch, capsys):
    import main
    import config.settings as S
    monkeypatch.setitem(S.OPCOES["sqlite"], "caminho", ambiente_cli / "data" / "busca.db")     # o banco real do teste fica no tmp
    it = iter([SENHA, SENHA])
    monkeypatch.setattr("getpass.getpass", lambda *a, **k: next(it))
    monkeypatch.setattr(sys, "argv", ["main.py", "usuario-admin", "--login", "chefe", "--nome", "Chefe"])
    main.main()
    assert (ambiente_cli / "data" / "contas.db").exists()


def test_r1_ordem_login_nome_grupo_no_adaptador(contas):
    c, caminho = contas
    _usuario(c, caminho, "maria", nome="Maria")
    with pytest.raises(ValueError, match="^Login já existe: maria$"):
        c.criar_usuario("maria", "MARIA", 999, A.hash_senha(SENHA), _agora())
    with pytest.raises(ValueError, match="^Nome já existe: MARIA$"):
        c.criar_usuario("outra", "MARIA", 999, A.hash_senha(SENHA), _agora())


def test_r1_csrf_com_acento_e_recusado_sem_quebrar(painel):
    cli, _, _, _ = painel
    _csrf(cli)
    for valor in ("ç", "�"):
        r = cli.post("/entrar", data={"login": "x", "senha": "y", "proximo": "/", "csrf": valor}, follow_redirects=False)
        assert r.status_code == 403 and "Formulário recusado" in r.text


def test_r1_nome_unico_sem_distinguir_maiusculas_acentuadas(contas):
    c, caminho = contas
    _usuario(c, caminho, "joao", nome="João")
    with pytest.raises(ValueError, match="^Nome já existe: JOÃO$"):
        _usuario(c, caminho, "joao2", nome="JOÃO")


def test_r1_indice_de_sessoes_por_usuario_e_parser_unico(contas):
    _, caminho = contas
    assert sqlite3.connect(caminho).execute("SELECT name FROM sqlite_master WHERE name='sessoes_por_usuario'").fetchone()
    assert A.ler_instante("2026-10-18T00:00:00+00:00") is not None
    assert A.ler_instante("2026-10-18 00:00:00") is None and A.ler_instante("lixo") is None
    import pathlib
    for f in ("painel/app.py", "adaptadores/contas_sqlite.py"):
        assert "def _parse_iso" not in (pathlib.Path(__file__).resolve().parent.parent / f).read_text(encoding="utf-8")


# ====================== retrabalho R2 (laudo de 18/10/2026) ======================
def test_r2_caminho_das_contas_e_sem_alias():
    import main
    from types import SimpleNamespace
    from pathlib import Path
    f = SimpleNamespace(caminho_banco=Path("/x/dados/busca.db"))
    assert main._caminho_contas(f, False) == Path("/x/dados/contas.db")
    assert main._caminho_contas(f, True) == Path("/x/dados/contas_simulado.db")
    for nome, simulado in (("contas.db", False), ("contas_simulado.db", True)):
        with pytest.raises(SystemExit) as e:
            main._caminho_contas(SimpleNamespace(caminho_banco=Path("/x/dados") / nome), simulado)
        assert str(e.value) == "O banco da pesquisa não pode se chamar contas.db nem contas_simulado.db."


def test_r2_sem_except_pass_no_adaptador_de_contas():
    import pathlib, re as _re
    fonte = (pathlib.Path(__file__).resolve().parent.parent / "adaptadores" / "contas_sqlite.py").read_text(encoding="utf-8")
    assert "except Exception" not in fonte and not _re.search(r"^\s*pass\s*$", fonte, _re.M)
    assert "BEGIN IMMEDIATE" in fonte


def test_r2_pagina_de_entrada_com_banco_ocupado_vira_503(painel, monkeypatch):
    cli, contas, _, _ = painel
    csrf = _csrf(cli)
    def ocupado(*a, **k):
        raise A.ContasOcupadas("ocupado")
    monkeypatch.setattr(contas, "existe_admin_ativo", ocupado)
    r = cli.get("/entrar")
    assert r.status_code == 503 and "O banco de contas está ocupado. Tente de novo em alguns segundos." in r.text
    r = cli.post("/entrar", data={"login": "x", "senha": "", "proximo": "/", "csrf": csrf}, follow_redirects=False)
    assert r.status_code == 503
