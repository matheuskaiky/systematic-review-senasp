"""Rotas acrescentadas em modulos proprios. Cada modulo expoe `registrar(c)`, onde `c` traz o que as rotas de `app.py`
usam: app, leitura, bruto, contexto, modelos (Jinja2Templates), pagina(request, modelo, status=200, **dados),
erro(request, status, titulo, texto), sem_banco(request), checar_escrita(request, csrf) e contas."""
from painel.rotas_extras import admin, analises, classificadores, metodologia, sobre, solucoes, triagem_escopo


def registrar_todas(c):
    for modulo in (admin, analises, classificadores, metodologia, sobre, solucoes, triagem_escopo):
        modulo.registrar(c)
