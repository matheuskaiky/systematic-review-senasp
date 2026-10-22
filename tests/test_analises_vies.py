"""Análises do banco `vies` (busca de viés algorítmico) e das ferramentas de busca (qualquer banco): os cálculos sobre o
corpus, os títulos que só afirmam o que os números sustentam, a página /analises de cada banco e a legenda do fim da página."""
import sqlite3
import unicodedata

import pytest
from fastapi.testclient import TestClient

import config.settings as S
from adaptadores.bruto_local import BrutoLocal
from adaptadores.leitura_sqlite import LeituraPainelSQLite
from adaptadores.repositorio_sqlite import RepositorioSQLite
from config import consultas as C, triagem_escopo as TE, vocabulario as V
from config.eixos_tematicos import EIXOS_EXPLORACAO
from dominio import analises_ferramentas as AF, analises_vies as AV
from painel import analises_blocos_ferramentas as bf, analises_blocos_vies as bv
from painel.app import Contexto, criar_app
from test_triagem_vies import construir_vies
from test_triagem_vies_painel import _linha, _triar

CONJ = {"LA1": "A", "LA2": "A", "LB1": "B"}
TEXTOS = {"LA1": "inteligência artificial viés algorítmico", "LA2": "investigação criminal", "LB1": "discriminação ética"}


def _web(i, **kw):
    l = {"referencia_id": i, "dominio": "www.exemplo.org", "url_original": f"https://exemplo.org/{i}", "titulo": f"Título {i}",
         "data_pub": "2025-03-01", "consultas": "LA1", "conjuntos": "A", "execucoes": "r"}
    l.update(kw)
    return l


def _art(i, **kw):
    l = {"artigo_id": i, "autores_publicacao": "A - R", "ano": 2024, "titulo": f"Artigo {i}", "link": f"https://s.org/{i}",
         "consultas": "LB1", "execucoes": "r"}
    l.update(kw)
    return l


def _t(**kw):
    t = {"valido": 1, "status_bruto": "alta", "tipo_fonte": "Artigo científico", "pais_escopo": "Brasil",
         "topicos": "Reconhecimento facial; viés algorítmico", "eixo": "Direitos e governança", "confianca": "alta"}
    t.update(kw)
    return t


def _itens(web=(), arts=(), tri=None):
    return AV.itens(list(web), list(arts), CONJ, tri or {})


# ---------- itens ----------
@pytest.mark.parametrize("tipo, grupo", [
    ("Artigo científico", "Literatura científica"), ("Reportagem / literatura cinzenta", "Literatura cinzenta"),
    ("Norma / fonte primária", "Fonte primária"), ("Solução tecnológica / produto / literatura cinzenta", "Literatura cinzenta"),
    (None, None), ("", None),
])
def test_grupo_do_tipo(tipo, grupo):
    assert AV.grupo_do_tipo(tipo) == grupo


def test_itens_juntam_as_fontes_com_a_triagem_valida_e_so_as_consultas_configuradas():
    w1, w2, a7 = _itens([_web(1, consultas="LA1,ZZ9"), _web(2)], [_art(7, consultas="LB1,LA2")],
                        {("referencia", 1): _t(), ("referencia", 2): _t(valido=0), ("artigo", 7): _t(eixo=None, topicos=" a ;; b ")})
    assert (w1["id"], w1["fonte"], w1["ano"], w1["consultas"], w1["conjuntos"], w1["relevancia"]) == ("W-1", "Web", 2025, ["LA1"], ["A"], "alta")
    assert (w2["relevancia"], w2["tipo_fonte"], w2["topicos"]) == (None, None, [])
    assert (a7["id"], a7["fonte"], a7["ano"], a7["conjuntos"], a7["topicos"], a7["eixo"]) == ("A-7", "Scholar", 2024, ["A", "B"], ["a", "b"], None)


@pytest.mark.parametrize("ano, esperado", [(2024, 2024), (None, None), ("2024", None), (True, None)])
def test_ano_do_artigo_so_quando_inteiro(ano, esperado):
    assert _itens(arts=[_art(1, ano=ano)])[0]["ano"] == esperado


# ---------- obras ----------
@pytest.mark.parametrize("a, b, mesma", [
    ("Ética e IA", "ETICA  e ia!", True), ("研究", "研究", True), ("研究", "論文", False), ("研究 AI", "論文 AI", False),
    ("Análise", "Analise", True), ("___", "___", False), ("—", "—", False), ("", "", False), (None, None, False),
    ("Título 1", "Título 2", False), ("Ｔítulo", "Titulo", True),          # forma de largura total vira latina (NFKD)
    ("Æther", "ther", False), ("Søren", "Sren", False), ("Łódź", "odz", False),   # letras latinas sem forma ASCII ficam
    ("Straße", "Strasse", True),                                              # casefold: a mesma palavra
])
def test_chave_de_titulo_em_qualquer_alfabeto(a, b, mesma):
    ka, kb = AV.chave_titulo(a), AV.chave_titulo(b)
    assert (ka is not None and ka == kb) is mesma


def test_titulos_so_em_outro_alfabeto_nao_juntam_obras_diferentes():
    lista = _itens([_web(1, titulo="研究", url_original="https://x.org/1")], [_art(9, titulo="論文", link="https://y.org/9")])
    assert AV.repetidos_na_web(lista) == set() and len(AV.obras(lista)) == 2
    igual = _itens([_web(1, titulo="研究", url_original="https://x.org/1")], [_art(9, titulo="研究", link="https://y.org/9")])
    assert AV.repetidos_na_web(igual) == {"W-1"}
@pytest.mark.parametrize("web, repetido", [
    (_web(1, url_original="https://www.s.org/9/"), True),         # mesma URL normalizada
    (_web(1, titulo="  ARTIGO 9 "), True),                         # mesmo título normalizado
    (_web(1, titulo="—"), False), (_web(1, titulo="..."), False),  # título sem letra nem número não identifica a obra
    (_web(1, titulo="___"), False), (_web(1, titulo="_ - _"), False),
    (_web(1), False),
])
def test_obra_repetida_na_web(web, repetido):
    lista = _itens([web], [_art(9), _art(10, titulo="—"), _art(11, titulo="___", link="")])
    assert (AV.repetidos_na_web(lista) == {"W-1"}) is repetido
    assert len(AV.obras(lista)) == (3 if repetido else 4)


def test_resumo():
    lista = _itens([_web(1, url_original="https://s.org/9"), _web(2)], [_art(9), _art(10)],
                   {("referencia", 1): _t(), ("referencia", 2): _t(status_bruto="fora_do_escopo"), ("artigo", 9): _t()})
    assert AV.resumo(lista) == {"n_itens": 4, "n_web": 2, "n_scholar": 2, "n_obras": 3, "n_em_ambas_fontes": 1,
                                "n_ambas_por_url": 1, "n_ambas_so_por_titulo": 0, "n_triados": 3, "n_alta": 2, "n_fora": 1}


def test_sobreposicao_separa_url_e_so_titulo():
    lista = _itens([_web(1, url_original="https://s.org/9"), _web(2, titulo="Artigo 10"), _web(3, url_original="https://s.org/11",
                                                                                              titulo="Artigo 11")],
                   [_art(9), _art(10), _art(11)])
    r = AV.resumo(lista)
    assert (r["n_em_ambas_fontes"], r["n_ambas_por_url"], r["n_ambas_so_por_titulo"]) == (3, 2, 1)   # URL e título: conta pela URL


def test_relevancia_por_fonte_e_no_escopo():
    lista = _itens([_web(1), _web(2)], [_art(5), _art(6)], {("referencia", 1): _t(), ("referencia", 2): _t(status_bruto="fora_do_escopo"),
                                                            ("artigo", 5): _t(status_bruto="baixa")})
    assert AV.relevancia_por_fonte(lista) == {
        "Web": {"alta": 1, "media": 0, "baixa": 0, "fora_do_escopo": 1, "sem triagem válida": 0},
        "Scholar": {"alta": 0, "media": 0, "baixa": 1, "fora_do_escopo": 0, "sem triagem válida": 1}}
    assert [i["id"] for i in AV.no_escopo(lista)] == ["W-1", "A-5"]


@pytest.mark.parametrize("valores, ordem, esperado", [
    (["b", "a", "b"], (), [("b", 2), ("a", 1)]), (["b", "a"], (), [("a", 1), ("b", 1)]),
    (["a"], ("x", "a"), [("a", 1), ("x", 0)]), ([], ("x",), [("x", 0)]), ([], (), []),
])
def test_contagem(valores, ordem, esperado):
    assert AV.contagem(valores, ordem) == esperado


# ---------- conteúdo: cada obra uma vez ----------
def test_conteudo_conta_cada_obra_uma_vez_e_eixos_vazios_aparecem():
    lista = _itens([_web(1, titulo="Artigo 9", url_original="https://x.org/1")], [_art(9), _art(10)],
                   {("referencia", 1): _t(), ("artigo", 9): _t(), ("artigo", 10): _t(eixo=None)})
    assert AV.tipos(lista) == [("Artigo científico", 2)]
    assert AV.eixos(lista, ("Direitos e governança", "Forense digital e deepfakes")) == [
        ("Direitos e governança", 1), ("Forense digital e deepfakes", 0), ("Sem eixo", 1)]
    assert AV.tipos_por_grupo_e_fonte(lista) == {("Literatura científica", "Web"): 1, ("Literatura científica", "Scholar"): 2}


def test_topicos_separam_as_palavras_da_busca_e_juntam_variantes():
    nfd = unicodedata.normalize("NFD", "reconhecimento facial")
    lista = _itens([_web(i) for i in range(1, 5)], [], {
        ("referencia", 1): _t(topicos=f"Reconhecimento facial; {nfd}; Viés algorítmico; IA"),
        ("referencia", 2): _t(topicos="reconhecimento  facial; Vieses algorítmicos; ia"),
        ("referencia", 3): _t(topicos="Ética"), ("referencia", 4): _t(topicos="zeta", status_bruto="fora_do_escopo")})
    proprios, da_busca = AV.topicos(lista, TEXTOS.values())
    assert proprios == [("IA", 2), ("Reconhecimento facial", 2)]          # empate: ordem alfabética do rótulo
    assert da_busca == [("Viés algorítmico", 2), ("Ética", 1)]            # variante plural junta; ética está em LB1
    assert AV.topicos(lista, TEXTOS.values(), n=1)[0] == [("IA", 2)]


def test_anos_e_por_ano():
    lista = _itens([_web(1, data_pub=None), _web(2, data_pub="2023-01-01")], [_art(5, ano=2025), _art(6, ano=None), _art(7, ano=2025)],
                   {("referencia", 1): _t(), ("referencia", 2): _t(), ("artigo", 5): _t(), ("artigo", 6): _t(), ("artigo", 7): _t()})
    assert AV.anos_scholar(lista) == [(2025, 2)]
    assert AV.por_ano(lista) == {2023: {"Web": 1, "Scholar": 0}, 2025: {"Web": 0, "Scholar": 2}, "Sem ano": {"Web": 1, "Scholar": 1}}
    assert AV.por_ano([]) == {}


@pytest.mark.parametrize("paises, esperado", [
    (["Brasil", "brasil", "EUA"], (2, 3)), (["Brasil / EUA", "EUA / Brasil", "EUA"], (2, 3)),
    (["Indeterminado", "Brasil"], (1, 1)), (["Indeterminado"], (0, 0)), (["Brasileiro"], (0, 1)),
])
def test_brasil_por_qualquer_parte_e_sem_indeterminado(paises, esperado):
    lista = _itens([_web(i) for i in range(1, len(paises) + 1)], [], {("referencia", i + 1): _t(pais_escopo=p) for i, p in enumerate(paises)})
    assert AV.brasil(lista) == esperado


def test_paises_juntam_maiusculas_e_espacos():
    lista = _itens([_web(1), _web(2), _web(3)], [], {("referencia", 1): _t(pais_escopo="Brasil"),
                                                     ("referencia", 2): _t(pais_escopo="brasil"), ("referencia", 3): _t(pais_escopo=None)})
    assert AV.paises(lista) == [("Brasil", 2)]


# ---------- consultas, conjuntos, sites ----------
def test_consultas():
    lista = _itens([_web(1), _web(2, consultas="LA1,LB1", conjuntos="A,B")], [_art(5), _art(6, consultas="LA2")],
                   {("referencia", 1): _t(), ("referencia", 2): _t(status_bruto="media"), ("artigo", 5): _t(status_bruto="fora_do_escopo")})
    assert AV.consultas(lista, {"A": ["LA1", "LA2"], "B": ["LB1"]}) == [
        {"conjunto": "A", "consulta": "LA1", "web": 2, "scholar": 0, "exclusivos": 1, "triados": 2, "alta": 1, "elegiveis": 2, "fora": 0},
        {"conjunto": "A", "consulta": "LA2", "web": 0, "scholar": 1, "exclusivos": 1, "triados": 0, "alta": 0, "elegiveis": 0, "fora": 0},
        {"conjunto": "B", "consulta": "LB1", "web": 1, "scholar": 1, "exclusivos": 1, "triados": 2, "alta": 0, "elegiveis": 1, "fora": 1}]


def test_conjuntos_so_a_e_b():
    lista = _itens([_web(1), _web(2, consultas="LA1,LB1"), _web(3, consultas="ZZ9")], [_art(5), _art(6, consultas="LA2")])
    assert AV.conjuntos(lista) == {"Web": {"Só A": 1, "Só B": 0, "A e B": 1}, "Scholar": {"Só A": 1, "Só B": 1, "A e B": 0}}


@pytest.mark.parametrize("dominio, registravel", [
    ("new.scielo.br", "scielo.br"), ("scielo.br", "scielo.br"), ("pt.scribd.com", "scribd.com"), ("www.exemplo.org", "exemplo.org"),
    ("basedeconhecimento.cgu.gov.br", "cgu.gov.br"), ("ibccrim.org.br", "ibccrim.org.br"), ("publicacoes.ibccrim.org.br", "ibccrim.org.br"),
    ("LOCALHOST", "localhost"), ("", ""), ("alpha.co.uk", "alpha.co.uk"), ("www.beta.co.uk", "beta.co.uk"),
    ("lse.ac.uk", "lse.ac.uk"), ("news.abc.com.au", "abc.com.au"), ("x.unknown.zz", "unknown.zz"),
])
def test_dominio_registravel(dominio, registravel):
    assert AV.dominio_registravel(dominio) == registravel


def test_dominios_so_web_no_escopo():
    lista = _itens([_web(1, dominio="new.scielo.br"), _web(2, dominio="scielo.br"), _web(3, dominio="jus.com.br")], [],
                   {("referencia", 1): _t(), ("referencia", 2): _t(), ("referencia", 3): _t(status_bruto="fora_do_escopo")})
    assert AV.dominios(lista) == ([("scielo.br", 2)], 1)


# ---------- ferramentas ----------
LEITURA = {"chamadas": [
    {"etapa": "triagem_escopo", "provedor": "gemini:m", "chamadas": 4, "ok": 3, "custo_usd": 0.2, "tokens_entrada": 10, "tokens_saida": 5},
    {"etapa": "busca_academica", "provedor": "serpapi_scholar", "chamadas": 2, "ok": 2, "custo_usd": 0, "tokens_entrada": 0, "tokens_saida": 0},
    {"etapa": "busca_literatura", "provedor": "perplexity_search", "chamadas": 2, "ok": 2, "custo_usd": 0.01, "tokens_entrada": 0, "tokens_saida": 0}],
    "resultados": {"busca_academica": 40, "busca_literatura": 40}, "itens": {"busca_academica": 30, "busca_literatura": 10},
    "creditos": {"serpapi_scholar": 2.0}}


def test_linhas_das_ferramentas_em_ordem_e_com_razoes():
    linhas = AF.linhas(LEITURA)
    assert [(l["etapa"], l["ferramenta"]) for l in linhas] == [("busca_academica", "serpapi_scholar"),
                                                               ("busca_literatura", "perplexity_search"), ("triagem_escopo", "gemini:m")]
    sch, web, tri = linhas
    assert (sch["resultados_por_chamada"], sch["itens_por_resultado"], sch["custo_por_item"], sch["creditos_por_item"]) == (20, 0.75, None, 2 / 30)
    assert (web["custo_por_item"], web["creditos"]) == (0.001, None)
    assert (tri["busca"], tri["falhas"], tri["resultados"], tri["itens_por_resultado"]) == (False, 1, None, None)
    assert AF.total_custo(linhas) == pytest.approx(0.21)
    assert AF.linhas({"chamadas": [], "resultados": {}, "itens": {}, "creditos": {}}) == []


def test_relevancia_por_ferramenta():
    lista = _itens([_web(1), _web(2)], [_art(5)], {("referencia", 1): _t(), ("referencia", 2): _t(status_bruto="baixa"), ("artigo", 5): _t()})
    linhas = {l["ferramenta"]: l for l in AV.relevancia_por_ferramenta(AF.linhas({**LEITURA, "itens": {"busca_academica": 1, "busca_literatura": 2}}), lista)}
    assert set(linhas) == {"serpapi_scholar", "perplexity_search"}
    assert (linhas["perplexity_search"]["elegiveis"], linhas["perplexity_search"]["custo_por_elegivel"]) == (1, 0.01)
    assert (linhas["serpapi_scholar"]["elegiveis"], linhas["serpapi_scholar"]["creditos_por_elegivel"]) == (1, 2.0)


def test_titulos_das_ferramentas():
    linhas = AF.linhas(LEITURA)
    assert bf.bloco_ferramentas_busca(linhas)["titulo"] == "A busca acadêmica (serpapi_scholar) trouxe mais itens únicos: 30 em 2 chamadas"
    assert bf.bloco_custos(linhas)["titulo"] == "O custo registrado foi US$ 0,21; a maior parte (95%) na triagem de escopo"
    assert bf.bloco_ferramentas_busca([])["titulo"] == "Nenhuma busca registrada nas execuções do relatório"
    assert bf.bloco_custos([l for l in linhas if l["etapa"] == "busca_academica"])["titulo"] == "Nenhuma chamada com custo em dólar registrado"


# ---------- títulos que só afirmam o que os números sustentam ----------
def _com(n_web=0, n_art=0, **campos):
    web = [_web(i) for i in range(1, n_web + 1)]
    arts = [_art(100 + i) for i in range(1, n_art + 1)]
    tri = {("referencia", i): _t(**campos) for i in range(1, n_web + 1)} | {("artigo", 100 + i): _t(**campos) for i in range(1, n_art + 1)}
    return _itens(web, arts, tri)


@pytest.mark.parametrize("lista, titulo", [
    (_com(2, 0, tipo_fonte="Reportagem / literatura cinzenta"), "A literatura cinzenta vem mais da web: 2 de 2 itens"),
    (_com(1, 1, tipo_fonte="Reportagem / literatura cinzenta"), "A literatura cinzenta se divide entre as fontes (2 itens)"),
    (_com(1, 1), "Nenhum item de literatura cinzenta no escopo"),
    (_com(0, 0), "Sem tipos de fonte para mostrar"),
])
def test_titulo_dos_grupos(lista, titulo):
    assert bv.bloco_grupos(lista)["titulo"] == titulo


@pytest.mark.parametrize("lista, titulo", [
    (_com(1, 0), "Obras no escopo por eixo de exploração"),          # um eixo só: sem "mais" nem "menos"
    (_itens([_web(1), _web(2), _web(3)], [], {("referencia", 1): _t(), ("referencia", 2): _t(), ("referencia", 3): _t(eixo="Biometria e vigilância")}),
     "O eixo mais coberto é Direitos e governança (2 itens); o menos coberto, Biometria e vigilância (1 item)"),
    (_com(0, 0), "Sem eixos para mostrar"),
])
def test_titulo_dos_eixos(lista, titulo):
    assert bv.bloco_eixos(lista, ())["titulo"] == titulo


def test_eixos_sem_obra_aparecem_como_lacuna():
    b = bv.bloco_eixos(_com(1, 0), tuple(EIXOS_EXPLORACAO))
    assert b["titulo"].startswith("O eixo mais coberto é Direitos e governança (1 item); o menos coberto,")
    assert b["texto"][0].startswith("Sem nenhuma obra: ")


@pytest.mark.parametrize("anos, titulo", [
    ([2025, 2026, 2026, 2020], "A maior parte dos artigos é recente: 3 de 4 com ano são de 2025 ou 2026"),
    ([2020, 2021, 2026], "Artigos do Scholar por ano de publicação"),
    ([], "Sem artigos do Scholar com ano conhecido"),
])
def test_titulo_dos_anos_usa_so_o_scholar(anos, titulo):
    lista = _itens([_web(1, data_pub="2026-01-01")], [_art(i, ano=a) for i, a in enumerate(anos, 1)],
                   {("referencia", 1): _t()} | {("artigo", i): _t() for i in range(1, len(anos) + 1)})
    assert bv.bloco_anos(lista, 2026)["titulo"] == titulo


@pytest.mark.parametrize("relevancias, titulo", [
    ({"LA1": "alta", "LA2": "alta", "LB1": "fora_do_escopo"}, "A consulta com menor parte elegível é LB1: 0 de 1 item, 1 fora do escopo"),
    ({"LA1": "fora_do_escopo", "LA2": "fora_do_escopo", "LB1": "alta"}, "As consultas com menor parte elegível, empatadas, são LA1, LA2"),
    ({"LA1": "alta", "LA2": "alta", "LB1": "alta"}, "Todas as consultas têm a mesma parte elegível"),
])
def test_titulo_das_consultas(relevancias, titulo):
    web = [_web(i, consultas=c) for i, c in enumerate(relevancias, 1)]
    lista = _itens(web, [], {("referencia", i): _t(status_bruto=r) for i, r in enumerate(relevancias.values(), 1)})
    assert bv.bloco_consultas(lista, {"A": ["LA1", "LA2"], "B": ["LB1"]}, TEXTOS)["titulo"] == titulo


@pytest.mark.parametrize("consultas, titulo", [
    (["LA1", "LB1", "LA1", "LB1", "LA1", "LA1,LB1"], "Os conjuntos A e B se complementam: 1 de 6 itens aparecem nos dois"),
    (["LA1,LB1", "LA1"], "1 de 2 itens aparecem nos dois conjuntos"),
])
def test_titulo_dos_conjuntos(consultas, titulo):
    assert bv.bloco_conjuntos(_itens([_web(i, consultas=c) for i, c in enumerate(consultas, 1)]))["titulo"] == titulo


@pytest.mark.parametrize("dominios, copias", [(["pt.scribd.com", "x.org"], True), (["x.org"], False)])
def test_aviso_de_repositorio_de_copias_so_quando_aparece(dominios, copias):
    lista = _itens([_web(i, dominio=d) for i, d in enumerate(dominios, 1)], [], {("referencia", i): _t() for i in range(1, len(dominios) + 1)})
    assert bool(bv.bloco_dominios(lista)["texto"]) is copias


def test_aviso_quando_uma_fonte_tem_mais_de_uma_ferramenta():
    lista = _itens([_web(1)], [], {("referencia", 1): _t()})
    duas = {**LEITURA, "chamadas": LEITURA["chamadas"] + [dict(LEITURA["chamadas"][2], provedor="outra_busca")]}
    texto = bv.bloco_ferramentas_relevancia(AV.relevancia_por_ferramenta(AF.linhas(duas), lista))["texto"]
    assert texto == ["A fonte Web tem mais de uma ferramenta: os resultados não são atribuídos a cada uma, os itens se repetem em "
                     "cada linha e a comparação entre elas não é causal."]
    assert bv.bloco_ferramentas_relevancia(AV.relevancia_por_ferramenta(AF.linhas(LEITURA), lista))["texto"] == []


def test_complemento_das_fontes_so_abaixo_do_limiar():
    pouco = {"n_itens": 10, "n_web": 5, "n_scholar": 5, "n_obras": 9, "n_em_ambas_fontes": 1, "n_ambas_por_url": 1,
             "n_ambas_so_por_titulo": 0, "n_triados": 10, "n_alta": 5, "n_fora": 0}
    muito = {**pouco, "n_obras": 6, "n_em_ambas_fontes": 4}
    assert bv.bloco_sobreposicao(pouco)["texto"] and not bv.bloco_sobreposicao(muito)["texto"]
    assert bv.bloco_sobreposicao(muito)["titulo"] == "6 obras distintas: 4 aparecem nas duas fontes"
    so_titulo = bv.bloco_sobreposicao({**muito, "n_ambas_por_url": 3, "n_ambas_so_por_titulo": 1})["texto"]
    assert so_titulo == ["Antes de citar a sobreposição, confira à mão os pares achados só pelo título: títulos comuns podem "
                         "juntar obras diferentes."]


# ---------- leitura das ferramentas ----------
def test_leitura_das_ferramentas_no_banco_vies(tmp_path):
    construir_vies(tmp_path / "busca.db", tmp_path / "raw")
    d = LeituraPainelSQLite(tmp_path / "busca.db").analise_ferramentas()
    assert {(c["etapa"], c["provedor"], c["chamadas"]) for c in d["chamadas"]} == {("busca_literatura", "falsa", 3), ("busca_academica", "falso", 1)}
    assert (d["resultados"], d["itens"]) == ({"busca_web": 0, "busca_academica": 1, "busca_literatura": 6},
                                              {"busca_web": 0, "busca_academica": 1, "busca_literatura": 4})


def test_leitura_das_ferramentas_em_banco_sem_tabelas(tmp_path):
    sqlite3.connect(tmp_path / "vazio.db").execute("CREATE TABLE x (a)")
    assert LeituraPainelSQLite(tmp_path / "vazio.db").analise_ferramentas() == {"chamadas": [], "resultados": {}, "itens": {}, "creditos": {}}


# ---------- página ----------
def _cli(banco, tmp_path, nome="vies"):
    ctx = Contexto(banco=nome, nome_banco="busca.db", somente_leitura=True, pasta_backup=tmp_path / "b", ufs=dict(C.UFS),
                   status_permitidos=set(V.STATUS), status_definicoes=dict(V.STATUS), hosts_permitidos=("testserver",),
                   termos={t.id: t.query for t in S.termos_do_banco(nome)},
                   conjunto_da_consulta={t.id: n for n, ts in C.CONJUNTOS_LITERATURA.items() for t in ts},
                   consultas_literatura={t.id: t.query for ts in C.CONJUNTOS_LITERATURA.values() for t in ts},
                   eixos_exploracao=dict(EIXOS_EXPLORACAO), versao_triagem_vies=TE.PROMPT_TRIAGEM_VIES_VERSAO)
    return TestClient(criar_app(LeituraPainelSQLite(banco), lambda: RepositorioSQLite(banco), BrutoLocal(tmp_path), ctx))


@pytest.fixture
def banco(tmp_path):
    construir_vies(tmp_path / "busca.db", tmp_path / "raw")
    con = sqlite3.connect(tmp_path / "busca.db")
    refs = [r[0] for r in con.execute("SELECT referencia_id FROM referencias_web ORDER BY 1")]
    arts = [r[0] for r in con.execute("SELECT artigo_id FROM artigos ORDER BY 1")]
    _triar(tmp_path / "busca.db", [_linha("referencia", i) for i in refs] + [_linha("artigo", i, status_bruto="fora_do_escopo",
                                                                                         status="excluido") for i in arts])
    return tmp_path / "busca.db"


ABAS = ["panorama", "ferramentas", "tipos", "temas", "tempo", "consultas", "web"]


def test_no_banco_vies_so_as_abas_da_busca_de_vies_com_legenda(banco, tmp_path):
    cli = _cli(banco, tmp_path)
    for secao in ABAS:
        r = cli.get(f"/analises?secao={secao}")
        assert r.status_code == 200, secao
        for chave in ABAS:
            assert f'href="/analises?secao={chave}"' in r.text
        assert 'href="/analises?secao=adocao"' not in r.text and "Kappa de Cohen" not in r.text
        assert '<h2 id="t-legenda">Legenda</h2>' in r.text and "<td><code>LB5</code></td><td>B</td>" in r.text
        assert "<dt><code>falsa</code></dt><dd>falsa; usada em: busca de literatura na web.</dd>" in r.text
    for secao in ("visao", "adocao", "auditoria", "xyz"):
        assert cli.get(f"/analises?secao={secao}").status_code == 404
    assert '<a href="/analises?secao=panorama" aria-current="page">' in cli.get("/analises").text


def test_panorama_mostra_os_cartoes_e_a_conclusao(banco, tmp_path):
    html = _cli(banco, tmp_path).get("/analises?secao=panorama").text
    assert "<strong>5</strong><span>obras distintas</span>" in html and "<strong>4</strong><span>referências da web</span>" in html
    assert "<strong>1</strong><span>fora do escopo</span>" in html
    assert "Os números descrevem o corpus recuperado por estas buscas (em português, nestas fontes), não a literatura em geral." in html
    assert "Elegíveis (relevância alta ou média): 100% das referências da web e 0% dos artigos do Scholar" in html


def test_banco_real_ganha_ferramentas_e_legenda_com_os_termos(copiar_demo, tmp_path):
    demo, _ = copiar_demo("analises_real")
    cli = _cli(demo, tmp_path, nome="real")
    busca = cli.get("/analises?secao=busca").text
    assert 'id="t-ferramentas-busca"' in busca and 'id="t-ferramentas-custos"' in busca
    visao = cli.get("/analises").text
    assert 'href="/analises?secao=adocao"' in visao and '<h2 id="t-legenda">Legenda</h2>' in visao
    assert "Códigos dos termos de busca" in visao and "<td><code>T01</code></td>" in visao and "LB5" not in visao
    assert cli.get("/analises?secao=panorama").status_code == 404


def test_banco_vies_vazio_abre_todas_as_abas(tmp_path):
    RepositorioSQLite(tmp_path / "vazio.db").fechar()
    cli = _cli(tmp_path / "vazio.db", tmp_path)
    textos = {s: cli.get(f"/analises?secao={s}") for s in ABAS}
    assert all(r.status_code == 200 for r in textos.values())
    assert "Sem triagem da busca de viés algorítmico" in textos["panorama"].text
    assert "Nenhuma busca registrada nas execuções do relatório" in textos["ferramentas"].text
