"""Auditoria da identidade das obras do banco `vies`: os itens da web juntados a artigos do Scholar (pela URL ou so pelo
titulo), as divergencias de classificacao entre os dois, as URLs compartilhadas por artigos diferentes e as referencias
ambiguas. Descritiva: a deduplicacao e as contagens por obra nao mudam."""
import copy

import pytest

from dominio import analises_vies as AV
from painel import analises_blocos_vies as bv

CONJ = {"LA1": "A", "LB1": "B", "LC1": "C"}
RECORTES = {"vies_algoritmico": "Viés algorítmico", "aplicacoes_tecnologicas": "Aplicações tecnológicas"}


def _web(i, consultas="LC1", url=None, titulo=None):
    return {"referencia_id": i, "dominio": "e.org", "url_original": f"https://e.org/w{i}" if url is None else url,
            "titulo": titulo or f"Página {i}", "data_pub": "2025-01-01", "consultas": consultas, "conjuntos": "", "execucoes": "r"}


def _art(i, consultas="LA1", url=None, titulo=None):
    return {"artigo_id": i, "autores_publicacao": "A - R", "ano": 2024, "titulo": titulo or f"Artigo {i}",
            "link": f"https://s.org/a{i}" if url is None else url, "consultas": consultas, "execucoes": "r"}


def _t(relevancia="alta", recorte="vies_algoritmico", eixo="Direitos e governança", tipo="Artigo científico", pais="Brasil"):
    return {"valido": 1, "status_bruto": relevancia, "tipo_fonte": tipo, "pais_escopo": pais, "topicos": "x", "eixo": eixo,
            "confianca": "alta", "recorte": recorte}


def _itens(web=(), arts=(), tri=None):
    return AV.itens(list(web), list(arts), CONJ, tri or {})


def test_par_pela_url_sem_divergencia():
    lista = _itens([_web(1, url="https://s.org/a5")], [_art(5)], {("referencia", 1): _t(), ("artigo", 5): _t()})
    r = AV.auditoria_identidade(lista)
    (p,) = r["pares"]
    assert (p["obra"], p["web"], p["criterio"], p["status"], p["divergencias"]) == ("A-5", "W-1", "url", "juncao_url", [])
    assert [m["id"] for m in p["membros"]] == ["A-5", "W-1"] and p["membros"][1]["conjuntos"] == ["C"]
    assert r["contagens"] == {"pares": 1, "por_url": 1, "por_titulo": 0, "pares_com_divergencia": 0,
                              "divergencias": {c: 0 for c in AV.CAMPOS_AUDITADOS}, "urls_compartilhadas": 0, "ambiguas": 0}


def test_par_so_pelo_titulo_e_juncao_automatica_pelo_titulo():
    lista = _itens([_web(1, url="https://outro.org/x", titulo="Artigo 5")], [_art(5)])
    (p,) = AV.auditoria_identidade(lista)["pares"]
    assert (p["criterio"], p["status"]) == ("titulo", "juncao_titulo")


@pytest.mark.parametrize("campo, artigo, web", [
    ("relevancia", _t(relevancia="alta"), _t(relevancia="baixa")),
    ("recorte", _t(recorte="vies_algoritmico"), _t(recorte="aplicacoes_tecnologicas")),
    ("eixo", _t(eixo="Direitos e governança"), _t(eixo=None)),                 # ausencia conta como valor
    ("tipo_fonte", _t(tipo="Artigo científico"), _t(tipo="Tese / dissertação")),
    ("pais", _t(pais="Brasil"), _t(pais="Portugal")),
])
def test_cada_campo_divergente_e_contado(campo, artigo, web):
    lista = _itens([_web(1, url="https://s.org/a5")], [_art(5)], {("artigo", 5): artigo, ("referencia", 1): web})
    r = AV.auditoria_identidade(lista)
    assert r["pares"][0]["divergencias"] == [campo]
    assert r["contagens"]["divergencias"][campo] == 1 and r["contagens"]["pares_com_divergencia"] == 1


def test_divergencia_continua_visivel_mesmo_com_a_web_fora_da_contagem_por_obra():
    """A obra conta com o rotulo do Scholar (a web sai de `obras`), mas a auditoria guarda os dois lados."""
    lista = _itens([_web(1, url="https://s.org/a5")], [_art(5)],
                   {("artigo", 5): _t(recorte="aplicacoes_tecnologicas"), ("referencia", 1): _t(recorte="vies_algoritmico")})
    assert [o["id"] for o in AV.obras(lista)] == ["A-5"]
    p = AV.auditoria_identidade(lista)["pares"][0]
    assert [m["recorte"] for m in p["membros"]] == ["aplicacoes_tecnologicas", "vies_algoritmico"]


def test_sem_triagem_os_campos_ficam_vazios_e_contam_quando_so_um_lado_tem():
    lista = _itens([_web(1, url="https://s.org/a5")], [_art(5)], {("artigo", 5): _t()})
    p = AV.auditoria_identidade(lista)["pares"][0]
    assert p["membros"][1]["relevancia"] is None and p["divergencias"] == list(AV.CAMPOS_AUDITADOS)
    sem_nenhuma = AV.auditoria_identidade(_itens([_web(1, url="https://s.org/a5")], [_art(5)]))
    assert sem_nenhuma["pares"][0]["divergencias"] == []


def test_urls_compartilhadas_por_artigos_diferentes_seguem_obras_distintas():
    arts = [_art(5, url="https://s.org/c/"), _art(6, url="https://www.s.org/c"), _art(7)]
    lista = _itens([], arts)
    r = AV.auditoria_identidade(lista)
    (g,) = r["urls_compartilhadas"]
    assert (g["url"], g["artigos"], g["status"], g["divergencias"]) == ("https://s.org/c", ["A-5", "A-6"], "possivel_duplicata", [])
    assert [m["id"] for m in g["membros"]] == ["A-5", "A-6"]
    assert len(AV.obras(lista)) == 3 and r["pares"] == [] and r["contagens"]["urls_compartilhadas"] == 1


def test_web_que_casa_com_dois_artigos_e_ambigua_e_nao_vira_par():
    arts = [_art(5, url="https://s.org/c"), _art(6, url="https://s.org/c")]
    r = AV.auditoria_identidade(_itens([_web(1, url="https://s.org/c")], arts))
    assert r["pares"] == [] and r["ambiguas"] == [{"web": "W-1", "criterio": "url", "artigos": ["A-5", "A-6"], "status": "ambiguidade"}]
    assert r["contagens"]["ambiguas"] == 1
    assert [g["artigos"] for g in r["urls_compartilhadas"]] == [["A-5", "A-6"]]       # so artigos do Scholar, nunca a web


def test_sem_coincidencia_e_entrada_vazia():
    r = AV.auditoria_identidade(_itens([_web(1)], [_art(5)]))
    assert r["pares"] == [] and r["ambiguas"] == [] and r["urls_compartilhadas"] == []
    vazia = AV.auditoria_identidade([])
    assert vazia["pares"] == [] and vazia["contagens"]["pares"] == 0


def test_dois_itens_da_web_na_mesma_obra_dao_dois_pares():
    web = [_web(1, url="https://s.org/a5"), _web(2, url="https://outro.org/y", titulo="Artigo 5")]
    r = AV.auditoria_identidade(_itens(web, [_art(5)]))
    assert [(p["obra"], p["web"], p["criterio"]) for p in r["pares"]] == [("A-5", "W-1", "url"), ("A-5", "W-2", "titulo")]


def test_auditoria_nao_muda_a_entrada_nem_as_obras_nem_a_origem():
    web = [_web(1, url="https://s.org/a5"), _web(2, "LB1"), _web(3, url="https://s.org/c")]
    arts = [_art(5), _art(6, url="https://s.org/c"), _art(7, url="https://s.org/c")]
    lista = _itens(web, arts, {("artigo", 5): _t(), ("referencia", 1): _t(pais="Portugal")})
    antes = copy.deepcopy(lista)
    obras_antes, origem_antes = AV.obras(lista), AV.conjuntos_por_obra(lista, ("A", "B", "C"))
    AV.auditoria_identidade(lista)
    assert lista == antes and AV.obras(lista) == obras_antes and AV.conjuntos_por_obra(lista, ("A", "B", "C")) == origem_antes


def test_casamentos_da_web_mantem_a_origem_da_f01():
    """O auxiliar comum nao muda `obras_com_origem` (URL antes do titulo; ambiguidade sem atribuicao)."""
    arts = [_art(5, url="https://s.org/c", titulo="Único"), _art(6, url="https://s.org/c")]
    obras, ambiguas = AV.obras_com_origem(_itens([_web(1, url="https://s.org/c", titulo="Único")], arts))
    assert ambiguas == ["W-1"] and all(len(o["membros"]) == 1 for o in obras)


# ---------- o bloco ----------
def _lista_bloco():
    web = [_web(1, url="https://s.org/a5"), _web(2, url="https://outro.org/y", titulo="Artigo 6")]
    arts = [_art(5), _art(6, consultas="LB1"), _art(7, url="https://s.org/c"), _art(8, url="https://s.org/c")]
    tri = {("artigo", 5): _t(), ("referencia", 1): _t(recorte="aplicacoes_tecnologicas", pais="Portugal"),
           ("artigo", 6): _t(), ("referencia", 2): _t()}
    return _itens(web, arts, tri)


def test_bloco_titulo_textos_pares_e_tabela():
    b = bv.bloco_identidade(_lista_bloco(), RECORTES)
    assert b["id"] == "vies-identidade"
    assert b["titulo"] == "2 itens da web foram juntados a artigos do Scholar; 1 par tem classificações diferentes"
    assert b["subtitulo"] == "por par: cada item da web juntado a um artigo do Scholar (D104), inclusive os fora do escopo"
    assert b["aviso"] == bv.AVISO_MODELO
    assert b["texto"][0].startswith("Divergência de classificação:") and "não por ser mais correto" in b["texto"][0]
    assert b["texto"][1].startswith("Identidade:") and "Nenhuma decisão nova de identidade foi tomada." in b["texto"][1]
    assert b["texto"][2] == ("1 URL normalizada é compartilhada por artigos diferentes do Scholar, que seguem contados como "
                             "obras distintas: A-7 e A-8.")
    assert b["pares"] == [("Pares web/Scholar", "2"), ("… pela URL", "1"), ("… só pelo título", "1"),
                          ("Pares com classificação diferente", "1"), ("Possíveis duplicatas (URL compartilhada)", "1"),
                          ("Referências ambíguas", "0")]
    assert b["tabela"]["cabecalho"] == ["Obra", "Item", "Fonte", "Critério", "Identidade", "Conjuntos", "Relevância", "Ângulo",
                                        "Eixo", "Tipo de fonte", "País/escopo", "Diverge em"]
    assert b["tabela"]["linhas"][:2] == [
        ["A-5", "A-5", "Scholar", "—", "—", "A", "Alta", "Viés algorítmico", "Direitos e governança", "Artigo científico", "Brasil", ""],
        ["A-5", "W-1", "Web", "pela URL", "Junção automática pela URL", "C", "Alta", "Aplicações tecnológicas",
         "Direitos e governança", "Artigo científico", "Portugal", "Ângulo predominante, País/escopo"]]
    assert b["tabela"]["linhas"][3][3:5] == ["só pelo título", "Junção automática só pelo título"]
    assert b["tabela"]["linhas"][3][-1] == "nenhum"
    assert [l[:5] for l in b["tabela"]["linhas"][4:]] == [
        ["A-7", "A-7", "Scholar", "URL compartilhada", "Possível duplicata (URL compartilhada, não juntada)"],
        ["A-7", "A-8", "Scholar", "URL compartilhada", "Possível duplicata (URL compartilhada, não juntada)"]]
    assert [l[-1] for l in b["tabela"]["linhas"][4:]] == ["", "nenhum"]
    assert "a mesma URL não prova a mesma obra" in b["texto"][1] and "itens juntados como a mesma obra" in b["texto"][0]
    assert "diferenças de redação contam" in b["texto"][0]


def test_bloco_singular_e_nenhuma_divergencia():
    lista = _itens([_web(1, url="https://s.org/a5")], [_art(5)], {("artigo", 5): _t(), ("referencia", 1): _t()})
    assert bv.bloco_identidade(lista, RECORTES)["titulo"] == (
        "1 item da web foi juntado a artigos do Scholar; nenhum par tem classificações diferentes")


def test_bloco_avisa_ambiguidade():
    arts = [_art(5, url="https://s.org/c"), _art(6, url="https://s.org/c")]
    b = bv.bloco_identidade(_itens([_web(1, url="https://s.org/c")], arts), RECORTES)
    assert b["texto"][-1] == ("1 referência da web casa com mais de um artigo e ficou sem junção (ambiguidade): "
                              "W-1 (A-5, A-6).")


def test_bloco_vazio():
    assert bv.bloco_identidade(_itens([_web(1)], [_art(5)]), RECORTES)["titulo"] == (
        "Nenhum item da web foi juntado a um artigo do Scholar nos registros considerados")


def test_pagina_do_panorama_mostra_a_auditoria_depois_da_sobreposicao(tmp_path):
    from fastapi.testclient import TestClient
    from adaptadores.bruto_local import BrutoLocal
    from adaptadores.leitura_sqlite import LeituraPainelSQLite
    from adaptadores.repositorio_sqlite import RepositorioSQLite
    from config import consultas as C, triagem_escopo as TE, vocabulario as V
    from config.eixos_tematicos import EIXOS_EXPLORACAO
    from painel.app import Contexto, criar_app
    from test_triagem_vies import construir_vies
    construir_vies(tmp_path / "busca.db", tmp_path / "raw")
    ctx = Contexto(banco="vies", nome_banco="busca.db", somente_leitura=True, pasta_backup=tmp_path / "b", ufs=dict(C.UFS),
                   status_permitidos=set(V.STATUS), status_definicoes=dict(V.STATUS), hosts_permitidos=("testserver",),
                   conjunto_da_consulta={t.id: n for n, ts in C.CONJUNTOS_LITERATURA.items() for t in ts},
                   consultas_literatura={t.id: t.query for ts in C.CONJUNTOS_LITERATURA.values() for t in ts},
                   eixos_exploracao=dict(EIXOS_EXPLORACAO), versao_triagem_vies=TE.PROMPT_TRIAGEM_VIES_VERSAO,
                   versoes_triagem_vies=TE.VERSOES_TRIAGEM_VIES, recortes_vies=dict(TE.RECORTES_VIES))
    cli = TestClient(criar_app(LeituraPainelSQLite(tmp_path / "busca.db"), lambda: RepositorioSQLite(tmp_path / "busca.db"),
                               BrutoLocal(tmp_path), ctx))
    html = cli.get("/analises?secao=panorama").text
    assert html.index('id="vies-sobreposicao"') < html.index('id="vies-identidade"')


def test_url_compartilhada_ignora_artigos_sem_url_e_mostra_divergencia_do_grupo():
    arts = [_art(5, url=""), _art(6, url=""), _art(7, url="https://s.org/c"), _art(8, url="https://s.org/c")]
    tri = {("artigo", 7): _t(recorte="vies_algoritmico"), ("artigo", 8): _t(recorte="aplicacoes_tecnologicas")}
    r = AV.auditoria_identidade(_itens([], arts, tri))
    assert [g["artigos"] for g in r["urls_compartilhadas"]] == [["A-7", "A-8"]]
    assert r["urls_compartilhadas"][0]["divergencias"] == ["recorte"]


def test_pares_na_ordem_das_obras():
    web = [_web(2, url="https://s.org/a6"), _web(1, url="https://s.org/a5")]
    r = AV.auditoria_identidade(_itens(web, [_art(5), _art(6)]))
    assert [(p["obra"], p["web"]) for p in r["pares"]] == [("A-5", "W-1"), ("A-6", "W-2")]


def test_web_com_titulo_de_um_artigo_e_url_de_outro_vai_pela_url():
    web = [_web(1, url="https://s.org/a6", titulo="Artigo 5")]
    (p,) = AV.auditoria_identidade(_itens(web, [_art(5), _art(6)]))["pares"]
    assert (p["obra"], p["criterio"]) == ("A-6", "url")


@pytest.mark.parametrize("artigo, web, divergencias", [
    (_t(), {**_t(), "valido": 0}, list(AV.CAMPOS_AUDITADOS)),          # triagem invalida de um lado: tudo ausente na web
    (_t(recorte="vies_algoritmico"), _t(recorte=None), ["recorte"]),   # sem angulo (como na v1) de um lado
])
def test_triagem_invalida_ou_sem_angulo_num_lado(artigo, web, divergencias):
    lista = _itens([_web(1, url="https://s.org/a5")], [_art(5)], {("artigo", 5): artigo, ("referencia", 1): web})
    assert AV.auditoria_identidade(lista)["pares"][0]["divergencias"] == divergencias


def test_ambiguas_sem_repeticao_e_na_ordem_da_entrada():
    arts = [_art(6, url="https://s.org/c"), _art(5, url="https://s.org/c")]
    r = AV.auditoria_identidade(_itens([_web(1, url="https://s.org/c")], arts))
    assert r["ambiguas"][0]["artigos"] == ["A-6", "A-5"]
