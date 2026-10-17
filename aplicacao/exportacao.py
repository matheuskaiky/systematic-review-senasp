import pandas as pd

from aplicacao import rotulagem as RT
from dominio import auditoria_negativos as AN


def montar_tabelas(repo, ufs):
    tabelas = repo.tabelas_para_exportacao()
    resumo = tabelas.pop("Resumo_UF_bruto")
    todas = pd.DataFrame({"uf": list(ufs), "nome": list(ufs.values())})
    tabelas["Resumo_UF"] = todas.merge(resumo, on="uf", how="left").fillna(0)   # includes states with no findings
    return tabelas


def tabelas_rotulagem(plano, status_validos):
    """Planilhas da rotulagem mínima: {nome do arquivo .xlsx: {aba: DataFrame}} (aba de dados mais a aba LEIA-ME) para o exportador,
    e {nome do .csv: DataFrame} da auditoria em `csvs`. Só as partes com linhas aparecem. Devolve (planilhas, csvs)."""
    leiame = lambda linhas: pd.DataFrame({"LEIA-ME": linhas})
    planilhas, csvs = {}, {}
    if plano["achados"]["linhas"]:
        planilhas[RT.ARQ_ACHADOS] = {"Achados": pd.DataFrame(plano["achados"]["linhas"]),
                                     "LEIA-ME": leiame(RT.leiame_achados(plano, status_validos))}
    if plano["triagem"]["linhas"]:
        planilhas[RT.ARQ_TRIAGEM] = {"Triagem": pd.DataFrame(plano["triagem"]["linhas"]), "LEIA-ME": leiame(RT.leiame_triagem(plano))}
    h4 = plano["triagem"]["h4"]
    if h4 and h4["linhas"]:
        planilhas[RT.ARQ_TRIAGEM_H4] = {"Triagem": pd.DataFrame(h4["linhas"]), "LEIA-ME": leiame(RT.leiame_triagem(plano, h4=True))}
    if plano["auditoria"]["linhas"]:
        csvs[RT.ARQ_AUDITORIA] = pd.DataFrame(plano["auditoria"]["linhas"], columns=list(AN.COLUNAS_AMOSTRA))
    return planilhas, csvs
