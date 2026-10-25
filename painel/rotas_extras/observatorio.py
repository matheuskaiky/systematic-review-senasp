"""Rotas do Observatorio do banco vies: listagem de obras com filtros compartilháveis."""
from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import HTMLResponse

from dominio import observatorio_vies as OV
from painel import analises_blocos_vies as bv, rotulos, visao_geral_vies


def consulta(filtros, **mudancas):
    """Devolve a query string para links que preservam os filtros ativos."""
    params = {**filtros, **mudancas}
    pares = []
    for k in OV.FILTROS:
        if k in params:
            v = params[k]
            if v is None:
                continue
            if k == "perspectiva" and v == "integrada":
                continue
            if k == "universo" and v == "elegiveis":
                continue
            pares.append((k, v))
    for k, v in mudancas.items():
        if k not in OV.FILTROS and v is not None:
            pares.append((k, v))
    return urlencode(pares)


def _formatar_obra(o, contexto, mapa_comb):
    """Formata os valores de exibição das nove colunas de uma obra."""
    titulo_raw = o.get("titulo") or ""
    texto_titulo = titulo_raw if titulo_raw.strip() else "Sem título"
    mid = o["id"]
    link_rep = f"/literatura/artigos/{mid[2:]}" if mid.startswith("A-") else f"/literatura/referencias/web/{mid[2:]}"

    fontes_str = " e ".join(o["fontes"])

    conjunto_str = mapa_comb[o["combinacao"]]

    recorte = o.get("recorte")
    if recorte in contexto.recortes_vies:
        angulo_str = contexto.recortes_vies[recorte]
    else:
        angulo_str = "Sem ângulo"

    rel = o.get("relevancia")
    if rel is None:
        relevancia_str = "Sem triagem válida"
    elif rel in rotulos.RELEVANCIA_VIES:
        relevancia_str = rotulos.RELEVANCIA_VIES[rel]
    else:
        relevancia_str = "Relevância não reconhecida"

    eixo = o.get("eixo")
    eixo_str = eixo if eixo else "Sem eixo"

    partes_div = []
    if o["divergencias"]:
        campos = [bv.CAMPOS_DA_AUDITORIA[c].lower() for c in o["divergencias"]]
        partes_div.append(f"Membros divergem em: {', '.join(campos)}")
    if o["possivel_duplicata"]:
        partes_div.append("Possível duplicata: outro artigo do Scholar tem a mesma URL")
    divergencia_str = "; ".join(partes_div) if partes_div else "—"

    membros = []
    for _, item_id in o["membros"]:
        link_m = f"/literatura/artigos/{item_id[2:]}" if item_id.startswith("A-") else f"/literatura/referencias/web/{item_id[2:]}"
        membros.append({"id": item_id, "link": link_m})

    url = o.get("url") or ""

    return {
        "titulo": texto_titulo,
        "link_representante": link_rep,
        "fontes": fontes_str,
        "conjuntos": conjunto_str,
        "angulo": angulo_str,
        "relevancia": relevancia_str,
        "eixo": eixo_str,
        "divergencia": divergencia_str,
        "membros": membros,
        "url": url,
    }


def registrar(c):
    """Registra as rotas do Observatório."""
    app, leitura, contexto = c.app, c.leitura, c.contexto

    @app.get("/observatorio/obras", response_class=HTMLResponse)
    def obras(request: Request):
        if contexto.banco != "vies":
            return c.erro(request, 404, "Página não encontrada", "O Observatório existe só no banco vies.")
        if not leitura.existe():
            return c.sem_banco(request)

        pares = list(request.query_params.multi_items())
        nomes = tuple(dict.fromkeys(contexto.conjunto_da_consulta.values()))
        recortes = tuple(contexto.recortes_vies)
        eixos = tuple(contexto.eixos_exploracao)

        filtros, erros = OV.ler_filtros(pares, nomes, recortes, eixos)
        if erros:
            return c.erro(request, 400, "Filtro inválido", " ".join(erros))

        with leitura.instantaneo() as l:
            lista = visao_geral_vies.itens(l, contexto)

        lista = [{**it, "url": it["url"] if isinstance(it.get("url"), str) else None} for it in lista]

        obras_proj, _ = OV.projecao(lista, nomes)
        filtradas = OV.ordenar(OV.filtrar(obras_proj, filtros, recortes))

        total = len(filtradas)
        pagina, erro = OV.ler_pagina(pares, total)
        if erro:
            return c.erro(request, 400, "Página inválida", erro)

        paginas = OV.ultima_pagina(total)
        fatia_obras = OV.fatia(filtradas, pagina)

        comb_opcoes = OV.combinacoes(nomes)
        mapa_comb = dict(comb_opcoes)
        linhas_tabela = [_formatar_obra(o, contexto, mapa_comb) for o in fatia_obras]

        ang_opcoes = [(k, contexto.recortes_vies[k]) for k in recortes] + [("sem_angulo", "Sem ângulo")]
        rotulo_recorte = ""
        if filtros["perspectiva"] in OV.ANGULO_DA_PERSPECTIVA:
            chave_recorte = OV.ANGULO_DA_PERSPECTIVA[filtros["perspectiva"]]
            rotulo_recorte = contexto.recortes_vies.get(chave_recorte, "")

        q_limpar = consulta(filtros)
        q_trilha = q_limpar

        return c.pagina(
            request,
            "observatorio_obras.html",
            filtros=filtros,
            total=total,
            pagina=pagina,
            paginas=paginas,
            linhas=linhas_tabela,
            nomes=nomes,
            eixos=eixos,
            comb_opcoes=comb_opcoes,
            ang_opcoes=ang_opcoes,
            rotulo_universo=dict(OV.UNIVERSOS)[filtros["universo"]],
            rotulo_recorte=rotulo_recorte,
            aviso_modelo=bv.AVISO_MODELO,
            consulta=consulta,
            query_limpar=q_limpar,
            query_trilha=q_trilha,
            perspectivas=OV.PERSPECTIVAS,
            universos=OV.UNIVERSOS,
            fontes=OV.FONTES,
        )
