"""Pagina "Sobre os dados": glossario de metricas, status e motivos (conteudo em painel/glossario.py)."""
from fastapi import Request
from fastapi.responses import HTMLResponse

from painel import glossario


def registrar(c):
    """Registra GET /sobre em c.app. A pagina nao le o banco: funciona tambem sem ele."""

    @c.app.get("/sobre", response_class=HTMLResponse)
    def sobre(request: Request):
        return c.pagina(request, "sobre.html", secoes=glossario.SECOES)
