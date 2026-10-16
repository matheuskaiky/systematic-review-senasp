"""Funcoes puras de `dominio/analise_termos.py` com dados montados a mao: proporcao com Wilson, palavras, auditoria do pre-filtro
e do limite por UF, tabela por termo (acao sugerida), simulacao de consulta composta e propriedades (monotonia da retencao)."""
import random

import pytest

from dominio import analise_termos as at
from dominio import estatistica as est


def _it(i, status, titulo="", resumo="", **extra):
    return {"item_id": i, "uf": extra.pop("uf", "PI"), "status": status, "valido": extra.pop("valido", 1), "titulo": titulo,
            "resumo": resumo, **extra}


# ============================== proporcao ==============================
def test_proporcao_com_wilson_igual_ao_modulo_estatistico():
    p = at.proporcao(8, 10)
    inf, sup = est.intervalo_wilson(8, 10)
    assert p == {"k": 8, "n": 10, "pct": 80.0, "ic_inf": round(100 * inf, 1), "ic_sup": round(100 * sup, 1)}
    assert p["ic_inf"] < 80.0 < p["ic_sup"]


def test_proporcao_sem_denominador_e_limites():
    assert at.proporcao(0, 0) == {"k": 0, "n": 0, "pct": None, "ic_inf": None, "ic_sup": None}
    assert at.proporcao(None, None)["pct"] is None
    zero, cheio = at.proporcao(0, 5), at.proporcao(5, 5)
    assert zero["pct"] == 0.0 and zero["ic_inf"] == 0.0 and cheio["pct"] == 100.0 and cheio["ic_sup"] == 100.0
    assert at.proporcao(9, 5)["k"] == 5                      # k e limitado a n


# ============================== palavras ==============================
def test_palavras_do_texto_sem_acento_sem_vazias_numeros_e_curtas():
    assert at.palavras_do_texto("A Polícia de Teresina usa 2024 câmeras em IA, de acordo com o www") == {
        "policia", "teresina", "usa", "cameras", "acordo"}
    assert at.palavras_do_texto(None) == set() and at.palavras_do_texto("") == set()


def test_ja_coberta_pelo_prefiltro_casa_por_trecho_e_por_palavra_de_expressao():
    pre = ["preditiv", "reconhecimento facial", "câmera"]
    assert at.ja_coberta_pelo_prefiltro("preditivo", pre)           # o pre-filtro casa `preditiv` dentro de `preditivo`
    assert at.ja_coberta_pelo_prefiltro("facial", pre)              # palavra de uma expressao do pre-filtro
    assert at.ja_coberta_pelo_prefiltro("camera", pre)              # sem acento
    assert not at.ja_coberta_pelo_prefiltro("drone", pre)
    assert not at.ja_coberta_pelo_prefiltro("drone", None)


def test_razao_de_chances_sinal_e_suavizacao():
    lo, lift = at.razao_de_chances(10, 20, 0, 100)
    assert lo > 0 and lift > 1 and lo != float("inf")                # a suavizacao evita infinito quando b = 0
    lo2, lift2 = at.razao_de_chances(5, 20, 25, 100)                 # mesma proporcao nos dois grupos: log perto de 0, lift perto de 1
    assert abs(lo2) < 0.1 and 0.9 < lift2 < 1.1
    assert at.razao_de_chances(1, 20, 30, 100)[0] < 0


def test_super_representadas_suporte_minimo_vazias_excluidas_e_prefiltro():
    frente = ["senasp painel dados", "senasp relatorio", "senasp edital", "camera rara", "dados dos"]
    fundo = ["painel dados", "outro texto", "mais um", "outro texto"]
    r = at.palavras_super_representadas(frente, fundo, min_suporte=2)
    assert [x["palavra"] for x in r][:1] == ["senasp"]
    assert "dos" not in {x["palavra"] for x in r}                     # palavra vazia
    assert "rara" not in {x["palavra"] for x in r}                    # abaixo do suporte
    com_pre = at.palavras_super_representadas(frente, fundo, prefiltro=["senasp"], min_suporte=2)
    assert "senasp" not in {x["palavra"] for x in com_pre}            # ja no pre-filtro
    com_ex = at.palavras_super_representadas(frente, fundo, excluir=["Senasp"], min_suporte=2)
    assert "senasp" not in {x["palavra"] for x in com_ex}
    s = r[0]
    assert s["n_frente"] == 3 and s["n_fundo"] == 0 and s["pct_frente"] == 60.0 and s["pct_fundo"] == 0.0 and s["lift"] > 1


def test_super_representadas_grupos_vazios_e_palavra_comum_nao_aparece():
    assert at.palavras_super_representadas([], ["a b c"]) == [] and at.palavras_super_representadas(["x y z"], []) == []
    # a palavra esta mais no fundo do que na frente: nao e super-representada
    r = at.palavras_super_representadas(["comum aqui", "comum la", "comum ali"], ["comum 1"] * 3 + ["comum 2", "comum 3"], min_suporte=1)
    assert "comum" not in {x["palavra"] for x in r}


def test_super_representadas_ordem_deterministica():
    frente = ["alfa beta", "alfa beta", "alfa gama", "beta gama"]
    fundo = ["delta", "delta", "delta", "delta"]
    a = at.palavras_super_representadas(frente, fundo, min_suporte=1)
    b = at.palavras_super_representadas(list(reversed(frente)), fundo, min_suporte=1)
    assert a == b and [x["palavra"] for x in a] == sorted([x["palavra"] for x in a], key=lambda p: (-next(y for y in a if y["palavra"] == p)["log_chances"], p))


# ============================== auditoria do pre-filtro ==============================
def _web():
    """6 selecionados (4 elegiveis), 5 descartados pelo pre-filtro (2 elegiveis), 4 pelo limite (3 elegiveis), 1 invalido, 1 sem decisao."""
    itens = []
    n = iter(range(1, 100))
    for st in ("elegivel",) * 4 + ("excluido", "quarentena"):
        itens.append(_it(next(n), st, "reconhecimento facial na secretaria", "dados", selecionada=1, motivo=None, n_ocorrencias=3, melhor_posicao=1))
    for st in ("elegivel", "elegivel", "excluido", "excluido", "quarentena"):
        itens.append(_it(next(n), st, "senasp novo painel" if st == "elegivel" else "receita de bolo", "senasp", selecionada=0,
                         motivo="prefiltro_palavras", n_ocorrencias=1, melhor_posicao=5))
    for st in ("elegivel", "elegivel", "elegivel", "excluido"):
        itens.append(_it(next(n), st, "sistema", "algo", selecionada=0, motivo="limite_por_uf", n_ocorrencias=1, melhor_posicao=9))
    itens.append(_it(next(n), "elegivel", "x", "y", selecionada=1, valido=0))
    itens.append(_it(next(n), "elegivel", "x", "y", selecionada=None))
    return itens


def test_auditoria_grupos_contagens_e_wilson():
    r = at.auditar_prefiltro(_web(), ["reconhecimento facial"], limite_por_uf=40, min_suporte=2)
    g = {x["chave"]: x for x in r["grupos"]}
    assert (r["n_itens"], r["n_validos"], r["n_invalidos"], r["n_sem_selecao"]) == (17, 15, 1, 1)
    assert g["selecionada"]["n"] == 6 and g["selecionada"]["n_elegivel"] == 4 and g["selecionada"]["elegivel"]["pct"] == pytest.approx(66.7, abs=0.05)
    assert g["nao_selecionada"]["n"] == 9 and g["nao_selecionada"]["n_elegivel"] == 5
    assert g["prefiltro_palavras"]["n"] == 5 and g["prefiltro_palavras"]["n_elegivel"] == 2 and g["prefiltro_palavras"]["n_quarentena"] == 1
    assert g["limite_por_uf"]["n"] == 4 and g["limite_por_uf"]["elegivel"]["k"] == 3
    assert g["prefiltro_palavras"]["util"]["k"] == 3                       # elegivel + quarentena
    assert g["nao_selecionada"]["n"] == g["prefiltro_palavras"]["n"] + g["limite_por_uf"]["n"]
    inf, sup = est.intervalo_wilson(4, 6)
    assert g["selecionada"]["elegivel"]["ic_inf"] == round(100 * inf, 1) and g["selecionada"]["elegivel"]["ic_sup"] == round(100 * sup, 1)
    assert "nada" in r["aviso"].lower() and "sugest" in r["aviso"].lower()


def test_auditoria_palavras_candidatas_e_o_que_capturariam():
    r = at.auditar_prefiltro(_web(), ["reconhecimento facial"], min_suporte=2)
    assert (r["n_frente"], r["n_fundo"]) == (2, 6)
    c = {x["palavra"]: x for x in r["palavras_candidatas"]}
    assert "senasp" in c and c["senasp"]["n_frente"] == 2 and c["senasp"]["n_fundo"] == 0
    # o resumo "senasp" aparece nos 5 descartados pelo pre-filtro: captura 5, dos quais 2 sao elegiveis
    assert c["senasp"]["capturados"]["n"] == 5 and c["senasp"]["capturados"]["n_elegivel"] == 2
    assert c["senasp"]["capturados"]["elegivel"]["pct"] == 40.0
    assert "reconhecimento" not in c and "facial" not in c                # ja no pre-filtro
    assert all(x["n_frente"] >= 2 for x in c.values())


def test_auditoria_desempenho_das_palavras_do_prefiltro():
    r = at.auditar_prefiltro(_web(), ["reconhecimento facial", "nao existe"], min_suporte=2)
    d = {x["palavra"]: x for x in r["desempenho_prefiltro"]}
    assert d["reconhecimento facial"]["n"] == 6 and d["reconhecimento facial"]["n_elegivel"] == 4 and d["reconhecimento facial"]["n_unica"] == 6
    assert d["nao existe"]["n"] == 0 and d["nao existe"]["elegivel"]["pct"] is None
    assert r["desempenho_prefiltro"][-1]["palavra"] == "nao existe"        # sem itens vai para o fim


def test_auditoria_vazia_e_sem_selecionados_nao_divide_por_zero():
    r = at.auditar_prefiltro([], ())
    assert r["n_validos"] == 0 and r["palavras_candidatas"] == [] and r["limite_por_uf"]["teto_necessario"] is None
    assert all(g["elegivel"]["pct"] is None for g in r["grupos"])
    so_descartados = [_it(1, "elegivel", "a", "b", selecionada=0, motivo="prefiltro_palavras")]
    r2 = at.auditar_prefiltro(so_descartados, ["x"], min_suporte=1)
    assert r2["n_fundo"] == 0 and r2["palavras_candidatas"] == []


def test_auditoria_motivo_ausente_vira_sem_motivo():
    r = at.auditar_prefiltro([_it(1, "elegivel", selecionada=0, motivo=None)], ())
    assert [g["chave"] for g in r["grupos"]] == ["selecionada", "nao_selecionada", "sem_motivo"]


# ============================== limite por UF ==============================
def _limite():
    """UF AA com limite 3: 7 candidatos; ranks por n_ocorrencias. Elegiveis cortados nos ranks 5 e 7; UF BB sem corte."""
    itens = []
    for rank, (st, sel) in enumerate([("elegivel", 1), ("excluido", 1), ("elegivel", 1), ("excluido", 0), ("elegivel", 0),
                                      ("quarentena", 0), ("elegivel", 0)], 1):
        itens.append(_it(rank, st, uf="AA", selecionada=sel, motivo=None if sel else "limite_por_uf", n_ocorrencias=100 - rank,
                         melhor_posicao=rank))
    itens.append(_it(50, "elegivel", uf="BB", selecionada=1, motivo=None, n_ocorrencias=1, melhor_posicao=1))
    return itens


def test_posicoes_seguem_a_ordem_do_download():
    pos = at.posicoes_por_uf(_limite())
    assert [pos[(i, "AA")] for i in range(1, 8)] == [1, 2, 3, 4, 5, 6, 7] and pos[(50, "BB")] == 1
    # mais ocorrencias primeiro, depois melhor posicao, depois id
    itens = [_it(9, "elegivel", selecionada=1, n_ocorrencias=1, melhor_posicao=1), _it(8, "elegivel", selecionada=1, n_ocorrencias=1, melhor_posicao=1),
             _it(7, "elegivel", selecionada=1, n_ocorrencias=2, melhor_posicao=9), _it(6, "elegivel", selecionada=0, motivo="prefiltro_palavras")]
    pos = at.posicoes_por_uf(itens)
    assert (pos[(7, "PI")], pos[(8, "PI")], pos[(9, "PI")]) == (1, 2, 3) and (6, "PI") not in pos


def test_limite_por_uf_teto_necessario_e_curva_monotona():
    r = at.analise_limite_por_uf(_limite(), 3)
    aa = {u["uf"]: u for u in r["por_uf"]}["AA"]
    assert (aa["n_candidatos"], aa["n_no_limite"], aa["n_triados"]) == (7, 4, 4)
    assert (aa["n_elegiveis_perdidos"], aa["n_uteis_perdidos"], aa["teto_necessario"], aa["downloads_extras"]) == (2, 3, 7, 4)
    bb = {u["uf"]: u for u in r["por_uf"]}["BB"]
    assert bb["teto_necessario"] is None and bb["downloads_extras"] == 0 and bb["n_elegiveis_perdidos"] == 0
    assert r["n_elegiveis_perdidos"] == 2 and r["n_ufs_com_perda"] == 1 and r["teto_necessario"] == 7
    c = r["curva"]
    assert c[0]["teto"] == 3 and c[0]["elegiveis_capturados"] == 0 and c[-1]["teto"] == 7 and c[-1]["elegiveis_capturados"] == 2
    for a, b in zip(c, c[1:]):                                              # mais teto: nunca captura menos nem baixa menos
        assert b["elegiveis_capturados"] >= a["elegiveis_capturados"] and b["downloads_extras"] >= a["downloads_extras"]
        assert b["uteis_capturados"] >= a["uteis_capturados"]
    assert c[-1]["downloads_extras"] == 4


def test_limite_por_uf_sem_corte_ou_sem_itens():
    r = at.analise_limite_por_uf([_it(1, "elegivel", selecionada=1, n_ocorrencias=1)], 40)
    assert r["teto_necessario"] is None and r["curva"] == [] and r["n_elegiveis_perdidos"] == 0
    assert at.analise_limite_por_uf([], 40)["por_uf"] == []


# ============================== tabela por termo ==============================
def _ficha(termo, n, e, q, x, dominios=None, cats=None, internacional=0.0):
    return {"termo": termo, "n_itens": n, "n_elegivel": e, "n_quarentena": q, "n_excluido": x, "categorias": cats or {},
            "dominios": dominios or {}, "pct_internacional": internacional}


@pytest.mark.parametrize("n,pct,dom,n_dom,ruido,esperado", [
    (9, 0.0, "saude", 9, 9, "amostra pequena"),                       # n abaixo do minimo vence qualquer outra regra
    (20, 50.0, "saude", 10, 10, "manter"),                           # exatamente 50%
    (20, 49.9, "saude", 10, 10, "candidato a ganhar contexto"),
    (20, 10.0, "saude", 10, 18, "candidato a ganhar contexto"),      # area dominante vence "revisar"
    (20, 10.0, "saude", 4, 18, "revisar o termo"),                   # area com menos de 5 itens nao e dominante
    (20, 10.0, "saude", 6, 18, "revisar o termo"),                   # 6/18 = 33% < 40%
    (20, 30.0, "saude", 4, 14, "observar"),
    (20, 24.9, None, 0, 15, "revisar o termo"),
])
def test_acao_sugerida_regras(n, pct, dom, n_dom, ruido, esperado):
    acao, regra = at.acao_sugerida(n, pct, dom, n_dom, ruido)
    assert acao == esperado and regra


def test_tabela_por_termo_linhas_ordem_e_campos():
    fichas = [_ficha('"a"', 20, 4, 2, 14, {"saude": 12, "outro": 4}, {"FORA_SEGURANCA_PUBLICA": 9}, 60.0),
              _ficha('"b"', 30, 27, 1, 2, {"saude": 2}, {"SEM_IA_OU_TECNOLOGIA": 2}),
              _ficha('"c"', 3, 3, 0, 0)]
    fichas[0]["termo_id"], fichas[0]["grupo"] = "T01", "g"
    t = at.tabela_por_termo(fichas)
    assert [l["termo"] for l in t] == ['"a"', '"b"', '"c"']               # menos elegivel primeiro
    a = t[0]
    assert a["termo_id"] == "T01" and a["n"] == 20 and a["elegivel"]["pct"] == 20.0 and a["motivo_top"] == "FORA_SEGURANCA_PUBLICA"
    assert a["dominio_top"] == "saude" and a["n_dominio_top"] == 12 and a["pct_dominio_top"] == 75.0
    assert a["acao"] == "candidato a ganhar contexto" and "saude" in a["regra"] and "internacionais" in a["observacao"]
    assert t[1]["acao"] == "manter" and t[1]["observacao"] == ""
    assert t[2]["acao"] == "amostra pequena" and t[2]["motivo_top"] is None and t[2]["pct_dominio_top"] is None


def test_tabela_por_termo_vazia_e_termo_sem_itens():
    assert at.tabela_por_termo([]) == [] and at.tabela_por_termo(None) == []
    t = at.tabela_por_termo([_ficha("x", 0, 0, 0, 0)])
    assert t[0]["elegivel"]["pct"] is None and t[0]["acao"] == "amostra pequena"


# ============================== simulacao ==============================
def _termo():
    """10 elegiveis (6 com 'policia', 2 com 'brasil'), 8 excluidos (1 com 'policia'), 2 em quarentena (1 com 'policia')."""
    itens, n = [], iter(range(1, 100))
    for k in range(10):
        txt = "Polícia usa modelo" if k < 6 else ("Brasil e o modelo" if k < 8 else "modelo geral")
        itens.append(_it(next(n), "elegivel", txt, "resumo"))
    for k in range(8):
        itens.append(_it(next(n), "excluido", "Polícia federal estudo" if k == 0 else "modelo de saude", "resumo"))
    for k in range(2):
        itens.append(_it(next(n), "quarentena", "policia militar" if k == 0 else "outro", "resumo"))
    return itens


def _cand(rotulo, *alts):
    return {"id": rotulo, "rotulo": rotulo, "alternativas": list(alts or [rotulo]), "origem": "padrao"}


def test_simulacao_contagens_e_proporcoes():
    s = at.simular_contextos(_termo(), [_cand("polícia")])
    assert (s["n"], s["n_elegivel"], s["n_excluido"], s["n_quarentena"]) == (20, 10, 8, 2)
    c = s["candidatas"][0]
    assert c["n_passam"] == 8                                             # 6 elegiveis + 1 excluido + 1 quarentena
    assert c["retencao_elegivel"]["k"] == 6 and c["retencao_elegivel"]["n"] == 10 and c["retencao_elegivel"]["pct"] == 60.0
    assert c["ruido_removido"]["k"] == 7 and c["ruido_removido"]["n"] == 8 and c["ruido_removido"]["pct"] == 87.5
    assert c["pct_elegivel_resultante"]["k"] == 6 and c["pct_elegivel_resultante"]["n"] == 8 and c["pct_elegivel_resultante"]["pct"] == 75.0
    assert c["perda_elegivel"] == 4 and c["perda_elegivel_pct"] == 40.0 and c["quarentena_removida"] == 1
    assert c["perde_muitos_uteis"] is True and c["aprovada"] is False
    assert s["elegivel"]["pct"] == 50.0


def test_simulacao_acento_caixa_e_palavra_inteira():
    itens = [_it(1, "elegivel", "POLICIA", ""), _it(2, "excluido", "policiais e policiamento", "")]
    s = at.simular_contextos(itens, [_cand("polícia")])
    assert s["candidatas"][0]["n_passam"] == 1 and s["candidatas"][0]["retencao_elegivel"]["k"] == 1
    assert s["candidatas"][0]["ruido_removido"]["k"] == 1                  # "policiais" nao e a palavra "policia"


def test_simulacao_limite_de_perda_e_configuravel_e_estrito():
    itens = [_it(i, "elegivel", "policia" if i < 9 else "outro", "") for i in range(10)] + [_it(50, "excluido", "x", "")]
    exato = at.simular_contextos(itens, [_cand("policia")])["candidatas"][0]       # perde 1 de 10 = 10%: nao passa de 10%
    assert exato["perda_elegivel_pct"] == 10.0 and exato["perde_muitos_uteis"] is False
    assert at.simular_contextos(itens, [_cand("policia")], limite_perda=0.05)["candidatas"][0]["perde_muitos_uteis"] is True
    assert at.simular_contextos(itens, [_cand("policia")], limite_perda=0.05)["limite_perda"] == 0.05


def test_simulacao_ordena_por_ruido_removido_e_mostra_a_perda_ao_lado():
    s = at.simular_contextos(_termo(), [_cand("brasil"), _cand("polícia"), _cand("inexistente")])
    ruidos = [c["ruido_removido"]["pct"] for c in s["candidatas"]]
    assert ruidos == sorted(ruidos, reverse=True)
    # "brasil" e "inexistente" removem todo o ruido (empate); a que perde menos elegiveis vem primeiro
    assert [c["rotulo"] for c in s["candidatas"]] == ["brasil", "inexistente", "polícia"]
    brasil, inexistente = s["candidatas"][0], s["candidatas"][1]
    assert brasil["ruido_removido"]["pct"] == 100.0 and brasil["perda_elegivel"] == 8
    assert inexistente["ruido_removido"]["pct"] == 100.0 and inexistente["perda_elegivel"] == 10 and inexistente["perde_muitos_uteis"]


def test_simulacao_sem_itens_validos_e_sem_elegiveis():
    assert at.simular_contextos([], [_cand("a")])["candidatas"] == []
    invalidos = [_it(1, "elegivel", "a", "", valido=0), {"item_id": 2, "status": "desconhecido", "valido": 1}]
    s = at.simular_contextos(invalidos, [_cand("a")])
    assert s["n"] == 0 and s["candidatas"] == [] and s["elegivel"]["pct"] is None
    so_ruido = [_it(1, "excluido", "x", ""), _it(2, "excluido", "policia", "")]
    c = at.simular_contextos(so_ruido, [_cand("policia")])["candidatas"][0]
    assert c["retencao_elegivel"]["pct"] is None and c["perda_elegivel"] == 0 and c["perde_muitos_uteis"] is False
    assert c["ruido_removido"]["k"] == 1 and c["amostra_pequena"] is True


def test_simulacao_amostra_pequena_depende_dos_elegiveis():
    assert at.simular_contextos(_termo(), [_cand("a")])["amostra_pequena"] is False
    assert at.simular_contextos(_termo()[:3], [_cand("a")])["amostra_pequena"] is True


def test_simulacao_traz_os_limites_do_teste():
    limites = at.simular_contextos(_termo(), [_cand("a")])["limites"]
    texto = " ".join(limites).lower()
    assert "topo do ranking" in texto and "interpretar operadores" in texto and "rd4" in texto and "texto inteiro" in texto


def test_retencao_nunca_cai_ao_ampliar_o_grupo_ou_e_nunca_sobe_ao_exigir_mais():
    rnd = random.Random(7)
    palavras = ["policia", "crime", "brasil", "delegacia", "drone", "saude", "modelo", "rede"]
    for _ in range(30):
        itens = [_it(i, rnd.choice(("elegivel", "excluido", "quarentena")), " ".join(rnd.sample(palavras, 3)), " ".join(rnd.sample(palavras, 2)))
                 for i in range(40)]
        a, b, c = rnd.sample(palavras, 3)
        s = at.simular_contextos(itens, [_cand(a), _cand(b), _cand(c), _cand("grupo", a, b, c), _cand("grupo2", a, b)])
        por = {x["rotulo"]: x for x in s["candidatas"]}
        for membro in (a, b, c):
            assert por["grupo"]["retencao_elegivel"]["k"] >= por[membro]["retencao_elegivel"]["k"]     # mais alternativas: retem mais
            assert por["grupo"]["ruido_removido"]["k"] <= por[membro]["ruido_removido"]["k"]          # ... e remove menos ruido
            assert por["grupo"]["perda_elegivel"] <= por[membro]["perda_elegivel"]
        assert por["grupo"]["retencao_elegivel"]["k"] >= por["grupo2"]["retencao_elegivel"]["k"]
        for x in s["candidatas"]:
            assert x["retencao_elegivel"]["k"] + x["perda_elegivel"] == s["n_elegivel"]
            assert x["n_passam"] <= s["n"]


# ============================== candidatas ==============================
def test_candidatas_padrao_pt_e_en_com_ids_distintos_e_nao_aprovadas():
    pt, en = at.candidatas_padrao("pt"), at.candidatas_padrao("en")
    assert [c["rotulo"] for c in pt[:-1]] == list(at.CONTEXTOS_PADRAO) and [c["rotulo"] for c in en[:-1]] == list(at.CONTEXTOS_PADRAO_EN)
    assert pt[-1]["alternativas"] == list(at.GRUPO_OU_PT) and en[-1]["alternativas"] == list(at.GRUPO_OU_EN)
    assert not ({c["id"] for c in pt} & {c["id"] for c in en})
    assert all(c["aprovada"] is False and c["origem"] == "padrao" for c in pt + en)
    assert at.candidatas_padrao(None)[0]["idioma"] == "pt"


def test_candidatas_automaticas_contrastam_elegiveis_e_excluidos_e_ignoram_o_proprio_termo():
    itens = ([_it(i, "elegivel", "vigilancia viaturas rede", "") for i in range(4)]
             + [_it(10 + i, "excluido", "ensino fisica rede", "") for i in range(4)])
    auto = at.candidatas_automaticas(itens, termo="vigilancia", min_suporte=3)
    rotulos = [c["rotulo"] for c in auto]
    assert "viaturas" in rotulos and "vigilancia" not in rotulos           # a palavra do proprio termo nao entra
    assert "rede" not in rotulos and "ensino" not in rotulos                # `rede` esta nos dois grupos; `ensino` so no excluido
    assert all(c["origem"] == "automatica" and c["aprovada"] is False for c in auto)
    assert at.candidatas_automaticas([], "x") == []


def test_candidatas_do_termo_nao_repete_palavra_ja_na_lista_padrao():
    itens = ([_it(i, "elegivel", "Brasil policia viaturas dados", "") for i in range(4)] + [_it(10 + i, "excluido", "ensino", "") for i in range(4)])
    c = at.candidatas_do_termo(itens, termo="dados", idioma="pt", min_suporte=3)
    assert [x["rotulo"] for x in c].count("Brasil") == 1 and "brasil" not in [x["rotulo"] for x in c]
    assert "brasil" not in [x["rotulo"] for x in c if x["origem"] == "automatica"]
    assert "policia" not in [x["rotulo"] for x in c if x["origem"] == "automatica"]   # "polícia" ja esta na lista padrao
    assert "viaturas" in [x["rotulo"] for x in c if x["origem"] == "automatica"]


# ============================== agregacao ==============================
def test_agregar_simulacoes_soma_pares_e_nao_mistura_idiomas():
    pt = at.simular_contextos(_termo(), at.candidatas_padrao("pt"))
    en = at.simular_contextos(_termo(), at.candidatas_padrao("en"))
    ag = at.agregar_simulacoes([pt, pt, en])
    por = {a["id"]: a for a in ag}
    policia = por["padrao:pt:policia"]
    assert policia["n_termos"] == 2 and policia["retencao_elegivel"]["n"] == 20 and policia["retencao_elegivel"]["k"] == 12
    assert policia["ruido_removido"]["n"] == 16 and policia["ruido_removido"]["k"] == 14 and policia["perda_elegivel"] == 8
    assert policia["idioma"] == "pt" and por["padrao:en:police"]["n_termos"] == 1 and por["padrao:en:police"]["idioma"] == "en"
    assert por["padrao:pt:grupo_ou"]["n_termos"] == 2 and por["padrao:en:grupo_ou"]["n_termos"] == 1
    assert at.agregar_simulacoes([]) == [] and at.agregar_simulacoes(None) == []
    ordem = [a["ruido_removido"]["pct"] for a in ag]
    assert ordem == sorted(ordem, reverse=True)


def test_agregar_ignora_candidatas_automaticas():
    s = at.simular_contextos(_termo(), [{"id": "auto:x", "rotulo": "x", "alternativas": ["x"], "origem": "automatica"}])
    assert at.agregar_simulacoes([s]) == []
