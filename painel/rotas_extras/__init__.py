"""Rotas acrescentadas em modulos proprios. Cada modulo expoe `registrar(c)`, onde `c` traz o que as rotas de `app.py`
usam: app, leitura, bruto, contexto, modelos (Jinja2Templates), pagina(request, modelo, status=200, **dados),
erro(request, status, titulo, texto), sem_banco(request), checar_escrita(request, csrf), contas, contas_ocupadas(request)
(a resposta 503 do banco de contas ocupado), novo_repositorio() (uma conexao de gravacao nova) e escrever(acao) (a copia
de seguranca da sessao antes da primeira gravacao e `acao(repo)` numa conexao nova, fechada no fim)."""
from painel.rotas_extras import admin, analises, api, classificadores, conta, metodologia, observatorio, sobre, solucoes, triagem_escopo, validacao


def registrar_todas(c):
    for modulo in (admin, analises, api, classificadores, conta, metodologia, observatorio, sobre, solucoes, triagem_escopo, validacao):
        modulo.registrar(c)
