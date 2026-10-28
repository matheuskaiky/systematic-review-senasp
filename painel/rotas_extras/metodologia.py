"""Pagina Metodologia: texto em portugues gerado dos dados, com cada numero ligado a pagina que o justifica."""
from fastapi import Request
from fastapi.responses import HTMLResponse

from painel import metodologia_texto


def registrar(c):
    app, leitura, contexto = c.app, c.leitura, c.contexto

    @app.get("/metodologia", response_class=HTMLResponse)
    def metodologia(request: Request):
        if not leitura.existe():
            return c.sem_banco(request)
        fatos = leitura.fatos_metodologia(len(contexto.ufs) or 27)
        fatos["bases_esperadas"] = list(contexto.bases)
        fatos["banco"] = contexto.banco
        custos = "ver_custos" in c.perms(request)
        return c.pagina(request, "metodologia.html",
                        m=metodologia_texto.filtrar_links(metodologia_texto.gerar_metodologia(fatos, contexto.ufs, custos=custos),
                                                         c.pode_seguir(request)))
