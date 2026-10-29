"""Na fila de revisao, o menu marca a fila ("Revisar achados", "Triar artigos"), nao a lista ("Achados", "Artigos")."""
import pytest

from painel import navegacao
from test_painel_navegacao import _menu, cliente, demo  # noqa: F401


def _atuais(caminho, em_fila):
    return [i["href"] for g in navegacao.grupos(caminho, em_fila) for i in g["itens"] if i["atual"]]


@pytest.mark.parametrize("caminho,em_fila,atuais", [
    ("/achados/7", True, ["/revisao/achados"]),
    ("/achados/7", False, ["/achados"]),
    ("/achados/7/", True, ["/revisao/achados"]),
    ("/achados", True, ["/revisao/achados"]),
    ("/literatura/artigos/9", True, ["/literatura/triagem"]),
    ("/literatura/artigos/9", False, ["/literatura/artigos"]),
    ("/literatura/artigos", True, ["/literatura/triagem"]),
    ("/estados/SP", True, ["/estados"]),
    ("/revisao/achados", True, ["/revisao/achados"]),
    ("/achados-antigos/1", True, []),
    ("/literatura/artigosx", True, []),
    ("", True, []),
    (None, True, []),
])
def test_item_da_fila_marca_a_fila(caminho, em_fila, atuais):
    assert _atuais(caminho, em_fila) == atuais


def test_sem_em_fila_o_padrao_e_a_lista():
    assert [i["href"] for g in navegacao.grupos("/achados/7") for i in g["itens"] if i["atual"]] == ["/achados"]


@pytest.mark.parametrize("rota,chave,atual", [("/achados/{}?fila=1", "achado", "/revisao/achados"),
                                              ("/achados/{}", "achado", "/achados"),
                                              ("/literatura/artigos/{}?fila=1", "artigo", "/literatura/triagem"),
                                              ("/literatura/artigos/{}", "artigo", "/literatura/artigos")])
def test_pagina_do_item_marca_a_fila_so_quando_aberta_pela_fila(cliente, rota, chave, atual):
    cli, ids = cliente
    r = cli.get(rota.format(ids[chave]))
    assert r.status_code == 200
    menu = _menu(r.text)
    assert [h for _, _, links in menu for h, marcado, _ in links if marcado] == [atual]
    assert [nome for nome, aberto, _ in menu if aberto] == ["Levantamento e revisão"]
