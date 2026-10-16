"""Analise por termo, auditoria do pre-filtro da web e teste barato de combinacoes (RE7 e RD12). Funcoes puras (sem I/O):
listas e dicionarios entram e saem. Nada aqui decide pela pessoa: tudo e SUGESTAO PARA AVALIACAO DO PESQUISADOR e nada e aplicado.

O veredito do modelo (`elegivel`, `quarentena`, `excluido`) e uma opiniao sobre o escopo, nao um achado confirmado. Toda
proporcao sai com o intervalo de Wilson de 95% (`dominio.estatistica.intervalo_wilson`), porque os grupos costumam ser pequenos.

Tres blocos:
1. Auditoria do pre-filtro de palavras-chave da web (`auditar_prefiltro`): quantos resultados elegiveis o pre-filtro e o limite
   por UF deixaram de baixar, que teto por UF os teria pegado e que palavras (ainda fora do pre-filtro) aparecem mais nesses
   resultados do que nos selecionados.
2. Tabela por termo (`tabela_por_termo`): quanto de cada termo e elegivel, qual o principal motivo e area do ruido e uma
   acao sugerida por regra transparente (as constantes `LIMITE_*` abaixo).
3. Simulacao de consulta composta como FILTRO sobre os resultados ja guardados do termo (`simular_contextos`): quantos
   elegiveis ficariam, quanto ruido sairia e quantos uteis se perderiam. So ve o topo do ranking que o termo ja trouxe."""
import math

from dominio import estatistica as est
from dominio.refinamento_busca import STATUS, contem_frase, normalizar_texto

# ---------- constantes ----------
LIMITE_PERDA_UTEIS = 0.10          # fracao de elegiveis perdidos acima da qual a candidata e marcada "perde muitos uteis"
MIN_SUPORTE = 3                    # frequencia minima (itens que contem a palavra) para uma palavra ser candidata (termos)
MIN_SUPORTE_PREFILTRO = 5          # idem, para as palavras candidatas ao pre-filtro da web (a frente tem ~115 itens)
MAX_CANDIDATAS_PALAVRAS = 20       # palavras candidatas ao pre-filtro devolvidas
MAX_CANDIDATAS_AUTOMATICAS = 5     # palavras de contexto achadas por contraste, por termo
SUAVIZACAO = 0.5                   # constante somada as contagens da razao de chances suavizada
TAMANHO_MINIMO_PALAVRA = 3
N_MINIMO_TERMO = 10                # abaixo disso, o termo e "amostra pequena"
LIMITE_ELEGIVEL_MANTER = 0.5       # fracao elegivel a partir da qual o termo e "manter"
LIMITE_ELEGIVEL_REVISAR = 0.25     # abaixo disso, sem area dominante: "revisar o termo"
FRACAO_AREA_DOMINANTE = 0.4        # a area tematica do ruido e dominante se tem ao menos esta fracao do ruido...
MIN_ITENS_AREA_DOMINANTE = 5       # ...e ao menos estes itens
LIMITE_INTERNACIONAL = 0.5         # fracao internacional a partir da qual se avisa
N_MINIMO_ELEGIVEIS_SIMULACAO = 5   # abaixo disso a simulacao do termo e marcada "amostra pequena"
PASSO_TETO = 10                    # passo da curva de teto por UF

ROTULO_MOTIVO = {
    "selecionada": "Selecionados para download",
    "nao_selecionada": "Não selecionados (todos os motivos)",
    "prefiltro_palavras": "Descartados pelo pré-filtro de palavras",
    "limite_por_uf": "Descartados pelo limite por UF",
    "dominio_excluido": "Descartados por domínio excluído",
    "nao_oficial": "Descartados por fonte não oficial",
    "sem_motivo": "Descartados sem motivo registrado",
}

# Palavras sem valor para distinguir grupos (sem acento, minusculas); inclui algumas inglesas porque os termos em ingles
# trazem artigos em ingles e tokens de endereco (www, http) que aparecem nos resumos da web.
PALAVRAS_VAZIAS_PT = frozenset("""
a as o os um uma uns umas de da do das dos em na no nas nos por para com sem sob sobre entre ate ao aos e ou mas que se como
mais menos muito muita muitos muitas ja nao sim foi ser sao era eram sera esta estao estar este esse essa estes esses essas
isto isso aquele aquela seu sua seus suas pelo pela pelos pelas num numa tem ter tinha pode podem ha tambem quando onde qual
quais quem cada outro outra outros outras todo toda todos todas apos desde durante contra ainda assim entao pois porque
the and of in to for on with by from is are an at this that its or be as it was were has have not which their
http https www gov com org html pdf
""".split())

# Contextos candidatos para a simulacao (RD12). NAO sao aprovados: a lista em portugues e a do pedido do pesquisador; a em
# ingles e a variante do piloto proposto no guia do projeto (secao 6.5). Servem para ordenar e descartar candidatas.
CONTEXTOS_PADRAO = ("segurança pública", "polícia", "policiamento", "criminal", "crime", "Brasil", "brasileiro", "delegacia",
                    "forças de segurança")
CONTEXTOS_PADRAO_EN = ("public security", "police", "policing", "Brazil", "Brazilian")
GRUPO_OU_PT = ("segurança pública", "polícia", "policiamento")        # variante A do piloto: ("segurança pública" OR polícia OR policiamento)
GRUPO_OU_EN = ("public security", "police", "policing")

AVISO_PREFILTRO = ("Sugestão para avaliação do pesquisador: nada foi aplicado. 'Elegível' é opinião do modelo sobre o escopo, "
                   "não achado confirmado.")
# Palavras centrais do tema: um operador negativo que as contenha e sempre "perigoso" (ver `refinamento_busca.avaliar_negativos`).
PALAVRAS_CENTRAIS_PADRAO = ("segurança pública", "inteligência artificial", "polícia", "policiamento", "reconhecimento facial",
                            "leitura de placas", "videomonitoramento inteligente", "análise preditiva", "policiamento preditivo")
LIMITES_SIMULACAO = (
    "A simulação só enxerga os resultados que o termo sozinho já devolveu (o topo do ranking, até 60); ela não sabe o que uma "
    "consulta composta traria de mais fundo no ranking.",
    "O Google Scholar pode interpretar operadores (aspas, OR, parênteses) de outro modo e casar por radical ou sinônimo; aqui "
    "o casamento é por palavra inteira, sem acento nem maiúscula, em título e resumo.",
    "O casamento é só em título e resumo curto, e o Scholar procura no texto inteiro: por isso a retenção simulada tende a ficar "
    "abaixo da real e o ruído removido acima da real (um artigo cujo texto cita o contexto, mas o resumo não, seria mantido de "
    "verdade e aqui aparece como removido).",
    "'Elegível' e 'excluído' são opiniões do modelo, não decisões humanas. A amostra real de 1 página (RD4, ainda não autorizada) "
    "é a confirmação.",
)


# ---------- estatistica basica ----------
def proporcao(k, n):
    """Proporcao k/n com intervalo de Wilson 95%, em percentual (0 a 100, uma casa).

    Devolve {"k", "n", "pct", "ic_inf", "ic_sup"}; sem denominador (n = 0) os tres ultimos sao None. k e limitado a [0, n]."""
    n = max(int(n or 0), 0)
    k = min(max(int(k or 0), 0), n)
    if not n:
        return {"k": k, "n": n, "pct": None, "ic_inf": None, "ic_sup": None}
    inf, sup = est.intervalo_wilson(k, n)
    return {"k": k, "n": n, "pct": round(100.0 * k / n, 1), "ic_inf": round(100.0 * inf, 1), "ic_sup": round(100.0 * sup, 1)}


def _pct(parte, total):
    return round(100.0 * parte / total, 1) if total else None


def _validos(itens):
    """Itens com veredito valido e status conhecido (os unicos que entram nas contas)."""
    return [i for i in itens if (i.get("valido") is None or int(i["valido"]) == 1) and i.get("status") in STATUS]


# ---------- palavras ----------
def _palavras_normalizadas(normalizado, vazias=PALAVRAS_VAZIAS_PT, tamanho_minimo=TAMANHO_MINIMO_PALAVRA):
    return {p for p in normalizado.split() if p not in vazias and len(p) >= tamanho_minimo and not p.isdigit()}


def palavras_do_texto(texto, vazias=PALAVRAS_VAZIAS_PT, tamanho_minimo=TAMANHO_MINIMO_PALAVRA):
    """Conjunto de palavras (normalizadas: sem acento, minusculas) do texto, sem palavras vazias, numeros nem palavras curtas."""
    return _palavras_normalizadas(normalizar_texto(texto), vazias, tamanho_minimo)


def ja_coberta_pelo_prefiltro(palavra, prefiltro):
    """A palavra ja esta no pre-filtro? O pre-filtro casa por trecho (`preditiv` casa `preditivo`), entao a palavra esta
    coberta se algum item do pre-filtro (normalizado) esta contido nela ou se ela e uma das palavras de uma expressao."""
    p = normalizar_texto(palavra)
    for f in prefiltro or ():
        f = normalizar_texto(f)
        if f and (f in p or p in f.split()):
            return True
    return False


def _conjunto(texto_ou_palavras):
    """Aceita um texto (e tokeniza) ou um conjunto de palavras ja pronto (evita normalizar duas vezes o mesmo item)."""
    if isinstance(texto_ou_palavras, (set, frozenset)):
        return texto_ou_palavras
    return palavras_do_texto(texto_ou_palavras)


def _contagem_documentos(conjuntos):
    """{palavra: numero de conjuntos (itens) que a contem}."""
    c = {}
    for s in conjuntos:
        for p in s:
            c[p] = c.get(p, 0) + 1
    return c


def razao_de_chances(a, n_a, b, n_b, suavizacao=SUAVIZACAO):
    """(log da razao de chances suavizada, lift suavizado) da palavra no grupo A (a de n_a itens) contra o grupo B (b de n_b).
    Positivo no log e lift > 1 = mais frequente em A do que em B. A suavizacao evita infinito quando b = 0."""
    s = suavizacao
    log_chances = (math.log((a + s) / (n_a - a + s)) - math.log((b + s) / (n_b - b + s)))
    lift = ((a + s) / (n_a + 2 * s)) / ((b + s) / (n_b + 2 * s))
    return round(log_chances, 3), round(lift, 2)


def palavras_super_representadas(frente, fundo, excluir=(), prefiltro=(), min_suporte=MIN_SUPORTE, maximo=MAX_CANDIDATAS_PALAVRAS):
    """Palavras mais frequentes no grupo `frente` do que no grupo `fundo` (cada grupo e uma lista de textos ou de conjuntos de palavras ja prontos).

    Frequencia = numero de textos que contem a palavra (nao quantas vezes ela aparece). So entram palavras presentes em ao menos
    `min_suporte` textos da frente, que nao sejam palavras vazias, nem estejam em `excluir` nem ja cobertas por `prefiltro`.
    Ordem: log da razao de chances suavizada (decrescente), depois frequencia na frente, depois a palavra.
    Devolve [{"palavra", "n_frente", "n_fundo", "pct_frente", "pct_fundo", "log_chances", "lift"}]; sem frente ou sem fundo, []."""
    if not frente or not fundo:
        return []
    ex = {normalizar_texto(e) for e in excluir}
    df_f = _contagem_documentos(_conjunto(t) for t in frente)
    df_b = _contagem_documentos(_conjunto(t) for t in fundo)
    saida = []
    for p, a in df_f.items():
        if a < min_suporte or p in ex or ja_coberta_pelo_prefiltro(p, prefiltro):
            continue
        b = df_b.get(p, 0)
        if a / len(frente) <= b / len(fundo):
            continue
        lo, lift = razao_de_chances(a, len(frente), b, len(fundo))
        saida.append({"palavra": p, "n_frente": a, "n_fundo": b, "pct_frente": _pct(a, len(frente)), "pct_fundo": _pct(b, len(fundo)),
                      "log_chances": lo, "lift": lift})
    saida.sort(key=lambda x: (-x["log_chances"], -x["n_frente"], x["palavra"]))
    return saida[:maximo]


def _texto(item):
    return f"{item.get('titulo') or ''} {item.get('resumo') or item.get('snippet') or ''}"


# ---------- 1. auditoria do pre-filtro (web) ----------
def _contagens_status(itens):
    return {s: sum(1 for i in itens if i["status"] == s) for s in STATUS}


def _grupo(chave, itens):
    c = _contagens_status(itens)
    n = len(itens)
    return {"chave": chave, "rotulo": ROTULO_MOTIVO.get(chave, chave), "n": n, "n_elegivel": c["elegivel"],
            "n_quarentena": c["quarentena"], "n_excluido": c["excluido"], "elegivel": proporcao(c["elegivel"], n),
            "util": proporcao(c["elegivel"] + c["quarentena"], n)}


def posicoes_por_uf(itens):
    """Posicao (1, 2, ...) de cada item no ranking de sua UF, como o download ordena: mais ocorrencias primeiro, depois a melhor
    posicao, depois o id (o desempate real nao esta no banco). So entram os itens que passaram pelos filtros anteriores ao limite
    (os selecionados e os descartados pelo limite). Devolve {(item_id, uf): posicao}."""
    por_uf = {}
    for i in itens:
        if i.get("selecionada") == 1 or i.get("motivo") == "limite_por_uf":
            por_uf.setdefault(i["uf"], []).append(i)
    pos = {}
    for uf, lista in por_uf.items():
        lista.sort(key=lambda i: (-(i.get("n_ocorrencias") or 0), i.get("melhor_posicao") if i.get("melhor_posicao") is not None else 10**6,
                                  i["item_id"]))
        for k, i in enumerate(lista, 1):
            pos[(i["item_id"], uf)] = k
    return pos


def analise_limite_por_uf(itens, limite_por_uf=40):
    """Itens elegiveis perdidos pelo limite por UF e o teto que os teria pegado.

    `itens`: dicionarios com `item_id`, `uf`, `status`, `valido`, `selecionada` (1/0), `motivo`, `n_ocorrencias` e `melhor_posicao`.
    Devolve {"limite", "por_uf": [...], "n_elegiveis_perdidos", "n_uteis_perdidos", "n_ufs_com_perda", "teto_necessario",
    "curva": [...]}. Em `por_uf`: `uf`, `n_candidatos` (passaram pelos outros filtros), `n_no_limite` (cortados), `n_triados`,
    `n_elegiveis_perdidos`, `n_uteis_perdidos` (elegivel + quarentena), `teto_necessario` (a posicao do ultimo elegivel perdido; None
    sem perda) e `downloads_extras` (teto - limite). `teto_necessario` global e o maior deles. `curva`: para cada teto (limite,
    limite + 10, ... ate o necessario) {"teto", "elegiveis_capturados", "uteis_capturados", "downloads_extras"} somando as UFs."""
    pos = posicoes_por_uf(itens)
    validos = _validos(itens)
    por_uf = {}
    for i in itens:
        if i.get("selecionada") == 1 or i.get("motivo") == "limite_por_uf":
            u = por_uf.setdefault(i["uf"], {"uf": i["uf"], "n_candidatos": 0, "n_no_limite": 0, "n_triados": 0,
                                            "n_elegiveis_perdidos": 0, "n_uteis_perdidos": 0, "teto_necessario": None})
            u["n_candidatos"] += 1
            u["n_no_limite"] += 1 if i.get("motivo") == "limite_por_uf" else 0
    perdidos = []                                         # (uf, posicao, status) dos itens validos cortados pelo limite
    for i in validos:
        if i.get("motivo") != "limite_por_uf" or i.get("selecionada") == 1:
            continue
        u = por_uf[i["uf"]]
        u["n_triados"] += 1
        p = pos[(i["item_id"], i["uf"])]
        perdidos.append((i["uf"], p, i["status"]))
        if i["status"] in ("elegivel", "quarentena"):
            u["n_uteis_perdidos"] += 1
        if i["status"] == "elegivel":
            u["n_elegiveis_perdidos"] += 1
            u["teto_necessario"] = max(u["teto_necessario"] or 0, p)
    lista = sorted(por_uf.values(), key=lambda u: (-u["n_elegiveis_perdidos"], u["uf"]))
    for u in lista:
        u["downloads_extras"] = max(u["teto_necessario"] - limite_por_uf, 0) if u["teto_necessario"] else 0
    teto = max((u["teto_necessario"] or 0 for u in lista), default=0) or None
    curva = []
    if teto:
        tetos = list(range(limite_por_uf, teto, PASSO_TETO)) + [teto]
        for t in tetos:
            extras = sum(max(min(t, u["n_candidatos"]) - limite_por_uf, 0) for u in lista)
            curva.append({"teto": t, "elegiveis_capturados": sum(1 for _, p, s in perdidos if s == "elegivel" and p <= t),
                          "uteis_capturados": sum(1 for _, p, s in perdidos if s in ("elegivel", "quarentena") and p <= t),
                          "downloads_extras": extras})
    return {"limite": limite_por_uf, "por_uf": lista, "n_elegiveis_perdidos": sum(u["n_elegiveis_perdidos"] for u in lista),
            "n_uteis_perdidos": sum(u["n_uteis_perdidos"] for u in lista),
            "n_ufs_com_perda": sum(1 for u in lista if u["n_elegiveis_perdidos"]), "teto_necessario": teto, "curva": curva}


def desempenho_palavras_prefiltro(itens, prefiltro, textos_normalizados=None):
    """Para cada palavra do pre-filtro: quantos itens validos a contem (casamento por trecho, como o download), quantos sao
    elegiveis (com Wilson) e quantos itens ela e a UNICA a pegar. Ordem: pior fracao elegivel primeiro. Palavra sem nenhum item:
    n = 0 e proporcao sem valor. `textos_normalizados`: {id(item): texto normalizado}, opcional (reaproveita a normalizacao)."""
    validos = _validos(itens)
    palavras = list(dict.fromkeys(normalizar_texto(p) for p in prefiltro or () if normalizar_texto(p)))
    cache = textos_normalizados if textos_normalizados is not None else {}
    textos = [(i, cache[id(i)] if id(i) in cache else normalizar_texto(_texto(i))) for i in validos]
    por_palavra = {p: [] for p in palavras}
    exclusivos = {p: 0 for p in palavras}
    for i, t in textos:
        achadas = [p for p in palavras if p in t]
        for p in achadas:
            por_palavra[p].append(i)
        if len(achadas) == 1:
            exclusivos[achadas[0]] += 1
    saida = []
    for p in palavras:
        lista = por_palavra[p]
        e = sum(1 for i in lista if i["status"] == "elegivel")
        saida.append({"palavra": p, "n": len(lista), "n_elegivel": e, "elegivel": proporcao(e, len(lista)),
                      "n_unica": exclusivos[p]})
    saida.sort(key=lambda x: (x["elegivel"]["pct"] is None, x["elegivel"]["pct"] if x["elegivel"]["pct"] is not None else 0, x["palavra"]))
    return saida


def auditar_prefiltro(itens, prefiltro=(), limite_por_uf=40, min_suporte=MIN_SUPORTE_PREFILTRO, maximo_palavras=MAX_CANDIDATAS_PALAVRAS):
    """Auditoria do pre-filtro e do limite por UF para os resultados web ja triados pelo modelo. Sugestao para avaliacao do
    pesquisador; nada e aplicado.

    `itens`: um por resultado (url, uf) da coleta principal, com `item_id`, `uf`, `status`, `valido`, `selecionada` (1/0, ou None
    sem decisao de download), `motivo`, `titulo`, `resumo`, `n_ocorrencias`, `melhor_posicao`. `prefiltro`: as palavras do pre-filtro.

    Devolve {"n_itens", "n_invalidos", "n_sem_selecao", "n_validos", "grupos", "limite_por_uf", "desempenho_prefiltro",
    "palavras_candidatas", "n_frente", "n_fundo", "aviso"}. `grupos`: selecionados, nao selecionados (todos) e cada motivo, cada
    um com `n`, contagens por status e `elegivel`/`util` (proporcao com Wilson 95%; `util` = elegivel + quarentena).
    `palavras_candidatas`: palavras que aparecem mais nos descartados pelo pre-filtro que o modelo julgou elegiveis (`n_frente`
    itens) do que nos selecionados (`n_fundo` itens), com a frequencia nos dois grupos, log da razao de chances suavizada, lift e o
    que a palavra capturaria entre TODOS os descartados pelo pre-filtro (`capturados`: n, n_elegivel, `elegivel` com Wilson)."""
    com_selecao = [i for i in itens if i.get("selecionada") is not None]
    validos = _validos(com_selecao)
    n_inval = len(com_selecao) - len(validos)
    sel = [i for i in validos if int(i["selecionada"]) == 1]
    nao = [i for i in validos if int(i["selecionada"]) == 0]
    grupos = [_grupo("selecionada", sel), _grupo("nao_selecionada", nao)]
    motivos = {}
    for i in nao:
        motivos.setdefault(i.get("motivo") or "sem_motivo", []).append(i)
    for m in sorted(motivos, key=lambda m: (-len(motivos[m]), m)):
        grupos.append(_grupo(m, motivos[m]))
    pref_desc = motivos.get("prefiltro_palavras", [])
    frente = [i for i in pref_desc if i["status"] == "elegivel"]
    norm = {id(i): normalizar_texto(_texto(i)) for i in validos}            # normaliza cada item uma so vez
    palavras = {id(i): _palavras_normalizadas(norm[id(i)]) for i in validos}
    candidatas = palavras_super_representadas([palavras[id(i)] for i in frente], [palavras[id(i)] for i in sel], prefiltro=prefiltro,
                                              min_suporte=min_suporte, maximo=maximo_palavras)
    palavras_desc = [(i, palavras[id(i)]) for i in pref_desc]
    for c in candidatas:
        cap = [i for i, ps in palavras_desc if c["palavra"] in ps]
        e = sum(1 for i in cap if i["status"] == "elegivel")
        c["capturados"] = {"n": len(cap), "n_elegivel": e, "elegivel": proporcao(e, len(cap))}
    return {"n_itens": len(itens), "n_invalidos": n_inval, "n_sem_selecao": len(itens) - len(com_selecao), "n_validos": len(validos),
            "grupos": grupos, "limite_por_uf": analise_limite_por_uf(com_selecao, limite_por_uf),
            "desempenho_prefiltro": desempenho_palavras_prefiltro(validos, prefiltro, norm), "palavras_candidatas": candidatas,
            "n_frente": len(frente), "n_fundo": len(sel), "aviso": AVISO_PREFILTRO}


# ---------- 2. tabela por termo ----------
def acao_sugerida(n, pct_elegivel, dominio_top, n_dominio_top, n_ruido, pct_internacional=None):
    """(acao, regra) por regras transparentes, nesta ordem. `pct_elegivel` e `pct_internacional` em percentual (0 a 100) ou None.

    1. menos de `N_MINIMO_TERMO` itens validos: "amostra pequena";
    2. elegiveis >= `LIMITE_ELEGIVEL_MANTER`: "manter";
    3. a area tematica mais frequente do ruido tem >= `FRACAO_AREA_DOMINANTE` do ruido e >= `MIN_ITENS_AREA_DOMINANTE` itens:
       "candidato a ganhar contexto" (contra aquela area);
    4. elegiveis < `LIMITE_ELEGIVEL_REVISAR`, sem area dominante: "revisar o termo" (ruido espalhado);
    5. senao: "observar" (resultado intermediario, sem area dominante).
    Devolve a acao e a frase da regra aplicada, para a tela mostrar de onde veio a sugestao."""
    if n < N_MINIMO_TERMO:
        return "amostra pequena", f"menos de {N_MINIMO_TERMO} resultados avaliados: ainda não dá para concluir"
    if pct_elegivel is not None and pct_elegivel >= 100 * LIMITE_ELEGIVEL_MANTER:
        return "manter", f"{int(100 * LIMITE_ELEGIVEL_MANTER)}% ou mais dos resultados são elegíveis"
    if n_ruido and dominio_top and n_dominio_top >= MIN_ITENS_AREA_DOMINANTE and n_dominio_top / n_ruido >= FRACAO_AREA_DOMINANTE:
        return "candidato a ganhar contexto", (f"mais de {int(100 * FRACAO_AREA_DOMINANTE)}% do ruído vem de uma só área ({dominio_top}): "
                                                "um contexto que a afaste pode ajudar")
    if pct_elegivel is not None and pct_elegivel < 100 * LIMITE_ELEGIVEL_REVISAR:
        return "revisar o termo", (f"menos de {int(100 * LIMITE_ELEGIVEL_REVISAR)}% elegíveis e o ruído vem de várias áreas: "
                                   "o termo em si pode ser largo demais")
    return "observar", "resultado intermediário e sem área de ruído dominante"


def tabela_por_termo(fichas):
    """Tabela "termo -> n -> % elegivel (Wilson) -> principal motivo de ruido -> area tematica do ruido -> acao sugerida".

    `fichas`: a saida de `dominio.refinamento_busca.ficha_por_termo` (pode trazer tambem `termo_id` e `grupo`). Devolve uma linha
    por termo, da maior fracao de ruido para a menor: `termo`, `termo_id`, `grupo`, `n`, `n_elegivel`, `n_quarentena`, `n_excluido`,
    `elegivel` (proporcao com Wilson), `motivo_top`, `n_motivo_top`, `dominio_top`, `n_dominio_top`, `pct_dominio_top` (do ruido),
    `pct_internacional`, `acao`, `regra`, `observacao`."""
    linhas = []
    for f in fichas or ():
        n = f.get("n_itens", 0)
        ruido = f.get("n_quarentena", 0) + f.get("n_excluido", 0)
        cats, doms = f.get("categorias") or {}, f.get("dominios") or {}
        motivo, n_motivo = (next(iter(cats.items())) if cats else (None, 0))
        dominio, n_dom = (next(iter(doms.items())) if doms else (None, 0))
        el = proporcao(f.get("n_elegivel", 0), n)
        acao, regra = acao_sugerida(n, el["pct"], dominio, n_dom, ruido, f.get("pct_internacional"))
        obs = ""
        if f.get("pct_internacional") is not None and f["pct_internacional"] >= 100 * LIMITE_INTERNACIONAL:
            obs = f"{f['pct_internacional']:.0f}% dos resultados são internacionais: um contexto de Brasil pode ajudar"
        linhas.append({"termo": f.get("termo"), "termo_id": f.get("termo_id"), "grupo": f.get("grupo"), "n": n,
                       "n_elegivel": f.get("n_elegivel", 0), "n_quarentena": f.get("n_quarentena", 0), "n_excluido": f.get("n_excluido", 0),
                       "elegivel": el, "motivo_top": motivo, "n_motivo_top": n_motivo, "dominio_top": dominio, "n_dominio_top": n_dom,
                       "pct_dominio_top": _pct(n_dom, ruido), "pct_internacional": f.get("pct_internacional"),
                       "acao": acao, "regra": regra, "observacao": obs})
    linhas.sort(key=lambda l: (l["elegivel"]["pct"] is None, l["elegivel"]["pct"] if l["elegivel"]["pct"] is not None else 0,
                               -l["n"], str(l["termo"])))
    return linhas


# ---------- 3. simulacao de consulta composta (RD12) ----------
def candidatas_padrao(idioma="pt"):
    """Candidatas padrao ("candidatas, nao aprovadas"): uma por palavra de contexto e um grupo OU (variante A do piloto).
    Cada candidata: {"id", "rotulo", "alternativas": [...], "origem": "padrao", "aprovada": False}. `idioma` 'en' usa a lista inglesa."""
    ingles = str(idioma or "").lower().startswith("en")
    palavras, grupo = (CONTEXTOS_PADRAO_EN, GRUPO_OU_EN) if ingles else (CONTEXTOS_PADRAO, GRUPO_OU_PT)
    chave = "en" if ingles else "pt"
    saida = [{"id": f"padrao:{chave}:{normalizar_texto(p)}", "rotulo": p, "alternativas": [p], "origem": "padrao", "aprovada": False,
              "idioma": chave} for p in palavras]
    saida.append({"id": f"padrao:{chave}:grupo_ou", "rotulo": "(" + " OU ".join(grupo) + ")", "alternativas": list(grupo),
                  "origem": "padrao", "aprovada": False, "idioma": chave})
    return saida


def candidatas_automaticas(itens, termo=None, min_suporte=MIN_SUPORTE, maximo=MAX_CANDIDATAS_AUTOMATICAS):
    """Palavras de contexto achadas por contraste entre os itens elegiveis e os excluidos do termo (frequencia em itens, suporte
    minimo, sem palavras vazias e sem as palavras do proprio termo, que estao em todos os resultados). Mesmo formato de
    `candidatas_padrao`, com `origem` "automatica", e as medidas do contraste (`n_elegivel`, `n_excluido`, `log_chances`)."""
    validos = _validos(itens)
    eleg = [_texto(i) for i in validos if i["status"] == "elegivel"]
    excl = [_texto(i) for i in validos if i["status"] == "excluido"]
    achadas = palavras_super_representadas(eleg, excl, excluir=normalizar_texto(termo).split() if termo else (), min_suporte=min_suporte,
                                           maximo=maximo)
    return [{"id": f"auto:{a['palavra']}", "rotulo": a["palavra"], "alternativas": [a["palavra"]], "origem": "automatica", "aprovada": False,
             "n_elegivel": a["n_frente"], "n_excluido": a["n_fundo"], "log_chances": a["log_chances"]} for a in achadas]


def candidatas_do_termo(itens, termo=None, idioma="pt", min_suporte=MIN_SUPORTE, maximo=MAX_CANDIDATAS_AUTOMATICAS):
    """As candidatas padrao do idioma do termo mais as automaticas, sem repetir: uma automatica cujas alternativas (normalizadas)
    ja sao as de uma candidata padrao (por exemplo "brasil" e "Brasil") e descartada."""
    padrao = candidatas_padrao(idioma)
    ja = {tuple(normalizar_texto(a) for a in c["alternativas"]) for c in padrao}
    auto = [c for c in candidatas_automaticas(itens, termo, min_suporte, maximo)
            if tuple(normalizar_texto(a) for a in c["alternativas"]) not in ja]
    return padrao + auto


def simular_contextos(itens, candidatas, limite_perda=LIMITE_PERDA_UTEIS, min_elegiveis=N_MINIMO_ELEGIVEIS_SIMULACAO):
    """Simula cada candidata como um FILTRO sobre os resultados ja guardados de um termo.

    `itens`: os resultados do termo, com `item_id`, `status`, `valido`, `titulo`, `resumo`. `candidatas`: de `candidatas_padrao` ou
    `candidatas_automaticas` (basta `id`, `rotulo`, `alternativas`). Um item "passa" se o titulo ou o resumo contem alguma das
    alternativas (palavra ou frase inteira, sem acento nem maiuscula).

    Para cada candidata: `retencao_elegivel` (elegiveis que passam, Wilson 95%), `ruido_removido` (excluidos que NAO passam, Wilson),
    `pct_elegivel_resultante` (elegiveis entre os que passam, Wilson), `perda_elegivel` (numero absoluto), `perda_elegivel_pct`,
    `perde_muitos_uteis` (perda acima de `limite_perda`), `n_passam`, `quarentena_removida` e `amostra_pequena`. Ordem: mais ruido
    removido primeiro, depois menos elegiveis perdidos, depois o rotulo; a tabela mostra a perda ao lado, nunca um veredito.
    Devolve {"n", "n_elegivel", "n_quarentena", "n_excluido", "elegivel" (proporcao base), "limite_perda", "amostra_pequena",
    "candidatas": [...], "limites": [...]}; sem itens validos, "candidatas" = []."""
    validos = _validos(itens)
    n_el = sum(1 for i in validos if i["status"] == "elegivel")
    n_ex = sum(1 for i in validos if i["status"] == "excluido")
    n_qu = sum(1 for i in validos if i["status"] == "quarentena")
    base = {"n": len(validos), "n_elegivel": n_el, "n_quarentena": n_qu, "n_excluido": n_ex, "elegivel": proporcao(n_el, len(validos)),
            "limite_perda": limite_perda, "amostra_pequena": n_el < min_elegiveis, "candidatas": [], "limites": list(LIMITES_SIMULACAO)}
    if not validos:
        return base
    textos = [(i, normalizar_texto(_texto(i))) for i in validos]
    saida = []
    for c in candidatas or ():
        alts = [normalizar_texto(a) for a in c.get("alternativas") or [c.get("rotulo")] if normalizar_texto(a)]
        passam = [i for i, t in textos if any(contem_frase(t, a) for a in alts)]
        kept_el = sum(1 for i in passam if i["status"] == "elegivel")
        kept_ex = sum(1 for i in passam if i["status"] == "excluido")
        kept_qu = sum(1 for i in passam if i["status"] == "quarentena")
        perda = n_el - kept_el
        perda_pct = round(100.0 * perda / n_el, 1) if n_el else None
        saida.append({
            "id": c.get("id"), "rotulo": c.get("rotulo"), "idioma": c.get("idioma"), "alternativas": list(c.get("alternativas") or []),
            "origem": c.get("origem"), "aprovada": bool(c.get("aprovada", False)), "n_passam": len(passam),
            "retencao_elegivel": proporcao(kept_el, n_el), "ruido_removido": proporcao(n_ex - kept_ex, n_ex),
            "pct_elegivel_resultante": proporcao(kept_el, len(passam)), "perda_elegivel": perda, "perda_elegivel_pct": perda_pct,
            "quarentena_removida": n_qu - kept_qu,
            "perde_muitos_uteis": bool(n_el and perda / n_el > limite_perda), "amostra_pequena": n_el < min_elegiveis})
    saida.sort(key=lambda s: (s["ruido_removido"]["pct"] is None, -(s["ruido_removido"]["pct"] or 0), s["perda_elegivel"], str(s["rotulo"])))
    base["candidatas"] = saida
    return base


def agregar_simulacoes(simulacoes, limite_perda=LIMITE_PERDA_UTEIS):
    """Soma as simulacoes de varios termos por candidata PADRAO (as automaticas mudam de termo para termo).

    `simulacoes`: lista de saidas de `simular_contextos`. A unidade somada e o par (termo, artigo): o mesmo artigo achado por dois
    termos conta duas vezes. Devolve [{"id", "rotulo", "n_termos", "retencao_elegivel", "ruido_removido", "perda_elegivel",
    "perde_muitos_uteis"}] ordenada como `simular_contextos`."""
    acum = {}
    for s in simulacoes or ():
        n_el, n_ex = s["n_elegivel"], s["n_excluido"]
        for c in s["candidatas"]:
            if c.get("origem") != "padrao":
                continue
            a = acum.setdefault(c["id"], {"id": c["id"], "rotulo": c["rotulo"], "idioma": c.get("idioma"), "n_termos": 0, "el": 0, "ex": 0, "kept_el": 0, "rem_ex": 0})
            a["n_termos"] += 1
            a["el"] += n_el
            a["ex"] += n_ex
            a["kept_el"] += c["retencao_elegivel"]["k"]
            a["rem_ex"] += c["ruido_removido"]["k"]
    saida = []
    for a in acum.values():
        perda = a["el"] - a["kept_el"]
        saida.append({"id": a["id"], "rotulo": a["rotulo"], "idioma": a["idioma"], "n_termos": a["n_termos"],
                      "retencao_elegivel": proporcao(a["kept_el"], a["el"]), "ruido_removido": proporcao(a["rem_ex"], a["ex"]),
                      "perda_elegivel": perda, "perda_elegivel_pct": _pct(perda, a["el"]),
                      "perde_muitos_uteis": bool(a["el"] and perda / a["el"] > limite_perda)})
    saida.sort(key=lambda s: (s["ruido_removido"]["pct"] is None, -(s["ruido_removido"]["pct"] or 0), s["perda_elegivel"], str(s["rotulo"])))
    return saida
