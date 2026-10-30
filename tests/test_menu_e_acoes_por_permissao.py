"""O menu, as filas e os botoes de acao (continuar a revisao ou a triagem, links dos alertas, sortear a amostra, desfazer)
seguem a mesma regra que o servidor aplica: so aparecem para quem o servidor aceitaria; o desfazer usa a mesma funcao no botao e
na rota; no modo somente leitura nenhuma acao de escrita e oferecida.
"""
import dataclasses
import re
import shutil
from apoio_divulgacao import gravar_politica
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from adaptadores.bruto_local import BrutoLocal
from adaptadores.contas_sqlite import ContasSQLite
from adaptadores.leitura_sqlite import LeituraPainelSQLite
from adaptadores.repositorio_sqlite import RepositorioSQLite
from config import consultas as C, vocabulario as V
from dominio import autenticacao as A
from painel import navegacao
from painel.app import Contexto, criar_app
from test_autenticacao import _criar, _entrar, _usuario, painel  # noqa: F401
from test_painel import demo  # noqa: F401
from test_validacao_vies import _cli as _cli_sem_login, _contexto, banco  # noqa: F401

GRUPOS = ("Visitante", "Leitor", "Revisor", "Administrador")
DECIDE_ACHADO = ("POST", "/achados/1/verificar")
DECIDE_ARTIGO = ("POST", "/literatura/artigos/1/triar")


def _pode(grupo, metodo, caminho):
    return A.pode_acessar(grupo, A.GRUPOS_PADRAO[grupo], metodo, caminho)


# ---------------- dominio ----------------
@pytest.mark.parametrize("grupo,perms,metodo,caminho,esperado", [
    ("Visitante", {"ver_painel"}, "GET", "/", True),
    ("Visitante", {"ver_painel"}, "GET", "/execucoes", False),
    ("Visitante", {"ver_painel", "triar_artigos"}, "POST", "/literatura/artigos/1/triar", False),   # visitante nunca escreve
    ("Leitor", {"ver_painel"}, "HEAD", "/", True),
    ("Leitor", {"ver_painel"}, "POST", "/validacao/sortear", False),
    ("Revisor", {"ver_painel", "triar_artigos"}, "POST", "/literatura/artigos/1/triar", True),
    ("Administrador", set(), "POST", "/validacao/sortear", True),
    ("Leitor", {"ver_painel"}, "GET", "/conta", True),
    ("Visitante", {"ver_painel"}, "GET", "/conta", False),
    ("Leitor", set(), "GET", "/entrar", True),
])
def test_pode_acessar_e_pode_com_a_permissao_da_rota(grupo, perms, metodo, caminho, esperado):
    assert A.pode_acessar(grupo, perms, metodo, caminho) is esperado
    assert esperado == A.pode(grupo, perms, A.permissao_exigida(metodo, caminho))


@pytest.mark.parametrize("grupo,nome,autor,esperado", [
    ("Administrador", "Chefe", "Ana", True), ("Administrador", None, None, True),
    ("Revisor", "Ana", "Ana", True), ("Revisor", "Ana", "Bia", False), ("Revisor", "Ana", None, False),
    ("Revisor", "", "", False), ("Revisor", None, "Ana", False), (None, None, None, False),
])
def test_pode_desfazer_decisao(grupo, nome, autor, esperado):
    assert A.pode_desfazer_decisao(grupo, nome, autor) is esperado


# ---------------- navegacao (funcao pura) ----------------
def _hrefs(grupos):
    return [i["href"] for g in grupos for i in g["itens"]]


def test_sem_regra_de_acesso_o_menu_fica_como_antes():
    for banco_ in ("real", "vies"):
        assert navegacao.grupos("/", banco=banco_) == navegacao.grupos("/", banco=banco_, pode=None)


def test_item_some_quando_a_regra_nega_o_get_do_destino():
    nega = {"/execucoes", "/chamadas", "/execucoes/comparar"}
    g = navegacao.grupos("/", banco="real", pode=lambda m, c: not (m == "GET" and c in nega))
    assert not set(_hrefs(g)) & nega and "/estados" in _hrefs(g)


@pytest.mark.parametrize("fila", ["/literatura/triagem", "/revisao/achados"])
def test_fila_so_aparece_para_quem_decide(fila):
    assert navegacao.ACOES_DOS_ITENS == {"/literatura/triagem": DECIDE_ARTIGO, "/revisao/achados": DECIDE_ACHADO}
    assert fila not in _hrefs(navegacao.grupos("/", banco="real", pode=lambda m, c: m == "GET"))
    assert fila in _hrefs(navegacao.grupos("/", banco="real", pode=lambda m, c: True))
    assert fila not in _hrefs(navegacao.grupos("/", banco="real", pode=lambda m, c: m == "POST"))


def test_grupo_sem_nenhum_item_visivel_nao_aparece():
    g = navegacao.grupos("/", banco="real", pode=lambda m, c: c in ("/", "/sobre"))
    assert [x["id"] for x in g] == ["revisao", "auditoria"] and _hrefs(g) == ["/", "/sobre"]


@pytest.mark.parametrize("banco_,fora", [("vies", "/estados"), ("real", "/observatorio")])
def test_itens_fora_do_banco_nem_sao_consultados(banco_, fora):
    vistos = []
    navegacao.grupos("/", banco=banco_, pode=lambda m, c: vistos.append((m, c)) or True)
    assert ("GET", fora) not in vistos and ("GET", "/") in vistos and DECIDE_ARTIGO in vistos


# ---------------- painel real com autenticacao ----------------
@pytest.fixture
def clientes(painel):  # noqa: F811
    cli, _, _, _ = painel
    saida = {"Visitante": cli}
    for grupo in GRUPOS[1:]:
        login = grupo.lower()
        _criar(painel, login, grupo)
        c = TestClient(cli.app)
        assert _entrar(c, login).status_code == 303
        saida[grupo] = c
    return saida


def _menu(html):
    nav = html[html.index('<nav'):html.index('</nav>')]
    return re.findall(r'<a [^>]*href="([^"]+)"', nav)


def _aceito(r):
    """Pagina servida (200) ou redirecionamento para outra pagina do painel que nao a entrada."""
    if r.status_code in (301, 302, 303, 307, 308):
        return urlsplit(r.headers["location"]).path != "/entrar"
    return r.status_code == 200


@pytest.mark.parametrize("grupo", GRUPOS)
def test_nenhum_item_do_menu_leva_a_recusa(clientes, grupo):
    cli = clientes[grupo]
    links = _menu(cli.get("/").text)
    assert links
    assert [h for h in links if not _aceito(cli.get(h, follow_redirects=False))] == []


@pytest.mark.parametrize("grupo,ausentes,presentes", [
    ("Visitante", {"/execucoes", "/chamadas", "/execucoes/comparar", "/revisao/achados", "/literatura/triagem", "/estados",
                   "/achados", "/analises"}, {"/", "/sobre", "/literatura/prisma", "/metodologia"}),
    ("Leitor", {"/execucoes", "/chamadas", "/execucoes/comparar", "/revisao/achados", "/literatura/triagem"}, {"/", "/estados"}),
    ("Revisor", {"/admin/usuarios"}, {"/execucoes", "/chamadas", "/revisao/achados", "/literatura/triagem"}),
    ("Administrador", set(), {"/execucoes", "/revisao/achados", "/admin/usuarios", "/admin/grupos"}),
])
def test_menu_de_cada_grupo(clientes, grupo, ausentes, presentes):
    links = set(_menu(clientes[grupo].get("/").text))
    assert not links & ausentes and presentes <= links


def test_middleware_menu_e_botoes_usam_a_mesma_funcao(clientes, monkeypatch):
    original = A.pode_acessar
    negados = {("GET", "/estados"), DECIDE_ACHADO, DECIDE_ARTIGO}
    monkeypatch.setattr(A, "pode_acessar", lambda g, p, m, c: False if (m, c) in negados else original(g, p, m, c))
    adm = clientes["Administrador"]
    h = adm.get("/").text
    assert "/estados" not in _menu(h) and "/revisao/achados" not in _menu(h)
    assert "Continuar a revisão" not in h and ">Começar revisão<" not in h
    assert "Continuar a triagem" not in adm.get("/literatura").text
    assert clientes["Leitor"].get("/estados", follow_redirects=False).status_code == 403   # o servidor usa a mesma funcao


def test_continuar_a_revisao_e_o_link_do_alerta(clientes):
    for grupo in GRUPOS:
        h = clientes[grupo].get("/").text
        decide = _pode(grupo, *DECIDE_ACHADO)
        assert ('href="/revisao/achados">Continuar a revisão' in h) is decide, grupo
        assert ("Achados aguardando verificação humana" in h) is decide, grupo   # a fila so aparece a quem decide
        assert ">Começar revisão<" not in h and "ainda sem verificação humana." not in h, grupo
    assert 'href="/revisao/achados">Continuar a revisão' in clientes["Revisor"].get("/").text


def test_continuar_a_triagem_na_literatura(clientes):
    for grupo in GRUPOS:
        if grupo == "Visitante":                                 # fechada para quem nao entrou (D145)
            assert clientes[grupo].get("/literatura", follow_redirects=False).status_code == 303
            continue
        h = clientes[grupo].get("/literatura").text
        assert ('href="/literatura/triagem">Continuar a triagem' in h) is _pode(grupo, *DECIDE_ARTIGO), grupo
    assert 'href="/literatura/triagem">Continuar a triagem' in clientes["Administrador"].get("/literatura").text


def test_partes_que_nao_oferecem_acao_continuam_iguais(clientes, painel):  # noqa: F811
    """Quem nao entrou nao ve o arquivo do banco na faixa nem as execucoes na Visao Geral (as duas pela mesma regra)."""
    _, _, copia, _ = painel
    h = clientes["Visitante"].get("/").text
    assert '<span class="banner-detalhe"></span>' in h and copia.name not in h and "Execuções e chamadas" not in h


# ---------------- desfazer ----------------
def _decidir(cli, achado_id):
    h = cli.get(f"/achados/{achado_id}").text
    csrf = re.search(r'name="csrf" value="([^"]+)"', h).group(1)
    status = re.search(r'name="status_final" value="([^"]+)"', h)
    r = cli.post(f"/achados/{achado_id}/verificar", data={"status_final": status.group(1) if status else "em_uso", "csrf": csrf},
                 follow_redirects=False)
    assert r.status_code == 303 and f"ok={achado_id}" in r.headers["location"]
    return r


def test_desfazer_do_aviso_so_para_o_autor_ou_o_administrador(painel, clientes):  # noqa: F811
    _criar(painel, "bia", "Revisor", nome="Bia")
    bia = TestClient(clientes["Visitante"].app)
    assert _entrar(bia, "bia").status_code == 303
    _decidir(clientes["Revisor"], 1)
    assert 'action="/achados/1/desfazer' in clientes["Revisor"].get("/achados/2?ok=1").text        # autor
    assert 'action="/achados/1/desfazer' not in bia.get("/achados/2?ok=1").text                    # outro revisor
    assert 'action="/achados/1/desfazer' in clientes["Administrador"].get("/achados/2?ok=1").text
    assert 'action="/achados/1/desfazer' not in clientes["Leitor"].get("/achados/2?ok=1").text
    assert 'action="/achados/3/desfazer' not in clientes["Revisor"].get("/achados/2?ok=3").text     # nada a desfazer em 3


def test_botao_e_rota_de_desfazer_usam_a_mesma_funcao(clientes, monkeypatch):
    rev = clientes["Revisor"]
    _decidir(rev, 1)
    monkeypatch.setattr(A, "pode_desfazer_decisao", lambda grupo, nome, autor: False)
    assert 'action="/achados/1/desfazer' not in rev.get("/achados/1").text
    assert 'action="/achados/1/desfazer' not in rev.get("/achados/2?ok=1").text
    csrf = re.search(r'name="csrf" value="([^"]+)"', rev.get("/achados/1").text).group(1)
    r = rev.post("/achados/1/desfazer", data={"csrf": csrf}, follow_redirects=False)
    assert r.status_code == 403 and "Só quem tomou a decisão ou um administrador pode desfazê-la." in r.text


# ---------------- somente leitura (painel local, sem login: nenhuma escrita e aceita) ----------------
@pytest.fixture
def somente_leitura(demo, tmp_path):  # noqa: F811
    banco_demo, raw = demo
    copia = tmp_path / "demo.db"
    shutil.copy(banco_demo, copia)
    ctx = Contexto(banco="real", nome_banco=copia.name, somente_leitura=True, pasta_backup=tmp_path / "backups",
                   ufs=dict(C.UFS), status_permitidos=set(V.STATUS) | set(V.STATUS_FINAL_EXTRA),
                   status_definicoes=dict(V.STATUS), hosts_permitidos=("testserver",), autenticacao=False)
    return TestClient(criar_app(LeituraPainelSQLite(copia), lambda: RepositorioSQLite(copia), BrutoLocal(raw), ctx))


def test_somente_leitura_nao_oferece_filas_nem_continuar(somente_leitura):
    h = somente_leitura.get("/").text
    assert "/revisao/achados" not in _menu(h) and "/literatura/triagem" not in _menu(h) and "/execucoes" in _menu(h)
    assert "Continuar a revisão" not in h and ">Começar revisão<" not in h and "Achados aguardando verificação humana" in h
    assert "Continuar a triagem" not in somente_leitura.get("/literatura").text


# ---------------- banco vies ----------------
@pytest.fixture
def vies(banco, tmp_path):  # noqa: F811
    ctx = dataclasses.replace(_contexto("vies", False, tmp_path), autenticacao=True, hosts_permitidos=("testserver",))
    contas_db = tmp_path / "contas_vies.db"
    contas = ContasSQLite(contas_db)
    gravar_politica(contas, "vies")
    app = criar_app(LeituraPainelSQLite(banco), lambda: RepositorioSQLite(banco), BrutoLocal(tmp_path), ctx, contas=contas)
    saida = {"Visitante": TestClient(app)}
    for grupo in GRUPOS[1:]:
        _usuario(contas, contas_db, grupo.lower(), grupo)
        c = TestClient(app)
        assert _entrar(c, grupo.lower()).status_code == 303
        saida[grupo] = c
    return saida


def test_sortear_a_amostra_so_para_quem_o_servidor_aceita(vies):
    for grupo, cli in vies.items():
        if grupo == "Visitante":                                 # a validacao fecha para quem nao entrou (D145)
            assert cli.get("/validacao", follow_redirects=False).status_code == 303
            continue
        h = cli.get("/validacao").text
        pode = _pode(grupo, "POST", "/validacao/sortear")
        assert ('action="/validacao/sortear"' in h) is pode, grupo
        assert ("Só quem administra o painel sorteia a amostra." in h) is (not pode), grupo


def test_sortear_sem_login_e_em_somente_leitura(banco, tmp_path):  # noqa: F811
    assert 'action="/validacao/sortear"' in _cli_sem_login(banco, tmp_path).get("/validacao").text      # sem login: tudo vale
    h = _cli_sem_login(banco, tmp_path, somente_leitura=True).get("/validacao").text
    assert 'action="/validacao/sortear"' not in h and "Painel em modo somente leitura." in h


def test_continuar_e_alerta_da_triagem_no_vies(vies, monkeypatch):
    monkeypatch.setattr(LeituraPainelSQLite, "contagem_triagem",
                        lambda self: {"total": 5, "incluidos": 1, "excluidos": 1, "pendentes": 3, "ocultos_llm": 0})
    for grupo, cli in vies.items():
        h = cli.get("/").text
        decide = _pode(grupo, *DECIDE_ARTIGO)
        assert ('href="/literatura/triagem">Continuar a triagem (3)' in h) is decide, grupo
        assert ("Artigos aguardando triagem humana" in h) is decide, grupo
        assert "ainda sem triagem humana." not in h, grupo
    assert 'href="/literatura/triagem">Continuar a triagem (3)' in vies["Revisor"].get("/").text


@pytest.mark.parametrize("grupo", GRUPOS)
def test_menu_e_triagem_no_vies(vies, grupo):
    cli = vies[grupo]
    h = cli.get("/").text
    assert [x for x in _menu(h) if not _aceito(cli.get(x, follow_redirects=False))] == []
    assert ("/literatura/triagem" in _menu(h)) is _pode(grupo, *DECIDE_ARTIGO)


def test_visao_geral_do_vies_com_e_sem_regra(banco, tmp_path, monkeypatch):  # noqa: F811
    """Com a regra das rotas negando o POST da decisao, so o botao da fila some; nenhum numero muda."""
    from painel import visao_geral as VG
    monkeypatch.setattr(LeituraPainelSQLite, "contagem_triagem",
                        lambda self: {"total": 5, "incluidos": 1, "excluidos": 1, "pendentes": 3, "ocultos_llm": 0})
    ctx = _contexto("vies", False, tmp_path)
    with LeituraPainelSQLite(banco).instantaneo() as l:
        dados = VG.ler_dados(l, ctx)
    quem = {"logado": True, "grupo": "Administrador", "permissoes": frozenset()}
    sem = VG.montar(dados, quem)
    nega = VG.montar(dados, {**quem, "pode_rota": lambda m, c: m == "GET"})
    fila = lambda s: next(b for x in s for b in x["blocos"] if b["id"] == "fila")
    assert fila(sem)["acoes"] == [{"texto": "Continuar a triagem (3)", "href": "/literatura/triagem"}] and fila(nega)["acoes"] == []
    assert [[(b["id"], b["indicadores"]) for b in x["blocos"]] for x in sem] == [[(b["id"], b["indicadores"]) for b in x["blocos"]]
                                                                              for x in nega]

# ---------------- destino da fila e rota de desfazer tambem contam (decisoes da pre-revisao) ----------------
def test_botoes_exigem_tambem_abrir_o_destino(clientes, monkeypatch):
    original = A.pode_acessar
    negados = {("GET", "/revisao/achados"), ("GET", "/literatura/triagem")}
    monkeypatch.setattr(A, "pode_acessar", lambda g, p, m, c: False if (m, c) in negados else original(g, p, m, c))
    adm = clientes["Administrador"]
    h = adm.get("/").text
    assert "Continuar a revisão" not in h and ">Começar revisão<" not in h and "/revisao/achados" not in _menu(h)
    assert "Continuar a triagem" not in adm.get("/literatura").text


def test_desfazer_exige_tambem_a_rota_de_desfazer(clientes, monkeypatch):
    rev = clientes["Revisor"]
    _decidir(rev, 1)
    original = A.pode_acessar
    monkeypatch.setattr(A, "pode_acessar", lambda g, p, m, c: False if (m, c) == ("POST", "/achados/1/desfazer")
                        else original(g, p, m, c))
    assert 'action="/achados/1/desfazer' not in rev.get("/achados/1").text
    assert 'action="/achados/1/desfazer' not in rev.get("/achados/2?ok=1").text


def test_fila_escondida_deixa_nenhum_item_atual():
    g = navegacao.grupos("/achados/5", em_fila=True, banco="real", pode=lambda m, c: m == "GET")
    assert not any(i["atual"] for x in g for i in x["itens"]) and "/revisao/achados" not in _hrefs(g)


def test_aviso_do_proprio_achado_nao_repete_leituras(clientes, monkeypatch):
    """Uma regra so para os dois botoes de desfazer: quando o aviso e do proprio achado, o historico e a decisao a desfazer sao
    lidos uma vez."""
    rev = clientes["Revisor"]
    _decidir(rev, 1)
    contagem = {"historico_achado": 0, "tem_decisao_para_desfazer": 0}
    for nome in contagem:
        original = getattr(LeituraPainelSQLite, nome)

        def contar(self, *a, _n=nome, _o=original, **k):
            contagem[_n] += 1
            return _o(self, *a, **k)
        monkeypatch.setattr(LeituraPainelSQLite, nome, contar)
    h = rev.get("/achados/1?ok=1").text
    assert 'action="/achados/1/desfazer' in h
    assert contagem == {"historico_achado": 1, "tem_decisao_para_desfazer": 1}
    contagem.update(historico_achado=0, tem_decisao_para_desfazer=0)
    rev.get("/achados/2?ok=1")
    assert contagem == {"historico_achado": 2, "tem_decisao_para_desfazer": 2}      # dois achados: uma leitura de cada
