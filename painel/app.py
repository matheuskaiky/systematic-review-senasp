"""Painel de resultados (FastAPI + Jinja2, HTML no servidor). Recebe leitura, fabrica de repositorio e armazenamento
bruto por parametro; nao importa adaptadores, composicao, sqlite3, requests nem le o ambiente."""
import hmac
import json
import secrets
from dataclasses import dataclass, field
from types import SimpleNamespace
from pathlib import Path
from urllib.parse import quote, unquote, urlencode, urlsplit

from fastapi import FastAPI, Form, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fastapi.templating import Jinja2Templates

from aplicacao import revisao
from dominio import relevancia as relev
from dominio.servicos_painel import diff_config, localizar_evidencia, mascarar_segredos, trecho_mais_parecido
from painel import formatacao as fmt, rotulos
from painel.graficos import barra_empilhada, barras_horizontais, colunas, mapa_de_blocos, mapa_de_calor

AQUI = Path(__file__).parent
CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
       "base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
FILTROS_CHAMADAS = ("run", "etapa", "provedor", "uf", "resultado", "q")
FILTROS_ARTIGOS = ("q", "decisao", "multi", "termo", "base", "ano_de", "ano_ate", "rel", "ordem", "llm")
FILTROS = ("uf", "esfera", "cidade", "tecnologia", "status", "confianca", "evidencia", "oficial", "origem", "verificacao", "q")
JANELA_CONTEXTO = 2500            # caracteres de cada lado da evidencia na visao resumida
LIMITE_TEXTO = 200_000            # o visor nunca mostra mais que isto
MAX_PAGINA = 1_000_000            # teto do ?p= (o OFFSET do SQLite estoura acima de 2**63)
MAX_BUSCA = 200
LIMITE_BRUTO = 200_000            # o visor de arquivos brutos mostra no maximo isto; o arquivo inteiro vai por download


def _inteiro(valor, padrao, minimo=1, maximo=MAX_PAGINA):
    """Parametro numerico da URL: vazio usa o padrao; texto ou fora da faixa devolve None (a rota responde 404)."""
    if valor in (None, ""):
        return padrao
    try:
        n = int(str(valor).strip())
    except ValueError:
        return None
    return n if minimo <= n <= maximo else None


@dataclass
class Contexto:
    banco: str                                # "real" | "simulado" | "demo"
    nome_banco: str
    somente_leitura: bool
    pasta_backup: Path
    ufs: dict                                 # sigla -> nome
    status_permitidos: set
    status_definicoes: dict                   # chave -> definicao (vem de config/vocabulario)
    comando_criar_banco: str = "python main.py pipeline-uf --ufs PI --limite 5"
    termos: dict = field(default_factory=dict)      # id -> consulta (so para exibir)
    bases: tuple = ()                               # bases das buscas manuais
    hosts_permitidos: tuple = ("127.0.0.1", "localhost")   # DNS rebinding: qualquer outro Host e recusado
    backup_feito: bool = field(default=False)


def _filtros(params):
    return {k: str(params[k])[:MAX_BUSCA] for k in FILTROS if params.get(k) not in (None, "")}


def criar_app(leitura, repositorio_fabrica, bruto, contexto):
    app = FastAPI(title="Painel de resultados", docs_url=None, redoc_url=None, openapi_url=None)
    modelos = Jinja2Templates(directory=str(AQUI / "templates"))
    modelos.env.filters["url_segura"] = lambda u: u if str(u or "").lower().startswith(("http://", "https://")) else "#"
    modelos.env.globals.update(fmt=fmt, rotulos=rotulos, ctx=contexto, quote=quote, urlencode=urlencode)
    app.mount("/static", StaticFiles(directory=str(AQUI / "static")), name="static")

    # ---------- seguranca: cabecalhos, CSRF (cookie duplicado no formulario) e cookies SameSite=Strict ----------
    @app.middleware("http")
    async def seguranca(request: Request, call_next):
        token = request.cookies.get("csrf") or secrets.token_urlsafe(32)
        request.state.csrf = token
        resposta = await call_next(request)
        if not request.cookies.get("csrf"):
            resposta.set_cookie("csrf", token, httponly=True, samesite="strict")
        resposta.headers["Content-Security-Policy"] = CSP
        resposta.headers["X-Content-Type-Options"] = "nosniff"
        resposta.headers["Referrer-Policy"] = "no-referrer"
        return resposta

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(contexto.hosts_permitidos))

    def pagina(request, modelo, status=200, **dados):
        revisor = unquote(request.cookies.get("revisor", ""))
        return modelos.TemplateResponse(request, modelo, {"revisor": revisor, "csrf": request.state.csrf,
                                                        "caminho": request.url.path, **dados}, status_code=status)

    def erro(request, status, titulo, texto):
        return pagina(request, "erro.html", status=status, titulo=titulo, texto=texto)

    def sem_banco(request):
        return pagina(request, "sem_banco.html", status=503)

    def _mesma_origem(request):
        """Origin (ou, sem ele, Referer) tem de ser o proprio painel: o cookie de CSRF sozinho nao distingue outra porta
        de localhost. Sem nenhum dos dois (cliente que nao e navegador) nao ha o que conferir."""
        for cabecalho in ("origin", "referer"):
            valor = request.headers.get(cabecalho)
            if valor is not None:
                return urlsplit(valor).netloc == request.headers.get("host")
        return True

    def checar_escrita(request, csrf):
        if contexto.somente_leitura:
            return erro(request, 403, "Modo somente leitura", "O painel foi iniciado com --somente-leitura; nenhuma decisão é gravada.")
        if not _mesma_origem(request):
            return erro(request, 403, "Pedido recusado", "O pedido veio de outro site ou de outra porta, não deste painel.")
        if not csrf or not hmac.compare_digest(csrf, request.cookies.get("csrf", "")):
            return erro(request, 403, "Formulário recusado", "O token de segurança não confere. Recarregue a página e tente de novo.")
        return None

    @app.exception_handler(RequestValidationError)
    async def parametro_invalido(request, exc):
        return erro(request, 404, "Endereço inválido", "Algum número ou parâmetro do endereço não é válido.")

    @app.exception_handler(404)
    async def nao_encontrado(request, exc):
        return erro(request, 404, "Página não encontrada", "O endereço não existe neste painel.")

    # ---------- visao geral ----------
    @app.get("/", response_class=HTMLResponse)
    def geral(request: Request):
        if not leitura.existe():
            return sem_banco(request)
        r, rev = leitura.resumo_geral(), leitura.contagem_revisao()
        f = leitura.funil()
        etapas = [("Consultas web", f["consultas_web"]), ("Resultados", f["resultados"]), ("URLs únicas", f["urls_unicas"]),
                  ("Páginas selecionadas", f["selecionadas"]), ("Páginas com texto", f["paginas_com_texto"]),
                  ("Classificações", f["classificacoes"]), ("Achados", f["achados"]), ("Achados verificados", f["verificados"]),
                  ("Confirmados", f["confirmados"])]
        funil = barras_horizontais(etapas, "Funil do levantamento nas secretarias",
                                   "Quantidade em cada etapa, da busca web aos achados confirmados", fmt.numero)
        alertas = []
        if rev["total"] - rev["verificados"]:
            alertas.append(("aviso", f"{fmt.numero(rev['total'] - rev['verificados'])} achado(s) ainda sem verificação humana.", "/revisao/achados", "Começar revisão"))
        if rev["pendentes_sem_evidencia"]:
            alertas.append(("aviso", f"{fmt.numero(rev['pendentes_sem_evidencia'])} achado(s) não verificado(s) com evidência não localizada no texto.", "/achados?verificacao=pendente&evidencia=0", "Ver"))
        if r["execucoes_nao_concluidas"]:
            alertas.append(("aviso", f"{fmt.numero(r['execucoes_nao_concluidas'])} execução(ões) não concluída(s).", None, None))
        if r["chamadas_com_falha"]:
            alertas.append(("info", f"{fmt.numero(r['chamadas_com_falha'])} chamada(s) externa(s) com falha registrada.", None, None))
        barra = barra_empilhada([(rev["confirmados"], "be-conf", "Confirmados"), (rev["descartados"], "be-desc", "Descartados")],
                                rev["total"], f"{rev['confirmados']} confirmados, {rev['descartados']} descartados, "
                                              f"{rev['total'] - rev['verificados']} pendentes")
        return pagina(request, "geral.html", r=r, rev=rev, funil=funil, barra=barra, alertas=alertas,
                      execucoes=leitura.execucoes_recentes(5), n_ufs=len(contexto.ufs))

    # ---------- estados ----------
    def _linhas_ufs():
        por_uf = {l["uf"]: l for l in leitura.resumo_ufs()}
        vazio = {"n_achados": 0, "n_verificados": 0, "n_confirmados": 0, "n_evidencia_ok": 0, "n_fonte_oficial": 0}
        return [{"uf": uf, "nome": nome, **{**vazio, **por_uf.get(uf, {})}} for uf, nome in contexto.ufs.items()]

    @app.get("/estados", response_class=HTMLResponse)
    def estados(request: Request):
        if not leitura.existe():
            return sem_banco(request)
        linhas = _linhas_ufs()
        blocos = {}
        for l in linhas:
            if l["n_confirmados"]:
                blocos[l["uf"]] = ("confirmado", f"{l['n_confirmados']} achado(s) confirmado(s)")
            elif l["n_achados"]:
                blocos[l["uf"]] = ("classificado", f"{l['n_achados']} achado(s), nenhum confirmado ainda")
            else:
                blocos[l["uf"]] = ("sem-achados", "nenhum achado")
        mapa = mapa_de_blocos(blocos, "Situação por estado", "Cada bloco é uma UF: confirmada, só classificada ou sem achados")
        return pagina(request, "estados.html", linhas=linhas, mapa=mapa)

    @app.get("/estados/{uf}", response_class=HTMLResponse)
    def estado(request: Request, uf: str):
        uf = uf.upper()
        if uf not in contexto.ufs:
            return erro(request, 404, "Estado não encontrado", f"“{uf}” não é uma UF conhecida.")
        if not leitura.existe():
            return sem_banco(request)
        itens = leitura.achados({"uf": uf}, 1, 200)["itens"]
        grupos = {}
        for a in itens:
            grupos.setdefault(a["tecnologia"], []).append(a)
        return pagina(request, "estado.html", uf=uf, nome=contexto.ufs[uf], grupos=grupos, total=len(itens))

    # ---------- execucoes ----------
    def _json(texto):
        try:
            return json.loads(texto) if texto else {}
        except ValueError:
            return {}

    def _arredondar(d):
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in d.items()}

    @app.get("/execucoes", response_class=HTMLResponse)
    def execucoes(request: Request):
        if not leitura.existe():
            return sem_banco(request)
        return pagina(request, "execucoes.html", itens=leitura.execucoes())

    @app.get("/execucoes/comparar", response_class=HTMLResponse)
    def comparar(request: Request, a: str = "", b: str = ""):
        if not leitura.existe():
            return sem_banco(request)
        todas = leitura.execucoes()
        ea, eb = (leitura.execucao(a) if a else None), (leitura.execucao(b) if b else None)
        if (a and ea is None) or (b and eb is None):
            return erro(request, 404, "Execução não encontrada", "Uma das execuções escolhidas não existe.")
        diferencas = []
        if ea and eb:
            diferencas = diff_config(mascarar_segredos(_json(ea["config_json"])), mascarar_segredos(_json(eb["config_json"])))
        campos = [("consultas_web_ok", "Consultas web"), ("resultados", "Resultados"), ("urls_unicas", "URLs únicas"),
                  ("pares_url_uf_selecionados", "Páginas selecionadas"), ("paginas_baixadas", "Páginas baixadas"),
                  ("paginas_com_texto", "Páginas com texto"), ("classificacoes", "Classificações"), ("achados", "Achados"),
                  ("achados_evidencia_ok", "Achados com evidência"), ("achados_verificados", "Achados verificados")]
        soma = lambda e: sum((c["custo_usd"] or 0) for c in e["custos"]) if e else 0       # download nao tem custo (nulo)
        return pagina(request, "comparar.html", todas=todas, a=a, b=b, ea=ea, eb=eb, diferencas=diferencas, campos=campos,
                      custo_a=soma(ea), custo_b=soma(eb))

    @app.get("/execucoes/{run_id}", response_class=HTMLResponse)
    def execucao(request: Request, run_id: str):
        if not leitura.existe():
            return sem_banco(request)
        e = leitura.execucao(run_id)
        if e is None:
            return erro(request, 404, "Execução não encontrada", f"Não existe a execução “{run_id[:60]}”.")
        f = e["funil"]
        etapas = [("Consultas web", f.get("consultas_web_ok")), ("Resultados", f.get("resultados")), ("URLs únicas", f.get("urls_unicas")),
                  ("Páginas selecionadas", f.get("pares_url_uf_selecionados")), ("Páginas baixadas", f.get("paginas_baixadas")),
                  ("Páginas com texto", f.get("paginas_com_texto")), ("Classificações", f.get("classificacoes")), ("Achados", f.get("achados")),
                  ("Achados verificados", f.get("achados_verificados"))]
        etapas = [(r, v) for r, v in etapas if v]
        funil = barras_horizontais(etapas, f"Funil da execução {run_id}", "Quantidade em cada etapa desta execução", fmt.numero)
        return pagina(request, "execucao.html", e=e, funil=funil, metricas=_arredondar(_json(e["metricas_json"])),
                      cfg=mascarar_segredos(_json(e["config_json"])), ambiente=mascarar_segredos(_json(e["ambiente_json"])),
                      custo_total=sum((c["custo_usd"] or 0) for c in e["custos"]))

    # ---------- chamadas ----------
    @app.get("/chamadas", response_class=HTMLResponse)
    def chamadas(request: Request):
        if not leitura.existe():
            return sem_banco(request)
        filtros = {k: str(request.query_params[k])[:MAX_BUSCA] for k in FILTROS_CHAMADAS if request.query_params.get(k)}
        n = _inteiro(request.query_params.get("p"), 1)
        if n is None:
            return erro(request, 404, "Página inválida", "O número da página não é válido.")
        res = leitura.chamadas(filtros, n, 50)
        paginas = max((res["total"] + res["por_pagina"] - 1) // res["por_pagina"], 1)
        return pagina(request, "chamadas.html", res=res, filtros=filtros, n=n, paginas=paginas, base=urlencode(filtros),
                      opcoes=leitura.opcoes_chamadas())

    def _extensao(c):
        return (str(c.get("raw_path") or "").rsplit(".", 1)[-1] if "." in str(c.get("raw_path") or "") else "bin")[:8]

    def _bruto(c):
        """Resposta bruta da chamada para exibir: JSON vira arvore (com segredos mascarados); o resto, texto escapado."""
        if not c.get("raw_path"):
            return {"existe": False}
        try:
            dados = bruto.ler(c["raw_path"])
        except (OSError, ValueError):
            return {"existe": False, "aviso": "O arquivo bruto não foi encontrado em data/raw."}
        out = {"existe": True, "tamanho": len(dados), "cortado": len(dados) > LIMITE_BRUTO, "arvore": None, "texto": None}
        amostra = dados[:LIMITE_BRUTO]
        if not out["cortado"]:
            try:
                out["arvore"] = mascarar_segredos(json.loads(dados.decode("utf-8")))
                return out
            except (ValueError, UnicodeDecodeError):
                pass
        if _extensao(c) in ("bin", "pdf") or b"\x00" in amostra[:2000]:
            out["binario"] = True
        else:
            out["texto"] = amostra.decode("utf-8", "replace")
        return out

    @app.get("/chamadas/{chamada_id}", response_class=HTMLResponse)
    def chamada(request: Request, chamada_id: int):
        if not leitura.existe():
            return sem_banco(request)
        c = leitura.chamada(chamada_id)
        if c is None:
            return erro(request, 404, "Chamada não encontrada", f"Não existe a chamada nº {chamada_id}.")
        return pagina(request, "chamada.html", c=c, parametros=mascarar_segredos(_json(c["parametros_json"])),
                      extras=mascarar_segredos(_json(c["extras_json"])), bruto=_bruto(c))

    @app.get("/chamadas/{chamada_id}/bruto")
    def chamada_bruto(request: Request, chamada_id: int):
        c = leitura.chamada(chamada_id) if leitura.existe() else None
        if c is None or not c.get("raw_path"):
            return erro(request, 404, "Arquivo não encontrado", "Esta chamada não tem resposta bruta guardada.")
        try:
            dados = bruto.ler(c["raw_path"])
        except (OSError, ValueError):
            return erro(request, 404, "Arquivo não encontrado", "O arquivo bruto não foi encontrado em data/raw.")
        return Response(dados, media_type="application/octet-stream",
                        headers={"Content-Disposition": f'attachment; filename="chamada_{chamada_id}.{_extensao(c)}"'})

    # ---------- literatura ----------
    def _filtros_artigos(params):
        return {k: str(params[k])[:MAX_BUSCA] for k in FILTROS_ARTIGOS if params.get(k) not in (None, "")}

    @app.get("/literatura", response_class=HTMLResponse)
    def literatura_geral(request: Request):
        if not leitura.existe():
            return sem_banco(request)
        d = leitura.literatura()
        anos = [(str(l["ano"]), l["n_artigos"]) for l in d["por_ano"]]
        grafico_anos = colunas(anos, "Artigos por ano", "Quantidade de artigos únicos encontrados, por ano de publicação", "ano", "artigos")
        termos = [l["termo_id"] for l in d["por_termo"]]
        valores = {(l["termo_a"], l["termo_b"]): l["n_em_comum"] for l in d["sobreposicao"]}
        valores.update({(l["termo_id"], l["termo_id"]): l["n_artigos"] for l in d["por_termo"]})
        calor = mapa_de_calor(termos, valores, "Artigos em comum entre termos", "Cada célula é o número de artigos encontrados pelos dois termos",
                              {t: contexto.termos.get(t, "") for t in termos})
        return pagina(request, "literatura.html", d=d, grafico_anos=grafico_anos, calor=calor, tri=leitura.contagem_triagem(),
                      rel=leitura.contagem_relevancia())

    @app.get("/literatura/artigos", response_class=HTMLResponse)
    def artigos(request: Request):
        if not leitura.existe():
            return sem_banco(request)
        filtros = _filtros_artigos(request.query_params)
        n = _inteiro(request.query_params.get("p"), 1)
        if n is None:
            return erro(request, 404, "Página inválida", "O número da página não é válido.")
        res = leitura.artigos(filtros, n, 50)
        paginas = max((res["total"] + res["por_pagina"] - 1) // res["por_pagina"], 1)
        return pagina(request, "artigos.html", res=res, filtros=filtros, n=n, paginas=paginas, base=urlencode(filtros),
                      marcadores=relev.MARCADORES_BRASIL, marcadores_tema=relev.MARCADORES_TEMA, dominios_br=relev.DOMINIOS_BRASIL_SEM_BR)

    def _query_triagem(request):
        return urlencode({k: v for k, v in request.query_params.items() if k in FILTROS_ARTIGOS or k == "fila"})

    @app.get("/literatura/artigos/{artigo_id}", response_class=HTMLResponse)
    def artigo(request: Request, artigo_id: int, ok: int = 0):
        if not leitura.existe():
            return sem_banco(request)
        a = leitura.artigo(artigo_id)
        if a is None:
            return erro(request, 404, "Artigo não encontrado", f"Não existe o artigo nº {artigo_id} nas buscas do relatório.")
        em_fila = "fila" in request.query_params
        ids = leitura.ids_fila_triagem(_filtros_artigos(request.query_params)) if em_fila else []
        proximo = next((i for i in ids if i != artigo_id), None)
        return pagina(request, "artigo.html", a=a, em_fila=em_fila, restantes=len(ids), proximo=proximo, tri=leitura.contagem_triagem(),
                      query=_query_triagem(request), ok=ok if 0 <= ok <= MAX_PAGINA * 1000 else 0)

    @app.get("/literatura/triagem", response_class=HTMLResponse)
    def fila_triagem(request: Request):
        if not leitura.existe():
            return sem_banco(request)
        filtros = _filtros_artigos(request.query_params)
        ids = leitura.ids_fila_triagem(filtros)
        if ids:
            return RedirectResponse("/literatura/artigos/%d?%s" % (ids[0], urlencode({**filtros, "fila": 1})), status_code=303)
        return pagina(request, "triagem_vazia.html", tri=leitura.contagem_triagem(), filtros=filtros)

    @app.post("/literatura/artigos/{artigo_id}/triar")
    def triar(request: Request, artigo_id: int, decisao: str = Form(""), revisor: str = Form(""), motivo: str = Form(""),
              base: str = Form(""), link: str = Form(""), etapa: str = Form("titulo_resumo"), versao: str = Form(None),
              csrf: str = Form("")):
        bloqueio = checar_escrita(request, csrf)
        if bloqueio:
            return bloqueio
        if leitura.artigo(artigo_id) is None:
            return erro(request, 404, "Artigo não encontrado", f"Não existe o artigo nº {artigo_id}.")
        if base and contexto.bases and base not in contexto.bases:
            return erro(request, 400, "Decisão não gravada", f"Base desconhecida: {base[:60]}")
        try:
            _escrever(lambda repo: revisao.decidir_triagem(repo, artigo_id, decisao, revisor, motivo, base, link, etapa, versao))
        except SystemExit as e:
            return erro(request, 409 if _conflito(str(e)) else 400, "Artigo alterado" if _conflito(str(e)) else "Decisão não gravada", str(e))
        if "fila" in request.query_params:
            filtros = _filtros_artigos(request.query_params)
            ids = leitura.ids_fila_triagem(filtros)
            proximo = next((i for i in ids if i != artigo_id), None)
            destino = ("/literatura/artigos/%d?%s&ok=%d" % (proximo, urlencode({**filtros, "fila": 1}), artigo_id) if proximo
                       else "/literatura/triagem?" + urlencode(filtros))
        else:
            destino = "/literatura/artigos/%d?ok=%d" % (artigo_id, artigo_id)
        resposta = RedirectResponse(destino, status_code=303)
        resposta.set_cookie("revisor", quote(revisor.strip()), max_age=31_536_000, samesite="strict")
        return resposta

    @app.get("/literatura/prisma", response_class=HTMLResponse)
    def prisma(request: Request):
        if not leitura.existe():
            return sem_banco(request)
        d = leitura.prisma()
        fases = {}
        for c in d["caixas"]:
            fases.setdefault(c["fase"], []).append(c)
        valores = {c["metrica"]: c["valor"] for c in d["caixas"]}
        informados = valores.get("buscas manuais: selecionados (contagem informada)")
        importados = valores.get("buscas manuais: artigos importados (por base)")
        aviso_manual = None
        if d["n_buscas_manuais"] and informados is not None and importados is not None and informados != importados:
            aviso_manual = (informados, importados)
        return pagina(request, "prisma.html", d=d, fases=fases, aviso_manual=aviso_manual)

    # ---------- achados ----------
    @app.get("/achados", response_class=HTMLResponse)
    def achados(request: Request):
        if not leitura.existe():
            return sem_banco(request)
        filtros = _filtros(request.query_params)
        n = _inteiro(request.query_params.get("p"), 1)
        if n is None:
            return erro(request, 404, "Página inválida", "O número da página não é válido.")
        res = leitura.achados(filtros, n, 50)
        paginas = max((res["total"] + res["por_pagina"] - 1) // res["por_pagina"], 1)
        base = urlencode(filtros)
        return pagina(request, "achados.html", res=res, filtros=filtros, paginas=paginas, base=base, n=n,
                      cidades=leitura.cidades())

    def _texto_enviado(a):
        """Texto que foi enviado ao classificador: a pagina extraida (cortada no que foi enviado) ou titulo + snippet."""
        aviso = None
        if a["origem_texto"] == "pagina" and a["texto_path"]:
            try:
                texto = bruto.ler(a["texto_path"]).decode("utf-8", "replace")
            except (OSError, ValueError):
                texto, aviso = "", "O arquivo do texto extraído não foi encontrado em data/raw."
        else:
            texto = f"{a['titulo'] or ''}\n{a['snippet'] or ''}"
        if a["n_chars_enviados"]:
            texto = texto[:a["n_chars_enviados"]]
        return texto[:LIMITE_TEXTO], aviso

    def _contexto_evidencia(a, completo):
        texto, aviso = _texto_enviado(a)
        par = localizar_evidencia(a["evidencia"], texto)
        aprox = None
        if par is None:
            aprox = trecho_mais_parecido(a["evidencia"], texto)
            par = aprox[:2] if aprox else None
        out = {"aviso": aviso, "encontrada": aprox is None and par is not None, "similaridade": aprox[2] if aprox else None,
               "n_texto": len(texto), "recortado": False, "antes": texto, "trecho": "", "depois": ""}
        if par:
            ini, fim = par
            a0, b0 = (0, len(texto)) if completo else (max(ini - JANELA_CONTEXTO, 0), min(fim + JANELA_CONTEXTO, len(texto)))
            out.update(antes=texto[a0:ini], trecho=texto[ini:fim], depois=texto[fim:b0], recortado=(a0 > 0 or b0 < len(texto)),
                       prefixo=a0 > 0, sufixo=b0 < len(texto))
        elif len(texto) > 4000 and not completo:
            out.update(antes=texto[:4000], recortado=True, sufixo=True)
        return out

    def _query_fila(request):
        q = {k: v for k, v in request.query_params.items() if k in FILTROS or k == "fila"}
        return urlencode(q)

    def _proximo(ids, atual):
        if not ids:
            return None
        if atual in ids:
            i = ids.index(atual)
            return ids[(i + 1) % len(ids)] if len(ids) > 1 else None
        return ids[0]

    @app.get("/achados/{achado_id}", response_class=HTMLResponse)
    def achado(request: Request, achado_id: int, completo: int = 0, ok: int = 0):
        ok = ok if 0 <= ok <= MAX_PAGINA * 1000 else 0
        if not leitura.existe():
            return sem_banco(request)
        a = leitura.achado(achado_id)
        if a is None:
            return erro(request, 404, "Achado não encontrado", f"Não existe o achado nº {achado_id}.")
        em_fila = "fila" in request.query_params
        ids = leitura.ids_fila_revisao(_filtros(request.query_params)) if em_fila else []
        rev = leitura.contagem_revisao()
        proximo = _proximo(ids, achado_id)
        return pagina(request, "achado.html", a=a, ev=_contexto_evidencia(a, bool(completo)), completo=bool(completo),
                      historico=leitura.historico_achado(achado_id), em_fila=em_fila, rev=rev, proximo=proximo,
                      query=_query_fila(request), ok=ok, restantes=len(ids),
                      pode_desfazer=leitura.tem_decisao_para_desfazer(achado_id),
                      status_opcoes=[(k, contexto.status_definicoes[k]) for k in contexto.status_definicoes])

    @app.get("/revisao/achados", response_class=HTMLResponse)
    def fila(request: Request):
        if not leitura.existe():
            return sem_banco(request)
        filtros = _filtros(request.query_params)
        ids = leitura.ids_fila_revisao(filtros)
        if ids:
            return RedirectResponse("/achados/%d?%s" % (ids[0], urlencode({**filtros, "fila": 1})), status_code=303)
        return pagina(request, "fila_vazia.html", rev=leitura.contagem_revisao(), filtros=filtros)

    def _voltar(request, achado_id, ok=None):
        filtros = _filtros(request.query_params)
        ids = leitura.ids_fila_revisao(filtros)
        q = urlencode({**filtros, "fila": 1})
        if ids:
            return "/achados/%d?%s&ok=%d" % (ids[0], q, ok or 0)
        return "/revisao/achados?" + urlencode(filtros)

    def _antes_de_escrever():
        """Copia de seguranca uma vez por sessao do painel, antes da primeira gravacao."""
        if not contexto.backup_feito:
            repo = repositorio_fabrica()
            try:
                repo.copia_de_seguranca(contexto.pasta_backup)
            finally:
                repo.fechar()
            contexto.backup_feito = True

    def _escrever(acao):
        _antes_de_escrever()
        repo = repositorio_fabrica()
        try:
            acao(repo)
        finally:
            repo.fechar()

    def _conflito(texto):
        return "mudou depois" in texto or "alterado depois" in texto

    @app.post("/achados/{achado_id}/verificar")
    def verificar(request: Request, achado_id: int, status_final: str = Form(""), revisor: str = Form(""),
                  observacao: str = Form(""), versao: str = Form(None), csrf: str = Form("")):
        bloqueio = checar_escrita(request, csrf)
        if bloqueio:
            return bloqueio
        if leitura.achado(achado_id) is None:
            return erro(request, 404, "Achado não encontrado", f"Não existe o achado nº {achado_id}.")
        try:
            _escrever(lambda repo: revisao.verificar_achado(repo, achado_id, status_final, revisor, observacao,
                                                            contexto.status_permitidos, versao))
        except SystemExit as e:
            if _conflito(str(e)):
                return erro(request, 409, "Achado alterado", str(e))
            return erro(request, 400, "Decisão não gravada", str(e))
        destino = (_voltar(request, achado_id, achado_id) if "fila" in request.query_params
                   else "/achados/%d?ok=%d" % (achado_id, achado_id))
        resposta = RedirectResponse(destino, status_code=303)
        resposta.set_cookie("revisor", quote(revisor.strip()), max_age=31_536_000, samesite="strict")
        return resposta

    @app.post("/achados/{achado_id}/desfazer")
    def desfazer(request: Request, achado_id: int, csrf: str = Form("")):
        bloqueio = checar_escrita(request, csrf)
        if bloqueio:
            return bloqueio
        try:
            _escrever(lambda repo: revisao.desfazer_decisao(repo, achado_id))
        except SystemExit as e:
            return erro(request, 409 if _conflito(str(e)) else 400, "Não foi possível desfazer", str(e))
        return RedirectResponse("/achados/%d?%s" % (achado_id, _query_fila(request)), status_code=303)

    @app.post("/achados/{achado_id}/revogar")
    def revogar(request: Request, achado_id: int, revisor: str = Form(""), motivo: str = Form(""),
                versao: str = Form(None), csrf: str = Form("")):
        bloqueio = checar_escrita(request, csrf)
        if bloqueio:
            return bloqueio
        if leitura.achado(achado_id) is None:
            return erro(request, 404, "Achado não encontrado", f"Não existe o achado nº {achado_id}.")
        try:
            _escrever(lambda repo: revisao.revogar_verificacao(repo, achado_id, revisor, motivo, versao))
        except SystemExit as e:
            return erro(request, 409 if _conflito(str(e)) else 400, "Verificação não revogada", str(e))
        resposta = RedirectResponse("/achados/%d?%s" % (achado_id, _query_fila(request)), status_code=303)
        resposta.set_cookie("revisor", quote(revisor.strip()), max_age=31_536_000, samesite="strict")
        return resposta

    from painel import rotas_extras
    rotas_extras.registrar_todas(SimpleNamespace(app=app, leitura=leitura, bruto=bruto, contexto=contexto, modelos=modelos,
                                                 pagina=pagina, erro=erro, sem_banco=sem_banco, checar_escrita=checar_escrita))
    return app
