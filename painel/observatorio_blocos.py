"""Blocos de gráficos e tabelas para as três perspectivas do Observatório."""
from dominio import analises_vies as AV, observatorio_vies as OV
from painel import analises_blocos_vies as bv, formatacao as fmt, graficos_analises as g
from painel.analises_blocos import _bloco


def _bloco_matriz(filtradas, nomes, recortes_vies, subtitulo, n, href):
    m = OV.matriz(filtradas, nomes, tuple(recortes_vies))
    titulo = f"Origem da busca × ângulo predominante: {bv._obras_pl(n)}"
    cols = [{"chave": k, "rotulo": recortes_vies[k]} for k in recortes_vies] + [
        {"chave": "sem_angulo", "rotulo": "Sem ângulo"}
    ]
    rows = [{"chave": k, "rotulo": r} for k, r in m["linhas"]]
    hrefs = {
        (l, c): href(combinacao=l, angulo=c)
        for (l, c), qtd in m["celulas"].items()
        if qtd > 0
    }
    grafico = g.mapa_de_calor_assimetrico(
        rows,
        cols,
        m["celulas"],
        titulo,
        formato=fmt.numero,
        descricao="Obras por combinação exata dos conjuntos de consultas e ângulo predominante da triagem",
        hrefs=hrefs,
    )
    textos = [
        "Cada célula conta obras distintas na combinação exata dos conjuntos que as acharam (uma obra achada em A e em C está só em “A + C”) e no ângulo predominante que o modelo atribuiu. Clique numa célula para ver as obras que a formam.",
        "As linhas “Só …” mostram o que cada conjunto trouxe sozinho: é ali que se vê se as buscas se complementam.",
        "Interseção temática entre viés e aplicações: indisponível na triagem v2. Requer classificação temática independente e multirrótulo.",
    ]
    linhas_tabela = []
    for l_chave, l_rotulo in m["linhas"]:
        celulas_linha = [fmt.numero(m["celulas"].get((l_chave, c["chave"]), 0)) for c in cols]
        soma_linha = sum(m["celulas"].get((l_chave, c["chave"]), 0) for c in cols)
        linhas_tabela.append([l_rotulo] + celulas_linha + [fmt.numero(soma_linha)])
    celulas_total = [
        fmt.numero(sum(m["celulas"].get((l_chave, c["chave"]), 0) for l_chave, _ in m["linhas"]))
        for c in cols
    ]
    linhas_tabela.append(["Total"] + celulas_total + [fmt.numero(n)])
    tabela = {
        "cabecalho": ["Origem"] + [c["rotulo"] for c in cols] + ["Total de obras"],
        "linhas": linhas_tabela,
    }
    return _bloco("obs-matriz", titulo, grafico=grafico, subtitulo=subtitulo, texto=textos, tabela=tabela)


def _bloco_combinacoes(id_, filtradas, nomes, subtitulo, n, href):
    titulo = f"Obras por combinação exata dos conjuntos: {bv._obras_pl(n)}"
    dados_brutos = OV.por_combinacao(filtradas, nomes)
    dados_comb = [(rotulo, count) for _, rotulo, count in dados_brutos]
    hrefs = [href(combinacao=chave) if count > 0 else None for chave, _, count in dados_brutos]
    grafico = bv._barras(
        dados_comb, titulo, "Obras pela combinação exata dos conjuntos de consultas que as acharam", hrefs=hrefs
    )
    texto = [
        "Cada obra conta uma vez, na combinação de todos os conjuntos que acharam os seus itens (web e Scholar). Uma obra achada em A e em C não conta em “Só A” nem em “Só C”."
    ]
    tabela = {
        "cabecalho": ["Combinação", "Obras"],
        "linhas": [[r, fmt.numero(c)] for r, c in dados_comb],
    }
    return _bloco(id_, titulo, grafico=grafico, subtitulo=subtitulo, texto=texto, tabela=tabela)


def _bloco_identidade(filtradas, ambiguas, subtitulo, href):
    titulo = "Identidade das obras: o que a deduplicação juntou e o que ficou em aberto"
    r = OV.resumo(filtradas)
    pares = [
        ("Obras com itens da web e do Scholar", fmt.numero(r["ambas"])),
        ("Obras cujos itens divergem em algum rótulo", fmt.numero(r["com_divergencia"])),
        ("Obras com URL compartilhada com outro artigo (possível duplicata)", fmt.numero(r["possiveis_duplicatas"])),
        ("Referências da web ambíguas, sem obra (no banco todo)", fmt.numero(len(ambiguas))),
    ]
    textos = [
        "Na obra que junta web e Scholar valem os rótulos do artigo do Scholar; a divergência aparece na lista de obras.",
        "As possíveis duplicatas não foram juntadas: juntar ou não é decisão do pesquisador.",
    ]
    link = {"href": href(fonte="ambas"), "rotulo": "Ver as obras com itens da web e do Scholar"}
    return _bloco("obs-identidade", titulo, subtitulo=subtitulo, texto=textos, pares=pares, link=link)


def _bloco_vies_total(subtitulo, n, href):
    titulo = f"{bv._obras_pl(n)} com viés algorítmico como ângulo predominante"
    textos = [
        "O ângulo predominante não mede quantas obras tratam de viés: uma obra classificada como aplicação tecnológica também pode discutir o tema, e a triagem v2 dá um só ângulo por obra."
    ]
    link = {"href": href(), "rotulo": "Ver estas obras"}
    return _bloco("obs-vies-total", titulo, subtitulo=subtitulo, texto=textos, link=link)


def _bloco_eixos(id_, filtradas, eixos, subtitulo, href):
    titulo = "Obras por eixo de exploração"
    dados_eixos = AV.contagem([o.get("eixo") or AV.SEM_EIXO for o in filtradas], ordem=eixos)
    eixos_set = set(eixos)
    hrefs = [
        (href(eixo=OV.SEM_EIXO) if e == AV.SEM_EIXO else href(eixo=e) if e in eixos_set else None)
        if c > 0
        else None
        for e, c in dados_eixos
    ]
    grafico = bv._barras(dados_eixos, titulo, "Obras por eixo de exploração", hrefs=hrefs)
    tabela = {
        "cabecalho": ["Eixo", "Obras"],
        "linhas": [[e, fmt.numero(c)] for e, c in dados_eixos],
    }
    return _bloco(id_, titulo, grafico=grafico, subtitulo=subtitulo, tabela=tabela)


def _bloco_grupos(filtradas, subtitulo):
    titulo = "Obras por grupo de fonte"
    dados_grupos = OV.grupos(filtradas)
    grafico = bv._barras(dados_grupos, titulo, "Obras por grupo de fonte")
    tabela = {
        "cabecalho": ["Grupo", "Obras"],
        "linhas": [[g_nome, fmt.numero(c)] for g_nome, c in dados_grupos],
    }
    return _bloco("obs-vies-grupos", titulo, grafico=grafico, subtitulo=subtitulo, tabela=tabela)


def _bloco_origem(id_, filtradas, nomes, subtitulo, href):
    titulo = "Obras por combinação exata dos conjuntos"
    dados_brutos = OV.por_combinacao(filtradas, nomes)
    dados_origem = [(rotulo, count) for _, rotulo, count in dados_brutos]
    hrefs = [href(combinacao=chave) if count > 0 else None for chave, _, count in dados_brutos]
    grafico = bv._barras(
        dados_origem, titulo, "Obras pela combinação exata dos conjuntos de consultas que as acharam", hrefs=hrefs
    )
    tabela = {
        "cabecalho": ["Combinação", "Obras"],
        "linhas": [[r, fmt.numero(c)] for r, c in dados_origem],
    }
    return _bloco(id_, titulo, grafico=grafico, subtitulo=subtitulo, tabela=tabela)


def _bloco_vies_indisponivel(subtitulo):
    titulo = "Tipos de discriminação, riscos e grupos afetados: indisponíveis"
    textos = [
        "Estes indicadores ainda não existem: a triagem v2 não os classifica. Requerem a codificação temática (taxonomia tx1), que ainda não foi aprovada; não são zero."
    ]
    return _bloco("obs-vies-indisponivel", titulo, subtitulo=subtitulo, texto=textos)


def _bloco_tec_total(subtitulo, n, href):
    titulo = f"{bv._obras_pl(n)} com aplicações tecnológicas como ângulo predominante"
    textos = [
        "Os rótulos dizem do que a obra trata, não se a tecnologia foi implantada, se funciona nem em que estágio está. Os eixos de exploração não são uma taxonomia de tecnologias."
    ]
    link = {"href": href(), "rotulo": "Ver estas obras"}
    return _bloco("obs-tec-total", titulo, subtitulo=subtitulo, texto=textos, link=link)


def _bloco_tec_topicos(filtradas, textos_das_consultas, subtitulo):
    titulo = "Tópicos mais citados pelo modelo"
    t = AV.topicos(filtradas, textos_das_consultas)
    linhas_grafico = [
        (f"{rotulo} (termo de busca)" if termo else rotulo, n_obras)
        for rotulo, n_obras, termo in t[:15]
    ]
    grafico = bv._barras(linhas_grafico, titulo, "Tópicos mais citados pelo modelo")
    textos = [
        "Tópicos atribuídos pelo modelo, contados uma vez por obra (as fora do escopo não contam); “(termo de busca)” marca o tópico que aparece no texto de alguma consulta."
    ]
    tabela = {
        "cabecalho": ["Tópico", "Obras", "Termo de busca"],
        "linhas": [[rotulo, fmt.numero(n_obras), "sim" if termo else "não"] for rotulo, n_obras, termo in t],
    }
    return _bloco("obs-tec-topicos", titulo, grafico=grafico, subtitulo=subtitulo, texto=textos, tabela=tabela)


def _bloco_tec_indisponivel(subtitulo):
    titulo = "Método, artefato, finalidade e contexto de uso: indisponíveis"
    textos = [
        "Estes indicadores ainda não existem: a triagem v2 não os classifica. Requerem a codificação temática (taxonomia tx1), prevista para a Fase 2; não são zero."
    ]
    return _bloco("obs-tec-indisponivel", titulo, subtitulo=subtitulo, texto=textos)


def blocos(perspectiva, filtradas, ambiguas, filtros, nomes, recortes_vies, eixos, textos_das_consultas, universo, href):
    """Devolve a lista de blocos para a perspectiva informada."""
    n = len(filtradas)
    subtitulo = f"por obra · universo: {bv._obras_pl(n)}, {universo.lower()}"
    if perspectiva == "integrada":
        return [
            _bloco_matriz(filtradas, nomes, recortes_vies, subtitulo, n, href),
            _bloco_combinacoes("obs-combinacoes", filtradas, nomes, subtitulo, n, href),
            _bloco_identidade(filtradas, ambiguas, subtitulo, href),
        ]
    if perspectiva == "vies":
        return [
            _bloco_vies_total(subtitulo, n, href),
            _bloco_eixos("obs-vies-eixos", filtradas, eixos, subtitulo, href),
            _bloco_grupos(filtradas, subtitulo),
            _bloco_origem("obs-vies-origem", filtradas, nomes, subtitulo, href),
            _bloco_vies_indisponivel(subtitulo),
        ]
    if perspectiva == "tecnologias":
        return [
            _bloco_tec_total(subtitulo, n, href),
            _bloco_eixos("obs-tec-eixos", filtradas, eixos, subtitulo, href),
            _bloco_origem("obs-tec-origem", filtradas, nomes, subtitulo, href),
            _bloco_tec_topicos(filtradas, textos_das_consultas, subtitulo),
            _bloco_tec_indisponivel(subtitulo),
        ]
    return []
