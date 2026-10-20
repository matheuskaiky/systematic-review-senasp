"""Página "Minha conta": os dados do usuário e o token de envio da coleta local para a nuvem (D98). O token aparece uma
única vez, na resposta que o gera (nunca em endereço, cookie ou registro); o banco guarda só o hash e o começo dele."""
from datetime import datetime, timezone

from fastapi import Form, Request
from starlette.responses import RedirectResponse

from dominio import autenticacao

AVISOS = {"revogado": "Token revogado: ele não envia mais nada.", "sem-token": "Você não tinha token ativo."}


def registrar(c) -> None:
    if not c.contexto.autenticacao:
        return
    app = c.app

    def _sem_cache(resposta):
        """Toda resposta das rotas da conta (pagina, erro, recusa e redirecionamento) sai sem cache."""
        resposta.headers["Cache-Control"] = "no-store"
        return resposta

    def _ocupado(request):
        return _sem_cache(c.contas_ocupadas(request))

    def _pagina(request, status=200, token_novo=None, aviso=None, token=False):
        """`token` False: le o token do banco; na resposta que o gera, vem pronto (sem nova leitura que, falhando,
        esconderia um token ja gravado)."""
        u = request.state.usuario
        if token is False:
            try:
                token = c.contas.token_do_usuario(u["usuario_id"])
            except autenticacao.ContasOcupadas:
                return _ocupado(request)
        resposta = c.pagina(request, "conta.html", status=status, conta=u, token=token, token_novo=token_novo, aviso=aviso,
                            pode_enviar="enviar_coletas" in request.state.perms)
        return _sem_cache(resposta)                              # a resposta que gera o token o mostra uma vez

    @app.get("/conta")
    def conta_view(request: Request):
        return _pagina(request, aviso=AVISOS.get(request.query_params.get("ok", "")))

    @app.post("/conta/token")
    def gerar_token_view(request: Request, csrf: str = Form("")):
        bloqueio = c.checar_escrita(request, csrf)
        if bloqueio:
            return _sem_cache(bloqueio)
        u = request.state.usuario
        token = autenticacao.gerar_token_api()
        agora = datetime.now(timezone.utc).isoformat()
        try:
            c.contas.gravar_token(u["usuario_id"], autenticacao.hash_token(token), autenticacao.inicio_do_token(token), agora,
                                  auditoria=(u["login"], "gerar_token", u["login"], None, agora))
        except autenticacao.ContasOcupadas:
            return _ocupado(request)
        except ValueError:                                       # a conta foi desativada depois de abrir a pagina
            return _sem_cache(c.erro(request, 403, "Conta desativada", "Esta conta foi desativada e não pode ter token."))
        return _pagina(request, token_novo=token,
                       token={"inicio": autenticacao.inicio_do_token(token), "criado_em": agora, "ultimo_uso": None})

    @app.post("/conta/token/revogar")
    def revogar_token_view(request: Request, csrf: str = Form("")):
        bloqueio = c.checar_escrita(request, csrf)
        if bloqueio:
            return _sem_cache(bloqueio)
        u = request.state.usuario
        agora = datetime.now(timezone.utc).isoformat()
        try:
            apagou = c.contas.revogar_token(u["usuario_id"], auditoria=(u["login"], "revogar_token", u["login"], None, agora))
        except autenticacao.ContasOcupadas:
            return _ocupado(request)
        return _sem_cache(RedirectResponse("/conta?ok=" + ("revogado" if apagou else "sem-token"), status_code=303))
