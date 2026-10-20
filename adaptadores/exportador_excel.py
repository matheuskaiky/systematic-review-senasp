from datetime import datetime
from pathlib import Path
import pandas as pd
from dominio.planilha import LIMITE_CELULA, MARCADOR, celula_segura

MAX_ABA = 31                    # limite do Excel para o nome de uma aba


_limpar = celula_segura           # a regra C3 fica em dominio/planilha.py (uma so implementacao)


def _limpar_tabela(df):
    df = df.copy()
    for col in df.columns:
        if pd.api.types.is_object_dtype(df[col]) or pd.api.types.is_string_dtype(df[col]):
            df[col] = df[col].map(_limpar)
    df.columns = [_limpar(c) for c in df.columns]
    return df


class ExportadorExcel:
    def __init__(self, pasta=None):
        self._pasta = Path(pasta or "outputs")

    def exportar(self, tabelas, caminho=None):
        caminho = Path(caminho or self._pasta / f"resultado_{datetime.now():%Y%m%d_%H%M}.xlsx")
        nomes = [aba[:MAX_ABA] for aba in tabelas]
        if len(set(nomes)) != len(nomes):
            raise ValueError("Nomes de aba repetidos depois de cortar em 31 caracteres: "
                             + ", ".join(sorted({n for n in nomes if nomes.count(n) > 1})))
        caminho.parent.mkdir(parents=True, exist_ok=True)
        with pd.ExcelWriter(caminho, engine="openpyxl") as xw:
            for aba, df in tabelas.items():
                _limpar_tabela(df).to_excel(xw, sheet_name=aba[:MAX_ABA], index=False)
        return str(caminho)
