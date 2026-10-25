"""Blocos da pagina /analises no banco `vies` (busca de vies algoritmico, D111 e D116): composicao do corpus e rendimento
das consultas, dos conjuntos e das ferramentas. Funcoes puras: recebem os resultados de `dominio.analises_vies` e devolvem
blocos no formato dos outros (`painel.analises_blocos._bloco`). Todo titulo que afirma algo so afirma quando os numeros
sustentam; senao, o titulo e neutro."""
from dominio import analises_vies as AV
from painel import formatacao as fmt, graficos, graficos_analises as g, rotulos
from painel.analises_blocos import _bloco, _href, _pct

ABAS_VIES = (
    ("panorama", "Panorama"), ("ferramentas", "Ferramentas de busca"), ("tipos", "Tipos de fonte"),
    ("temas", "Eixos e tópicos"), ("tempo", "Tempo e lugar"), ("consultas", "Consultas e conjuntos"), ("web", "Sites da web"),
)
AVISO_MODELO = ("Relevância, ângulo predominante, tipo de fonte, eixo, tópicos e país/escopo vêm da triagem automática do "
                "modelo, ainda sem conferência humana: não são inclusão na revisão nem categorias validadas.")
BASE_OBRAS = "cada obra uma vez (a referência da web que repete um artigo do Scholar sai), só as que ficaram no escopo"
MARGEM_ROTULOS = 285          # rotulos longos (eixos, tipos de fonte com sufixo) cabem inteiros
MAX_ROTULO = 44               # rotulo livre (topico, pais, site) mais longo que isso e cortado; o inteiro fica na dica
LIMIAR_SOBREPOSICAO = 0.2     # "se complementam" so quando menos de 20% dos itens aparecem nas duas partes
REPOSITORIOS_DE_COPIAS = ("scribd.com", "passeidireto.com")


def _rel(chave):
    return rotulos.RELEVANCIA_VIES.get(chave, chave)


def _itens_pl(n):
    return f"{fmt.numero(n)} {'item' if n == 1 else 'itens'}"


def _obras_pl(n):
    return f"{fmt.numero(n)} {'obra' if n == 1 else 'obras'}"


def _barras(linhas, titulo, descricao, hrefs=None):
    return graficos.barras_horizontais(linhas, titulo, descricao, fmt.numero, MARGEM_ROTULOS, MAX_ROTULO, hrefs=hrefs)


# ---------------------------------------------------------------- panorama
def bloco_relevancia(itens):
    """A parte elegivel (relevancia alta ou media) em cada fonte, com a relevancia completa na memoria de calculo."""
    por_fonte = AV.relevancia_por_fonte(itens)
    linhas = []
    for fonte, c in por_fonte.items():
        triados = sum(v for k, v in c.items() if k != AV.SEM_TRIAGEM)
        linhas.append({"rotulo": fonte, "total": triados, "parte": c["alta"] + c["media"],
                       "href": _href("/literatura/referencias", fonte=fonte)})
    if not any(l["total"] for l in linhas):
        return _bloco("vies-relevancia", "Sem triagem da busca de viés algorítmico",
                      aviso="Rode `triar-escopo --banco vies --fonte referencias` e `--fonte artigos`.")
    partes = [f"{_pct(l['parte'], l['total'])} {'das referências da web' if l['rotulo'] == AV.FONTE_WEB else 'dos artigos do Scholar'}"
              for l in linhas if l["total"]]
    titulo = "Relevância alta ou média segundo o modelo: " + " e ".join(partes)
    graf = g.barras_proporcao(linhas, titulo, "Parte dos itens de cada fonte com relevância alta ou média",
                              rotulo_parte="Alta ou média", rotulo_resto="Baixa ou fora do escopo")
    tabela = {"cabecalho": ["Fonte"] + [_rel(r) for r in AV.RELEVANCIAS] + ["Sem triagem válida"],
              "linhas": [[f] + [fmt.numero(c[r]) for r in AV.RELEVANCIAS + (AV.SEM_TRIAGEM,)] for f, c in por_fonte.items()]}
    fora = sum(c["fora_do_escopo"] for c in por_fonte.values())
    return _bloco("vies-relevancia", titulo, graf, "por fonte: cada item da sua fonte, com triagem válida",
                  [f"{_itens_pl(fora)} {'foi classificado' if fora == 1 else 'foram classificados'} automaticamente como fora do "
                   "escopo; saem das análises de conteúdo desta página.",
                   "A comparação entre as fontes não é de qualidade pura: a referência da web foi julgada pelo título e pelo "
                   "trecho da busca, e o artigo do Scholar pelo título, pelo resumo e pelos autores."],
                  aviso=AVISO_MODELO, tabela=tabela)


def bloco_sobreposicao(r):
    """Quantas obras aparecem nas duas fontes (mesma URL ou mesmo titulo)."""
    if not r["n_itens"]:
        return _bloco("vies-sobreposicao", "Ainda não há itens da busca de viés algorítmico neste banco")
    ambas = r["n_em_ambas_fontes"]
    titulo = (f"{fmt.numero(r['n_obras'])} obras distintas: {fmt.numero(ambas)} "
              f"{'aparece' if ambas == 1 else 'aparecem'} nas duas fontes")
    itens = [("Só na web", r["n_web"] - ambas), ("Só no Scholar", r["n_scholar"] - ambas), ("Nas duas fontes", ambas)]
    graf = graficos.barras_horizontais(itens, titulo, "Obras distintas por fonte", fmt.numero)
    texto = []
    if r["n_obras"] and ambas / r["n_obras"] < LIMIAR_SOBREPOSICAO:
        texto.append("As duas fontes se sobrepõem pouco: poucas obras aparecem nas duas.")
    return _bloco("vies-sobreposicao", titulo, graf, "mesma obra: URL normalizada igual ou título normalizado igual (D104)",
                  texto + (["Antes de citar a sobreposição, confira à mão os pares achados só pelo título: títulos "
                            "comuns podem juntar obras diferentes."] if r["n_ambas_so_por_titulo"] else []),
                  pares=[("Itens (web + Scholar)", fmt.numero(r["n_itens"])), ("Obras distintas", fmt.numero(r["n_obras"])),
                         ("Nas duas fontes", fmt.numero(ambas)), ("… pela URL", fmt.numero(r["n_ambas_por_url"])),
                         ("… só pelo título", fmt.numero(r["n_ambas_so_por_titulo"]))])


CAMPOS_DA_AUDITORIA = {"relevancia": "Relevância", "recorte": "Ângulo predominante", "eixo": "Eixo",
                       "tipo_fonte": "Tipo de fonte", "pais": "País/escopo"}
STATUS_DA_IDENTIDADE = {"juncao_url": "Junção automática pela URL", "juncao_titulo": "Junção automática só pelo título",
                        "possivel_duplicata": "Possível duplicata (URL compartilhada, não juntada)"}


def bloco_identidade(itens, recortes):
    """A auditoria da identidade das obras: os itens da web juntados a artigos do Scholar, o criterio, as divergencias de
    classificacao entre os dois e as URLs compartilhadas por artigos diferentes. Descritiva: nao decide identidade."""
    r = AV.auditoria_identidade(itens)
    c = r["contagens"]
    if not c["pares"] and not c["urls_compartilhadas"] and not c["ambiguas"]:
        return _bloco("vies-identidade", "Nenhum item da web foi juntado a um artigo do Scholar nos registros considerados")
    k = c["pares_com_divergencia"]
    titulo = (f"{_itens_pl(c['pares'])} da web {'foi juntado' if c['pares'] == 1 else 'foram juntados'} a artigos do Scholar; "
              + ("nenhum par tem classificações diferentes" if not k else
                 f"{fmt.numero(k)} {'par tem' if k == 1 else 'pares têm'} classificações diferentes"))
    graf = _barras([(CAMPOS_DA_AUDITORIA[campo], n) for campo, n in c["divergencias"].items()], titulo,
                   "Pares web/Scholar com valores diferentes em cada campo da triagem") if c["pares"] else None

    def valor(campo, v):
        if v is None:
            return "—"
        return _rel(v) if campo == "relevancia" else recortes.get(v, v) if campo == "recorte" else v
    linhas = []
    for p in r["pares"]:
        for m in p["membros"]:
            web = m["fonte"] == AV.FONTE_WEB
            linhas.append([p["obra"], m["id"], m["fonte"], ("pela URL" if p["criterio"] == "url" else "só pelo título") if web else "—",
                           STATUS_DA_IDENTIDADE[p["status"]] if web else "—", ", ".join(m["conjuntos"]) or "—"]
                          + [valor(campo, m[campo]) for campo in AV.CAMPOS_AUDITADOS]
                          + [", ".join(CAMPOS_DA_AUDITORIA[d] for d in p["divergencias"]) or "nenhum" if web else ""])
    for g in r["urls_compartilhadas"]:
        for k_m, m in enumerate(g["membros"]):
            linhas.append([g["artigos"][0], m["id"], m["fonte"], "URL compartilhada", STATUS_DA_IDENTIDADE["possivel_duplicata"],
                           ", ".join(m["conjuntos"]) or "—"] + [valor(campo, m[campo]) for campo in AV.CAMPOS_AUDITADOS]
                          + [(", ".join(CAMPOS_DA_AUDITORIA[d] for d in g["divergencias"]) or "nenhum") if k_m == len(g["membros"]) - 1 else ""])
    texto = ["Divergência de classificação: itens juntados como a mesma obra receberam rótulos diferentes do modelo (um rótulo "
             "ausente também conta, e o país/escopo é texto livre: diferenças de redação contam). Nas análises por obra vale o "
             "rótulo do artigo do Scholar, por regra operacional, não por ser mais correto; os dois ficam aqui.",
             "Identidade: a junção pela URL ou só pelo título é automática (D104) e deve ser conferida, porque a mesma URL não "
             "prova a mesma obra e títulos comuns podem juntar obras diferentes. Artigos do Scholar que compartilham a URL "
             "normalizada não são juntados e aparecem como possíveis duplicatas; a referência que casa com mais de um artigo "
             "fica sem junção (ambiguidade). Nenhuma decisão nova de identidade foi tomada."]
    if c["urls_compartilhadas"]:
        texto.append(f"{fmt.numero(c['urls_compartilhadas'])} "
                     f"{'URL normalizada é compartilhada' if c['urls_compartilhadas'] == 1 else 'URLs normalizadas são compartilhadas'} "
                     "por artigos diferentes do Scholar, que seguem contados como obras distintas: "
                     + "; ".join(" e ".join(g["artigos"]) for g in r["urls_compartilhadas"]) + ".")
    if c["ambiguas"]:
        texto.append(f"{fmt.numero(c['ambiguas'])} {'referência da web casa' if c['ambiguas'] == 1 else 'referências da web casam'} "
                     f"com mais de um artigo e {'ficou' if c['ambiguas'] == 1 else 'ficaram'} sem junção (ambiguidade): "
                     + "; ".join(f"{a['web']} ({', '.join(a['artigos'])})" for a in r["ambiguas"]) + ".")
    return _bloco("vies-identidade", titulo, graf,
                  "por par: cada item da web juntado a um artigo do Scholar (D104), inclusive os fora do escopo", texto,
                  aviso=AVISO_MODELO,
                  pares=[("Pares web/Scholar", fmt.numero(c["pares"])), ("… pela URL", fmt.numero(c["por_url"])),
                         ("… só pelo título", fmt.numero(c["por_titulo"])),
                         ("Pares com classificação diferente", fmt.numero(k)),
                         ("Possíveis duplicatas (URL compartilhada)", fmt.numero(c["urls_compartilhadas"])),
                         ("Referências ambíguas", fmt.numero(c["ambiguas"]))],
                  tabela={"cabecalho": ["Obra", "Item", "Fonte", "Critério", "Identidade", "Conjuntos", "Relevância",
                                        "Ângulo", "Eixo", "Tipo de fonte", "País/escopo", "Diverge em"], "linhas": linhas})


# ---------------------------------------------------------------- ferramentas
def bloco_ferramentas_relevancia(linhas):
    """Cada ferramenta de busca: a parte elegivel dos itens que trouxe e o custo por item elegivel."""
    if not linhas:
        return _bloco("vies-ferramentas", "Nenhuma busca registrada nas execuções do relatório")
    prop = [{"rotulo": f"{l['fonte']} · {l['ferramenta']}", "total": l["itens"] or 0, "parte": l["elegiveis"]} for l in linhas]
    melhor = max(linhas, key=lambda l: ((l["elegiveis"] / l["itens"]) if l["itens"] else -1, l["ferramenta"]))
    titulo = (f"{melhor['ferramenta']} trouxe a maior parte com relevância alta ou média: {fmt.numero(melhor['elegiveis'])} de "
              f"{_itens_pl(melhor['itens'] or 0)}") if len(linhas) > 1 else (
              f"{melhor['ferramenta']}: {fmt.numero(melhor['elegiveis'])} de {_itens_pl(melhor['itens'] or 0)} com relevância alta "
              "ou média")
    graf = g.barras_proporcao(prop, titulo, "Parte dos itens de cada ferramenta com relevância alta ou média",
                              rotulo_parte="Alta ou média", rotulo_resto="Baixa ou fora do escopo")

    def custo(l):
        if l["custo_por_elegivel"]:
            return fmt.moeda_usd(l["custo_por_elegivel"])
        if l["creditos_por_elegivel"]:
            return f"{l['creditos_por_elegivel']:.2f} crédito".replace(".", ",")
        return "—"
    tabela = {"cabecalho": ["Ferramenta", "Fonte", "Itens", "Alta", "Alta ou média", "Fora do escopo",
                            "Custo por item de relevância alta ou média"],
              "linhas": [[l["ferramenta"], l["fonte"], fmt.numero(l["itens"] or 0), fmt.numero(l["alta"]), fmt.numero(l["elegiveis"]),
                          fmt.numero(l["fora"]), custo(l)] for l in linhas]}
    fontes = [l["fonte"] for l in linhas]
    repetidas = sorted({f for f in fontes if fontes.count(f) > 1})
    texto = [f"A fonte {', '.join(repetidas)} tem mais de uma ferramenta: os resultados não são atribuídos a cada uma, os "
             "itens se repetem em cada linha e a comparação entre elas não é causal."] if repetidas else []
    texto.append("A comparação entre as ferramentas não é de qualidade pura: a referência da web foi julgada pelo título e "
                 "pelo trecho da busca, e o artigo do Scholar pelo título, pelo resumo e pelos autores.")
    return _bloco("vies-ferramentas", titulo, graf,
                  "por fonte: os itens únicos de cada ferramenta; a parte de relevância alta ou média vem da triagem do modelo",
                  texto, aviso=AVISO_MODELO, tabela=tabela)


# ---------------------------------------------------------------- tipos
def bloco_grupos(itens):
    """Literatura cientifica, cinzenta e fonte primaria em cada fonte (por fonte)."""
    c = AV.tipos_por_grupo_e_fonte(itens)
    if not sum(c.values()):
        return _bloco("vies-grupos", "Sem tipos de fonte para mostrar", aviso="Rode `triar-escopo --banco vies`.")
    cinza = {f: c.get((AV.GRUPO_CINZENTA, f), 0) for f in (AV.FONTE_WEB, AV.FONTE_SCHOLAR)}
    total_cinza = sum(cinza.values())
    if total_cinza and max(cinza.values()) * 2 > total_cinza:
        fonte = max(cinza, key=lambda f: (cinza[f], f))
        titulo = f"A literatura cinzenta vem mais {'da web' if fonte == AV.FONTE_WEB else 'do Scholar'}: {fmt.numero(cinza[fonte])} de {_itens_pl(total_cinza)}"
    elif total_cinza:
        titulo = f"A literatura cinzenta se divide entre as fontes ({_itens_pl(total_cinza)})"
    else:
        titulo = "Nenhum item de literatura cinzenta no escopo"
    graf = g.mapa_de_calor_assimetrico(list(AV.GRUPOS), [AV.FONTE_WEB, AV.FONTE_SCHOLAR],
                                       {(gr, f): c.get((gr, f), 0) for gr in AV.GRUPOS for f in (AV.FONTE_WEB, AV.FONTE_SCHOLAR)},
                                       titulo, descricao="Itens no escopo por grupo de literatura e fonte da busca")
    return _bloco("vies-grupos", titulo, graf, f"por fonte: {_itens_pl(sum(c.values()))} no escopo com tipo de fonte",
                  ["O grupo vem do sufixo do tipo de fonte (D110): \"/ literatura cinzenta\", \"/ fonte primária\" ou nenhum."],
                  aviso=AVISO_MODELO)


def bloco_relevancia_por_grupo(itens):
    """A relevancia em cada grupo de literatura (obras, todas as relevancias)."""
    c = AV.relevancia_por_grupo(itens)
    grupos = [gr for gr in AV.GRUPOS if any(c.get((gr, r)) for r in AV.RELEVANCIAS)]
    if not grupos:
        return _bloco("vies-relevancia-grupo", "Sem tipos de fonte para cruzar com a relevância")
    titulo = "Relevância em cada grupo de literatura"
    graf = g.mapa_de_calor_assimetrico(grupos, [{"chave": r, "rotulo": _rel(r)} for r in AV.RELEVANCIAS],
                                       {(gr, r): c.get((gr, r), 0) for gr in grupos for r in AV.RELEVANCIAS}, titulo,
                                       descricao="Obras por grupo de literatura e relevância")
    return _bloco("vies-relevancia-grupo", titulo, graf, "cada obra uma vez, com triagem válida (inclui as fora do escopo)",
                  aviso=AVISO_MODELO)


def bloco_tipos(itens):
    """Os tipos de fonte mais frequentes (obras no escopo)."""
    linhas = AV.tipos(itens)
    if not linhas:
        return _bloco("vies-tipos", "Sem tipos de fonte para mostrar")
    empatados = [t for t, n in linhas if n == linhas[0][1]]
    titulo = (f"O tipo mais comum é {linhas[0][0]} ({_obras_pl(linhas[0][1])})" if len(empatados) == 1
              else f"Os tipos mais comuns, empatados, são {', '.join(empatados)} ({_obras_pl(linhas[0][1])} cada)")
    graf = _barras(linhas[:15], titulo, "Obras no escopo por tipo de fonte (15 mais frequentes)")
    return _bloco("vies-tipos", titulo, graf, f"{BASE_OBRAS}; {fmt.numero(len(linhas))} tipos diferentes", aviso=AVISO_MODELO,
                  tabela={"cabecalho": ["Tipo de fonte", "Obras"], "linhas": [[t, fmt.numero(n)] for t, n in linhas]})


# ---------------------------------------------------------------- temas
def bloco_eixos(itens, todos):
    """Os eixos de exploracao, inclusive os sem nenhuma obra (lacunas)."""
    linhas = AV.eixos(itens, todos)
    com_eixo = [x for x in linhas if x[0] != AV.SEM_EIXO]
    if not any(n for _, n in linhas):
        return _bloco("vies-eixos", "Sem eixos para mostrar", aviso="Rode `triar-escopo --banco vies`.")
    if len(com_eixo) > 1 and com_eixo[0][1] != com_eixo[-1][1]:
        titulo = (f"O eixo mais coberto é {com_eixo[0][0]} ({_obras_pl(com_eixo[0][1])}); "
                  f"o menos coberto, {com_eixo[-1][0]} ({_obras_pl(com_eixo[-1][1])})")
    else:
        titulo = "Obras no escopo por eixo de exploração"
    graf = _barras(linhas, titulo, "Obras no escopo por eixo de exploração")
    vazios = [e for e, n in com_eixo if n == 0]
    texto = ["Um eixo pouco coberto descreve o corpus recuperado (as consultas e o ranking dos provedores), não "
             "necessariamente uma lacuna da literatura: vale uma consulta dirigida antes de concluir."]
    if vazios:
        texto.insert(0, f"Sem nenhuma obra: {', '.join(vazios)}.")
    return _bloco("vies-eixos", titulo, graf, BASE_OBRAS, texto, aviso=AVISO_MODELO)


def bloco_eixo_relevancia(itens):
    """Eixo cruzado com relevancia (obras no escopo)."""
    c = AV.eixo_por_relevancia(itens)
    eixos = sorted({e for e, _ in c}, key=lambda e: (e == AV.SEM_EIXO, -sum(v for (x, _), v in c.items() if x == e), e))
    rels = ("alta", "media", "baixa")
    if not eixos:
        return _bloco("vies-eixo-relevancia", "Sem eixos para cruzar com a relevância")
    titulo = "Relevância das obras em cada eixo"
    graf = g.mapa_de_calor_assimetrico(eixos, [{"chave": r, "rotulo": _rel(r)} for r in rels],
                                       {(e, r): c.get((e, r), 0) for e in eixos for r in rels}, titulo,
                                       descricao="Obras no escopo por eixo e relevância")
    return _bloco("vies-eixo-relevancia", titulo, graf, BASE_OBRAS, aviso=AVISO_MODELO)


TOPICOS_NO_GRAFICO, TOPICOS_NA_TABELA = 20, 50
MARCA_TERMO_DE_BUSCA = " (termo de busca)"     # marca textual no grafico: o topico tambem e expressao das consultas


def bloco_topicos(itens, textos_das_consultas):
    """Todos os topicos numa lista so, pela frequencia; o que tambem e expressao das consultas leva uma marca textual e
    conta como os demais."""
    lista = AV.topicos(itens, textos_das_consultas)
    if not lista:
        return _bloco("vies-topicos", "Nenhum tópico classificado foi encontrado nos registros considerados por esta análise")
    if len(lista) > 1:
        titulo = f"Os tópicos mais citados são {lista[0][0]} e {lista[1][0]}"
    else:
        titulo = f"O tópico mais citado é {lista[0][0]}"
    graf = _barras([(t + (MARCA_TERMO_DE_BUSCA if busca else ""), n) for t, n, busca in lista[:TOPICOS_NO_GRAFICO]], titulo,
                   f"Obras no escopo que citam cada tópico ({TOPICOS_NO_GRAFICO} mais citados)")
    linhas = [[t, fmt.numero(n), "sim" if busca else "não"] for t, n, busca in lista[:TOPICOS_NA_TABELA]]
    return _bloco("vies-topicos", titulo, graf, f"{BASE_OBRAS}; cada tópico conta uma vez por obra",
                  ["Os tópicos marcados com “(termo de busca)” também são expressões das consultas; contam como os demais.",
                   "As contagens descrevem os rótulos que o modelo deu aos resultados recuperados, não a frequência dos temas na "
                   "literatura nem a adoção das tecnologias.",
                   "Variantes de singular e plural contam juntas (por exemplo, vieses algorítmicos com viés algorítmico).",
                   f"{fmt.numero(len(lista))} {'tópico distinto' if len(lista) == 1 else 'tópicos distintos'}; a tabela mostra "
                   f"{'o' if min(len(lista), TOPICOS_NA_TABELA) == 1 else 'os'} {fmt.numero(min(len(lista), TOPICOS_NA_TABELA))} "
                   f"mais {'citado' if min(len(lista), TOPICOS_NA_TABELA) == 1 else 'citados'}."],
                  aviso=AVISO_MODELO,
                  link={"href": "/literatura/referencias", "rotulo": "Ver os tópicos de cada item na tela Referências"},
                  tabela={"cabecalho": ["Tópico", "Obras", "Também é termo de busca"], "linhas": linhas})


# ---------------------------------------------------------------- tempo e lugar
def bloco_anos(itens, ano_corrente):
    """Ano de publicacao dos artigos do Scholar; a data da pagina das referencias da web fica a parte (nao e publicacao)."""
    anos = AV.anos_scholar(itens)
    if not anos:
        return _bloco("vies-anos", "Sem artigos do Scholar com ano conhecido")
    com_ano = sum(n for _, n in anos)
    ultimos = sum(n for a, n in anos if a >= ano_corrente - 1)
    titulo = "Distribuição por ano dos artigos do Scholar no escopo com ano conhecido"
    if ultimos * 2 > com_ano:
        titulo += f": {fmt.numero(ultimos)} de {fmt.numero(com_ano)} são de {ano_corrente - 1} ou {ano_corrente}"
    graf = graficos.colunas([(str(a), n) for a, n in anos], titulo, "Artigos do Scholar no escopo por ano de publicação", "Ano", "Artigos")
    d = AV.por_ano(itens)
    linhas = [[str(a), fmt.numero(v[AV.FONTE_SCHOLAR]), fmt.numero(v[AV.FONTE_WEB])] for a, v in d.items()]
    sem_ano = d.get(AV.SEM_ANO, {}).get(AV.FONTE_SCHOLAR, 0)
    return _bloco("vies-anos", titulo, graf, f"artigos do Scholar no escopo com ano conhecido ({fmt.numero(com_ano)})",
                  [f"{ano_corrente} ainda está em curso. As buscas trazem os primeiros resultados do ranking de cada provedor: "
                   "a concentração em anos recentes não mede o crescimento da produção científica.",
                   f"{fmt.numero(sem_ano)} {'artigo' if sem_ano == 1 else 'artigos'} do Scholar no escopo sem ano "
                   f"{'fica' if sem_ano == 1 else 'ficam'} fora do gráfico.",
                   "Na memória de cálculo, a coluna da web traz o ano da data da página (a data do resultado da busca), que "
                   "não é o ano de publicação."],
                  tabela={"cabecalho": ["Ano", "Scholar (publicação)", "Web (data da página)"], "linhas": linhas})


def bloco_paises(itens):
    """Pais ou escopo das obras; o Brasil conta quando qualquer parte e Brasil; 'Indeterminado' fica fora do denominador."""
    linhas = AV.paises(itens)
    if not linhas:
        return _bloco("vies-paises", "Sem país ou escopo para mostrar")
    no_brasil, com_lugar = AV.brasil(itens)
    titulo = (f"Segundo o modelo, {_pct(no_brasil, com_lugar)} das obras com país/escopo definido têm o Brasil no "
              f"país/escopo atribuído "
              f"({fmt.numero(no_brasil)} de {fmt.numero(com_lugar)})") if com_lugar else "Nenhuma obra com país/escopo definido pelo modelo"
    graf = _barras(linhas, titulo, "Obras no escopo por país ou escopo (12 mais frequentes)")
    return _bloco("vies-paises", titulo, graf, BASE_OBRAS,
                  ["\"Brasil / UF\" e \"Brasil / União Europeia\" contam como Brasil; \"Indeterminado\" não entra no denominador.",
                   "As consultas foram escritas em português; a busca na web foi filtrada para páginas em português do "
                   "Brasil, e o Scholar rodou com e sem o filtro de português: a amostra puxa para o Brasil e para Portugal.",
                   "O país/escopo é inferido pelo modelo a partir do texto de cada item; não indica onde uma tecnologia foi "
                   "implantada."], aviso=AVISO_MODELO)


# ---------------------------------------------------------------- consultas e conjuntos
def bloco_consultas(itens, ids_por_conjunto, textos):
    """A parte elegivel dos itens que cada consulta achou; a de menor parte e a candidata a ajuste."""
    linhas = AV.consultas(itens, ids_por_conjunto)
    validas = [l for l in linhas if l["triados"]]
    if not validas:
        return _bloco("vies-consultas", "Sem itens com triagem achados pelas consultas")
    prop = [{"rotulo": f"{l['consulta']} · {textos.get(l['consulta'], '')}", "total": l["triados"], "parte": l["elegiveis"]}
            for l in linhas]
    menor = min(l["elegiveis"] / l["triados"] for l in validas)
    piores = [l for l in validas if l["elegiveis"] / l["triados"] == menor]
    if len(piores) == len(validas):
        titulo = "Todas as consultas têm a mesma parte com relevância alta ou média"
    elif len(piores) == 1:
        p = piores[0]
        titulo = (f"A consulta com menor parte de relevância alta ou média é {p['consulta']}: {fmt.numero(p['elegiveis'])} de "
                  f"{_itens_pl(p['triados'])}, {fmt.numero(p['fora'])} fora do escopo")
    else:
        titulo = (f"As consultas com menor parte de relevância alta ou média, empatadas, são "
                  f"{', '.join(p['consulta'] for p in piores)}")
    graf = g.barras_proporcao(prop, titulo, "Parte dos itens achados por cada consulta com relevância alta ou média",
                              rotulo_parte="Alta ou média", rotulo_resto="Baixa ou fora do escopo")
    tabela = {"cabecalho": ["Consulta", "Conjunto", "Web", "Scholar", "Só ela achou", "Alta", "Alta ou média", "Fora do escopo"],
              "linhas": [[f"{l['consulta']} · {textos.get(l['consulta'], '')}", l["conjunto"], fmt.numero(l["web"]),
                          fmt.numero(l["scholar"]), fmt.numero(l["exclusivos"]), fmt.numero(l["alta"]), fmt.numero(l["elegiveis"]),
                          fmt.numero(l["fora"])] for l in linhas]}
    texto = (["Uma consulta com pouca parte de relevância alta ou média, segundo o modelo, é candidata a ajuste antes de "
              "ampliar a busca."] if len(piores) < len(validas) else [])
    return _bloco("vies-consultas", titulo, graf, "por fonte; um item conta em cada consulta que o achou", texto,
                  aviso=AVISO_MODELO, tabela=tabela)


def bloco_conjuntos(itens, nomes):
    """Em que combinacao dos conjuntos de consultas (`nomes`, na ordem da configuracao) cada obra foi achada."""
    contagem, ambiguas = AV.conjuntos_por_obra(itens, nomes)
    total = sum(contagem.values())
    if not total:
        return _bloco("vies-conjuntos", "Sem obras dos conjuntos para comparar")
    varios = sum(contagem[r] for r in AV.combinacoes(nomes)[len(nomes):])     # as combinacoes de dois ou mais conjuntos
    titulo = (f"Nenhuma de {_obras_pl(total)} foi achada por mais de um conjunto de consultas" if not varios else
              f"{fmt.numero(varios)} de {_obras_pl(total)} {'foi achada' if varios == 1 else 'foram achadas'} "
              "por mais de um conjunto de consultas")
    linhas = list(contagem.items())
    graf = _barras(linhas, titulo, "Obras pela combinação exata dos conjuntos de consultas que as acharam")
    texto = ["Cada obra conta uma vez, na combinação de todos os conjuntos que acharam os seus itens (web e Scholar). "
             "As buscas item por item, por consulta e por fonte, estão no bloco anterior."]
    if ambiguas:
        texto.append(f"{fmt.numero(len(ambiguas))} {'referência' if len(ambiguas) == 1 else 'referências'} da web "
                     f"{'casa' if len(ambiguas) == 1 else 'casam'} com mais de um artigo do Scholar: os conjuntos "
                     f"{'dela' if len(ambiguas) == 1 else 'delas'} não "
                     "foram somados a nenhuma obra (a decidir).")
    return _bloco("vies-conjuntos", titulo, graf, "por obra: todas as obras, inclusive as fora do escopo, na união dos conjuntos de todos os seus itens", texto,
                  tabela={"cabecalho": ["Combinação", "Obras"], "linhas": [[r, fmt.numero(n)] for r, n in linhas]})


def bloco_origem_angulo(itens, nomes, recortes):
    """A origem da busca (combinacao de conjuntos) x o angulo predominante da triagem v2 (`recortes`: chave -> rotulo), nas
    obras elegiveis. So contagens: o angulo e um rotulo unico do modelo, nao a intersecao tematica."""
    r = AV.origem_por_angulo(itens, nomes, tuple(recortes))
    total = r["elegiveis"]
    if not total:
        return _bloco("vies-origem-angulo", "Nenhuma obra com relevância alta ou média segundo o modelo para cruzar origem e "
                      "ângulo predominante")
    rotulos = {**recortes, AV.SEM_ANGULO: "Sem ângulo"}
    tot_col = {c: sum(r["matriz"][l][c] for l in r["linhas"]) for c in r["colunas"]}
    titulo = f"Origem da busca × ângulo predominante: {_obras_pl(total)} com relevância alta ou média"
    graf = g.mapa_de_calor_assimetrico(
        r["linhas"], [{"chave": c, "rotulo": rotulos[c]} for c in r["colunas"]],
        {(l, c): r["matriz"][l][c] for l in r["linhas"] for c in r["colunas"]}, titulo,
        descricao="Obras com relevância alta ou média por combinação de conjuntos de consultas e ângulo predominante da triagem")
    texto = ["Cada célula representa obras distintas, classificadas com relevância alta ou média pela triagem v2. Os conjuntos "
             "indicam onde as obras foram encontradas; os ângulos representam classificações predominantes atribuídas "
             "automaticamente pelo modelo. Uma obra pode abordar os dois temas, embora tenha apenas um ângulo predominante.",
             "Interseção temática viés × aplicações: indisponível na triagem v2, pois o recorte é mutuamente exclusivo por "
             "construção.",
             f"Fora desta matriz: {_obras_pl(r['fora'])} de relevância baixa, fora do escopo ou sem triagem válida (na obra que "
             "junta web e Scholar, vale a triagem do artigo do Scholar; o panorama mostra a relevância por item)."]
    if r["divergentes"]:
        texto.append(f"{_obras_pl(r['divergentes'])} {'tem' if r['divergentes'] == 1 else 'têm'} itens com ângulos "
                     "diferentes na web e no Scholar; a matriz usa o ângulo do artigo do Scholar.")
    if r["ambiguas"]:
        n = len(r["ambiguas"])
        texto.append(f"{fmt.numero(n)} {'referência' if n == 1 else 'referências'} da web "
                     f"{'casa' if n == 1 else 'casam'} com mais de um artigo do Scholar: os conjuntos "
                     f"{'dela' if n == 1 else 'delas'} não foram somados a nenhuma obra (a decidir).")
    tabela = {"cabecalho": ["Origem"] + [rotulos[c] for c in r["colunas"]] + ["Total de obras"],
              "linhas": [[l] + [fmt.numero(r["matriz"][l][c]) for c in r["colunas"]] + [fmt.numero(sum(r["matriz"][l].values()))]
                         for l in r["linhas"]]
              + [["Total"] + [fmt.numero(tot_col[c]) for c in r["colunas"]] + [fmt.numero(total)]]}
    return _bloco("vies-origem-angulo", titulo, graf,
                  f"por obra: denominador de {_obras_pl(total)} com relevância alta ou média segundo o modelo; não são itens "
                  "nem ocorrências", texto, aviso=AVISO_MODELO, tabela=tabela)


# ---------------------------------------------------------------- sites da web
def bloco_dominios(itens):
    """Os sites (dominio registravel) que mais aparecem nas referencias da web no escopo."""
    linhas, n_dominios = AV.dominios(itens)
    if not linhas:
        return _bloco("vies-dominios", "Sem referências da web no escopo")
    titulo = f"As referências da web vêm de {fmt.numero(n_dominios)} sites; o mais frequente é {linhas[0][0]}"
    graf = _barras(linhas, titulo, "Referências da web no escopo por site (15 mais frequentes)")
    copias = [d for d, _ in linhas if d in REPOSITORIOS_DE_COPIAS]
    texto = [f"Repositórios de cópias ({', '.join(copias)}) guardam documentos de terceiros: vale buscar a publicação original."] if copias else []
    return _bloco("vies-dominios", titulo, graf, "por fonte: referências da web no escopo; sites agrupados pelo domínio registrável",
                  texto, tabela={"cabecalho": ["Site", "Referências"], "linhas": [[d, fmt.numero(n)] for d, n in linhas]})
