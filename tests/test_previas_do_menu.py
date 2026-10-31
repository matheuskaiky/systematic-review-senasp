"""Previas do menu: na pagina de revisao, o menu que o grupo teria com as alteracoes revisadas (um conjunto hipotetico,
nunca gravado); para o Visitante, uma previa por estado da divulgacao da pesquisa, pela mesma regra que decide o acesso de
quem nao entrou. A previa so mostra o menu: nao grava, nao cria sessao e nao troca de identidade."""
import re
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from apoio_divulgacao import gravar_politica
from dominio import autenticacao as A
from dominio import divulgacao as D
from painel import navegacao
from test_admin import _csrf, _gid, adm  # noqa: F401
from test_edicao_por_grupo import _erros, _form, _post, _revisar
from test_painel import demo  # noqa: F401

DADOS_REAIS = (Path(__file__).resolve().parents[1] / "data").resolve()
LEITOR = {"ver_painel", "ver_nomes_revisores", "ver_registros_revisao", "ver_custos"}
NOTA = ("<p>A prévia mostra só o menu. O acesso a cada página continua sendo decidido pelo servidor a cada "
        "pedido.</p>")
VAZIO = '<p class="vazio">Nenhum item no menu.</p>'
NAO_DIV = "pesquisa não divulgada"
DIV = "pesquisa divulgada, sem resultados preliminares"


@pytest.fixture(autouse=True)
def _nunca_abre_o_data_real(monkeypatch):
    """Todo teste deste arquivo falha se algo tentar abrir um arquivo SQLite dentro do data/ de verdade (contas reais)."""
    original = sqlite3.connect

    def conectar(caminho, *a, **k):
        alvo = Path(str(caminho)).resolve() if str(caminho) != ":memory:" else None
        if alvo is not None and (alvo == DADOS_REAIS or DADOS_REAIS in alvo.parents):
            raise AssertionError(f"teste tentou abrir {alvo}")
        return original(caminho, *a, **k)
    monkeypatch.setattr(sqlite3, "connect", conectar)


def _secoes(h):
    """[(rotulo, [(grupo, [itens])], vazio?)] de cada previa, na ordem da pagina."""
    saida = []
    for rotulo, corpo in re.findall(r'<section class="perm-previa" aria-label="([^"]+)">(.*?)</section>', h, re.S):
        assert f"<h2>{rotulo}</h2>" in corpo
        grupos = [(n, re.findall(r"<li>([^<]+)</li>", itens))
                  for n, itens in re.findall(r'<li class="previa-grupo"><span>([^<]+)</span><ul>(.*?)</ul></li>', corpo, re.S)]
        saida.append((rotulo, grupos, VAZIO in corpo))
        assert "<a " not in corpo and "<form" not in corpo and "<button" not in corpo and "<input" not in corpo
        if grupos:
            assert re.search(r'</h2>\s*<ul>\s*<li class="previa-grupo">', corpo) and VAZIO not in corpo
            assert re.search(r"</li>\s*</ul>\s*$", corpo)                      # a lista de fora fecha antes da secao
        else:
            assert re.search(r"</h2>\s*" + re.escape(VAZIO) + r"\s*$", corpo) and "<ul>" not in corpo
    return saida


def _esperado(nome, perms, politica=None, banco="real"):
    if politica is None:
        pode = lambda m, c: A.pode_acessar(nome, perms, m, c)        # noqa: E731
    else:
        pode = lambda m, c: (D.decisao_publico(m, c, politica) == "liberada"   # noqa: E731
                             and A.pode_acessar(nome, perms, m, c))
    return [(g["nome"], [i["texto"] for i in g["itens"]])
            for g in navegacao.grupos("/", admin=(nome == A.GRUPO_ADMIN), banco=banco, pode=pode)]


FECHADA = {"publica": False, "preliminares": False}
ABERTA = {"publica": True, "preliminares": False}


# ---------------- dominio ----------------

def test_estados_da_previa():
    assert D.ESTADOS_DA_PREVIA == ((NAO_DIV, FECHADA), (DIV, ABERTA))
    for _, pol in D.ESTADOS_DA_PREVIA:
        assert D.validar_nova(pol) == []


# ---------------- pagina do grupo (leitura) ----------------

def _pagina(cli, gid, **params):
    r = cli.get(f"/admin/grupos/{gid}", params=params)
    assert r.status_code == 200
    return r.text


@pytest.mark.parametrize("estado,marcado", [(None, NAO_DIV), (False, NAO_DIV), (True, DIV)])
def test_visitante_tem_uma_previa_por_estado(adm, estado, marcado):
    cli, contas, contas_db, _ = adm
    if estado is not None:
        gravar_politica(contas, "real", publica=estado)
    gid = _gid(contas_db, "Visitante")
    perms = next(g["permissoes"] for g in contas.grupos() if g["grupo_id"] == gid)
    secoes = _secoes(_pagina(cli, gid))
    rotulos = [f"Prévia do menu: {NAO_DIV}", f"Prévia do menu: {DIV}"]
    rotulos = [r + (" (estado atual)" if r.endswith(marcado) else "") for r in rotulos]
    assert [s[0] for s in secoes] == rotulos
    assert secoes[0][1] == _esperado("Visitante", perms, FECHADA) == []
    assert secoes[0][2] is True
    assert secoes[1][1] == _esperado("Visitante", perms, ABERTA) and secoes[1][1]
    assert secoes[1][2] is False


@pytest.mark.parametrize("valor", ["{", '{"publica": "sim", "preliminares": false}', '{"publica": true}',
                                   '{"publica": true, "preliminares": false, "extra": 1}',
                                   '{"publica": true, "preliminares": true}', '{"publica": true, "preliminares": "nao"}',
                                   "[]", "null"])
def test_configuracao_invalida_conta_como_nao_divulgada(adm, valor):
    cli, contas, contas_db, _ = adm
    contas.garantir_padrao()
    with contas._conexao(escrita=True) as conn:
        conn.execute("INSERT INTO configuracoes (chave, valor) VALUES (?, ?)", ("divulgacao:real", valor))
    rotulos = [s[0] for s in _secoes(_pagina(cli, _gid(contas_db, "Visitante")))]
    assert rotulos == [f"Prévia do menu: {NAO_DIV} (estado atual)", f"Prévia do menu: {DIV}"]


@pytest.mark.parametrize("grupo", ["Administrador", "Leitor", "Revisor"])
def test_outros_grupos_tem_uma_previa_so(adm, grupo):
    cli, contas, contas_db, _ = adm
    gravar_politica(contas, "real", publica=False)
    gid = _gid(contas_db, grupo)
    perms = next(g["permissoes"] for g in contas.grupos() if g["grupo_id"] == gid)
    h = _pagina(cli, gid)
    secoes = _secoes(h)
    assert [s[0] for s in secoes] == ["Prévia do menu"]
    assert secoes[0][1] == _esperado(grupo, perms)          # quem entrou nao depende da divulgacao


@pytest.mark.parametrize("grupo", ["Visitante", "Leitor", "Administrador"])
def test_nota_uma_vez_depois_das_previas(adm, grupo):
    cli, _, contas_db, _ = adm
    h = _pagina(cli, _gid(contas_db, grupo))
    assert h.count(NOTA) == 1
    assert h.rindex("</section>") < h.index(NOTA)


def test_grupo_sem_ver_painel_tem_menu_vazio_explicado(adm):
    cli, contas, contas_db, _ = adm
    gid = contas.criar_grupo("Nada", "2026-10-31T00:00:00+00:00")
    secoes = _secoes(_pagina(cli, gid))
    assert secoes == [("Prévia do menu", [], True)]


def _menu_real(h):
    """Textos dos itens do menu lateral que a pagina realmente entrega (sem a marca do topo)."""
    if "<nav" not in h:
        return []
    nav = h[h.index("<nav"):h.index("</nav>")]
    grupos = re.findall(r'<summary>([^<]+)</summary>\s*<ul class="menu-lista"[^>]*>(.*?)</ul>', nav, re.S)
    return [(n, re.findall(r"<a [^>]*>([^<]+)</a>", itens)) for n, itens in grupos]


@pytest.mark.parametrize("publica", [False, True])
def test_previa_do_visitante_e_o_menu_que_ele_recebe(adm, publica):
    """Em cada estado, a previa do Visitante e o menu que quem nao entrou recebe de fato, e cada item dela abre para ele."""
    cli, contas, contas_db, _ = adm
    gravar_politica(contas, "real", publica=publica)
    rotulo = f"Prévia do menu: {DIV if publica else NAO_DIV} (estado atual)"
    secoes = dict((s[0], s[1]) for s in _secoes(_pagina(cli, _gid(contas_db, "Visitante"))))
    assert rotulo in secoes
    previa = secoes[rotulo]
    anonimo = TestClient(cli.app)
    r = anonimo.get("/", follow_redirects=False)
    if publica:
        assert r.status_code == 200 and _menu_real(r.text) == previa
    else:
        assert r.status_code == 303 and urlsplit(r.headers["location"]).path == "/entrar"
        assert previa == [] and _menu_real(anonimo.get("/entrar").text) == []
    hrefs = [i["href"] for g in navegacao.grupos("/", banco="real",
                                                   pode=lambda m, c: True) for i in g["itens"]]
    textos = {i["texto"]: i["href"] for g in navegacao.grupos("/", banco="real", pode=lambda m, c: True) for i in g["itens"]}
    for _, itens in previa:
        for t in itens:
            assert textos[t] in hrefs
            assert anonimo.get(textos[t], follow_redirects=False).status_code == 200, t


def test_previa_do_visitante_segue_a_regra_de_divulgacao(adm, monkeypatch):
    cli, contas, contas_db, _ = adm
    gid = _gid(contas_db, "Visitante")
    perms = next(g["permissoes"] for g in contas.grupos() if g["grupo_id"] == gid)
    monkeypatch.setattr(D, "decisao_publico", lambda m, c, p: "liberada")
    secoes = _secoes(_pagina(cli, gid))
    assert len(secoes) == 2
    assert secoes[0][1] == secoes[1][1] == _esperado("Visitante", perms) and secoes[0][1]


def test_previa_do_visitante_le_a_politica_uma_vez(adm, monkeypatch):
    cli, contas, contas_db, _ = adm
    lidas = []
    original = type(contas).politica_divulgacao

    def contar(self, banco):
        lidas.append(banco)
        return original(self, banco)
    monkeypatch.setattr(type(contas), "politica_divulgacao", contar)
    gid = _gid(contas_db, "Visitante")
    lidas.clear()
    _pagina(cli, gid)
    # o acesso do proprio Administrador nao le a politica (ele entrou); so a previa le, uma vez, desta pesquisa
    assert lidas == ["real"]
    lidas.clear()
    _pagina(cli, _gid(contas_db, "Leitor"))
    assert lidas == []


def test_contas_ocupadas_na_leitura_da_politica(adm, monkeypatch):
    cli, contas, contas_db, _ = adm
    gid = _gid(contas_db, "Visitante")

    def ocupada(self, banco):
        raise A.ContasOcupadas()
    monkeypatch.setattr(type(contas), "politica_divulgacao", ocupada)
    r = cli.get(f"/admin/grupos/{gid}")
    assert r.status_code == 503


# ---------------- pagina de revisao ----------------

def test_revisao_mostra_o_menu_com_as_alteracoes(adm):
    cli, _, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    novas = LEITOR | {"ver_chamadas"}
    h = _revisar(cli, gid, sorted(novas)).text
    secoes = _secoes(h)
    assert [s[0] for s in secoes] == ["Prévia do menu com estas alterações"]
    assert secoes[0][1] == _esperado("Leitor", novas)
    assert secoes[0][1] != _esperado("Leitor", LEITOR)                 # e a hipotese, nao o gravado
    assert h.count(NOTA) == 1
    i_form = h.index(f'<form method="post" action="/admin/grupos/{gid}/permissoes"')
    assert h.index("</form>", i_form) < h.index('<section class="perm-previa"')


def test_revisao_do_visitante_tem_uma_previa_por_estado(adm):
    cli, contas, contas_db, _ = adm
    gravar_politica(contas, "real", publica=True)
    gid = _gid(contas_db, "Visitante")
    h = _revisar(cli, gid, []).text                                    # retira ver_painel do Visitante
    secoes = _secoes(h)
    assert [s[0] for s in secoes] == [f"Prévia do menu com estas alterações: {NAO_DIV}",
                                      f"Prévia do menu com estas alterações: {DIV} (estado atual)"]
    assert secoes[0][1] == [] and secoes[1][1] == [] and secoes[1][2] is True
    assert _esperado("Visitante", {"ver_painel"}, ABERTA)                # hoje o Visitante ve o menu


@pytest.mark.parametrize("marcadas", [sorted(LEITOR), sorted(LEITOR | {"triar_texto_completo"})])
def test_revisao_sem_alteracao_ou_com_erro_nao_mostra_previa(adm, marcadas):
    cli, _, contas_db, _ = adm
    h = _revisar(cli, _gid(contas_db, "Leitor"), marcadas).text
    assert '<section class="perm-previa"' not in h and NOTA not in h


def test_formulario_incompleto_nao_mostra_previa(adm):
    cli, _, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    h = _post(cli, f"/admin/grupos/{gid}/revisar", [("csrf", _csrf(cli, f"/admin/grupos/{gid}/editar"))]).text
    assert '<section class="perm-previa"' not in h and NOTA not in h


def test_gravacao_recusada_volta_a_revisao_com_a_previa(adm):
    """Sem a confirmacao exigida, o servidor recusa e mostra a revisao de novo: a previa tambem volta."""
    cli, _, contas_db, _ = adm
    gid = _gid(contas_db, "Leitor")
    novas = LEITOR | {"ver_chamadas"}
    h = _revisar(cli, gid, sorted(novas)).text
    pares = [(k, v) for k, v in _form(h, f"/admin/grupos/{gid}/permissoes") if k != "confirmo"] + [("justificativa", "x")]
    r = _post(cli, f"/admin/grupos/{gid}/permissoes", pares)
    assert r.status_code == 400 and _erros(r.text)
    secoes = _secoes(r.text)
    assert [s[0] for s in secoes] == ["Prévia do menu com estas alterações"]
    assert secoes[0][1] == _esperado("Leitor", novas)


def test_previa_na_revisao_nao_grava_nem_troca_de_identidade(adm):
    cli, _, contas_db, _ = adm
    gid = _gid(contas_db, "Visitante")
    con = sqlite3.connect(contas_db)
    antes = (sorted(con.execute("SELECT grupo_id, permissao FROM grupo_permissoes").fetchall()),
             con.execute("SELECT COUNT(*) FROM auditoria_admin").fetchone()[0],
             sorted(con.execute("SELECT * FROM sessoes").fetchall()))
    r = _revisar(cli, gid, [])
    assert r.status_code == 200 and _secoes(r.text)
    assert "set-cookie" not in {k.lower() for k in r.headers.keys()} or "__session" not in r.headers.get("set-cookie", "")
    con = sqlite3.connect(contas_db)
    depois = (sorted(con.execute("SELECT grupo_id, permissao FROM grupo_permissoes").fetchall()),
              con.execute("SELECT COUNT(*) FROM auditoria_admin").fetchone()[0],
              sorted(con.execute("SELECT * FROM sessoes").fetchall()))
    assert depois == antes
    h = cli.get("/admin/grupos").text                                  # continua o Administrador
    assert "Administração" in h and cli.get("/admin/grupos").status_code == 200


def test_previa_da_revisao_usa_a_navegacao_e_o_estado_revisado(adm, monkeypatch):
    cli, _, contas_db, _ = adm
    chamadas = []
    original = navegacao.grupos

    def espiao(*a, **k):
        chamadas.append(k)
        return original(*a, **k)
    monkeypatch.setattr(navegacao, "grupos", espiao)
    gid = _gid(contas_db, "Leitor")
    _revisar(cli, gid, sorted(LEITOR | {"ver_chamadas"}))
    da_previa = [k for k in chamadas if "pode" in k and k.get("admin") is False and k.get("banco") == "real"]
    da_previa = [k for k in da_previa if k["pode"]("GET", "/execucoes") is True]
    assert len(da_previa) == 1


def test_revisao_do_visitante_tem_a_nota_uma_vez_depois_das_duas(adm):
    cli, _, contas_db, _ = adm
    h = _revisar(cli, _gid(contas_db, "Visitante"), []).text
    assert len(_secoes(h)) == 2 and h.count(NOTA) == 1 and h.rindex("</section>") < h.index(NOTA)


def _ocupada(self, banco):
    raise A.ContasOcupadas()


def test_contas_ocupadas_na_revisao(adm, monkeypatch):
    cli, contas, contas_db, _ = adm
    gid = _gid(contas_db, "Visitante")
    monkeypatch.setattr(type(contas), "politica_divulgacao", _ocupada)
    assert _revisar(cli, gid, []).status_code == 503


def test_contas_ocupadas_na_gravacao_recusada(adm, monkeypatch):
    cli, contas, contas_db, _ = adm
    gid = _gid(contas_db, "Visitante")
    h = _revisar(cli, gid, []).text
    pares = [(k, v) for k, v in _form(h, f"/admin/grupos/{gid}/permissoes") if k != "confirmo"] + [("justificativa", "")]

    def recusa(self, *a, **k):
        raise A.AlteracaoRecusada(["Recusa de teste."])
    monkeypatch.setattr(type(contas), "definir_permissoes_do_grupo", recusa)
    lidas = []
    original = type(contas).politica_divulgacao

    def contar(self, banco):
        lidas.append(banco)
        return original(self, banco)
    monkeypatch.setattr(type(contas), "politica_divulgacao", contar)
    r = _post(cli, f"/admin/grupos/{gid}/permissoes", pares)
    assert r.status_code == 400 and _erros(r.text) == ["Recusa de teste."] and len(_secoes(r.text)) == 2
    assert lidas == ["real"]
    monkeypatch.setattr(type(contas), "politica_divulgacao", _ocupada)
    assert _post(cli, f"/admin/grupos/{gid}/permissoes", pares).status_code == 503


def test_revisao_le_a_politica_uma_vez(adm, monkeypatch):
    cli, contas, contas_db, _ = adm
    lidas = []
    original = type(contas).politica_divulgacao

    def contar(self, banco):
        lidas.append(banco)
        return original(self, banco)
    monkeypatch.setattr(type(contas), "politica_divulgacao", contar)
    _revisar(cli, _gid(contas_db, "Visitante"), [])
    assert lidas == ["real"]


def test_previa_usa_o_resultado_da_revisao_que_a_rota_ja_tem(adm, monkeypatch):
    """A previa recebe o "depois" da revisao calculada pela rota (uma chamada), nunca um recalculo."""
    cli, _, contas_db, _ = adm
    chamadas = []
    original = A.revisar_alteracao

    def marcada(*a, **k):
        r = original(*a, **k)
        chamadas.append(1)
        if not r["erros"] and (r["concedidas"] or r["retiradas"]):
            r = dict(r, depois=sorted(set(r["depois"]) | {"ver_chamadas"}))
        return r
    monkeypatch.setattr(A, "revisar_alteracao", marcada)
    gid = _gid(contas_db, "Leitor")
    h = _revisar(cli, gid, sorted(LEITOR | {"triar_artigos"})).text
    assert len(chamadas) == 1 and len(_secoes(h)) == 1
    assert _secoes(h)[0][1] == _esperado("Leitor", LEITOR | {"triar_artigos", "ver_chamadas"})
