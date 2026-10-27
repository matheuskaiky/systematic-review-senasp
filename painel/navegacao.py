"""Menu lateral do painel: três grupos de links, na ordem em que o pesquisador trabalha.

Só apresentação: nenhuma rota é criada ou removida aqui. `grupos(caminho, em_fila)` devolve, para o caminho da página atual, os
grupos com cada link marcado como atual (vira `aria-current="page"`) e o grupo que contém a página atual marcado como aberto.
Um achado ou um artigo aberto pela fila de revisão (`?fila=1`) marca a fila ("Revisar achados", "Triar artigos"), não a lista.
"""
from urllib.parse import unquote, urlsplit

# (endereço, texto, prefixo que também marca o link como atual, prefixos de outro link que NÃO contam)
_GRUPOS = (
    ("revisao", "Revisão sistemática", (
        ("/", "Visão geral", None, ()),
        ("/literatura/prisma", "PRISMA", "/literatura/prisma", ()),
        ("/estados", "Estados", "/estados", ()),
        ("/achados", "Achados", "/achados", ()),
        ("/revisao/achados", "Revisar achados", "/revisao", ()),
        ("/literatura/artigos", "Artigos", "/literatura/artigos", ()),
        ("/literatura/referencias", "Referências", "/literatura/referencias", ()),
        ("/literatura", "Visão da literatura", None, ()),
        ("/literatura/triagem", "Triar artigos", "/literatura/triagem", ()),
    )),
    ("analises", "Análises e qualidade", (
        ("/observatorio", "Observatório", "/observatorio", ()),
        ("/analises", "Análises", "/analises", ()),
        ("/triagem-escopo", "Triagem de escopo (LLM)", "/triagem-escopo", ()),
        ("/validacao", "Validação da triagem", "/validacao", ()),
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

# as telas só da Tarefa 1 (secretarias, páginas baixadas e achados): saem do menu no banco `vies`; as rotas continuam no ar
SO_TAREFA_1 = frozenset({"/estados", "/achados", "/revisao/achados", "/classificadores", "/execucoes/comparar", "/solucoes",
                         "/buscar-texto"})

# as telas só do banco `vies`: saem do menu nos outros bancos
SO_VIES = frozenset({"/validacao", "/observatorio"})

# na fila de revisão, a página de um item conta como a página da fila
_FILAS = (("/achados", "/revisao/achados"), ("/literatura/artigos", "/literatura/triagem"))

# ações que cada fila exige além de abrir a página (decisão de triagem ou de revisão)
ACOES_DOS_ITENS = {
    "/literatura/triagem": ("POST", "/literatura/artigos/1/triar"),
    "/revisao/achados": ("POST", "/achados/1/verificar"),
}


def pode_seguir(href, pode):
    """Informa se o usuário tem permissão para seguir o endereço dado.

    Aceita apenas caminhos internos absolutos (começando com `/` e não `//`). Decodifica percent-escapes
    e ignora parâmetros ou âncoras. Consulta primeiro o método GET e, para filas de decisão, a ação
    exigida em ACOES_DOS_ITENS.
    """
    if not isinstance(href, str) or not href.startswith("/") or href.startswith("//"):
        return False
    caminho = unquote(urlsplit(href).path)
    if not pode("GET", caminho):
        return False
    if caminho in ACOES_DOS_ITENS:
        return bool(pode(*ACOES_DOS_ITENS[caminho]))
    return True


def grupos(caminho, em_fila=False, admin=False, banco="real", pode=None):
    """Lista de {id, nome, aberto, itens: [{href, texto, atual}]} para o `caminho` (ex.: `/estados/SP`) da página atual.
    No banco `vies`, sem as telas de `SO_TAREFA_1`; nos outros, sem as de `SO_VIES`. Com `pode`, filtra por permissão."""
    caminho = (caminho.rstrip("/") or "/") if caminho else ""          # sem caminho conhecido: nenhum link atual
    if em_fila:
        caminho = next((fila for lista, fila in _FILAS if _sob(caminho, lista)), caminho)
    saida = []
    for id_, nome, itens in _GRUPOS + ((_ADMIN,) if admin else ()):
        marcados = []
        for h, t, p, ex in itens:
            if banco == "vies" and h in SO_TAREFA_1:
                continue
            if banco != "vies" and h in SO_VIES:
                continue
            if pode is not None and not pode_seguir(h, pode):
                continue
            marcados.append({"href": h, "texto": t, "atual": _atual(caminho, h, p, ex)})
        if pode is not None and not marcados:
            continue
        saida.append({"id": id_, "nome": nome, "aberto": any(i["atual"] for i in marcados), "itens": marcados})
    return saida


def enderecos():
    """Todos os endereços linkados no menu (para os testes conferirem que nenhuma rota ficou de fora)."""
    return [h for _, _, itens in _GRUPOS for h, *_ in itens]
