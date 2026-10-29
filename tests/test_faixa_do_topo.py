"""Faixa do topo: o nome da pesquisa aparece para todos; o arquivo do banco, "somente leitura" e a dica `--banco vies` so para
quem entrou com ver_chamadas (com o login desligado, como antes). Demonstracao, simulacao e paginas de erro seguem a mesma regra.
Os dois nomes e a regra sao um so lugar cada um, usados tambem pela Visao Geral."""
import re
import shutil

import pytest
from fastapi.testclient import TestClient

from adaptadores.bruto_local import BrutoLocal
from adaptadores.contas_sqlite import ContasSQLite
from adaptadores.leitura_sqlite import LeituraPainelSQLite
from adaptadores.repositorio_sqlite import RepositorioSQLite
from config import consultas as C, vocabulario as V
from dominio import autenticacao as A
from painel import rotulos
from painel.app import Contexto, criar_app
from test_autenticacao import _entrar, _usuario
from test_painel import demo  # noqa: F401
from test_validacao_vies import _cli as _cli_vies, banco  # noqa: F401
from test_visao_geral_montador import ADMIN, LEITOR, VG, _bloco, _real, _vies

NOMES = {"real": "Secretarias Estaduais de Segurança Pública",
         "vies": "Viés Algorítmico e Inteligência Artificial na Segurança Pública"}
DICA_VIES = " · comandos: acrescente --banco vies"


# ---------------- painel de teste ----------------
def _painel(demo, tmp_path, banco="real", somente_leitura=False, autenticacao=True, sem_banco=False):  # noqa: F811
    db, raw = demo
    tmp_path.mkdir(parents=True, exist_ok=True)
    copia = tmp_path / "demo.db"
    if not copia.exists():
        shutil.copy(db, copia)
    ctx = Contexto(banco=banco, nome_banco=copia.name, somente_leitura=somente_leitura, pasta_backup=tmp_path / "backups",
                   ufs=dict(C.UFS), status_permitidos=set(V.STATUS) | set(V.STATUS_FINAL_EXTRA),
                   status_definicoes=dict(V.STATUS), hosts_permitidos=("testserver",), autenticacao=autenticacao)
    contas = ContasSQLite(tmp_path / "contas.db") if autenticacao else None
    leitura = LeituraPainelSQLite(tmp_path / "nao-existe.db" if sem_banco else copia)
    app = criar_app(leitura, lambda: RepositorioSQLite(copia), BrutoLocal(raw), ctx, contas=contas)
    return app, contas, tmp_path / "contas.db"


def _grupo_id(contas, nome):
    return next(g["grupo_id"] for g in contas.grupos() if g["nome"] == nome)


# quem ve -> (grupo da conta ou None para quem nao entrou, permissao ver_chamadas acrescentada ao grupo, ve os detalhes)
QUEM = {
    "anonimo": (None, False, False),
    "anonimo_visitante_com_chamadas": (None, True, False),
    "leitor": ("Leitor", False, False),
    "leitor_com_chamadas": ("Leitor", True, True),
    "revisor": ("Revisor", False, True),
    "administrador": ("Administrador", False, True),
}


def _cliente(app, contas, contas_db, quem):
    grupo, acrescenta, _ = QUEM[quem]
    alvo = grupo or A.GRUPO_VISITANTE
    if acrescenta:
        contas.definir_permissoes(_grupo_id(contas, alvo), set(A.GRUPOS_PADRAO[alvo]) | {"ver_chamadas"})
    cli = TestClient(app)
    if grupo:
        _usuario(contas, contas_db, quem, grupo)
        assert _entrar(cli, quem).status_code == 303
    return cli


def _faixa(html):
    return html[html.index('<header class="banner'):html.index("</header>")]


def _forte(html):
    return re.search(r"<strong>(.*?)</strong>", _faixa(html)).group(1)


def _detalhe(html):
    return re.search(r'<span class="banner-detalhe">(.*?)</span>', _faixa(html)).group(1)


def _detalhe_completo(banco, somente_leitura):
    return "demo.db" + (" · somente leitura" if somente_leitura else "") + (DICA_VIES if banco == "vies" else "")


def _sem_detalhe(html):
    f = _faixa(html)
    assert _detalhe(html) == ""
    assert "demo.db" not in f and "somente leitura" not in f and "--banco vies" not in f


# ---------------- os nomes e a regra ----------------
def test_nomes_da_pesquisa_num_so_lugar():
    assert rotulos.NOMES_PESQUISA == NOMES


@pytest.mark.parametrize("logado,grupo,permissoes,esperado", [
    (False, "Administrador", set(), False),                       # sem sessao nunca, nem para o grupo administrador
    (True, "Administrador", set(), True),
    (True, "Leitor", {"ver_painel"}, False),
    (True, "Leitor", {"ver_painel", "ver_chamadas"}, True),        # a permissao decide, nao o nome do grupo
    (False, "Visitante", {"ver_painel", "ver_chamadas"}, False),
    (True, "Revisor", set(A.GRUPOS_PADRAO["Revisor"]), True),
    (True, "Leitor", frozenset({"ver_chamadas"}), True),
    (True, "Leitor", ["ver_chamadas"], True),
    (True, "Leitor", [], False),
    (True, "Leitor", None, False),
])
def test_ve_detalhes_tecnicos(logado, grupo, permissoes, esperado):
    assert A.ve_detalhes_tecnicos(logado, grupo, permissoes) is esperado


def test_ve_detalhes_tecnicos_segue_a_regra_de_permissao(monkeypatch):
    vistos = []
    monkeypatch.setattr(A, "pode", lambda g, p, exigida: vistos.append(exigida) or exigida != "ver_chamadas")
    assert A.ve_detalhes_tecnicos(True, "Administrador", set()) is False
    assert vistos == ["ver_chamadas"]


# ---------------- faixa por quem ve ----------------
@pytest.mark.parametrize("quem", list(QUEM))
@pytest.mark.parametrize("somente_leitura", [False, True])
@pytest.mark.parametrize("nome_banco", ["real", "vies"])
def test_faixa_por_quem_ve(demo, tmp_path, nome_banco, somente_leitura, quem):  # noqa: F811
    app, contas, contas_db = _painel(demo, tmp_path, nome_banco)
    cli = _cliente(app, contas, contas_db, quem)
    if somente_leitura:     # o modo somente leitura recusa a entrada; a sessao vem do mesmo banco de contas
        cli = TestClient(_painel(demo, tmp_path, nome_banco, somente_leitura=True)[0], cookies=cli.cookies)
    h = cli.get("/sobre").text
    assert f'<header class="banner banner-{nome_banco}" role="banner">' in h
    assert _forte(h) == NOMES[nome_banco]
    if QUEM[quem][2]:
        assert _detalhe(h) == _detalhe_completo(nome_banco, somente_leitura)
    else:
        _sem_detalhe(h)


@pytest.mark.parametrize("quem", ["anonimo", "leitor", "revisor", "administrador"])
def test_visao_geral_tem_o_mesmo_nome_da_faixa(demo, tmp_path, quem):  # noqa: F811
    app, contas, contas_db = _painel(demo, tmp_path)
    h = _cliente(app, contas, contas_db, quem).get("/").text
    assert _forte(h) == NOMES["real"] and h.count(NOMES["real"]) >= 2      # faixa e titulo da identificacao
    if QUEM[quem][2]:
        assert _detalhe(h) == "demo.db"
    else:
        _sem_detalhe(h)


@pytest.mark.parametrize("caminho", ["/", "/sobre"])
def test_sem_login_a_faixa_continua_completa(demo, tmp_path, caminho):  # noqa: F811
    app, _, _ = _painel(demo, tmp_path, autenticacao=False)
    h = TestClient(app).get(caminho).text
    assert _forte(h) == NOMES["real"] and _detalhe(h) == "demo.db"


@pytest.mark.parametrize("nome_banco,rotulo", [("demo", "DEMONSTRAÇÃO (dados fictícios)"), ("simulado", "SIMULADO")])
def test_demonstracao_e_simulacao_mantem_o_rotulo(demo, tmp_path, nome_banco, rotulo):  # noqa: F811
    app, _, _ = _painel(demo, tmp_path / "local", nome_banco, autenticacao=False)
    h = TestClient(app).get("/sobre").text
    assert f'<header class="banner banner-{nome_banco}" role="banner">' in h
    assert _forte(h) == rotulo and _detalhe(h) == "demo.db"
    app, contas, contas_db = _painel(demo, tmp_path / "login", nome_banco)
    h = _cliente(app, contas, contas_db, "anonimo").get("/sobre").text
    assert _forte(h) == rotulo
    _sem_detalhe(h)
    h = _cliente(app, contas, contas_db, "administrador").get("/sobre").text
    assert _forte(h) == rotulo and _detalhe(h) == "demo.db"


# ---------------- paginas de erro ----------------
@pytest.mark.parametrize("quem,caminho,status", [
    ("anonimo", "/nao-existe", 404),
    ("administrador", "/nao-existe", 404),
    ("leitor", "/chamadas", 403),
    ("revisor", "/admin/usuarios", 403),
])
def test_paginas_de_erro_seguem_a_regra(demo, tmp_path, quem, caminho, status):  # noqa: F811
    app, contas, contas_db = _painel(demo, tmp_path)
    r = _cliente(app, contas, contas_db, quem).get(caminho, follow_redirects=False)
    assert r.status_code == status
    assert _forte(r.text) == NOMES["real"]
    if QUEM[quem][2]:
        assert _detalhe(r.text) == "demo.db"
    else:
        _sem_detalhe(r.text)


@pytest.mark.parametrize("quem", ["anonimo", "administrador"])
def test_banco_de_contas_ocupado_nao_mostra_detalhes(demo, tmp_path, monkeypatch, quem):  # noqa: F811
    app, contas, contas_db = _painel(demo, tmp_path)
    cli = _cliente(app, contas, contas_db, quem)

    def ocupado(*a, **k):
        raise A.ContasOcupadas()

    monkeypatch.setattr(contas, "usuario_da_sessao", ocupado)
    monkeypatch.setattr(contas, "permissoes_do_grupo", ocupado)
    r = cli.get("/sobre")
    assert r.status_code == 503 and _forte(r.text) == NOMES["real"]
    _sem_detalhe(r.text)


@pytest.mark.parametrize("autenticacao,quem,detalhe", [
    (False, None, "demo.db"),
    (True, "anonimo", ""),
    (True, "administrador", "demo.db"),
])
def test_painel_sem_banco_segue_a_regra(demo, tmp_path, autenticacao, quem, detalhe):  # noqa: F811
    app, contas, contas_db = _painel(demo, tmp_path, autenticacao=autenticacao, sem_banco=True)
    cli = _cliente(app, contas, contas_db, quem) if quem else TestClient(app)
    r = cli.get("/")
    assert r.status_code == 503 and _forte(r.text) == NOMES["real"] and _detalhe(r.text) == detalhe


@pytest.mark.parametrize("autenticacao,quem,detalhe", [
    (False, None, "demo.db"),             # login desligado vale antes do estado da requisicao
    (True, "anonimo", ""),
    (True, "administrador", ""),          # /static/ nao passa pelo controle de acesso: sem estado, nada aparece
])
def test_pagina_sem_estado_de_acesso_nao_mostra_detalhes(demo, tmp_path, autenticacao, quem, detalhe):  # noqa: F811
    app, contas, contas_db = _painel(demo, tmp_path, autenticacao=autenticacao)
    cli = _cliente(app, contas, contas_db, quem) if quem else TestClient(app)
    r = cli.get("/static/nao-existe.css")
    assert r.status_code == 404 and _detalhe(r.text) == detalhe


@pytest.mark.parametrize("campo", ["grupo", "permissoes"])
@pytest.mark.parametrize("caminho", ["/sobre", "/nao-existe"])
def test_grupo_ou_permissoes_nulos_nao_mostram_detalhes(demo, tmp_path, monkeypatch, campo, caminho):  # noqa: F811
    app, contas, contas_db = _painel(demo, tmp_path)
    adm = _cliente(app, contas, contas_db, "administrador")
    original = contas.usuario_da_sessao
    monkeypatch.setattr(contas, "usuario_da_sessao", lambda *a, **k: (lambda u: u and {**u, campo: None})(original(*a, **k)))
    _sem_detalhe(adm.get(caminho, follow_redirects=False).text)


# ---------------- reuso: a faixa e a Visao Geral seguem o mesmo lugar ----------------
def test_trocar_os_nomes_muda_a_faixa_e_a_visao_geral(demo, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(rotulos, "NOMES_PESQUISA", {"real": "Pesquisa R de teste", "vies": "Pesquisa V de teste"})
    assert _bloco(VG.montar(_real(), ADMIN), "identificacao")["titulo"] == "Pesquisa R de teste"
    assert _bloco(VG.montar(_vies(), ADMIN), "identificacao")["titulo"] == "Pesquisa V de teste"
    app, contas, contas_db = _painel(demo, tmp_path)
    h = _cliente(app, contas, contas_db, "anonimo").get("/").text
    assert _forte(h) == "Pesquisa R de teste" and h.count("Pesquisa R de teste") >= 2 and NOMES["real"] not in h
    app, contas, contas_db = _painel(demo, tmp_path / "vies", "vies")
    h = _cliente(app, contas, contas_db, "anonimo").get("/sobre").text
    assert _forte(h) == "Pesquisa V de teste" and NOMES["vies"] not in h


def test_titulo_da_identificacao_e_o_nome_da_pesquisa():
    assert _bloco(VG.montar(_real(), LEITOR), "identificacao")["titulo"] == NOMES["real"]
    assert _bloco(VG.montar(_vies(), LEITOR), "identificacao")["titulo"] == NOMES["vies"]


def _ids(secoes):
    return [b["id"] for s in secoes for b in s["blocos"]]


def test_trocar_a_regra_muda_a_faixa_e_a_visao_geral(demo, tmp_path, monkeypatch):  # noqa: F811
    app, contas, contas_db = _painel(demo, tmp_path)
    adm = _cliente(app, contas, contas_db, "administrador")
    leitor = _cliente(app, contas, contas_db, "leitor")
    monkeypatch.setattr(A, "ve_detalhes_tecnicos", lambda logado, grupo, permissoes: False)
    s = VG.montar(_real(), ADMIN)
    assert [c["comando"] for c in _bloco(s, "prontidao")["cartoes"]] == [None, None] and "execucoes" not in _ids(s)
    _sem_detalhe(adm.get("/sobre").text)
    _sem_detalhe(adm.get("/").text)
    monkeypatch.setattr(A, "ve_detalhes_tecnicos", lambda logado, grupo, permissoes: True)
    s = VG.montar(_real(), LEITOR)
    assert [c["comando"] for c in _bloco(s, "prontidao")["cartoes"]] == ["python main.py rotular", None]
    assert "execucoes" in _ids(s)
    assert _detalhe(leitor.get("/sobre").text) == "demo.db"


# ---------------- todas as paginas: o nome nao depende do que cada rota passa ao modelo ----------------
def _links_do_menu(html):
    nav = html[html.index("<nav"):html.index("</nav>")]
    return sorted(set(re.findall(r'<a [^>]*href="(/[^"#?]*)"', nav)))


def test_modelo_base_nao_le_o_modulo_de_rotulos():
    """Uma rota pode passar ao modelo uma variavel com o mesmo nome de um global (a validacao passa `rotulos`): a faixa usa
    so o que `pagina` entrega."""
    from pathlib import Path
    fonte = (Path(__file__).resolve().parents[1] / "painel" / "templates" / "base.html").read_text(encoding="utf-8")
    assert "rotulos" not in fonte and "BANCO REAL" not in fonte and "BANCO VIÉS" not in fonte


def test_nome_da_pesquisa_em_todas_as_paginas_do_menu_real(demo, tmp_path):  # noqa: F811
    app, _, _ = _painel(demo, tmp_path, autenticacao=False)
    cli = TestClient(app)
    links = _links_do_menu(cli.get("/").text)
    assert len(links) > 10
    for href in links:
        r = cli.get(href)
        assert r.status_code == 200 and _forte(r.text) == NOMES["real"] and _detalhe(r.text) == "demo.db", href


def test_nome_da_pesquisa_em_todas_as_paginas_do_menu_vies(banco, tmp_path):  # noqa: F811
    cli = _cli_vies(banco, tmp_path)
    links = _links_do_menu(cli.get("/").text)
    assert "/validacao" in links and len(links) > 10
    for href in links:
        r = cli.get(href)
        assert r.status_code == 200, href
        assert _forte(r.text) == NOMES["vies"] and _detalhe(r.text) == "busca.db" + DICA_VIES, href
