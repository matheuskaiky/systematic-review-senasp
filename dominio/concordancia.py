"""Concordancia entre duas execucoes de classificacao sobre as mesmas paginas (funcao pura, sem E/S).

Entrada: listas de dicionarios simples; saida: um dicionario simples. Toda conta e inteira ou de uma divisao so,
para o pesquisador poder refaze-la a mao a partir dos numeros que a tela mostra.

Itens (um por classificacao): classificacao_id, url_id, uf, relevante, json_valido, custo_usd, tokens_entrada,
tokens_saida e, opcionalmente, url. Achados: achado_id, classificacao_id, tecnologia, status_reportado, confianca,
evidencia_confere. O pareamento usa (url_id, uf); se uma execucao tiver duas classificacoes do mesmo par, vale a
primeira da lista e os achados da outra sao ignorados.
"""

TIPOS_DIVERGENCIA = ("relevancia", "tecnologia", "status", "confianca")


def interpretar_kappa(kappa):
    """Faixas de Landis e Koch (1977), so como leitura aproximada."""
    if kappa is None:
        return None
    if kappa < 0:
        return "pior que o acaso"
    for limite, texto in ((0.20, "fraca"), (0.40, "razoável"), (0.60, "moderada"), (0.80, "substancial")):
        if kappa <= limite:
            return texto
    return "quase perfeita"


def kappa_binario(ambas_sim, so_a, so_b, ambas_nao):
    """Kappa de Cohen para duas respostas sim/nao. Devolve (kappa, motivo); kappa e None quando nao esta definido:
    motivo 'sem_pares' (nenhum par) ou 'sem_variacao' (acaso esperado = 100%: as duas execucoes deram a mesma resposta
    em todos os pares, entao 0/0)."""
    n = ambas_sim + so_a + so_b + ambas_nao
    if n == 0:
        return None, "sem_pares"
    sim_a, sim_b = ambas_sim + so_a, ambas_sim + so_b
    concordam = ambas_sim + ambas_nao
    acaso = sim_a * sim_b + (n - sim_a) * (n - sim_b)          # pe * n**2
    if acaso == n * n:
        return None, "sem_variacao"
    return (concordam * n - acaso) / (n * n - acaso), None


def _por_par(itens):
    """{(url_id, uf): item}, ficando com a primeira classificacao de cada par."""
    saida = {}
    for item in itens:
        saida.setdefault((item["url_id"], item["uf"]), item)
    return saida


def _achados_por_classificacao(achados, ids_validos):
    saida = {}
    for a in achados:
        if a["classificacao_id"] in ids_validos:
            saida.setdefault(a["classificacao_id"], []).append(a)
    return saida


def _soma(valores):
    """Soma, ou None se faltar algum valor (custo 'nao calculado' em vez de um total enganoso)."""
    valores = list(valores)
    if not valores or any(v is None for v in valores):
        return None
    return sum(valores)


def _divisao(parte, total):
    return None if not total else parte / total


def metricas_da_execucao(itens, achados):
    """Numeros de uma execucao inteira (nao so dos pares em comum)."""
    ids = {i["classificacao_id"] for i in _por_par(itens).values()}
    itens = [i for i in itens if i["classificacao_id"] in ids]
    achados = [a for a in achados if a["classificacao_id"] in ids]
    avaliados = [a for a in achados if a.get("evidencia_confere") is not None]
    n_paginas, n_achados = len(itens), len(achados)
    custo = _soma(i.get("custo_usd") for i in itens)
    tok_ent = _soma(i.get("tokens_entrada") for i in itens)
    tok_sai = _soma(i.get("tokens_saida") for i in itens)
    return {
        "n_paginas": n_paginas,
        "n_relevantes": sum(1 for i in itens if i.get("relevante")),
        "n_json_valido": sum(1 for i in itens if i.get("json_valido")),
        "n_achados": n_achados,
        "n_evidencia_avaliada": len(avaliados),
        "n_evidencia_confere": sum(1 for a in avaliados if a["evidencia_confere"]),
        "custo_total": custo,
        "n_sem_custo": sum(1 for i in itens if i.get("custo_usd") is None),
        "custo_por_pagina": None if custo is None else _divisao(custo, n_paginas),
        "custo_por_achado": None if custo is None else _divisao(custo, n_achados),
        "tokens_entrada": tok_ent,
        "tokens_saida": tok_sai,
        "tokens_por_pagina": None if None in (tok_ent, tok_sai) else _divisao(tok_ent + tok_sai, n_paginas),
    }


def _evidencia_nos_pares(itens_por_par, achados_por_cls, pares):
    """Taxa de evidencia que confere, so nas paginas em comum (comparacao justa entre execucoes de tamanhos diferentes)."""
    avaliados = [a for p in pares for a in achados_por_cls.get(itens_por_par[p]["classificacao_id"], [])
                 if a.get("evidencia_confere") is not None]
    return {"n_evidencia_avaliada": len(avaliados), "n_evidencia_confere": sum(1 for a in avaliados if a["evidencia_confere"])}


def comparar_classificacoes(itens_a, achados_a, itens_b, achados_b):
    pa, pb = _por_par(itens_a), _por_par(itens_b)
    comuns = sorted(set(pa) & set(pb))
    ac_a = _achados_por_classificacao(achados_a, {i["classificacao_id"] for i in pa.values()})
    ac_b = _achados_por_classificacao(achados_b, {i["classificacao_id"] for i in pb.values()})

    # ---- relevancia (binaria) sobre os pares em comum ----
    tabela = {"ambas_sim": 0, "so_a": 0, "so_b": 0, "ambas_nao": 0}
    for p in comuns:
        ra, rb = bool(pa[p].get("relevante")), bool(pb[p].get("relevante"))
        tabela["ambas_sim" if ra and rb else "so_a" if ra else "so_b" if rb else "ambas_nao"] += 1
    n = len(comuns)
    concordam = tabela["ambas_sim"] + tabela["ambas_nao"]
    kappa, motivo = kappa_binario(tabela["ambas_sim"], tabela["so_a"], tabela["so_b"], tabela["ambas_nao"])

    # ---- tecnologias e achados nos pares relevantes nas duas execucoes ----
    divergencias, n_pares_rel, iguais, soma_jaccard = [], 0, 0, 0.0
    pareados = so_a = so_b = status_iguais = conf_iguais = 0
    for p in comuns:
        ia, ib = pa[p], pb[p]
        la, lb = ac_a.get(ia["classificacao_id"], []), ac_b.get(ib["classificacao_id"], [])
        base = {"url_id": p[0], "uf": p[1], "url": ia.get("url") or ib.get("url")}
        if bool(ia.get("relevante")) != bool(ib.get("relevante")):
            divergencias.append({**base, "tipo": "relevancia", "tecnologia": None,
                                 "valor_a": bool(ia.get("relevante")), "valor_b": bool(ib.get("relevante")),
                                 "achado_id_a": la[0]["achado_id"] if la else None,
                                 "achado_id_b": lb[0]["achado_id"] if lb else None})
            continue
        if not ia.get("relevante"):
            continue
        n_pares_rel += 1
        ma, mb = {}, {}
        for a in la:
            ma.setdefault(a["tecnologia"], a)
        for b in lb:
            mb.setdefault(b["tecnologia"], b)
        uniao = set(ma) | set(mb)
        iguais += set(ma) == set(mb)
        soma_jaccard += len(set(ma) & set(mb)) / len(uniao) if uniao else 1.0
        for tec in sorted(uniao, key=str):
            a, b = ma.get(tec), mb.get(tec)
            linha = {**base, "tecnologia": tec, "achado_id_a": a and a["achado_id"], "achado_id_b": b and b["achado_id"]}
            if a is None or b is None:
                so_b += a is None
                so_a += b is None
                divergencias.append({**linha, "tipo": "tecnologia", "valor_a": a and a["status_reportado"],
                                     "valor_b": b and b["status_reportado"]})
                continue
            pareados += 1
            if a["status_reportado"] == b["status_reportado"]:
                status_iguais += 1
            else:
                divergencias.append({**linha, "tipo": "status", "valor_a": a["status_reportado"], "valor_b": b["status_reportado"]})
            if a["confianca"] == b["confianca"]:
                conf_iguais += 1
            else:
                divergencias.append({**linha, "tipo": "confianca", "valor_a": a["confianca"], "valor_b": b["confianca"]})

    ordem = {t: i for i, t in enumerate(TIPOS_DIVERGENCIA)}
    divergencias.sort(key=lambda d: (ordem[d["tipo"]], d["uf"], d["url_id"], str(d["tecnologia"])))
    return {
        "pares": {"ambas": n, "so_a": len(pa) - n, "so_b": len(pb) - n, "total_a": len(pa), "total_b": len(pb)},
        "relevancia": {"n": n, "tabela": tabela, "concordam": concordam, "taxa": _divisao(concordam, n),
                       "kappa": kappa, "kappa_motivo": motivo, "interpretacao": interpretar_kappa(kappa)},
        "tecnologias": {"n": n_pares_rel, "iguais": iguais, "taxa_iguais": _divisao(iguais, n_pares_rel),
                        "jaccard_medio": _divisao(soma_jaccard, n_pares_rel)},
        "achados": {"pareados": pareados, "so_a": so_a, "so_b": so_b,
                    "status_iguais": status_iguais, "taxa_status": _divisao(status_iguais, pareados),
                    "confianca_iguais": conf_iguais, "taxa_confianca": _divisao(conf_iguais, pareados)},
        "execucoes": {"a": metricas_da_execucao(itens_a, achados_a), "b": metricas_da_execucao(itens_b, achados_b)},
        "evidencia_em_comum": {"a": _evidencia_nos_pares(pa, ac_a, comuns), "b": _evidencia_nos_pares(pb, ac_b, comuns)},
        "divergencias": divergencias,
        "divergencias_por_tipo": {t: sum(1 for d in divergencias if d["tipo"] == t) for t in TIPOS_DIVERGENCIA},
    }
