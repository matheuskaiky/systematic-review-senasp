"""Origem da busca x angulo predominante (recorte da triagem v2) nas analises do banco `vies`: o recorte chega aos itens,
cada obra elegivel (relevancia alta ou media) conta uma vez numa combinacao de conjuntos e numa coluna de angulo, o recorte
ausente ou desconhecido fica em coluna propria, a divergencia entre web e Scholar e contada sem apagar a do Scholar, e a
obra fora do universo fica de fora da matriz."""
import copy

import pytest

from dominio import analises_vies as AV
from painel import analises_blocos_vies as bv

CONJ = {"LA1": "A", "LA2": "A", "LB1": "B", "LC1": "C"}
NOMES = ("A", "B", "C")
RECORTES = {"vies_algoritmico": "Viés algorítmico", "aplicacoes_tecnologicas": "Aplicações tecnológicas"}
V, AP = "vies_algoritmico", "aplicacoes_tecnologicas"


def _web(i, consultas="LA1", url=None, titulo=None):
    return {"referencia_id": i, "dominio": "exemplo.org", "url_original": f"https://exemplo.org/w{i}" if url is None else url,
            "titulo": titulo or f"Página {i}", "data_pub": "2025-03-01", "consultas": consultas, "conjuntos": "", "execucoes": "r"}


def _art(i, consultas="LB1", url=None, titulo=None):
    return {"artigo_id": i, "autores_publicacao": "A - R", "ano": 2024, "titulo": titulo or f"Artigo {i}",
            "link": f"https://s.org/a{i}" if url is None else url, "consultas": consultas, "execucoes": "r"}


def _t(relevancia="alta", recorte=V, valido=1):
    return {"valido": valido, "status_bruto": relevancia, "tipo_fonte": "Artigo científico", "pais_escopo": "Brasil",
            "topicos": "x", "eixo": "y", "confianca": "alta", "recorte": recorte}


def _itens(web=(), arts=(), tri=None):
    return AV.itens(list(web), list(arts), CONJ, tri or {})


def _celulas(r):
    return {(l, c): n for l, cs in r["matriz"].items() for c, n in cs.items() if n}


# ---------- o recorte chega aos itens ----------
@pytest.mark.parametrize("triagem, recorte", [
    (_t(recorte=V), V), (_t(recorte=AP), AP), (_t(recorte=None), None), (_t(recorte="outro"), "outro"),
    (_t(recorte=V, valido=0), None), (None, None),
])
def test_recorte_da_triagem_valida_chega_ao_item(triagem, recorte):
    tri = {("referencia", 1): triagem} if triagem is not None else {}
    item, = _itens([_web(1)], [], tri)
    assert item["recorte"] == recorte


def test_triagem_sem_coluna_recorte_vale_como_ausente():
    t = _t()
    del t["recorte"]
    assert _itens([_web(1)], [], {("referencia", 1): t})[0]["recorte"] is None


# ---------- a matriz ----------
def test_obra_so_de_c_com_vies():
    r = AV.origem_por_angulo(_itens([_web(1, "LC1")], [], {("referencia", 1): _t(recorte=V)}), NOMES, tuple(RECORTES))
    assert _celulas(r) == {("Só C", V): 1} and r["elegiveis"] == 1 and r["fora"] == 0


@pytest.mark.parametrize("consultas, linha", [("LA1", "Só A"), ("LB1", "Só B")])
def test_obra_so_de_a_ou_b_com_aplicacoes(consultas, linha):
    r = AV.origem_por_angulo(_itens([], [_art(5, consultas)], {("artigo", 5): _t(recorte=AP)}), NOMES, tuple(RECORTES))
    assert _celulas(r) == {(linha, AP): 1}


def test_artigo_de_a_com_web_de_c_conta_uma_vez_em_a_mais_c():
    lista = _itens([_web(1, "LC1", url="https://s.org/a5")], [_art(5, "LA1")],
                   {("artigo", 5): _t(recorte=V), ("referencia", 1): _t(recorte=V)})
    r = AV.origem_por_angulo(lista, NOMES, tuple(RECORTES))
    assert _celulas(r) == {("A + C", V): 1} and r["elegiveis"] == 1 and r["divergentes"] == 0


def test_par_web_scholar_divergente_usa_o_scholar_e_conta_a_divergencia():
    lista = _itens([_web(1, "LC1", url="https://s.org/a5")], [_art(5, "LA1")],
                   {("artigo", 5): _t(recorte=AP), ("referencia", 1): _t(recorte=V)})
    r = AV.origem_por_angulo(lista, NOMES, tuple(RECORTES))
    assert _celulas(r) == {("A + C", AP): 1} and r["divergentes"] == 1
    assert [i["recorte"] for i in lista] == [V, AP]          # a divergencia continua nos itens


def test_divergencia_so_conta_obras_da_matriz():
    lista = _itens([_web(1, "LC1", url="https://s.org/a5")], [_art(5, "LA1")],
                   {("artigo", 5): _t("baixa", AP), ("referencia", 1): _t("alta", V)})
    r = AV.origem_por_angulo(lista, NOMES, tuple(RECORTES))
    assert _celulas(r) == {} and r["fora"] == 1 and r["divergentes"] == 0


def test_relevancia_da_obra_e_a_do_scholar_mesmo_com_web_elegivel():
    """Scholar baixo e web alta: a obra fica fora (vale a triagem do artigo, como em `obras` e nas outras analises)."""
    lista = _itens([_web(1, "LC1", url="https://s.org/a5")], [_art(5, "LA1")],
                   {("artigo", 5): _t("baixa", V), ("referencia", 1): _t("alta", V)})
    r = AV.origem_por_angulo(lista, NOMES, tuple(RECORTES))
    assert (r["elegiveis"], r["fora"]) == (0, 1)


@pytest.mark.parametrize("rec_scholar, rec_web, celula, divergente", [
    (None, V, AV.SEM_ANGULO, 0),        # o Scholar sem angulo vale (precedencia): coluna propria, sem divergencia
    ("", V, AV.SEM_ANGULO, 0),
    (V, "", V, 0),                      # angulo desconhecido num membro nao e divergencia
    (V, "outro", V, 0),
    (V, AP, V, 1),
])
def test_regra_da_divergencia_com_angulos_ausentes_ou_desconhecidos(rec_scholar, rec_web, celula, divergente):
    lista = _itens([_web(1, "LC1", url="https://s.org/a5")], [_art(5, "LA1")],
                   {("artigo", 5): _t(recorte=rec_scholar), ("referencia", 1): _t(recorte=rec_web)})
    r = AV.origem_por_angulo(lista, NOMES, tuple(RECORTES))
    assert _celulas(r) == {("A + C", celula): 1} and r["divergentes"] == divergente


def test_duas_webs_diferentes_num_scholar_sem_angulo_nao_e_divergencia():
    web = [_web(1, "LC1", url="https://s.org/a5"), _web(2, "LB1", url="https://s.org/a5")]
    tri = {("artigo", 5): _t(recorte=None), ("referencia", 1): _t(recorte=V), ("referencia", 2): _t(recorte=AP)}
    r = AV.origem_por_angulo(_itens(web, [_art(5, "LA1")], tri), NOMES, tuple(RECORTES))
    assert _celulas(r) == {("A + B + C", AV.SEM_ANGULO): 1} and r["divergentes"] == 0


@pytest.mark.parametrize("triagem", [None, _t(valido=0)])
def test_sem_triagem_valida_fica_fora_do_universo(triagem):
    tri = {("referencia", 1): triagem} if triagem else {}
    r = AV.origem_por_angulo(_itens([_web(1, "LC1")], [], tri), NOMES, tuple(RECORTES))
    assert _celulas(r) == {} and r["fora"] == 1 and r["elegiveis"] == 0


@pytest.mark.parametrize("recorte", [None, "outro", "", "VIES_ALGORITMICO"])
def test_recorte_ausente_ou_desconhecido_vai_para_sem_angulo(recorte):
    r = AV.origem_por_angulo(_itens([_web(1, "LA1")], [], {("referencia", 1): _t(recorte=recorte)}), NOMES, tuple(RECORTES))
    assert _celulas(r) == {("Só A", AV.SEM_ANGULO): 1}


@pytest.mark.parametrize("relevancia, entra", [("alta", True), ("media", True), ("baixa", False), ("fora_do_escopo", False),
                                               (None, False), ("outra", False)])
def test_so_relevancia_alta_ou_media_entra(relevancia, entra):
    r = AV.origem_por_angulo(_itens([_web(1, "LA1")], [], {("referencia", 1): _t(relevancia)}), NOMES, tuple(RECORTES))
    assert (r["elegiveis"], r["fora"]) == ((1, 0) if entra else (0, 1))


def test_lista_vazia_tem_todas_as_linhas_e_colunas_com_zero():
    r = AV.origem_por_angulo([], NOMES, tuple(RECORTES))
    assert r["linhas"] == AV.combinacoes(NOMES) + [AV.SEM_CONJUNTO] and r["colunas"] == [V, AP, AV.SEM_ANGULO]
    assert _celulas(r) == {} and (r["elegiveis"], r["fora"], r["divergentes"], r["ambiguas"]) == (0, 0, 0, [])


def test_obra_sem_conjunto_reconhecido():
    r = AV.origem_por_angulo(_itens([_web(1, "ZZ9")], [], {("referencia", 1): _t()}), NOMES, tuple(RECORTES))
    assert _celulas(r) == {(AV.SEM_CONJUNTO, V): 1}


def test_cada_obra_numa_celula_so_e_soma_igual_aos_elegiveis():
    web = [_web(1, "LA1"), _web(2, "LB1"), _web(3, "LC1"), _web(4, "LA1,LC1"), _web(5, "LC1", url="https://s.org/a7")]
    arts = [_art(6, "LA1,LB1"), _art(7, "LB1"), _art(8, "LA1")]
    tri = {("referencia", i): _t(recorte=V if i % 2 else AP) for i in range(1, 6)}
    tri.update({("artigo", 6): _t(recorte=AP), ("artigo", 7): _t("media", V), ("artigo", 8): _t("baixa", V)})
    lista = _itens(web, arts, tri)
    r = AV.origem_por_angulo(lista, NOMES, tuple(RECORTES))
    obras, _ = AV.obras_com_origem(lista)
    assert sum(r["matriz"][l][c] for l in r["linhas"] for c in r["colunas"]) == r["elegiveis"] == 6
    assert r["elegiveis"] + r["fora"] == len(obras) == 7
    assert _celulas(r) == {("Só A", V): 1, ("Só B", AP): 1, ("Só C", V): 1, ("A + C", AP): 1, ("A + B", AP): 1, ("B + C", V): 1}


def test_linhas_da_matriz_batem_com_a_origem_da_f01():
    """Somando as colunas e os nao elegiveis, cada linha e a contagem de `conjuntos_por_obra`."""
    web = [_web(1, "LA1"), _web(2, "LC1"), _web(3, "LB1,LC1")]
    tri = {("referencia", 1): _t(), ("referencia", 2): _t("baixa"), ("referencia", 3): _t(recorte=AP)}
    lista = _itens(web, [], tri)
    r = AV.origem_por_angulo(lista, NOMES, tuple(RECORTES))
    contagem, _ = AV.conjuntos_por_obra(lista, NOMES)
    assert {l: sum(r["matriz"][l].values()) for l in r["linhas"]} == {**contagem, "Só C": 0}
    assert contagem["Só C"] == 1 and r["fora"] == 1


def test_entrada_nao_muda():
    lista = _itens([_web(1, "LC1", url="https://s.org/a5")], [_art(5, "LA1")], {("artigo", 5): _t()})
    antes = copy.deepcopy(lista)
    AV.origem_por_angulo(lista, NOMES, tuple(RECORTES))
    assert lista == antes


# ---------- o bloco ----------
def _lista_bloco():
    web = [_web(1, "LA1"), _web(2, "LC1", url="https://s.org/a5"), _web(3, "LB1")]
    tri = {("referencia", 1): _t(recorte=V), ("referencia", 2): _t(recorte=V), ("artigo", 5): _t(recorte=AP),
           ("referencia", 3): _t("fora_do_escopo")}
    return _itens(web, [_art(5, "LA1")], tri)


def test_bloco_titulo_subtitulo_textos_e_tabela():
    b = bv.bloco_origem_angulo(_lista_bloco(), NOMES, RECORTES)
    assert b["id"] == "vies-origem-angulo"
    assert b["titulo"] == "Origem da busca × ângulo predominante: 2 obras elegíveis"
    assert b["subtitulo"] == ("por obra: denominador de 2 obras elegíveis (relevância alta ou média); não são itens nem "
                              "ocorrências")
    assert b["texto"] == [
        "Cada célula representa obras distintas, classificadas com relevância alta ou média pela triagem v2. Os conjuntos "
        "indicam onde as obras foram encontradas; os ângulos representam classificações predominantes atribuídas "
        "automaticamente pelo modelo. Uma obra pode abordar os dois temas, embora tenha apenas um ângulo predominante.",
        "Interseção temática viés × aplicações: indisponível na triagem v2, pois o recorte é mutuamente exclusivo por construção.",
        "Fora desta matriz: 1 obra de relevância baixa, fora do escopo ou sem triagem válida (na obra que junta web e Scholar, "
        "vale a triagem do artigo do Scholar; o panorama mostra a relevância por item).",
        "1 obra tem itens com ângulos diferentes na web e no Scholar; a matriz usa o ângulo do artigo do Scholar."]
    assert b["aviso"] == bv.AVISO_MODELO
    assert b["tabela"]["cabecalho"] == ["Origem", "Viés algorítmico", "Aplicações tecnológicas", "Sem ângulo", "Total de obras"]
    assert b["tabela"]["linhas"] == [
        ["Só A", "1", "0", "0", "1"], ["Só B", "0", "0", "0", "0"], ["Só C", "0", "0", "0", "0"],
        ["A + B", "0", "0", "0", "0"], ["A + C", "0", "1", "0", "1"], ["B + C", "0", "0", "0", "0"],
        ["A + B + C", "0", "0", "0", "0"], ["Sem conjunto", "0", "0", "0", "0"], ["Total", "1", "1", "0", "2"]]


def test_bloco_sem_divergencia_nao_traz_a_frase():
    lista = _itens([_web(1, "LA1")], [], {("referencia", 1): _t()})
    textos = bv.bloco_origem_angulo(lista, NOMES, RECORTES)["texto"]
    assert len(textos) == 3 and not any("ângulos diferentes" in t for t in textos)
    assert textos[2] == ("Fora desta matriz: 0 obras de relevância baixa, fora do escopo ou sem triagem válida (na obra que junta "
                         "web e Scholar, vale a triagem do artigo do Scholar; o panorama mostra a relevância por item).")


def test_bloco_plural_das_divergencias():
    web = [_web(1, "LC1", url="https://s.org/a5"), _web(2, "LC1", url="https://s.org/a6")]
    tri = {("referencia", 1): _t(recorte=V), ("referencia", 2): _t(recorte=V), ("artigo", 5): _t(recorte=AP),
           ("artigo", 6): _t(recorte=AP)}
    textos = bv.bloco_origem_angulo(_itens(web, [_art(5, "LA1"), _art(6, "LB1")], tri), NOMES, RECORTES)["texto"]
    assert textos[-1] == "2 obras têm itens com ângulos diferentes na web e no Scholar; a matriz usa o ângulo do artigo do Scholar."


def test_bloco_avisa_das_referencias_ambiguas():
    arts = [_art(5, "LA1", url="https://s.org/c"), _art(6, "LB1", url="https://s.org/c")]
    tri = {("artigo", 5): _t(), ("artigo", 6): _t(), ("referencia", 1): _t()}
    textos = bv.bloco_origem_angulo(_itens([_web(1, "LC1", url="https://s.org/c")], arts, tri), NOMES, RECORTES)["texto"]
    assert textos[-1] == ("1 referência da web casa com mais de um artigo do Scholar: os conjuntos dela não foram somados a "
                          "nenhuma obra (a decidir).")


def test_bloco_sem_obras_elegiveis():
    lista = _itens([_web(1, "LA1")], [], {("referencia", 1): _t("baixa")})
    b = bv.bloco_origem_angulo(lista, NOMES, RECORTES)
    assert b["titulo"] == "Sem obras elegíveis para cruzar origem e ângulo predominante" and b["tabela"] is None


def test_bloco_nao_diz_que_a_intersecao_e_zero_nem_tem_links():
    b = bv.bloco_origem_angulo(_lista_bloco(), NOMES, RECORTES)
    texto = " ".join(b["texto"]) + str(b["grafico"])
    assert "interseção" not in b["titulo"].lower() and "indisponível na triagem v2" in texto and "<a " not in str(b["grafico"])


def test_pagina_de_analises_mostra_a_matriz_depois_dos_conjuntos(tmp_path):
    import re
    from fastapi.testclient import TestClient
    from adaptadores.bruto_local import BrutoLocal
    from adaptadores.leitura_sqlite import LeituraPainelSQLite
    from adaptadores.repositorio_sqlite import RepositorioSQLite
    from config import consultas as C, triagem_escopo as TE, vocabulario as V_
    from config.eixos_tematicos import EIXOS_EXPLORACAO
    from painel.app import Contexto, criar_app
    from test_triagem_vies import construir_vies
    from test_triagem_vies_painel import _linha, _triar
    construir_vies(tmp_path / "busca.db", tmp_path / "raw")
    import sqlite3
    con = sqlite3.connect(tmp_path / "busca.db")
    refs = [x[0] for x in con.execute("SELECT referencia_id FROM referencias_web ORDER BY 1")]
    con.close()
    _triar(tmp_path / "busca.db", [_linha("referencia", refs[0], recorte="aplicacoes_tecnologicas")]
           + [_linha("referencia", i, recorte="vies_algoritmico") for i in refs[1:]])
    ctx = Contexto(banco="vies", nome_banco="busca.db", somente_leitura=True, pasta_backup=tmp_path / "b", ufs=dict(C.UFS),
                   status_permitidos=set(V_.STATUS), status_definicoes=dict(V_.STATUS), hosts_permitidos=("testserver",),
                   conjunto_da_consulta={t.id: n for n, ts in C.CONJUNTOS_LITERATURA.items() for t in ts},
                   consultas_literatura={t.id: t.query for ts in C.CONJUNTOS_LITERATURA.values() for t in ts},
                   eixos_exploracao=dict(EIXOS_EXPLORACAO), versao_triagem_vies=TE.PROMPT_TRIAGEM_VIES_VERSAO,
                   versoes_triagem_vies=TE.VERSOES_TRIAGEM_VIES, recortes_vies=dict(TE.RECORTES_VIES))
    cli = TestClient(criar_app(LeituraPainelSQLite(tmp_path / "busca.db"), lambda: RepositorioSQLite(tmp_path / "busca.db"),
                               BrutoLocal(tmp_path), ctx))
    html = cli.get("/analises?secao=consultas").text
    assert html.index('id="vies-conjuntos"') < html.index('id="vies-origem-angulo"')
    bloco = html[html.index('id="vies-origem-angulo"'):]
    assert "Viés algorítmico" in bloco and "Aplicações tecnológicas" in bloco and "Total de obras" in bloco
    total = re.search(r"Origem da busca × ângulo predominante: (\d+) obras? elegíve", bloco)
    assert total and int(total.group(1)) >= 1
    linhas = re.findall(r"<tr><td>([^<]+)</td>", bloco[bloco.index("Total de obras"):])
    assert linhas[:9] == ["Só A", "Só B", "Só C", "A + B", "A + C", "B + C", "A + B + C", "Sem conjunto", "Total"]
