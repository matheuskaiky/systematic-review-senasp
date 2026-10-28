"""Blocos da análise RG5 (cobertura e redundância de termos), no estilo de `painel/analises_blocos.py`: cada bloco junta um gráfico
SVG do servidor, um título que CONTA A CONCLUSÃO com os números, frases em linguagem simples e a "Memória de cálculo".

Funções puras: recebem os dicionários de `adaptadores/leitura_termos_cobertura.py` e devolvem listas de blocos (o mesmo formato de
`_bloco`). Não tocam no banco.

Duas ressalvas aparecem em todos os blocos de cobertura: "elegível" é a opinião do modelo sobre o escopo (sem conferência humana) e
toda cobertura é RELATIVA ao universo já coletado, não é a revocação verdadeira."""
from markupsafe import Markup

from painel import formatacao as fmt, graficos_analises as g, rotulos
from painel.analises_blocos import _bloco, _href

AVISO_RELATIVO = ("Cobertura relativa: os percentuais são sobre os artigos elegíveis que as buscas já feitas trouxeram, não sobre "
                  "tudo o que existe na literatura. \"Elegível\" é a opinião do modelo sobre o escopo, ainda sem conferência humana.")
AVISO_RELATIVO_WEB = AVISO_RELATIVO.replace("artigos elegíveis", "páginas elegíveis")
MINIMO_PARA_DESTAQUE = 10        # termo com menos de 10 artigos triados não entra como "melhor" ou "pior" (a margem de erro é enorme)
LIMIAR_CONTIDO = 80              # "quase todo dentro de outro termo": 80% dos elegíveis ou mais
TOPO_PARES = 20
NOMES_IDIOMA = {"apenas_pt": "Só termos em português", "apenas_en": "Só termos em inglês", "ambos": "Português e inglês",
                "sem_idioma": "Termo sem idioma"}
GRUPOS = {"reconhecimento_identificacao": "Reconhecimento e identificação", "video_monitoramento": "Vídeo e monitoramento",
          "analise_preditiva": "Análise preditiva", "dados_automacao": "Dados e automação",
          "atendimento_triagem": "Atendimento e triagem", "outras_aplicacoes": "Outras aplicações", "sem_grupo": "Sem grupo"}


# ---------------------------------------------------------------- utilitários
def _p(fracao, casas=0):
    """Fração (0 a 1) como percentual em pt-BR; None vira traço."""
    return "—" if fracao is None else fmt.decimal(100 * fracao, casas) + "%"


def _pc(pct, casas=0):
    """Valor já em 0 a 100."""
    return "—" if pct is None else fmt.decimal(pct, casas) + "%"


def _consulta(query):
    return str(query or "").strip().strip('"').strip()


def _rot(termo_id, query):
    q = _consulta(query)
    return f"{termo_id} · {q}" if q else str(termo_id)


def _grupo(chave):
    return GRUPOS.get(chave, str(chave or "—").replace("_", " "))


def _ic(l):
    return "—" if l.get("ic_inf") is None else f"{_p(l['ic_inf'])} a {_p(l['ic_sup'])}"


def _link_termo(termo_id, texto=None):
    """Célula de tabela com link para os artigos do termo (Markup escapa os argumentos)."""
    return Markup('<a href="{}">{}</a>').format( _href("/literatura/artigos", termo=termo_id), texto or termo_id)


def _vazio(id_, titulo, aviso):
    return _bloco(id_, titulo, aviso=aviso)


def _marco(cobertura, percentual):
    return next((m for m in (cobertura or {}).get("marcos") or [] if m["percentual"] == percentual), None)


def _creditos(n):
    return f"{fmt.numero(n)} crédito" + ("" if n == 1 else "s")


def _usd(v):
    return fmt.moeda_usd(v)


# ---------------------------------------------------------------- 1. rendimento por termo
def blocos_cobertura_termos(dados, cobertura=None):
    """Blocos do rendimento por termo. `dados` = `analise_cobertura_termos()`; `cobertura` (opcional) =
    `analise_cobertura_incremental()`, que acrescenta a curva de cobertura acumulada."""
    dados = dados or {}
    if not dados.get("n_termos"):
        return [_vazio("termos_precisao", "Ainda não há termos de busca para analisar", "Nenhuma busca acadêmica registrada.")]
    blocos = []
    if cobertura is not None:
        blocos.append(bloco_curva_cobertura(cobertura))
    blocos.append(bloco_precisao_termos(dados))
    blocos.append(bloco_idioma(dados))
    blocos.append(bloco_faixa_grupo(dados))
    return blocos


def bloco_curva_cobertura(c):
    passos = (c or {}).get("passos") or []
    universo = (c or {}).get("universo") or 0
    if not passos or not universo:
        return _vazio("termos_curva", "Cobertura acumulada dos termos: ainda sem artigos elegíveis para somar",
                      "Rode `triar-escopo --fonte artigos` e confira se há artigos elegíveis." if not c.get("tem_triagem") else
                      "Nenhum artigo foi julgado elegível pelo modelo.")
    n_termos = c.get("n_termos") or len(passos)
    m95 = _marco(c, 95)
    base = "elegíveis ou em quarentena" if c.get("base") == "elegiveis_e_quarentena" else "elegíveis"
    pontos = [(0, 0)] + [(p["ordem"], p["pct_acumulado"]) for p in passos if p.get("pct_acumulado") is not None]
    if m95 and m95["atingido"]:
        titulo = (f"Com {fmt.numero(m95['n_chaves'])} dos {fmt.numero(n_termos)} termos já se encontram 95% dos artigos {base} "
                  f"coletados ({fmt.numero(m95['acumulado'])} de {fmt.numero(universo)})")
        corte = m95["n_chaves"]
    else:
        titulo = f"Cobertura acumulada dos {fmt.numero(n_termos)} termos sobre {fmt.numero(universo)} artigos {base}"
        corte = None
    graf = g.linha_com_corte(pontos, titulo, "Percentual acumulado dos artigos elegíveis já coletados, somando os termos na ordem em que "
                             "cada um acrescenta mais artigos novos", "Termos somados (do que mais acrescenta ao que menos)",
                             "% dos artigos elegíveis", corte=corte, teto=95, rotulo_corte=f"{corte} termos" if corte else "",
                             rotulo_teto="95%")
    texto = ["Cada ponto soma mais um termo, sempre o que traz mais artigos novos naquele momento. A curva sobe rápido e depois "
             "achata: os últimos termos quase não acrescentam nada ao que os outros já trouxeram."]
    if m95 and m95["atingido"]:
        texto.append(f"Esses {fmt.numero(m95['n_chaves'])} termos custaram {_creditos(m95['creditos_acumulados'])} dos "
                     f"{_creditos(c.get('creditos_total'))} já gastos nesta rodada (1 crédito por página do Google Scholar).")
    m100 = _marco(c, 100)
    if m100 and m100["atingido"]:
        texto.append(f"Para ter todos os {fmt.numero(universo)} são precisos {fmt.numero(m100['n_chaves'])} termos e "
                     f"{_creditos(m100['creditos_acumulados'])}; os demais {fmt.numero(n_termos - m100['n_chaves'])} termos "
                     "não acrescentaram nenhum.")
    texto.append("Vale só para o que já foi coletado: um termo que hoje não acrescenta nada pode ser o único a achar artigos que "
                 "ainda não vieram.")
    pares = [("Base de contagem", "artigos elegíveis ou em quarentena" if "quarentena" in str(c.get("base")) else "artigos elegíveis (opinião do modelo)"),
             ("Universo (artigos da base)", fmt.numero(universo)), ("Termos considerados", fmt.numero(n_termos)),
             ("Créditos gastos no total", fmt.numero(c.get("creditos_total")))]
    for m in c.get("marcos") or []:
        pares.append((f"Menor prefixo que alcança {m['percentual']}%",
                      f"{fmt.numero(m['n_chaves'])} termos, {_creditos(m['creditos_acumulados'])}, {fmt.numero(m['acumulado'])} artigos"
                      if m["atingido"] else "não alcançado"))
    pares.append(("Critério de desempate", c.get("criterio_desempate") or "—"))
    tabela = {"cabecalho": ["Ordem", "Termo", "Artigos elegíveis do termo", "Novos que ele acrescenta", "Acumulado", "% acumulada", "Créditos acumulados"],
              "linhas": [[p["ordem"], _link_termo(p["termo_id"], _rot(p["termo_id"], p.get("query"))), fmt.numero(p.get("n_elegiveis")),
                          fmt.numero(p["ganho"]), fmt.numero(p["acumulado"]), _pc(p["pct_acumulado"], 1),
                          fmt.numero(p["creditos_acumulados"])] for p in passos]}
    return _bloco("termos_curva", titulo, graf, f"{fmt.numero(universo)} artigos {base}; método guloso (cada passo acrescenta o máximo de novos)",
                  texto, aviso=AVISO_RELATIVO, pares=pares, tabela=tabela)


def bloco_precisao_termos(d):
    termos = [t for t in d.get("por_termo") or [] if t.get("n_triados")]
    sem_resultado = [t for t in d.get("por_termo") or [] if not t.get("n_resultados")]
    if not termos or not d.get("tem_triagem"):
        return _vazio("termos_precisao", "Precisão por termo: sem triagem de escopo para medir",
                      "Rode `triar-escopo --fonte artigos` para o modelo julgar os artigos.")
    ordenados = sorted(termos, key=lambda t: (-(t["precisao"] or 0), -t["n_triados"], t["termo_id"]))
    firmes = [t for t in ordenados if t["n_triados"] >= MINIMO_PARA_DESTAQUE]
    if len(firmes) >= 2:
        a, b = firmes[0], firmes[-1]
        titulo = (f"Entre os termos com pelo menos {MINIMO_PARA_DESTAQUE} artigos, a precisão vai de {_p(b['precisao'])} ({b['termo_id']}) "
                  f"a {_p(a['precisao'])} ({a['termo_id']})")
    else:
        titulo = f"Precisão de cada termo: {_p(d.get('precisao_geral'))} dos artigos coletados são elegíveis"
    itens = [{"rotulo": _rot(t["termo_id"], t.get("query")), "total": t["n_triados"], "parte": t["n_elegiveis"],
              "href": _href("/literatura/artigos", termo=t["termo_id"])} for t in ordenados]
    graf = g.barras_proporcao(itens, titulo, "Parte dos artigos de cada termo que o modelo julgou dentro do escopo", rotulo_parte="Elegíveis",
                              rotulo_resto="Não elegíveis")
    texto = ["Precisão aqui é a parte dos artigos que um termo trouxe e que o modelo julgou dentro do escopo (segurança pública com "
             "tecnologia). Quanto menos artigos o termo trouxe, menos confiável é o percentual: veja o intervalo de 95% na memória de cálculo.",
             f"No conjunto, {fmt.numero(d.get('n_elegiveis'))} de {fmt.numero(d.get('n_triados'))} artigos triados são elegíveis "
             f"({_p(d.get('precisao_geral'))}, intervalo de 95%: {_p(d.get('precisao_ic_inf'))} a {_p(d.get('precisao_ic_sup'))})."]
    if sem_resultado:
        gasto = sum(t.get("creditos") or 0 for t in sem_resultado)
        texto.append(f"{fmt.numero(len(sem_resultado))} termos não devolveram nenhum resultado e gastaram {_creditos(gasto)} sem retorno "
                     f"({', '.join(t['termo_id'] for t in sem_resultado)}).")
    pares = [("Termos com resultado", f"{fmt.numero(d.get('n_termos_com_resultado'))} de {fmt.numero(d.get('n_termos'))}"),
             ("Artigos distintos", fmt.numero(d.get("n_artigos"))), ("Artigos com veredito válido", fmt.numero(d.get("n_triados"))),
             ("Artigos sem veredito válido", fmt.numero(d.get("n_sem_veredito"))), ("Créditos gastos", fmt.numero(d.get("creditos_total"))),
             ("Precisão", "elegíveis ÷ triados do termo; intervalo de Wilson 95%"),
             ("Único", "elegível que só este termo trouxe (sai da base se o termo sair)")]
    tabela = {"cabecalho": ["Termo", "Idioma", "Artigos", "Elegíveis", "Quarentena", "Precisão", "Intervalo 95%", "Créditos",
                            "Elegíveis por crédito", "Só deste termo", "Também em outro termo", "Posição média dos elegíveis"],
              "linhas": [[_link_termo(t["termo_id"], _rot(t["termo_id"], t.get("query"))), (t.get("idioma") or "—"),
                          fmt.numero(t["n_triados"]), fmt.numero(t["n_elegiveis"]), fmt.numero(t["n_quarentena"]), _p(t["precisao"], 1),
                          _ic(t), fmt.numero(t["creditos"]), fmt.decimal(t["elegiveis_por_credito"], 1),
                          fmt.numero(t["n_elegiveis_unicos"]), _pc(t["pct_elegiveis_de_outros"]), fmt.decimal(t["posicao_media_elegiveis"], 1)]
                         for t in ordenados]}
    return _bloco("termos_precisao", titulo, graf, f"{fmt.numero(d.get('n_triados'))} artigos triados em {len(termos)} termos; elegível = opinião do modelo",
                  texto, aviso=AVISO_RELATIVO, pares=pares, tabela=tabela)


def bloco_idioma(d):
    linhas = d.get("por_idioma") or []
    if not linhas or not d.get("tem_triagem"):
        return _vazio("termos_idioma", "Contribuição por idioma: sem triagem de escopo para medir",
                      "Rode `triar-escopo --fonte artigos`.")
    por = {l["achado_por"]: l for l in linhas}
    pt, en, ambos = (por.get(k, {}) for k in ("apenas_pt", "apenas_en", "ambos"))
    titulo = (f"Artigos elegíveis achados só por termos em português: {fmt.numero(pt.get('n_elegiveis', 0))}; só em inglês: "
              f"{fmt.numero(en.get('n_elegiveis', 0))}; pelos dois: {fmt.numero(ambos.get('n_elegiveis', 0))}")
    itens = [{"rotulo": NOMES_IDIOMA.get(l["achado_por"], l["achado_por"]), "total": l["n_triados"], "parte": l["n_elegiveis"]} for l in linhas]
    graf = g.barras_proporcao(itens, titulo, "Parte dos artigos de cada grupo que o modelo julgou elegível", rotulo_parte="Elegíveis",
                              rotulo_resto="Não elegíveis")
    texto = ["Mostra o que cada lista de termos acrescenta: os elegíveis que só os termos em inglês acharam seriam perdidos se a lista "
             "em inglês fosse cortada, e vice-versa.",
             f"Os dois idiomas quase não se repetem: só {fmt.numero(ambos.get('n_artigos', 0))} artigos foram achados pelos dois lados."]
    if pt.get("precisao") is not None and en.get("precisao") is not None:
        texto.append(f"Precisão: {_p(pt['precisao'])} nos achados só em português (n = {fmt.numero(pt['n_triados'])}) contra "
                     f"{_p(en['precisao'])} nos só em inglês (n = {fmt.numero(en['n_triados'])}).")
    tabela = {"cabecalho": ["Achado por", "Artigos", "Elegíveis", "Quarentena", "Excluídos", "Precisão", "Intervalo 95%", "% de todos os elegíveis"],
              "linhas": [[NOMES_IDIOMA.get(l["achado_por"], l["achado_por"]), fmt.numero(l["n_triados"]), fmt.numero(l["n_elegiveis"]),
                          fmt.numero(l["n_quarentena"]), fmt.numero(l["n_excluidos"]), _p(l["precisao"], 1), _ic(l),
                          _pc(l["pct_dos_elegiveis"], 1)] for l in linhas]}
    return _bloco("termos_idioma", titulo, graf, f"{fmt.numero(d.get('n_triados'))} artigos triados; a classe vem do idioma dos termos que acharam o artigo",
                  texto, aviso=AVISO_RELATIVO, tabela=tabela)


def bloco_faixa_grupo(d):
    linhas = d.get("por_faixa_grupo") or []
    if not linhas or not d.get("tem_triagem"):
        return _vazio("termos_faixa", "Utilidade por posição e grupo de termo: sem triagem de escopo para medir",
                      "Rode `triar-escopo --fonte artigos`.")
    grupos = sorted({l["grupo"] for l in linhas})
    faixas = sorted({l["faixa"] for l in linhas})
    rot_faixa = {l["faixa"]: l["rotulo"] for l in linhas}
    valores = {(l["grupo"], l["faixa"]): l["pct_elegiveis"] for l in linhas}
    por_faixa = {}
    for l in linhas:
        a = por_faixa.setdefault(l["faixa"], [0, 0])
        a[0] += l["n_triados"]
        a[1] += l["n_elegiveis"]
    primeira, ultima = faixas[0], faixas[-1]
    p1 = 100 * por_faixa[primeira][1] / por_faixa[primeira][0] if por_faixa[primeira][0] else None
    pu = 100 * por_faixa[ultima][1] / por_faixa[ultima][0] if por_faixa[ultima][0] else None
    titulo = (f"Nas posições {rot_faixa[primeira]} do Scholar, {_pc(p1)} dos artigos são elegíveis; nas posições {rot_faixa[ultima]}, {_pc(pu)}"
              if p1 is not None and pu is not None and primeira != ultima else "Parte de artigos elegíveis por posição e grupo de termo")
    graf = g.mapa_de_calor_assimetrico([{"chave": x, "rotulo": _grupo(x)} for x in grupos],
                                       [{"chave": f, "rotulo": rot_faixa[f]} for f in faixas], valores,
                                       titulo, formato=lambda v: f"{v:.0f}%",
                                       descricao="Percentual de artigos elegíveis por grupo de termo (linhas) e faixa de posições do Scholar (colunas)")
    texto = ["Cada quadrado é o percentual de artigos elegíveis naquela faixa de posições (1-10 é a primeira página). Se a cor não esmaece para a "
             "direita, as páginas seguintes ainda valem os créditos; se esmaece, o fundo do ranking traz mais ruído.",
             "Cada quadrado tem poucos artigos (veja a memória de cálculo): leia a tendência, não cada valor."]
    tabela = {"cabecalho": ["Grupo de termos", "Posições", "Artigos triados", "Elegíveis", "% elegíveis"],
              "linhas": [[_grupo(l["grupo"]), l["rotulo"], fmt.numero(l["n_triados"]), fmt.numero(l["n_elegiveis"]), _pc(l["pct_elegiveis"], 1)]
                         for l in linhas]}
    return _bloco("termos_faixa", titulo, graf, f"{fmt.numero(sum(l['n_triados'] for l in linhas))} artigos por grupo e faixa; cada artigo conta uma vez por "
                  "grupo, na melhor posição que o grupo lhe deu", texto, aviso=AVISO_RELATIVO, tabela=tabela)


# ---------------------------------------------------------------- 2. redundância
def blocos_redundancia(dados, cobertura=None):
    """Blocos de redundância. `dados` = `analise_redundancia_termos()`; `cobertura` = `analise_cobertura_incremental()` (para as listas de
    termos dispensáveis e insubstituíveis)."""
    blocos = [bloco_jaccard(dados or {}), bloco_contidos(dados or {})]
    if cobertura is not None:
        blocos.append(bloco_dispensaveis(cobertura))
        blocos.append(bloco_insubstituiveis(cobertura))
    return blocos


def bloco_jaccard(d):
    termos, matriz = d.get("termos") or [], d.get("matriz") or []
    if len(termos) < 2:
        return _vazio("termos_jaccard", "Sobreposição entre termos: poucos termos com artigos elegíveis para comparar",
                      f"Só entram termos com pelo menos {d.get('minimo_elegiveis', 5)} artigos elegíveis.")
    pares = d.get("pares") or []
    rotulos_ = d.get("rotulos") or {}
    valores = {(a, b): matriz[i][j] for i, a in enumerate(termos) for j, b in enumerate(termos) if i != j and matriz[i][j] is not None}
    if pares:
        top = pares[0]
        parecido = (f"o par mais parecido ({top['termo_a']} e {top['termo_b']}) tem {fmt.numero(top['n_em_comum'])} de "
                    f"{fmt.numero(top['n_uniao'])} artigos elegíveis em comum ({_p(top['jaccard'])})")
        titulo = (f"Os termos quase não se repetem: {parecido}" if top["jaccard"] < 0.3
                  else f"Há termos redundantes: {parecido}")
    else:
        titulo = "Os termos comparados não têm nenhum artigo elegível em comum"
    graf = g.mapa_de_calor_assimetrico([{"chave": t, "rotulo": _rot(t, rotulos_.get(t))} for t in termos], [{"chave": t, "rotulo": t} for t in termos],
                                       valores, titulo, formato=lambda v: f"{100 * v:.0f}%",
                                       descricao="Sobreposição (Jaccard) entre os artigos elegíveis de cada par de termos")
    texto = ["Cada quadrado diz, entre os artigos elegíveis de dois termos, que parte é a mesma (100% = os dois acham exatamente os mesmos "
             "artigos; 0% = nenhum em comum). Quadrados escuros indicam termos redundantes, que gastam créditos para achar o mesmo.",
             "Poucos quadrados escuros significam que os termos são complementares: cada um acha artigos que os outros não acham."]
    pares_mem = [("Termos na matriz", f"{fmt.numero(len(termos))} (com pelo menos {d.get('minimo_elegiveis')} artigos elegíveis)"),
                 ("Termos com elegíveis, mas abaixo do mínimo", fmt.numero(d.get("n_termos_fora"))),
                 ("Jaccard", "artigos em comum ÷ artigos em qualquer um dos dois (só elegíveis)"),
                 ("Pares com algum artigo em comum", fmt.numero(len(pares)))]
    tabela = {"cabecalho": ["Par de termos", "Elegíveis do 1º", "Elegíveis do 2º", "Em comum", "Em qualquer um", "Jaccard"],
              "linhas": [[f"{p['termo_a']} e {p['termo_b']}", fmt.numero(p["n_a"]), fmt.numero(p["n_b"]), fmt.numero(p["n_em_comum"]),
                          fmt.numero(p["n_uniao"]), _p(p["jaccard"], 1)] for p in pares[:TOPO_PARES]]}
    return _bloco("termos_jaccard", titulo, graf, f"Jaccard entre os elegíveis de {fmt.numero(len(termos))} termos; mostrados os {min(len(pares), TOPO_PARES)} pares mais parecidos na tabela",
                  texto, aviso=AVISO_RELATIVO, pares=pares_mem, tabela=tabela)


def bloco_contidos(d):
    linhas = [l for l in d.get("contidos") or [] if l.get("contido_em")]
    if not linhas:
        return _vazio("termos_contidos", "Termos contidos em outros: sem dados suficientes",
                      f"Só entram termos com pelo menos {d.get('minimo_elegiveis', 5)} artigos elegíveis e algum artigo em comum.")
    muito = [l for l in linhas if (l["pct_contido"] or 0) >= LIMIAR_CONTIDO]
    top = linhas[0]
    if muito:
        titulo = (f"{fmt.numero(len(muito))} {'termo tem' if len(muito) == 1 else 'termos têm'} {LIMIAR_CONTIDO}% ou mais dos seus artigos "
                  f"elegíveis dentro de outro termo (candidatos a dispensar)")
    else:
        titulo = (f"Nenhum termo está quase todo dentro de outro: o maior é {top['termo_id']}, com {_pc(top['pct_contido'])} dos elegíveis "
                  f"também em {top['contido_em']} ({fmt.numero(top['n_contido'])} de {fmt.numero(top['n_elegiveis'])})")
    itens = [{"rotulo": f"{l['termo_id']} dentro de {l['contido_em']}", "total": l["n_elegiveis"], "parte": l["n_contido"],
              "href": _href("/literatura/artigos", termo=l["termo_id"])} for l in linhas[:15]]
    graf = g.barras_proporcao(itens, titulo, "Parte dos artigos elegíveis de cada termo que um outro termo específico também traz",
                              rotulo_parte="Também no outro termo", rotulo_resto="Só neste termo")
    texto = ["Um termo \"contido\" em outro traz quase os mesmos artigos elegíveis que ele; um dos dois sobra. Aqui se compara cada termo com "
             "o outro termo que mais se parece com ele.",
             "A coluna \"em qualquer outro termo\" da memória de cálculo soma todos os outros: mesmo que nenhum termo isolado contenha o "
             "termo, o conjunto dos demais pode contê-lo."]
    tabela = {"cabecalho": ["Termo", "Artigos elegíveis", "Mais parecido com", "Em comum", "% dentro desse termo", "% dentro de qualquer outro"],
              "linhas": [[_link_termo(l["termo_id"]), fmt.numero(l["n_elegiveis"]), l["contido_em"], fmt.numero(l["n_contido"]),
                          _pc(l["pct_contido"], 1), _pc(l["pct_nos_demais"], 1)] for l in linhas]}
    return _bloco("termos_contidos", titulo, graf, f"{fmt.numero(len(linhas))} termos com pelo menos {d.get('minimo_elegiveis')} artigos elegíveis",
                  texto, aviso=AVISO_RELATIVO, tabela=tabela)


def bloco_dispensaveis(c):
    disp = (c or {}).get("dispensaveis") or []
    universo = (c or {}).get("universo") or 0
    n_termos = (c or {}).get("n_termos") or 0
    if not n_termos or not universo:
        return _vazio("termos_dispensaveis", "Termos dispensáveis: ainda sem artigos elegíveis para comparar", "Faltam resultados da triagem de escopo.")
    sem_res = [x for x in disp if x["sem_resultados"]]
    sem_elegivel = [x for x in disp if x["n_elegiveis"] == 0 and not x["sem_resultados"]]
    redundantes = [x for x in disp if x["n_elegiveis"] > 0]
    creditos = sum(x["creditos"] for x in disp)
    titulo = (f"{fmt.numero(len(disp))} dos {fmt.numero(n_termos)} termos não acrescentaram nenhum artigo elegível ao que os outros "
              f"já traziam (créditos gastos neles: {fmt.numero(creditos)})")
    texto = ["\"Dispensável neste universo\" quer dizer: depois de somar os termos que mais acrescentam, este não trouxe nenhum artigo elegível novo.",
             f"Dos {fmt.numero(len(disp))}: {fmt.numero(len(sem_res))} não devolveram resultado algum, {fmt.numero(len(sem_elegivel))} "
             f"trouxeram artigos mas nenhum elegível e {fmt.numero(len(redundantes))} trouxeram elegíveis que outros termos também trazem.",
             "Não é prova de que o termo seja inútil: ele só não acrescenta nada ao universo já coletado, e a ordem do método guloso pode trocar "
             "qual de dois termos parecidos aparece como dispensável."]
    situ = lambda x: ("sem resultado" if x["sem_resultados"] else "só não elegíveis" if x["n_elegiveis"] == 0 else "elegíveis repetidos")
    tabela = {"cabecalho": ["Termo", "Artigos elegíveis", "Créditos", "Situação"],
              "linhas": [[_link_termo(x["termo_id"], _rot(x["termo_id"], x.get("query"))), fmt.numero(x["n_elegiveis"]),
                          fmt.numero(x["creditos"]), situ(x)] for x in disp]}
    pares = [("Termos dispensáveis", fmt.numero(len(disp))), ("Créditos desses termos", fmt.numero(creditos)),
             ("Créditos do total", fmt.numero(c.get("creditos_total"))), ("Critério de desempate do método guloso", c.get("criterio_desempate") or "—")]
    return _bloco("termos_dispensaveis", titulo, None, f"{fmt.numero(universo)} artigos elegíveis no universo; cobertura relativa ao já coletado",
                  texto, aviso=AVISO_RELATIVO, pares=pares, tabela=tabela)


def bloco_insubstituiveis(c):
    unicos = (c or {}).get("com_unicos") or []
    n_termos = (c or {}).get("n_termos") or 0
    if not unicos:
        return _vazio("termos_unicos", "Termos que trazem artigos que nenhum outro traz: nenhum", "Sem artigos elegíveis ou todos repetidos.")
    soma = sum(u["n_unicos"] for u in unicos)
    titulo = (f"{fmt.numero(len(unicos))} dos {fmt.numero(n_termos)} termos trazem artigos elegíveis que mais nenhum termo traz "
              f"({fmt.numero(soma)} artigos): cortá-los perde esses artigos")
    itens = [{"rotulo": _rot(u["termo_id"], u.get("query")), "total": u["n_elegiveis"], "parte": u["n_unicos"],
              "href": _href("/literatura/artigos", termo=u["termo_id"])} for u in unicos]
    graf = g.barras_proporcao(itens, titulo, "Parte dos artigos elegíveis de cada termo que nenhum outro termo trouxe",
                              rotulo_parte="Só deste termo", rotulo_resto="Também em outro termo")
    texto = ["Estes termos não podem ser cortados sem perda: cada um achou artigos elegíveis que nenhum outro termo achou.",
             "Isso mede o que aconteceu nesta coleta. Com outro conjunto de termos, o que é exclusivo mudaria."]
    tabela = {"cabecalho": ["Termo", "Artigos elegíveis", "Só deste termo", "Também em outro termo"],
              "linhas": [[_link_termo(u["termo_id"], _rot(u["termo_id"], u.get("query"))), fmt.numero(u["n_elegiveis"]), fmt.numero(u["n_unicos"]),
                          fmt.numero(u["n_elegiveis"] - u["n_unicos"])] for u in unicos]}
    return _bloco("termos_unicos", titulo, graf, f"{fmt.numero(len(unicos))} termos com elegíveis exclusivos; cobertura relativa ao já coletado",
                  texto, aviso=AVISO_RELATIVO, tabela=tabela)


# ---------------------------------------------------------------- 3. web
def _tec(chave):
    return rotulos.TECNOLOGIAS.get(chave, chave or "—")


def _rot_celula(l):
    return f"{_tec(l['tecnologia'])} · {l['modelo_id']}"


def blocos_cobertura_web(dados, custos=True):
    """Blocos da coleta web (tecnologia x modelo de consulta). `dados` = `analise_cobertura_web()`."""
    dados = dados or {}
    if not dados.get("tem_dados"):
        return [_vazio("web_precisao", "Cobertura da busca web: ainda não há resultados web", "Nenhuma busca web registrada.")]
    if not dados.get("tem_triagem"):
        return [_vazio("web_precisao", "Cobertura da busca web: sem triagem de escopo para medir", "Rode `triar-escopo --fonte web`.")]
    return [bloco_precisao_web(dados, custos=custos), bloco_sobreposicao_modelos(dados), bloco_curva_web(dados, custos=custos)]


def bloco_precisao_web(d, custos=True):
    celulas = [c for c in d.get("por_celula") or [] if c.get("n_triados")]
    modelos = [m for m in d.get("por_modelo") or [] if m.get("n_triados")]
    ordenados = sorted(celulas, key=lambda c: (-(c["precisao"] or 0), c["tecnologia"], c["modelo_id"]))
    if len(modelos) >= 2:
        a, b = sorted(modelos, key=lambda m: -(m["precisao"] or 0))[:2]
        titulo = (f"Na busca web, {_p(a['precisao'])} dos resultados do modelo {a['modelo_id']} são elegíveis, contra {_p(b['precisao'])} do "
                  f"{b['modelo_id']} (n = {fmt.numero(a['n_triados'])} e {fmt.numero(b['n_triados'])})")
    else:
        titulo = f"Na busca web, {_p((d.get('n_elegiveis') or 0) / d['n_triados'] if d.get('n_triados') else None)} dos resultados triados são elegíveis"
    itens = [{"rotulo": _rot_celula(c), "total": c["n_triados"], "parte": c["n_elegiveis"]} for c in ordenados]
    graf = g.barras_proporcao(itens, titulo, "Parte dos resultados de cada tecnologia e modelo de consulta que o modelo julgou elegível",
                              rotulo_parte="Elegíveis", rotulo_resto="Não elegíveis")
    perfis = ", ".join(f"{m['modelo_id']} = {m.get('perfil') or '—'}" for m in d.get("por_modelo") or [])
    texto = ["Cada barra é uma combinação de tecnologia e modelo de consulta (M01 busca só sites .gov.br; M02 busca sem esse filtro). "
             "Mostra onde cada consulta rende mais páginas dentro do escopo."]
    if custos:
        texto.append(f"Perfis: {perfis}. O custo é o da busca (US$ {fmt.decimal(d.get('custo_total_usd'), 2)} no total), não o da triagem.")
        cabecalho = ["Tecnologia", "Modelo", "Perfil", "Resultados", "Elegíveis", "Quarentena", "Precisão", "Intervalo 95%", "Só deste par",
                     "Custo da busca", "Elegíveis por US$"]
        linhas_tab = [[_tec(c["tecnologia"]), c["modelo_id"], c.get("perfil") or "—", fmt.numero(c["n_triados"]), fmt.numero(c["n_elegiveis"]),
                       fmt.numero(c["n_quarentena"]), _p(c["precisao"], 1), _ic(c), fmt.numero(c["n_elegiveis_unicos"]),
                       _usd(c["custo_usd"]), fmt.numero(c["elegiveis_por_usd"]) if c.get("elegiveis_por_usd") is not None else "—"]
                      for c in ordenados]
        pares = [("Resultados distintos (URL e UF)", fmt.numero(d.get("n_resultados"))), ("Com veredito válido", fmt.numero(d.get("n_triados"))),
                 ("Elegíveis", fmt.numero(d.get("n_elegiveis"))), ("Custo total das buscas", _usd(d.get("custo_total_usd"))),
                 ("Item", "par (URL, UF) de secretaria estadual; resultado municipal fica de fora")]
    else:
        texto.append(f"Perfis: {perfis}.")
        cabecalho = ["Tecnologia", "Modelo", "Perfil", "Resultados", "Elegíveis", "Quarentena", "Precisão", "Intervalo 95%", "Só deste par"]
        linhas_tab = [[_tec(c["tecnologia"]), c["modelo_id"], c.get("perfil") or "—", fmt.numero(c["n_triados"]), fmt.numero(c["n_elegiveis"]),
                       fmt.numero(c["n_quarentena"]), _p(c["precisao"], 1), _ic(c), fmt.numero(c["n_elegiveis_unicos"])]
                      for c in ordenados]
        pares = [("Resultados distintos (URL e UF)", fmt.numero(d.get("n_resultados"))), ("Com veredito válido", fmt.numero(d.get("n_triados"))),
                 ("Elegíveis", fmt.numero(d.get("n_elegiveis"))),
                 ("Item", "par (URL, UF) de secretaria estadual; resultado municipal fica de fora")]
    tabela = {"cabecalho": cabecalho, "linhas": linhas_tab}
    return _bloco("web_precisao", titulo, graf, f"{fmt.numero(d.get('n_triados'))} resultados triados; elegível = opinião do modelo", texto,
                  aviso=AVISO_RELATIVO_WEB, pares=pares, tabela=tabela)


def bloco_sobreposicao_modelos(d):
    sobre = d.get("sobreposicao_modelos") or []
    modelos = {m["modelo_id"]: m for m in d.get("por_modelo") or []}
    if not sobre:
        return _vazio("web_sobreposicao", "Sobreposição entre modelos de consulta: só há um modelo com resultados", "Compare quando houver dois.")
    s = sobre[0]
    a, b = s["modelo_a"], s["modelo_b"]
    titulo = (f"Os modelos {a} e {b} se repetem pouco: só {fmt.numero(s['n_em_comum'])} de {fmt.numero(s['n_uniao'])} páginas elegíveis "
              f"aparecem nos dois ({_p(s['jaccard'])}); cada um traz páginas que o outro não traz")
    itens = [{"rotulo": f"{m} ({modelos[m].get('perfil') or '—'}): só nele", "total": modelos[m]["n_elegiveis"], "parte": modelos[m]["n_elegiveis_unicos"]}
             for m in (a, b) if m in modelos]
    graf = g.barras_proporcao(itens, titulo, "Parte das páginas elegíveis de cada modelo de consulta que o outro modelo não trouxe",
                              rotulo_parte="Só neste modelo", rotulo_resto="Também no outro modelo")
    texto = [f"O {b} acrescenta {fmt.numero(s['so_b'])} páginas elegíveis que o {a} não traz e o {a} acrescenta {fmt.numero(s['so_a'])} que o {b} não traz. "
             "Usar os dois modelos se justifica enquanto cada um trouxer páginas exclusivas.",
             "Jaccard é a parte em comum sobre o total dos dois (100% = mesmas páginas)."]
    tabela = {"cabecalho": ["Par", "Elegíveis do 1º", "Elegíveis do 2º", "Em comum", "Em qualquer um", "Jaccard (elegíveis)", "Jaccard (todos os resultados)"],
              "linhas": [[f"{x['modelo_a']} e {x['modelo_b']}", fmt.numero(x["n_a"]), fmt.numero(x["n_b"]), fmt.numero(x["n_em_comum"]),
                          fmt.numero(x["n_uniao"]), _p(x["jaccard"], 1), _p(x["jaccard_resultados"], 1)] for x in sobre]}
    return _bloco("web_sobreposicao", titulo, graf, f"{fmt.numero(s['n_uniao'])} páginas elegíveis na união; cobertura relativa ao já coletado", texto,
                  aviso=AVISO_RELATIVO_WEB, tabela=tabela)


def bloco_curva_web(d, custos=True):
    inc = d.get("incremental") or {}
    passos, universo = inc.get("passos") or [], inc.get("universo") or 0
    if not passos or not universo:
        return _vazio("web_curva", "Cobertura acumulada na web: sem páginas elegíveis para somar", "Faltam resultados da triagem web.")
    n = inc.get("n_chaves") or len(passos)
    m95 = _marco(inc, 95)
    if m95 and m95["atingido"]:
        titulo = (f"Com {fmt.numero(m95['n_chaves'])} dos {fmt.numero(n)} pares tecnologia × modelo já se encontram 95% das páginas elegíveis "
                  f"coletadas ({fmt.numero(m95['acumulado'])} de {fmt.numero(universo)})")
        corte = m95["n_chaves"]
    else:
        titulo = f"Cobertura acumulada dos {fmt.numero(n)} pares tecnologia × modelo"
        corte = None
    pontos = [(0, 0)] + [(p["ordem"], p["pct_acumulado"]) for p in passos if p.get("pct_acumulado") is not None]
    graf = g.linha_com_corte(pontos, titulo, "Percentual acumulado das páginas elegíveis, somando os pares na ordem em que cada um acrescenta mais páginas novas",
                             "Pares somados", "% das páginas elegíveis", corte=corte, teto=95, rotulo_corte=f"{corte} pares" if corte else "",
                             rotulo_teto="95%")
    disp = inc.get("dispensaveis") or []
    texto = ["Cada ponto soma mais um par (uma tecnologia com um modelo de consulta), sempre o que traz mais páginas elegíveis novas. UFs não entram: "
             "uma UF não substitui outra."]
    if custos and m95 and m95["atingido"]:
        texto.append(f"Esses {fmt.numero(m95['n_chaves'])} pares custaram {_usd(m95['creditos_acumulados'])} de {_usd(inc.get('custo_total'))} em buscas.")
    texto.append("Nenhum par é dispensável: todos trazem páginas elegíveis exclusivas." if not disp else
                 f"{fmt.numero(len(disp))} pares não acrescentam nenhuma página elegível ao que os outros trazem.")
    pares = [("Universo (páginas elegíveis)", fmt.numero(universo)), ("Pares considerados", fmt.numero(n))]
    if custos:
        pares.append(("Custo total das buscas", _usd(inc.get("custo_total"))))
    for m in inc.get("marcos") or []:
        if m["atingido"]:
            val = (f"{fmt.numero(m['n_chaves'])} pares, {_usd(m['creditos_acumulados'])}, {fmt.numero(m['acumulado'])} páginas"
                   if custos else f"{fmt.numero(m['n_chaves'])} pares, {fmt.numero(m['acumulado'])} páginas")
        else:
            val = "não alcançado"
        pares.append((f"Menor prefixo que alcança {m['percentual']}%", val))
    pares.append(("Critério de desempate", inc.get("criterio_desempate") or "—"))
    if custos:
        cabecalho = ["Ordem", "Tecnologia", "Modelo", "Elegíveis do par", "Novas que ele acrescenta", "Acumulado", "% acumulada", "Custo acumulado"]
        linhas_tab = [[p["ordem"], _tec(p["tecnologia"]), p["modelo_id"], fmt.numero(p["n_elegiveis"]), fmt.numero(p["ganho"]),
                       fmt.numero(p["acumulado"]), _pc(p["pct_acumulado"], 1), _usd(p["custo_acumulado_usd"])] for p in passos]
    else:
        cabecalho = ["Ordem", "Tecnologia", "Modelo", "Elegíveis do par", "Novas que ele acrescenta", "Acumulado", "% acumulada"]
        linhas_tab = [[p["ordem"], _tec(p["tecnologia"]), p["modelo_id"], fmt.numero(p["n_elegiveis"]), fmt.numero(p["ganho"]),
                       fmt.numero(p["acumulado"]), _pc(p["pct_acumulado"], 1)] for p in passos]
    tabela = {"cabecalho": cabecalho, "linhas": linhas_tab}
    return _bloco("web_curva", titulo, graf, f"{fmt.numero(universo)} páginas elegíveis; método guloso por par tecnologia × modelo", texto,
                  aviso=AVISO_RELATIVO_WEB, pares=pares, tabela=tabela)
