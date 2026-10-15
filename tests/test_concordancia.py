"""Concordancia entre duas classificacoes (funcao pura): exemplo calculado a mao e casos de borda."""
import pytest

from dominio.concordancia import comparar_classificacoes, interpretar_kappa, kappa_binario


def _item(i, relevante, custo=0.01, json_valido=1, uf="PI", cls=None):
    return {"classificacao_id": cls or i, "url_id": i, "uf": uf, "relevante": relevante, "json_valido": json_valido,
            "custo_usd": custo, "tokens_entrada": 1000, "tokens_saida": 100, "url": f"https://exemplo.gov.br/{i}"}


def _achado(aid, cls, tec, status, conf, confere=1):
    return {"achado_id": aid, "classificacao_id": cls, "tecnologia": tec, "status_reportado": status,
            "confianca": conf, "evidencia_confere": confere}


RF, LP = "reconhecimento_facial", "leitura_placas"


def _exemplo():
    """Dez pares em comum (url_id 1 a 10) mais a pagina 11 so em A e a 12 so em B.
    Relevancia: 1-4 sim/sim, 5 sim/nao, 6-7 nao/sim, 8-10 nao/nao."""
    itens_a = [_item(i, int(i <= 5 or i == 11)) for i in range(1, 12)]
    itens_b = [_item(i, int(i <= 4 or i in (6, 7) or i == 12), custo=0.02) for i in [*range(1, 11), 12]]
    achados_a = [
        _achado(101, 1, RF, "em_uso", "alta"),
        _achado(102, 2, RF, "piloto", "media"),
        _achado(103, 3, RF, "em_uso", "alta"), _achado(104, 3, LP, "em_uso", "baixa"),
        _achado(105, 4, RF, "em_estudo", "baixa", confere=0),
        _achado(106, 5, RF, "anunciado", "media"),
        _achado(107, 11, RF, "em_uso", "alta", confere=None),
    ]
    achados_b = [
        _achado(201, 1, RF, "em_uso", "alta"),
        _achado(202, 2, RF, "licitacao", "media"),
        _achado(203, 3, RF, "em_uso", "media", confere=0),
        _achado(204, 4, LP, "em_estudo", "baixa"),
        _achado(205, 6, RF, "em_uso", "alta"), _achado(206, 7, RF, "em_uso", "alta"),
        _achado(207, 12, RF, "em_uso", "alta"),
    ]
    return itens_a, achados_a, itens_b, achados_b


def test_exemplo_calculado_a_mao_pares_e_relevancia():
    r = comparar_classificacoes(*_exemplo())
    assert r["pares"] == {"ambas": 10, "so_a": 1, "so_b": 1, "total_a": 11, "total_b": 11}
    rel = r["relevancia"]
    assert rel["tabela"] == {"ambas_sim": 4, "so_a": 1, "so_b": 2, "ambas_nao": 3}
    assert rel["concordam"] == 7 and rel["taxa"] == pytest.approx(0.7)
    # po = 7/10; A diz sim em 5, B em 6 -> pe = (5*6 + 5*4)/100 = 0,5; kappa = (0,7 - 0,5)/(1 - 0,5) = 0,4
    assert rel["kappa"] == pytest.approx(0.4) and rel["kappa_motivo"] is None
    assert rel["interpretacao"] == "razoável"


def test_exemplo_calculado_a_mao_tecnologias_status_e_confianca():
    r = comparar_classificacoes(*_exemplo())
    # pares relevantes nas duas: 1, 2, 3, 4. Conjuntos iguais em 1 e 2; Jaccard = (1 + 1 + 1/2 + 0)/4 = 0,625
    assert r["tecnologias"]["n"] == 4 and r["tecnologias"]["iguais"] == 2
    assert r["tecnologias"]["jaccard_medio"] == pytest.approx(0.625)
    a = r["achados"]
    # pareados (par, tecnologia): RF nos pares 1, 2 e 3. Status iguais em 1 e 3; confianca igual em 1 e 2.
    assert a["pareados"] == 3 and a["status_iguais"] == 2 and a["confianca_iguais"] == 2
    assert a["taxa_status"] == pytest.approx(2 / 3)
    assert (a["so_a"], a["so_b"]) == (2, 1)                    # LP no par 3 e RF no 4 so em A; LP no 4 so em B
    assert r["divergencias_por_tipo"] == {"relevancia": 3, "tecnologia": 3, "status": 1, "confianca": 1}
    tipos = [d["tipo"] for d in r["divergencias"]]
    assert tipos == sorted(tipos, key=("relevancia", "tecnologia", "status", "confianca").index)
    status = next(d for d in r["divergencias"] if d["tipo"] == "status")
    assert (status["url_id"], status["valor_a"], status["valor_b"], status["achado_id_a"], status["achado_id_b"]) == (2, "piloto", "licitacao", 102, 202)
    rel5 = next(d for d in r["divergencias"] if d["tipo"] == "relevancia" and d["url_id"] == 5)
    assert (rel5["valor_a"], rel5["valor_b"], rel5["achado_id_a"], rel5["achado_id_b"]) == (True, False, 106, None)
    so_a = next(d for d in r["divergencias"] if d["tipo"] == "tecnologia" and d["url_id"] == 3)
    assert (so_a["tecnologia"], so_a["achado_id_a"], so_a["achado_id_b"], so_a["valor_b"]) == (LP, 104, None, None)


def test_exemplo_calculado_a_mao_metricas_por_execucao():
    r = comparar_classificacoes(*_exemplo())
    a, b = r["execucoes"]["a"], r["execucoes"]["b"]
    assert a["n_paginas"] == 11 and a["n_achados"] == 7
    assert a["n_evidencia_avaliada"] == 6 and a["n_evidencia_confere"] == 5          # um com evidencia nao avaliada e um que nao confere
    assert a["custo_total"] == pytest.approx(0.11) and a["custo_por_pagina"] == pytest.approx(0.01)
    assert a["custo_por_achado"] == pytest.approx(0.11 / 7)
    assert a["tokens_por_pagina"] == 1100
    assert b["n_paginas"] == 11 and b["custo_por_pagina"] == pytest.approx(0.02) and b["n_achados"] == 7
    assert b["n_evidencia_avaliada"] == 7 and b["n_evidencia_confere"] == 6
    # so nas paginas em comum (1 a 10): A tem 6 achados avaliados (o do par 11 fica de fora), 5 conferem
    assert r["evidencia_em_comum"]["a"] == {"n_evidencia_avaliada": 6, "n_evidencia_confere": 5}
    assert r["evidencia_em_comum"]["b"] == {"n_evidencia_avaliada": 6, "n_evidencia_confere": 5}


def test_vazio():
    r = comparar_classificacoes([], [], [], [])
    assert r["pares"]["ambas"] == 0
    assert r["relevancia"]["kappa"] is None and r["relevancia"]["kappa_motivo"] == "sem_pares"
    assert r["relevancia"]["taxa"] is None and r["tecnologias"]["jaccard_medio"] is None
    assert r["divergencias"] == [] and r["execucoes"]["a"]["custo_por_pagina"] is None


def test_execucoes_identicas_concordam_em_tudo():
    itens_a, achados_a, _, _ = _exemplo()
    r = comparar_classificacoes(itens_a, achados_a, itens_a, achados_a)
    assert r["pares"] == {"ambas": 11, "so_a": 0, "so_b": 0, "total_a": 11, "total_b": 11}
    assert r["relevancia"]["taxa"] == 1 and r["relevancia"]["kappa"] == pytest.approx(1)
    assert r["tecnologias"]["taxa_iguais"] == 1 and r["tecnologias"]["jaccard_medio"] == 1
    assert r["achados"]["taxa_status"] == 1 and r["achados"]["taxa_confianca"] == 1
    assert r["divergencias"] == []


def test_sem_pares_em_comum():
    r = comparar_classificacoes([_item(1, 1)], [_achado(1, 1, RF, "em_uso", "alta")],
                                [_item(2, 1)], [_achado(2, 2, RF, "em_uso", "alta")])
    assert r["pares"] == {"ambas": 0, "so_a": 1, "so_b": 1, "total_a": 1, "total_b": 1}
    assert r["relevancia"]["kappa_motivo"] == "sem_pares" and r["divergencias"] == []
    assert r["execucoes"]["a"]["n_achados"] == 1                     # as metricas por execucao nao dependem do pareamento


def test_o_par_e_url_e_uf_e_nao_so_a_url():
    r = comparar_classificacoes([_item(1, 1, uf="PI")], [], [_item(1, 1, uf="CE")], [])
    assert r["pares"]["ambas"] == 0


def test_kappa_indefinido_quando_nao_ha_variacao():
    # todas as paginas relevantes nas duas: pe = 1 e o kappa e 0/0
    assert kappa_binario(5, 0, 0, 0) == (None, "sem_variacao")
    assert kappa_binario(0, 0, 0, 5) == (None, "sem_variacao")
    r = comparar_classificacoes([_item(i, 1) for i in (1, 2)], [], [_item(i, 1) for i in (1, 2)], [])
    assert r["relevancia"]["taxa"] == 1 and r["relevancia"]["kappa"] is None
    assert r["relevancia"]["kappa_motivo"] == "sem_variacao" and r["relevancia"]["interpretacao"] is None


def test_kappa_negativo_e_discordancia_total():
    # A e B sempre discordam: po = 0, pe = 0,5 -> kappa = -1
    assert kappa_binario(0, 2, 2, 0)[0] == pytest.approx(-1)
    assert interpretar_kappa(-1) == "pior que o acaso"
    assert [interpretar_kappa(k) for k in (0, 0.2, 0.4, 0.6, 0.8, 0.9, 1)] == [
        "fraca", "fraca", "razoável", "moderada", "substancial", "quase perfeita", "quase perfeita"]


def test_ambos_relevantes_sem_achados_validos_contam_como_conjunto_igual():
    r = comparar_classificacoes([_item(1, 1), _item(2, 0)], [], [_item(1, 1), _item(2, 1)], [])
    assert r["tecnologias"] == {"n": 1, "iguais": 1, "taxa_iguais": 1, "jaccard_medio": 1}
    assert r["divergencias_por_tipo"]["relevancia"] == 1


def test_custo_nulo_nao_vira_total_enganoso():
    itens = [_item(1, 1, custo=0.5), _item(2, 1, custo=None)]
    m = comparar_classificacoes(itens, [], itens, [])["execucoes"]["a"]
    assert m["custo_total"] is None and m["custo_por_pagina"] is None and m["custo_por_achado"] is None
    assert m["n_sem_custo"] == 1


def test_classificacao_repetida_no_mesmo_par_vale_a_primeira():
    itens = [_item(1, 1, cls=10), _item(1, 0, cls=11)]
    achados = [_achado(1, 10, RF, "em_uso", "alta"), _achado(2, 11, LP, "em_uso", "alta")]
    r = comparar_classificacoes(itens, achados, [_item(1, 1)], [_achado(9, 1, RF, "em_uso", "alta")])
    assert r["pares"]["total_a"] == 1 and r["execucoes"]["a"]["n_achados"] == 1
    assert r["divergencias"] == []
