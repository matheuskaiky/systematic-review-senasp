"""Rendimento e custo de cada ferramenta usada nas etapas (busca, download, classificacao, triagem), em qualquer banco. Sem
I/O: recebe o que `analise_ferramentas()` le das chamadas das execucoes do relatorio. O nome da ferramenta e o provedor
como o banco gravou: trocar de provedor nao muda este arquivo."""

ETAPAS_DE_BUSCA = ("busca_web", "busca_academica", "busca_literatura")


def _razao(parte, total):
    return parte / total if total else None


def linhas(d):
    """Uma linha por etapa e ferramenta, na ordem das etapas de busca e depois das outras (pelo nome), com chamadas, falhas,
    custo, tokens e creditos; nas buscas, tambem os resultados brutos, os itens unicos e as razoes (resultados por chamada,
    itens por resultado, custo e creditos por item). A etapa com mais de uma ferramenta repete os resultados em cada linha."""
    ordem = {e: i for i, e in enumerate(ETAPAS_DE_BUSCA)}
    saida = []
    for c in sorted(d["chamadas"], key=lambda c: (ordem.get(c["etapa"], len(ordem)), c["etapa"], c["provedor"])):
        busca = c["etapa"] in ETAPAS_DE_BUSCA
        resultados = d["resultados"].get(c["etapa"]) if busca else None
        itens = d["itens"].get(c["etapa"]) if busca else None
        custo, creditos = c["custo_usd"] or 0.0, d["creditos"].get(c["provedor"])
        saida.append({"etapa": c["etapa"], "ferramenta": c["provedor"], "busca": busca, "chamadas": c["chamadas"],
                      "falhas": c["chamadas"] - (c["ok"] or 0), "custo_usd": custo, "creditos": creditos,
                      "tokens_entrada": c["tokens_entrada"] or 0, "tokens_saida": c["tokens_saida"] or 0,
                      "resultados": resultados, "itens": itens,
                      "resultados_por_chamada": _razao(resultados, c["chamadas"]) if busca else None,
                      "itens_por_resultado": _razao(itens, resultados) if busca else None,
                      "custo_por_item": _razao(custo, itens) if busca and custo else None,
                      "creditos_por_item": _razao(creditos, itens) if busca and creditos else None})
    return saida


def total_custo(lista):
    """O custo registrado de todas as linhas, em US$."""
    return sum(l["custo_usd"] for l in lista)
