"""Blocos da analise por termo (RE7) e do teste barato de combinacoes (RD12), no mesmo formato de `painel/analises_blocos.py`:
um grafico, um titulo que CONTA A CONCLUSAO com os numeros, um "Como ler" em linguagem simples e a memoria de calculo.

Funcoes puras: recebem os dicionarios de `adaptadores/leitura_termos_ruido.py` (`analise_prefiltro_web`, `analise_ruido_por_termo`,
`analise_simulacao_contexto`) e devolvem listas de blocos. Nao tocam no banco.

Tudo aqui e SUGESTAO PARA AVALIACAO DO PESQUISADOR. "Elegivel" e opiniao do modelo sobre o escopo, nao achado confirmado, e nenhuma
palavra de veredito ("bom", "ruim") aparece: a simulacao mostra o ruido que sai ao lado dos uteis que se perdem.

O campo `link` de cada bloco, quando existe, e {"href", "rotulo"}."""
from dominio import analise_termos as at
from painel import analises_blocos as b, formatacao as fmt, graficos_analises as g, rotulos_escopo

AVISO_SUGESTAO = ("Sugestão para avaliação do pesquisador: nada foi aplicado e nada muda na busca sozinho. "
                  "'Elegível' é a opinião do modelo sobre o escopo, não um achado confirmado.")
MAX_BARRAS = 40                        # barras por grafico de proporcao
MAX_UFS = 15
MAX_PALAVRAS = 12
MAX_LINHAS_TERMO = 5                   # candidatas por termo na tabela da simulacao
MAX_TERMOS_MAPA = 40
MAX_DOMINIOS_MAPA = 8
MIN_ELEGIVEIS_TERMO = at.N_MINIMO_ELEGIVEIS_SIMULACAO
_BLOCO = b._bloco
_ORIGEM = {"padrao": "padrão", "automatica": "automática"}


def _num(n):
    return fmt.numero(n)


def _ic(p):
    """'80,8% (IC 95%: 78,3 a 83,0)' de uma proporcao de `analise_termos.proporcao`; '—' sem denominador."""
    if not p or p.get("pct") is None:
        return "—"
    return f"{fmt.decimal(p['pct'], 1)}% (IC 95%: {fmt.decimal(p['ic_inf'], 1)} a {fmt.decimal(p['ic_sup'], 1)})"


def _p0(p):
    """Percentual sem casas ('81%') de uma proporcao; '—' sem denominador."""
    return "—" if not p or p.get("pct") is None else f"{fmt.decimal(p['pct'], 0)}%"


def _rotulo_dominio(chave):
    return rotulos_escopo.rotulo(rotulos_escopo.DOMINIOS, chave, "—") if chave else "—"


def _rotulo_motivo(chave):
    return rotulos_escopo.rotulo(rotulos_escopo.CATEGORIAS, chave, "—") if chave else "—"


def _vazio(id_, titulo, aviso):
    return _BLOCO(id_, titulo, aviso=aviso)


# ================================================================== RE7a: pre-filtro da web
def blocos_prefiltro(dados):
    """Blocos da auditoria do pre-filtro (web): grupos de download, limite por UF, palavras candidatas e desempenho das palavras
    atuais. Sem dados (sem triagem de escopo da web ou sem coleta principal), um unico bloco com o aviso."""
    dados = dados or {}
    if not dados.get("tem_dados") or not dados.get("n_validos"):
        return [_vazio("prefiltro", "Auditoria do pré-filtro: ainda não há dados para comparar",
                       "Precisa da triagem de escopo da web (`triar-escopo --fonte web`) e da coleta principal (`pipeline-uf`).")]
    return [x for x in (_bloco_grupos(dados), _bloco_limite_uf(dados), _bloco_palavras_candidatas(dados),
                        _bloco_desempenho_prefiltro(dados)) if x]


def _bloco_grupos(d):
    grupos = {x["chave"]: x for x in d["grupos"]}
    sel, nao = grupos.get("selecionada"), grupos.get("nao_selecionada")
    if not sel or not nao or not nao["n"]:
        return None
    ordem = ["selecionada"] + [x["chave"] for x in d["grupos"] if x["chave"] not in ("selecionada", "nao_selecionada")]
    itens = [{"rotulo": grupos[k]["rotulo"], "total": grupos[k]["n"], "parte": grupos[k]["n_elegivel"],
              "href": b._href("/triagem-escopo", fonte="web", status="elegivel")} for k in ordem if grupos[k]["n"]]
    titulo = (f"Dos {_num(nao['n'])} resultados web que não foram baixados, {_num(nao['n_elegivel'])} ({_p0(nao['elegivel'])}) "
              f"foram julgados elegíveis pelo modelo; entre os baixados, {_p0(sel['elegivel'])}")
    graf = g.barras_proporcao(itens, titulo, "Parte de cada grupo de resultados web julgada elegível pelo modelo",
                              rotulo_parte="Elegíveis", rotulo_resto="Não elegíveis")
    texto = ["Como ler: cada barra é um grupo de resultados da busca web; a parte verde é a fatia que o modelo julgou possivelmente útil. "
             "Se um grupo que nós deixamos de baixar tem muitos elegíveis, a regra que o descartou está perdendo material.",
             f"Foram deixados de fora {_num(nao['n'])} resultados: "
             + "; ".join(f"{x['rotulo']}: {_num(x['n'])} ({_p0(x['elegivel'])} elegíveis)" for x in d["grupos"]
                         if x["chave"] not in ("selecionada", "nao_selecionada")) + "."]
    return _BLOCO("prefiltro_grupos", titulo, graf,
                  f"{_num(d['n_validos'])} resultados web com veredito válido da coleta {d.get('run_id')}; intervalo de Wilson 95%",
                  texto, aviso=AVISO_SUGESTAO, link={"href": b._href("/triagem-escopo", fonte="web", status="elegivel"),
                                                     "rotulo": "Ver os elegíveis da busca web"},
                  pares=[("Coleta analisada", str(d.get("run_id"))), ("Resultados com veredito válido", _num(d["n_validos"])),
                         ("Vereditos inválidos (fora das contas)", _num(d["n_invalidos"])),
                         ("Sem decisão de download registrada", _num(d["n_sem_selecao"]))],
                  tabela={"cabecalho": ["Grupo", "Avaliados", "Elegíveis", "% elegíveis (IC 95%)", "% elegíveis + quarentena"],
                          "linhas": [[x["rotulo"], _num(x["n"]), _num(x["n_elegivel"]), _ic(x["elegivel"]), _p0(x["util"])]
                                     for x in d["grupos"]]})


def _bloco_limite_uf(d):
    lim = d.get("limite_por_uf") or {}
    ufs = [u for u in lim.get("por_uf") or [] if u["n_no_limite"]]
    if not ufs:
        return None
    perdidos, teto = lim["n_elegiveis_perdidos"], lim.get("teto_necessario")
    titulo = (f"O limite de {lim['limite']} por UF deixou de fora {_num(perdidos)} resultados elegíveis em {lim['n_ufs_com_perda']} UFs"
              + (f"; um limite de {teto} os teria pegado, ao custo de {_num(lim['curva'][-1]['downloads_extras'])} downloads a mais"
                 if teto and lim.get("curva") else ""))
    top = sorted(ufs, key=lambda u: (-u["n_elegiveis_perdidos"], u["uf"]))[:MAX_UFS]
    itens = [{"rotulo": f"{u['uf']} (limite necessário: {u['teto_necessario'] or '—'})", "total": u["n_triados"],
              "parte": u["n_elegiveis_perdidos"], "href": b._href("/triagem-escopo", fonte="web", status="elegivel")} for u in top]
    graf = g.barras_proporcao(itens, titulo, "Resultados cortados pelo limite em cada UF e quantos eram elegíveis",
                              rotulo_parte="Elegíveis perdidos", rotulo_resto="Não elegíveis")
    curva = lim.get("curva") or []
    graf2 = g.linha_com_corte([(c["downloads_extras"], c["elegiveis_capturados"]) for c in curva],
                              "Elegíveis recuperados conforme o limite sobe",
                              "Elegíveis recuperados em função dos downloads a mais, somando as UFs", "Downloads a mais",
                              "Elegíveis recuperados") if len(curva) > 1 else ""
    texto = ["Como ler: o download ordena os resultados de cada UF (mais achados pelas consultas primeiro) e baixa só os 40 primeiros. "
             "Cada barra mostra, para uma UF, quantos resultados ficaram depois do 40º e quantos deles o modelo julgou elegíveis. "
             "O número entre parênteses é a posição do último elegível perdido: o limite mínimo que pegaria todos.",
             "A curva mostra o custo e o benefício: cada ponto é um limite (40, 50, 60...), com quantos elegíveis seriam recuperados e "
             "quantos downloads a mais isso pede. A ordem aqui é reconstruída (mais ocorrências, depois melhor posição); o desempate "
             "exato da coleta não está no banco."]
    return _BLOCO("prefiltro_limite_uf", titulo, graf + graf2, f"{lim['n_ufs_com_perda']} UFs com perda; sugestão, nada aplicado", texto,
                  aviso=AVISO_SUGESTAO,
                  pares=[("Limite atual por UF", str(lim["limite"])), ("Elegíveis perdidos pelo limite", _num(perdidos)),
                         ("Elegíveis + quarentena perdidos", _num(lim["n_uteis_perdidos"])),
                         ("Limite que pegaria todos os elegíveis", str(teto or "—"))],
                  tabela={"cabecalho": ["UF", "Resultados válidos antes do corte", "Cortados", "Elegíveis perdidos", "Limite necessário",
                                        "Downloads a mais"],
                          "linhas": [[u["uf"], _num(u["n_candidatos"]), _num(u["n_no_limite"]), _num(u["n_elegiveis_perdidos"]),
                                      str(u["teto_necessario"] or "—"), _num(u["downloads_extras"])] for u in ufs]})


def _bloco_palavras_candidatas(d):
    cands = (d.get("palavras_candidatas") or [])[:MAX_PALAVRAS]
    if not cands:
        return _vazio("prefiltro_palavras", "Nenhuma palavra nova se destaca nos elegíveis que o pré-filtro descartou",
                      f"Nenhuma palavra aparece em {at.MIN_SUPORTE_PREFILTRO} ou mais dos {_num(d.get('n_frente'))} elegíveis descartados "
                      "e mais do que nos baixados.")
    itens = [{"rotulo": c["palavra"], "total": c["capturados"]["n"], "parte": c["capturados"]["n_elegivel"]} for c in cands]
    titulo = (f"Palavras que aparecem mais nos {_num(d['n_frente'])} elegíveis descartados pelo pré-filtro do que nos "
              f"{_num(d['n_fundo'])} baixados: " + ", ".join(c["palavra"] for c in cands[:3]) + "…")
    graf = g.barras_proporcao(itens, titulo, "Entre os descartados pelo pré-filtro que contêm a palavra, quantos são elegíveis",
                              rotulo_parte="Elegíveis", rotulo_resto="Não elegíveis")
    texto = ["Como ler: cada barra é uma palavra que ainda não está no pré-filtro. O tamanho da barra é quantos resultados descartados "
             "contêm a palavra, e a parte verde é quantos deles são elegíveis. Palavra com barra quase toda verde pegaria bastante "
             "material útil sem trazer muito ruído; palavra com muito cinza traria ruído junto.",
             f"A lista só traz palavras presentes em pelo menos {at.MIN_SUPORTE_PREFILTRO} dos elegíveis descartados; palavras "
             "já cobertas pelo pré-filtro e palavras muito comuns ficam de fora. Palavras de nome próprio (siglas, órgãos) podem "
             "indicar um assunto, não uma regra geral."]
    return _BLOCO("prefiltro_palavras", titulo, graf, f"{_num(d['n_frente'])} elegíveis descartados contra {_num(d['n_fundo'])} baixados; "
                  "frequência = número de resultados que contêm a palavra", texto, aviso=AVISO_SUGESTAO,
                  tabela={"cabecalho": ["Palavra", "Em quantos elegíveis descartados", "Em quantos baixados", "Quantas vezes mais frequente (lift)",
                                        "Descartados que a contêm", "% elegíveis entre eles (IC 95%)"],
                          "linhas": [[c["palavra"], f"{c['n_frente']} ({fmt.decimal(c['pct_frente'], 1)}%)",
                                      f"{c['n_fundo']} ({fmt.decimal(c['pct_fundo'], 1)}%)", fmt.decimal(c["lift"], 1),
                                      _num(c["capturados"]["n"]), _ic(c["capturados"]["elegivel"])] for c in cands]},
                  pares=[("Suporte mínimo (itens)", str(at.MIN_SUPORTE_PREFILTRO)),
                         ("Medida de contraste", "log da razão de chances suavizada (+0,5 em cada contagem) e lift"),
                         ("Palavras do pré-filtro atual", ", ".join(d.get("prefiltro") or []) or "—")])


def _bloco_desempenho_prefiltro(d):
    pal = [x for x in d.get("desempenho_prefiltro") or [] if x["n"]]
    if not pal:
        return None
    pior = pal[0]
    titulo = (f"Das {len(pal)} palavras do pré-filtro, a de menor acerto é '{pior['palavra']}': "
              f"{_p0(pior['elegivel'])} dos {_num(pior['n'])} resultados que a contêm são elegíveis")
    itens = [{"rotulo": x["palavra"], "total": x["n"], "parte": x["n_elegivel"]} for x in pal]
    graf = g.barras_proporcao(itens, titulo, "Resultados que contêm cada palavra do pré-filtro e quantos são elegíveis",
                              rotulo_parte="Elegíveis", rotulo_resto="Não elegíveis")
    texto = ["Como ler: para cada palavra do pré-filtro atual, quanto dos resultados que a contêm o modelo julgou elegíveis. É uma "
             "medida de precisão: palavra com barra curta deixa passar muito ruído. 'Pega sozinha' é quantos resultados só ela "
             "deixou passar: se for zero, tirar a palavra não muda quem é baixado."]
    return _BLOCO("prefiltro_desempenho", titulo, graf, f"{_num(sum(x['n'] for x in pal))} presenças de palavras; resultados com veredito válido",
                  texto, aviso=AVISO_SUGESTAO,
                  tabela={"cabecalho": ["Palavra do pré-filtro", "Resultados que a contêm", "Elegíveis", "% elegíveis (IC 95%)", "Pega sozinha"],
                          "linhas": [[x["palavra"], _num(x["n"]), _num(x["n_elegivel"]), _ic(x["elegivel"]), _num(x["n_unica"])]
                                     for x in pal]})


# ================================================================== RE7b: ruido por termo
def blocos_ruido_termos(dados):
    """Blocos do ruido por termo dos artigos: tabela termo -> acao sugerida, mapa termo x area do ruido e operadores negativos."""
    dados = dados or {}
    if not dados.get("tem_dados") or not dados.get("tabela"):
        return [_vazio("ruido_termos", "Ruído por termo: ainda não há dados para comparar",
                       "Precisa da triagem de escopo dos artigos (`triar-escopo --fonte artigos`).")]
    return [x for x in (_bloco_tabela_termos(dados), _bloco_mapa_ruido(dados), _bloco_negativos(dados)) if x]


def _href_termo_artigos(l):
    return b._href("/literatura/artigos", termo=l.get("termo_id")) if l.get("termo_id") else None


def _bloco_tabela_termos(d):
    linhas = d["tabela"]
    com_n = [l for l in linhas if l["n"] >= at.N_MINIMO_TERMO]
    baixos = [l for l in com_n if l["elegivel"]["pct"] is not None and l["elegivel"]["pct"] < 100 * at.LIMITE_ELEGIVEL_MANTER]
    piores = baixos[:3]
    titulo = (f"Em {len(baixos)} dos {len(com_n)} termos com ao menos {at.N_MINIMO_TERMO} resultados, menos da metade é elegível"
              + (": " + ", ".join(f"{l['termo']} ({_p0(l['elegivel'])})" for l in piores) if piores else ""))
    itens = [{"rotulo": (f"{l['termo_id']} " if l.get("termo_id") else "") + str(l["termo"]), "total": l["n"], "parte": l["n_elegivel"],
              "href": _href_termo_artigos(l)} for l in linhas[:MAX_BARRAS]]
    graf = g.barras_proporcao(itens, titulo, "Resultados de cada termo e quantos o modelo julgou elegíveis (do pior ao melhor)",
                              rotulo_parte="Elegíveis", rotulo_resto="Não elegíveis")
    acoes = {}
    for l in linhas:
        acoes[l["acao"]] = acoes.get(l["acao"], 0) + 1
    texto = ["Como ler: cada barra é um termo da busca; a parte verde é a fatia dos seus resultados que o modelo julgou elegível. "
             "Termos com barra curta trazem muito ruído. A última coluna da tabela sugere o que avaliar, por uma regra simples e "
             "visível (a regra aparece na frase de cada linha).",
             "Ações sugeridas: " + "; ".join(f"{a}: {n}" for a, n in sorted(acoes.items(), key=lambda kv: (-kv[1], kv[0]))) + ". "
             "Termos com poucos resultados ficam como 'amostra pequena': o intervalo de confiança é largo demais para concluir."]
    return _BLOCO("ruido_tabela", titulo, graf, f"{_num(d['n_itens'])} artigos com veredito válido em {d['n_termos']} termos; "
                  "um artigo conta em cada termo que o achou; intervalo de Wilson 95%", texto, aviso=AVISO_SUGESTAO,
                  link={"href": b._href("/triagem-escopo", fonte="artigo", status="todos"), "rotulo": "Ver os vereditos dos artigos"},
                  pares=[("Artigos com veredito válido", _num(d["n_itens"])), ("Vereditos inválidos (fora das contas)", _num(d["n_invalidos"])),
                         ("Termos", _num(d["n_termos"])),
                         ("Regra de 'manter'", f"{int(100 * at.LIMITE_ELEGIVEL_MANTER)}% ou mais de elegíveis"),
                         ("Regra de área dominante", f"{int(100 * at.FRACAO_AREA_DOMINANTE)}% do ruído e ao menos {at.MIN_ITENS_AREA_DOMINANTE} itens")],
                  tabela={"cabecalho": ["Termo", "Resultados", "% elegíveis (IC 95%)", "Principal motivo do ruído", "Área do ruído",
                                        "Ação sugerida", "Por quê"],
                          "linhas": [[(f"{l['termo_id']} " if l.get("termo_id") else "") + str(l["termo"]), _num(l["n"]), _ic(l["elegivel"]),
                                      _rotulo_motivo(l["motivo_top"]), (_rotulo_dominio(l["dominio_top"])
                                                                        + (f" ({fmt.decimal(l['pct_dominio_top'], 0)}% do ruído)" if l["pct_dominio_top"] is not None else "")),
                                      l["acao"], l["regra"] + (f"; {l['observacao']}" if l["observacao"] else "")] for l in linhas]})


def _bloco_mapa_ruido(d):
    fichas = [f for f in d.get("fichas") or [] if f["n_itens"] >= at.N_MINIMO_TERMO and f["dominios"]][:MAX_TERMOS_MAPA]
    if not fichas:
        return None
    total_dom = {}
    for f in d["fichas"]:
        for k, n in f["dominios"].items():
            total_dom[k] = total_dom.get(k, 0) + n
    dominios = [k for k, _ in sorted(total_dom.items(), key=lambda kv: (-kv[1], kv[0]))][:MAX_DOMINIOS_MAPA]
    soma = sum(total_dom.values())
    topo = dominios[0]
    linhas = [{"chave": f["termo"], "rotulo": f["termo"]} for f in fichas]
    colunas = [{"chave": k, "rotulo": _rotulo_dominio(k)} for k in dominios]
    valores = {(f["termo"], k): f["dominios"].get(k, 0) for f in fichas for k in dominios}
    hrefs = {(f["termo"], k): b._href("/triagem-escopo", fonte="artigo", termo=f["termo"], dominio_tematico=k, status="todos")
             for f in fichas for k in dominios}
    titulo = (f"A área que mais gera ruído é '{_rotulo_dominio(topo)}': {_num(total_dom[topo])} dos {_num(soma)} resultados "
              "não elegíveis dos termos")
    graf = g.mapa_de_calor_assimetrico(linhas, colunas, valores, titulo, descricao="Número de resultados não elegíveis (excluídos ou em "
                                       "quarentena) de cada termo, por área temática do ruído", hrefs=hrefs)
    texto = ["Como ler: cada linha é um termo e cada coluna é uma área do conhecimento. O número na célula é quantos resultados "
             "daquele termo não são elegíveis e pertencem àquela área; quanto mais escura, mais ruído. Um termo cujo ruído se concentra "
             "numa só área é candidato a ganhar um contexto que afaste essa área."]
    return _BLOCO("ruido_mapa", titulo, graf, f"{len(fichas)} termos com ao menos {at.N_MINIMO_TERMO} resultados; só as {len(dominios)} áreas "
                  "mais frequentes", texto, aviso=AVISO_SUGESTAO,
                  tabela={"cabecalho": ["Termo de origem do ruído", "Motivo", "Área", "Itens"],
                          "linhas": [[(m["termo_gerador"] or "—"), _rotulo_motivo(m["categoria_motivo"]), _rotulo_dominio(m["dominio_tematico"]),
                                      _num(m["n"])] for m in (d.get("matriz") or [])[:20]]})


def _bloco_negativos(d):
    negativos = d.get("negativos") or []
    if not negativos:
        return None
    n_seguros = (d.get("por_veredito") or {}).get("seguro", sum(1 for n in negativos if n["veredito"] == "seguro"))
    mostrados = sorted(negativos, key=lambda n: (_ordem_veredito(n["veredito"]), -n["n_excluidos_atingidos"], n["chave"]))[:MAX_PALAVRAS]
    n_termos = d.get("n_termos_com_negativo_seguro", 0)
    ganho = d.get("ganho_minimo_negativo", 3)
    titulo = (f"{n_seguros} de {d['n_negativos']} palavras sugeridas pelo modelo para excluir não tirariam nenhum item bom, mas só "
              f"{d.get('n_negativos_seguros_de_ganho', 0)} delas tirariam {ganho} ou mais excluídos; "
              f"{n_termos} termos teriam ao menos uma exclusão sem perda")
    itens = [{"rotulo": f"{n['sinal']} ({rotulos_escopo.rotulo(rotulos_escopo.VEREDITOS, n['veredito'])})", "total": n["n_no_corpus"],
              "parte": n["n_colateral"]} for n in mostrados]
    graf = g.barras_proporcao(itens, titulo, "Itens que contêm a palavra e quantos deles são bons (dano colateral)",
                              rotulo_parte="Itens bons atingidos", rotulo_resto="Outros itens")
    texto = ["Como ler: o modelo sugeriu palavras que apareceriam no ruído. Cada barra é uma palavra: o tamanho é quantos artigos a contêm "
             "e o trecho colorido é quantos desses são bons (elegíveis, em quarentena ou incluídos por você). Barra sem cor = nenhum "
             "artigo bom seria perdido. Palavras centrais do tema são sempre marcadas como perigosas."]
    return _BLOCO("ruido_negativos", titulo, graf, f"{d['n_negativos']} palavras avaliadas (as {len(mostrados)} mais seguras e úteis no gráfico)",
                  texto, aviso=AVISO_SUGESTAO,
                  tabela={"cabecalho": ["Palavra", "Veredito", "Artigos que a contêm", "Excluídos que sairiam", "Itens bons atingidos"],
                          "linhas": [[n["sinal"], rotulos_escopo.rotulo(rotulos_escopo.VEREDITOS, n["veredito"]), _num(n["n_no_corpus"]),
                                      _num(n["n_excluidos_atingidos"]), _num(n["n_colateral"])] for n in negativos[:30]]})


def _ordem_veredito(v):
    return ("seguro", "arriscado", "perigoso").index(v) if v in ("seguro", "arriscado", "perigoso") else 3


# ================================================================== RD12: simulacao de combinacoes
def blocos_simulacao(dados):
    """Blocos do teste barato de combinacoes: resumo por candidata padrao, mapa de perda por termo, tabela de trade-off por termo e
    os limites do teste. Sem dados, um unico bloco com o aviso."""
    dados = dados or {}
    if not dados.get("tem_dados"):
        return [_vazio("simulacao", "Teste de combinações: ainda não há dados para simular",
                       "Precisa dos artigos do Google Scholar já salvos e da triagem de escopo dos artigos.")]
    return [x for x in (_bloco_resumo_simulacao(dados), _bloco_mapa_perda(dados), _bloco_termos_simulacao(dados),
                        _bloco_limites_simulacao(dados)) if x]


def _bloco_resumo_simulacao(d):
    agregado = d.get("agregado") or []
    if not agregado:
        return None
    limite = d.get("limite_perda", at.LIMITE_PERDA_UTEIS)
    n_alerta = sum(1 for a in agregado if a["perde_muitos_uteis"])
    melhor = min(agregado, key=lambda a: (a["perda_elegivel_pct"] if a["perda_elegivel_pct"] is not None else 101, -(a["ruido_removido"]["pct"] or 0)))
    titulo = (f"{n_alerta} de {len(agregado)} contextos candidatos perderiam mais de {fmt.decimal(100 * limite, 0)}% dos elegíveis nos "
              f"resultados já salvos; o que menos perde, {melhor['rotulo']}, perderia {fmt.decimal(melhor['perda_elegivel_pct'], 0)}% "
              f"e tiraria {_p0(melhor['ruido_removido'])} do ruído")
    graf = ""
    for idioma, nome in (("pt", "em português"), ("en", "em inglês")):
        itens = [{"rotulo": a["rotulo"], "total": a["retencao_elegivel"]["n"], "parte": a["retencao_elegivel"]["k"]}
                 for a in agregado if a.get("idioma") == idioma]
        if itens:
            graf += g.barras_proporcao(itens, f"Elegíveis que sobrariam, termos {nome}",
                                       f"Elegíveis dos termos {nome} que continuariam depois de exigir cada contexto (candidatas, não aprovadas)",
                                       rotulo_parte="Elegíveis que sobram", rotulo_resto="Elegíveis perdidos")
    texto = ["Como ler: cada barra é um contexto candidato (palavra ou grupo) que a consulta passaria a exigir. A parte colorida é quantos "
             "elegíveis dos resultados já salvos continuariam. Quanto menor, mais resultados úteis se perderiam. A tabela traz, ao lado, "
             "quanto do ruído sairia: o que importa é o conjunto, não só uma coluna.",
             "São candidatas, não aprovadas: a lista é só um ponto de partida para o pesquisador. Termos sem nenhum elegível ficam de fora "
             "da conta de perda (não há o que perder); para eles o problema é o próprio termo."]
    return _BLOCO("simulacao_resumo", titulo, graf, f"{_num(d['n_pares'])} pares (termo, artigo) em {d['n_termos']} termos; "
                  f"alerta acima de {fmt.decimal(100 * limite, 0)}% de elegíveis perdidos", texto,
                  aviso=AVISO_SUGESTAO + " " + at.LIMITES_SIMULACAO[1],
                  pares=[("Limite de alerta (perda de elegíveis)", f"{fmt.decimal(100 * limite, 0)}%"),
                         ("Unidade somada", "par (termo, artigo): um artigo achado por dois termos conta duas vezes"),
                         ("Termos simulados", _num(d["n_termos"]))],
                  tabela={"cabecalho": ["Contexto candidato", "Idioma", "Termos", "Ruído removido (IC 95%)", "Elegíveis que sobram (IC 95%)",
                                        "Elegíveis perdidos", "Alerta"],
                          "linhas": [[a["rotulo"], (a.get("idioma") or "—"), _num(a["n_termos"]), _ic(a["ruido_removido"]), _ic(a["retencao_elegivel"]),
                                      f"{_num(a['perda_elegivel'])} ({fmt.decimal(a['perda_elegivel_pct'], 0)}%)",
                                      "perde muitos úteis" if a["perde_muitos_uteis"] else "—"] for a in agregado]})


def _bloco_mapa_perda(d):
    termos = [t for t in d.get("termos") or [] if t["n_elegivel"] >= MIN_ELEGIVEIS_TERMO][:MAX_TERMOS_MAPA]
    if not termos:
        return None
    graf = ""
    for idioma, nome in (("pt", "português"), ("en", "inglês")):
        ts = [t for t in termos if (t.get("idioma") or "pt").lower().startswith(idioma)]
        cols = []
        for t in ts:
            for c in t["candidatas"]:
                if c.get("origem") == "padrao" and c["id"] not in [x["chave"] for x in cols]:
                    cols.append({"chave": c["id"], "rotulo": c["rotulo"]})
        if not ts or not cols:
            continue
        linhas = [{"chave": t["termo_id"], "rotulo": f"{t['termo_id']} {t['termo']}"} for t in ts]
        valores = {(t["termo_id"], c["id"]): c["perda_elegivel_pct"] for t in ts for c in t["candidatas"] if c.get("origem") == "padrao"}
        hrefs = {(t["termo_id"], cc["chave"]): b._href("/literatura/artigos", termo=t["termo_id"]) for t in ts for cc in cols}
        graf += g.mapa_de_calor_assimetrico(linhas, cols, valores, f"Elegíveis perdidos (%) em cada combinação, termos em {nome}",
                                            formato=lambda v: f"{v:.0f}%", descricao=f"Percentual dos elegíveis do termo que se perderia ao "
                                            f"exigir cada contexto candidato (termos em {nome}); mais escuro = mais perdas", hrefs=hrefs)
    if not graf:
        return None
    todas = [(t, c) for t in termos for c in t["candidatas"]]
    ok = sum(1 for _, c in todas if not c["perde_muitos_uteis"])
    titulo = (f"Só {ok} de {len(todas)} combinações (termo × contexto) ficam dentro do limite de {fmt.decimal(100 * d['limite_perda'], 0)}% "
              f"de elegíveis perdidos, nos {len(termos)} termos com ao menos {MIN_ELEGIVEIS_TERMO} elegíveis")
    sem_el = [t for t in d["termos"] if not t["n_elegivel"]]
    texto = ["Como ler: cada linha é um termo e cada coluna um contexto candidato; o número é a porcentagem dos elegíveis daquele termo que "
             "se perderia se a consulta exigisse o contexto. Célula escura = perda grande. Clique para ver os artigos do termo.",
             (f"{len(sem_el)} termos não têm nenhum resultado elegível e ficam fora do mapa: nenhum contexto os salva." if sem_el else "")]
    return _BLOCO("simulacao_mapa", titulo, graf, "candidatas, não aprovadas; perda medida só em título e resumo já salvos", texto,
                  aviso=AVISO_SUGESTAO)


def _bloco_termos_simulacao(d):
    termos = [t for t in d.get("termos") or [] if t["n_elegivel"] >= 1 and t["n_excluido"] >= 1]
    if not termos:
        return None
    limite = d["limite_perda"]
    linhas = []
    for t in termos:
        for c in t["candidatas"][:MAX_LINHAS_TERMO]:
            linhas.append([f"{t['termo_id']} {t['termo']}", c["rotulo"], _ORIGEM.get(c.get("origem"), c.get("origem") or "—"),
                           f"{_num(c['n_passam'])} de {_num(t['n'])}", _ic(c["ruido_removido"]), _ic(c["retencao_elegivel"]),
                           f"{_num(c['perda_elegivel'])} de {_num(t['n_elegivel'])}", _p0(c["pct_elegivel_resultante"]),
                           "; ".join(x for x in ("perde muitos úteis" if c["perde_muitos_uteis"] else "",
                                                 "amostra pequena" if c["amostra_pequena"] else "") if x) or "—"])
    um = len(termos) == 1
    titulo = (f"Termo {termos[0]['termo_id']} ({termos[0]['termo']}): o que cada contexto tiraria de ruído e de elegíveis"
              if um else f"Para cada termo, as {MAX_LINHAS_TERMO} candidatas que mais tiram ruído, com os elegíveis perdidos ao lado")
    texto = ["Como ler: para cada termo, cada linha é um contexto que a consulta passaria a exigir. 'Ruído removido' é a fatia dos resultados "
             "excluídos pelo modelo que sairia; 'elegíveis que sobram' é a fatia dos úteis que continuaria; 'elegíveis perdidos' é o número "
             "absoluto de úteis que sairiam. Ordem: quem tira mais ruído primeiro, sem juízo de valor.",
             f"Candidata marcada 'perde muitos úteis' perde mais de {fmt.decimal(100 * limite, 0)}% dos elegíveis do termo. 'Automática' é "
             "palavra achada por contraste entre elegíveis e excluídos do próprio termo; 'padrão' vem da lista de candidatas, não aprovadas."]
    return _BLOCO("simulacao_termos", titulo, None, f"{len(termos)} termos com ao menos 1 elegível e 1 excluído", texto,
                  aviso=AVISO_SUGESTAO, link=({"href": b._href("/literatura/artigos", termo=termos[0]["termo_id"]), "rotulo": "Ver os artigos do termo"}
                                              if um else None),
                  tabela={"cabecalho": ["Termo", "Contexto candidato", "Origem", "Resultados que passam", "Ruído removido (IC 95%)",
                                        "Elegíveis que sobram (IC 95%)", "Elegíveis perdidos", "% elegíveis entre os que passam", "Alerta"],
                          "linhas": linhas})


def _bloco_limites_simulacao(d):
    return _BLOCO("simulacao_limites", "O que este teste não consegue ver",
                  texto=list(d.get("limites") or at.LIMITES_SIMULACAO),
                  aviso="Este teste ordena e descarta candidatas; quem confirma é a amostra real de 1 página (RD4), que ainda precisa de autorização.")
