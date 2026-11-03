"""Fluxo PRISMA para o banco de busca de viés algorítmico."""
from dominio import analises_vies as AV
from painel import formatacao as fmt
from painel import rotulos
from painel import visao_geral_vies

NOTA_TRIAGEM = (
    "Só os artigos do Google Scholar seguem para a triagem humana. "
    "As referências da web recebem só a triagem de escopo do modelo "
    "e não passam por triagem humana no procedimento atualmente documentado."
)
ORIGEM_PRISMA = "origem: v_prisma"
ORIGEM_MODELO = "origem: v_prisma · triagem de escopo do modelo, só com confiança alta; decisão humana sempre vence"
ORIGEM_WEB = "origem: chamadas da busca na web"
ORIGEM_DUAS = "origem: referências da web e artigos do Scholar"
ORIGEM_REF_WEB = "origem: referências da web, as mesmas da Visão Geral"
LIMITES = "junção automática, não conferida por pessoas; os limites estão na Metodologia (Deduplicação e limites)"

TITULOS_FASES = {
    "identificacao": "Identificação: Google Scholar",
    "web": "Identificação e organização: busca na web e obras",
    "triagem": "Triagem (título e resumo)",
    "elegibilidade": "Elegibilidade (texto completo)",
    "inclusao": "Inclusão",
}


def dados_vies(leitura, contexto) -> dict:
    """Coleta e estrutura os dados brutos para o fluxo PRISMA do banco de viés."""
    prisma_dados = leitura.prisma()
    lit_dados = leitura.literatura()
    af_dados = leitura.analise_ferramentas()
    params = leitura.parametros_buscas_vies()
    ocorr_sch = leitura.ocorrencias_scholar_por_chamada()
    itens_lista = visao_geral_vies.itens(leitura, contexto)

    por_termo = lit_dados.get("por_termo") or []
    pares = sum(l.get("n_artigos", 0) for l in por_termo)

    chamadas_lista = af_dados.get("chamadas") or []
    c = sum(r.get("chamadas", 0) for r in chamadas_lista if r.get("etapa") == "busca_literatura")
    res_dict = af_dados.get("resultados") or {}
    o = res_dict.get("busca_literatura", 0)

    web_params = params.get("web") or []
    sch_params = params.get("scholar") or []
    exec_web = len({r.get("run_id") for r in web_params if r.get("run_id")})

    repeticoes = AV.repeticoes_na_mesma_consulta(ocorr_sch)

    corpus = AV.resumo(itens_lista)

    return {
        "prisma": prisma_dados,
        "pares_artigo_consulta": pares,
        "web": {"chamadas": c, "ocorrencias": o, "execucoes": exec_web},
        "scholar_chamadas": len(sch_params),
        "repeticoes": repeticoes,
        "corpus": corpus,
    }


def montar_prisma_vies(dados: dict, ocultos=frozenset()) -> dict:
    """Monta a estrutura de fases e caixas do PRISMA adaptado para o viés algorítmico."""
    prisma = dados.get("prisma") or {}
    caixas_raw = prisma.get("caixas") or []
    n_buscas_scholar = prisma.get("n_buscas_scholar", 0)
    pares = dados.get("pares_artigo_consulta")
    scholar_chamadas = dados.get("scholar_chamadas")
    repeticoes = dados.get("repeticoes")

    valores_metricas = {c.get("metrica"): c.get("valor") for c in caixas_raw if "metrica" in c}
    val_unicos = valores_metricas.get("Google Scholar: artigos unicos") or 0
    val_duplicatas = valores_metricas.get("Google Scholar: duplicatas entre termos removidas") or 0

    if pares is not None:
        entre = pares - val_unicos
        mesmo = val_duplicatas - entre
    else:
        entre = None
        mesmo = None

    scholar_executado = (isinstance(n_buscas_scholar, int) and n_buscas_scholar > 0)

    divisao_mostrada = (
        scholar_executado
        and pares is not None
        and entre is not None
        and mesmo is not None
        and entre >= 0
        and mesmo >= 0
    )

    if divisao_mostrada and repeticoes is not None and repeticoes.get("total") == mesmo and mesmo > 0:
        repetidos_por_causa = [
            f"na mesma consulta com a outra configuração de idioma (com e sem o parâmetro de idioma português): {fmt.numero(repeticoes['outro_idioma'])};",
            f"em outra página de resultados da mesma consulta, com a mesma configuração: {fmt.numero(repeticoes['outra_pagina'])};",
            f"na mesma chamada (dois resultados com o mesmo título normalizado): {fmt.numero(repeticoes['mesma_chamada'])};",
            f"total: {fmt.numero(repeticoes['total'])}.",
        ]
    else:
        repetidos_por_causa = None

    fases_dict = {}
    for c in caixas_raw:
        fase_id = c.get("fase", "")
        metrica = c.get("metrica", "")
        c_valor = c.get("valor")

        if metrica == "Google Scholar: duplicatas entre termos removidas":
            rotulo = "Google Scholar: registros repetidos removidos"
        elif metrica == "Google Scholar: registros retornados":
            rotulo = "Google Scholar: ocorrências devolvidas"
        elif metrica == "duplicatas entre fontes removidas":
            rotulo = "duplicatas entre o Google Scholar e as bases manuais removidas"
        elif metrica == "registros (artigo x fonte) apos remover duplicatas entre termos":
            rotulo = "Google Scholar: artigos após remover todos os registros repetidos (a mesma contagem dos artigos únicos)"
        else:
            rotulo = rotulos.rotulo(rotulos.PRISMA, metrica)

        if metrica in ocultos:
            valor = "não divulgado"
            especial = True
        elif "buscas manuais" in metrica or metrica == "duplicatas entre fontes removidas":
            valor = "não se aplica"
            especial = True
        elif ("Google Scholar" in metrica or "execucoes de busca" in metrica) and not scholar_executado:
            valor = "não executado"
            especial = True
        else:
            valor = fmt.numero(c_valor if c_valor is not None else 0)
            especial = False

        nota = ORIGEM_PRISMA
        link_triagem = False

        if metrica == "execucoes de busca academica":
            if not especial and isinstance(scholar_chamadas, int) and scholar_chamadas > 0:
                pl = "chamada" if scholar_chamadas == 1 else "chamadas"
                nota = f"origem: v_prisma · em {fmt.numero(scholar_chamadas)} {pl}"
            else:
                nota = ORIGEM_PRISMA
        elif metrica == "Google Scholar: duplicatas entre termos removidas":
            if not especial and divisao_mostrada and entre is not None and mesmo is not None:
                veja = " (veja abaixo do fluxo)" if repetidos_por_causa is not None else ""
                nota = (
                    f"origem: v_prisma · registros de um artigo já devolvido por outra consulta: {fmt.numero(entre)} · "
                    f"registros devolvidos de novo pela mesma consulta: {fmt.numero(mesmo)}{veja}"
                )
            else:
                nota = ORIGEM_PRISMA
        elif "ferramenta automatica" in metrica:
            nota = ORIGEM_MODELO
            link_triagem = True

        caixa = {
            "rotulo": rotulo,
            "valor": valor,
            "especial": especial,
            "nota": nota,
            "link_triagem": link_triagem,
        }
        fases_dict.setdefault(fase_id, []).append(caixa)

    fases_list = []
    for fid, cxs in fases_dict.items():
        titulo = TITULOS_FASES.get(fid, fid)
        nota_fase = NOTA_TRIAGEM if fid == "triagem" else None
        fases_list.append({
            "id": fid,
            "titulo": titulo,
            "nota": nota_fase,
            "caixas": cxs,
        })

    w = dados.get("web") or {}
    r = dados.get("corpus") or {}

    chamadas = w.get("chamadas")
    ocorrencias_raw = w.get("ocorrencias")
    execucoes = w.get("execucoes")

    web_executada = (isinstance(chamadas, int) and not isinstance(chamadas, bool) and chamadas > 0)
    chamadas_efetivas = chamadas if (isinstance(chamadas, int) and not isinstance(chamadas, bool)) else 0

    n_web = r.get("n_web") if (isinstance(r.get("n_web"), int) and not isinstance(r.get("n_web"), bool)) else 0
    n_em_ambas_fontes = r.get("n_em_ambas_fontes") if (isinstance(r.get("n_em_ambas_fontes"), int) and not isinstance(r.get("n_em_ambas_fontes"), bool)) else 0
    n_ambas_por_url = r.get("n_ambas_por_url") if (isinstance(r.get("n_ambas_por_url"), int) and not isinstance(r.get("n_ambas_por_url"), bool)) else 0
    n_ambas_so_por_titulo = r.get("n_ambas_so_por_titulo") if (isinstance(r.get("n_ambas_so_por_titulo"), int) and not isinstance(r.get("n_ambas_so_por_titulo"), bool)) else 0
    n_obras_em_ambas = r.get("n_obras_em_ambas") if (isinstance(r.get("n_obras_em_ambas"), int) and not isinstance(r.get("n_obras_em_ambas"), bool)) else 0
    n_obras = r.get("n_obras") if (isinstance(r.get("n_obras"), int) and not isinstance(r.get("n_obras"), bool)) else 0
    n_itens = r.get("n_itens") if (isinstance(r.get("n_itens"), int) and not isinstance(r.get("n_itens"), bool)) else 0

    if not web_executada:
        caixas_web = [
            {
                "rotulo": "busca na web: chamadas",
                "valor": "não executado",
                "especial": True,
                "nota": ORIGEM_WEB,
                "link_triagem": False,
            },
            {
                "rotulo": "busca na web: ocorrências devolvidas",
                "valor": "não executado",
                "especial": True,
                "nota": ORIGEM_WEB,
                "link_triagem": False,
            },
            {
                "rotulo": "busca na web: ocorrências repetidas juntadas",
                "valor": "não executado",
                "especial": True,
                "nota": "origem: chamadas da busca na web e referências da web",
                "link_triagem": False,
            },
            {
                "rotulo": "busca na web: referências únicas (por endereço normalizado)",
                "valor": "não executado",
                "especial": True,
                "nota": ORIGEM_REF_WEB,
                "link_triagem": False,
            },
            {
                "rotulo": "referências da web que repetem um artigo do Scholar",
                "valor": "não executado",
                "especial": True,
                "nota": (
                    f"{ORIGEM_DUAS} · pelo endereço: {fmt.numero(n_ambas_por_url)} · "
                    f"só pelo título: {fmt.numero(n_ambas_so_por_titulo)} · "
                    f"obras correspondentes: {fmt.numero(n_obras_em_ambas)}"
                ),
                "link_triagem": False,
            },
            {
                "rotulo": "obras distintas (artigos do Scholar e referências da web)",
                "valor": fmt.numero(n_obras),
                "especial": False,
                "nota": (
                    f"{ORIGEM_DUAS} · itens das duas fontes: {fmt.numero(n_itens)} · "
                    f"referências da web juntadas a um artigo do Scholar: {fmt.numero(n_em_ambas_fontes)} · {LIMITES}"
                ),
                "link_triagem": False,
            },
        ]
    else:
        if isinstance(execucoes, int) and not isinstance(execucoes, bool) and execucoes > 0:
            pl_exec = "execução" if execucoes == 1 else "execuções"
            nota_chamadas = f"{ORIGEM_WEB} · em {fmt.numero(execucoes)} {pl_exec}"
        else:
            nota_chamadas = ORIGEM_WEB

        val_ocorr = ocorrencias_raw if (isinstance(ocorrencias_raw, int) and not isinstance(ocorrencias_raw, bool)) else 0

        if (
            ocorrencias_raw is not None
            and isinstance(ocorrencias_raw, int)
            and not isinstance(ocorrencias_raw, bool)
            and ocorrencias_raw >= n_web
        ):
            val_juntadas = fmt.numero(ocorrencias_raw - n_web)
            esp_juntadas = False
        else:
            val_juntadas = "não calculado"
            esp_juntadas = True

        caixas_web = [
            {
                "rotulo": "busca na web: chamadas",
                "valor": fmt.numero(chamadas_efetivas),
                "especial": False,
                "nota": nota_chamadas,
                "link_triagem": False,
            },
            {
                "rotulo": "busca na web: ocorrências devolvidas",
                "valor": fmt.numero(val_ocorr),
                "especial": False,
                "nota": ORIGEM_WEB,
                "link_triagem": False,
            },
            {
                "rotulo": "busca na web: ocorrências repetidas juntadas",
                "valor": val_juntadas,
                "especial": esp_juntadas,
                "nota": "origem: chamadas da busca na web e referências da web",
                "link_triagem": False,
            },
            {
                "rotulo": "busca na web: referências únicas (por endereço normalizado)",
                "valor": fmt.numero(n_web),
                "especial": False,
                "nota": ORIGEM_REF_WEB,
                "link_triagem": False,
            },
            {
                "rotulo": "referências da web que repetem um artigo do Scholar",
                "valor": fmt.numero(n_em_ambas_fontes),
                "especial": False,
                "nota": (
                    f"{ORIGEM_DUAS} · pelo endereço: {fmt.numero(n_ambas_por_url)} · "
                    f"só pelo título: {fmt.numero(n_ambas_so_por_titulo)} · "
                    f"obras correspondentes: {fmt.numero(n_obras_em_ambas)}"
                ),
                "link_triagem": False,
            },
            {
                "rotulo": "obras distintas (artigos do Scholar e referências da web)",
                "valor": fmt.numero(n_obras),
                "especial": False,
                "nota": (
                    f"{ORIGEM_DUAS} · itens das duas fontes: {fmt.numero(n_itens)} · "
                    f"referências da web juntadas a um artigo do Scholar: {fmt.numero(n_em_ambas_fontes)} · {LIMITES}"
                ),
                "link_triagem": False,
            },
        ]

    fase_web = {
        "id": "web",
        "titulo": TITULOS_FASES["web"],
        "nota": None,
        "caixas": caixas_web,
    }

    idx_identificacao = next((i for i, f in enumerate(fases_list) if f["id"] == "identificacao"), None)
    if idx_identificacao is not None:
        fases_list.insert(idx_identificacao + 1, fase_web)
    else:
        fases_list.insert(0, fase_web)

    return {
        "fases": fases_list,
        "motivos": prisma.get("motivos", []),
        "repetidos_por_causa": repetidos_por_causa,
    }
