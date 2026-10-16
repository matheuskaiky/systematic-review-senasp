"""Cobertura e redundância de termos de busca (análise RG5): funções puras, sem I/O.

Pergunta que o módulo responde, sem gastar nada: com os artigos (ou páginas) que JÁ estão no banco, quais termos valem os
seus créditos e quais são redundantes?

Duas ressalvas valem para tudo aqui e aparecem nos textos do painel:

1. "Elegível" é a opinião do modelo sobre o escopo (triagem de escopo), não uma inclusão humana.
2. Toda cobertura é RELATIVA ao universo já coletado: "o termo X acrescenta 0 artigos" quer dizer "acrescenta 0 artigos
   elegíveis dentre os que as 46 buscas já trouxeram", não "o termo X é inútil para o tema". Não é revocação verdadeira.

Convenções das entradas (todas simples, hashable e JSON-friendly):
- `itens_por_chave`: {chave: {item_id: posicao_ou_None}}. A chave é o termo (ou o par tecnologia x modelo); `item_id` é o
  `artigo_id` (ou o par (url_id, uf)); a posição é a MELHOR (menor) posição do item naquela chave.
- `status_por_item`: {item_id: 'elegivel' | 'quarentena' | 'excluido'}, só com veredito válido. Item sem veredito não conta
  como triado.
- `conjuntos`: {chave: conjunto de item_id} (por exemplo, só os elegíveis de cada termo).
- `creditos`: {chave: número de créditos (ou custo) gasto pela chave}; chave ausente vale 0.

Convenção das saídas: `precisao`, `ic_*` e frações vão de 0 a 1; campos `pct_*` vão de 0 a 100 (uma casa decimal).
Divisão sem denominador devolve None."""
from dominio import estatistica as est

# Percentuais do universo elegível que a curva incremental marca (menor prefixo de termos que alcança cada um).
MARCOS_COBERTURA = (80, 90, 95, 100)

# Matriz de Jaccard: só entram termos com ao menos esta quantidade de elegíveis (com menos, a proporção oscila demais).
MINIMO_ELEGIVEIS_MATRIZ = 5

# Tamanho da faixa de posições do Scholar (1-10, 11-20, ...), igual à análise de retorno por posição.
FAIXA_POSICOES = 10

CRITERIO_DESEMPATE = ("maior ganho de itens novos; empate: menos créditos; empate: mais itens elegíveis no total; "
                      "empate: chave em ordem alfabética (T02 antes de T10)")

STATUS_ELEGIVEL = ("elegivel",)
STATUS_ELEGIVEL_E_QUARENTENA = ("elegivel", "quarentena")


def _pct(parte, total):
    return round(100.0 * parte / total, 1) if total else None


def _fracao(parte, total):
    return round(parte / total, 4) if total else None


def _arred(x):
    return None if x is None else round(x, 4)


# ---------- conjuntos ----------
def conjuntos_por_status(itens_por_chave, status_por_item, status=STATUS_ELEGIVEL):
    """{chave: frozenset(itens da chave cujo veredito está em `status`)}. Todas as chaves aparecem, mesmo vazias."""
    return {c: frozenset(i for i in itens if status_por_item.get(i) in status) for c, itens in itens_por_chave.items()}


def jaccard(a, b):
    """Jaccard = |A ∩ B| / |A ∪ B| (0 a 1). Dois conjuntos vazios não têm sobreposição definida: devolve None."""
    uniao = len(a | b)
    return round(len(a & b) / uniao, 4) if uniao else None


def itens_unicos(conjuntos):
    """{chave: conjunto dos itens que SÓ essa chave traz} (os que somem se a chave sair)."""
    contagem = {}
    for itens in conjuntos.values():
        for i in itens:
            contagem[i] = contagem.get(i, 0) + 1
    return {c: frozenset(i for i in itens if contagem[i] == 1) for c, itens in conjuntos.items()}


def universo(conjuntos):
    """União de todos os conjuntos."""
    todos = set()
    for itens in conjuntos.values():
        todos |= itens
    return todos


# ---------- 1. resumo por chave ----------
def _melhor_posicao_media(posicoes):
    validas = [p for p in posicoes if p is not None]
    return round(sum(validas) / len(validas), 1) if validas else None


def resumir_chaves(chaves, itens_por_chave, status_por_item, creditos=None):
    """Uma linha por chave, na ordem de `chaves`.

    Campos: chave, n_resultados (itens distintos), n_triados (com veredito válido), n_elegiveis, n_quarentena, n_excluidos,
    n_elegiveis_mais_quarentena, precisao = n_elegiveis / n_triados com intervalo de Wilson 95% (ic_inf, ic_sup),
    creditos, elegiveis_por_credito (None se não gastou), n_elegiveis_unicos (só esta chave traz),
    pct_elegiveis_de_outros (dos elegíveis da chave, quantos OUTRA chave também traz; None sem elegíveis),
    posicao_media_elegiveis (média da melhor posição dos elegíveis; None se não há posição)."""
    creditos = creditos or {}
    elegiveis = conjuntos_por_status(itens_por_chave, status_por_item, STATUS_ELEGIVEL)
    unicos = itens_unicos(elegiveis)
    saida = []
    for c in chaves:
        itens = itens_por_chave.get(c, {})
        triados = [i for i in itens if i in status_por_item]
        n_eleg = len(elegiveis.get(c, ()))
        n_quar = sum(1 for i in triados if status_por_item[i] == "quarentena")
        n_exc = sum(1 for i in triados if status_por_item[i] == "excluido")
        inf, sup = est.intervalo_wilson(n_eleg, len(triados)) if triados else (None, None)
        cred = creditos.get(c, 0) or 0
        n_unicos = len(unicos.get(c, ()))
        saida.append({
            "chave": c, "n_resultados": len(itens), "n_triados": len(triados), "n_elegiveis": n_eleg, "n_quarentena": n_quar,
            "n_excluidos": n_exc, "n_elegiveis_mais_quarentena": n_eleg + n_quar,
            "precisao": _fracao(n_eleg, len(triados)), "ic_inf": _arred(inf), "ic_sup": _arred(sup),
            "creditos": cred, "elegiveis_por_credito": round(n_eleg / cred, 3) if cred else None,
            "n_elegiveis_unicos": n_unicos,
            "pct_elegiveis_de_outros": _pct(n_eleg - n_unicos, n_eleg),
            "posicao_media_elegiveis": _melhor_posicao_media([itens[i] for i in elegiveis.get(c, ())]),
        })
    return saida


# ---------- 2. redundância ----------
def matriz_jaccard(conjuntos, minimo=MINIMO_ELEGIVEIS_MATRIZ, ordem=None):
    """Matriz de Jaccard entre as chaves com pelo menos `minimo` itens. A ordem é a de `ordem` (lista de chaves; as que ela
    não cita vão ao fim, em ordem alfabética); sem `ordem`, alfabética.

    Devolve {chaves, matriz} com matriz[i][j] = Jaccard (diagonal 1.0; None se união vazia, o que não acontece com minimo >= 1)."""
    posicao = {c: i for i, c in enumerate(ordem or [])}
    chaves = sorted((c for c, itens in conjuntos.items() if len(itens) >= max(int(minimo), 1)),
                    key=lambda c: (posicao.get(c, len(posicao)), c))
    matriz = [[1.0 if a == b else jaccard(conjuntos[a], conjuntos[b]) for b in chaves] for a in chaves]
    return {"chaves": chaves, "matriz": matriz}


def pares_sobrepostos(conjuntos, minimo=MINIMO_ELEGIVEIS_MATRIZ):
    """Pares (a < b) com ao menos um item em comum, do mais ao menos sobreposto. Só chaves com >= `minimo` itens.

    Cada par: {chave_a, chave_b, n_a, n_b, n_em_comum, n_uniao, jaccard}."""
    chaves = sorted(c for c, itens in conjuntos.items() if len(itens) >= max(int(minimo), 1))
    saida = []
    for i, a in enumerate(chaves):
        for b in chaves[i + 1:]:
            comum = len(conjuntos[a] & conjuntos[b])
            if comum:
                saida.append({"chave_a": a, "chave_b": b, "n_a": len(conjuntos[a]), "n_b": len(conjuntos[b]), "n_em_comum": comum,
                              "n_uniao": len(conjuntos[a] | conjuntos[b]), "jaccard": jaccard(conjuntos[a], conjuntos[b])})
    saida.sort(key=lambda p: (-p["jaccard"], p["chave_a"], p["chave_b"]))
    return saida


def contidos_em_outro(conjuntos, minimo=MINIMO_ELEGIVEIS_MATRIZ):
    """Relação "está contido em": para cada chave A (com >= `minimo` itens), a OUTRA chave B que contém a maior parte dos itens
    de A (empate: mais itens em comum, depois ordem alfabética).

    Cada linha: {chave, n_itens, contido_em, n_contido (|A ∩ B|), pct_contido (|A ∩ B| / |A|, 0 a 100),
    pct_nos_demais (parte de A que QUALQUER outra chave também traz, 0 a 100)}. `contido_em` é None se nenhuma outra chave
    compartilha item. Ordenado do mais ao menos contido."""
    saida = []
    for a, itens in conjuntos.items():
        if len(itens) < max(int(minimo), 1):
            continue
        melhor, n_melhor = None, 0
        for b in sorted(conjuntos):
            if b == a:
                continue
            n = len(itens & conjuntos[b])
            if n > n_melhor:
                melhor, n_melhor = b, n
        outros = set()
        for b, ib in conjuntos.items():
            if b != a:
                outros |= ib & itens
        saida.append({"chave": a, "n_itens": len(itens), "contido_em": melhor, "n_contido": n_melhor,
                      "pct_contido": _pct(n_melhor, len(itens)), "pct_nos_demais": _pct(len(outros), len(itens))})
    saida.sort(key=lambda l: (-(l["pct_contido"] or 0), -(l["pct_nos_demais"] or 0), l["chave"]))
    return saida


# ---------- 3. cobertura incremental (cobertura de conjuntos, método guloso) ----------
def cobertura_gulosa(conjuntos, creditos=None, marcos=MARCOS_COBERTURA):
    """Ordena TODAS as chaves para que cada passo acrescente o máximo de itens novos (algoritmo guloso de cobertura de conjuntos).

    O guloso é determinístico (desempate em `CRITERIO_DESEMPATE`) e dá uma boa ordem, mas não garante o menor conjunto
    possível. O universo é a união dos conjuntos: a cobertura é relativa ao que já foi coletado.

    Devolve {universo, n_chaves, creditos_total, passos, marcos, dispensaveis, com_unicos, criterio_desempate}:
    - passos: [{ordem (1...), chave, n_itens (tamanho do conjunto), ganho (itens novos), acumulado, pct_acumulado (0 a 100; None se universo 0), creditos,
      creditos_acumulados}] com todas as chaves; as que não trazem nada novo vêm no fim, com ganho 0;
    - marcos: [{percentual, atingido, n_chaves, chave_final, acumulado, creditos_acumulados}], o MENOR prefixo da ordem que
      alcança cada percentual (`atingido` False e o resto None quando o universo é vazio);
    - dispensaveis: chaves de ganho 0 neste universo, na ordem do guloso ({chave, n_itens, creditos});
    - com_unicos: chaves que têm itens que mais ninguém traz, e portanto não podem sair sem perda ({chave, n_unicos, n_itens})."""
    creditos = creditos or {}
    restantes = {c: set(itens) for c, itens in conjuntos.items()}
    total = len(universo(conjuntos))
    coberto, passos = set(), []
    cred_acum = 0
    while restantes:
        def prioridade(c):
            return (-len(restantes[c] - coberto), creditos.get(c, 0) or 0, -len(conjuntos[c]), c)
        c = min(restantes, key=prioridade)
        ganho = len(restantes.pop(c) - coberto)
        coberto |= conjuntos[c]
        cred = creditos.get(c, 0) or 0
        cred_acum = round(cred_acum + cred, 6)           # custo em dólar acumula erro de ponto flutuante
        passos.append({"ordem": len(passos) + 1, "chave": c, "n_itens": len(conjuntos[c]), "ganho": ganho, "acumulado": len(coberto),
                       "pct_acumulado": _pct(len(coberto), total), "creditos": cred, "creditos_acumulados": cred_acum})
    saida_marcos = []
    for p in marcos:
        alvo = next((x for x in passos if total and x["acumulado"] * 100 >= p * total), None)
        saida_marcos.append({"percentual": p, "atingido": alvo is not None, "n_chaves": alvo["ordem"] if alvo else None,
                             "chave_final": alvo["chave"] if alvo else None, "acumulado": alvo["acumulado"] if alvo else None,
                             "creditos_acumulados": alvo["creditos_acumulados"] if alvo else None})
    unicos = itens_unicos(conjuntos)
    return {"universo": total, "n_chaves": len(passos), "creditos_total": cred_acum, "passos": passos, "marcos": saida_marcos,
            "dispensaveis": [{"chave": x["chave"], "n_itens": len(conjuntos[x["chave"]]), "creditos": x["creditos"]}
                             for x in passos if x["ganho"] == 0],
            "com_unicos": sorted(({"chave": c, "n_unicos": len(u), "n_itens": len(conjuntos[c])} for c, u in unicos.items() if u),
                                 key=lambda l: (-l["n_unicos"], l["chave"])),
            "criterio_desempate": CRITERIO_DESEMPATE}


def simular_mantidos(conjuntos, mantidos, creditos=None):
    """E se eu mantivesse só estas chaves? Cobertura dos itens (relativa ao universo coletado) e créditos.

    `mantidos` pode trazer chaves que não existem: elas vão para `desconhecidos` e não contam. Devolve {n_mantidos,
    desconhecidos, universo, n_cobertos, n_perdidos, pct_cobertos (None se universo 0), creditos_mantidos, creditos_total,
    creditos_economizados, chaves_descartadas}."""
    creditos = creditos or {}
    unicas = sorted(set(mantidos))
    validas = [c for c in unicas if c in conjuntos]
    cobertos = set()
    for c in validas:
        cobertos |= conjuntos[c]
    total = len(universo(conjuntos))
    cred_mant = round(sum(creditos.get(c, 0) or 0 for c in validas), 6)
    cred_total = round(sum(creditos.get(c, 0) or 0 for c in conjuntos), 6)
    return {"n_mantidos": len(validas), "desconhecidos": [c for c in unicas if c not in conjuntos], "universo": total,
            "n_cobertos": len(cobertos), "n_perdidos": total - len(cobertos), "pct_cobertos": _pct(len(cobertos), total),
            "creditos_mantidos": cred_mant, "creditos_total": cred_total, "creditos_economizados": round(cred_total - cred_mant, 6),
            "chaves_descartadas": sorted(c for c in conjuntos if c not in set(validas))}


# ---------- 4. idioma e posição ----------
def ganho_por_idioma(itens_por_chave, idioma_por_chave, status_por_item):
    """Itens achados só por termos em português, só em inglês, ou por ambos (a classe de um item vem dos idiomas dos termos que o
    acharam; termo sem idioma conhecido não conta para nenhum lado e o item que só ele achou vai para `sem_idioma`).

    Uma linha por classe existente, na ordem apenas_pt, apenas_en, ambos, sem_idioma: {achado_por, n_artigos, n_triados,
    n_elegiveis, n_quarentena, n_excluidos, precisao, ic_inf, ic_sup, pct_dos_elegiveis (parte de todos os elegíveis do universo)}."""
    idiomas = {}
    for c, itens in itens_por_chave.items():
        for i in itens:
            idiomas.setdefault(i, set()).add(idioma_por_chave.get(c))
    classes = {}
    for i, ids in idiomas.items():
        pt, en = "pt" in ids, "en" in ids
        classe = "ambos" if pt and en else "apenas_pt" if pt else "apenas_en" if en else "sem_idioma"
        classes.setdefault(classe, []).append(i)
    n_elegiveis_total = sum(1 for i in idiomas if status_por_item.get(i) == "elegivel")
    saida = []
    for classe in ("apenas_pt", "apenas_en", "ambos", "sem_idioma"):
        itens = classes.get(classe)
        if not itens:
            continue
        triados = [status_por_item[i] for i in itens if i in status_por_item]
        n_eleg = triados.count("elegivel")
        inf, sup = est.intervalo_wilson(n_eleg, len(triados)) if triados else (None, None)
        saida.append({"achado_por": classe, "n_artigos": len(itens), "n_triados": len(triados), "n_elegiveis": n_eleg,
                      "n_quarentena": triados.count("quarentena"), "n_excluidos": triados.count("excluido"),
                      "precisao": _fracao(n_eleg, len(triados)), "ic_inf": _arred(inf), "ic_sup": _arred(sup),
                      "pct_dos_elegiveis": _pct(n_eleg, n_elegiveis_total)})
    return saida


def retorno_por_faixa_e_grupo(itens_por_chave, grupo_por_chave, status_por_item, faixa=FAIXA_POSICOES):
    """Por grupo de termo e faixa de posições: quantos itens triados e quantos elegíveis. Cada item conta uma vez por grupo, na
    MELHOR posição que algum termo do grupo lhe deu; item sem posição ou sem veredito válido fica de fora.

    Linhas ordenadas por grupo e faixa: {grupo, faixa (1 = posições 1-10), rotulo, n_triados, n_elegiveis, pct_elegiveis}."""
    melhor = {}
    for c, itens in itens_por_chave.items():
        grupo = grupo_por_chave.get(c) or "sem_grupo"
        for i, pos in itens.items():
            if pos is None or pos < 1 or i not in status_por_item:
                continue
            chave = (grupo, i)
            if chave not in melhor or pos < melhor[chave]:
                melhor[chave] = pos
    celulas = {}
    for (grupo, i), pos in melhor.items():
        k = (pos - 1) // faixa + 1
        cel = celulas.setdefault((grupo, k), [0, 0])
        cel[0] += 1
        cel[1] += 1 if status_por_item[i] == "elegivel" else 0
    return [{"grupo": g, "faixa": k, "rotulo": f"{(k - 1) * faixa + 1}-{k * faixa}", "n_triados": n, "n_elegiveis": e,
             "pct_elegiveis": _pct(e, n)} for (g, k), (n, e) in sorted(celulas.items())]


# ---------- 5. termos compostos (ponto de extensão) ----------
def ganho_de_composto(conjuntos, composto, pai):
    """O que a consulta composta acrescenta ao termo pai, em itens elegíveis: {n_composto, n_pai, em_comum, so_no_composto,
    so_no_pai}. Chave ausente conta como conjunto vazio."""
    a, b = conjuntos.get(composto, frozenset()), conjuntos.get(pai, frozenset())
    return {"n_composto": len(a), "n_pai": len(b), "em_comum": len(a & b), "so_no_composto": len(a - b), "so_no_pai": len(b - a)}
