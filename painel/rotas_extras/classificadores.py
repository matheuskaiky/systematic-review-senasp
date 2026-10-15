"""Pagina Classificadores: concordancia entre duas execucoes de classificacao sobre as mesmas paginas (secao 12.2)."""
from fastapi import Request
from fastapi.responses import HTMLResponse

from dominio.concordancia import comparar_classificacoes

MAX_RUN_ID = 120
LIMITE_DIVERGENCIAS = 100


def registrar(c):
    app, leitura = c.app, c.leitura

    @app.get("/classificadores", response_class=HTMLResponse)
    def classificadores(request: Request, a: str = "", b: str = ""):
        if not leitura.existe():
            return c.sem_banco(request)
        a, b = a.strip()[:MAX_RUN_ID], b.strip()[:MAX_RUN_ID]
        execucoes = leitura.execucoes_classificacao()
        base = dict(execucoes=execucoes, a=a, b=b, ea=None, eb=None, r=None, aviso=None, limite=LIMITE_DIVERGENCIAS)
        if not a and not b:
            return c.pagina(request, "classificadores.html", **base)
        ea, eb = (leitura.execucao_classificacao(x) if x else None for x in (a, b))
        if (a and ea is None) or (b and eb is None):
            return c.erro(request, 404, "Execução não encontrada",
                          "Uma das execuções escolhidas não existe ou não é uma execução de classificação.")
        if not (a and b):
            return c.pagina(request, "classificadores.html", **{**base, "aviso": "Escolha as duas execuções para comparar."})
        if a == b:
            return c.pagina(request, "classificadores.html", **{**base, "aviso": "Escolha duas execuções diferentes: "
                            "uma execução comparada consigo mesma sempre concorda em tudo."})
        r = comparar_classificacoes(leitura.classificacoes_para_comparar(a), leitura.achados_para_comparar(a),
                                    leitura.classificacoes_para_comparar(b), leitura.achados_para_comparar(b))
        aviso = None
        if not r["pares"]["ambas"]:
            aviso = ("As duas execuções não têm nenhuma página em comum (mesma URL e mesma UF), então não há o que comparar. "
                     "Para comparar dois modelos, rode classificar duas vezes com o mesmo --de.")
        return c.pagina(request, "classificadores.html", **{**base, "ea": ea, "eb": eb, "r": r, "aviso": aviso})
