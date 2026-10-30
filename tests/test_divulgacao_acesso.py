"""Politica de divulgacao aplicada no servidor (D145): para quem nao entrou, a pesquisa nao divulgada leva toda pagina a
entrada; a divulgada abre so as paginas publicas (lista fechada); quem entrou nao e afetado; o menu e os links seguem a
mesma regra; banco de contas ocupado, politica invalida ou preliminares gravados nunca abrem nada."""
import re
import shutil

import pytest
from fastapi.testclient import TestClient

from adaptadores.bruto_local import BrutoLocal
from adaptadores.contas_sqlite import ContasSQLite
from adaptadores.leitura_sqlite import LeituraPainelSQLite
from adaptadores.repositorio_sqlite import RepositorioSQLite
from apoio_divulgacao import gravar_politica
from config import consultas as C, vocabulario as V
from dominio import autenticacao as A
from painel.app import Contexto, criar_app
from test_autenticacao import _criar, _entrar
from test_painel import demo  # noqa: F401
from test_validacao_vies import banco  # noqa: F401

PUBLICAS = ["/", "/sobre", "/literatura/prisma", "/metodologia"]


def _painel(demo, tmp_path, autenticacao=True, banco="real"):  # noqa: F811
    db, raw = demo
    tmp_path.mkdir(parents=True, exist_ok=True)
    copia = tmp_path / "demo.db"
    shutil.copy(db, copia)
    ctx = Contexto(banco=banco, nome_banco=copia.name, somente_leitura=False, pasta_backup=tmp_path / "b", ufs=dict(C.UFS),
                   status_permitidos=set(V.STATUS) | set(V.STATUS_FINAL_EXTRA), status_definicoes=dict(V.STATUS),
                   hosts_permitidos=("testserver",), autenticacao=autenticacao)
    contas = ContasSQLite(tmp_path / "contas.db") if autenticacao else None
    if contas is not None:
        contas.garantir_padrao()
    app = criar_app(LeituraPainelSQLite(copia), lambda: RepositorioSQLite(copia), BrutoLocal(raw), ctx, contas=contas)
    return app, contas, tmp_path / "contas.db", copia


def _leitura_do_visitante():
    """Toda rota GET que o Visitante abriria pelas permissoes, com um exemplo concreto para cada parametro."""
    saida = []
    for m, padrao, perm in A.REGRAS_ROTAS:
        if m != "GET" or padrao in ("/entrar", "/api/coletas") or not A.pode("Visitante", {"ver_painel"}, perm):
            continue
        saida.append(re.sub(r"\{[^}]+\}", "1", padrao))
    return saida


def _vai_para_a_entrada(r):
    return r.status_code == 303 and r.headers["location"].startswith("/entrar")


# ======================== pesquisa nao divulgada (sem politica gravada) ========================
def test_rotas_de_leitura_do_visitante_cobrem_as_paginas_publicas():
    rotas = _leitura_do_visitante()
    assert set(PUBLICAS) <= set(rotas) and len(rotas) >= 20


@pytest.mark.parametrize("estado", ["ausente", "fechada", "invalida", "preliminares"])
@pytest.mark.parametrize("metodo", ["GET", "HEAD"])
def test_sem_divulgacao_tudo_vai_para_a_entrada(demo, tmp_path, estado, metodo):  # noqa: F811
    app, contas, _, _ = _painel(demo, tmp_path)
    if estado == "fechada":
        gravar_politica(contas, "real", publica=False)
    elif estado == "invalida":
        with contas._conexao(escrita=True) as conn:
            conn.execute("INSERT INTO configuracoes (chave, valor) VALUES ('divulgacao:real', '{\"publica\": 1}')")
    elif estado == "preliminares":
        gravar_politica(contas, "real", publica=True, preliminares=True)
    cli = TestClient(app)
    ruins = [c for c in _leitura_do_visitante() if not _vai_para_a_entrada(cli.request(metodo, c, follow_redirects=False))]
    assert ruins == []


def test_a_entrada_e_os_estaticos_continuam_abertos(demo, tmp_path):  # noqa: F811
    app, _, _, _ = _painel(demo, tmp_path)
    cli = TestClient(app)
    assert cli.get("/entrar").status_code == 200 and cli.get("/static/painel.css").status_code == 200


# ======================== pesquisa divulgada ========================
@pytest.mark.parametrize("metodo", ["GET", "HEAD"])
def test_divulgada_abre_so_as_paginas_publicas(demo, tmp_path, metodo):  # noqa: F811
    app, contas, _, _ = _painel(demo, tmp_path)
    gravar_politica(contas, "real")
    cli = TestClient(app)
    erros = []
    for c in _leitura_do_visitante():
        r = cli.request(metodo, c, follow_redirects=False)
        # HEAD numa pagina publica: 200 ou o 405 do roteador para rotas so GET (sem conteudo), nunca a entrada
        aberta = r.status_code == 200 or (metodo == "HEAD" and r.status_code == 405)
        if (c in PUBLICAS and not aberta) or (c not in PUBLICAS and not _vai_para_a_entrada(r)):
            erros.append((c, r.status_code))
    assert erros == []


def test_rota_desconhecida_vai_para_a_entrada(demo, tmp_path):  # noqa: F811
    app, contas, _, _ = _painel(demo, tmp_path)
    gravar_politica(contas, "real")
    for c in ("/nao-existe", "/sobre/", "/SOBRE"):           # pontos e barras duplas: o cliente normaliza; ver test_divulgacao
        assert _vai_para_a_entrada(TestClient(app).get(c, follow_redirects=False)), c


def test_a_politica_e_por_pesquisa(demo, tmp_path):  # noqa: F811
    app, contas, _, _ = _painel(demo, tmp_path / "vies", banco="vies")
    gravar_politica(contas, "real")                                       # so a outra pesquisa esta divulgada
    assert _vai_para_a_entrada(TestClient(app).get("/", follow_redirects=False))
    gravar_politica(contas, "vies")
    assert TestClient(app).get("/sobre").status_code == 200


def test_entrada_devolve_ao_destino_pedido(demo, tmp_path):  # noqa: F811
    app, contas, _, _ = _painel(demo, tmp_path)
    gravar_politica(contas, "real")
    r = TestClient(app).get("/estados?uf=PI", follow_redirects=False)
    assert r.headers.get("location") == "/entrar?proximo=%2Festados%3Fuf%3DPI"


# ======================== quem entrou nao e afetado ========================
@pytest.mark.parametrize("politica", [None, False, True])
def test_quem_entrou_mantem_o_acesso(demo, tmp_path, politica):  # noqa: F811
    app, contas, contas_db, _ = _painel(demo, tmp_path)
    if politica is not None:
        gravar_politica(contas, "real", publica=politica)
    painel = (TestClient(app), contas, None, contas_db)
    _criar(painel, "leo", "Leitor")
    cli = TestClient(app)
    assert _entrar(cli, "leo").status_code == 303
    for c in ("/", "/estados", "/achados", "/analises", "/literatura/artigos", "/literatura/referencias.xlsx"):
        assert cli.get(c, follow_redirects=False).status_code == 200, c


# ======================== menu e links ========================
def _menu(html):
    nav = html[html.index("<nav"):html.index("</nav>")]
    return sorted(set(re.findall(r'<a [^>]*href="([^"]+)"', nav)))


def test_menu_do_visitante_so_com_as_paginas_publicas(demo, tmp_path):  # noqa: F811
    app, contas, _, _ = _painel(demo, tmp_path)
    gravar_politica(contas, "real")
    h = TestClient(app).get("/").text
    assert _menu(h) == ["/", "/literatura/prisma", "/metodologia", "/sobre"]
    corpo = h[h.index('<main id="conteudo"'):]
    links = {re.sub(r"[?#].*", "", x) for x in re.findall(r'href="(/[^"]*)"', corpo)}
    assert links <= {"/", "/sobre", "/literatura/prisma", "/metodologia", "/entrar"}, links


def test_servidor_e_menu_usam_a_mesma_decisao(demo, tmp_path, monkeypatch):  # noqa: F811
    from dominio import divulgacao
    app, contas, _, _ = _painel(demo, tmp_path)
    gravar_politica(contas, "real")
    original = divulgacao.decisao_publico
    monkeypatch.setattr(divulgacao, "decisao_publico",
                        lambda m, c, p: "liberada" if c == "/estados" else original(m, c, p))
    cli = TestClient(app)
    assert cli.get("/estados", follow_redirects=False).status_code == 200
    assert "/estados" in _menu(cli.get("/").text)


# ======================== falhas fecham ========================
def test_banco_de_contas_ocupado_ao_ler_a_politica(demo, tmp_path, monkeypatch):  # noqa: F811
    app, contas, _, _ = _painel(demo, tmp_path)
    gravar_politica(contas, "real")

    def ocupado(*a, **k):
        raise A.ContasOcupadas()
    monkeypatch.setattr(contas, "politica_divulgacao", ocupado)
    r = TestClient(app).get("/sobre", follow_redirects=False)
    assert r.status_code == 503 and "Sobre os dados" not in r.text


def test_sem_login_no_painel_local_nada_muda(demo, tmp_path):  # noqa: F811
    app, _, _, _ = _painel(demo, tmp_path, autenticacao=False)
    cli = TestClient(app)
    for c in ("/", "/estados", "/achados", "/analises", "/literatura/referencias.xlsx"):
        assert cli.get(c, follow_redirects=False).status_code == 200, c


def test_nada_e_gravado_nos_bancos(demo, tmp_path):  # noqa: F811
    import sqlite3
    app, contas, contas_db, copia = _painel(demo, tmp_path)
    antes = sqlite3.connect(copia).execute("SELECT COUNT(*), MAX(rowid) FROM achados").fetchone()
    cli = TestClient(app)
    for c in _leitura_do_visitante():
        cli.get(c, follow_redirects=False)
    assert contas.politica_divulgacao("real") == ({"publica": False, "preliminares": False}, "ausente")
    assert sqlite3.connect(copia).execute("SELECT COUNT(*), MAX(rowid) FROM achados").fetchone() == antes


# ======================== pre-revisao: entrada, envio, quem entrou, falhas ========================
LINK_PUBLICO = '<a class="botao secundario" href="/">Ver os dados sem entrar</a>'


@pytest.mark.parametrize("publica,mostra", [(None, False), (False, False), (True, True)])
def test_entrada_so_oferece_o_link_publico_com_a_pesquisa_divulgada(demo, tmp_path, publica, mostra):  # noqa: F811
    app, contas, _, _ = _painel(demo, tmp_path)
    if publica is not None:
        gravar_politica(contas, "real", publica=publica)
    assert (LINK_PUBLICO in TestClient(app).get("/entrar").text) is mostra


def test_entrada_continua_se_a_politica_falhar(demo, tmp_path, monkeypatch):  # noqa: F811
    app, contas, _, _ = _painel(demo, tmp_path)
    gravar_politica(contas, "real")

    def quebrada(*a, **k):
        raise RuntimeError("leitura quebrada")
    monkeypatch.setattr(contas, "politica_divulgacao", quebrada)
    cli = TestClient(app, raise_server_exceptions=False)
    h = cli.get("/entrar")
    assert h.status_code == 200 and LINK_PUBLICO not in h.text                # a entrada nunca depende da politica
    r = cli.get("/sobre", follow_redirects=False)
    assert r.status_code == 500 and "Sobre os dados" not in r.text            # pagina de pesquisa: erro sem conteudo


def test_quem_entrou_nao_le_a_politica(demo, tmp_path, monkeypatch):  # noqa: F811
    app, contas, contas_db, _ = _painel(demo, tmp_path)
    painel = (TestClient(app), contas, None, contas_db)
    _criar(painel, "leo", "Leitor")
    cli = TestClient(app)
    assert _entrar(cli, "leo").status_code == 303

    def quebrada(*a, **k):
        raise RuntimeError("nao deveria ser lida")
    monkeypatch.setattr(contas, "politica_divulgacao", quebrada)
    for c in ("/", "/estados", "/sobre"):
        assert cli.get(c, follow_redirects=False).status_code == 200, c


def test_sair_e_envio_de_coletas_nao_dependem_da_politica(demo, tmp_path):  # noqa: F811
    import dataclasses
    db, raw = demo
    app, contas, _, copia = _painel(demo, tmp_path)
    r = TestClient(app).post("/sair", follow_redirects=False)
    assert not (r.status_code == 303 and "proximo=" in r.headers.get("location", ""))  # nunca o desvio da politica
    ctx = Contexto(banco="real", nome_banco=copia.name, somente_leitura=False, pasta_backup=tmp_path / "b2", ufs=dict(C.UFS),
                   status_permitidos=set(V.STATUS), status_definicoes=dict(V.STATUS), hosts_permitidos=("testserver",),
                   autenticacao=True, aceita_envios=True)
    app2 = criar_app(LeituraPainelSQLite(copia), lambda: RepositorioSQLite(copia), BrutoLocal(raw), ctx, contas=contas)
    r = TestClient(app2).get("/api/coletas", follow_redirects=False)
    assert r.status_code != 303 and "/entrar" not in r.headers.get("location", "")


@pytest.mark.parametrize("publica", [None, True])
def test_nada_e_gravado_nos_bancos_em_cada_estado(demo, tmp_path, publica):  # noqa: F811
    import sqlite3
    app, contas, contas_db, copia = _painel(demo, tmp_path)
    if publica:
        gravar_politica(contas, "real")
    conf = lambda: sqlite3.connect(contas_db).execute("SELECT chave, valor FROM configuracoes ORDER BY chave").fetchall()
    antes_conf = conf()
    antes = sqlite3.connect(copia).execute("SELECT COUNT(*), MAX(rowid) FROM achados").fetchone()
    cli = TestClient(app)
    for c in _leitura_do_visitante():
        cli.get(c, follow_redirects=False)
    assert conf() == antes_conf
    assert sqlite3.connect(copia).execute("SELECT COUNT(*), MAX(rowid) FROM achados").fetchone() == antes


def test_menu_e_links_do_visitante_no_banco_vies(banco, tmp_path):  # noqa: F811
    import dataclasses
    from test_validacao_vies import _contexto
    ctx = dataclasses.replace(_contexto("vies", False, tmp_path), autenticacao=True, hosts_permitidos=("testserver",))
    contas = ContasSQLite(tmp_path / "contas_vies.db")
    gravar_politica(contas, "vies")
    app = criar_app(LeituraPainelSQLite(banco), lambda: RepositorioSQLite(banco), BrutoLocal(tmp_path), ctx, contas=contas)
    h = TestClient(app).get("/").text
    assert _menu(h) == ["/", "/literatura/prisma", "/metodologia", "/sobre"]
    corpo = h[h.index('<main id="conteudo"'):]
    links = {re.sub(r"[?#].*", "", x) for x in re.findall(r'href="(/[^"]*)"', corpo)}
    assert links <= {"/", "/sobre", "/literatura/prisma", "/metodologia", "/entrar"}, links


# ======================== a visao geral publica sem numeros que dependem do modelo ========================
def _bloco(h, bid):
    i = h.index(f'id="vg-bloco-{bid}"')
    return h[i:h.index("</section>", i)]


def test_visao_geral_publica_sem_denominador_do_modelo_no_banco_real(demo, tmp_path):  # noqa: F811
    """O total de achados vem do modelo: quem nao entrou ve quantos foram verificados, sem o "de N" e sem a barra (D145, D146)."""
    import sqlite3
    app, contas, contas_db, copia = _painel(demo, tmp_path)
    gravar_politica(contas, "real")
    total = sqlite3.connect(copia).execute("SELECT COUNT(*) FROM v_achados_revisao").fetchone()[0]
    h = TestClient(app).get("/").text
    b = _bloco(h, "decisoes_humanas")
    assert re.search(r'<div class="kpi" id="vg-ind-verificados"><span class="kpi-valor">\d+</span>', b)
    assert f"de {total}</small>" not in b and "pendentes" not in b and "<svg" not in b
    p = _bloco(h, "prontidao")      # cartoes compactos: so as contagens humanas; o universo dos negativos do modelo nunca aparece
    assert 'id="pr-h2-c"' in p and 'id="pr-h5-c"' in p and 'id="pr-auditoria-c"' in p and "do universo de" not in h
    painel = (TestClient(app), contas, None, contas_db)
    _criar(painel, "leo", "Leitor")
    leitor = TestClient(app)
    assert _entrar(leitor, "leo").status_code == 303
    b = _bloco(leitor.get("/").text, "decisoes_humanas")                       # quem entrou: como antes
    assert re.search(rf'id="vg-ind-verificados"><span class="kpi-valor">\d+ <small>de {total}</small>', b) and "pendentes" in b
    p = _bloco(leitor.get("/").text, "prontidao")
    assert 'id="pr-h2-c"' in p and 'id="pr-h5-c"' in p and 'id="pr-auditoria-c"' in p


def test_visao_geral_publica_sem_denominador_do_modelo_no_banco_vies(banco, tmp_path):  # noqa: F811
    """No vies, o total da triagem humana exclui os artigos que o modelo ocultou: quem nao entrou ve so as contagens humanas."""
    import dataclasses
    from test_validacao_vies import _contexto
    ctx = dataclasses.replace(_contexto("vies", False, tmp_path), autenticacao=True, hosts_permitidos=("testserver",))
    contas = ContasSQLite(tmp_path / "contas_vies.db")
    gravar_politica(contas, "vies")
    app = criar_app(LeituraPainelSQLite(banco), lambda: RepositorioSQLite(banco), BrutoLocal(tmp_path), ctx, contas=contas)
    b = _bloco(TestClient(app).get("/").text, "decisoes_humanas")
    assert re.search(r'<div class="kpi" id="vg-ind-com_triagem_humana"><span class="kpi-valor">\d+</span>', b)
    assert "pendentes" not in b and "<svg" not in b
    painel = (TestClient(app), contas, None, tmp_path / "contas_vies.db")
    _criar(painel, "leo", "Leitor")
    leitor = TestClient(app)
    assert _entrar(leitor, "leo").status_code == 303
    b = _bloco(leitor.get("/").text, "decisoes_humanas")                       # quem entrou: como antes
    assert re.search(r'id="vg-ind-com_triagem_humana"><span class="kpi-valor">\d+ <small>de \d+</small>', b) and "pendentes" in b


@pytest.mark.parametrize("metodo,caminho", [("GET", "/entrar"), ("POST", "/sair"), ("GET", "/static/painel.css"),
                                            ("GET", "/api/coletas"), ("POST", "/api/coletas")])
def test_caminhos_de_infraestrutura_nunca_leem_a_politica(demo, tmp_path, monkeypatch, metodo, caminho):  # noqa: F811
    app, contas, _, copia = _painel(demo, tmp_path)
    if caminho == "/api/coletas":                    # a rota de envio so e isenta no painel que aceita envios (D98)
        ctx = Contexto(banco="real", nome_banco=copia.name, somente_leitura=False, pasta_backup=tmp_path / "b2", ufs=dict(C.UFS),
                       status_permitidos=set(V.STATUS), status_definicoes=dict(V.STATUS), hosts_permitidos=("testserver",),
                       autenticacao=True, aceita_envios=True)
        app = criar_app(LeituraPainelSQLite(copia), lambda: RepositorioSQLite(copia), BrutoLocal(demo[1]), ctx, contas=contas)
    lidas = []

    def espia(*a, **k):
        lidas.append(a)
        raise RuntimeError("nao deveria ser lida")
    monkeypatch.setattr(contas, "politica_divulgacao", espia)
    r = TestClient(app, raise_server_exceptions=False).request(metodo, caminho, follow_redirects=False)
    assert r.status_code < 500 and not (r.status_code == 303 and "proximo=" in r.headers.get("location", ""))
    if caminho != "/entrar":                         # a pagina de entrada le a politica so para o link publico (item 6)
        assert lidas == [], caminho
