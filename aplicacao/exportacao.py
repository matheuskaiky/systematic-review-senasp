import pandas as pd


def montar_tabelas(repo, ufs):
    tabelas = repo.tabelas_para_exportacao()
    resumo = tabelas.pop("Resumo_UF_bruto")
    todas = pd.DataFrame({"uf": list(ufs), "nome": list(ufs.values())})
    tabelas["Resumo_UF"] = todas.merge(resumo, on="uf", how="left").fillna(0)   # includes states with no findings
    return tabelas
