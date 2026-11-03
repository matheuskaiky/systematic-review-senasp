"""Metodologia do banco `vies` em nove seções, gerada dos dados a cada carga."""
from dominio import analises_vies as AV, validacao_vies as VV
from painel import formatacao as fmt, glossario, metodologia_texto as MT, visao_geral_vies

OBJETO = (
    "Levantamento da literatura científica e cinzenta sobre inteligência artificial na segurança pública, com dois ângulos: "
    "o viés algorítmico (discriminação, ética, direitos e governança) e as aplicações tecnológicas. A página descreve o que as "
    "buscas recuperaram e como os itens foram organizados e classificados. Não é uma revisão sistemática concluída."
)

FONTES_INTRO = "Duas fontes, contadas separadamente:"
FONTES_ITENS = [
    "o Google Scholar, consultado por meio do serviço SerpApi;",
    "a busca na web, feita pelo serviço Perplexity.",
]
CADA_EXECUCAO = " Cada execução aparece com o seu identificador, o comando, a situação, o hash da configuração e o commit do código."

ESTRATEGIA_INTRO_P1 = "Foram usadas quinze consultas, escritas em português, em três conjuntos de cinco:"
ESTRATEGIA_ITENS = [
    "o conjunto A combina termos de inteligência artificial, segurança pública, viés algorítmico e investigação criminal;",
    "o B, de inteligência artificial, segurança pública, viés algorítmico, discriminação e ética;",
    "o C trata das aplicações da inteligência artificial na segurança pública.",
]
ESTRATEGIA_INTRO_P2 = "As mesmas consultas foram usadas nas duas fontes."

DEDUP_1 = (
    "Dentro de cada fonte, as ocorrências repetidas foram juntadas automaticamente: na web, pelo endereço normalizado; no "
    "Scholar, pelo título normalizado."
)
DEDUP_ENTRE = (
    "Entre as fontes, uma referência da web e um artigo do Scholar contam como a mesma obra quando têm o mesmo endereço "
    "normalizado ou o mesmo título normalizado. "
)
DEDUP_FIM_INTRO = "A junção é um procedimento operacional automático, não uma identificação bibliográfica conferida por pessoas:"
DEDUP_FIM_ITENS = [
    "títulos escritos de forma diferente não são reconhecidos como a mesma obra;",
    "artigos do Scholar diferentes com o mesmo endereço continuam separados;",
    "possíveis duplicatas que restam ainda não foram examinadas.",
]

CLASSIFICA_MEIO_UL = [
    "relevância (alta, média, baixa ou fora do escopo), com uma confiança (alta, média ou baixa) e uma justificativa;",
    "ângulo, tipo de fonte, país ou escopo, tópicos e eixo.",
]
CLASSIFICA_MEIO_P2 = "Ele é instruído a julgar só pelo que o item mostra."
CLASSIFICA_MEIO_P3 = "Resultado da triagem:"
NAO_DECISAO = "São classificações automatizadas, não decisões de pesquisadores."

VAZIO = "Nada foi coletado ainda: não há execuções nem itens da busca no banco, então não há método a descrever."
SUBTITULO = (
    "Esta página descreve os procedimentos de busca, organização e classificação registrados na pesquisa, com suas "
    "fontes e limitações. Informações não disponíveis são identificadas ao longo do texto."
)


def _juntar_e(itens):
    """Junta itens com vírgulas e 'e': ['a'] -> 'a', ['a', 'b'] -> 'a e b', ['a', 'b', 'c'] -> 'a, b e c'."""
    if not itens:
        return ""
    if len(itens) == 1:
        return str(itens[0])
    if len(itens) == 2:
        return f"{itens[0]} e {itens[1]}"
    return f"{', '.join(str(x) for x in itens[:-1])} e {itens[-1]}"


def fatos_vies(leitura, contexto):
    """Lê os fatos do banco vies para a geração da página de metodologia."""
    fatos_meta = leitura.fatos_metodologia()
    ferramentas = leitura.analise_ferramentas()
    parametros = leitura.parametros_buscas_vies()
    linhas_val = leitura.linhas_validacao_vies()
    triagem_exec = leitura.triagem_vies_por_execucao()
    lista_itens = visao_geral_vies.itens(leitura, contexto)

    execucoes = fatos_meta.get("execucoes") or []
    retomadas = fatos_meta.get("retomadas") or []
    lit = fatos_meta.get("literatura") or {}
    triagem_h = lit.get("triagem") or {}

    resultados = ferramentas.get("resultados") or {}
    ocorrencias = {
        "web": resultados.get("busca_literatura", 0) or 0,
        "scholar": resultados.get("busca_academica", 0) or 0,
    }

    consultas_lit = getattr(contexto, "consultas_literatura", None) or {}
    conjunto_map = getattr(contexto, "conjunto_da_consulta", None) or {}
    consultas = [
        {"id": c, "conjunto": n, "texto": consultas_lit.get(c)}
        for c, n in conjunto_map.items()
    ]

    corpus = AV.resumo(lista_itens)
    relevancia = AV.relevancia_por_fonte(lista_itens)

    validacao = {
        "itens": len(linhas_val),
        "respondidos": VV.respondidas(linhas_val),
    }

    return {
        "banco": contexto.banco,
        "execucoes": execucoes,
        "retomadas": retomadas,
        "triagem_humana": triagem_h,
        "consultas": consultas,
        "chamadas": parametros,
        "ocorrencias": ocorrencias,
        "corpus": corpus,
        "relevancia": relevancia,
        "versao_triagem": getattr(contexto, "versao_triagem_vies", None),
        "validacao": validacao,
        "triagem_por_execucao": triagem_exec,
    }


def _eh_padrao_web(chamadas_web):
    """Regra W estrita: retorna (padrao, N)."""
    if not chamadas_web:
        return False, None
    primeiro_max = chamadas_web[0].get("max_resultados")
    if not isinstance(primeiro_max, int) or isinstance(primeiro_max, bool) or primeiro_max <= 0:
        return False, None
    for r in chamadas_web:
        m = r.get("max_resultados")
        if not isinstance(m, int) or isinstance(m, bool) or m != primeiro_max:
            return False, None
        if r.get("idiomas") != ["pt"]:
            return False, None
        if r.get("pais") != "BR":
            return False, None
    return True, primeiro_max


def _eh_padrao_scholar(chamadas_sch):
    """Regra S estrita: retorna (padrao, P, M)."""
    if not chamadas_sch:
        return False, None, None
    primeiro_por_pagina = chamadas_sch[0].get("por_pagina")
    if not isinstance(primeiro_por_pagina, int) or isinstance(primeiro_por_pagina, bool) or primeiro_por_pagina <= 0:
        return False, None, None
    filtros_por_consulta = {}
    tuplas_vistas = set()
    maior_pag = 0
    for r in chamadas_sch:
        if r.get("interface") != "pt":
            return False, None, None
        p = r.get("por_pagina")
        if not isinstance(p, int) or isinstance(p, bool) or p != primeiro_por_pagina:
            return False, None, None
        f = r.get("filtro_idioma")
        if f not in ("so_portugues", "sem_filtro"):
            return False, None, None
        pag = r.get("pagina")
        if not isinstance(pag, int) or isinstance(pag, bool) or pag < 1:
            return False, None, None
        if pag > maior_pag:
            maior_pag = pag
        cid = r.get("consulta_id")
        filtros_por_consulta.setdefault(cid, set()).add(f)
        tup = (cid, f, pag)
        if tup in tuplas_vistas:
            return False, None, None
        tuplas_vistas.add(tup)
    for cid, filtros in filtros_por_consulta.items():
        if filtros != {"so_portugues", "sem_filtro"}:
            return False, None, None
    return True, primeiro_por_pagina, maior_pag


def _frase_conjuntos_web(consultas, chamadas_web):
    if not consultas or not chamadas_web:
        return ""
    conjuntos_ordem = []
    queries_por_conjunto = {}
    for c in consultas:
        conj = c.get("conjunto")
        if conj not in queries_por_conjunto:
            conjuntos_ordem.append(conj)
            queries_por_conjunto[conj] = set()
        queries_por_conjunto[conj].add(c.get("id"))

    runs_por_conjunto = {}
    for conj in conjuntos_ordem:
        q_ids = queries_por_conjunto[conj]
        runs = {r.get("run_id") for r in chamadas_web if r.get("consulta_id") in q_ids and r.get("run_id")}
        runs_por_conjunto[conj] = len(runs)

    if len(conjuntos_ordem) == 1:
        c1 = conjuntos_ordem[0]
        k1 = runs_por_conjunto[c1]
        return f" O conjunto {c1} foi consultado em {k1} {MT._pl(k1, 'execução', 'execuções')}."

    partes = []
    c1 = conjuntos_ordem[0]
    k1 = runs_por_conjunto[c1]
    partes.append(f"O conjunto {c1} foi consultado em {k1} {MT._pl(k1, 'execução', 'execuções')}")
    for ci in conjuntos_ordem[1:]:
        ki = runs_por_conjunto[ci]
        partes.append(f"o {ci}, em {ki}")
    return " " + "; ".join(partes) + "."


def _secao_objeto():
    return MT._secao("objeto", "Objeto e finalidade", [MT._p((OBJETO, None))])


def _secao_fontes(fatos, modelo=True):
    b0 = MT._p((FONTES_INTRO, None))
    b1 = MT._ul([[(it, None)] for it in FONTES_ITENS])

    execucoes = fatos.get("execucoes") or []
    ex = [e for e in execucoes if e.get("no_relatorio")]
    if not ex:
        b2 = MT._p(("Nenhuma execução está incluída no relatório.", None))
        return MT._secao("fontes", "Fontes", [b0, b1, b2])

    n = len(ex)
    periodo = MT._periodo(ex[0].get("iniciado_em"), ex[-1].get("iniciado_em"))
    clausula_periodo = f", {periodo}" if periodo else ""

    w = sum(1 for e in ex if e.get("comando") == "buscar-literatura")
    s = sum(1 for e in ex if e.get("comando") == "academico")
    t = sum(1 for e in ex if e.get("comando") == "triar-escopo")
    o = sum(1 for e in ex if e.get("comando") not in ("buscar-literatura", "academico", "triar-escopo"))

    partes = []
    if w > 0 and s > 0:
        partes.append(f"{fmt.numero(w + s)} de busca ({fmt.numero(w)} na web e {fmt.numero(s)} no Google Scholar)")
    elif w > 0:
        partes.append(f"{fmt.numero(w)} de busca na web")
    elif s > 0:
        partes.append(f"{fmt.numero(s)} de busca no Google Scholar")

    if t > 0:
        partes.append(f"{fmt.numero(t)} de triagem pelo modelo")

    if o > 0:
        partes.append(f"{fmt.numero(o)} {MT._pl(o, 'de outro comando', 'de outros comandos')}")

    partes_str = _juntar_e(partes)

    frase_triagem = ""
    versao_vigente = fatos.get("versao_triagem")
    if versao_vigente:
        triagem_runs = {e.get("run_id") for e in ex if e.get("comando") == "triar-escopo"}
        triagens_fatos = fatos.get("triagem_por_execucao") or []
        runs_com_diferenca = set()
        versoes_diferentes = set()
        for tr in triagens_fatos:
            rid = tr.get("run_id")
            if rid in triagem_runs:
                v = tr.get("versao")
                if v != versao_vigente:
                    runs_com_diferenca.add(rid)
                    if v is not None:
                        versoes_diferentes.add(str(v))

        k = len(runs_com_diferenca)
        if k > 0:
            verbo_triagens = MT._pl(k, "das triagens usou", "das triagens usaram")
            if versoes_diferentes:
                v_ord = sorted(versoes_diferentes)
                if len(v_ord) == 1:
                    detalhe_v = f"a versão {v_ord[0]} das instruções, substituída pela {versao_vigente}"
                else:
                    detalhe_v = f"as versões {_juntar_e(v_ord)} das instruções, substituídas pela {versao_vigente}"
            else:
                detalhe_v = "instruções sem versão registrada"
            if modelo:
                frase_triagem = f" {fmt.numero(k)} {verbo_triagens} {detalhe_v}; a contagem por relevância da seção Classificação automatizada usa só a {versao_vigente}."
            else:
                frase_triagem = f" {fmt.numero(k)} {verbo_triagens} {detalhe_v}."

    texto_exec = (
        f"O levantamento usou {fmt.numero(n)} {MT._pl(n, 'execução', 'execuções')}{clausula_periodo}: {partes_str}.{frase_triagem}"
        f"{CADA_EXECUCAO}"
    )
    b2 = MT._p((texto_exec, None))
    b3 = MT._ul(MT._itens_execucoes(ex))
    return MT._secao("fontes", "Fontes", [b0, b1, b2, b3])


def _secao_estrategia(fatos):
    b0 = MT._p((ESTRATEGIA_INTRO_P1, None))
    b1 = MT._ul([[(it, None)] for it in ESTRATEGIA_ITENS])
    blocos = [b0, b1]

    chamadas = fatos.get("chamadas") or {}
    chamadas_web = chamadas.get("web") or []
    chamadas_sch = chamadas.get("scholar") or []

    if chamadas_web and chamadas_sch:
        set_w = {r.get("consulta_id") for r in chamadas_web}
        set_s = {r.get("consulta_id") for r in chamadas_sch}
        if set_w == set_s:
            b_mesmas = MT._p(("As mesmas consultas foram usadas nas duas fontes.", None))
        else:
            b_mesmas = MT._p(("As consultas usadas não foram as mesmas nas duas fontes; cada chamada registra a sua.", None))
        blocos.append(b_mesmas)

    consultas = fatos.get("consultas") or []
    if consultas:
        itens_consultas = []
        for c in consultas:
            cid = c.get("id")
            conj = c.get("conjunto")
            txt = c.get("texto")
            if not txt:
                desc = f"{cid} (conjunto {conj}): texto da consulta não encontrado na configuração"
            else:
                desc = f"{cid} (conjunto {conj}): {txt}"
            itens_consultas.append([(desc, None)])
        blocos.append(MT._ul(itens_consultas))

    if not chamadas_web:
        web_item_texto = "Busca na web: nenhuma chamada consta nas execuções do relatório."
    else:
        padrao_w, n_w = _eh_padrao_web(chamadas_web)
        if padrao_w:
            web_item_texto = (
                f"Busca na web: cada consulta foi enviada numa chamada própria, pedindo até {fmt.numero(n_w)} "
                f"resultados, com os parâmetros de idioma português e de país Brasil."
            )
        else:
            web_item_texto = (
                "Busca na web: cada consulta foi enviada numa chamada própria; os parâmetros não foram os mesmos em todas as "
                "chamadas e estão registrados em cada uma."
            )
        web_item_texto += _frase_conjuntos_web(consultas, chamadas_web)

    if not chamadas_sch:
        sch_item_texto = "Google Scholar: nenhuma chamada consta nas execuções do relatório."
    else:
        padrao_s, p_s, m_s = _eh_padrao_scholar(chamadas_sch)
        if padrao_s:
            sch_item_texto = (
                f"Google Scholar: cada consulta foi feita duas vezes, com a interface em português: uma vez com o parâmetro de "
                f"idioma português e outra sem parâmetro de idioma. Cada vez pediu {fmt.numero(p_s)} resultados por página, em até "
                f"{m_s} {MT._pl(m_s, 'página', 'páginas')}; a paginação parava na primeira página com menos de {fmt.numero(p_s)} "
                f"resultados ou com falha na chamada."
            )
        else:
            sch_item_texto = (
                "Google Scholar: as chamadas não usaram os mesmos parâmetros em todas as consultas; eles estão registrados em "
                "cada chamada."
            )

    blocos.append(MT._ul([[(web_item_texto, None)], [(sch_item_texto, None)]]))
    return MT._secao("estrategia", "Estratégia de busca", blocos)


def _secao_unidades():
    secao_u = next((s for s in glossario.SECOES_VIES if s.get("id") == "unidades"), {})
    intro = secao_u.get("intro") or ""
    entradas = secao_u.get("entradas") or []
    b0 = MT._p((intro, None))
    b1 = MT._ul([[(f"{e['termo']}: {e['texto']}", None)] for e in entradas])
    return MT._secao("unidades", "Unidades de análise", [b0, b1])


def _secao_recuperacao(fatos):
    chamadas = fatos.get("chamadas") or {}
    web_rows = chamadas.get("web") or []
    sch_rows = chamadas.get("scholar") or []
    c_web = len(web_rows)
    c_sch = len(sch_rows)

    oco = fatos.get("ocorrencias") or {}
    o_web = oco.get("web", 0) or 0
    o_sch = oco.get("scholar", 0) or 0

    corpus = fatos.get("corpus") or {}
    r = corpus.get("n_web", 0) or 0
    a = corpus.get("n_scholar", 0) or 0
    i = corpus.get("n_itens", 0) or 0

    consultas = fatos.get("consultas") or []

    if not web_rows:
        web_part = "Na busca na web, nenhuma chamada consta nas execuções do relatório."
    else:
        verb_web = MT._pl(o_web, "resultou", "resultaram")
        web_part = (
            f"Na busca na web, {fmt.numero(o_web)} {MT._pl(o_web, 'ocorrência devolvida', 'ocorrências devolvidas')} em "
            f"{fmt.numero(c_web)} {MT._pl(c_web, 'chamada', 'chamadas')} {verb_web} em "
            f"{fmt.numero(r)} {MT._pl(r, 'referência única', 'referências únicas')} (por endereço normalizado)."
        )

        conjuntos_ordem = []
        queries_por_conjunto = {}
        for c in consultas:
            conj = c.get("conjunto")
            if conj not in queries_por_conjunto:
                conjuntos_ordem.append(conj)
                queries_por_conjunto[conj] = set()
            queries_por_conjunto[conj].add(c.get("id"))

        frases_rep = []
        for conj in conjuntos_ordem:
            q_ids = queries_por_conjunto[conj]
            rows_set = [row for row in web_rows if row.get("consulta_id") in q_ids and bool(row.get("run_id"))]
            distinct_runs = sorted({row["run_id"] for row in rows_set})
            k = len(distinct_runs)
            if k >= 2:
                min_run = distinct_runs[0]
                x = sum(
                    row.get("n_retornados")
                    for row in rows_set
                    if row.get("run_id") != min_run
                    and type(row.get("n_retornados")) is int
                    and not isinstance(row.get("n_retornados"), bool)
                    and row.get("n_retornados") >= 0
                )
                verbo_vem = "vem" if x == 1 else "vêm"
                if k == 2:
                    frases_rep.append(
                        f" O conjunto {conj} foi consultado em 2 execuções na web; {fmt.numero(x)} dessas ocorrências {verbo_vem} da segunda execução."
                    )
                else:
                    frases_rep.append(
                        f" O conjunto {conj} foi consultado em {fmt.numero(k)} execuções na web; {fmt.numero(x)} dessas ocorrências {verbo_vem} das execuções depois da primeira."
                    )

        if frases_rep:
            web_part += "".join(frases_rep)

    if not sch_rows:
        sch_part = "No Google Scholar, nenhuma chamada consta nas execuções do relatório."
    else:
        verb_sch = MT._pl(o_sch, "resultou", "resultaram")
        sch_part = (
            f"No Google Scholar, {fmt.numero(o_sch)} {MT._pl(o_sch, 'ocorrência devolvida', 'ocorrências devolvidas')} em "
            f"{fmt.numero(c_sch)} {MT._pl(c_sch, 'chamada', 'chamadas')} {verb_sch} em "
            f"{fmt.numero(a)} {MT._pl(a, 'artigo único', 'artigos únicos')} (por título normalizado)."
        )

    verbo_total = MT._pl(i, "é", "são")
    total_part = (
        f"Ao todo, {verbo_total} {fmt.numero(i)} {MT._pl(i, 'item', 'itens')}, porque cada artigo e cada referência conta como um item: "
        f"{fmt.numero(a)} {MT._pl(a, 'artigo', 'artigos')} e {fmt.numero(r)} {MT._pl(r, 'referência', 'referências')}."
    )

    texto = f"{web_part} {sch_part} {total_part}"
    return MT._secao("recuperacao", "Recuperação e organização", [MT._p((texto, None))])


def _secao_deduplicacao(fatos):
    b0 = MT._p((DEDUP_1, None))

    corpus = fatos.get("corpus") or {}
    n_em_ambas = corpus.get("n_em_ambas_fontes", 0) or 0
    o = corpus.get("n_obras", 0) or 0
    if n_em_ambas == 0:
        fim_entre = (
            f"Assim, nenhuma referência da web repete um artigo do Scholar, e o total é de "
            f"{fmt.numero(o)} {MT._pl(o, 'obra distinta', 'obras distintas')}."
        )
    else:
        u = corpus.get("n_ambas_por_url", 0) or 0
        t = corpus.get("n_ambas_so_por_titulo", 0) or 0
        fim_entre = (
            f"Assim, {fmt.numero(n_em_ambas)} {MT._pl(n_em_ambas, 'referência da web repete', 'referências da web repetem')} "
            f"um artigo do Scholar ({fmt.numero(u)} pelo endereço e {fmt.numero(t)} só pelo título), e o total é de "
            f"{fmt.numero(o)} {MT._pl(o, 'obra distinta', 'obras distintas')}."
        )
    b1 = MT._p((DEDUP_ENTRE + fim_entre, None))
    b2 = MT._p((DEDUP_FIM_INTRO, None))
    b3 = MT._ul([[(it, None)] for it in DEDUP_FIM_ITENS])
    return MT._secao("deduplicacao", "Deduplicação e limites", [b0, b1, b2, b3])


def _secao_classificacao(fatos, modelo):
    versao = fatos.get("versao_triagem")
    triagens_fatos = fatos.get("triagem_por_execucao") or []

    nomes = []
    if versao:
        nomes_set = set()
        for tr in triagens_fatos:
            if tr.get("versao") == versao:
                p = tr.get("provedor")
                if isinstance(p, str) and p.strip():
                    if ":" in p:
                        _, suf = p.split(":", 1)
                        nome = suf if suf else p
                    else:
                        nome = p
                    nomes_set.add(nome)
        nomes = sorted(nomes_set)

    lista = _juntar_e(nomes)
    conforme = ", conforme a execução" if len(nomes) >= 2 else ""

    if not modelo:
        if versao and nomes:
            txt = (
                f"Os itens são classificados por um modelo de linguagem, registrado nas chamadas como {lista}{conforme}, "
                f"com as instruções da versão {versao}, quanto à relevância, ao ângulo, ao tipo de fonte, "
                f"ao país ou escopo, aos tópicos e ao eixo. Os artigos que o modelo põe fora do escopo com confiança alta ficam ocultos "
                f"das listas até uma decisão humana. Os resultados automatizados ainda não são divulgados."
            )
        elif versao:
            txt = (
                f"Os itens são classificados por um modelo de linguagem (versão {versao}) quanto à relevância, ao ângulo, ao tipo de fonte, "
                f"ao país ou escopo, aos tópicos e ao eixo. Os artigos que o modelo põe fora do escopo com confiança alta ficam ocultos "
                f"das listas até uma decisão humana. Os resultados automatizados ainda não são divulgados."
            )
        else:
            txt = (
                "Os itens são classificados por um modelo de linguagem quanto à relevância, ao ângulo, ao tipo de fonte, "
                "ao país ou escopo, aos tópicos e ao eixo. Os artigos que o modelo põe fora do escopo com confiança alta ficam ocultos "
                "das listas até uma decisão humana. Os resultados automatizados ainda não são divulgados."
            )
        return MT._secao("classificacao", "Classificação automatizada", [MT._p((txt, None))])

    if versao and nomes:
        b0_txt = (
            f"Os itens são classificados por um modelo de linguagem, registrado nas chamadas como {lista}{conforme}, "
            f"com as instruções da versão {versao}. O modelo atribui:"
        )
    elif versao:
        b0_txt = f"Os itens são classificados por um modelo de linguagem, com as instruções da versão {versao}. O modelo atribui:"
    else:
        b0_txt = "Os itens são classificados por um modelo de linguagem. O modelo atribui:"

    b0 = MT._p((b0_txt, None))
    b1 = MT._ul([[(it, None)] for it in CLASSIFICA_MEIO_UL])
    b2 = MT._p((CLASSIFICA_MEIO_P2, None))
    b3 = MT._p((CLASSIFICA_MEIO_P3, None))

    rel = fatos.get("relevancia") or {}
    rel_sch = rel.get(AV.FONTE_SCHOLAR) or rel.get("Scholar") or {}
    rel_web = rel.get(AV.FONTE_WEB) or rel.get("Web") or {}
    alta_sch = rel_sch.get("alta", 0) or 0
    media_sch = rel_sch.get("media", 0) or 0
    baixa_sch = rel_sch.get("baixa", 0) or 0
    fora_sch = rel_sch.get("fora_do_escopo", 0) or 0
    alta_web = rel_web.get("alta", 0) or 0
    media_web = rel_web.get("media", 0) or 0
    baixa_web = rel_web.get("baixa", 0) or 0
    fora_web = rel_web.get("fora_do_escopo", 0) or 0
    s = (rel_sch.get(AV.SEM_TRIAGEM, 0) or 0) + (rel_web.get(AV.SEM_TRIAGEM, 0) or 0)

    it_sch = (
        f"artigos do Scholar: {fmt.numero(alta_sch)} de relevância alta, {fmt.numero(media_sch)} média, "
        f"{fmt.numero(baixa_sch)} baixa e {fmt.numero(fora_sch)} fora do escopo;"
    )
    it_web = (
        f"referências da web: {fmt.numero(alta_web)} alta, {fmt.numero(media_web)} média, "
        f"{fmt.numero(baixa_web)} baixa e {fmt.numero(fora_web)} fora do escopo;"
    )
    it_sem = f"{fmt.numero(s)} {MT._pl(s, 'item sem triagem válida', 'itens sem triagem válida')}."
    b4 = MT._ul([[(it_sch, None)], [(it_web, None)], [(it_sem, None)]])

    triagem_h = fatos.get("triagem_humana") or {}
    h = triagem_h.get("ocultos_llm") or 0
    if h == 0:
        b5_txt = f"Nenhum artigo está oculto das listas de artigos pela triagem do modelo. {NAO_DECISAO}"
    elif h == 1:
        b5_txt = (
            f"1 artigo que o modelo pôs fora do escopo com confiança alta fica oculto das listas de artigos até uma "
            f"decisão humana. Nada é apagado. {NAO_DECISAO}"
        )
    else:
        b5_txt = (
            f"Os {fmt.numero(h)} artigos que o modelo pôs fora do escopo com confiança alta ficam ocultos das listas de artigos até uma "
            f"decisão humana. Nada é apagado. {NAO_DECISAO}"
        )
    b5 = MT._p((b5_txt, None))

    return MT._secao("classificacao", "Classificação automatizada", [b0, b1, b2, b3, b4, b5])


def _secao_decisoes(fatos):
    triagem_h = fatos.get("triagem_humana") or {}
    inc = triagem_h.get("incluidos") or 0
    exc = triagem_h.get("excluidos") or 0
    d = inc + exc

    inicio = (
        f"Até a data desta página, {fmt.numero(d)} {MT._pl(d, 'artigo do Scholar tem', 'artigos do Scholar têm')} "
        f"decisão de triagem registrada por uma pessoa ({fmt.numero(inc)} {MT._pl(inc, 'incluído', 'incluídos')} e "
        f"{fmt.numero(exc)} {MT._pl(exc, 'excluído', 'excluídos')}). As referências da web não passam por triagem humana no procedimento atualmente documentado. "
    )

    val = fatos.get("validacao") or {}
    n_val = val.get("itens") or 0
    r_val = val.get("respondidos") or 0

    if n_val == 0:
        val_txt = "A amostra de validação humana da triagem ainda não foi sorteada."
    else:
        val_txt = (
            f"A amostra de validação humana da triagem foi sorteada: {fmt.numero(r_val)} de {fmt.numero(n_val)} "
            f"{MT._pl(n_val, 'item respondido', 'itens respondidos')}."
        )

    return MT._secao("decisoes", "Decisões humanas registradas", [MT._p((inicio + val_txt, None))])


def _secao_limitacoes(fatos):
    chamadas = fatos.get("chamadas") or {}
    web_rows = chamadas.get("web") or []
    sch_rows = chamadas.get("scholar") or []
    padrao_w, n_w = _eh_padrao_web(web_rows)
    padrao_s, p_s, m_s = _eh_padrao_scholar(sch_rows)

    if padrao_w and padrao_s:
        def _valido_menor(v, maximo):
            return type(v) is int and not isinstance(v, bool) and 0 <= v < maximo

        variou_web = any(_valido_menor(r.get("n_retornados"), n_w) for r in web_rows)
        variou_scholar = any(_valido_menor(r.get("n_retornados"), p_s) for r in sch_rows)

        if variou_web and variou_scholar:
            clausula_variou = " A profundidade efetiva variou entre as consultas nas duas fontes."
        elif variou_scholar:
            clausula_variou = " No Google Scholar, a profundidade efetiva variou entre as consultas."
        elif variou_web:
            clausula_variou = " Na web, a profundidade efetiva variou entre as consultas."
        else:
            clausula_variou = ""

        clausula_difere = " A profundidade pedida difere entre as fontes." if (n_w != 2 * m_s * p_s) else ""
        clausula_prof = f"{clausula_variou}{clausula_difere}"

        it1 = (
            f"Cada consulta trouxe só os primeiros resultados de cada fonte: na web, até {fmt.numero(n_w)} por chamada; no "
            f"Google Scholar, até {m_s} {MT._pl(m_s, 'página', 'páginas')} de {fmt.numero(p_s)} em cada variante de filtro, e a "
            f"paginação parava na primeira página com menos de {fmt.numero(p_s)} resultados ou com falha na chamada.{clausula_prof}"
        )
        it2 = (
            "As consultas foram escritas em português. Na web, com os parâmetros de idioma português e de país Brasil; no Scholar, com e "
            "sem o parâmetro de idioma português. Isso descreve os parâmetros enviados ao provedor, não o idioma dos itens recuperados, que não foi medido."
        )
    else:
        it1 = (
            "Cada consulta trouxe só os primeiros resultados de cada fonte; a profundidade pedida está registrada em cada chamada."
        )
        it2 = (
            "As consultas foram escritas em português. Os parâmetros de idioma e de país estão registrados em cada chamada. "
            "Isso descreve os parâmetros enviados ao provedor, não o idioma dos itens recuperados, que não foi medido."
        )

    val = fatos.get("validacao") or {}
    n_val = val.get("itens") or 0
    r_val = val.get("respondidos") or 0
    if n_val == 0 or r_val == 0:
        it3 = "A classificação do modelo ainda não foi conferida por pessoas."
    elif 0 < r_val < n_val:
        it3 = (
            f"A classificação do modelo está sendo conferida numa amostra de {fmt.numero(n_val)} itens "
            f"({fmt.numero(r_val)} {MT._pl(r_val, 'respondido', 'respondidos')})."
        )
    else:
        it3 = f"A classificação do modelo foi conferida numa amostra de {fmt.numero(n_val)} {MT._pl(n_val, 'item', 'itens')}."

    it4 = "A deduplicação é automática e pode deixar duplicatas."
    it5 = "Buscas manuais em bases bibliográficas não fazem parte deste levantamento."

    ul_blocos = MT._ul([[(it1, None)], [(it2, None)], [(it3, None)], [(it4, None)], [(it5, None)]])
    return MT._secao("limitacoes", "Limitações", [ul_blocos])


def gerar_metodologia_vies(fatos, custos=True, modelo=True):
    """Gera as nove seções da metodologia do banco vies e suas ressalvas."""
    fatos = fatos or {}
    execucoes = fatos.get("execucoes") or []
    corpus = fatos.get("corpus") or {}
    n_itens = corpus.get("n_itens") or 0

    if not execucoes and not n_itens:
        secoes = [MT._secao("situacao", "Situação dos dados", [MT._p((VAZIO, None))])]
        ressalvas = []
        return {
            "secoes": secoes,
            "ressalvas": ressalvas,
            "vazio": True,
            "texto": MT._texto_puro(secoes, ressalvas),
            "subtitulo": SUBTITULO,
        }

    x = MT._Fatos(fatos)
    ressalvas = MT._ressalvas_execucoes(x, custos=custos)

    secoes = [
        _secao_objeto(),
        _secao_fontes(fatos, modelo=modelo),
        _secao_estrategia(fatos),
        _secao_unidades(),
        _secao_recuperacao(fatos),
        _secao_deduplicacao(fatos),
        _secao_classificacao(fatos, modelo),
        _secao_decisoes(fatos),
        _secao_limitacoes(fatos),
    ]

    return {
        "secoes": secoes,
        "ressalvas": ressalvas,
        "vazio": False,
        "texto": MT._texto_puro(secoes, ressalvas),
        "subtitulo": SUBTITULO,
    }
