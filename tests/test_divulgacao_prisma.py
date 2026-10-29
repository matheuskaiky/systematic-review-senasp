"""PRISMA publico sem os numeros do modelo (D145, Q-P8-4 b): com a pesquisa divulgada, quem nao entrou abre o fluxo PRISMA, mas
os tres numeros que dependem da triagem de escopo do modelo aparecem como "não divulgado", com o aviso "Resultados automatizados
ainda não divulgados."; quem entrou e o painel sem login veem a pagina como antes."""
import re
import sqlite3

import pytest
from fastapi.testclient import TestClient

from apoio_divulgacao import gravar_politica
from dominio import divulgacao
from painel import rotulos
from test_autenticacao import _criar, _entrar
from test_divulgacao_acesso import _painel
from test_painel import demo  # noqa: F401

AVISO = "Resultados automatizados ainda não divulgados."
DO_MODELO = ("removidos por ferramenta automatica (triagem de escopo do modelo, sem decisao humana)",
             "artigos unicos para triagem", "pendentes de titulo e resumo")


def _caixas(html):
    """{rotulo da metrica: conteudo da celula do numero}, na ordem da pagina."""
    saida = {}
    for num, texto in re.findall(r'<li class="caixa-prisma"><span class="num-prisma">(.*?)</span>\s*<span>(.*?)<br>', html, re.S):
        saida[texto.strip()] = num.strip()
    return saida


def _valores(copia):
    return {m: v for m, v in sqlite3.connect(copia).execute("SELECT metrica, valor FROM v_prisma")}


def _com_removidos_pelo_modelo(copia, n=2):
    """Marca `n` artigos sem decisao humana como excluidos pela triagem de escopo do modelo (o banco de demonstracao nao tem
    nenhum), para os tres numeros que dependem do modelo serem diferentes de zero."""
    con = sqlite3.connect(copia)
    run = con.execute("SELECT run_id FROM execucoes ORDER BY run_id LIMIT 1").fetchone()[0]
    ids = [r[0] for r in con.execute("SELECT artigo_id FROM artigos WHERE artigo_id NOT IN (SELECT artigo_id FROM triagem "
                                     "WHERE decisao IN ('incluir', 'excluir')) ORDER BY artigo_id LIMIT ?", (n,))]
    assert len(ids) == n
    con.executemany("INSERT INTO triagem_escopo (run_id, fonte, item_id, uf, status, valido, criado_em) "
                    "VALUES (?, 'artigo', ?, '', 'excluido', 1, '2026-10-01T00:00:00+00:00')", [(run, i) for i in ids])
    con.commit()
    con.close()


def _conteudo(html):
    return html[html.index('<main id="conteudo"'):]


def _leitor(app, contas, contas_db):
    _criar((TestClient(app), contas, None, contas_db), "leo", "Leitor")
    cli = TestClient(app)
    assert _entrar(cli, "leo").status_code == 303
    return cli


def test_prisma_entra_na_lista_publica():
    assert divulgacao.ROTAS_PUBLICAS == frozenset({"/", "/sobre", "/literatura/prisma"})


@pytest.mark.parametrize("banco", ["real", "vies"])
def test_visitante_ve_o_prisma_sem_os_numeros_do_modelo(demo, tmp_path, banco):  # noqa: F811
    app, contas, _, copia = _painel(demo, tmp_path, banco=banco)
    _com_removidos_pelo_modelo(copia)
    gravar_politica(contas, banco)
    r = TestClient(app).get("/literatura/prisma", follow_redirects=False)
    assert r.status_code == 200
    caixas, valores = _caixas(r.text), _valores(copia)
    assert all(valores[m] > 0 for m in DO_MODELO)                    # o banco de teste tem os tres numeros, para o teste valer
    for m in DO_MODELO:
        assert caixas[rotulos.rotulo(rotulos.PRISMA, m)] == '<span class="nd">não divulgado</span>', m
    conteudo = _conteudo(r.text)
    assert conteudo.count(AVISO) == 1
    assert re.search(r'<div class="aviso" role="status">' + re.escape(AVISO) + "</div>", conteudo)


@pytest.mark.parametrize("banco", ["real", "vies"])
def test_os_numeros_humanos_e_da_coleta_continuam_para_o_visitante(demo, tmp_path, banco):  # noqa: F811
    app, contas, contas_db, copia = _painel(demo, tmp_path, banco=banco)
    _com_removidos_pelo_modelo(copia)
    gravar_politica(contas, banco)
    visitante = _caixas(TestClient(app).get("/literatura/prisma").text)
    leitor = _caixas(_leitor(app, contas, contas_db).get("/literatura/prisma").text)
    ocultos = {rotulos.rotulo(rotulos.PRISMA, m) for m in DO_MODELO}
    assert list(visitante) == list(leitor) and len(visitante) == 20          # as mesmas caixas, na mesma ordem
    assert {k: v for k, v in visitante.items() if k not in ocultos} == {k: v for k, v in leitor.items() if k not in ocultos}


def test_quem_entrou_ve_o_prisma_como_antes(demo, tmp_path):  # noqa: F811
    app, contas, contas_db, copia = _painel(demo, tmp_path)
    _com_removidos_pelo_modelo(copia)
    gravar_politica(contas, "real")
    h = _leitor(app, contas, contas_db).get("/literatura/prisma").text
    caixas, valores = _caixas(h), _valores(copia)
    for m in DO_MODELO:
        assert caixas[rotulos.rotulo(rotulos.PRISMA, m)] == f"{valores[m]:,}".replace(",", "."), m
    assert AVISO not in h and "não divulgado" not in h
    assert 'href="/triagem-escopo"' in _conteudo(h) and '<a href="/literatura">Literatura</a>' in h


def test_sem_login_o_prisma_nao_muda(demo, tmp_path):  # noqa: F811
    app, _, _, copia = _painel(demo, tmp_path, autenticacao=False)
    _com_removidos_pelo_modelo(copia)
    h = TestClient(app).get("/literatura/prisma").text
    caixas, valores = _caixas(h), _valores(copia)
    for m in DO_MODELO:
        assert caixas[rotulos.rotulo(rotulos.PRISMA, m)] == f"{valores[m]:,}".replace(",", "."), m
    assert AVISO not in h and 'href="/triagem-escopo"' in _conteudo(h)


def test_os_links_do_prisma_do_visitante_so_levam_a_paginas_abertas(demo, tmp_path):  # noqa: F811
    app, contas, _, _ = _painel(demo, tmp_path)
    gravar_politica(contas, "real")
    h = TestClient(app).get("/literatura/prisma").text
    links = {re.sub(r"[?#].*", "", x) for x in re.findall(r'href="(/[^"]*)"', _conteudo(h))}
    assert links <= {"/", "/sobre", "/literatura/prisma", "/entrar"}, links
    assert '<p class="trilha">Literatura › PRISMA</p>' in h                 # a trilha fica, sem o link para a pagina fechada


def test_menu_do_visitante_com_o_prisma(demo, tmp_path):  # noqa: F811
    from test_divulgacao_acesso import _menu
    app, contas, _, _ = _painel(demo, tmp_path)
    gravar_politica(contas, "real")
    assert _menu(TestClient(app).get("/").text) == ["/", "/literatura/prisma", "/sobre"]


@pytest.mark.parametrize("estado", [None, False])
def test_sem_divulgacao_o_prisma_vai_para_a_entrada(demo, tmp_path, estado):  # noqa: F811
    app, contas, _, _ = _painel(demo, tmp_path)
    if estado is not None:
        gravar_politica(contas, "real", publica=estado)
    r = TestClient(app).get("/literatura/prisma", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/entrar?proximo=%2Fliteratura%2Fprisma"


@pytest.mark.parametrize("banco", ["real", "vies"])
def test_a_pagina_do_visitante_nao_depende_dos_numeros_do_modelo(demo, tmp_path, banco):  # noqa: F811
    """Nada do que o modelo removeu chega ao visitante, em lugar nenhum da resposta (atributos, dados embutidos): com 2 ou 5
    artigos removidos pelo modelo, a pagina do visitante e a mesma, byte a byte (ela nao tem nada que mude a cada pedido)."""
    paginas, do_leitor = [], []
    for n in (2, 5):
        app, contas, contas_db, copia = _painel(demo, tmp_path / str(n), banco=banco)
        _com_removidos_pelo_modelo(copia, n)
        gravar_politica(contas, banco)
        r = TestClient(app).get("/literatura/prisma", follow_redirects=False)
        assert r.status_code == 200
        paginas.append(r.content)
        do_leitor.append(_leitor(app, contas, contas_db).get("/literatura/prisma").content)
    assert paginas[0] == paginas[1]
    assert do_leitor[0] != do_leitor[1]                  # para quem entrou os numeros mudam: o teste enxerga a diferenca
