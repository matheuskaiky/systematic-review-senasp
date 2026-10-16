"""Filtro "Brasil" de /literatura/artigos: dois sinais independentes (palavras no texto e escopo geografico do modelo)."""
import shutil
import sqlite3

import pytest
from fastapi.testclient import TestClient

import painel_demo
from adaptadores.leitura_sqlite import FILTRO_BRASIL, LeituraPainelSQLite
from test_painel import _app
from test_painel_triagem_escopo import semear


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("demo_brasil")
    banco = painel_demo.construir(pasta)
    ids = semear(banco)
    c = sqlite3.connect(banco)
    pend = [r[0] for r in c.execute("""SELECT a.artigo_id FROM r_artigos a LEFT JOIN triagem t ON t.artigo_id=a.artigo_id
                                       WHERE COALESCE(t.decisao,'pendente')='pendente' ORDER BY a.artigo_id""")]
    a, b, cq = pend[0], pend[1], pend[2]
    # a: palavra Brasil no titulo + modelo Brasil (os dois)   b: modelo internacional, sem palavras
    # cq: so o modelo diz Brasil (sem palavras)               i: sem veredito e sem palavras
    c.execute("UPDATE artigos SET titulo='Reconhecimento facial na polícia do Brasil', snippet='', autores_publicacao='', link='https://exemplo.org/a' WHERE artigo_id=?", (a,))
    c.execute("UPDATE artigos SET titulo='Hospital municipal usa IA', snippet='', autores_publicacao='', link='https://exemplo.org/b' WHERE artigo_id=?", (b,))
    c.execute("UPDATE artigos SET titulo='Câmeras de hospital universitário', snippet='', autores_publicacao='', link='https://exemplo.org/c' WHERE artigo_id=?", (cq,))
    c.execute("UPDATE triagem_escopo SET escopo_geografico='brasil' WHERE fonte='artigo' AND item_id IN (?, ?)", (a, cq))
    c.execute("UPDATE triagem_escopo SET escopo_geografico='internacional' WHERE fonte='artigo' AND item_id=?", (b,))
    sem_veredito = [i for i in pend if i not in {x for x, in c.execute("SELECT item_id FROM triagem_escopo WHERE fonte='artigo'")}][0]
    c.execute("UPDATE artigos SET titulo='Obra sem relacao', snippet='', autores_publicacao='', link='https://exemplo.org/d' WHERE artigo_id=?", (sem_veredito,))
    c.commit()
    c.close()
    return banco, {"a": a, "b": b, "cq": cq, "sem": sem_veredito}


def _ids(banco, **filtros):
    r = LeituraPainelSQLite(banco).artigos({"llm": "todos", **filtros}, 1, 200)
    return {x["artigo_id"] for x in r["itens"]}


def test_cada_opcao_do_filtro_separa_os_indicios(base):
    banco, i = base
    # a = texto cita o Brasil e a IA diz Brasil; cq = so a IA; b = IA diz internacional, texto sem Brasil; sem = nada
    assert {i["a"], i["cq"]} <= _ids(banco, brasil="sim") and i["b"] not in _ids(banco, brasil="sim")
    assert i["a"] in _ids(banco, brasil="certo") and i["cq"] not in _ids(banco, brasil="certo")
    assert i["cq"] in _ids(banco, brasil="talvez") and i["a"] not in _ids(banco, brasil="talvez")
    assert i["b"] in _ids(banco, brasil="fora") and i["a"] not in _ids(banco, brasil="fora")
    assert i["sem"] in _ids(banco, brasil="sem") and not ({i["a"], i["cq"], i["b"]} & _ids(banco, brasil="sem"))


def test_categorias_nao_se_sobrepoem_e_sim_e_a_uniao(base):
    banco, _ = base
    certo, talvez, fora, sem = (_ids(banco, brasil=k) for k in ("certo", "talvez", "fora", "sem"))
    assert certo.isdisjoint(talvez) and certo.isdisjoint(fora) and certo.isdisjoint(sem)
    assert talvez.isdisjoint(fora) and talvez.isdisjoint(sem) and fora.isdisjoint(sem)
    assert _ids(banco, brasil="sim") == certo | talvez
    assert certo | talvez | fora | sem == _ids(banco)               # toda linha cai em exatamente uma categoria


def test_valor_desconhecido_nao_filtra_e_nao_quebra(base):
    banco, _ = base
    assert _ids(banco, brasil="inexistente") == _ids(banco)
    assert FILTRO_BRASIL == ("sim", "certo", "talvez", "fora", "sem")


def test_escopo_so_vale_com_veredito_valido(base, tmp_path):
    banco, i = base
    copia = tmp_path / "v.db"
    shutil.copy(banco, copia)
    c = sqlite3.connect(copia)
    c.execute("UPDATE triagem_escopo SET valido=0 WHERE fonte='artigo' AND item_id=?", (i["cq"],))
    c.commit()
    c.close()
    assert i["cq"] not in _ids(copia, brasil="sim") and i["cq"] in _ids(copia, brasil="sem")


def test_pagina_mostra_o_filtro_a_coluna_e_filtra(base, tmp_path):
    banco, i = base
    copia = tmp_path / "p.db"
    shutil.copy(banco, copia)
    app, _ = _app(copia, tmp_path / "raw", tmp_path, somente_leitura=True)
    cli = TestClient(app)
    html = cli.get("/literatura/artigos").text
    assert 'name="brasil"' in html and "<th>Brasil</th>" in html and "Qualquer indício" in html and "Brasil com certeza" in html and "Como o filtro Brasil decide" in html
    assert "palavras ou modelo" not in html
    r = cli.get("/literatura/artigos?brasil=certo&llm=todos")
    assert r.status_code == 200 and f"/literatura/artigos/{i['a']}" in r.text and f"/literatura/artigos/{i['b']}" not in r.text
    assert cli.get("/literatura/artigos?brasil=%3Cscript%3E").status_code == 200


def test_banco_sem_triagem_de_escopo_ainda_filtra_por_palavras(tmp_path):
    banco = painel_demo.construir(tmp_path)
    leitura = LeituraPainelSQLite(banco)
    assert leitura.artigos({"brasil": "sim"}, 1, 200)["total"] >= 0
    assert leitura.artigos({"brasil": "certo"}, 1, 200)["total"] == 0          # sem triagem de escopo nao ha o segundo indicio
