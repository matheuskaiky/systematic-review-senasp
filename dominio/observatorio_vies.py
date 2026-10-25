"""Observatorio do banco `vies`: a projecao de obras (cada obra uma vez, com os membros da web e do Scholar, a uniao dos conjuntos, o angulo da obra e as divergencias entre membros), os filtros GET lidos sem tolerancia, a filtragem sobre obras (nunca sobre membros), a ordem, as paginas e as agregacoes das perspectivas. Funcoes puras; a deduplicacao e a de `analises_vies`."""
import itertools
import math
import re

from dominio import analises_vies as AV

FILTROS = ("perspectiva", "universo", "combinacao", "conjunto", "fonte", "angulo", "eixo", "divergencia")
DIVERGENCIAS = (("com", "Com divergência entre os itens"), ("sem", "Sem divergência entre os itens"))
PERSPECTIVAS = (("integrada", "Integrada"), ("vies", "Viés algorítmico e discriminação"),
                ("tecnologias", "Aplicações tecnológicas de IA"))
ANGULO_DA_PERSPECTIVA = {"vies": "vies_algoritmico", "tecnologias": "aplicacoes_tecnologicas"}
UNIVERSOS = (("elegiveis", "Relevância alta ou média"), ("todas", "Todas as obras"))
FONTES = (("web", "Achada na web"), ("scholar", "Achada no Scholar"), ("so_web", "Só na web"),
          ("so_scholar", "Só no Scholar"), ("ambas", "Na web e no Scholar"))
SEM_CONJUNTO = "nenhum"
SEM_EIXO = "sem_eixo"
TAMANHO_PAGINA = 50


def combinacoes(nomes):
    """Devolve [(chave, rotulo)] das combinacoes de conjuntos e a opcao sem conjunto."""
    chaves = ["+".join(g) for n in range(1, len(nomes) + 1) for g in itertools.combinations(nomes, n)]
    itens = list(zip(chaves, AV.combinacoes(nomes)))
    itens.append((SEM_CONJUNTO, AV.SEM_CONJUNTO))
    return itens


def projecao(lista, nomes):
    """Devolve (obras, ambiguas) da projecao com membros, fontes, combinacao e divergencias."""
    obras_base, ambiguas = AV.obras_com_origem(lista)
    audit = AV.auditoria_identidade(lista)
    if not obras_base:
        return [], ambiguas
    divergencias_por_obra = {}
    for par in audit["pares"]:
        divergencias_por_obra.setdefault(par["obra"], set()).update(par["divergencias"])
    artigos_duplicados = {art for grupo in audit["urls_compartilhadas"] for art in grupo["artigos"]}

    obras = []
    for o in obras_base:
        nova = dict(o)
        fontes_membros = {f for f, _ in o["membros"]}
        nova["fontes"] = tuple(f for f in ("Web", "Scholar") if f in fontes_membros)
        pertencentes = [n for n in nomes if n in o["conjuntos_da_obra"]]
        nova["combinacao"] = "+".join(pertencentes) if pertencentes else SEM_CONJUNTO
        if len(o["membros"]) > 1:
            divs = divergencias_por_obra.get(o["id"], set())
            nova["divergencias"] = [c for c in AV.CAMPOS_AUDITADOS if c in divs]
        else:
            nova["divergencias"] = []
        nova["possivel_duplicata"] = o["id"] in artigos_duplicados
        obras.append(nova)
    return obras, ambiguas


def ler_filtros(pares, nomes, recortes, eixos):
    """Devolve (filtros, erros) com a leitura estrita dos parametros de consulta."""
    filtros = {"perspectiva": "integrada", "universo": "elegiveis", "combinacao": None, "conjunto": None,
               "fonte": None, "angulo": None, "eixo": None, "divergencia": None}
    valores_por_chave = {k: [] for k in FILTROS}
    for chave, valor in pares:
        if chave in valores_por_chave:
            limpo = valor.strip()
            if limpo:
                valores_por_chave[chave].append(limpo)

    permitidos = {
        "perspectiva": {k for k, _ in PERSPECTIVAS},
        "universo": {k for k, _ in UNIVERSOS},
        "combinacao": {k for k, _ in combinacoes(nomes)},
        "conjunto": set(nomes),
        "fonte": {k for k, _ in FONTES},
        "angulo": set(recortes) | {AV.SEM_ANGULO},
        "eixo": set(eixos) | {SEM_EIXO},
        "divergencia": {k for k, _ in DIVERGENCIAS},
    }

    erros = []
    for k in FILTROS:
        vals = valores_por_chave[k]
        if not vals:
            continue
        if len(vals) > 1:
            erros.append(f"Filtro repetido: {k}.")
        else:
            v = vals[0]
            if v not in permitidos[k]:
                erros.append(f"Filtro inválido: {k}.")
            else:
                filtros[k] = v

    if filtros["perspectiva"] in ("vies", "tecnologias") and filtros["angulo"] is not None:
        erros.append("O ângulo já é definido pela perspectiva: tire o filtro de ângulo.")

    return filtros, erros


def filtrar(obras, filtros, recortes):
    """Devolve uma nova lista de obras filtrada pelas condicoes dos filtros."""
    recortes_set = set(recortes)
    perspectiva = filtros.get("perspectiva")
    angulo_filtro = (ANGULO_DA_PERSPECTIVA[perspectiva]
                     if perspectiva in ANGULO_DA_PERSPECTIVA
                     else filtros.get("angulo"))
    universo = filtros.get("universo")
    combinacao = filtros.get("combinacao")
    conjunto = filtros.get("conjunto")
    fonte = filtros.get("fonte")
    eixo = filtros.get("eixo")
    divergencia = filtros.get("divergencia")

    resultado = []
    for o in obras:
        if universo == "elegiveis" and o["relevancia"] not in AV.ELEGIVEIS:
            continue
        if combinacao is not None and o["combinacao"] != combinacao:
            continue
        if conjunto is not None and conjunto not in o["conjuntos_da_obra"]:
            continue
        if fonte is not None:
            fontes = o["fontes"]
            if fonte == "web" and "Web" not in fontes:
                continue
            if fonte == "scholar" and "Scholar" not in fontes:
                continue
            if fonte == "so_web" and fontes != ("Web",):
                continue
            if fonte == "so_scholar" and fontes != ("Scholar",):
                continue
            if fonte == "ambas" and fontes != ("Web", "Scholar"):
                continue
        if angulo_filtro is not None:
            angulo_obra = o["recorte"] if o["recorte"] in recortes_set else AV.SEM_ANGULO
            if angulo_obra != angulo_filtro:
                continue
        if eixo is not None:
            eixo_obra = o.get("eixo")
            if eixo == SEM_EIXO:
                if eixo_obra:
                    continue
            elif eixo_obra != eixo:
                continue
        if divergencia is not None:
            tem_div = bool(o.get("divergencias"))
            if divergencia == "com" and not tem_div:
                continue
            if divergencia == "sem" and tem_div:
                continue
        resultado.append(o)
    return resultado


def matriz(obras, nomes, recortes):
    """Devolve a matriz de contagens {linhas, colunas, celulas} de combinacao por angulo."""
    linhas = combinacoes(nomes)
    colunas = [*recortes, AV.SEM_ANGULO]
    recortes_set = set(recortes)
    celulas = {(l, c): 0 for l, _ in linhas for c in colunas}
    for o in obras:
        l = o["combinacao"]
        c = o["recorte"] if o["recorte"] in recortes_set else AV.SEM_ANGULO
        if (l, c) in celulas:
            celulas[(l, c)] += 1
    return {"linhas": linhas, "colunas": colunas, "celulas": celulas}


def por_combinacao(obras, nomes):
    """Devolve [(chave, rotulo, n)] com a contagem de obras em cada combinacao."""
    linhas = combinacoes(nomes)
    contagens = {l: 0 for l, _ in linhas}
    for o in obras:
        l = o["combinacao"]
        if l in contagens:
            contagens[l] += 1
    return [(l, r, contagens[l]) for l, r in linhas]


def grupos(obras):
    """Devolve [(grupo, n)] das obras por grupo de tipo de fonte."""
    contagens = {g: 0 for g in AV.GRUPOS}
    sem_tipo = 0
    for o in obras:
        tipo = o.get("tipo_fonte")
        if not tipo:
            sem_tipo += 1
        else:
            grupo = AV.grupo_do_tipo(tipo)
            if grupo in contagens:
                contagens[grupo] += 1
            else:
                sem_tipo += 1
    resultado = [(g, contagens[g]) for g in AV.GRUPOS]
    if sem_tipo > 0:
        resultado.append(("Sem tipo de fonte", sem_tipo))
    return resultado


def resumo(obras):
    """Devolve um dicionario com os totais de obras, fontes, divergencias e duplicatas."""
    so_web, so_scholar, ambas, com_div, duplicatas = 0, 0, 0, 0, 0
    for o in obras:
        fontes = o["fontes"]
        if fontes == ("Web",):
            so_web += 1
        elif fontes == ("Scholar",):
            so_scholar += 1
        elif fontes == ("Web", "Scholar"):
            ambas += 1
        if o["divergencias"]:
            com_div += 1
        if o["possivel_duplicata"]:
            duplicatas += 1
    return {"obras": len(obras), "so_web": so_web, "so_scholar": so_scholar, "ambas": ambas,
            "com_divergencia": com_div, "possiveis_duplicatas": duplicatas}


def ordenar(obras):
    """Devolve uma nova lista de obras ordenada pelo titulo normalizado, sem alterar a entrada."""
    def chave(o):
        k = AV.chave_titulo(o.get("titulo"))
        return (k is None, k or "")
    return sorted(obras, key=chave)


def ultima_pagina(total):
    """Devolve o numero da ultima pagina com base no total de itens e no tamanho da pagina."""
    return max(1, math.ceil(total / TAMANHO_PAGINA))


def ler_pagina(pares, total):
    """Devolve (pagina, erro) apos validacao estrita do parametro pagina."""
    valores = [v.strip() for k, v in pares if k == "pagina" and v.strip()]
    if not valores:
        return 1, None
    if len(valores) > 1:
        return None, "Página inválida."
    v = valores[0]
    if not re.fullmatch(r"[0-9]{1,6}", v):
        return None, "Página inválida."
    num = int(v)
    if not (1 <= num <= ultima_pagina(total)):
        return None, "Página inválida."
    return num, None


def fatia(obras, pagina):
    """Devolve a fatia de obras correspondente a pagina informada."""
    inicio = (pagina - 1) * TAMANHO_PAGINA
    return obras[inicio : inicio + TAMANHO_PAGINA]
