"""Painel de resultados (FastAPI + Jinja2, HTML no servidor). Recebe leitura, fabrica de repositorio e armazenamento
bruto por parametro; nao importa adaptadores, composicao, sqlite3, requests nem le o ambiente."""
import hmac
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, unquote, urlencode

from fastapi import FastAPI, Form, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from aplicacao import revisao
from dominio.servicos_painel import localizar_evidencia, trecho_mais_parecido
from painel import formatacao as fmt, rotulos
from painel.graficos import barra_empilhada, barras_horizontais, mapa_de_blocos

AQUI = Path(__file__).parent
CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
       "base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
FILTROS = ("uf", "tecnologia", "status", "confianca", "evidencia", "oficial", "origem", "verificacao", "q")
JANELA_CONTEXTO = 2500            # caracteres de cada lado da evidencia na visao resumida
LIMITE_TEXTO = 200_000            # o visor nunca mostra mais que isto


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
    backup_feito: bool = field(default=False)


def _filtros(params):
    return {k: params[k] for k in FILTROS if params.get(k) not in (None, "")}


def criar_app(leitura, repositorio_fabrica, bruto, contexto):
    app = FastAPI(title="Painel de resultados", docs_url=None, redoc_url=None, openapi_url=None)
    modelos = Jinja2Templates(directory=str(AQUI / "templates"))
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

    def pagina(request, modelo, status=200, **dados):
        revisor = unquote(request.cookies.get("revisor", ""))
        return modelos.TemplateResponse(request, modelo, {"revisor": revisor, "csrf": request.state.csrf,
                                                        "caminho": request.url.path, **dados}, status_code=status)

    def erro(request, status, titulo, texto):
        return pagina(request, "erro.html", status=status, titulo=titulo, texto=texto)

    def sem_banco(request):
        return pagina(request, "sem_banco.html", status=503)

    def checar_escrita(request, csrf):
        if contexto.somente_leitura:
            return erro(request, 403, "Modo somente leitura", "O painel foi iniciado com --somente-leitura; nenhuma decisão é gravada.")
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

    # ---------- achados ----------
    @app.get("/achados", response_class=HTMLResponse)
    def achados(request: Request):
        if not leitura.existe():
            return sem_banco(request)
        filtros = _filtros(request.query_params)
        n = max(int(request.query_params.get("p", 1) or 1), 1)
        res = leitura.achados(filtros, n, 50)
        paginas = max((res["total"] + res["por_pagina"] - 1) // res["por_pagina"], 1)
        base = urlencode(filtros)
        return pagina(request, "achados.html", res=res, filtros=filtros, paginas=paginas, base=base, n=n)

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

    @app.post("/achados/{achado_id}/verificar")
    def verificar(request: Request, achado_id: int, status_final: str = Form(""), revisor: str = Form(""),
                  observacao: str = Form(""), csrf: str = Form("")):
        bloqueio = checar_escrita(request, csrf)
        if bloqueio:
            return bloqueio
        if leitura.achado(achado_id) is None:
            return erro(request, 404, "Achado não encontrado", f"Não existe o achado nº {achado_id}.")
        try:
            _escrever(lambda repo: revisao.verificar_achado(repo, achado_id, status_final, revisor, observacao,
                                                            contexto.status_permitidos))
        except SystemExit as e:
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
            return erro(request, 400, "Nada a desfazer", str(e))
        return RedirectResponse("/achados/%d?%s" % (achado_id, _query_fila(request)), status_code=303)

    return app
