"""RB16 (D76, D78): area de administracao (usuarios, matriz de permissoes, auditoria) e atividade dos revisores."""
import re
import shutil
import sqlite3
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
from test_painel_acessibilidade import verificar

SENHA = "senha-de-teste-123"
MSG_LOGIN = "O login deve ter de 3 a 40 caracteres: letras minúsculas, números, ponto, hífen ou sublinhado."
HOJE = datetime.now(timezone.utc).date()


def _agora():
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture
def adm(demo, tmp_path):
    banco, raw = demo
    copia = tmp_path / "demo.db"
    shutil.copy(banco, copia)
    ctx = Contexto(banco="real", nome_banco=copia.name, somente_leitura=False, pasta_backup=tmp_path / "b",
                   ufs=dict(C.UFS), status_permitidos=set(V.STATUS) | set(V.STATUS_FINAL_EXTRA),
                   status_definicoes=dict(V.STATUS), hosts_permitidos=("testserver",), autenticacao=True)
    contas_db = tmp_path / "contas.db"
    contas = ContasSQLite(contas_db)
    cli = TestClient(criar_app(LeituraPainelSQLite(copia), lambda: RepositorioSQLite(copia), BrutoLocal(raw), ctx, contas=contas))
    contas.definir_admin("chefe", "Chefe", A.hash_senha(SENHA), _agora())
    _entrar(cli, "chefe")
    return cli, contas, contas_db, copia


def _csrf(cli, caminho="/entrar"):
    return re.search(r'name="csrf" value="([^"]+)"', cli.get(caminho).text).group(1)


def _entrar(cli, login, senha=SENHA):
    return cli.post("/entrar", data={"login": login, "senha": senha, "proximo": "/", "csrf": _csrf(cli)}, follow_redirects=False)


def _sair(cli):
    cli.post("/sair", data={"csrf": _csrf(cli, "/")})


def _gid(contas_db, nome):
    return sqlite3.connect(contas_db).execute("SELECT grupo_id FROM grupos WHERE nome=?", (nome,)).fetchone()[0]


def _uid(contas_db, login):
    return sqlite3.connect(contas_db).execute("SELECT usuario_id FROM usuarios WHERE login=?", (login,)).fetchone()[0]


def _criar(cli, contas_db, login="maria", nome="Maria Souza", grupo="Revisor", senha=SENHA, senha2=None, grupo_id=None):
    gid = grupo_id if grupo_id is not None else str(_gid(contas_db, grupo))
    return cli.post("/admin/usuarios", data={"login": login, "nome": nome, "grupo_id": gid, "senha": senha,
                                             "senha2": senha if senha2 is None else senha2, "csrf": _csrf(cli, "/admin/usuarios")},
                    follow_redirects=False)


def _erros(h):
    i = h.index('class="aviso erro"')
    return re.findall(r"<li>([^<]+)</li>", h[i:h.index("</ul>", i)])


def _auditoria(contas_db):
    return [r for r in sqlite3.connect(contas_db).execute("SELECT acao, alvo, detalhe FROM auditoria_admin ORDER BY id")]


# ====================== navegacao e acessibilidade ======================
@pytest.mark.parametrize("caminho,titulo", [("/admin/usuarios", "Usuários"), ("/admin/grupos", "Permissões por grupo"),
                                            ("/admin/auditoria", "Registro de administração"),
                                            ("/estatisticas-usuarios", "Atividade dos revisores")])
def test_paginas_acessiveis_marcadas_no_menu(adm, caminho, titulo):
    cli, _, _, _ = adm
    h = cli.get(caminho).text
    assert f"<h1>{titulo}</h1>" in h and f'<a href="{caminho}" aria-current="page">{titulo}</a>' in h and verificar(h) == []
    assert 'class="admin-abas"' not in h                                     # o grupo Administracao do menu substituiu as abas


def test_admin_redireciona_lista_e_links(adm):
    cli, _, contas_db, _ = adm
    r = cli.get("/admin", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin/usuarios"
    h = cli.get("/admin/usuarios").text
    assert re.findall(r"<th[^>]*>([^<]+)</th>", h)[:5] == ["Login", "Nome", "Grupo", "Situação", "Último acesso"]
    inicio = cli.get("/").text
    assert 'class="conta-admin" href="/admin"' in inicio and 'class="conta-estatisticas" href="/estatisticas-usuarios"' in inicio
    nav = inicio[inicio.index("<nav"):inicio.index("</nav>")]
    assert '<details class="menu-grupo" data-grupo="administracao">' in nav and '<a href="/admin/usuarios">Usuários</a>' in nav


# ====================== usuarios ======================
def test_criar_usuario_e_auditar_na_mesma_transacao(adm):
    cli, _, contas_db, _ = adm
    r = _criar(cli, contas_db, nome="  Maria Souza  ")
    assert r.status_code == 303 and r.headers["location"] == "/admin/usuarios?ok=1"
    assert "Alteração gravada." in cli.get("/admin/usuarios?ok=1").text
    assert sqlite3.connect(contas_db).execute("SELECT nome FROM usuarios WHERE login='maria'").fetchone() == ("Maria Souza",)
    assert _auditoria(contas_db) == [("criar_usuario", "maria", "Revisor")]


@pytest.mark.parametrize("dados,esperado", [
    ({"login": "Maria", "nome": " ", "senha": "curta", "senha2": "outra", "grupo_id": "x"},
     [MSG_LOGIN, "O nome não pode ficar vazio.", "A senha precisa ter pelo menos 10 caracteres.", "As senhas não conferem.",
      "Escolha um grupo válido."]),
    ({"grupo_id": ""}, ["Escolha um grupo válido."]),
    ({"grupo_id": "9223372036854775808"}, ["Escolha um grupo válido."]),
    ({"grupo_id": "999"}, ["Escolha um grupo válido."]),
    ({"grupo": "Visitante"}, ["Escolha um grupo válido."])])
def test_criar_usuario_erros_exatos_sem_gravar(adm, dados, esperado):
    cli, _, contas_db, _ = adm
    kw = {"login": dados.get("login", "maria"), "nome": dados.get("nome", "Maria"), "senha": dados.get("senha", SENHA),
          "senha2": dados.get("senha2"), "grupo": dados.get("grupo", "Revisor"), "grupo_id": dados.get("grupo_id")}
    r = _criar(cli, contas_db, **kw)
    assert r.status_code == 400 and _erros(r.text) == esperado
    assert SENHA not in r.text
    assert sqlite3.connect(contas_db).execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 1 and _auditoria(contas_db) == []
    assert verificar(r.text) == []


def test_criar_usuario_duplicado(adm):
    cli, _, contas_db, _ = adm
    _criar(cli, contas_db)
    r = _criar(cli, contas_db, login="maria2", nome="maria SOUZA")
    assert r.status_code == 400 and _erros(r.text) == ["Nome já existe: maria SOUZA"]


@pytest.mark.parametrize("caminho,status,texto", [
    ("/admin/usuarios/abc", 404, "Endereço inválido"), ("/admin/usuarios/9223372036854775808", 404, "Endereço inválido"),
    ("/admin/usuarios/999", 404, "Não existe o usuário nº 999.")])
def test_ids_invalidos_e_desconhecidos(adm, caminho, status, texto):
    cli, _, _, _ = adm
    r = cli.get(caminho)
    assert r.status_code == status and texto in r.text


def test_regras_do_ultimo_admin_e_da_propria_conta(adm):
    cli, _, contas_db, _ = adm
    uid = _uid(contas_db, "chefe")
    h = cli.get(f"/admin/usuarios/{uid}").text
    assert "Desativar conta" not in h
    csrf = _csrf(cli, f"/admin/usuarios/{uid}")
    r = cli.post(f"/admin/usuarios/{uid}", data={"acao": "desativar", "csrf": csrf}, follow_redirects=False)
    assert r.status_code == 400 and _erros(r.text) == ["Você não pode desativar a própria conta."]
    r = cli.post(f"/admin/usuarios/{uid}", data={"acao": "dados", "login": "chefe", "nome": "Chefe",
                                                 "grupo_id": str(_gid(contas_db, "Revisor")), "csrf": csrf}, follow_redirects=False)
    assert r.status_code == 400 and _erros(r.text) == ["O painel precisa de pelo menos um administrador ativo."]
    assert cli.post(f"/admin/usuarios/{uid}", data={"acao": "x", "csrf": csrf}).status_code == 400


def test_editar_audita_valores_antigos_e_novos_e_sem_mudanca_nada(adm):
    cli, _, contas_db, _ = adm
    _criar(cli, contas_db)
    uid = _uid(contas_db, "maria")
    csrf = _csrf(cli, f"/admin/usuarios/{uid}")
    base = {"acao": "dados", "login": "maria", "nome": "Maria Souza", "grupo_id": str(_gid(contas_db, "Revisor")), "csrf": csrf}
    assert cli.post(f"/admin/usuarios/{uid}", data=base, follow_redirects=False).status_code == 303
    assert len(_auditoria(contas_db)) == 1
    novo = {**base, "login": "msouza", "grupo_id": str(_gid(contas_db, "Leitor"))}
    assert cli.post(f"/admin/usuarios/{uid}", data=novo, follow_redirects=False).status_code == 303
    assert _auditoria(contas_db)[-1] == ("editar_usuario", "maria", "login: maria -> msouza; grupo: Revisor -> Leitor")


def test_desativar_reativar_idempotentes_e_senha(adm):
    cli, contas, contas_db, _ = adm
    _criar(cli, contas_db)
    uid = _uid(contas_db, "maria")
    contas.abrir_sessao(uid, "h-maria", _agora())
    csrf = _csrf(cli, f"/admin/usuarios/{uid}")
    for acao in ("desativar", "desativar", "reativar", "reativar"):
        assert cli.post(f"/admin/usuarios/{uid}", data={"acao": acao, "csrf": csrf}, follow_redirects=False).status_code == 303
    assert [a for a, _, _ in _auditoria(contas_db)] == ["criar_usuario", "desativar_usuario", "reativar_usuario"]
    assert sqlite3.connect(contas_db).execute("SELECT COUNT(*) FROM sessoes WHERE usuario_id=?", (uid,)).fetchone()[0] == 0
    r = cli.post(f"/admin/usuarios/{uid}", data={"acao": "senha", "senha": "nova-senha-boa", "senha2": "nova-senha-boa", "csrf": csrf},
                 follow_redirects=False)
    assert r.status_code == 303 and _auditoria(contas_db)[-1] == ("redefinir_senha", "maria", None)


def test_redefinir_a_propria_senha_leva_a_entrada(adm):
    cli, _, contas_db, _ = adm
    uid = _uid(contas_db, "chefe")
    csrf = _csrf(cli, f"/admin/usuarios/{uid}")
    r = cli.post(f"/admin/usuarios/{uid}", data={"acao": "senha", "senha": "nova-senha-boa", "senha2": "nova-senha-boa", "csrf": csrf},
                 follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/entrar"


# ====================== matriz ======================
def _ocultos_da_matriz(cli):
    """Os campos ocultos que a pagina entrega: os grupos exibidos e a versao das permissoes deles."""
    h = cli.get("/admin/grupos").text
    return {"grupos": re.findall(r'<input type="hidden" name="grupos" value="([^"]*)">', h),
            "versao": (re.findall(r'<input type="hidden" name="versao" value="([^"]*)">', h) or [""])[0]}


def _dados_matriz(cli, contas):
    dados = {"csrf": _csrf(cli, "/admin/grupos"), **_ocultos_da_matriz(cli)}
    for g in contas.grupos():
        if g["nome"] != "Administrador":
            for p in g["permissoes"]:
                dados[f"p-{g['grupo_id']}-{p}"] = "on"
    return dados


@pytest.mark.parametrize("grupo,permissoes,mensagem", [
    ("Administrador", set(), "As permissões do Administrador não podem ser alteradas."),
    ("Visitante", {"ver_painel", "triar_artigos"}, "O grupo Visitante não pode receber essa permissão: triar_artigos"),
    ("Visitante", {"ver_estatisticas_usuarios"}, "O grupo Visitante não pode receber essa permissão: ver_estatisticas_usuarios"),
    ("Leitor", {"zzz", "aaa"}, "Permissão desconhecida: aaa")])
def test_definir_permissoes_regras_do_adaptador(adm, grupo, permissoes, mensagem):
    _, contas, contas_db, _ = adm
    with pytest.raises(ValueError, match=re.escape(mensagem)):
        contas.definir_permissoes(_gid(contas_db, grupo), permissoes)
    assert contas.definir_permissoes(_gid(contas_db, "Leitor"),
                                     {"ver_painel", "ver_nomes_revisores", "ver_registros_revisao", "ver_custos"}) == 0


# ====================== grupos ======================
def test_grupos_criar_renomear_e_travas(adm):
    cli, _, contas_db, _ = adm
    csrf = lambda: _csrf(cli, "/admin/grupos")
    assert cli.post("/admin/grupos/novo", data={"nome": "  Bolsistas  ", "csrf": csrf()}, follow_redirects=False).status_code == 303
    g = _gid(contas_db, "Bolsistas")
    assert cli.post(f"/admin/grupos/{g}/renomear", data={"nome": "Bolsistas", "csrf": csrf()}, follow_redirects=False).status_code == 303
    assert cli.post(f"/admin/grupos/{g}/renomear", data={"nome": "BOLSISTAS", "csrf": csrf()}, follow_redirects=False).status_code == 303
    for nome in ("Visitante", "Revisor", "Leitor", "Administrador"):
        r = cli.post(f"/admin/grupos/{_gid(contas_db, nome)}/renomear", data={"nome": "Outro", "csrf": csrf()})
        assert r.status_code == 400 and _erros(r.text) == ["Este grupo não pode ser renomeado."]
    r = cli.post("/admin/grupos/novo", data={"nome": "bolsistas", "csrf": csrf()})
    assert r.status_code == 400 and _erros(r.text) == ["Grupo já existe: bolsistas"]
    assert cli.post("/admin/grupos/novo", data={"nome": "x" * 40, "csrf": csrf()}, follow_redirects=False).status_code == 303
    r = cli.post("/admin/grupos/novo", data={"nome": "y" * 41, "csrf": csrf()})
    assert _erros(r.text) == ["O nome do grupo pode ter no máximo 40 caracteres."]
    assert cli.post("/admin/grupos/999/renomear", data={"nome": "Z", "csrf": csrf()}).status_code == 404
    assert [(a, al, d) for a, al, d in _auditoria(contas_db)] == [
        ("criar_grupo", "Bolsistas", None), ("renomear_grupo", "BOLSISTAS", "Bolsistas -> BOLSISTAS"), ("criar_grupo", "x" * 40, None)]


# ====================== auditoria ======================
def test_pagina_de_auditoria(adm):
    cli, _, contas_db, _ = adm
    assert "Nenhuma ação registrada." in cli.get("/admin/auditoria").text
    _criar(cli, contas_db)
    h = cli.get("/admin/auditoria").text
    assert "criar_usuario" in h and "chefe" in h and verificar(h) == []


# ====================== atividade dos revisores ======================
def _historico(copia):
    c = sqlite3.connect(copia)
    c.execute("DELETE FROM achados_revisoes")
    c.execute("DELETE FROM triagem_revisoes")
    hoje = HOJE.isoformat() + "T12:00:00+00:00"
    velho = (HOJE - timedelta(days=40)).isoformat() + "T12:00:00+00:00"
    a = c.execute("SELECT achado_id FROM achados LIMIT 1").fetchone()[0]
    t = c.execute("SELECT artigo_id FROM artigos LIMIT 1").fetchone()[0]
    linhas_a = [("Ana", hoje, 0, 0), ("Ana", hoje, 1, 0), (" Ana ", velho, 0, 1), ("Bruno", hoje, 0, 0), ("  ", hoje, 0, 0)]
    for rev, quando, desfeita, indep in linhas_a:
        c.execute("INSERT INTO achados_revisoes (achado_id, verificado_por, status_final, importado_em, desfeita, independente) "
                  "VALUES (?, ?, 'em_uso', ?, ?, ?)", (a, rev, quando, desfeita, indep))
    for rev, quando in (("Ana", hoje), ("Bruno", velho), ("Bruno", velho)):
        c.execute("INSERT INTO triagem_revisoes (artigo_id, revisor, decisao, importado_em, independente) VALUES (?, ?, 'incluir', ?, 0)",
                  (t, rev, quando))
    c.commit()


def test_resumir_atividade_tabela():
    hoje = HOJE.isoformat()
    linhas = [{"revisor": "Ana", "dia": hoje, "achados": 2, "artigos": 1},
              {"revisor": "Bruno", "dia": (HOJE - timedelta(days=40)).isoformat(), "achados": 0, "artigos": 5},
              {"revisor": "Ana", "dia": (HOJE - timedelta(days=29)).isoformat(), "achados": 1, "artigos": 0}]
    totais, janela = A.resumir_atividade(linhas, hoje)
    assert [(t["revisor"], t["achados"], t["artigos"], t["hoje"], t["ultimo_dia"]) for t in totais] == [
        ("Bruno", 0, 5, 0, (HOJE - timedelta(days=40)).isoformat()), ("Ana", 3, 1, 3, hoje)]
    assert [(j["dia"], j["revisor"]) for j in janela] == [(hoje, "Ana"), ((HOJE - timedelta(days=29)).isoformat(), "Ana")]


def test_atividade_conta_eventos_do_historico(adm):
    cli, _, _, copia = adm
    _historico(copia)
    h = cli.get("/estatisticas-usuarios").text
    assert re.findall(r"<th[^>]*>([^<]+)</th>", h)[:5] == ["Revisor", "Decisões em achados", "Decisões em artigos", "Hoje (UTC)",
                                                          "Último dia com decisão"]
    assert "Ana" in h and "Bruno" in h and verificar(h) == []


def test_atividade_vazia(adm):
    cli, _, _, copia = adm
    c = sqlite3.connect(copia)
    c.execute("DELETE FROM achados_revisoes")
    c.execute("DELETE FROM triagem_revisoes")
    c.commit()
    h = cli.get("/estatisticas-usuarios").text
    assert "Ainda não há decisões de revisores." in h and "Últimos 30 dias" not in h


def test_atividade_exige_permissao_e_some_para_visitante(adm):
    cli, _, contas_db, _ = adm
    _criar(cli, contas_db, login="leo", nome="Leo", grupo="Leitor")
    _sair(cli)
    _entrar(cli, "leo")
    assert cli.get("/estatisticas-usuarios", follow_redirects=False).status_code == 403
    assert cli.get("/admin/usuarios", follow_redirects=False).status_code == 403
    inicio = cli.get("/").text
    assert 'href="/admin"' not in inicio and 'href="/estatisticas-usuarios"' not in inicio


def test_atividade_com_nomes_ocultos_numera_revisores(adm):
    cli, contas, contas_db, copia = adm
    _historico(copia)
    g = sqlite3.connect(contas_db)
    g.execute("INSERT INTO grupos (nome, fixo, criado_em) VALUES ('Estat', 0, ?)", (_agora(),))
    g.execute("INSERT INTO grupo_permissoes SELECT grupo_id, p FROM grupos, (SELECT 'ver_painel' p UNION SELECT 'ver_estatisticas_usuarios') "
              "WHERE nome='Estat'")
    g.commit()
    _criar(cli, contas_db, login="est", nome="Est", grupo="Estat")
    _sair(cli)
    _entrar(cli, "est")
    h = cli.get("/estatisticas-usuarios").text
    assert "Ana" not in h and "Bruno" not in h and "Revisor 1" in h and "Revisor 2" in h


def test_permissao_exigida_e_nome_de_grupo():
    assert A.permissao_exigida("GET", "/estatisticas-usuarios") == "ver_estatisticas_usuarios"
    assert A.validar_nome_grupo(" ") == ["O nome do grupo não pode ficar vazio."]
    assert A.validar_nome_grupo("x" * 40) == [] and A.validar_nome_grupo("x" * 41) == ["O nome do grupo pode ter no máximo 40 caracteres."]
    assert not A.pode("Visitante", {"ver_estatisticas_usuarios"}, "ver_estatisticas_usuarios")


# ====================== retrabalho R1 ======================
def test_r1_reexibe_os_valores_enviados_mesmo_vazios(adm):
    cli, _, contas_db, _ = adm
    _criar(cli, contas_db)
    uid = _uid(contas_db, "maria")
    r = cli.post(f"/admin/usuarios/{uid}", data={"acao": "dados", "login": "maria", "nome": "   ", "grupo_id": str(_gid(contas_db, "Revisor")),
                                                 "csrf": _csrf(cli, f"/admin/usuarios/{uid}")})
    assert r.status_code == 400 and _erros(r.text) == ["O nome não pode ficar vazio."]
    tag = re.search(r'<input[^>]*id="nome"[^>]*>', r.text).group(0)
    assert 'value=""' in tag and "Maria Souza" not in tag


def test_r1_acao_desconhecida_reexibe_a_pagina_do_usuario(adm):
    cli, _, contas_db, _ = adm
    uid = _uid(contas_db, "chefe")
    r = cli.post(f"/admin/usuarios/{uid}", data={"acao": "x", "csrf": _csrf(cli, f"/admin/usuarios/{uid}")})
    assert r.status_code == 400 and "<h1>Usuário chefe</h1>" in r.text and _erros(r.text) == ["Ação desconhecida."]


def test_r1_auditoria_mostra_alteracao_gravada(adm):
    cli, _, _, _ = adm
    assert "Alteração gravada." in cli.get("/admin/auditoria?ok=1").text


def test_r1_validacao_do_nome_antes_da_regra_de_grupo_fixo(adm):
    cli, _, contas_db, _ = adm
    r = cli.post(f"/admin/grupos/{_gid(contas_db, 'Administrador')}/renomear", data={"nome": "  ", "csrf": _csrf(cli, "/admin/grupos")})
    assert r.status_code == 400 and _erros(r.text) == ["O nome do grupo não pode ficar vazio."]


def test_r1_sem_apelido_nem_duplicacao_no_adaptador():
    import pathlib
    raiz = pathlib.Path(__file__).resolve().parent.parent
    assert "def decisoes_por_revisor" not in (raiz / "adaptadores" / "leitura_sqlite.py").read_text(encoding="utf-8")
    fonte = (raiz / "adaptadores" / "contas_sqlite.py").read_text(encoding="utf-8")
    assert fonte.count("INSERT INTO auditoria_admin") == 1 and fonte.count("INSERT INTO grupo_permissoes") <= 2


# ====================== retrabalho R2 ======================
def test_r2_pagina_do_usuario_abre_com_os_dados_gravados(adm):
    cli, _, contas_db, _ = adm
    _criar(cli, contas_db)
    uid = _uid(contas_db, "maria")
    h = cli.get(f"/admin/usuarios/{uid}").text
    assert re.search(r'id="login"[^>]*value="maria"|value="maria"[^>]*id="login"', h)
    assert re.search(r'id="nome"[^>]*value="Maria Souza"|value="Maria Souza"[^>]*id="nome"', h)
    g = _gid(contas_db, "Revisor")
    assert re.search(rf'<option value="{g}" selected>', h)


def test_r2_acao_desconhecida_mantem_os_campos_enviados(adm):
    cli, _, contas_db, _ = adm
    _criar(cli, contas_db)
    uid = _uid(contas_db, "maria")
    leitor = _gid(contas_db, "Leitor")
    r = cli.post(f"/admin/usuarios/{uid}", data={"acao": "x", "login": "nova", "nome": " Novo nome ", "grupo_id": str(leitor),
                                                 "csrf": _csrf(cli, f"/admin/usuarios/{uid}")})
    assert r.status_code == 400
    assert re.search(r'id="login"[^>]*value="nova"|value="nova"[^>]*id="login"', r.text)
    assert re.search(r'id="nome"[^>]*value="Novo nome"|value="Novo nome"[^>]*id="nome"', r.text)
    assert re.search(rf'<option value="{leitor}" selected>', r.text)


def test_r2_nomes_de_grupo_reexibidos_apos_erro(adm):
    cli, _, contas_db, _ = adm
    cli.post("/admin/grupos/novo", data={"nome": "Bolsistas", "csrf": _csrf(cli, "/admin/grupos")})
    r = cli.post("/admin/grupos/novo", data={"nome": "  bolsistas  ", "csrf": _csrf(cli, "/admin/grupos")})
    assert r.status_code == 400 and re.search(r'id="nome-grupo"[^>]*value="bolsistas"|value="bolsistas"[^>]*id="nome-grupo"', r.text)
    g = _gid(contas_db, "Bolsistas")
    cli.post("/admin/grupos/novo", data={"nome": "Outro", "csrf": _csrf(cli, "/admin/grupos")})
    r = cli.post(f"/admin/grupos/{g}/renomear", data={"nome": " outro ", "csrf": _csrf(cli, "/admin/grupos")})
    assert r.status_code == 400 and re.search(rf'id="renomear-{g}"[^>]*value="outro"|value="outro"[^>]*id="renomear-{g}"', r.text)
    h = cli.get("/admin/grupos").text
    assert re.search(r'id="nome-grupo"[^>]*value=""|value=""[^>]*id="nome-grupo"', h)
