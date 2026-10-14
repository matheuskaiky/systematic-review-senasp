from datetime import datetime
from pathlib import Path
import pandas as pd


class ExportadorExcel:
    def exportar(self, tabelas, caminho=None):
        caminho = Path(caminho or f"outputs/resultado_{datetime.now():%Y%m%d_%H%M}.xlsx")
        caminho.parent.mkdir(parents=True, exist_ok=True)
        with pd.ExcelWriter(caminho, engine="openpyxl") as xw:
            for aba, df in tabelas.items():
                df.to_excel(xw, sheet_name=aba[:31], index=False)
        return str(caminho)
