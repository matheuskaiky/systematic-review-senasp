"""A lista de obras do Observatorio do banco `vies` (/observatorio/obras): os mesmos filtros e a mesma projecao do dominio,
os erros sem eco do valor, a ordem e as paginas, as URLs que preservam os filtros, as colunas de cada obra com os links
para as fichas, uma so leitura consistente por resposta e a pagina so no banco `vies`."""
import re
import sqlite3

import pytest
from fastapi.testclient import TestClient

import config.settings as S
from adaptadores.bruto_local import BrutoLocal
from adaptadores.leitura_sqlite import LeituraPainelSQLite
from adaptadores.repositorio_sqlite import RepositorioSQLite
from config import consultas as C, triagem_escopo as TE, vocabulario as V
from config.triagem_escopo import RECORTES_VIES
from dominio import analises_vies as AV, autenticacao, observatorio_vies as OV
from painel.app import Contexto, criar_app
from painel.rotas_extras import observatorio as RO
from test_leitura_instantaneo import _Rastreada, rastreio, renderizacoes  # noqa: F401
from test_observatorio_vies import NOMES, RECORTES, _art, _corpus, _itens, _t, _web
from test_validacao_vies import banco  # noqa: F401  (vies com triagem, para a leitura real)

EIXOS = {"E1": "d1", "E2": "d2", "E3": "d3"}


def _ctx(nome="vies", tmp=None):
    return Contexto(banco=nome, nome_banco="busca.db", somente_leitura=True, pasta_backup=(tmp or S.DATA_DIR) / "b",
                    ufs=dict(C.UFS), status_permitidos=set(V.STATUS), status_definicoes=dict(V.STATUS),
                    hosts_permitidos=("testserver",), termos={},
                    conjunto_da_consulta={t.id: n for n, ts in C.CONJUNTOS_LITERATURA.items() for t in ts},
                    consultas_literatura={t.id: t.query for ts in C.CONJUNTOS_LITERATURA.values() for t in ts},
                    eixos_exploracao=dict(EIXOS), versao_triagem_vies=TE.PROMPT_TRIAGEM_VIES_VERSAO,
                    recortes_vies=dict(RECORTES_VIES))


def _cli(banco_db, tmp_path, nome="vies"):
    return TestClient(criar_app(LeituraPainelSQLite(banco_db), lambda: RepositorioSQLite(banco_db), BrutoLocal(tmp_path),
                                _ctx(nome, tmp_path)))


@pytest.fixture
def sintetico(monkeypatch, banco, tmp_path):
    """O painel do banco `vies` com os itens trocados pelos do corpus sintetico de seis obras (a leitura do banco continua
    acontecendo; so o resultado de `visao_geral_vies.itens` muda)."""
    itens = {"lista": _corpus()}
    monkeypatch.setattr(RO.visao_geral_vies, "itens", lambda leitura, contexto: itens["lista"])
    return _cli(banco, tmp_path), itens


def _linhas(html):
    """Os ids da coluna Itens de cada linha da tabela, na ordem."""
    corpo = html.split("<tbody>", 1)[1].split("</tbody>", 1)[0] if "<tbody>" in html else ""
    return [re.findall(r">((?:A|W)-\d+)</a>", tr) for tr in corpo.split("<tr")[1:]]


def _total(html):
    m = re.search(r"<strong>([\d.]+)</strong> (obra|obras) · universo: ", html)
    return int(m.group(1).replace(".", "")) if m else None


# ---------- o auxiliar das URLs ----------
@pytest.mark.parametrize("mudancas, esperado", [
    ({}, ""),
    ({"pagina": 2}, "pagina=2"),
    ({"fonte": "web"}, "fonte=web"),
    ({"angulo": "sem_angulo", "combinacao": "A+C"}, "combinacao=A%2BC&angulo=sem_angulo"),     # na ordem de FILTROS
    ({"perspectiva": "integrada", "universo": "elegiveis"}, ""),                              # os padroes nao aparecem
    ({"perspectiva": "vies", "universo": "todas"}, "perspectiva=vies&universo=todas"),
    ({"eixo": "Biometria e vigilância"}, "eixo=Biometria+e+vigil%C3%A2ncia"),
    ({"fonte": None, "pagina": 3}, "pagina=3"),
])
def test_consulta(mudancas, esperado):
    filtros = {"perspectiva": "integrada", "universo": "elegiveis", "combinacao": None, "conjunto": None, "fonte": None,
               "angulo": None, "eixo": None}
    assert RO.consulta(filtros, **mudancas) == esperado


def test_consulta_parte_dos_filtros_ativos():
    filtros = {"perspectiva": "integrada", "universo": "todas", "combinacao": None, "conjunto": "C", "fonte": "web",
               "angulo": None, "eixo": None}
    assert RO.consulta(filtros) == "universo=todas&conjunto=C&fonte=web"
    assert RO.consulta(filtros, pagina=2) == "universo=todas&conjunto=C&fonte=web&pagina=2"
    assert RO.consulta(filtros, fonte="ambas", angulo="vies_algoritmico") == \
        "universo=todas&conjunto=C&fonte=ambas&angulo=vies_algoritmico"


# ---------- so no banco vies; permissoes de sempre ----------
def test_so_no_banco_vies(banco, tmp_path):
    r = _cli(banco, tmp_path, nome="real").get("/observatorio/obras")
    assert r.status_code == 404 and "O Observatório existe só no banco vies." in r.text


def test_permissao_e_a_das_paginas_de_leitura():
    assert autenticacao.permissao_exigida("GET", "/observatorio/obras") == "ver_painel"
    assert autenticacao.permissao_exigida("GET", "/observatorio") == "ver_painel"


# ---------- a lista ----------
def test_lista_padrao(sintetico):
    cli, _ = sintetico
    r = cli.get("/observatorio/obras")
    assert r.status_code == 200
    assert "<h1>Obras do Observatório</h1>" in r.text
    assert "<strong>4</strong> obras · universo: Relevância alta ou média" in r.text
    assert _linhas(r.text) == [["A-2"], ["A-3", "W-3"], ["W-1"], ["W-5"]]           # pelo titulo: Artigo 2, Artigo 3, Pagina 1, Pagina 5
    assert "Unidade: obra" in r.text and AV.SEM_CONJUNTO in r.text
    assert "triagem automática" in r.text


@pytest.mark.parametrize("consulta, linhas", [
    ("universo=todas", [["A-2"], ["A-3", "W-3"], ["A-4"], ["A-6"], ["W-1"], ["W-5"]]),
    ("combinacao=A%2BC", [["A-3", "W-3"]]),
    ("combinacao=C", [["A-2"]]),
    ("conjunto=C", [["A-2"], ["A-3", "W-3"]]),
    ("fonte=web", [["A-3", "W-3"], ["W-1"], ["W-5"]]),
    ("fonte=so_web", [["W-1"], ["W-5"]]),
    ("fonte=so_scholar", [["A-2"]]),
    ("fonte=ambas", [["A-3", "W-3"]]),
    ("angulo=vies_algoritmico", [["A-3", "W-3"], ["W-1"]]),
    ("angulo=sem_angulo", [["W-5"]]),
    ("perspectiva=vies", [["A-3", "W-3"], ["W-1"]]),
    ("perspectiva=tecnologias", [["A-2"]]),
    ("eixo=E1", [["A-3", "W-3"], ["W-1"]]),
    ("eixo=sem_eixo", [["W-5"]]),
    ("conjunto=&fonte=+&eixo=", [["A-2"], ["A-3", "W-3"], ["W-1"], ["W-5"]]),     # vazios = sem filtro
    ("pagina=1&outra=x", [["A-2"], ["A-3", "W-3"], ["W-1"], ["W-5"]]),
])
def test_filtros_pela_url(sintetico, consulta, linhas):
    cli, _ = sintetico
    r = cli.get(f"/observatorio/obras?{consulta}")
    assert r.status_code == 200 and _linhas(r.text) == linhas
    assert _total(r.text) == len(linhas)


def test_sem_resultado(sintetico):
    cli, _ = sintetico
    r = cli.get("/observatorio/obras?eixo=E3")
    assert r.status_code == 200 and "Nenhuma obra com estes filtros." in r.text and "<tbody>" not in r.text
    assert 'href="/observatorio/obras">Limpar filtros</a>' in r.text
    assert "<strong>0</strong> obras · universo: Relevância alta ou média" in r.text


@pytest.mark.parametrize("consulta, mensagem", [
    ("fonte=%3Cscript%3E", "Filtro inválido: fonte."),
    ("conjunto=D&eixo=x", "Filtro inválido: conjunto. Filtro inválido: eixo."),
    ("fonte=web&fonte=ambas", "Filtro repetido: fonte."),
    ("perspectiva=vies&angulo=aplicacoes_tecnologicas", "O ângulo já é definido pela perspectiva: tire o filtro de ângulo."),
])
def test_filtro_invalido(sintetico, consulta, mensagem):
    cli, _ = sintetico
    r = cli.get(f"/observatorio/obras?{consulta}")
    assert r.status_code == 400 and "Filtro inválido" in r.text and mensagem in r.text
    assert "%3Cscript" not in r.text and "&lt;script&gt;" not in r.text            # o valor nunca volta na pagina


def test_filtro_invalido_nao_le_o_banco(sintetico, rastreio):
    cli, _ = sintetico
    rastreio.todas.clear()
    assert cli.get("/observatorio/obras?fonte=x").status_code == 400
    assert rastreio.todas == []


# ---------- colunas ----------
def test_colunas_da_obra_que_junta_web_e_scholar(sintetico):
    cli, _ = sintetico
    html = cli.get("/observatorio/obras?fonte=ambas").text
    cab = re.findall(r"<th[^>]*>([^<]+)</th>", html)
    assert cab == ["Título", "Fontes", "Conjuntos", "Ângulo", "Relevância", "Eixo", "Divergência", "Itens", "Documento"]
    linha = html.split("<tbody>", 1)[1].split("</tr>", 1)[0]
    celulas = re.findall(r"<td[^>]*>(.*?)</td>", linha, re.S)
    assert celulas[0] == '<a href="/literatura/artigos/3">Artigo 3</a>'
    assert celulas[1:7] == ["Web e Scholar", "A + C", "Viés algorítmico", "Alta", "E1",
                            "Membros divergem em: ângulo predominante"]
    assert celulas[7] == '<a href="/literatura/artigos/3">A-3</a> · <a href="/literatura/referencias/web/3">W-3</a>'
    assert celulas[8] == '<a href="https://s.org/a3" rel="noopener noreferrer" target="_blank">abrir</a>'


@pytest.mark.parametrize("consulta, valores", [
    ("fonte=so_web&eixo=sem_eixo", ["Web", "Sem conjunto", "Sem ângulo", "Alta", "Sem eixo", "—"]),
    ("perspectiva=tecnologias", ["Scholar", "Só C", "Aplicações tecnológicas", "Média", "E2", "—"]),
])
def test_rotulos_das_colunas(sintetico, consulta, valores):
    cli, _ = sintetico
    linha = cli.get(f"/observatorio/obras?{consulta}").text.split("<tbody>", 1)[1].split("</tr>", 1)[0]
    assert re.findall(r"<td[^>]*>(.*?)</td>", linha, re.S)[1:7] == valores


def test_relevancia_sem_triagem_valida_e_possivel_duplicata(sintetico):
    cli, itens = sintetico
    itens["lista"] = _itens([], [_art(1, url="https://x.org/p"), _art(2, url="https://x.org/p")],
                            {("artigo", 1): _t("alta", "vies_algoritmico", "E1")})
    linhas = cli.get("/observatorio/obras?universo=todas").text.split("<tbody>", 1)[1].split("<tr")[1:]
    c1, c2 = (re.findall(r"<td[^>]*>(.*?)</td>", l, re.S) for l in linhas)
    assert c1[4] == "Alta" and c2[4] == "Sem triagem válida"
    assert c1[6] == c2[6] == "Possível duplicata: outro artigo do Scholar tem a mesma URL"


def test_divergencia_e_duplicata_juntas_e_varios_campos(sintetico):
    cli, itens = sintetico
    itens["lista"] = _itens([_web(1, url="https://w.org/z", titulo="Artigo 1")],          # junta pelo titulo
                            [_art(1, url="https://x.org/p"), _art(2, url="https://x.org/p")],
                            {("artigo", 1): _t("alta", "vies_algoritmico", "E1"), ("referencia", 1): _t("media", "vies_algoritmico", "E2"),
                             ("artigo", 2): _t("alta", "vies_algoritmico", "E1")})
    html = cli.get("/observatorio/obras?universo=todas").text
    assert ("Membros divergem em: relevância, eixo; Possível duplicata: outro artigo do Scholar tem a mesma URL") in html


def test_documento_com_endereco_que_nao_e_http(sintetico):
    cli, itens = sintetico
    itens["lista"] = _itens([_web(1, url="javascript:alert(1)")], [], {("referencia", 1): _t()})
    linha = cli.get("/observatorio/obras").text.split("<tbody>", 1)[1].split("</tr>", 1)[0]
    assert re.findall(r"<td[^>]*>(.*?)</td>", linha, re.S)[8] == ""
    assert "javascript:" not in linha


# ---------- paginas e URLs ----------
@pytest.fixture
def muitas(sintetico):
    cli, itens = sintetico
    itens["lista"] = _itens([_web(i, titulo=f"Obra {i:03d}") for i in range(1, 121)], [],
                            {("referencia", i): _t() for i in range(1, 121)})
    return cli


def test_paginas(muitas):
    r1 = muitas.get("/observatorio/obras?fonte=web")
    assert _total(r1.text) == 120 and len(_linhas(r1.text)) == 50 and _linhas(r1.text)[0] == ["W-1"]
    assert "Página 1 de 3" in r1.text and "← Anterior" not in r1.text
    assert 'href="/observatorio/obras?fonte=web&amp;pagina=2">Próxima →</a>' in r1.text
    r2 = muitas.get("/observatorio/obras?fonte=web&pagina=2")
    assert _linhas(r2.text)[0] == ["W-51"] and "Página 2 de 3" in r2.text
    assert 'href="/observatorio/obras?fonte=web&amp;pagina=1">← Anterior</a>' in r2.text
    r3 = muitas.get("/observatorio/obras?fonte=web&pagina=3")
    assert len(_linhas(r3.text)) == 20 and "Próxima →" not in r3.text
    assert _total(r3.text) == 120


@pytest.mark.parametrize("consulta", ["pagina=4", "pagina=0", "pagina=x", "pagina=1&pagina=2", "pagina=" + "9" * 5000])
def test_pagina_invalida(muitas, consulta):
    r = muitas.get(f"/observatorio/obras?{consulta}")
    assert r.status_code == 400 and "Página inválida." in r.text


def test_filtro_invalido_vem_antes_da_pagina(muitas):
    r = muitas.get("/observatorio/obras?fonte=x&pagina=99")
    assert r.status_code == 400 and "Filtro inválido: fonte." in r.text and "Página inválida." not in r.text


def test_voltar_ao_observatorio_e_o_formulario_preservam_os_filtros(sintetico):
    cli, _ = sintetico
    html = cli.get("/observatorio/obras?universo=todas&conjunto=C&fonte=web&pagina=1").text
    assert '<a href="/observatorio?universo=todas&amp;conjunto=C&amp;fonte=web">Observatório</a>' in html
    assert re.search(r'<option value="todas" selected>Todas as obras</option>', html)
    assert re.search(r'<option value="C" selected>C</option>', html)
    assert re.search(r'<option value="web" selected>Achada na web</option>', html)
    assert '<form class="filtros" method="get" action="/observatorio/obras">' in html


def test_perspectiva_que_fixa_o_angulo_tira_o_seletor_de_angulo(sintetico):
    cli, _ = sintetico
    html = cli.get("/observatorio/obras?perspectiva=vies").text
    assert 'name="angulo"' not in html and "Ângulo: definido pela perspectiva (Viés algorítmico)." in html
    assert 'name="angulo"' in cli.get("/observatorio/obras").text


# ---------- leitura real: uma conexao, nada aberto ao renderizar ----------
def test_uma_leitura_consistente_por_resposta(banco, tmp_path, rastreio, renderizacoes):
    cli = _cli(banco, tmp_path)
    rastreio.todas.clear()
    renderizacoes.clear()
    r = cli.get("/observatorio/obras?universo=todas")
    assert r.status_code == 200 and _total(r.text) == 5                      # 4 referencias e 1 artigo, nenhuma junção
    assert len(rastreio.todas) == 1 and rastreio.abertas == [] and set(renderizacoes) == {0}


def test_banco_ausente(tmp_path):
    r = _cli(tmp_path / "nao_existe.db", tmp_path).get("/observatorio/obras")
    assert r.status_code == 503


# ---------- PostgreSQL: a mesma projecao ----------
@pytest.mark.postgres
def test_paridade_da_projecao_pg(banco, pg_url):
    from adaptadores import migrador_postgres as M
    from adaptadores.leitura_postgres import LeituraPainelPostgres
    from adaptadores.postgres import conexao as CX, importador as I
    from painel import visao_geral_vies
    M.aplicar(pg_url)
    M.aplicar(pg_url, esquema="vies")
    I.importar(banco, pg_url, esquema="vies")
    pool = CX.criar_pool(pg_url, esquema="vies")
    try:
        ctx = _ctx()
        nomes = tuple(dict.fromkeys(ctx.conjunto_da_consulta.values()))

        def projecao(leitura):
            with leitura.instantaneo() as l:
                return OV.projecao(visao_geral_vies.itens(l, ctx), nomes)
        sqlite = projecao(LeituraPainelSQLite(banco))
        assert sqlite[0] and projecao(LeituraPainelPostgres(pool, CX.chaves_do_banco(pool))) == sqlite
    finally:
        pool.close()


def test_obra_sem_titulo(sintetico):
    cli, itens = sintetico
    itens["lista"] = _itens([_web(1)], [], {("referencia", 1): _t()})
    itens["lista"][0]["titulo"] = ""
    linha = cli.get("/observatorio/obras").text.split("<tbody>", 1)[1].split("</tr>", 1)[0]
    assert re.findall(r"<td[^>]*>(.*?)</td>", linha, re.S)[0] == '<a href="/literatura/referencias/web/1">Sem título</a>'


def test_sub_e_aviso(sintetico):
    cli, _ = sintetico
    html = cli.get("/observatorio/obras").text
    assert ("Cada linha é uma obra: a referência da web que repete um artigo do Scholar entra na obra do artigo. Os filtros "
            "valem para a obra inteira e nunca tiram só um dos seus itens. Os rótulos vêm da triagem automática v2.") in html
    from painel.analises_blocos_vies import AVISO_MODELO
    assert f'<p class="aviso" role="status">{AVISO_MODELO}</p>' in html
    assert "<caption class=\"so-leitor\">Obras com os filtros escolhidos</caption>" in html


# ---------- pre-revisao ----------
def test_fonte_scholar_e_pertinencia(sintetico):
    cli, _ = sintetico
    assert _linhas(cli.get("/observatorio/obras?fonte=scholar").text) == [["A-2"], ["A-3", "W-3"]]


def test_banco_que_nao_e_vies_vem_antes_do_banco_ausente(tmp_path):
    r = _cli(tmp_path / "nao_existe.db", tmp_path, nome="real").get("/observatorio/obras")
    assert r.status_code == 404 and "<h1>Página não encontrada</h1>" in r.text


def test_consulta_com_todos_os_filtros_e_a_pagina():
    filtros = {"perspectiva": "vies", "universo": "todas", "combinacao": "A+C", "conjunto": "C", "fonte": "ambas",
               "angulo": "sem_angulo", "eixo": "E1"}
    assert RO.consulta(filtros, pagina=4) == ("perspectiva=vies&universo=todas&combinacao=A%2BC&conjunto=C&fonte=ambas"
                                              "&angulo=sem_angulo&eixo=E1&pagina=4")
    assert RO.consulta({**filtros, "eixo": None}, pagina=None) == ("perspectiva=vies&universo=todas&combinacao=A%2BC"
                                                                   "&conjunto=C&fonte=ambas&angulo=sem_angulo")


def _selects(html):
    """[(rotulo, name, [(value, selected, texto)])] dos selects do formulario, na ordem."""
    form = html.split('<form class="filtros"', 1)[1].split("</form>", 1)[0]
    saida = []
    for m in re.finditer(r"<label>([^<]+?)\s*<select name=\"(\w+)\">(.*?)</select>", form, re.S):
        opcoes = re.findall(r'<option value="([^"]*)"( selected)?>([^<]*)</option>', m.group(3))
        saida.append((m.group(1).strip(), m.group(2), [(v, bool(s), t) for v, s, t in opcoes]))
    return saida


def test_formulario_completo_e_padroes(sintetico):
    cli, _ = sintetico
    s = _selects(cli.get("/observatorio/obras").text)
    assert [(r, n) for r, n, _ in s] == [("Perspectiva", "perspectiva"), ("Universo", "universo"),
                                         ("Combinação exata dos conjuntos", "combinacao"), ("Achada no conjunto", "conjunto"),
                                         ("Fonte", "fonte"), ("Ângulo predominante", "angulo"), ("Eixo", "eixo")]
    op = {n: o for _, n, o in s}
    assert op["perspectiva"] == [(k, k == "integrada", t) for k, t in OV.PERSPECTIVAS]
    assert op["universo"] == [(k, k == "elegiveis", t) for k, t in OV.UNIVERSOS]
    assert op["combinacao"] == [("", False, "qualquer")] + [(k, False, t) for k, t in OV.combinacoes(NOMES)]
    assert op["conjunto"] == [("", False, "qualquer")] + [(n, False, n) for n in NOMES]
    assert op["fonte"] == [("", False, "qualquer")] + [(k, False, t) for k, t in OV.FONTES]
    assert op["angulo"] == [("", False, "qualquer"), ("vies_algoritmico", False, "Viés algorítmico"),
                            ("aplicacoes_tecnologicas", False, "Aplicações tecnológicas"), ("sem_angulo", False, "Sem ângulo")]
    assert op["eixo"] == [("", False, "qualquer"), ("E1", False, "E1"), ("E2", False, "E2"), ("E3", False, "E3"),
                          ("sem_eixo", False, "Sem eixo")]
    assert '<button class="botao" type="submit">Filtrar</button>' in cli.get("/observatorio/obras").text
    assert 'href="/observatorio/obras">Limpar</a>' not in cli.get("/observatorio/obras").text
    assert 'href="/observatorio/obras">Limpar</a>' in cli.get("/observatorio/obras?fonte=web").text


def test_formulario_marca_cada_valor_escolhido(sintetico):
    cli, _ = sintetico
    html = cli.get("/observatorio/obras?universo=todas&combinacao=A%2BC&conjunto=A&fonte=ambas&angulo=vies_algoritmico"
                   "&eixo=E1").text
    marcados = {n: [v for v, sel, _ in o if sel] for _, n, o in _selects(html)}
    assert marcados == {"perspectiva": ["integrada"], "universo": ["todas"], "combinacao": ["A+C"], "conjunto": ["A"],
                        "fonte": ["ambas"], "angulo": ["vies_algoritmico"], "eixo": ["E1"]}


def test_contagem_no_singular_e_vazio_sem_tabela_nem_paginas(sintetico):
    cli, _ = sintetico
    assert "<strong>1</strong> obra · universo: Relevância alta ou média" in cli.get("/observatorio/obras?fonte=ambas").text
    vazio = cli.get("/observatorio/obras?eixo=E3").text
    assert "<table" not in vazio and 'class="paginacao"' not in vazio


@pytest.mark.parametrize("consulta, titulo", [
    ("fonte=%3Cscript%3E", "Filtro inválido"), ("pagina=9", "Página inválida")])
def test_titulos_dos_erros_e_nenhum_eco(sintetico, consulta, titulo):
    cli, _ = sintetico
    r = cli.get(f"/observatorio/obras?{consulta}")
    assert r.status_code == 400 and f"<h1>{titulo}</h1>" in r.text and "<script>" not in r.text


def test_texto_dos_dados_e_escapado(sintetico):
    cli, itens = sintetico
    itens["lista"] = _itens([_web(1, titulo="<b>negrito</b> & cia")], [],
                            {("referencia", 1): _t(eixo="<i>eixo</i>")})
    html = cli.get("/observatorio/obras?universo=todas").text
    assert "<b>negrito</b>" not in html and "&lt;b&gt;negrito&lt;/b&gt; &amp; cia" in html
    assert "<i>eixo</i>" not in html and "&lt;i&gt;eixo&lt;/i&gt;" in html


@pytest.mark.parametrize("titulo, esperado", [("   ", "Sem título"), ("\t\n", "Sem título"), ("  Título  ", "  Título  ")])
def test_titulo_so_de_espacos(sintetico, titulo, esperado):
    cli, itens = sintetico
    itens["lista"] = _itens([_web(1)], [], {("referencia", 1): _t()})
    itens["lista"][0]["titulo"] = titulo
    linha = cli.get("/observatorio/obras").text.split("<tbody>", 1)[1].split("</tr>", 1)[0]
    assert re.findall(r"<td[^>]*>(.*?)</td>", linha, re.S)[0] == f'<a href="/literatura/referencias/web/1">{esperado}</a>'


@pytest.mark.parametrize("eixo, esperado", [("", "Sem eixo"), (None, "Sem eixo"), ("E2", "E2")])
def test_eixo_vazio(sintetico, eixo, esperado):
    cli, itens = sintetico
    itens["lista"] = _itens([_web(1)], [], {("referencia", 1): _t(eixo=eixo)})
    linha = cli.get("/observatorio/obras").text.split("<tbody>", 1)[1].split("</tr>", 1)[0]
    assert re.findall(r"<td[^>]*>(.*?)</td>", linha, re.S)[5] == esperado


# ---------- retrabalho R1 ----------
def test_documento_usa_o_filtro_url_segura_do_painel(monkeypatch, banco, tmp_path):
    """O link do documento passa pelo filtro `url_segura` do painel: se a regra de la mudar, a lista muda junto."""
    import painel.app as PA
    criados = []
    original = PA.Jinja2Templates

    class Gravado(original):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            criados.append(self)
    monkeypatch.setattr(PA, "Jinja2Templates", Gravado)
    monkeypatch.setattr(RO.visao_geral_vies, "itens", lambda leitura, contexto: _corpus())
    cli = _cli(banco, tmp_path)
    criados[0].env.filters["url_segura"] = lambda u: "#"
    corpo = cli.get("/observatorio/obras").text.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
    assert "abrir</a>" not in corpo
    criados[0].env.filters["url_segura"] = lambda u: "https://trocado.example/"
    corpo = cli.get("/observatorio/obras").text.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
    assert corpo.count('<a href="https://trocado.example/" rel="noopener noreferrer" target="_blank">abrir</a>') == 4


@pytest.mark.parametrize("relevancia, esperado", [("alta", "Alta"), ("fora_do_escopo", "Fora do escopo"),
                                                  ("valor-desconhecido", "Relevância não reconhecida"), ("", "Relevância não reconhecida"),
                                                  (None, "Sem triagem válida")])
def test_relevancia_desconhecida_aparece_como_esta(sintetico, relevancia, esperado):
    cli, itens = sintetico
    itens["lista"] = _itens([_web(1)], [], {("referencia", 1): _t()})
    itens["lista"][0]["relevancia"] = relevancia
    linha = cli.get("/observatorio/obras?universo=todas").text.split("<tbody>", 1)[1].split("</tr>", 1)[0]
    assert re.findall(r"<td[^>]*>(.*?)</td>", linha, re.S)[4] == esperado


def test_rotulos_das_combinacoes_uma_vez_por_resposta(sintetico, monkeypatch):
    cli, itens = sintetico
    itens["lista"] = _itens([_web(i, titulo=f"Obra {i:03d}") for i in range(1, 61)], [], {("referencia", i): _t() for i in range(1, 61)})
    chamadas = []
    original = OV.combinacoes
    monkeypatch.setattr(OV, "combinacoes", lambda nomes: (chamadas.append(1), original(nomes))[1])
    assert cli.get("/observatorio/obras").status_code == 200
    assert len(chamadas) <= 3                              # leitura dos filtros, formulario e rotulos: nunca uma por linha


@pytest.mark.parametrize("url", [b"https://x.example", 123, None, "  https://x.example", "ftp://x.example", "data:text/html,x",
                                 "JavaScript:alert(1)"])
def test_documento_com_endereco_inesperado_nao_derruba_a_lista(sintetico, url):
    cli, itens = sintetico
    itens["lista"] = _itens([_web(1)], [], {("referencia", 1): _t()})
    itens["lista"][0]["url"] = url
    r = cli.get("/observatorio/obras")
    assert r.status_code == 200
    linha = r.text.split("<tbody>", 1)[1].split("</tr>", 1)[0]
    assert re.findall(r"<td[^>]*>(.*?)</td>", linha, re.S)[8] == ""


def test_documento_http_maiusculo_continua_valendo(sintetico):
    cli, itens = sintetico
    itens["lista"] = _itens([_web(1)], [], {("referencia", 1): _t()})
    itens["lista"][0]["url"] = "HTTPS://X.example/a?b=1&c=2"
    linha = cli.get("/observatorio/obras").text.split("<tbody>", 1)[1].split("</tr>", 1)[0]
    assert re.findall(r"<td[^>]*>(.*?)</td>", linha, re.S)[8] == \
        '<a href="HTTPS://X.example/a?b=1&amp;c=2" rel="noopener noreferrer" target="_blank">abrir</a>'
