"""Busca no texto publica sem os achados do modelo (D145, Q-P8-4 b): com a pesquisa divulgada, quem nao entrou procura no texto
coletado (D78, D136), mas nao ve a coluna "Achados dessa página" (tecnologia, estagio e nome da solucao vem do modelo); o servidor
nem le esses achados para ele. Um aviso traz "Resultados automatizados ainda não divulgados.". Quem entrou e o painel sem login
veem a pagina como antes."""
import re

import pytest
from fastapi.testclient import TestClient

from adaptadores.leitura_sqlite import LeituraPainelSQLite
from apoio_divulgacao import gravar_politica
from dominio import divulgacao
from test_autenticacao import _criar, _entrar
from test_divulgacao_acesso import _menu, _painel
from test_painel import demo  # noqa: F401

AVISO = '<div class="aviso" role="status">Resultados automatizados ainda não divulgados.</div>'
# (url, status de hoje): formulario vazio, resultados, filtro por UF, palavra inteira, nenhum resultado e os tres avisos 400
ESTADOS = [("/buscar-texto", 200), ("/buscar-texto?q=seguran%C3%A7a", 200), ("/buscar-texto?q=seguran%C3%A7a&uf=SP", 200),
           ("/buscar-texto?q=seguran%C3%A7a&inteira=1", 200), ("/buscar-texto?q=zzzzqqqq", 200), ("/buscar-texto?q=ab", 400),
           ("/buscar-texto?q=seguran%C3%A7a&uf=XX", 400), ("/buscar-texto?q=%21%21%21", 400)]
BUSCAS = [u for u, _ in ESTADOS]


def _visitante(demo, tmp_path, banco="real"):  # noqa: F811
    app, contas, contas_db, copia = _painel(demo, tmp_path, banco=banco)
    gravar_politica(contas, banco)
    return app, contas, contas_db


def _leitor(app, contas, contas_db):
    _criar((TestClient(app), contas, None, contas_db), "leo", "Leitor")
    cli = TestClient(app)
    assert _entrar(cli, "leo").status_code == 303
    return cli


def _abre(cli, url):
    """A pagina sem seguir desvio: um desvio para a entrada nunca passa por pagina aberta."""
    r = cli.get(url, follow_redirects=False)
    assert r.status_code == 200, (url, r.status_code)
    return r


def _conteudo(html):
    return html[html.index('<main id="conteudo"'):]


def test_busca_no_texto_entra_na_lista_publica():
    assert divulgacao.ROTAS_PUBLICAS == frozenset({"/", "/sobre", "/literatura/prisma", "/metodologia", "/buscar-texto"})


def test_o_banco_de_teste_tem_achados_nas_paginas_achadas(demo, tmp_path):  # noqa: F811
    """Para os testes valerem: quem entrou ve achados na coluna para a busca usada."""
    app, contas, contas_db = _visitante(demo, tmp_path)
    h = _leitor(app, contas, contas_db).get(BUSCAS[1]).text
    assert "Achados dessa página" in h and re.search(r'href="/achados/\d+"', h)


def _sem_achados(corpo):
    assert corpo.count(AVISO) == 1 and "</form>\n" + AVISO in corpo         # uma vez, logo depois do formulario
    assert "Achados dessa página" not in corpo and "nenhum achado nesta página" not in corpo
    assert not re.search(r'href="/achados', corpo)


@pytest.mark.parametrize("url,status", ESTADOS)
def test_visitante_busca_sem_os_achados_do_modelo(demo, tmp_path, url, status):  # noqa: F811
    app, _, _ = _visitante(demo, tmp_path)
    r = TestClient(app).get(url, follow_redirects=False)
    assert r.status_code == status                            # o mesmo status de hoje
    _sem_achados(_conteudo(r.text))


def test_o_servidor_nem_le_os_achados_para_o_visitante(demo, tmp_path, monkeypatch):  # noqa: F811
    lidas = []
    original = LeituraPainelSQLite.achados_das_urls

    def espia(self, pares):
        lidas.append(len(pares))
        return original(self, pares)
    monkeypatch.setattr(LeituraPainelSQLite, "achados_das_urls", espia)
    app, contas, contas_db = _visitante(demo, tmp_path)
    _abre(TestClient(app), BUSCAS[1])
    assert lidas == []
    _abre(_leitor(app, contas, contas_db), BUSCAS[1])
    assert len(lidas) == 1


def test_a_pagina_do_visitante_nao_depende_dos_achados(demo, tmp_path):  # noqa: F811
    """Os achados gravados mudam (nome da solucao, tecnologia e estagio vem do modelo): a pagina do visitante e a mesma, byte a
    byte, em todos os estados; a de quem entrou muda."""
    import sqlite3
    paginas, do_leitor = [], []
    for mudar in (False, True):
        app, contas, contas_db, copia = _painel(demo, tmp_path / str(mudar))
        gravar_politica(contas, "real")
        if mudar:
            con = sqlite3.connect(copia)
            con.execute("UPDATE achados SET nome_solucao = 'Solucao Trocada', status_reportado = 'em_estudo'")
            con.commit()
            con.close()
        paginas.append([_abre(TestClient(app), u).content if s == 200 else TestClient(app).get(u).content for u, s in ESTADOS])
        do_leitor.append(_abre(_leitor(app, contas, contas_db), BUSCAS[1]).content)
    assert paginas[0] == paginas[1]
    assert do_leitor[0] != do_leitor[1]


def test_os_resultados_do_texto_continuam_para_o_visitante(demo, tmp_path):  # noqa: F811
    """A contagem de paginas, os trechos marcados e o link para a pagina original sao do texto coletado e continuam."""
    app, contas, contas_db = _visitante(demo, tmp_path)
    visitante = _abre(TestClient(app), BUSCAS[1]).text
    leitor = _abre(_leitor(app, contas, contas_db), BUSCAS[1]).text
    contagem = re.search(r'<p class="contagem" role="status">Foram pesquisadas.*?citam', leitor, re.S).group(0)
    assert contagem in visitante
    assert re.findall(r"<mark>.*?</mark>", visitante) == re.findall(r"<mark>.*?</mark>", leitor) != []
    assert re.findall(r'class="link-original" href="([^"]+)"', visitante) == re.findall(r'class="link-original" href="([^"]+)"', leitor)


def test_quem_entrou_e_sem_login_veem_como_antes(demo, tmp_path):  # noqa: F811
    app, contas, contas_db = _visitante(demo, tmp_path)
    h = _leitor(app, contas, contas_db).get(BUSCAS[1]).text
    assert AVISO not in h and "Achados dessa página" in h and 'href="/achados?q=' in h
    assert '<a href="/solucoes">Soluções conhecidas</a>' in _leitor_sem_busca(app, contas, contas_db)
    app2, _, _, _ = _painel(demo, tmp_path / "sem", autenticacao=False)
    h = TestClient(app2).get(BUSCAS[1]).text
    assert AVISO not in h and "Achados dessa página" in h and 'href="/achados?q=' in h
    assert '<a href="/solucoes">Soluções conhecidas</a>' in TestClient(app2).get("/buscar-texto").text


def _leitor_sem_busca(app, contas, contas_db):
    cli = TestClient(app)
    assert _entrar(cli, "leo").status_code == 303
    return cli.get("/buscar-texto").text


def test_os_links_do_visitante_so_levam_a_paginas_abertas(demo, tmp_path):  # noqa: F811
    app, _, _ = _visitante(demo, tmp_path)
    for url in BUSCAS:
        corpo = _conteudo(TestClient(app).get(url, follow_redirects=False).text)
        links = {re.sub(r"[?#].*", "", x) for x in re.findall(r'href="(/[^"]*)"', corpo)}
        assert links <= {"/", "/sobre", "/literatura/prisma", "/metodologia", "/buscar-texto", "/entrar"}, (url, links)
    assert "Veja a conferência por solução em Soluções conhecidas." in _abre(TestClient(app), "/buscar-texto").text


def test_menu_do_visitante_com_a_busca(demo, tmp_path):  # noqa: F811
    app, _, _ = _visitante(demo, tmp_path)
    assert _menu(TestClient(app).get("/").text) == ["/", "/buscar-texto", "/literatura/prisma", "/metodologia", "/sobre"]


def test_no_vies_o_visitante_tambem_busca_sem_achados(demo, tmp_path):  # noqa: F811
    app, _, _ = _visitante(demo, tmp_path, banco="vies")
    _sem_achados(_conteudo(_abre(TestClient(app), BUSCAS[1]).text))


@pytest.mark.parametrize("estado", [None, False])
def test_sem_divulgacao_a_busca_vai_para_a_entrada(demo, tmp_path, estado):  # noqa: F811
    app, contas, _, _ = _painel(demo, tmp_path)
    if estado is not None:
        gravar_politica(contas, "real", publica=estado)
    r = TestClient(app).get("/buscar-texto?q=abc", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/entrar?proximo=%2Fbuscar-texto%3Fq%3Dabc"
