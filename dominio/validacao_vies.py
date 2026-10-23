"""Validacao humana da triagem do banco `vies` por amostra (RB34): o sorteio estratificado pela relevancia que o modelo deu,
a resposta da pessoa (sem ver a do modelo) e a concordancia entre as duas. Python puro."""
from dominio import analises_vies as AV
from dominio import estatistica as est
from dominio.triagem_escopo import _h

SEMENTE = "validacao-vies-v1"
TAMANHO = 40
MINIMO_POR_ESTRATO = 4                       # cada relevancia aparece (os fora do escopo sao poucos)
CAMPOS = ("relevancia", "grupo", "eixo", "pais")
PAISES = ("brasil", "outro", "indeterminado")
SEM_EIXO = "nenhum"
FONTES = {"W": "referencia", "A": "artigo"}  # o prefixo do id do item da analise (W-1, A-7) e a fonte da triagem


def alocacao(tamanhos, n=TAMANHO, minimo=MINIMO_POR_ESTRATO):
    """{estrato: itens a sortear}: primeiro min(minimo, tamanho) em cada estrato; o resto proporcional ao que sobra em
    cada um (maiores restos; empate pela ordem de `tamanhos`). Com menos itens que `n`, todos."""
    tamanhos = {e: t for e, t in tamanhos.items() if t > 0}
    total = sum(tamanhos.values())
    if total <= n:
        return dict(tamanhos)
    base = {e: min(minimo, t) for e, t in tamanhos.items()}
    resto = n - sum(base.values())
    if resto < 0:
        raise ValueError("amostra menor que o mínimo por estrato")
    sobra = {e: tamanhos[e] - base[e] for e in tamanhos}
    total_sobra = sum(sobra.values())
    cotas = {e: resto * s / total_sobra for e, s in sobra.items()}
    extra = {e: int(c) for e, c in cotas.items()}
    ordem = sorted(tamanhos, key=lambda e: (-(cotas[e] - extra[e]), list(tamanhos).index(e)))
    for e in ordem[:resto - sum(extra.values())]:
        extra[e] += 1
    return {e: base[e] + extra[e] for e in tamanhos}


def respostas_do_modelo(item, eixos):
    """As quatro respostas do modelo no vocabulario da validacao (o que a pessoa escolhe)."""
    eixo = item["eixo"] if item["eixo"] in eixos else SEM_EIXO
    return {"relevancia": item["relevancia"], "grupo": AV.grupo_do_tipo(item["tipo_fonte"]), "eixo": eixo,
            "pais": AV.categoria_pais(item["pais"])}


def sortear(itens, triagens, eixos, n=TAMANHO, semente=SEMENTE):
    """A amostra: [{ordem, fonte, item_id, triagem_id, estrato, estrato_tamanho, modelo_*}], so dos itens com triagem
    valida e tipo de fonte (sem tipo, a pessoa nao teria como concordar no grupo). Estratos pela relevancia do modelo
    (`alocacao`); dentro de cada um, pela ordem do sha1 da semente; a lista final tambem vai na ordem do sha1 (quem
    confere nao ve os estratos em bloco)."""
    candidatos = []
    for i in itens:
        if i["relevancia"] not in AV.RELEVANCIAS or AV.grupo_do_tipo(i["tipo_fonte"]) is None:
            continue
        fonte, item_id = FONTES[i["id"][0]], int(i["id"][2:])
        t = triagens.get((fonte, item_id))
        if not t:
            continue
        candidatos.append((i, fonte, item_id, t["id"]))
    tamanhos = {r: sum(1 for c in candidatos if c[0]["relevancia"] == r) for r in AV.RELEVANCIAS}
    cotas = alocacao(tamanhos, n)
    escolhidos = []
    for r, k in cotas.items():
        do_estrato = sorted((c for c in candidatos if c[0]["relevancia"] == r), key=lambda c: _h(semente, f"{c[1]}|{c[2]}"))
        escolhidos += do_estrato[:k]
    escolhidos.sort(key=lambda c: _h(semente + "|mistura", f"{c[1]}|{c[2]}"))
    return [{"ordem": pos, "fonte": fonte, "item_id": item_id, "triagem_id": tid, "estrato": i["relevancia"],
             "estrato_tamanho": tamanhos[i["relevancia"]],
             **{f"modelo_{campo}": v for campo, v in respostas_do_modelo(i, eixos).items()}}
            for pos, (i, fonte, item_id, tid) in enumerate(escolhidos, 1)]


def opcoes(eixos):
    """Os valores aceitos em cada campo da resposta, na ordem do formulario."""
    return {"relevancia": AV.RELEVANCIAS, "grupo": AV.GRUPOS, "eixo": tuple(eixos) + (SEM_EIXO,), "pais": PAISES}


def conferir_resposta(valores, eixos):
    """(resposta, erros). Cada campo e obrigatorio e tem de ser exatamente uma das `opcoes` (vem de uma lista de escolha:
    nada e aparado); erros na ordem de CAMPOS."""
    ops, limpa, erros = opcoes(eixos), {}, []
    for campo in CAMPOS:
        v = valores.get(campo)
        v = v if isinstance(v, str) else ""
        if not v.strip():
            erros.append(f"Escolha a opção de {ROTULOS[campo]}.")
        elif v not in ops[campo]:
            erros.append(f"Opção inválida em {ROTULOS[campo]}.")
        else:
            limpa[campo] = v
    return limpa, erros


ROTULOS = {"relevancia": "relevância", "grupo": "tipo de fonte", "eixo": "eixo temático", "pais": "país"}


def concordancia(linhas, eixos):
    """Por campo: {n, iguais, proporcao, kappa (o dict de `estatistica.kappa_cohen`), faixa, matriz, categorias}, na
    amostra sem ponderar; mais `elegivel` (alta ou media) e a concordancia da elegibilidade estimada para todos os itens
    triados, pesando cada estrato pelo seu tamanho (None enquanto algum estrato sorteado nao tiver resposta). So as linhas
    respondidas contam. Valor fora das opcoes (eixo que mudou depois do sorteio) vira categoria propria."""
    respondidas = [l for l in linhas if l.get("relevancia")]
    sorteados = {l["estrato"] for l in linhas}
    ops = opcoes(eixos)
    saida = {}
    for campo in CAMPOS:
        cats = list(ops[campo])
        pares = [(l[f"modelo_{campo}"], l[campo]) for l in respondidas]
        saida[campo] = _par(pares, cats)
    elegivel = [(l["modelo_relevancia"] in AV.ELEGIVEIS, l["relevancia"] in AV.ELEGIVEIS) for l in respondidas]
    saida["elegivel"] = _par([("sim" if a else "não", "sim" if b else "não") for a, b in elegivel], ["sim", "não"])
    por_estrato = {}
    for l, (a, b) in zip(respondidas, elegivel):
        e = por_estrato.setdefault(l["estrato"], {"tamanho": l["estrato_tamanho"], "n": 0, "iguais": 0})
        e["n"] += 1
        e["iguais"] += a == b
    peso_total = sum(e["tamanho"] for e in por_estrato.values())
    saida["elegivel_estimada"] = (sum(e["tamanho"] * e["iguais"] / e["n"] for e in por_estrato.values()) / peso_total
                                  if peso_total and set(por_estrato) == sorteados else None)
    saida["estratos"] = por_estrato
    return saida


def _par(pares, cats):
    """Matriz modelo x pessoa nas `cats` (valor fora delas vira linha propria no fim) e o kappa de Cohen."""
    for a, b in pares:
        for v in (a, b):
            if v not in cats:
                cats.append(v)
    idx = {c: k for k, c in enumerate(cats)}
    matriz = [[0] * len(cats) for _ in cats]
    for a, b in pares:
        matriz[idx[a]][idx[b]] += 1
    iguais = sum(matriz[k][k] for k in range(len(cats)))
    n = len(pares)
    kappa = est.kappa_cohen(matriz) if n else {"kappa": None}
    return {"n": n, "iguais": iguais, "proporcao": iguais / n if n else None, "kappa": kappa, "matriz": matriz,
            "categorias": cats, "faixa": est.faixa_kappa(kappa["kappa"]) if kappa["kappa"] is not None else None}
