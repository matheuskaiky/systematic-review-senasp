"""Blocos da pagina /analises sobre as ferramentas de cada etapa (buscas, download, classificacao, triagem), em qualquer
banco: quanto cada ferramenta trouxe, quanto se aproveitou e quanto custou. Funcoes puras sobre
`dominio.analises_ferramentas.linhas`."""
from painel import formatacao as fmt, graficos, graficos_analises as g, rotulos
from painel.analises_blocos import _bloco, _pct

MARGEM_ROTULOS = 285
MAX_ROTULO = 40               # 'triagem de escopo · gemini:modelo' e cortado; o inteiro fica na dica


def _usd(v):
    return fmt.moeda_usd(v) if v else "—"


def _num(v):
    return fmt.numero(v) if v is not None else "—"


def _razao(v, casas=2):
    return f"{v:.{casas}f}".replace(".", ",") if v is not None else "—"


def _nome(l):
    return f"{rotulos.ETAPAS.get(l['etapa'], l['etapa'])} · {l['ferramenta']}"


def bloco_ferramentas_busca(linhas, custos=True):
    """As buscas: resultados brutos, itens unicos (o que sobra depois de juntar as repeticoes) e custo de cada ferramenta."""
    buscas = [l for l in linhas if l["busca"] and l["chamadas"]]
    if not buscas:
        return _bloco("ferramentas-busca", "Nenhuma busca registrada nas execuções do relatório")
    maior = max(buscas, key=lambda l: ((l["itens"] or 0), l["etapa"]))
    titulo = (f"A {rotulos.ETAPAS.get(maior['etapa'], maior['etapa'])} ({maior['ferramenta']}) trouxe mais itens únicos: "
              f"{_num(maior['itens'])} em {_num(maior['chamadas'])} chamadas")
    graf = g.barras_proporcao([{"rotulo": _nome(l), "total": l["resultados"] or 0, "parte": l["itens"] or 0} for l in buscas],
                              titulo, "Itens únicos dentro dos resultados brutos de cada busca", rotulo_parte="Itens únicos",
                              rotulo_resto="Repetições")
    if custos:
        cabecalho = ["Etapa · ferramenta", "Chamadas", "Falhas", "Resultados", "Resultados por chamada", "Itens únicos",
                     "Custo", "Créditos", "Custo por item"]
        linhas_tab = [[_nome(l), _num(l["chamadas"]), _num(l["falhas"]), _num(l["resultados"]), _razao(l["resultados_por_chamada"], 1),
                       _num(l["itens"]), _usd(l["custo_usd"]), _num(l["creditos"]),
                       _usd(l["custo_por_item"]) if l["custo_por_item"] else (f"{_razao(l['creditos_por_item'])} crédito"
                                                                              if l["creditos_por_item"] else "—")]
                      for l in buscas]
        texto = ["Créditos são o saldo do provedor no início menos o do fim de cada execução que registrou os dois; "
                 "não são dólares."]
    else:
        cabecalho = ["Etapa · ferramenta", "Chamadas", "Falhas", "Resultados", "Resultados por chamada", "Itens únicos"]
        linhas_tab = [[_nome(l), _num(l["chamadas"]), _num(l["falhas"]), _num(l["resultados"]), _razao(l["resultados_por_chamada"], 1),
                       _num(l["itens"])]
                      for l in buscas]
        texto = []
    tabela = {"cabecalho": cabecalho, "linhas": linhas_tab}
    return _bloco("ferramentas-busca", titulo, graf, "execuções do relatório; repetição = o mesmo item em mais de um resultado",
                  texto, tabela=tabela)


def bloco_custos(linhas, custos=True):
    """Todas as etapas: o custo registrado em US$ de cada ferramenta, com chamadas, falhas e tokens."""
    if not custos:
        if not linhas:
            return _bloco("ferramentas-chamadas", "Nenhuma chamada registrada nas execuções do relatório")
        tabela = {"cabecalho": ["Etapa · ferramenta", "Chamadas", "Falhas", "Tokens de entrada", "Tokens de saída"],
                  "linhas": [[_nome(l), _num(l["chamadas"]), _num(l["falhas"]), _num(l["tokens_entrada"] or None),
                              _num(l["tokens_saida"] or None)] for l in linhas]}
        return _bloco("ferramentas-chamadas", "Chamadas, falhas e tokens por etapa e ferramenta", None, "execuções do relatório",
                      ["Falha é a chamada sem resposta aproveitável (erro, cota, bloqueio); ela fica registrada."],
                      tabela=tabela)

    com_custo = [l for l in linhas if l["custo_usd"]]
    if not linhas:
        return _bloco("ferramentas-custos", "Nenhuma chamada registrada nas execuções do relatório")
    total = sum(l["custo_usd"] for l in linhas)
    if com_custo:
        maior = max(com_custo, key=lambda l: (l["custo_usd"], l["etapa"]))
        titulo = (f"O custo registrado foi {_usd(total)}; a maior parte ({_pct(maior['custo_usd'], total)}) "
                  f"na {rotulos.ETAPAS.get(maior['etapa'], maior['etapa'])}")
    else:
        titulo = "Nenhuma chamada com custo em dólar registrado"
    graf = graficos.barras_horizontais([(_nome(l), round(l["custo_usd"], 4)) for l in com_custo], titulo,
                                       "Custo registrado em US$ por etapa e ferramenta", _usd, MARGEM_ROTULOS, MAX_ROTULO) if com_custo else None
    tabela = {"cabecalho": ["Etapa · ferramenta", "Chamadas", "Falhas", "Custo", "Tokens de entrada", "Tokens de saída", "Créditos"],
              "linhas": [[_nome(l), _num(l["chamadas"]), _num(l["falhas"]), _usd(l["custo_usd"]), _num(l["tokens_entrada"] or None),
                          _num(l["tokens_saida"] or None), _num(l["creditos"])] for l in linhas]}
    return _bloco("ferramentas-custos", titulo, graf, "custo registrado por chamada (preço de tabela); download não tem custo",
                  ["Falha é a chamada sem resposta aproveitável (erro, cota, bloqueio); ela fica registrada e pode custar."],
                  tabela=tabela)
