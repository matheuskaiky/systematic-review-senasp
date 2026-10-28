"""Visão geral do banco `vies` (busca de viés algorítmico)."""
from dominio import analises_vies as AV


def itens(leitura, contexto):
    """Os itens da busca (referências da web e artigos do Scholar) com a última triagem válida do modelo."""
    conjunto = contexto.conjunto_da_consulta
    return AV.itens(
        leitura.linhas_referencias_web(),
        leitura.linhas_artigos_das_consultas(list(conjunto)),
        conjunto,
        leitura.triagens_vies(contexto.versao_triagem_vies),
    )
