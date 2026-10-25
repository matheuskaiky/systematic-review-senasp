"""Rotas do Observatorio do banco vies: listagem de obras e página com três perspectivas."""
from datetime import datetime
from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import HTMLResponse

from dominio import observatorio_vies as OV
from painel import analises_blocos_vies as bv, observatorio_blocos, rotulos, visao_geral_vies


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


def _preparar_dados(c, request):
    """Executa os passos 1 a 6 comuns às rotas do Observatório."""
    contexto = c.contexto
    if contexto.banco != "vies":
        return None, c.erro(request, 404, "Página não encontrada", "O Observatório existe só no banco vies.")
    if not c.leitura.existe():
        return None, c.sem_banco(request)

    pares = list(request.query_params.multi_items())
    nomes = tuple(dict.fromkeys(contexto.conjunto_da_consulta.values()))
    recortes = tuple(contexto.recortes_vies)
    eixos = tuple(contexto.eixos_exploracao)

    filtros, erros = OV.ler_filtros(pares, nomes, recortes, eixos)
    if erros:
        return None, c.erro(request, 400, "Filtro inválido", " ".join(erros))

    with c.leitura.instantaneo() as l:
        lista = visao_geral_vies.itens(l, contexto)
        hora_leitura = datetime.now().strftime("%d/%m/%Y %H:%M")

    lista = [{**it, "url": it["url"] if isinstance(it.get("url"), str) else None} for it in lista]

    obras_proj, ambiguas = OV.projecao(lista, nomes)
    filtradas = OV.filtrar(obras_proj, filtros, recortes)

    comb_opcoes = OV.combinacoes(nomes)
    mapa_comb = dict(comb_opcoes)
    ang_opcoes = [(k, contexto.recortes_vies[k]) for k in recortes] + [("sem_angulo", "Sem ângulo")]
    rotulo_recorte = ""
    if filtros["perspectiva"] in OV.ANGULO_DA_PERSPECTIVA:
        chave_recorte = OV.ANGULO_DA_PERSPECTIVA[filtros["perspectiva"]]
        rotulo_recorte = contexto.recortes_vies.get(chave_recorte, "")

    rotulo_universo = dict(OV.UNIVERSOS)[filtros["universo"]]
    q_limpar = consulta(filtros)

    dados = {
        "filtros": filtros,
        "filtradas": filtradas,
        "ambiguas": ambiguas,
        "pares": pares,
        "nomes": nomes,
        "recortes": recortes,
        "eixos": eixos,
        "comb_opcoes": comb_opcoes,
        "mapa_comb": mapa_comb,
        "ang_opcoes": ang_opcoes,
        "rotulo_recorte": rotulo_recorte,
        "rotulo_universo": rotulo_universo,
        "hora_leitura": hora_leitura,
        "q_limpar": q_limpar,
    }
    return dados, None


def registrar(c):
    """Registra as rotas do Observatório."""
    app = c.app

    @app.get("/observatorio", response_class=HTMLResponse)
    def observatorio(request: Request):
        dados, erro = _preparar_dados(c, request)
        if erro:
            return erro

        filtradas = dados["filtradas"]
        total = len(filtradas)
        filtros = dados["filtros"]

        def _href(**mudancas):
            q = consulta(filtros, **mudancas)
            return f"/observatorio/obras?{q}" if q else "/observatorio/obras"

        textos_consultas = tuple(c.contexto.consultas_literatura.values())
        blocos_lista = (
            observatorio_blocos.blocos(
                filtros["perspectiva"],
                filtradas,
                dados["ambiguas"],
                filtros,
                dados["nomes"],
                c.contexto.recortes_vies,
                dados["eixos"],
                textos_consultas,
                dados["rotulo_universo"],
                _href,
            )
            if total > 0
            else []
        )

        return c.pagina(
            request,
            "observatorio.html",
            filtros=filtros,
            total=total,
            hora_leitura=dados["hora_leitura"],
            rotulo_universo=dados["rotulo_universo"],
            rotulo_recorte=dados["rotulo_recorte"],
            comb_opcoes=dados["comb_opcoes"],
            ang_opcoes=dados["ang_opcoes"],
            nomes=dados["nomes"],
            eixos=dados["eixos"],
            blocos=blocos_lista,
            consulta=consulta,
            query_limpar=dados["q_limpar"],
            perspectivas=OV.PERSPECTIVAS,
            universos=OV.UNIVERSOS,
            fontes=OV.FONTES,
        )

    @app.get("/observatorio/obras", response_class=HTMLResponse)
    def obras(request: Request):
        dados, erro = _preparar_dados(c, request)
        if erro:
            return erro

        filtradas_ordenadas = OV.ordenar(dados["filtradas"])
        total = len(filtradas_ordenadas)
        pagina, erro_pag = OV.ler_pagina(dados["pares"], total)
        if erro_pag:
            return c.erro(request, 400, "Página inválida", erro_pag)

        paginas = OV.ultima_pagina(total)
        fatia_obras = OV.fatia(filtradas_ordenadas, pagina)
        linhas_tabela = [_formatar_obra(o, c.contexto, dados["mapa_comb"]) for o in fatia_obras]

        return c.pagina(
            request,
            "observatorio_obras.html",
            filtros=dados["filtros"],
            total=total,
            pagina=pagina,
            paginas=paginas,
            linhas=linhas_tabela,
            nomes=dados["nomes"],
            eixos=dados["eixos"],
            comb_opcoes=dados["comb_opcoes"],
            ang_opcoes=dados["ang_opcoes"],
            rotulo_universo=dados["rotulo_universo"],
            rotulo_recorte=dados["rotulo_recorte"],
            aviso_modelo=bv.AVISO_MODELO,
            consulta=consulta,
            query_limpar=dados["q_limpar"],
            query_trilha=dados["q_limpar"],
            perspectivas=OV.PERSPECTIVAS,
            universos=OV.UNIVERSOS,
            fontes=OV.FONTES,
        )
