"""Textos do painel: os rotulos do fluxo PRISMA aparecem com acento (a view guarda a chave sem acento, que nao muda) e as
etiquetas da fila de triagem e de revisao nao comecam com um separador solto."""
import re

import pytest
from fastapi.testclient import TestClient

from painel import rotulos
from test_painel import _app, demo  # noqa: F401

PRISMA = [
    ("execucoes de busca academica", "execuções de busca acadêmica"),
    ("Google Scholar: artigos unicos", "Google Scholar: artigos únicos"),
    ("buscas manuais: apos filtro da base (contagem informada)", "buscas manuais: após filtro da base (contagem informada)"),
    ("registros (artigo x fonte) apos remover duplicatas entre termos", "registros (artigo × fonte) após remover duplicatas entre termos"),
    ("removidos por ferramenta automatica (triagem de escopo do modelo, sem decisao humana)",
     "removidos por ferramenta automática (triagem de escopo do modelo, sem decisão humana)"),
    ("artigos unicos para triagem", "artigos únicos para triagem"),
    ("avaliados por titulo e resumo", "avaliados por título e resumo"),
    ("excluidos por titulo e resumo", "excluídos por título e resumo"),
    ("incluidos por titulo e resumo", "incluídos por título e resumo"),
    ("pendentes de titulo e resumo", "pendentes de título e resumo"),
    ("excluidos por texto completo", "excluídos por texto completo"),
    ("incluidos no estudo (texto completo)", "incluídos no estudo (texto completo)"),
]
SEM_MUDANCA = ["Google Scholar: registros retornados", "buscas manuais: registros retornados (contagem informada)",
               "Google Scholar: duplicatas entre termos removidas", "buscas manuais: selecionados (contagem informada)",
               "buscas manuais: artigos importados (por base)", "duplicatas entre fontes removidas",
               "avaliados por texto completo", "aguardando texto completo"]


def test_tabela_de_rotulos_do_prisma_e_exatamente_a_lista():
    assert rotulos.PRISMA == dict(PRISMA)


@pytest.fixture(scope="module")
def pagina_prisma(demo, tmp_path_factory):
    banco, raw = demo
    app, _ = _app(banco, raw, tmp_path_factory.mktemp("prisma"))
    return TestClient(app).get("/literatura/prisma").text


@pytest.mark.parametrize("chave,texto", PRISMA)
def test_prisma_mostra_o_rotulo_acentuado_e_nao_a_chave(pagina_prisma, chave, texto):
    spans = re.findall(r'<span class="num-prisma">[^<]*</span>\s*<span>([^<]*)<br>', pagina_prisma)
    assert texto in spans and chave not in spans


@pytest.mark.parametrize("texto", SEM_MUDANCA)
def test_prisma_rotulos_que_ja_eram_corretos_continuam(pagina_prisma, texto):
    spans = re.findall(r'<span class="num-prisma">[^<]*</span>\s*<span>([^<]*)<br>', pagina_prisma)
    assert texto in spans


def test_prisma_continua_marcando_contagem_informada_e_ferramenta_automatica(pagina_prisma):
    assert pagina_prisma.count("contagem informada por você") == 3
    assert pagina_prisma.count('<a href="/triagem-escopo">ver a triagem do modelo</a>') == 1


@pytest.mark.parametrize("caminho", ["/literatura/triagem", "/revisao/achados"])
def test_etiqueta_da_fila_nao_comeca_com_separador(demo, tmp_path, caminho):
    banco, raw = demo
    app, _ = _app(banco, raw, tmp_path)
    h = TestClient(app).get(caminho).text
    etiquetas = re.findall(r'<span class="fila-info">([^<]*)', h)
    assert etiquetas, "a fila precisa mostrar a etiqueta"
    assert all(not e.lstrip().startswith("·") for e in etiquetas)
    assert all(e.startswith("fila de ") for e in etiquetas)
