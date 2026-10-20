"""Menu lateral do painel: três grupos de links, na ordem em que o pesquisador trabalha.

Só apresentação: nenhuma rota é criada ou removida aqui. `grupos(caminho, em_fila)` devolve, para o caminho da página atual, os
grupos com cada link marcado como atual (vira `aria-current="page"`) e o grupo que contém a página atual marcado como aberto.
Um achado ou um artigo aberto pela fila de revisão (`?fila=1`) marca a fila ("Revisar achados", "Triar artigos"), não a lista.
"""

# (endereço, texto, prefixo que também marca o link como atual, prefixos de outro link que NÃO contam)
_GRUPOS = (
    ("revisao", "Revisão sistemática", (
        ("/", "Visão geral", None, ()),
        ("/literatura/prisma", "PRISMA", "/literatura/prisma", ()),
        ("/estados", "Estados", "/estados", ()),
        ("/achados", "Achados", "/achados", ()),
        ("/revisao/achados", "Revisar achados", "/revisao", ()),
        ("/literatura/artigos", "Artigos", "/literatura/artigos", ()),
        ("/literatura", "Visão da literatura", None, ()),
        ("/literatura/triagem", "Triar artigos", "/literatura/triagem", ()),
    )),
    ("analises", "Análises e qualidade", (
        ("/analises", "Análises", "/analises", ()),
        ("/triagem-escopo", "Triagem de escopo (LLM)", "/triagem-escopo", ()),
        ("/classificadores", "Classificadores", "/classificadores", ()),
        # sem parâmetros a página é o seletor de duas execuções (responde 200), então o link direto está certo
        ("/execucoes/comparar", "Comparar execuções", "/execucoes/comparar", ()),
        ("/solucoes", "Soluções conhecidas", "/solucoes", ()),
    )),
    ("auditoria", "Auditoria e operação", (
        ("/buscar-texto", "Buscar no texto", "/buscar-texto", ()),
        ("/execucoes", "Execuções", "/execucoes", ("/execucoes/comparar",)),
        ("/chamadas", "Chamadas", "/chamadas", ()),
        ("/metodologia", "Metodologia", "/metodologia", ()),
        ("/sobre", "Sobre os dados", "/sobre", ()),
    )),
)


def _sob(caminho, prefixo):
    return caminho == prefixo or caminho.startswith(prefixo + "/")


def _atual(caminho, href, prefixo, excecoes):
    if caminho == href:
        return True
    return bool(prefixo) and _sob(caminho, prefixo) and not any(_sob(caminho, e) for e in excecoes)


# só para administradores: as telas de administração (antes só pelo link "Administração" do topo)
_ADMIN = ("administracao", "Administração", (
    ("/admin/usuarios", "Usuários", "/admin/usuarios", ()),
    ("/admin/grupos", "Permissões por grupo", "/admin/grupos", ()),
    ("/admin/auditoria", "Registro de administração", "/admin/auditoria", ()),
    ("/estatisticas-usuarios", "Atividade dos revisores", "/estatisticas-usuarios", ()),
))

# na fila de revisão, a página de um item conta como a página da fila
_FILAS = (("/achados", "/revisao/achados"), ("/literatura/artigos", "/literatura/triagem"))


def grupos(caminho, em_fila=False, admin=False):
    """Lista de {id, nome, aberto, itens: [{href, texto, atual}]} para o `caminho` (ex.: `/estados/SP`) da página atual."""
    caminho = (caminho.rstrip("/") or "/") if caminho else ""          # sem caminho conhecido: nenhum link atual
    if em_fila:
        caminho = next((fila for lista, fila in _FILAS if _sob(caminho, lista)), caminho)
    saida = []
    for id_, nome, itens in _GRUPOS + ((_ADMIN,) if admin else ()):
        marcados = [{"href": h, "texto": t, "atual": _atual(caminho, h, p, ex)} for h, t, p, ex in itens]
        saida.append({"id": id_, "nome": nome, "aberto": any(i["atual"] for i in marcados), "itens": marcados})
    return saida


def enderecos():
    """Todos os endereços linkados no menu (para os testes conferirem que nenhuma rota ficou de fora)."""
    return [h for _, _, itens in _GRUPOS for h, *_ in itens]
