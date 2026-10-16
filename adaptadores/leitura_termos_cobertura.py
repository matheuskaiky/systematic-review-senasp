"""Leituras da análise RG5 "termos e combinações": cobertura, redundância e ganho incremental de cada termo de busca.
Mistura em LeituraPainelSQLite: usa self._ler (de LeituraAnalises, que por sua vez usa self._consulta). Só lê; nunca grava e
nunca chama API: tudo é cálculo em Python sobre o que já está no banco (as contas ficam em `dominio/cobertura_termos.py`).

Regras comuns:
- os dados vêm das views `r_*` (execuções marcadas para o relatório), da view `v_termos` e da `triagem_escopo`;
- "elegível" é a opinião do modelo sobre o escopo (último veredito válido de cada item), não uma inclusão humana;
- toda cobertura é RELATIVA ao universo já coletado, não é revocação verdadeira;
- cada método lê as tabelas uma vez (poucas centenas de linhas) e calcula em Python;
- leitura defensiva: sem tabela ou view (banco antigo) o método devolve o resultado vazio, não falha;
- só entram as ocorrências do Google Scholar (`r_ocorrencias`); as buscas manuais (IEEE, ACM, Scopus, SBC) não têm créditos
  nem posição e ficam de fora."""
from collections import Counter

from dominio import cobertura_termos as cob
from dominio import estatistica as est

# Veredito atual (a linha de maior id) de cada item da fonte `?`; um único argumento (mesma regra de leitura_analises).
_VEREDITO_ATUAL = ("SELECT te.* FROM triagem_escopo te WHERE te.fonte = ? AND te.id IN "
                   "(SELECT MAX(id) FROM triagem_escopo WHERE fonte = ? GROUP BY item_id, uf)")


def _modelo_da_consulta(consulta_id):
    """`M01-PI-reconhecimento_facial` -> `M01`."""
    return str(consulta_id or "").split("-", 1)[0]


def _chave_celula(tecnologia, modelo):
    return f"{tecnologia or '(sem tecnologia)'}|{modelo}"


def _enriquecer(passos, meta):
    """Troca `chave` por `termo_id` e junta query, idioma e grupo ao passo do guloso."""
    saida = []
    for p in passos:
        m = meta.get(p["chave"], {})
        resto = {k: v for k, v in p.items() if k not in ("chave", "ordem", "n_itens")}
        saida.append({"ordem": p["ordem"], "termo_id": p["chave"], "query": m.get("query"), "idioma": m.get("idioma"),
                      "grupo": m.get("grupo"), "n_elegiveis": p["n_itens"], **resto})
    return saida


class LeituraTermosCobertura:
    """Cobertura e redundância dos termos de busca. Mistura em LeituraPainelSQLite (usa self._ler)."""

    # ---------- carga ----------
    def _tem_tabela(self, nome):
        return bool(self._ler("SELECT 1 AS x FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?", (nome,)))

    def _carregar_termos(self):
        """Lê uma vez o que a análise de termos precisa. Devolve {termos: [{termo_id, query, idioma, grupo, pai}] (ordem do id),
        meta: {termo_id: {...}}, itens: {termo_id: {artigo_id: melhor posição}}, status: {artigo_id: status} (veredito válido),
        creditos: {termo_id: chamadas bem-sucedidas ao Scholar}, tem_triagem: bool}."""
        termos = {l["termo_id"]: l for l in self._ler("SELECT termo_id, query, idioma, grupo, pai FROM v_termos")}
        itens = {}
        for l in self._ler("SELECT termo_id, artigo_id, MIN(posicao) AS posicao FROM r_ocorrencias GROUP BY termo_id, artigo_id"):
            itens.setdefault(l["termo_id"], {})[l["artigo_id"]] = l["posicao"]
        creditos = {l["alvo_id"]: l["n"] for l in self._ler(
            "SELECT alvo_id, COUNT(*) AS n FROM r_chamadas WHERE etapa = 'busca_academica' AND sucesso = 1 GROUP BY alvo_id")}
        for tid in set(itens) | set(creditos):               # termo que saiu da configuração mas ainda tem dados
            termos.setdefault(tid, {"termo_id": tid, "query": None, "idioma": None, "grupo": None, "pai": None})
        tem_triagem = self._tem_tabela("triagem_escopo")
        status = {}
        if tem_triagem:
            status = {l["item_id"]: l["status"] for l in self._ler(
                "SELECT item_id, status FROM (" + _VEREDITO_ATUAL + ") WHERE valido = 1 AND uf = ''", ("artigo", "artigo"))}
        ordem = sorted(termos)
        return {"termos": [termos[t] for t in ordem], "meta": termos, "itens": {t: itens.get(t, {}) for t in ordem},
                "status": status, "creditos": {t: creditos.get(t, 0) for t in ordem}, "tem_triagem": tem_triagem and bool(status)}

    @staticmethod
    def _conjuntos_de(base, incluir_quarentena=False):
        return cob.conjuntos_por_status(base["itens"], base["status"],
                                        cob.STATUS_ELEGIVEL_E_QUARENTENA if incluir_quarentena else cob.STATUS_ELEGIVEL)

    # ---------- 1. rendimento por termo ----------
    def analise_cobertura_termos(self):
        """Rendimento de cada termo do Scholar contra a triagem de escopo, mais a contribuição por idioma e por posição.

        Precisão = elegíveis / triados (itens com veredito válido), com intervalo de Wilson 95%: é a opinião do modelo sobre o
        escopo, não inclusão humana. Créditos = chamadas bem-sucedidas ao Scholar (1 por página). Artigo achado por mais de um
        termo conta em cada um. `n_elegiveis_unicos` = elegíveis que só este termo traz.

        Devolve {tem_triagem, n_termos, n_termos_com_resultado, n_artigos, n_triados, n_sem_veredito, n_elegiveis,
        n_quarentena, n_excluidos, precisao_geral, precisao_ic_inf, precisao_ic_sup, creditos_total,
        por_termo: [{termo_id, query, idioma, grupo, pai, n_resultados, n_triados, n_elegiveis, n_quarentena, n_excluidos,
        n_elegiveis_mais_quarentena, precisao, ic_inf, ic_sup, creditos, elegiveis_por_credito, n_elegiveis_unicos,
        pct_elegiveis_de_outros, posicao_media_elegiveis}],
        por_idioma: [{achado_por: apenas_pt|apenas_en|ambos|sem_idioma, n_artigos, n_triados, n_elegiveis, n_quarentena,
        n_excluidos, precisao, ic_inf, ic_sup, pct_dos_elegiveis}],
        por_faixa_grupo: [{grupo, faixa, rotulo, n_triados, n_elegiveis, pct_elegiveis}]}.
        Exemplo: {"n_termos": 46, "n_elegiveis": 294, "por_termo": [{"termo_id": "T09", "n_resultados": 36, "n_elegiveis": 24,
        "precisao": 0.6667, "creditos": 2, ...}], ...}. Sem dados, tudo zero e listas vazias."""
        base = self._carregar_termos()
        ids = [t["termo_id"] for t in base["termos"]]
        linhas = cob.resumir_chaves(ids, base["itens"], base["status"], base["creditos"])
        por_termo = []
        for l in linhas:
            m = base["meta"][l["chave"]]
            r = {k: v for k, v in l.items() if k != "chave"}
            por_termo.append({"termo_id": l["chave"], "query": m.get("query"), "idioma": m.get("idioma"), "grupo": m.get("grupo"),
                              "pai": m.get("pai") or None, **r})
        todos = set().union(*[set(i) for i in base["itens"].values()]) if base["itens"] else set()
        triados = [base["status"][i] for i in todos if i in base["status"]]
        n_eleg = triados.count("elegivel")
        inf, sup = est.intervalo_wilson(n_eleg, len(triados)) if triados else (None, None)
        idiomas = {t: base["meta"][t].get("idioma") for t in ids}
        grupos = {t: base["meta"][t].get("grupo") for t in ids}
        return {"tem_triagem": base["tem_triagem"], "n_termos": len(ids), "n_termos_com_resultado": sum(1 for t in ids if base["itens"][t]),
                "n_artigos": len(todos), "n_triados": len(triados), "n_sem_veredito": len(todos) - len(triados),
                "n_elegiveis": n_eleg, "n_quarentena": triados.count("quarentena"), "n_excluidos": triados.count("excluido"),
                "precisao_geral": round(n_eleg / len(triados), 4) if triados else None,
                "precisao_ic_inf": None if inf is None else round(inf, 4), "precisao_ic_sup": None if sup is None else round(sup, 4),
                "creditos_total": sum(base["creditos"].values()), "por_termo": por_termo,
                "por_idioma": cob.ganho_por_idioma(base["itens"], idiomas, base["status"]),
                "por_faixa_grupo": cob.retorno_por_faixa_e_grupo(base["itens"], grupos, base["status"])}

    # ---------- 2. redundância ----------
    def analise_redundancia_termos(self, minimo_elegiveis=cob.MINIMO_ELEGIVEIS_MATRIZ):
        """Sobreposição entre termos nos artigos ELEGÍVEIS: Jaccard (matriz e pares) e relação "contido em".

        Só entram termos com pelo menos `minimo_elegiveis` elegíveis (constante `MINIMO_ELEGIVEIS_MATRIZ` = 5; com menos, a
        proporção oscila demais). Jaccard = em comum / união (0 a 1). "Contido em": parte dos elegíveis de um termo que outro
        termo específico também traz.

        Devolve {minimo_elegiveis, n_termos_na_matriz, n_termos_fora (com elegíveis, mas abaixo do mínimo), termos: [ids na
        ordem grupo, id], rotulos: {id: query}, grupos: {id: grupo}, matriz: [[jaccard]] (alinhada a `termos`),
        pares: [{termo_a, termo_b, n_a, n_b, n_em_comum, n_uniao, jaccard}] (do mais ao menos sobreposto),
        contidos: [{termo_id, n_elegiveis, contido_em, n_contido, pct_contido, pct_nos_demais}]}."""
        base = self._carregar_termos()
        conj = self._conjuntos_de(base)
        meta = base["meta"]
        ordem = sorted(meta, key=lambda t: (meta[t].get("grupo") or "~", t))
        m = cob.matriz_jaccard(conj, minimo_elegiveis, ordem)
        pares = [{"termo_a": p["chave_a"], "termo_b": p["chave_b"], **{k: v for k, v in p.items() if k not in ("chave_a", "chave_b")}}
                 for p in cob.pares_sobrepostos(conj, minimo_elegiveis)]
        contidos = [{"termo_id": c["chave"], "n_elegiveis": c["n_itens"], **{k: v for k, v in c.items() if k not in ("chave", "n_itens")}}
                    for c in cob.contidos_em_outro(conj, minimo_elegiveis)]
        return {"minimo_elegiveis": int(minimo_elegiveis), "n_termos_na_matriz": len(m["chaves"]),
                "n_termos_fora": sum(1 for c in conj.values() if 0 < len(c) < int(minimo_elegiveis)),
                "termos": m["chaves"], "rotulos": {t: meta[t].get("query") for t in m["chaves"]},
                "grupos": {t: meta[t].get("grupo") for t in m["chaves"]}, "matriz": m["matriz"], "pares": pares, "contidos": contidos}

    # ---------- 3. cobertura incremental ----------
    def analise_cobertura_incremental(self, incluir_quarentena=False):
        """Ordem gulosa dos termos (cada passo acrescenta o máximo de artigos elegíveis novos) e quantos termos bastam.

        A cobertura é RELATIVA ao universo já coletado: 100% = todos os elegíveis que as buscas feitas trouxeram. O guloso é
        determinístico (desempate: mais ganho, menos créditos, mais elegíveis no total, id) e dá uma boa ordem, não
        necessariamente o menor conjunto possível. Com `incluir_quarentena`, os itens em quarentena contam como elegíveis.

        Devolve {base: 'elegiveis'|'elegiveis_e_quarentena', tem_triagem, universo, n_termos, creditos_total, criterio_desempate,
        passos: [{ordem, termo_id, query, idioma, grupo, n_elegiveis (do termo), ganho, acumulado, pct_acumulado, creditos,
        creditos_acumulados}]
        (todos os termos; os de ganho 0 vêm no fim), marcos: [{percentual (80, 90, 95, 100), atingido, n_chaves, chave_final,
        acumulado, creditos_acumulados}], dispensaveis: [{termo_id, query, n_elegiveis, creditos, sem_resultados}] (ganho 0
        neste universo), n_dispensaveis_sem_elegiveis, creditos_dispensaveis, com_unicos: [{termo_id, query, n_unicos, n_elegiveis}] (não
        podem sair sem perda)}.
        Exemplo: {"universo": 294, "marcos": [{"percentual": 95, "n_chaves": 18, "chave_final": "T33", ...}], ...}."""
        base = self._carregar_termos()
        conj = self._conjuntos_de(base, incluir_quarentena)
        g = cob.cobertura_gulosa(conj, base["creditos"])
        meta = base["meta"]
        dispensaveis = [{"termo_id": d["chave"], "query": meta[d["chave"]].get("query"), "n_elegiveis": d["n_itens"],
                         "creditos": d["creditos"], "sem_resultados": not base["itens"][d["chave"]]} for d in g["dispensaveis"]]
        return {"base": "elegiveis_e_quarentena" if incluir_quarentena else "elegiveis", "tem_triagem": base["tem_triagem"],
                "universo": g["universo"], "n_termos": g["n_chaves"], "creditos_total": g["creditos_total"],
                "criterio_desempate": g["criterio_desempate"], "passos": _enriquecer(g["passos"], meta), "marcos": g["marcos"],
                "dispensaveis": dispensaveis,
                "n_dispensaveis_sem_elegiveis": sum(1 for d in dispensaveis if d["n_elegiveis"] == 0),
                "creditos_dispensaveis": sum(d["creditos"] for d in dispensaveis),
                "com_unicos": [{"termo_id": u["chave"], "query": meta[u["chave"]].get("query"), "n_unicos": u["n_unicos"],
                                "n_elegiveis": u["n_itens"]}
                               for u in g["com_unicos"]]}

    def analise_cobertura_se_mantidos(self, termos_mantidos, incluir_quarentena=False):
        """E se eu mantivesse só estes termos? Cobertura dos artigos elegíveis já coletados e créditos (os que a lista gastou
        e os que a busca inteira gastou). Termo desconhecido vai para `desconhecidos` e não conta.

        Devolve {n_mantidos, desconhecidos, universo, n_cobertos, n_perdidos, pct_cobertos, creditos_mantidos, creditos_total,
        creditos_economizados, termos_descartados}. Exemplo: manter 20 termos retém `pct_cobertos` % dos elegíveis por
        `creditos_mantidos` créditos."""
        base = self._carregar_termos()
        r = cob.simular_mantidos(self._conjuntos_de(base, incluir_quarentena), termos_mantidos or [], base["creditos"])
        r["termos_descartados"] = r.pop("chaves_descartadas")
        return r

    # ---------- 4. web: tecnologia x modelo de consulta ----------
    def analise_cobertura_web(self):
        """Mesma ideia para a coleta web: cada par (tecnologia, modelo de consulta M01/M02...) e cada modelo. Item = par
        (URL, UF) de uma secretaria estadual (resultados municipais ficam de fora); o modelo vem do prefixo de `consulta_id`.
        Elegível = último veredito válido da triagem de escopo (opinião do modelo). UFs não entram na cobertura: uma UF não
        "substitui" outra. Custo = soma de `custo_usd` das buscas web (provedor de busca, não o Gemini).

        Devolve {tem_dados, tem_triagem, n_resultados, n_triados, n_elegiveis, n_quarentena, custo_total_usd,
        por_celula: [{chave, tecnologia, modelo_id, perfil, n_consultas, n_linhas, n_resultados, n_triados, n_elegiveis,
        n_quarentena, n_excluidos, precisao, ic_inf, ic_sup, custo_usd, elegiveis_por_usd, n_elegiveis_unicos,
        pct_elegiveis_de_outros, posicao_media_elegiveis}], por_modelo: [mesmos campos, sem tecnologia],
        sobreposicao_modelos: [{modelo_a, modelo_b, n_a, n_b, n_em_comum, n_uniao, jaccard (dos elegíveis), so_a, so_b,
        jaccard_resultados (de todos os resultados)}],
        incremental: {universo, n_chaves, custo_total, passos: [{ordem, chave, tecnologia, modelo_id, n_elegiveis, ganho, acumulado,
        pct_acumulado, custo_usd, custo_acumulado_usd}], marcos, dispensaveis, com_unicos}}.
        `chave` = "<tecnologia>|<modelo>"."""
        linhas = self._ler("SELECT url_id, uf, consulta_id, tecnologia, perfil, posicao FROM r_resultados_web WHERE cidade IS NULL")
        status = {}
        tem_triagem = self._tem_tabela("triagem_escopo")
        if tem_triagem:
            status = {(l["item_id"], l["uf"]): l["status"] for l in self._ler(
                "SELECT item_id, uf, status FROM (" + _VEREDITO_ATUAL + ") WHERE valido = 1", ("web", "web"))}
        celulas, modelos, perfis, consultas, n_linhas, tecs = {}, {}, {}, {}, Counter(), {}
        for r in linhas:
            modelo, chave = _modelo_da_consulta(r["consulta_id"]), _chave_celula(r["tecnologia"], _modelo_da_consulta(r["consulta_id"]))
            item = (r["url_id"], r["uf"])
            for destino, k in ((celulas, chave), (modelos, modelo)):
                d = destino.setdefault(k, {})
                if item not in d or (r["posicao"] is not None and (d[item] is None or r["posicao"] < d[item])):
                    d[item] = r["posicao"]
            tecs[chave] = (r["tecnologia"] or "(sem tecnologia)", modelo)
            perfis.setdefault(modelo, Counter())[r["perfil"]] += 1
            consultas.setdefault(chave, set()).add(r["consulta_id"])
            n_linhas[chave] += 1
        custo, custo_modelo = Counter(), Counter()
        for c in self._ler("SELECT alvo_id, custo_usd FROM r_chamadas WHERE etapa = 'busca_web' AND sucesso = 1"):
            a = str(c["alvo_id"] or "")
            if a.count("-") != 2:                            # municipal (M11-UF-cidade-tec) ou formato desconhecido
                continue
            modelo, tec = _modelo_da_consulta(a), a.rsplit("-", 1)[-1]
            custo[_chave_celula(tec, modelo)] += c["custo_usd"] or 0
            custo_modelo[modelo] += c["custo_usd"] or 0
        for k in custo:                                      # buscas sem nenhum resultado também gastaram
            if k not in celulas:
                tec, modelo = k.split("|")
                celulas[k], tecs[k] = {}, (tec, modelo)
        for m in custo_modelo:
            modelos.setdefault(m, {})

        def perfil(m):
            return perfis[m].most_common(1)[0][0] if m in perfis else None

        def linha(l, extra, usd):
            r = {k: v for k, v in l.items() if k != "chave"}
            r["elegiveis_por_usd"] = round(l["n_elegiveis"] / usd, 1) if usd else None
            return {**extra, **r}
        ordem_c = sorted(celulas, key=lambda k: (tecs[k][1], tecs[k][0]))
        resumo_c = cob.resumir_chaves(ordem_c, celulas, status, {})
        por_celula = []
        for l in resumo_c:
            k = l["chave"]
            usd = round(custo.get(k, 0), 6)
            r = linha(l, {"chave": k, "tecnologia": tecs[k][0], "modelo_id": tecs[k][1], "perfil": perfil(tecs[k][1]),
                          "n_consultas": len(consultas.get(k, ())), "n_linhas": n_linhas.get(k, 0)}, usd)
            r.pop("creditos"), r.pop("elegiveis_por_credito")
            r["custo_usd"] = usd
            por_celula.append(r)
        ordem_m = sorted(modelos)
        por_modelo = []
        for l in cob.resumir_chaves(ordem_m, modelos, status, {}):
            m = l["chave"]
            usd = round(custo_modelo.get(m, 0), 6)
            r = linha(l, {"modelo_id": m, "perfil": perfil(m)}, usd)
            r.pop("creditos"), r.pop("elegiveis_por_credito")
            r["custo_usd"] = usd
            por_modelo.append(r)
        eleg_m = cob.conjuntos_por_status(modelos, status)
        sobre = []
        for i, a in enumerate(ordem_m):
            for b in ordem_m[i + 1:]:
                ea, eb = eleg_m[a], eleg_m[b]
                sobre.append({"modelo_a": a, "modelo_b": b, "n_a": len(ea), "n_b": len(eb), "n_em_comum": len(ea & eb),
                              "n_uniao": len(ea | eb), "jaccard": cob.jaccard(ea, eb), "so_a": len(ea - eb), "so_b": len(eb - ea),
                              "jaccard_resultados": cob.jaccard(set(modelos[a]), set(modelos[b]))})
        eleg_c = cob.conjuntos_por_status(celulas, status)
        g = cob.cobertura_gulosa(eleg_c, {k: custo.get(k, 0) for k in celulas})
        passos = []
        for p in g["passos"]:
            tec, mod = tecs[p["chave"]]
            passos.append({"ordem": p["ordem"], "chave": p["chave"], "tecnologia": tec, "modelo_id": mod, "n_elegiveis": p["n_itens"], "ganho": p["ganho"],
                           "acumulado": p["acumulado"], "pct_acumulado": p["pct_acumulado"], "custo_usd": round(p["creditos"], 6),
                           "custo_acumulado_usd": round(p["creditos_acumulados"], 6)})
        todos = set().union(*[set(d) for d in modelos.values()]) if modelos else set()
        triados = [status[i] for i in todos if i in status]
        return {"tem_dados": bool(linhas), "tem_triagem": tem_triagem and bool(status), "n_resultados": len(todos),
                "n_triados": len(triados), "n_elegiveis": triados.count("elegivel"), "n_quarentena": triados.count("quarentena"),
                "custo_total_usd": round(sum(custo.values()), 6), "por_celula": por_celula, "por_modelo": por_modelo,
                "sobreposicao_modelos": sobre,
                "incremental": {"universo": g["universo"], "n_chaves": g["n_chaves"], "custo_total": round(g["creditos_total"], 6),
                                "passos": passos, "marcos": g["marcos"], "dispensaveis": g["dispensaveis"], "com_unicos": g["com_unicos"],
                                "criterio_desempate": g["criterio_desempate"]}}

    # ---------- 5. combinações (ponto de extensão) ----------
    def analise_ganho_combinacoes(self):
        """Ganho de cada consulta COMPOSTA sobre o seu termo pai (`Termo.pai`, view `v_ganho_contexto`). Hoje não há termo
        composto (o piloto RD4 ainda não foi autorizado): a view vem vazia e o método devolve [].

        Quando houver, cada linha traz as colunas da view (termo_composto, termo_pai, query, n_artigos_composto, n_artigos_pai,
        n_em_comum, so_no_composto, so_no_pai, n_incluidos_*, incluidos_so_no_*, taxa_inclusao_*_pct) e, calculados aqui com a
        triagem de escopo: n_elegiveis_composto, n_elegiveis_pai, elegiveis_em_comum, elegiveis_so_no_composto,
        elegiveis_so_no_pai, creditos_composto, elegiveis_novos_por_credito (elegíveis só no composto por crédito gasto).
        Sem a view (banco antigo), devolve []."""
        linhas = self._ler("SELECT * FROM v_ganho_contexto")
        if not linhas:
            return []
        base = self._carregar_termos()
        conj = self._conjuntos_de(base)
        saida = []
        for l in linhas:
            g = cob.ganho_de_composto(conj, l.get("termo_composto"), l.get("termo_pai"))
            cred = base["creditos"].get(l.get("termo_composto"), 0)
            saida.append({**l, "n_elegiveis_composto": g["n_composto"], "n_elegiveis_pai": g["n_pai"],
                          "elegiveis_em_comum": g["em_comum"], "elegiveis_so_no_composto": g["so_no_composto"],
                          "elegiveis_so_no_pai": g["so_no_pai"], "creditos_composto": cred,
                          "elegiveis_novos_por_credito": round(g["so_no_composto"] / cred, 3) if cred else None})
        return saida
