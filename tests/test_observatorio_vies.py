"""Observatorio do banco `vies` (dominio): a projecao de obras (cada obra uma vez, com os seus membros web e Scholar, a
uniao dos conjuntos, o angulo da obra e as divergencias entre membros), a leitura estrita dos filtros GET, a filtragem sobre
obras (nunca sobre membros), a ordem da lista, a paginacao e as agregacoes das perspectivas, com a regra de que cada celula
da matriz tem exatamente as obras da lista filtrada correspondente."""
import copy

import pytest

from dominio import analises_vies as AV
from dominio import observatorio_vies as OV

CONJ = {"LA1": "A", "LA2": "A", "LB1": "B", "LC1": "C"}
NOMES = ("A", "B", "C")
RECORTES = ("vies_algoritmico", "aplicacoes_tecnologicas")
V, AP = RECORTES
EIXOS = ("E1", "E2", "E3")


def _web(i, consultas="LA1", url=None, titulo=None):
    return {"referencia_id": i, "dominio": "exemplo.org", "url_original": f"https://exemplo.org/w{i}" if url is None else url,
            "titulo": titulo or f"Página {i}", "data_pub": "2025-03-01", "consultas": consultas, "conjuntos": "", "execucoes": "r"}


def _art(i, consultas="LB1", url=None, titulo=None):
    return {"artigo_id": i, "autores_publicacao": "A - R", "ano": 2024, "titulo": titulo or f"Artigo {i}",
            "link": f"https://s.org/a{i}" if url is None else url, "consultas": consultas, "execucoes": "r"}


def _t(relevancia="alta", recorte=V, eixo="E1", tipo="Artigo científico", valido=1, pais="Brasil", topicos="x"):
    return {"valido": valido, "status_bruto": relevancia, "tipo_fonte": tipo, "pais_escopo": pais, "topicos": topicos,
            "eixo": eixo, "confianca": "alta", "recorte": recorte}


def _itens(web=(), arts=(), tri=None):
    return AV.itens(list(web), list(arts), CONJ, tri or {})


def _corpus():
    """Seis obras com tudo o que os filtros distinguem:
    W-1 so web, A, alta, vies, E1 | A-2 so Scholar, C, media, aplicacoes, E2 |
    A-3 web (W-3, conjunto A, aplicacoes) + Scholar (C, vies) juntados pela URL: A+C, alta, vies, divergem no angulo |
    A-4 so Scholar, B, baixa, vies | W-5 so web, sem conjunto, alta, sem angulo, sem eixo |
    A-6 so Scholar, A+B+C, fora do escopo."""
    web = [_web(1, "LA1"), _web(3, "LA2", url="https://s.org/a3"), _web(5, "LX9")]
    arts = [_art(2, "LC1"), _art(3, "LC1"), _art(4, "LB1"), _art(6, "LA1,LB1,LC1")]
    tri = {("referencia", 1): _t("alta", V, "E1"), ("artigo", 2): _t("media", AP, "E2"),
           ("referencia", 3): _t("alta", AP, "E1"), ("artigo", 3): _t("alta", V, "E1"),
           ("artigo", 4): _t("baixa", V, "E2"), ("referencia", 5): _t("alta", None, None),
           ("artigo", 6): _t("fora_do_escopo", V, "E3")}
    return _itens(web, arts, tri)


def _ids(obras):
    return [o["id"] for o in obras]


def _filtros(**k):
    base = {"perspectiva": "integrada", "universo": "elegiveis", "combinacao": None, "conjunto": None, "fonte": None,
            "angulo": None, "eixo": None}
    base.update(k)
    return base


# ---------- constantes ----------
def test_constantes():
    assert OV.FILTROS == ("perspectiva", "universo", "combinacao", "conjunto", "fonte", "angulo", "eixo")
    assert OV.PERSPECTIVAS == (("integrada", "Integrada"), ("vies", "Viés algorítmico e discriminação"),
                               ("tecnologias", "Aplicações tecnológicas de IA"))
    assert OV.ANGULO_DA_PERSPECTIVA == {"vies": V, "tecnologias": AP}
    assert OV.UNIVERSOS == (("elegiveis", "Relevância alta ou média"), ("todas", "Todas as obras"))
    assert OV.FONTES == (("web", "Achada na web"), ("scholar", "Achada no Scholar"), ("so_web", "Só na web"),
                         ("so_scholar", "Só no Scholar"), ("ambas", "Na web e no Scholar"))
    assert (OV.SEM_CONJUNTO, OV.SEM_EIXO, OV.TAMANHO_PAGINA) == ("nenhum", "sem_eixo", 50)


def test_angulos_da_perspectiva_sao_os_recortes_configurados():
    from config.triagem_escopo import RECORTES_VIES
    assert tuple(OV.ANGULO_DA_PERSPECTIVA.values()) == tuple(RECORTES_VIES)


@pytest.mark.parametrize("nomes, esperado", [
    (("A", "B", "C"), [("A", "Só A"), ("B", "Só B"), ("C", "Só C"), ("A+B", "A + B"), ("A+C", "A + C"), ("B+C", "B + C"),
                       ("A+B+C", "A + B + C"), ("nenhum", "Sem conjunto")]),
    (("A",), [("A", "Só A"), ("nenhum", "Sem conjunto")]),
    ((), [("nenhum", "Sem conjunto")]),
])
def test_combinacoes(nomes, esperado):
    assert OV.combinacoes(nomes) == esperado
    assert [r for _, r in OV.combinacoes(nomes)] == AV.combinacoes(nomes) + [AV.SEM_CONJUNTO]


# ---------- projecao ----------
def test_projecao_vazia():
    assert OV.projecao([], NOMES) == ([], [])


def test_projecao_cada_obra_uma_vez_com_membros_fontes_e_combinacao():
    obras, ambiguas = OV.projecao(_corpus(), NOMES)
    assert ambiguas == []
    assert _ids(obras) == ["W-1", "W-5", "A-2", "A-3", "A-4", "A-6"]        # a ordem de `obras_com_origem`
    por = {o["id"]: o for o in obras}
    assert por["A-3"]["membros"] == [("Scholar", "A-3"), ("Web", "W-3")]
    assert [por[i]["fontes"] for i in ("W-1", "A-2", "A-3")] == [("Web",), ("Scholar",), ("Web", "Scholar")]
    assert {i: por[i]["combinacao"] for i in por} == {"W-1": "A", "W-5": "nenhum", "A-2": "C", "A-3": "A+C", "A-4": "B",
                                                     "A-6": "A+B+C"}
    assert por["A-3"]["conjuntos_da_obra"] == ["A", "C"] and por["A-3"]["conjuntos"] == ["C"]   # o do artigo fica como era
    assert (por["A-3"]["relevancia"], por["A-3"]["recorte"]) == ("alta", V)                    # vale o artigo do Scholar


def test_projecao_tem_todas_as_chaves_da_obra_e_as_novas():
    lista = _corpus()
    obras, _ = OV.projecao(lista, NOMES)
    origem, _ = AV.obras_com_origem(lista)
    for o, base in zip(obras, origem):
        assert {k: o[k] for k in base} == base
        assert set(o) == set(base) | {"fontes", "combinacao", "divergencias", "possivel_duplicata"}


@pytest.mark.parametrize("tri_web, tri_art, divergencias", [
    (_t("alta", V, "E1"), _t("alta", V, "E1"), []),
    (_t("alta", AP, "E1"), _t("alta", V, "E1"), ["recorte"]),
    (_t("media", AP, "E2"), _t("alta", V, "E1"), ["relevancia", "recorte", "eixo"]),
    (_t("alta", V, "E1", pais="Brasil / SP"), _t("alta", V, "E1"), ["pais"]),
    (_t("alta", V, "E1", tipo="Relatório técnico / literatura cinzenta"), _t("alta", V, "E1"), ["tipo_fonte"]),
    (None, _t("alta", V, "E1"), ["relevancia", "recorte", "eixo", "tipo_fonte", "pais"]),   # ausencia conta como valor
    (_t("alta", V, "E1", valido=0), _t("alta", V, "E1"), ["relevancia", "recorte", "eixo", "tipo_fonte", "pais"]),
])
def test_divergencias_entre_membros_na_ordem_dos_campos_auditados(tri_web, tri_art, divergencias):
    tri = {("artigo", 1): tri_art}
    if tri_web is not None:
        tri[("referencia", 1)] = tri_web
    obras, _ = OV.projecao(_itens([_web(1, url="https://s.org/a1")], [_art(1)], tri), NOMES)
    assert len(obras) == 1 and obras[0]["divergencias"] == divergencias


def test_obra_de_um_membro_so_nao_diverge():
    obras, _ = OV.projecao(_corpus(), NOMES)
    assert {o["id"]: o["divergencias"] for o in obras if o["id"] != "A-3"} == {i: [] for i in ("W-1", "W-5", "A-2", "A-4", "A-6")}


def test_divergencia_de_varios_membros_web_e_a_uniao():
    lista = _itens([_web(1, url="https://s.org/a1"), _web(2, titulo="Artigo 1", url="https://outro.org/x")], [_art(1)],
                   {("artigo", 1): _t("alta", V, "E1"), ("referencia", 1): _t("alta", V, "E2"),
                    ("referencia", 2): _t("media", V, "E1")})
    obras, _ = OV.projecao(lista, NOMES)
    assert len(obras) == 1 and obras[0]["membros"] == [("Scholar", "A-1"), ("Web", "W-1"), ("Web", "W-2")]
    assert obras[0]["divergencias"] == ["relevancia", "eixo"]


def test_possivel_duplicata_pela_url_compartilhada_entre_artigos():
    lista = _itens([], [_art(1, url="https://x.org/p"), _art(2, url="https://x.org/p"), _art(3), _art(4, url=""),
                        _art(5, url="")], {})
    obras, _ = OV.projecao(lista, NOMES)
    assert {o["id"]: o["possivel_duplicata"] for o in obras} == {"A-1": True, "A-2": True, "A-3": False, "A-4": False,
                                                                 "A-5": False}


def test_referencia_ambigua_fica_fora_das_obras():
    lista = _itens([_web(1, titulo="Mesmo título", url="https://w.org/1")],
                   [_art(1, titulo="Mesmo título"), _art(2, titulo="Mesmo título")], {})
    obras, ambiguas = OV.projecao(lista, NOMES)
    assert _ids(obras) == ["A-1", "A-2"] and ambiguas == ["W-1"]
    assert all(o["membros"] == [("Scholar", o["id"])] for o in obras)


def test_projecao_nao_muda_a_entrada_nem_compartilha_listas():
    lista = _corpus()
    antes = copy.deepcopy(lista)
    obras, _ = OV.projecao(lista, NOMES)
    assert lista == antes
    for o in obras:
        o["conjuntos_da_obra"].append("Z")
        o["topicos"].append("Z")
        o["divergencias"].append("Z")
    assert lista == antes


def test_contagem_por_combinacao_igual_a_da_f01():
    lista = _corpus()
    obras, _ = OV.projecao(lista, NOMES)
    contagem, _ = AV.conjuntos_por_obra(lista, NOMES)
    assert [(r, n) for _, r, n in OV.por_combinacao(obras, NOMES)] == list(contagem.items())


def test_matriz_igual_a_da_f02_nas_obras_elegiveis():
    lista = _corpus()
    obras, _ = OV.projecao(lista, NOMES)
    m = OV.matriz(OV.filtrar(obras, _filtros(), RECORTES), NOMES, RECORTES)
    f02 = AV.origem_por_angulo(lista, NOMES, RECORTES)
    rotulo = dict(OV.combinacoes(NOMES))
    assert m["linhas"] == OV.combinacoes(NOMES) and m["colunas"] == [V, AP, AV.SEM_ANGULO]
    assert {(rotulo[l], c): n for (l, c), n in m["celulas"].items()} == {(l, c): n for l, cs in f02["matriz"].items()
                                                                          for c, n in cs.items()}


# ---------- leitura dos filtros ----------
PADRAO = _filtros()


@pytest.mark.parametrize("pares, filtros, erros", [
    ([], PADRAO, []),
    ([("perspectiva", "vies")], _filtros(perspectiva="vies"), []),
    ([("perspectiva", "tecnologias")], _filtros(perspectiva="tecnologias"), []),
    ([("perspectiva", "outra")], PADRAO, ["Filtro inválido: perspectiva."]),
    ([("universo", "todas")], _filtros(universo="todas"), []),
    ([("universo", "elegiveis")], PADRAO, []),
    ([("universo", "alta")], PADRAO, ["Filtro inválido: universo."]),
    ([("combinacao", "A+C")], _filtros(combinacao="A+C"), []),
    ([("combinacao", "nenhum")], _filtros(combinacao="nenhum"), []),
    ([("combinacao", "C+A")], PADRAO, ["Filtro inválido: combinacao."]),           # so a forma canonica
    ([("combinacao", "A+A")], PADRAO, ["Filtro inválido: combinacao."]),
    ([("combinacao", "a")], PADRAO, ["Filtro inválido: combinacao."]),             # maiuscula conta
    ([("combinacao", "Só A")], PADRAO, ["Filtro inválido: combinacao."]),          # o rotulo nao e a chave
    ([("combinacao", "A + C")], PADRAO, ["Filtro inválido: combinacao."]),
    ([("conjunto", "C")], _filtros(conjunto="C"), []),
    ([("conjunto", "D")], PADRAO, ["Filtro inválido: conjunto."]),
    ([("conjunto", "nenhum")], PADRAO, ["Filtro inválido: conjunto."]),
    ([("fonte", "so_web")], _filtros(fonte="so_web"), []),
    ([("fonte", "Web")], PADRAO, ["Filtro inválido: fonte."]),
    ([("angulo", V)], _filtros(angulo=V), []),
    ([("angulo", "sem_angulo")], _filtros(angulo="sem_angulo"), []),
    ([("angulo", "Viés algorítmico")], PADRAO, ["Filtro inválido: angulo."]),
    ([("eixo", "E2")], _filtros(eixo="E2"), []),
    ([("eixo", "sem_eixo")], _filtros(eixo="sem_eixo"), []),
    ([("eixo", "e2")], PADRAO, ["Filtro inválido: eixo."]),
    ([("eixo", "Sem eixo")], PADRAO, ["Filtro inválido: eixo."]),
    ([("conjunto", "  C  ")], _filtros(conjunto="C"), []),                          # espacos nas pontas saem
    ([("conjunto", "")], PADRAO, []),                                               # vazio = sem filtro
    ([("conjunto", "   ")], PADRAO, []),                                            # so espacos = sem filtro
    ([("conjunto", "C"), ("conjunto", "")], _filtros(conjunto="C"), []),            # o vazio nao repete
    ([("conjunto", "C"), ("conjunto", "C")], PADRAO, ["Filtro repetido: conjunto."]),
    ([("conjunto", "C"), ("conjunto", "D")], PADRAO, ["Filtro repetido: conjunto."]),
    ([("pagina", "2"), ("outra", "x"), ("csrf", "y")], PADRAO, []),                 # chaves fora de FILTROS: ignoradas
    ([("perspectiva", "vies"), ("angulo", AP)], _filtros(perspectiva="vies", angulo=AP),
     ["O ângulo já é definido pela perspectiva: tire o filtro de ângulo."]),
    ([("perspectiva", "integrada"), ("angulo", AP)], _filtros(angulo=AP), []),
    # todos os erros, na ordem de FILTROS; o conflito de perspectiva so entre valores validos, por ultimo
    ([("eixo", "x"), ("fonte", "y"), ("fonte", "z"), ("universo", "w"), ("perspectiva", "vies"), ("angulo", "q")],
     _filtros(perspectiva="vies"),
     ["Filtro inválido: universo.", "Filtro repetido: fonte.", "Filtro inválido: angulo.", "Filtro inválido: eixo."]),
    ([("eixo", "x"), ("perspectiva", "tecnologias"), ("angulo", V)], _filtros(perspectiva="tecnologias", angulo=V),
     ["Filtro inválido: eixo.", "O ângulo já é definido pela perspectiva: tire o filtro de ângulo."]),
])
def test_ler_filtros(pares, filtros, erros):
    assert OV.ler_filtros(pares, NOMES, RECORTES, EIXOS) == (filtros, erros)


def test_ler_filtros_valor_longo_e_invalido_sem_estourar():
    assert OV.ler_filtros([("eixo", "E" * 100000)], NOMES, RECORTES, EIXOS) == (PADRAO, ["Filtro inválido: eixo."])


# ---------- filtragem: sobre obras, nunca sobre membros ----------
@pytest.mark.parametrize("filtros, ids", [
    (_filtros(), ["W-1", "W-5", "A-2", "A-3"]),                                     # padrao: relevancia alta ou media
    (_filtros(universo="todas"), ["W-1", "W-5", "A-2", "A-3", "A-4", "A-6"]),
    (_filtros(combinacao="A+C"), ["A-3"]),                                          # combinacao exata
    (_filtros(combinacao="A"), ["W-1"]),                                            # "so A": A-3 (A e C) nao entra
    (_filtros(combinacao="C"), ["A-2"]),                                            # exclusivamente em C
    (_filtros(conjunto="C"), ["A-2", "A-3"]),                                       # achada em C (com ou sem outros)
    (_filtros(conjunto="A"), ["W-1", "A-3"]),
    (_filtros(universo="todas", conjunto="C"), ["A-2", "A-3", "A-6"]),
    (_filtros(combinacao="nenhum"), ["W-5"]),
    (_filtros(conjunto="A", combinacao="A+C"), ["A-3"]),
    (_filtros(conjunto="B", combinacao="A+C"), []),
    (_filtros(fonte="web"), ["W-1", "W-5", "A-3"]),                                 # achada na web (tambem a que junta)
    (_filtros(fonte="so_web"), ["W-1", "W-5"]),                                     # so na web
    (_filtros(fonte="scholar"), ["A-2", "A-3"]),
    (_filtros(fonte="so_scholar"), ["A-2"]),                                        # A-3 tem membro do Scholar e nao entra
    (_filtros(fonte="ambas"), ["A-3"]),
    (_filtros(angulo=V), ["W-1", "A-3"]),                                           # o angulo da obra (do artigo, em A-3)
    (_filtros(angulo=AP), ["A-2"]),                                                 # o membro web de A-3 nao conta
    (_filtros(angulo="sem_angulo"), ["W-5"]),
    (_filtros(perspectiva="vies"), ["W-1", "A-3"]),
    (_filtros(perspectiva="tecnologias"), ["A-2"]),
    (_filtros(perspectiva="tecnologias", universo="todas"), ["A-2"]),
    (_filtros(perspectiva="vies", universo="todas"), ["W-1", "A-3", "A-4", "A-6"]),
    (_filtros(eixo="E1"), ["W-1", "A-3"]),
    (_filtros(eixo="sem_eixo"), ["W-5"]),
    (_filtros(eixo="E3"), []),
    (_filtros(universo="todas", eixo="E3"), ["A-6"]),
    (_filtros(fonte="web", angulo=V, eixo="E1", conjunto="A"), ["W-1", "A-3"]),
])
def test_filtrar(filtros, ids):
    obras, _ = OV.projecao(_corpus(), NOMES)
    antes = copy.deepcopy(obras)
    assert _ids(OV.filtrar(obras, filtros, RECORTES)) == ids
    assert obras == antes


def test_recorte_fora_da_lista_configurada_conta_como_sem_angulo():
    obras, _ = OV.projecao(_itens([_web(1)], [], {("referencia", 1): _t("alta", "outro")}), NOMES)
    assert _ids(OV.filtrar(obras, _filtros(angulo="sem_angulo"), RECORTES)) == ["W-1"]
    assert OV.matriz(obras, NOMES, RECORTES)["celulas"][("A", AV.SEM_ANGULO)] == 1


def test_as_fontes_particionam_as_obras():
    obras, _ = OV.projecao(_corpus(), NOMES)
    partes = [_ids(OV.filtrar(obras, _filtros(universo="todas", fonte=f), RECORTES)) for f in ("so_web", "so_scholar", "ambas")]
    assert sorted(sum(partes, [])) == sorted(_ids(obras))


# ---------- a celula da matriz e a lista ----------
@pytest.mark.parametrize("base", [_filtros(), _filtros(fonte="web"), _filtros(eixo="E1"), _filtros(universo="todas"),
                                  _filtros(conjunto="C"), _filtros(fonte="so_scholar", universo="todas")])
def test_cada_celula_tem_exatamente_as_obras_da_lista(base):
    obras, _ = OV.projecao(_corpus(), NOMES)
    filtradas = OV.filtrar(obras, base, RECORTES)
    m = OV.matriz(filtradas, NOMES, RECORTES)
    assert sum(m["celulas"].values()) == len(filtradas)
    assert set(m["celulas"]) == {(l, c) for l, _ in m["linhas"] for c in m["colunas"]}
    for (l, c), n in m["celulas"].items():
        assert len(OV.filtrar(obras, {**base, "combinacao": l, "angulo": c}, RECORTES)) == n


# ---------- agregacoes ----------
def test_por_combinacao_com_zeros_na_ordem():
    obras, _ = OV.projecao(_corpus(), NOMES)
    assert OV.por_combinacao(OV.filtrar(obras, _filtros(), RECORTES), NOMES) == [
        ("A", "Só A", 1), ("B", "Só B", 0), ("C", "Só C", 1), ("A+B", "A + B", 0), ("A+C", "A + C", 1), ("B+C", "B + C", 0),
        ("A+B+C", "A + B + C", 0), ("nenhum", "Sem conjunto", 1)]
    assert OV.por_combinacao([], NOMES) == [(k, r, 0) for k, r in OV.combinacoes(NOMES)]


def test_grupos():
    lista = _itens([_web(1), _web(2), _web(3)], [_art(4)],
                   {("referencia", 1): _t(tipo="Artigo científico"),
                    ("referencia", 2): _t(tipo="Relatório técnico / literatura cinzenta"),
                    ("referencia", 3): _t(tipo=None)})
    obras, _ = OV.projecao(lista, NOMES)
    assert OV.grupos(obras) == [("Literatura científica", 1), ("Literatura cinzenta", 1), ("Fonte primária", 0),
                                ("Sem tipo de fonte", 2)]
    assert OV.grupos(obras[:2]) == [("Literatura científica", 1), ("Literatura cinzenta", 1), ("Fonte primária", 0)]
    assert OV.grupos([]) == [("Literatura científica", 0), ("Literatura cinzenta", 0), ("Fonte primária", 0)]


def test_resumo():
    obras, _ = OV.projecao(_corpus(), NOMES)
    assert OV.resumo(obras) == {"obras": 6, "so_web": 2, "so_scholar": 3, "ambas": 1, "com_divergencia": 1,
                                "possiveis_duplicatas": 0}
    assert OV.resumo([]) == {"obras": 0, "so_web": 0, "so_scholar": 0, "ambas": 0, "com_divergencia": 0,
                             "possiveis_duplicatas": 0}


def test_as_agregacoes_da_f0_valem_sobre_as_obras_filtradas():
    """As funcoes de `analises_vies` que recebem itens dao o mesmo resultado sobre as obras da projecao (cada obra ja e um
    item representativo, e nenhuma repete outra)."""
    lista = _corpus()
    obras, _ = OV.projecao(lista, NOMES)
    assert AV.eixos(obras, EIXOS) == AV.eixos(lista, EIXOS)
    assert AV.topicos(obras) == AV.topicos(lista)


# ---------- ordem e paginas ----------
def test_ordenar_pelo_titulo_sem_acento_e_sem_maiuscula_e_os_sem_letra_por_ultimo():
    lista = _itens([_web(1, titulo="beta"), _web(2, titulo="Álfa"), _web(3, titulo="---"), _web(4, titulo="alfa"),
                    _web(5, titulo="Gama")], [], {})
    obras, _ = OV.projecao(lista, NOMES)
    antes = copy.deepcopy(obras)
    assert _ids(OV.ordenar(obras)) == ["W-2", "W-4", "W-1", "W-5", "W-3"]          # empate: a ordem da projecao
    assert obras == antes


@pytest.mark.parametrize("pares, total, esperado", [
    ([], 0, (1, None)), ([], 120, (1, None)), ([("pagina", "")], 120, (1, None)), ([("pagina", "  ")], 120, (1, None)),
    ([("pagina", "3")], 120, (3, None)), ([("pagina", " 2 ")], 120, (2, None)), ([("pagina", "0002")], 120, (2, None)),
    ([("pagina", "4")], 120, (None, "Página inválida.")), ([("pagina", "0")], 120, (None, "Página inválida.")),
    ([("pagina", "-1")], 120, (None, "Página inválida.")), ([("pagina", "1.0")], 120, (None, "Página inválida.")),
    ([("pagina", "abc")], 120, (None, "Página inválida.")), ([("pagina", "1234567")], 10 ** 9, (None, "Página inválida.")),
    ([("pagina", "9" * 5000)], 120, (None, "Página inválida.")),
    ([("pagina", "٣")], 120, (None, "Página inválida.")),                          # digito de outro alfabeto
    ([("pagina", "1"), ("pagina", "2")], 120, (None, "Página inválida.")),
    ([("pagina", "1"), ("pagina", "")], 120, (1, None)),
    ([("pagina", "1")], 0, (1, None)), ([("pagina", "2")], 0, (None, "Página inválida.")),
    ([("pagina", "1")], 50, (1, None)), ([("pagina", "2")], 50, (None, "Página inválida.")),
    ([("pagina", "2")], 51, (2, None)),
])
def test_ler_pagina(pares, total, esperado):
    assert OV.ler_pagina(pares, total) == esperado


def test_fatia_e_ultima_pagina():
    obras = [{"id": f"W-{i}"} for i in range(1, 121)]
    assert _ids(OV.fatia(obras, 1)) == [f"W-{i}" for i in range(1, 51)]
    assert _ids(OV.fatia(obras, 3)) == [f"W-{i}" for i in range(101, 121)]
    assert [OV.ultima_pagina(n) for n in (0, 1, 50, 51, 100, 101)] == [1, 1, 1, 2, 2, 3]


# ---------- pre-revisao: cada valor aceito, cada chave repetida, todos os erros ----------
def _valores_aceitos():
    return {"perspectiva": [k for k, _ in OV.PERSPECTIVAS], "universo": [k for k, _ in OV.UNIVERSOS],
            "combinacao": [k for k, _ in OV.combinacoes(NOMES)], "conjunto": list(NOMES), "fonte": [k for k, _ in OV.FONTES],
            "angulo": list(RECORTES) + [AV.SEM_ANGULO], "eixo": list(EIXOS) + [OV.SEM_EIXO]}


@pytest.mark.parametrize("chave, valor", [(k, v) for k, vs in _valores_aceitos().items() for v in vs])
def test_cada_valor_aceito(chave, valor):
    filtros, erros = OV.ler_filtros([(chave, valor)], NOMES, RECORTES, EIXOS)
    assert erros == [] and filtros == {**PADRAO, chave: valor}


@pytest.mark.parametrize("chave", OV.FILTROS)
def test_cada_chave_repetida(chave):
    v = _valores_aceitos()[chave][0]
    assert OV.ler_filtros([(chave, v), (chave, v)], NOMES, RECORTES, EIXOS) == (PADRAO, [f"Filtro repetido: {chave}."])


def test_todos_os_erros_juntos_na_ordem():
    pares = [("eixo", "x"), ("angulo", "x"), ("fonte", "x"), ("conjunto", "x"), ("combinacao", "x"), ("universo", "x"),
             ("perspectiva", "x")]
    assert OV.ler_filtros(pares, NOMES, RECORTES, EIXOS) == (PADRAO, [f"Filtro inválido: {k}." for k in OV.FILTROS])
    pares = [(k, "x") for k in OV.FILTROS] + [(k, "y") for k in OV.FILTROS]
    assert OV.ler_filtros(pares, NOMES, RECORTES, EIXOS) == (PADRAO, [f"Filtro repetido: {k}." for k in OV.FILTROS])


# ---------- pre-revisao: uma auditoria por projecao ----------
def test_projecao_chama_a_auditoria_uma_vez(monkeypatch):
    chamadas = []
    original = AV.auditoria_identidade

    def contada(lista):
        chamadas.append(1)
        return original(lista)
    monkeypatch.setattr(AV, "auditoria_identidade", contada)
    OV.projecao(_corpus(), NOMES)
    assert chamadas == [1]


# ---------- pre-revisao: nenhuma funcao muda a entrada; filtrar devolve lista nova ----------
def test_nenhuma_funcao_muda_a_entrada():
    obras, _ = OV.projecao(_corpus(), NOMES)
    antes = copy.deepcopy(obras)
    OV.matriz(obras, NOMES, RECORTES)
    OV.por_combinacao(obras, NOMES)
    OV.grupos(obras)
    OV.resumo(obras)
    OV.fatia(obras, 1)
    OV.ordenar(obras)
    OV.filtrar(obras, _filtros(universo="todas"), RECORTES)
    assert obras == antes
    pares = [("conjunto", " C "), ("pagina", "1")]
    OV.ler_filtros(pares, NOMES, RECORTES, EIXOS)
    OV.ler_pagina(pares, 10)
    assert pares == [("conjunto", " C "), ("pagina", "1")]


def test_filtrar_devolve_lista_nova_mesmo_sem_tirar_nada():
    obras, _ = OV.projecao(_corpus(), NOMES)
    todas = OV.filtrar(obras, _filtros(universo="todas"), RECORTES)
    assert todas == obras and todas is not obras


def test_formato_da_matriz():
    obras, _ = OV.projecao(_corpus(), NOMES)
    assert set(OV.matriz(obras, NOMES, RECORTES)) == {"linhas", "colunas", "celulas"}
    vazia = OV.matriz([], NOMES, RECORTES)
    assert set(vazia["celulas"].values()) == {0} and len(vazia["celulas"]) == 8 * 3


# ---------- pre-revisao: docstrings ----------
def test_docstrings():
    texto = " ".join((OV.__doc__ or "").split())
    assert texto == ("Observatorio do banco `vies`: a projecao de obras (cada obra uma vez, com os membros da web e do Scholar, "
                     "a uniao dos conjuntos, o angulo da obra e as divergencias entre membros), os filtros GET lidos sem "
                     "tolerancia, a filtragem sobre obras (nunca sobre membros), a ordem, as paginas e as agregacoes das "
                     "perspectivas. Funcoes puras; a deduplicacao e a de `analises_vies`.")
    for nome in ("combinacoes", "projecao", "ler_filtros", "filtrar", "matriz", "por_combinacao", "grupos", "resumo",
                 "ordenar", "ultima_pagina", "ler_pagina", "fatia"):
        assert (getattr(OV, nome).__doc__ or "").strip(), nome


# ---------- pre-revisao: texto vazio vale como ausente ----------
def test_eixo_e_tipo_vazios_valem_como_ausentes():
    lista = _itens([_web(1), _web(2)], [], {("referencia", 1): _t(eixo="", tipo=""), ("referencia", 2): _t(eixo=None, tipo=None)})
    obras, _ = OV.projecao(lista, NOMES)
    assert _ids(OV.filtrar(obras, _filtros(eixo="sem_eixo"), RECORTES)) == ["W-1", "W-2"]
    assert OV.grupos(obras)[-1] == ("Sem tipo de fonte", 2)


# ---------- retrabalho R1: as ancoras sao usadas, nao copiadas ----------
def test_rotulos_das_combinacoes_vem_de_analises_vies(monkeypatch):
    """Os rotulos sao os de `AV.combinacoes`: se a regra de la mudar, a daqui muda junto."""
    monkeypatch.setattr(AV, "combinacoes", lambda nomes: [f"<{i}>" for i in range(2 ** len(nomes) - 1)])
    assert OV.combinacoes(("A", "B")) == [("A", "<0>"), ("B", "<1>"), ("A+B", "<2>"), ("nenhum", "Sem conjunto")]


def test_projecao_vazia_tambem_chama_a_auditoria_uma_vez(monkeypatch):
    chamadas = []
    original = AV.auditoria_identidade

    def contada(lista):
        chamadas.append(1)
        return original(lista)
    monkeypatch.setattr(AV, "auditoria_identidade", contada)
    assert OV.projecao([], NOMES) == ([], [])
    assert chamadas == [1]


def test_ordenar_calcula_a_chave_uma_vez_por_obra(monkeypatch):
    chamadas = []
    original = AV.chave_titulo

    def contada(titulo):
        chamadas.append(titulo)
        return original(titulo)
    obras, _ = OV.projecao(_corpus(), NOMES)
    monkeypatch.setattr(AV, "chave_titulo", contada)
    OV.ordenar(obras)
    assert len(chamadas) == len(obras)
