"""Algarismos de largura fixa so onde numeros se alinham em coluna: no texto corrido, a fonte da ao hifen a largura de um
digito e "busca-web" e as datas aparecem espacados."""
import re
from pathlib import Path

CSS = (Path(__file__).resolve().parent.parent / "painel" / "static" / "painel.css").read_text(encoding="utf-8")


def test_corpo_do_texto_sem_algarismos_tabulares():
    body = re.search(r"\nbody \{[^}]*\}", CSS).group(0)
    assert "tabular-nums" not in body


def test_colunas_e_contadores_com_algarismos_tabulares():
    assert ".num, .kpi-valor, .num-prisma, .contagem, .fila-contagem, .gr-valor { font-variant-numeric: tabular-nums; }" in CSS
