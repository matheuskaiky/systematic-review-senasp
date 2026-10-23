"""Visao geral do banco `vies` (busca de vies algoritmico): os numeros desta busca no lugar do funil da Tarefa 1.
Funcoes puras sobre as leituras do painel; a rota `/` chama `dados` quando o banco e o `vies`."""
from dominio import analises_vies as AV
from painel import analises_blocos_vies as bv, formatacao as fmt
from painel.graficos import barra_empilhada


def itens(leitura, contexto):
    """Os itens da busca (referencias da web e artigos do Scholar) com a ultima triagem valida do modelo."""
    conjunto = contexto.conjunto_da_consulta
    return AV.itens(leitura.linhas_referencias_web(), leitura.linhas_artigos_das_consultas(list(conjunto)), conjunto,
                    leitura.triagens_vies(contexto.versao_triagem_vies))


def dados(leitura, contexto):
    """O contexto do modelo `geral_vies.html`: resumo, alertas, relevancia, triagem humana e ultimas execucoes."""
    lista = itens(leitura, contexto)
    resumo = AV.resumo(lista)
    r, tri = leitura.resumo_geral(), leitura.contagem_triagem()
    alertas = []
    if tri["pendentes"]:
        alertas.append(("aviso", f"{fmt.numero(tri['pendentes'])} artigo(s) ainda sem triagem humana.", "/literatura/triagem", "Triar artigos"))
    if r["execucoes_nao_concluidas"]:
        alertas.append(("aviso", f"{fmt.numero(r['execucoes_nao_concluidas'])} execução(ões) não concluída(s).", None, None))
    if r["chamadas_com_falha"]:
        alertas.append(("info", f"{fmt.numero(r['chamadas_com_falha'])} chamada(s) externa(s) com falha registrada.", None, None))
    barra = barra_empilhada([(tri["incluidos"], "be-conf", "Incluídos"), (tri["excluidos"], "be-desc", "Excluídos")], tri["total"],
                            f"{tri['incluidos']} incluídos, {tri['excluidos']} excluídos, {tri['pendentes']} pendentes")
    return {"resumo": resumo, "r": r, "tri": tri, "alertas": alertas, "barra": barra, "relevancia": bv.bloco_relevancia(lista),
            "execucoes": leitura.execucoes_recentes(5)}
