"""Cobertura e redundância de termos (dominio/cobertura_termos.py): casos montados a mão (vazio, empates, tudo redundante, conjuntos
disjuntos) e propriedades da curva incremental (monotônica e termina em 100%)."""
import copy
import random

import pytest

from dominio import cobertura_termos as cob
from dominio import estatistica as est


def _s(*itens):
    return frozenset(itens)


# ============================== conjuntos básicos ==============================
def test_jaccard_basico_e_vazios():
    assert cob.jaccard(_s(1, 2, 3), _s(2, 3, 4)) == 0.5
    assert cob.jaccard(_s(1), _s(1)) == 1.0
    assert cob.jaccard(_s(1), _s(2)) == 0.0
    assert cob.jaccard(_s(), _s()) is None            # união vazia: sobreposição indefinida


def test_itens_unicos_e_universo():
    c = {"A": _s(1, 2, 3), "B": _s(3, 4), "C": _s()}
    assert cob.itens_unicos(c) == {"A": _s(1, 2), "B": _s(4), "C": _s()}
    assert cob.universo(c) == {1, 2, 3, 4}
    assert cob.universo({}) == set()


def test_conjuntos_por_status_ignora_item_sem_veredito():
    itens = {"A": {1: 1, 2: 2, 3: 3}, "B": {}}
    status = {1: "elegivel", 2: "quarentena", 4: "elegivel"}
    assert cob.conjuntos_por_status(itens, status) == {"A": _s(1), "B": _s()}
    assert cob.conjuntos_por_status(itens, status, cob.STATUS_ELEGIVEL_E_QUARENTENA) == {"A": _s(1, 2), "B": _s()}


# ============================== resumo por chave ==============================
def test_resumir_chaves_contagens_wilson_e_posicao():
    itens = {"A": {1: 1, 2: 5, 3: 7, 4: None, 9: 2}, "B": {1: 3, 5: 1}, "C": {}}
    status = {1: "elegivel", 2: "elegivel", 3: "quarentena", 4: "excluido", 5: "elegivel"}   # item 9 sem veredito
    a, b, c = cob.resumir_chaves(["A", "B", "C"], itens, status, {"A": 2, "B": 0})
    assert (a["n_resultados"], a["n_triados"], a["n_elegiveis"], a["n_quarentena"], a["n_excluidos"]) == (5, 4, 2, 1, 1)
    assert a["n_elegiveis_mais_quarentena"] == 3
    assert a["precisao"] == 0.5
    inf, sup = est.intervalo_wilson(2, 4)
    assert (a["ic_inf"], a["ic_sup"]) == (round(inf, 4), round(sup, 4))
    assert a["creditos"] == 2 and a["elegiveis_por_credito"] == 1.0
    assert a["n_elegiveis_unicos"] == 1                      # o item 2 (o 1 também está em B)
    assert a["pct_elegiveis_de_outros"] == 50.0
    assert a["posicao_media_elegiveis"] == 3.0               # (1 + 5) / 2
    assert b["n_elegiveis"] == 2 and b["n_elegiveis_unicos"] == 1 and b["elegiveis_por_credito"] is None   # sem créditos
    assert c["n_resultados"] == 0 and c["precisao"] is None and c["ic_inf"] is None and c["pct_elegiveis_de_outros"] is None
    assert c["posicao_media_elegiveis"] is None


def test_resumir_chaves_sem_posicao_nem_elegivel():
    r = cob.resumir_chaves(["A"], {"A": {1: None}}, {1: "excluido"})[0]
    assert r["precisao"] == 0.0 and r["posicao_media_elegiveis"] is None and r["pct_elegiveis_de_outros"] is None


# ============================== redundância ==============================
def test_matriz_jaccard_respeita_minimo_e_ordem():
    c = {"B": _s(1, 2, 3, 4, 5), "A": _s(4, 5, 6, 7, 8), "C": _s(1, 2)}
    m = cob.matriz_jaccard(c, minimo=5)
    assert m["chaves"] == ["A", "B"]                         # C tem só 2 elegíveis
    assert m["matriz"][0][0] == 1.0 and m["matriz"][0][1] == m["matriz"][1][0] == round(2 / 8, 4)
    assert cob.matriz_jaccard(c, minimo=5, ordem=["B", "A"])["chaves"] == ["B", "A"]
    assert cob.matriz_jaccard(c, minimo=1, ordem=["C"])["chaves"] == ["C", "A", "B"]       # fora da ordem: alfabética, ao fim
    assert cob.matriz_jaccard({}, minimo=5) == {"chaves": [], "matriz": []}


def test_pares_sobrepostos_ordenados_e_sem_pares_disjuntos():
    c = {"A": _s(1, 2, 3, 4, 5), "B": _s(1, 2, 3, 4, 6), "C": _s(5, 7, 8, 9, 10), "D": _s(20, 21, 22, 23, 24)}
    pares = cob.pares_sobrepostos(c, minimo=5)
    assert [(p["chave_a"], p["chave_b"]) for p in pares] == [("A", "B"), ("A", "C")]
    assert pares[0]["n_em_comum"] == 4 and pares[0]["n_uniao"] == 6 and pares[0]["jaccard"] == round(4 / 6, 4)
    assert not any("D" in (p["chave_a"], p["chave_b"]) for p in pares)


def test_contidos_em_outro_escolhe_o_mais_parecido_e_desempata_por_nome():
    c = {"A": _s(1, 2, 3, 4, 5), "B": _s(1, 2, 3, 4, 5, 6, 7), "C": _s(1, 2, 3, 4, 5, 8), "D": _s(40, 41, 42, 43, 44)}
    r = {l["chave"]: l for l in cob.contidos_em_outro(c, minimo=5)}
    assert r["A"]["contido_em"] == "B" and r["A"]["pct_contido"] == 100.0       # B e C contêm A por inteiro; B vence pelo nome
    assert r["A"]["pct_nos_demais"] == 100.0
    assert r["D"]["contido_em"] is None and r["D"]["pct_contido"] == 0.0
    ordem = [l["chave"] for l in cob.contidos_em_outro(c, minimo=5)]
    assert ordem[-1] == "D"


def test_contidos_com_uniao_dos_demais_maior_que_qualquer_um_isolado():
    c = {"A": _s(1, 2, 3, 4, 5, 6), "B": _s(1, 2, 3), "C": _s(4, 5, 6)}
    r = {l["chave"]: l for l in cob.contidos_em_outro(c, minimo=3)}
    assert r["A"]["pct_contido"] == 50.0 and r["A"]["pct_nos_demais"] == 100.0


# ============================== cobertura gulosa ==============================
def test_gulosa_caso_simples_com_marcos_e_dispensaveis():
    c = {"A": _s(1, 2, 3, 4), "B": _s(3, 4, 5), "C": _s(5), "D": _s(1), "E": _s()}
    g = cob.cobertura_gulosa(c, {"A": 3, "B": 2, "C": 1, "D": 1, "E": 1})
    assert g["universo"] == 5 and g["n_chaves"] == 5
    assert [p["chave"] for p in g["passos"]][:2] == ["A", "C"]          # B e C ganham 1 (o item 5): C é mais barato
    assert [p["ganho"] for p in g["passos"]] == [4, 1, 0, 0, 0]
    assert [p["acumulado"] for p in g["passos"]] == [4, 5, 5, 5, 5]
    assert [p["pct_acumulado"] for p in g["passos"]][:2] == [80.0, 100.0]
    assert g["passos"][1]["creditos_acumulados"] == 4 and g["creditos_total"] == 8
    marcos = {m["percentual"]: m for m in g["marcos"]}
    assert marcos[80]["n_chaves"] == 1 and marcos[90]["n_chaves"] == 2 and marcos[100]["chave_final"] == "C"
    assert marcos[100]["creditos_acumulados"] == 4
    assert {d["chave"] for d in g["dispensaveis"]} == {"B", "D", "E"}
    assert g["com_unicos"] == [{"chave": "A", "n_unicos": 1, "n_itens": 4}]        # só o item 2 é exclusivo de A


def test_gulosa_marco_usa_aritmetica_inteira_no_limite():
    c = {f"T{i}": _s(i) for i in range(20)}                 # 20 itens, 1 por termo
    g = cob.cobertura_gulosa(c)
    marcos = {m["percentual"]: m["n_chaves"] for m in g["marcos"]}
    assert marcos == {80: 16, 90: 18, 95: 19, 100: 20}       # 95% de 20 = 19 exatos, nem 18 nem 20


def test_gulosa_desempate_por_creditos_depois_tamanho_depois_nome():
    # mesmo ganho inicial: o termo mais barato vem antes
    g = cob.cobertura_gulosa({"A": _s(1, 2), "B": _s(3, 4)}, {"A": 3, "B": 1})
    assert [p["chave"] for p in g["passos"]] == ["B", "A"]
    # mesmo ganho e mesmo custo: o de mais itens no total vem antes (A e B ganham 2 no começo; B tem 3 itens)
    g = cob.cobertura_gulosa({"A": _s(1, 2), "B": _s(3, 4, 1)})
    assert g["passos"][0]["chave"] == "B"
    # tudo igual: ordem alfabética, não a de inserção
    g = cob.cobertura_gulosa({"T10": _s(1), "T02": _s(2), "T01": _s(3)})
    assert [p["chave"] for p in g["passos"]] == ["T01", "T02", "T10"]


def test_gulosa_resultado_nao_depende_da_ordem_de_insercao():
    base = {"A": _s(1, 2, 3), "B": _s(3, 4, 5), "C": _s(5, 6, 1), "D": _s(7), "E": _s(2, 7)}
    esperado = cob.cobertura_gulosa(base, {"A": 1, "B": 1, "C": 1})
    for _ in range(10):
        chaves = list(base)
        random.shuffle(chaves)
        assert cob.cobertura_gulosa({k: base[k] for k in chaves}, {"A": 1, "B": 1, "C": 1}) == esperado


def test_gulosa_tudo_redundante_um_termo_basta():
    mesmo = _s(1, 2, 3, 4)
    g = cob.cobertura_gulosa({"A": mesmo, "B": mesmo, "C": mesmo})
    assert [p["ganho"] for p in g["passos"]] == [4, 0, 0]
    assert [d["chave"] for d in g["dispensaveis"]] == ["B", "C"]
    assert g["com_unicos"] == []                             # ninguém tem item exclusivo, mas o guloso ainda precisa de um
    assert all(m["n_chaves"] == 1 for m in g["marcos"])


def test_gulosa_conjuntos_disjuntos_todos_necessarios():
    c = {"A": _s(1, 2, 3), "B": _s(4, 5), "C": _s(6)}
    g = cob.cobertura_gulosa(c)
    assert [p["chave"] for p in g["passos"]] == ["A", "B", "C"]
    assert g["dispensaveis"] == [] and {u["chave"] for u in g["com_unicos"]} == {"A", "B", "C"}
    assert {m["percentual"]: m["n_chaves"] for m in g["marcos"]} == {80: 2, 90: 3, 95: 3, 100: 3}
    assert [p["acumulado"] for p in g["passos"]] == [3, 5, 6]


def test_gulosa_vazia_e_universo_vazio():
    g = cob.cobertura_gulosa({})
    assert g["universo"] == 0 and g["passos"] == [] and g["dispensaveis"] == [] and g["creditos_total"] == 0
    assert all(m["atingido"] is False and m["n_chaves"] is None for m in g["marcos"])
    g = cob.cobertura_gulosa({"A": _s(), "B": _s()}, {"A": 2, "B": 1})
    assert g["universo"] == 0 and all(p["pct_acumulado"] is None for p in g["passos"])
    assert all(m["atingido"] is False for m in g["marcos"]) and len(g["dispensaveis"]) == 2 and g["creditos_total"] == 3


def test_gulosa_nao_altera_a_entrada():
    c = {"A": _s(1, 2), "B": _s(2, 3)}
    copia = copy.deepcopy(c)
    cob.cobertura_gulosa(c, {"A": 1})
    assert c == copia


@pytest.mark.parametrize("semente", range(15))
def test_gulosa_propriedades_em_conjuntos_aleatorios(semente):
    rnd = random.Random(semente)
    n_itens = rnd.randint(1, 60)
    c = {f"T{i:02d}": frozenset(rnd.sample(range(n_itens), rnd.randint(0, min(n_itens, 15)))) for i in range(rnd.randint(1, 25))}
    cred = {k: rnd.randint(0, 3) for k in c}
    g = cob.cobertura_gulosa(c, cred)
    passos = g["passos"]
    assert len(passos) == len(c) and {p["chave"] for p in passos} == set(c)         # toda chave aparece uma vez
    acum = [p["acumulado"] for p in passos]
    assert acum == sorted(acum)                                                      # monotônica
    assert [p["ganho"] for p in passos] == [b - a for a, b in zip([0] + acum, acum)]
    ganhos = [p["ganho"] for p in passos]
    assert ganhos == sorted(ganhos, reverse=True)                                    # guloso: ganhos não crescem (submodularidade)
    assert acum[-1] == g["universo"] == len(cob.universo(c))                         # termina em 100% do universo
    if g["universo"]:
        assert passos[-1]["pct_acumulado"] == 100.0
        pcts = [p["pct_acumulado"] for p in passos]
        assert pcts == sorted(pcts)
        assert {m["percentual"]: m["atingido"] for m in g["marcos"]} == {80: True, 90: True, 95: True, 100: True}
        prefixos = [m["n_chaves"] for m in g["marcos"]]
        assert prefixos == sorted(prefixos)
        for m in g["marcos"]:                                                        # mínimo: um passo antes não alcança
            assert m["acumulado"] * 100 >= m["percentual"] * g["universo"]
            if m["n_chaves"] > 1:
                assert acum[m["n_chaves"] - 2] * 100 < m["percentual"] * g["universo"]
    cum_cred = [p["creditos_acumulados"] for p in passos]
    assert cum_cred == sorted(cum_cred) and cum_cred[-1] == g["creditos_total"] == sum(cred.values())
    assert {d["chave"] for d in g["dispensaveis"]} == {p["chave"] for p in passos if p["ganho"] == 0}
    unicos = cob.itens_unicos(c)
    assert {u["chave"] for u in g["com_unicos"]} == {k for k, v in unicos.items() if v}
    assert all(p["ganho"] > 0 for p in passos if p["chave"] in unicos and unicos[p["chave"]])   # quem tem exclusivo nunca é dispensável


# ============================== e se eu mantivesse só estes ==============================
def test_simular_mantidos():
    c = {"A": _s(1, 2, 3), "B": _s(3, 4), "C": _s(5), "D": _s()}
    r = cob.simular_mantidos(c, ["A", "C", "A", "Z"], {"A": 2, "B": 3, "C": 1, "D": 1})
    assert r["n_mantidos"] == 2 and r["desconhecidos"] == ["Z"] and r["universo"] == 5
    assert r["n_cobertos"] == 4 and r["n_perdidos"] == 1 and r["pct_cobertos"] == 80.0
    assert r["creditos_mantidos"] == 3 and r["creditos_total"] == 7 and r["creditos_economizados"] == 4
    assert r["chaves_descartadas"] == ["B", "D"]
    todos = cob.simular_mantidos(c, list(c))
    assert todos["pct_cobertos"] == 100.0 and todos["creditos_economizados"] == 0
    nenhum = cob.simular_mantidos(c, [])
    assert nenhum["n_cobertos"] == 0 and nenhum["pct_cobertos"] == 0.0
    assert cob.simular_mantidos({}, ["A"])["pct_cobertos"] is None


def test_simular_mantidos_bate_com_o_prefixo_do_guloso():
    c = {"A": _s(1, 2, 3, 4), "B": _s(3, 4, 5), "C": _s(5, 6), "D": _s(7)}
    cred = {"A": 2, "B": 1, "C": 1, "D": 1}
    g = cob.cobertura_gulosa(c, cred)
    for k in range(1, len(g["passos"]) + 1):
        r = cob.simular_mantidos(c, [p["chave"] for p in g["passos"][:k]], cred)
        assert r["n_cobertos"] == g["passos"][k - 1]["acumulado"] and r["creditos_mantidos"] == g["passos"][k - 1]["creditos_acumulados"]


def test_creditos_em_dolar_nao_acumulam_erro_de_ponto_flutuante():
    c = {f"M{i}": _s(i) for i in range(10)}
    g = cob.cobertura_gulosa(c, {k: 0.005 for k in c})
    assert g["creditos_total"] == 0.05 and g["passos"][2]["creditos_acumulados"] == 0.015


# ============================== idioma e posição ==============================
def test_ganho_por_idioma_classes_e_percentuais():
    itens = {"T1": {1: 1, 2: 2, 3: 3}, "T2": {3: 1, 4: 2}, "T3": {5: 1}, "T4": {6: 1}}
    idioma = {"T1": "pt", "T2": "en", "T3": "pt", "T4": None}
    status = {1: "elegivel", 2: "excluido", 3: "elegivel", 4: "quarentena", 5: "elegivel", 6: "elegivel"}
    r = {l["achado_por"]: l for l in cob.ganho_por_idioma(itens, idioma, status)}
    assert list(r) == ["apenas_pt", "apenas_en", "ambos", "sem_idioma"]
    assert r["apenas_pt"]["n_artigos"] == 3 and r["apenas_pt"]["n_elegiveis"] == 2          # 1, 2, 5
    assert r["apenas_en"]["n_artigos"] == 1 and r["apenas_en"]["n_quarentena"] == 1        # 4
    assert r["ambos"]["n_artigos"] == 1 and r["ambos"]["n_elegiveis"] == 1                 # 3
    assert r["sem_idioma"]["n_elegiveis"] == 1
    assert sum(l["pct_dos_elegiveis"] for l in r.values()) == pytest.approx(100.0, abs=0.2)
    assert cob.ganho_por_idioma({}, {}, {}) == []


def test_retorno_por_faixa_e_grupo_usa_a_melhor_posicao_do_grupo():
    itens = {"T1": {1: 3, 2: 12, 3: 25}, "T2": {1: 15, 2: 4, 9: 1}, "T3": {4: 61, 5: None}}
    grupo = {"T1": "g1", "T2": "g1", "T3": "g2"}
    status = {1: "elegivel", 2: "excluido", 3: "elegivel", 4: "excluido", 5: "elegivel"}      # 9 sem veredito, 5 sem posição
    r = cob.retorno_por_faixa_e_grupo(itens, grupo, status)
    por = {(l["grupo"], l["faixa"]): l for l in r}
    assert por[("g1", 1)]["n_triados"] == 2 and por[("g1", 1)]["n_elegiveis"] == 1          # itens 1 (pos 3) e 2 (pos 4)
    assert por[("g1", 3)]["n_triados"] == 1 and por[("g1", 3)]["rotulo"] == "21-30"
    assert por[("g2", 7)]["rotulo"] == "61-70" and por[("g2", 7)]["pct_elegiveis"] == 0.0
    assert len(r) == 3 and cob.retorno_por_faixa_e_grupo({}, {}, {}) == []


def test_ganho_de_composto():
    c = {"T05": _s(1, 2, 3), "T01": _s(2, 3, 4, 5)}
    assert cob.ganho_de_composto(c, "T05", "T01") == {"n_composto": 3, "n_pai": 4, "em_comum": 2, "so_no_composto": 1, "so_no_pai": 2}
    assert cob.ganho_de_composto(c, "T99", "T01")["n_composto"] == 0
