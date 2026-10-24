"""Origem unida por obra (todos os conjuntos de consultas): cada obra distinta, com a uniao dos conjuntos de todos os seus
itens (web e Scholar), conta uma vez na combinacao exata dos conjuntos configurados; nenhuma obra some, nenhuma juncao nova
e criada, e a referencia da web que casa com mais de um artigo fica sem atribuicao."""
import copy

import pytest

from dominio import analises_vies as AV
from painel import analises_blocos_vies as bv

CONJ = {"LA1": "A", "LA2": "A", "LB1": "B", "LC1": "C"}
NOMES = ("A", "B", "C")


def _web(i, consultas="LA1", url=None, titulo=None):
    return {"referencia_id": i, "dominio": "exemplo.org", "url_original": f"https://exemplo.org/w{i}" if url is None else url,
            "titulo": titulo or f"Página {i}", "data_pub": "2025-03-01", "consultas": consultas, "conjuntos": "", "execucoes": "r"}


def _art(i, consultas="LB1", url=None, titulo=None):
    return {"artigo_id": i, "autores_publicacao": "A - R", "ano": 2024, "titulo": f"Artigo {i}" if titulo is None else titulo,
            "link": f"https://s.org/a{i}" if url is None else url, "consultas": consultas, "execucoes": "r"}


def _itens(web=(), arts=()):
    return AV.itens(list(web), list(arts), CONJ, {})


def _por_id(obras):
    return {o["id"]: o for o in obras}


# ---------- combinacoes ----------
@pytest.mark.parametrize("nomes, rotulos", [
    (("A", "B"), ["Só A", "Só B", "A + B"]),
    (("A", "B", "C"), ["Só A", "Só B", "Só C", "A + B", "A + C", "B + C", "A + B + C"]),
    (("C", "A"), ["Só C", "Só A", "C + A"]),
    (("A",), ["Só A"]),
    ((), []),
    (("A", "B", "C", "D"), ["Só A", "Só B", "Só C", "Só D", "A + B", "A + C", "A + D", "B + C", "B + D", "C + D",
                            "A + B + C", "A + B + D", "A + C + D", "B + C + D", "A + B + C + D"]),
])
def test_combinacoes_na_ordem_dos_nomes(nomes, rotulos):
    assert AV.combinacoes(nomes) == rotulos


# ---------- uniao por obra ----------
def test_item_so_de_c_aparece():
    contagem, ambiguas = AV.conjuntos_por_obra(_itens([_web(1, "LC1")]), NOMES)
    assert contagem["Só C"] == 1 and sum(contagem.values()) == 1 and ambiguas == []


@pytest.mark.parametrize("web", [
    _web(1, "LC1", url="https://s.org/a5"),                       # mesma URL
    _web(1, "LC1", url="https://outro.org/x", titulo="Artigo 5"),  # so o titulo
])
def test_artigo_de_a_unido_a_web_de_c_vira_a_mais_c_sem_duplicar(web):
    lista = _itens([web], [_art(5, "LA2")])
    obras, ambiguas = AV.obras_com_origem(lista)
    assert [o["id"] for o in obras] == ["A-5"] and ambiguas == []
    assert obras[0]["membros"] == [("Scholar", "A-5"), ("Web", "W-1")] and obras[0]["conjuntos_da_obra"] == ["A", "C"]
    contagem, _ = AV.conjuntos_por_obra(lista, NOMES)
    assert contagem["A + C"] == 1 and contagem["Só A"] == 0 and sum(contagem.values()) == 1


def test_obra_achada_pelos_tres_conjuntos():
    lista = _itens([_web(1, "LC1", url="https://s.org/a5"), _web(2, "LB1", url="https://s.org/a5")], [_art(5, "LA1")])
    contagem, _ = AV.conjuntos_por_obra(lista, NOMES)
    assert contagem["A + B + C"] == 1 and sum(contagem.values()) == 1


def test_obra_sem_conjunto_reconhecido_vai_para_sem_conjunto():
    """Consulta fora da configuracao nao vira conjunto (AV.itens a descarta); um conjunto fora de `nomes` nao conta."""
    lista = _itens([_web(1, "ZZ9"), _web(2, "LC1")])
    assert AV.conjuntos_por_obra(lista, NOMES)[0][AV.SEM_CONJUNTO] == 1
    contagem, _ = AV.conjuntos_por_obra(lista, ("A", "B"))
    assert contagem == {"Só A": 0, "Só B": 0, "A + B": 0, AV.SEM_CONJUNTO: 2}


def test_lista_vazia_devolve_todas_as_combinacoes_com_zero():
    assert AV.conjuntos_por_obra([], NOMES) == ({r: 0 for r in AV.combinacoes(NOMES) + [AV.SEM_CONJUNTO]}, [])
    assert AV.obras_com_origem([]) == ([], [])


@pytest.mark.parametrize("web", [
    _web(1, "LC1", url="https://s.org/compartilhada"),             # a URL de dois artigos
    _web(1, "LC1", url="https://outro.org/x", titulo="Mesmo título"),  # o titulo de dois artigos
])
def test_web_que_casa_com_dois_artigos_fica_sem_atribuicao(web):
    arts = [_art(5, "LA1", url="https://s.org/compartilhada", titulo="Mesmo título"),
            _art(6, "LB1", url="https://s.org/compartilhada", titulo="Mesmo título")]
    lista = _itens([web], arts)
    obras, ambiguas = AV.obras_com_origem(lista)
    assert ambiguas == ["W-1"] and [o["id"] for o in obras] == ["A-5", "A-6"]
    assert _por_id(obras)["A-5"]["conjuntos_da_obra"] == ["A"] and _por_id(obras)["A-6"]["conjuntos_da_obra"] == ["B"]
    assert all(len(o["membros"]) == 1 for o in obras)
    contagem, amb = AV.conjuntos_por_obra(lista, NOMES)
    assert contagem["Só A"] == 1 and contagem["Só B"] == 1 and contagem["Só C"] == 0 and amb == ["W-1"]


def test_url_vence_o_titulo_como_na_deduplicacao():
    """A web casada pela URL com um artigo e pelo titulo com outro segue a regra de `obras`: vale a URL (sem ambiguidade)."""
    lista = _itens([_web(1, "LC1", url="https://s.org/a5", titulo="Artigo 6")], [_art(5, "LA1"), _art(6, "LB1")])
    obras, ambiguas = AV.obras_com_origem(lista)
    assert ambiguas == [] and _por_id(obras)["A-5"]["conjuntos_da_obra"] == ["A", "C"]
    assert _por_id(obras)["A-6"]["conjuntos_da_obra"] == ["B"]


def test_ids_iguais_em_fontes_diferentes_sao_membros_distintos():
    lista = _itens([_web(7, "LC1")], [_art(7, "LA1")])
    obras, _ = AV.obras_com_origem(lista)
    assert sorted(m for o in obras for m in o["membros"]) == [("Scholar", "A-7"), ("Web", "W-7")] and len(obras) == 2


def test_mesmas_obras_e_mesma_ordem_de_av_obras():
    lista = _itens([_web(1, "LC1", url="https://s.org/a5"), _web(2, "LA1"), _web(3, "LB1", titulo="Artigo 6")],
                   [_art(5, "LA1"), _art(6, "LC1"), _art(8, "LB1")])
    obras, _ = AV.obras_com_origem(lista)
    assert [o["id"] for o in obras] == [o["id"] for o in AV.obras(lista)]
    assert len(obras) == len(AV.obras(lista)) == 4


def test_entrada_nao_muda_nem_pelas_listas_da_saida():
    lista = _itens([_web(1, "LC1", url="https://s.org/a5")], [_art(5, "LA1")])
    antes = copy.deepcopy(lista)
    obras, _ = AV.obras_com_origem(lista)
    AV.conjuntos_por_obra(lista, NOMES)
    obras[0]["conjuntos"].append("Z")
    obras[0]["consultas"].append("ZZ")
    assert lista == antes


# ---------- bloco do painel ----------
def test_bloco_conta_obras_na_ordem_dos_nomes():
    lista = _itens([_web(1, "LC1", url="https://s.org/a5"), _web(2, "LC1")], [_art(5, "LA1"), _art(6, "LB1")])
    b = bv.bloco_conjuntos(lista, NOMES)
    assert b["titulo"] == "1 de 3 obras foi achada por mais de um conjunto de consultas"
    assert b["subtitulo"] == "por obra: todas as obras, inclusive as fora do escopo, na união dos conjuntos de todos os seus itens"
    assert b["tabela"]["cabecalho"] == ["Combinação", "Obras"]
    assert b["tabela"]["linhas"] == [["Só A", "0"], ["Só B", "1"], ["Só C", "1"], ["A + B", "0"], ["A + C", "1"], ["B + C", "0"],
                                     ["A + B + C", "0"], ["Sem conjunto", "0"]]
    assert b["texto"] == ["Cada obra conta uma vez, na combinação de todos os conjuntos que acharam os seus itens (web e Scholar). "
                          "As buscas item por item, por consulta e por fonte, estão no bloco anterior."]


@pytest.mark.parametrize("n_varios, total, titulo", [
    (0, 1, "Nenhuma de 1 obra foi achada por mais de um conjunto de consultas"),
    (0, 3, "Nenhuma de 3 obras foi achada por mais de um conjunto de consultas"),
    (1, 3, "1 de 3 obras foi achada por mais de um conjunto de consultas"),
    (2, 2, "2 de 2 obras foram achadas por mais de um conjunto de consultas"),
])
def test_titulo_concorda_em_numero(n_varios, total, titulo):
    web = [_web(i, "LA1,LB1" if i <= n_varios else "LA1") for i in range(1, total + 1)]
    assert bv.bloco_conjuntos(_itens(web), NOMES)["titulo"] == titulo


def test_bloco_avisa_das_referencias_sem_atribuicao():
    arts = [_art(5, "LA1", url="https://s.org/c"), _art(6, "LB1", url="https://s.org/c")]
    b = bv.bloco_conjuntos(_itens([_web(1, "LC1", url="https://s.org/c")], arts), NOMES)
    assert b["texto"][-1] == ("1 referência da web casa com mais de um artigo do Scholar: os conjuntos dela não foram somados "
                              "a nenhuma obra (a decidir).")


def test_bloco_sem_obras():
    assert bv.bloco_conjuntos([], NOMES)["titulo"] == "Sem obras dos conjuntos para comparar"


# ---------- linhas pedidas pela revisao ----------
def test_url_ambigua_nao_cai_no_titulo_unico():
    """A URL de dois artigos decide (como em `obras`), mesmo que o titulo case com um so: fica ambigua."""
    arts = [_art(5, "LA1", url="https://s.org/c", titulo="Único"), _art(6, "LB1", url="https://s.org/c")]
    obras, ambiguas = AV.obras_com_origem(_itens([_web(1, "LC1", url="https://s.org/c", titulo="Único")], arts))
    assert ambiguas == ["W-1"] and all(o["conjuntos_da_obra"] != ["A", "C"] for o in obras)


def test_tres_membros_por_url_e_por_titulo_na_ordem():
    lista = _itens([_web(1, "LC1", url="https://s.org/a5"), _web(2, "LB1", url="https://outro.org/y", titulo="artigo 5")],
                   [_art(5, "LA1")])
    obras, _ = AV.obras_com_origem(lista)
    assert obras[0]["membros"] == [("Scholar", "A-5"), ("Web", "W-1"), ("Web", "W-2")]
    assert obras[0]["conjuntos_da_obra"] == ["A", "B", "C"]


@pytest.mark.parametrize("url_web", ["https://www.s.org/a5/", "https://s.org/a5?utm_source=x", "https://S.ORG/a5"])
def test_url_normalizada_tambem_une(url_web):
    obras, _ = AV.obras_com_origem(_itens([_web(1, "LC1", url=url_web)], [_art(5, "LA1")]))
    assert len(obras) == 1 and obras[0]["conjuntos_da_obra"] == ["A", "C"]


def test_http_e_https_seguem_a_regra_atual_da_deduplicacao():
    """A fatia nao muda a deduplicacao: `normalizar_url` mantem o esquema, entao http e https sao obras diferentes."""
    lista = _itens([_web(1, "LC1", url="http://s.org/a5", titulo="Outro título")], [_art(5, "LA1")])
    obras, _ = AV.obras_com_origem(lista)
    assert len(obras) == len(AV.obras(lista)) == 2


def test_titulo_com_outra_caixa_e_acento_une():
    obras, _ = AV.obras_com_origem(_itens([_web(1, "LC1", url="https://outro.org/z", titulo="AVALIAÇÃO   de risco")],
                                          [_art(5, "LA1", titulo="avaliacao de Risco")]))
    assert len(obras) == 1 and obras[0]["conjuntos_da_obra"] == ["A", "C"]


def test_web_sem_url_une_pelo_titulo():
    obras, _ = AV.obras_com_origem(_itens([_web(1, "LC1", url="", titulo="Artigo 5")], [_art(5, "LA1")]))
    assert len(obras) == 1 and obras[0]["membros"] == [("Scholar", "A-5"), ("Web", "W-1")]


def test_artigo_sem_link_ou_sem_titulo_util_nunca_e_alvo():
    lista = _itens([_web(1, "LC1", url="", titulo="!!!"), _web(2, "LB1", url="https://outro.org/q", titulo="?")],
                   [_art(5, "LA1", url="", titulo="!!!"), _art(6, "LA2", url="", titulo="?")])
    obras, ambiguas = AV.obras_com_origem(lista)
    assert len(obras) == 4 and ambiguas == [] and all(len(o["membros"]) == 1 for o in obras)


def test_duas_ambiguas_no_plural_e_na_ordem_da_entrada():
    arts = [_art(5, "LA1", url="https://s.org/c"), _art(6, "LB1", url="https://s.org/c")]
    lista = _itens([_web(3, "LC1", url="https://s.org/c"), _web(1, "LC1", url="https://s.org/c")], arts)
    assert AV.obras_com_origem(lista)[1] == ["W-3", "W-1"]
    assert bv.bloco_conjuntos(lista, NOMES)["texto"][-1] == (
        "2 referências da web casam com mais de um artigo do Scholar: os conjuntos delas não foram somados a nenhuma obra "
        "(a decidir).")


def test_pagina_de_analises_do_vies_usa_os_tres_conjuntos(tmp_path):
    """A rota passa os conjuntos da configuracao (A, B, C): uma obra achada so por C aparece em "Só C"."""
    import re
    from fastapi.testclient import TestClient
    from adaptadores.bruto_local import BrutoLocal
    from adaptadores.leitura_sqlite import LeituraPainelSQLite
    from adaptadores.repositorio_sqlite import RepositorioSQLite
    from config import consultas as C, triagem_escopo as TE, vocabulario as V
    from config.eixos_tematicos import EIXOS_EXPLORACAO
    from painel.app import Contexto, criar_app
    from test_triagem_vies import construir_vies
    construir_vies(tmp_path / "busca.db", tmp_path / "raw")
    import sqlite3
    con = sqlite3.connect(tmp_path / "busca.db")
    con.execute("UPDATE ocorrencias_web SET conjunto = 'C', consulta_id = 'LC1' WHERE referencia_id = "
                "(SELECT MAX(referencia_id) FROM referencias_web)")
    con.commit()
    con.close()
    ctx = Contexto(banco="vies", nome_banco="busca.db", somente_leitura=True, pasta_backup=tmp_path / "b", ufs=dict(C.UFS),
                   status_permitidos=set(V.STATUS), status_definicoes=dict(V.STATUS), hosts_permitidos=("testserver",),
                   conjunto_da_consulta={t.id: n for n, ts in C.CONJUNTOS_LITERATURA.items() for t in ts},
                   consultas_literatura={t.id: t.query for ts in C.CONJUNTOS_LITERATURA.values() for t in ts},
                   eixos_exploracao=dict(EIXOS_EXPLORACAO), versao_triagem_vies=TE.PROMPT_TRIAGEM_VIES_VERSAO,
                   versoes_triagem_vies=TE.VERSOES_TRIAGEM_VIES, recortes_vies=dict(TE.RECORTES_VIES))
    cli = TestClient(criar_app(LeituraPainelSQLite(tmp_path / "busca.db"), lambda: RepositorioSQLite(tmp_path / "busca.db"),
                               BrutoLocal(tmp_path), ctx))
    html = cli.get("/analises?secao=consultas").text
    bloco = html[html.index('id="vies-conjuntos"'):]
    linhas = re.findall(r"<tr><td>([^<]+)</td><td[^>]*>([^<]+)</td></tr>", bloco)
    rotulos = [r for r, _ in linhas][:8]
    assert rotulos == ["Só A", "Só B", "Só C", "A + B", "A + C", "B + C", "A + B + C", "Sem conjunto"]
    assert dict(linhas)["Só C"] == "1"
