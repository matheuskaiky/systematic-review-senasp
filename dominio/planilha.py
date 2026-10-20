"""Regra de seguranca das celulas de texto nas planilhas exportadas (correcao C3): uma so implementacao, usada pela
exportacao principal (adaptadores/exportador_excel.py) e pelo catalogo de referencias (aplicacao/exportacao.py)."""
import re

LIMITE_CELULA = 32_000          # o Excel aceita 32.767 caracteres por celula; sobra margem para o marcador
MARCADOR = "…[truncado]"
_CONTROLE = re.compile(r"[\000-\010]|[\013-\014]|[\016-\037]")     # os caracteres que o openpyxl recusa


def celula_segura(valor):
    """Tira caracteres de controle (o openpyxl levanta IllegalCharacterError), corta texto acima do limite da celula com
    marcador visivel e impede que texto que comece com "=" vire formula no Excel. Valor que nao e texto passa como esta."""
    if not isinstance(valor, str):
        return valor
    valor = _CONTROLE.sub("", valor)
    if len(valor) > LIMITE_CELULA:
        valor = valor[:LIMITE_CELULA - len(MARCADOR)] + MARCADOR
    if valor.startswith("="):
        valor = " " + valor
    return valor
