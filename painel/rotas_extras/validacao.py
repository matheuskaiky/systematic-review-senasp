"""Validacao humana da triagem do banco `vies` por amostra (RB34). So no banco `vies`.

/validacao: a amostra (sorteada uma vez, por quem administra), o andamento e, com tudo respondido, a concordancia entre a
pessoa e o modelo. /validacao/{ordem}: um item, com titulo, trecho e endereco, e o formulario; a resposta do modelo nunca
aparece antes de a amostra inteira estar respondida."""
from urllib.parse import quote

from fastapi import Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from dominio import validacao_vies as VV
from painel import visao_geral_vies
from painel.app import IdDoBanco


def registrar(c):
    app, leitura, contexto = c.app, c.leitura, c.contexto

    def _so_vies(request):
        if contexto.banco != "vies":
            return c.erro(request, 404, "Página não encontrada", "A validação da triagem existe só no banco vies.")
        if not leitura.existe():
            return c.sem_banco(request)
        return None

    def _eixos():
        return tuple(contexto.eixos_exploracao)

    @app.get("/validacao", response_class=HTMLResponse)
    def validacao(request: Request):
        fora = _so_vies(request)
        if fora:
            return fora
        linhas = leitura.linhas_validacao_vies()
        respondidas = sum(1 for l in linhas if l["relevancia"])
        completa = bool(linhas) and respondidas == len(linhas)
        resultado = VV.concordancia(linhas, _eixos()) if completa else None
        return c.pagina(request, "validacao.html", linhas=linhas, respondidas=respondidas, completa=completa,
                        resultado=resultado, tamanho=VV.TAMANHO, rotulos=VV.ROTULOS)

    @app.post("/validacao/sortear")
    def sortear(request: Request, csrf: str = Form("")):
        fora = _so_vies(request)
        if fora:
            return fora
        bloqueio = c.checar_escrita(request, csrf)
        if bloqueio:
            return bloqueio
        with leitura.instantaneo() as l:
            linhas = VV.sortear(visao_geral_vies.itens(l, contexto), l.triagens_vies(contexto.versao_triagem_vies),
                                _eixos())
        try:
            c.escrever(lambda repo: repo.sortear_validacao_vies(linhas))
        except SystemExit as e:
            return c.erro(request, 409, "Amostra não sorteada", str(e))
        return RedirectResponse("/validacao", status_code=303)

    def _item(request, ordem, status=200, erros=(), valores=None):
        linhas = leitura.linhas_validacao_vies()
        linha = next((l for l in linhas if l["ordem"] == ordem), None)
        if linha is None:
            return c.erro(request, 404, "Item não encontrado", f"A amostra não tem o item nº {ordem}.")
        valores = valores if valores is not None else {k: linha[k] for k in VV.CAMPOS}
        pendente = next((l["ordem"] for l in linhas if not l["relevancia"] and l["ordem"] != ordem), None)
        return c.pagina(request, "validacao_item.html", status=status, item=linha, total=len(linhas), valores=valores,
                        erros=list(erros), opcoes=VV.opcoes(_eixos()), rotulos=VV.ROTULOS, proximo_pendente=pendente,
                        eixos=dict(contexto.eixos_exploracao))

    @app.get("/validacao/{ordem}", response_class=HTMLResponse)
    def item(request: Request, ordem: IdDoBanco):
        fora = _so_vies(request)
        return fora or _item(request, ordem)

    @app.post("/validacao/{ordem}/triar")
    def responder(request: Request, ordem: IdDoBanco, relevancia: str = Form(""), grupo: str = Form(""), eixo: str = Form(""),
                  pais: str = Form(""), revisor: str = Form(""), csrf: str = Form("")):
        fora = _so_vies(request)
        if fora:
            return fora
        bloqueio = c.checar_escrita(request, csrf)
        if bloqueio:
            return bloqueio
        valores = {"relevancia": relevancia, "grupo": grupo, "eixo": eixo, "pais": pais}
        resposta, erros = VV.conferir_resposta(valores, _eixos())
        usuario = getattr(request.state, "usuario", None)
        if usuario:
            revisor = usuario["nome"]
        if not revisor.strip():
            erros.append("Informe o nome do revisor.")
        if erros:
            return _item(request, ordem, status=400, erros=erros, valores=valores)
        try:
            c.escrever(lambda repo: repo.responder_validacao_vies(ordem, resposta, revisor))
        except SystemExit as e:
            if "inexistente" in str(e):
                return c.erro(request, 404, "Item não encontrado", f"A amostra não tem o item nº {ordem}.")
            if "concluída" in str(e) or "outra pessoa" in str(e):
                return c.erro(request, 409, "Resposta não gravada", str(e))
            return c.erro(request, 400, "Resposta não gravada", str(e))
        pendente = next((l["ordem"] for l in leitura.linhas_validacao_vies() if not l["relevancia"]), None)
        resposta_http = RedirectResponse(f"/validacao/{pendente}" if pendente else "/validacao", status_code=303)
        if not usuario:
            resposta_http.set_cookie("revisor", quote(revisor.strip()), max_age=31_536_000, samesite="strict")
        return resposta_http
