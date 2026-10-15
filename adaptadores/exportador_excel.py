from datetime import datetime
from pathlib import Path
import pandas as pd
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

LIMITE_CELULA = 32_000          # o Excel aceita 32.767 caracteres por celula; sobra margem para o marcador
MARCADOR = "…[truncado]"
MAX_ABA = 31                    # limite do Excel para o nome de uma aba


def _limpar(valor):
    """C3: tira caracteres de controle (o openpyxl levanta IllegalCharacterError), corta texto acima do limite da
    celula com marcador visivel e impede que texto da web que comece com "=" vire formula no Excel."""
    if not isinstance(valor, str):
        return valor
    valor = ILLEGAL_CHARACTERS_RE.sub("", valor)
    if len(valor) > LIMITE_CELULA:
        valor = valor[:LIMITE_CELULA - len(MARCADOR)] + MARCADOR
    if valor.startswith("="):
        valor = " " + valor
    return valor


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
