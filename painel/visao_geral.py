"""Montador da Visão Geral do painel.

Função pura que constrói as seções e blocos da Visão Geral para os bancos real e vies,
com metadados rigorosos por indicador, controle de visibilidade baseado nas funções do servidor
e supressão de dados preliminares automatizados (C2) e operacionais (C3) para quem não entrou.
"""
from datetime import datetime, timezone
from urllib.parse import quote

from dominio import analises_vies as AV, autenticacao
from painel import (
    analises_blocos,
    analises_blocos_vies,
    formatacao as fmt,
    graficos,
    navegacao,
    rotulos,
    visao_geral_vies,
)

PRELIMINAR = (
    "Resultado preliminar: produzido por processamento automatizado e ainda não validado por pesquisadores. "
    "Interprete como exploratório."
)
NAO_DIVULGADO = "Resultados automatizados ainda não divulgados."

ORIGENS = {
    "humana": ("Decisão humana", "Decisão registrada por uma pessoa."),
    "modelo": ("Segundo o modelo", "Saída de um modelo de linguagem; ainda não validada por pesquisadores."),
    "verificacao_automatica": ("Conferência automática", "Conferência automática sobre a saída do modelo, sem leitura humana."),
    "calculada": ("Calculado", "Calculado por regra a partir de decisões humanas."),
    "coleta": ("Coleta", "Contagem do que a busca recuperou; não envolve julgamento."),
    "operacao": ("Operação", "Registro técnico das execuções."),
    "administracao": ("Administração", "Registro do banco de contas do painel."),
}

REL = "Execuções marcadas para o relatório."
TODAS = "Todas as execuções registradas."
ITENS = "Referências da web e artigos do Google Scholar das consultas configuradas."
ART = "Artigos exibidos na triagem humana."


def _indicador(
    iid: str,
    origem: str,
    rotulo: str,
    valor,
    denominador,
    universo: str,
    definicao: str,
    classe: str,
    formato: str = "numero",
    exige: tuple[str, ...] = (),
) -> dict:
    return {
        "id": iid,
        "rotulo": rotulo,
        "valor": valor,
        "denominador": denominador,
        "formato": formato,
        "origem": origem,
        "origem_rotulo": ORIGENS[origem][0],
        "validacao": ORIGENS[origem][1],
        "universo": universo,
        "definicao": definicao,
        "classe": classe,
        "exige": tuple(exige),
    }


def _bloco_base(
    bid: str,
    titulo: str,
    classe: str,
    texto: list[str] | None = None,
    indicadores: list[dict] | None = None,
    grafico: str | None = None,
    vazio: str | None = None,
    acoes: list[dict] | None = None,
    aviso: str | None = None,
    cartoes: list[dict] | None = None,
    execucoes: list[dict] | None = None,
    mostrar_custo: bool | None = None,
    comando_inicial: str | None = None,
    ultima_coleta: str | None = None,
    origem: str | None = None,
    origem_rotulo: str | None = None,
    validacao: str | None = None,
    universo: str | None = None,
    definicao: str | None = None,
) -> dict:
    return {
        "id": bid,
        "titulo": titulo,
        "classe": classe,
        "texto": texto if texto is not None else [],
        "indicadores": indicadores if indicadores is not None else [],
        "grafico": grafico,
        "vazio": vazio,
        "acoes": acoes if acoes is not None else [],
        "aviso": aviso,
        "cartoes": cartoes,
        "execucoes": execucoes,
        "mostrar_custo": mostrar_custo,
        "comando_inicial": comando_inicial,
        "ultima_coleta": ultima_coleta,
        "origem": origem,
        "origem_rotulo": origem_rotulo,
        "validacao": validacao,
        "universo": universo,
        "definicao": definicao,
    }


def ve_fila_artigos(quem) -> bool:
    """Verifica se o usuário pode ver a fila de triagem de artigos."""
    if not isinstance(quem, dict):
        return False
    if not quem.get("logado"):
        return False
    grupo = quem.get("grupo")
    permissoes = quem.get("permissoes")
    if grupo is None or permissoes is None:
        return False
    return bool(autenticacao.pode(grupo, permissoes, "triar_artigos"))


def ve_andamento(quem) -> bool:
    """Verifica se o usuário pode ver o bloco de andamento da equipe."""
    if not isinstance(quem, dict):
        return False
    if not quem.get("logado"):
        return False
    grupo = quem.get("grupo")
    permissoes = quem.get("permissoes")
    if grupo is None or permissoes is None:
        return False
    return bool(autenticacao.pode(grupo, permissoes, "ver_estatisticas_usuarios"))


def ve_administracao(quem) -> bool:
    """Verifica se o usuário pode ver a seção de administração."""
    if not isinstance(quem, dict):
        return False
    if not quem.get("logado"):
        return False
    grupo = quem.get("grupo")
    permissoes = quem.get("permissoes")
    if grupo is None or permissoes is None:
        return False
    return bool(autenticacao.pode(grupo, permissoes, autenticacao.SO_ADMIN))


def ler_contas(contas, quem) -> dict | None:
    """Lê resumo de contas e auditoria para o administrador."""
    if not ve_administracao(quem) or contas is None:
        return None
    try:
        usuarios = contas.listar_usuarios()
        auditoria = contas.auditoria(limite=200)
    except autenticacao.ContasOcupadas:
        return {"indisponivel": True}

    total = len(usuarios)
    ativas = sum(1 for u in usuarios if u.get("ativo") == 1)
    inativas = total - ativas

    alteracoes = []
    for row in auditoria:
        if row.get("acao") == "salvar_permissoes":
            detalhe = row.get("detalhe")
            res = autenticacao.resumo_detalhe_auditoria(detalhe)
            if res is not None:
                resumo = res
            elif isinstance(detalhe, str) and len(detalhe) > 0:
                resumo = detalhe
            else:
                resumo = "—"
            alteracoes.append({
                "quando": row.get("quando"),
                "admin_login": row.get("admin_login"),
                "alvo": row.get("alvo"),
                "resumo": resumo,
            })
            if len(alteracoes) == 5:
                break

    return {
        "ativas": ativas,
        "inativas": inativas,
        "total": total,
        "alteracoes": alteracoes,
    }


def ler_dados(leitura, contexto, quem=None) -> dict:
    """Lê os dados necessários para montar a Visão Geral de acordo com o banco configurado."""
    banco = getattr(contexto, "banco", "real")
    if banco == "vies":
        lista = visao_geral_vies.itens(leitura, contexto)
        dados = {
            "banco": "vies",
            "resumo": leitura.resumo_geral(),
            "av": AV.resumo(lista),
            "triagem": leitura.contagem_triagem(),
            "relevancia": analises_blocos_vies.bloco_relevancia(lista),
            "execucoes": leitura.execucoes_recentes(5),
            "ultima_coleta": leitura.ultima_coleta_concluida(),
        }
    else:
        dados = {
            "banco": "real",
            "resumo": leitura.resumo_geral(),
            "revisao": leitura.contagem_revisao(),
            "prontidao": analises_blocos.bloco_prontidao(leitura.analise_prontidao())["cartoes"],
            "execucoes": leitura.execucoes_recentes(5),
            "ultima_coleta": leitura.ultima_coleta_concluida(),
            "n_ufs": len(contexto.ufs),
        }
        if ve_fila_artigos(quem):
            dados["triagem"] = leitura.contagem_triagem()
    if ve_andamento(quem):
        dados["atividade"] = leitura.atividade_por_revisor()
        dados["hoje"] = datetime.now(timezone.utc).date().isoformat()
    return dados


def _bloco_fila_artigos(triagem: dict, pred, bid: str, iid: str) -> dict:
    """Constrói o bloco da fila de triagem de artigos."""
    total_tri = triagem.get("total", 0)
    pendentes_tri = triagem.get("pendentes", 0)
    acoes_fila = []
    aviso_fila = None
    if pendentes_tri > 0:
        href_fila = "/literatura/triagem"
        if navegacao.pode_seguir(href_fila, pred):
            acoes_fila.append({"texto": f"Continuar a triagem ({pendentes_tri})", "href": href_fila})
    else:
        aviso_fila = "Nada pendente."
    return _bloco_base(
        bid,
        "Artigos para triar",
        "C1",
        indicadores=[
            _indicador(iid, "humana", "Artigos aguardando triagem humana", pendentes_tri, total_tri, ART, "Artigos exibidos na triagem que ainda não têm decisão de uma pessoa.", "C1")
        ],
        acoes=acoes_fila,
        aviso=aviso_fila,
    )


def montar(dados: dict, quem: dict) -> list[dict]:
    """Monta a lista de seções e blocos da Visão Geral."""
    banco = dados.get("banco", "real")
    logado = bool(quem.get("logado"))
    grupo = quem.get("grupo")
    permissoes = quem.get("permissoes", frozenset())

    pode_rota = quem.get("pode_rota")
    if callable(pode_rota):
        pred = pode_rota
    else:
        def pred(metodo: str, caminho: str) -> bool:
            return autenticacao.pode_acessar(grupo, permissoes, metodo, caminho)

    resumo = dados.get("resumo", {})
    revisao = dados.get("revisao", {})
    triagem = dados.get("triagem", {})
    av = dados.get("av", {})
    relevancia = dados.get("relevancia", {})

    # ---------------- 1. PESQUISA ----------------
    # Identificação
    if banco == "real":
        bloco_identificacao = _bloco_base(
            "identificacao",
            rotulos.NOMES_PESQUISA["real"],
            "C1",
            texto=[
                "Levantamento nas secretarias estaduais de segurança pública. Os números consideram só as execuções marcadas para o relatório."
            ],
            ultima_coleta=dados.get("ultima_coleta"),
        )
        inds_cobertura = [
            _indicador("consultas_web", "coleta", "Consultas web", resumo.get("consultas_web"), None, REL, "Buscas na web feitas com sucesso pelo provedor de busca.", "C1"),
            _indicador("urls_unicas", "coleta", "URLs únicas", resumo.get("urls_unicas"), None, REL, "Endereços distintos devolvidos pelas buscas na web.", "C1"),
            _indicador("paginas_com_texto", "coleta", "Páginas com texto", resumo.get("paginas_com_texto"), None, REL, "Páginas baixadas das quais o texto foi extraído.", "C1"),
        ]
    else:
        bloco_identificacao = _bloco_base(
            "identificacao",
            rotulos.NOMES_PESQUISA["vies"],
            "C1",
            texto=[
                "Busca de literatura científica e cinzenta sobre viés algorítmico: referências da web e artigos do Google Scholar, com a triagem do modelo e a triagem humana."
            ],
            ultima_coleta=dados.get("ultima_coleta"),
        )
        inds_cobertura = [
            _indicador("n_obras", "coleta", "Obras distintas", av.get("n_obras"), None, ITENS, "Itens contados uma vez quando a mesma obra aparece nas duas fontes.", "C1"),
            _indicador("n_web", "coleta", "Referências da web", av.get("n_web"), None, ITENS, "Itens devolvidos pela busca de literatura na web.", "C1"),
            _indicador("n_scholar", "coleta", "Artigos do Scholar", av.get("n_scholar"), None, ITENS, "Artigos devolvidos pelo Google Scholar.", "C1"),
            _indicador("n_em_ambas_fontes", "coleta", "Nas duas fontes", av.get("n_em_ambas_fontes"), None, ITENS, "Obras encontradas na web e no Scholar (mesmo endereço ou mesmo título).", "C1"),
        ]

    bloco_cobertura = _bloco_base(
        "cobertura",
        "Cobertura da coleta",
        "C1",
        indicadores=inds_cobertura,
    )

    # ---------------- 2. REVISÃO ----------------
    blocos_revisao = []
    if banco == "real":
        if logado and autenticacao.pode(grupo, permissoes, "verificar_achados"):
            total_rev = revisao.get("total", 0)
            verificados_rev = revisao.get("verificados", 0)
            pendentes_rev = total_rev - verificados_rev
            acoes_fila = []
            aviso_fila = None
            if pendentes_rev > 0:
                href_fila = "/revisao/achados"
                if navegacao.pode_seguir(href_fila, pred):
                    acoes_fila.append({"texto": f"Continuar a revisão ({pendentes_rev})", "href": href_fila})
            else:
                aviso_fila = "Nada pendente."
            bloco_fila = _bloco_base(
                "fila",
                "Achados para verificar",
                "C2",
                indicadores=[
                    _indicador("pendentes", "modelo", "Achados aguardando verificação humana", pendentes_rev, total_rev, REL, "Achados apontados pelo modelo que ainda não foram lidos por uma pessoa.", "C2")
                ],
                acoes=acoes_fila,
                aviso=aviso_fila,
            )
            blocos_revisao.append(bloco_fila)
        if ve_fila_artigos(quem) and "triagem" in dados:
            blocos_revisao.append(_bloco_fila_artigos(dados["triagem"], pred, "fila_artigos", "artigos_pendentes"))
    else:
        if ve_fila_artigos(quem):
            blocos_revisao.append(_bloco_fila_artigos(triagem, pred, "fila", "pendentes"))

    # ---------------- 3. RESULTADOS ----------------
    if banco == "real":
        conf_rev = revisao.get("confirmados", 0)
        desc_rev = revisao.get("descartados", 0)
        tot_rev = revisao.get("total", 0)
        ver_rev = revisao.get("verificados", 0)
        pend_rev = tot_rev - ver_rev
        rotulo_barra = f"{conf_rev} confirmados, {desc_rev} descartados, {pend_rev} pendentes"
        if logado:
            grafico_humanas = graficos.barra_empilhada(
                [(conf_rev, "be-conf", "Confirmados"), (desc_rev, "be-desc", "Descartados")],
                tot_rev,
                rotulo_barra,
            )
            den_verificados = revisao.get("total")
        else:
            grafico_humanas = None
            den_verificados = None
        inds_humanas = [
            _indicador("verificados", "humana", "Achados verificados", revisao.get("verificados"), den_verificados, REL, "Achados que uma pessoa leu e classificou.", "C1"),
            _indicador("confirmados", "humana", "Confirmados", revisao.get("confirmados"), revisao.get("verificados"), REL, "Achados verificados que a pessoa manteve como menção válida.", "C1"),
            _indicador("descartados", "humana", "Descartados", revisao.get("descartados"), revisao.get("verificados"), REL, "Achados verificados que a pessoa descartou.", "C1"),
            _indicador("ufs_confirmadas", "humana", "UFs com achado confirmado", resumo.get("ufs_confirmadas"), dados.get("n_ufs", 27), REL, "Unidades da federação com pelo menos um achado confirmado por uma pessoa.", "C1"),
        ]
        texto_humanas = ["Achado ainda não verificado não é achado descartado: falta a leitura de uma pessoa."]

        etapas = [
            ("Consultas web", resumo.get("consultas_web")),
            ("Resultados", resumo.get("resultados")),
            ("URLs únicas", resumo.get("urls_unicas")),
            ("Páginas selecionadas", resumo.get("selecionadas")),
            ("Páginas com texto", resumo.get("paginas_com_texto")),
            ("Classificações", resumo.get("classificacoes")),
            ("Achados", resumo.get("achados")),
            ("Achados verificados", resumo.get("verificados")),
            ("Confirmados", resumo.get("confirmados")),
        ]
        grafico_modelo = graficos.barras_horizontais(
            etapas,
            "Funil do levantamento nas secretarias",
            "Quantidade em cada etapa, da busca web aos achados confirmados",
            fmt.numero,
        )
        vazio_modelo = None
        inds_modelo = [
            _indicador("classificacoes", "modelo", "Classificações", resumo.get("classificacoes"), None, REL, "Páginas que o modelo leu e classificou.", "C2"),
            _indicador("achados", "modelo", "Achados apontados pelo modelo", resumo.get("achados"), None, REL, "Trechos em que o modelo identificou menção a uma ferramenta de IA na segurança pública.", "C2"),
        ]
    else:
        inc_tri = triagem.get("incluidos", 0)
        exc_tri = triagem.get("excluidos", 0)
        tot_tri = triagem.get("total", 0)
        pend_tri = triagem.get("pendentes", 0)
        triados_humana = inc_tri + exc_tri
        rotulo_barra = f"{inc_tri} incluídos, {exc_tri} excluídos, {pend_tri} pendentes"
        if logado:
            grafico_humanas = graficos.barra_empilhada(
                [(inc_tri, "be-conf", "Incluídos"), (exc_tri, "be-desc", "Excluídos")],
                tot_tri,
                rotulo_barra,
            )
            den_triagem = tot_tri
        else:
            grafico_humanas = None
            den_triagem = None
        inds_humanas = [
            _indicador("com_triagem_humana", "humana", "Artigos com triagem humana", triados_humana, den_triagem, ART, "Artigos que uma pessoa incluiu ou excluiu.", "C1"),
            _indicador("incluidos", "humana", "Incluídos", inc_tri, triados_humana, ART, "Artigos que a pessoa incluiu.", "C1"),
            _indicador("excluidos", "humana", "Excluídos", exc_tri, triados_humana, ART, "Artigos que a pessoa excluiu.", "C1"),
        ]
        texto_humanas = ["Artigo ainda sem triagem humana não é artigo excluído: falta a decisão de uma pessoa."]

        grafico_modelo = relevancia.get("grafico")
        vazio_modelo = relevancia.get("aviso") if not grafico_modelo else None
        inds_modelo = [
            _indicador("n_triados", "modelo", "Com triagem válida do modelo", av.get("n_triados"), av.get("n_itens"), ITENS, "Itens que o modelo classificou com uma resposta válida (cada item na sua fonte).", "C2"),
            _indicador("n_alta", "modelo", "Relevância alta segundo o modelo", av.get("n_alta"), av.get("n_triados"), ITENS, "Itens que o modelo julgou de relevância alta.", "C2"),
            _indicador("n_fora", "modelo", "Fora do escopo segundo o modelo", av.get("n_fora"), av.get("n_triados"), ITENS, "Itens que o modelo julgou fora do escopo da pesquisa.", "C2"),
        ]

    bloco_decisoes_humanas = _bloco_base(
        "decisoes_humanas",
        "Decisões humanas",
        "C1",
        texto=texto_humanas,
        indicadores=inds_humanas,
        grafico=grafico_humanas,
    )

    if logado:
        bloco_segundo_modelo = _bloco_base(
            "segundo_o_modelo",
            "Segundo o modelo (preliminar)",
            "C2",
            indicadores=inds_modelo,
            grafico=grafico_modelo,
            vazio=vazio_modelo,
            aviso=PRELIMINAR,
        )
    else:
        bloco_segundo_modelo = _bloco_base(
            "segundo_o_modelo",
            "Segundo o modelo (preliminar)",
            "C2",
            indicadores=[],
            grafico=None,
            vazio=None,
            acoes=[],
            cartoes=None,
            execucoes=None,
            texto=[],
            aviso=NAO_DIVULGADO,
        )

    # ---------------- 4. QUALIDADE ----------------
    if banco == "real":
        # Conferencia (C2)
        if logado:
            acoes_conf = []
            if revisao.get("pendentes_sem_evidencia", 0) > 0:
                href_conf = "/achados?verificacao=pendente&evidencia=0"
                if navegacao.pode_seguir(href_conf, pred):
                    acoes_conf.append({"texto": "Ver esses achados", "href": href_conf})
            bloco_conferencia = _bloco_base(
                "conferencia",
                "Conferência das citações",
                "C2",
                indicadores=[
                    _indicador("evidencia", "verificacao_automatica", "Citação localizada no texto", resumo.get("evidencia_ok"), resumo.get("achados"), REL, "Achados cuja citação literal foi encontrada no texto da página por conferência automática.", "C2"),
                    _indicador("sem_evidencia", "verificacao_automatica", "Sem verificação humana e com a citação não localizada", revisao.get("pendentes_sem_evidencia"), None, REL, "Achados ainda não verificados cuja citação a conferência automática não encontrou no texto.", "C2"),
                ],
                acoes=acoes_conf,
                aviso=PRELIMINAR,
            )
        else:
            bloco_conferencia = _bloco_base(
                "conferencia",
                "Conferência das citações",
                "C2",
                indicadores=[],
                grafico=None,
                vazio=None,
                acoes=[],
                cartoes=None,
                execucoes=None,
                texto=[],
                aviso=NAO_DIVULGADO,
            )

        # Prontidao (C1)
        cartoes_prontidao = []
        pode_chamadas = autenticacao.ve_detalhes_tecnicos(logado, grupo, permissoes)
        for c in dados.get("prontidao", []):
            card = dict(c)
            card["href"] = card["href"] if (card.get("href") and navegacao.pode_seguir(card["href"], pred)) else None
            card["comando"] = card.get("comando") if pode_chamadas else None
            cartoes_prontidao.append(card)

        bloco_prontidao = _bloco_base(
            "prontidao",
            "Prontidão metodológica",
            "C1",
            texto=["O que falta rotular por uma pessoa para destravar cada análise."],
            cartoes=cartoes_prontidao,
            origem="calculada",
            origem_rotulo=ORIGENS["calculada"][0],
            validacao=ORIGENS["calculada"][1],
            universo=REL,
            definicao="Cada cartão compara as decisões humanas já registradas com o mínimo que a análise estatística exige.",
        )
        blocos_qualidade = [bloco_conferencia, bloco_prontidao]
    else:
        # Ocultos (C2)
        if logado:
            bloco_ocultos = _bloco_base(
                "ocultos",
                "Artigos ocultos pelo modelo",
                "C2",
                indicadores=[
                    _indicador("ocultos_llm", "modelo", "Artigos ocultos pela triagem do modelo", triagem.get("ocultos_llm"), None, "Todos os artigos.", "Artigos que o modelo excluiu e que ainda não têm decisão de uma pessoa; não aparecem na triagem por padrão.", "C2")
                ],
                aviso=PRELIMINAR,
            )
        else:
            bloco_ocultos = _bloco_base(
                "ocultos",
                "Artigos ocultos pelo modelo",
                "C2",
                indicadores=[],
                grafico=None,
                vazio=None,
                acoes=[],
                cartoes=None,
                execucoes=None,
                texto=[],
                aviso=NAO_DIVULGADO,
            )
        blocos_qualidade = [bloco_ocultos]

    # ---------------- 5. OPERAÇÃO (C3) ----------------
    bloco_operacao = None
    if autenticacao.ve_detalhes_tecnicos(logado, grupo, permissoes):
        mostrar_custo = bool(autenticacao.pode(grupo, permissoes, "ver_custos"))
        execucoes_raw = dados.get("execucoes", [])
        lista_exec = []
        for e in execucoes_raw:
            run_id = e["run_id"]
            href = f"/execucoes/{quote(run_id, safe='')}"
            href_valido = href if navegacao.pode_seguir(href, pred) else None
            custo = e.get("custo_usd") if mostrar_custo else None
            no_rel = "dentro" if e.get("no_relatorio") == 1 else "fora"
            lista_exec.append({
                "run_id": run_id,
                "href": href_valido,
                "comando": e.get("comando"),
                "status": e.get("status"),
                "iniciado_em": e.get("iniciado_em"),
                "custo_usd": custo,
                "no_relatorio": no_rel,
            })

        comando_ini = None
        if len(execucoes_raw) == 0:
            if banco == "real":
                comando_ini = "python main.py pipeline-uf --ufs PI --limite 5"
            else:
                comando_ini = "python main.py buscar-literatura --conjunto A --limite 5 --banco vies"

        inds_exec = [
            _indicador("nao_concluidas", "operacao", "Execuções não concluídas", resumo.get("execucoes_nao_concluidas"), None, TODAS, "Execuções que não terminaram como concluídas.", "C3"),
            _indicador("falhas", "operacao", "Chamadas externas com falha", resumo.get("chamadas_com_falha"), None, TODAS, "Chamadas aos provedores registradas sem sucesso.", "C3"),
        ]
        if mostrar_custo:
            inds_exec.append(
                _indicador("gasto", "operacao", "Gasto registrado", resumo.get("custo_total_usd"), None, TODAS, "Soma do custo registrado das chamadas.", "C3", formato="moeda", exige=("ver_custos",))
            )

        bloco_operacao = _bloco_base(
            "execucoes",
            "Execuções e chamadas",
            "C3",
            indicadores=inds_exec,
            execucoes=lista_exec,
            mostrar_custo=mostrar_custo,
            comando_inicial=comando_ini,
        )

    # ---------------- 5. ANDAMENTO DA EQUIPE (C3) ----------------
    bloco_andamento = None
    if ve_andamento(quem) and "atividade" in dados:
        totais, janela = autenticacao.resumir_atividade(dados["atividade"], dados.get("hoje", ""))
        soma_achados = sum(t["achados"] for t in totais)
        soma_artigos = sum(t["artigos"] for t in totais)
        decisoes = soma_achados + soma_artigos
        soma_janela = sum(j["achados"] + j["artigos"] for j in janela)
        universo_and = "Decisões de revisores registradas no painel, em achados (sem as desfeitas) e em artigos."
        inds_andamento = [
            _indicador("decisoes", "humana", "Decisões registradas", decisoes, None, universo_and, "Decisões em achados e em artigos, somadas.", "C3"),
            _indicador("decisoes_achados", "humana", "Em achados", soma_achados, decisoes, universo_and, "Decisões de verificação de achados que não foram desfeitas.", "C3"),
            _indicador("decisoes_artigos", "humana", "Em artigos", soma_artigos, decisoes, universo_and, "Decisões de triagem de artigos.", "C3"),
            _indicador("decisoes_recentes", "humana", "Nos últimos 30 dias", soma_janela, decisoes, universo_and, "Decisões com data entre hoje e 29 dias atrás (UTC).", "C3"),
        ]
        acoes_andamento = []
        href_estat = "/estatisticas-usuarios"
        if navegacao.pode_seguir(href_estat, pred):
            acoes_andamento.append({"texto": "Ver a atividade por revisor", "href": href_estat})
        vazio_andamento = "Ainda não há decisões de revisores." if decisoes == 0 else None
        bloco_andamento = _bloco_base(
            "andamento",
            "Atividade da equipe",
            "C3",
            texto=["Totais da equipe, sem identificar quem decidiu."],
            indicadores=inds_andamento,
            acoes=acoes_andamento,
            vazio=vazio_andamento,
        )

    # ---------------- 6. ADMINISTRAÇÃO (C3) ----------------
    bloco_administracao = None
    if ve_administracao(quem) and dados.get("contas_resumo"):
        resumo_contas = dados["contas_resumo"]
        texto_admin = ["Quem não entrou só vê o que a divulgação pública desta pesquisa libera."]
        if resumo_contas.get("indisponivel"):
            bloco_administracao = _bloco_base(
                "administracao",
                "Contas e permissões",
                "C3",
                texto=texto_admin,
                aviso="O banco de contas está ocupado. Tente de novo em alguns segundos.",
                indicadores=[],
                vazio=None,
                acoes=[],
            )
            bloco_administracao["alteracoes"] = []
        else:
            ativas = resumo_contas.get("ativas", 0)
            inativas = resumo_contas.get("inativas", 0)
            total = resumo_contas.get("total", 0)
            alteracoes = list(resumo_contas.get("alteracoes", []))

            inds_admin = [
                _indicador(
                    "contas_ativas",
                    "administracao",
                    "Contas ativas",
                    ativas,
                    total,
                    "Contas do painel.",
                    "Contas que podem entrar no painel.",
                    "C3",
                ),
                _indicador(
                    "contas_inativas",
                    "administracao",
                    "Contas desativadas",
                    inativas,
                    total,
                    "Contas do painel.",
                    "Contas desativadas por um administrador; não entram no painel.",
                    "C3",
                ),
            ]

            acoes_admin = []
            for t, h in [
                ("Gerenciar contas", "/admin/usuarios"),
                ("Ver a divulgação pública", "/admin/divulgacao"),
                ("Ver o registro de administração", "/admin/auditoria"),
            ]:
                if navegacao.pode_seguir(h, pred):
                    acoes_admin.append({"texto": t, "href": h})

            vazio_admin = "Nenhuma alteração de permissões registrada." if not alteracoes else None

            bloco_administracao = _bloco_base(
                "administracao",
                "Contas e permissões",
                "C3",
                texto=texto_admin,
                aviso=None,
                indicadores=inds_admin,
                vazio=vazio_admin,
                acoes=acoes_admin,
            )
            bloco_administracao["alteracoes"] = alteracoes

    # ---------------- 7. APROFUNDAR (C1) ----------------
    if banco == "real":
        candidatos_links = [
            ("PRISMA", "/literatura/prisma"),
            ("Estados", "/estados"),
            ("Achados", "/achados"),
            ("Análises", "/analises"),
            ("Metodologia", "/metodologia"),
            ("Sobre os dados", "/sobre"),
        ]
    else:
        candidatos_links = [
            ("Observatório", "/observatorio"),
            ("Referências", "/literatura/referencias"),
            ("PRISMA", "/literatura/prisma"),
            ("Análises", "/analises"),
            ("Validação da triagem", "/validacao"),
            ("Metodologia", "/metodologia"),
            ("Sobre os dados", "/sobre"),
        ]
    acoes_links = [{"texto": t, "href": h} for t, h in candidatos_links if navegacao.pode_seguir(h, pred)]
    bloco_links = _bloco_base(
        "links",
        "Páginas para aprofundar",
        "C1",
        acoes=acoes_links,
    )

    # ---------------- MONTAGEM FINAL DAS SEÇÕES ----------------
    secoes_candidatas = [
        {"id": "pesquisa", "titulo": "A pesquisa", "blocos": [bloco_identificacao, bloco_cobertura]},
        {"id": "revisao", "titulo": "Sua revisão", "blocos": blocos_revisao},
        {"id": "resultados", "titulo": "Resultados", "blocos": [bloco_decisoes_humanas, bloco_segundo_modelo]},
        {"id": "qualidade", "titulo": "Qualidade dos dados", "blocos": blocos_qualidade},
        {"id": "andamento", "titulo": "Andamento da equipe", "blocos": [bloco_andamento] if bloco_andamento else []},
        {"id": "operacao", "titulo": "Operação técnica", "blocos": [bloco_operacao] if bloco_operacao else []},
        {"id": "administracao", "titulo": "Administração", "blocos": [bloco_administracao] if bloco_administracao else []},
        {"id": "aprofundar", "titulo": "Para aprofundar", "blocos": [bloco_links]},
    ]

    secoes = []
    for s in secoes_candidatas:
        blocos = [b for b in s["blocos"] if b is not None]
        if not autenticacao.pode(grupo, permissoes, "ver_painel"):
            blocos = []
        if blocos:
            secoes.append({"id": s["id"], "titulo": s["titulo"], "blocos": blocos})

    return secoes
