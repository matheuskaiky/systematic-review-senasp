"""Selos e frases em linguagem simples para os resultados do módulo estatístico (funções puras, sem I/O).

Os textos seguem o plano de visualização (seção 7.1, item 2). As classes CSS ficam em `static/analises.css`
e combinam com `.selo` de `painel.css` (`<span class="selo ev-forte">...</span>`).
"""
import math

_NIVEIS = {
    "forte": ("ev-forte", "✔ Evidência forte (p < 0,01)", "Diferença muito improvável de ser acaso (p < 0,01)"),
    "moderada": ("ev-moderada", "◐ Evidência moderada (0,01 ≤ p < 0,05)", "Diferença improvável de ser acaso (p < 0,05)"),
    "insuficiente": ("ev-insuficiente", "○ Sem evidência suficiente (p ≥ 0,05)",
                     "Os dados não permitem afirmar diferença; isso não prova que os grupos sejam iguais"),
    None: ("ev-sem", "— Sem teste estatístico", "Ainda não há dados suficientes para o teste estatístico."),
}


def nivel_de_evidencia(p_valor):
    """Devolve 'forte', 'moderada', 'insuficiente' ou None.

    Aceita o p-valor (número entre 0 e 1) ou o próprio nível já calculado pelo módulo estatístico
    ('forte', 'moderada', 'insuficiente'). Qualquer outra coisa (None, NaN, texto desconhecido, fora de [0, 1]) dá None.
    """
    if isinstance(p_valor, str):
        return p_valor if p_valor in ("forte", "moderada", "insuficiente") else None
    if isinstance(p_valor, bool):
        return None
    try:
        p = float(p_valor)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(p) or p < 0 or p > 1:
        return None
    if p < 0.01:
        return "forte"
    if p < 0.05:
        return "moderada"
    return "insuficiente"


def selo(p_valor):
    """`p_valor` = float, nível ('forte'|'moderada'|'insuficiente') ou None.

    Devolve {"classe": "ev-forte" | "ev-moderada" | "ev-insuficiente" | "ev-sem", "rotulo": texto curto do selo,
    "texto": frase em linguagem simples para o gestor}.
    """
    classe, rotulo, texto = _NIVEIS[nivel_de_evidencia(p_valor)]
    return {"classe": classe, "rotulo": rotulo, "texto": texto}


def _vezes(v):
    """6 -> '6x'; 4.2 -> '4,2x'; 11.4 -> '11x' (uma casa decimal abaixo de 10, nenhuma a partir de 10)."""
    if v >= 10:
        return f"{v:.0f}x"
    texto = f"{v:.1f}".rstrip("0").rstrip(".")
    return texto.replace(".", ",") + "x"


def _positivo(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x > 0 and not math.isnan(x) else None


NOTA_RAZAO_DE_CHANCES = "Razão de chances não é o mesmo que probabilidade."


def _razao(v):
    """Razão de chances em texto: abaixo de 1 usa duas casas (0,25 -> '0,25x'); de 1 para cima, como `_vezes`."""
    if v < 1:
        return f"{v:.2f}".replace(".", ",") + "x"
    return _vezes(v)


def frase_odds(rotulo, or_, ic_inf, ic_sup):
    """Transforma uma razão de chances (odds ratio) com IC 95% em frase direta, sem dizer "N vezes mais provável".

    Uma razão de chances compara ODDS (chance = p / (1 - p)), não probabilidades: só se aproxima de "vezes mais
    provável" quando o evento é raro. Por isso a frase fala em "chance (odds)" e traz a nota
    `NOTA_RAZAO_DE_CHANCES`.
    Ex.: frase_odds("citação literal verificada", 8.5, 6.0, 11.2) ->
    "Achados com citação literal verificada: a chance (odds) de serem confirmados pelo perito humano é entre 6x e 11x
    a dos achados sem essa característica. Razão de chances não é o mesmo que probabilidade."
    Se o intervalo inclui 1 (sem efeito), a frase diz que não há evidência de diferença.
    """
    r = str(rotulo or "").strip()
    sujeito = f"Achados com {r}" if r else "Achados com essa característica"
    est, inf, sup = _positivo(or_), _positivo(ic_inf), _positivo(ic_sup)
    if est is None or inf is None:
        return f"{sujeito}: sem estimativa (dados insuficientes)."
    if sup is None:
        return f"{sujeito}: sem estimativa (dados insuficientes)."
    infinito = math.isinf(sup)
    base = f"{sujeito}: a chance (odds) de serem confirmados pelo perito humano é"
    if inf > 1:
        faixa = f"de pelo menos {_razao(inf)}" if infinito else f"entre {_razao(inf)} e {_razao(sup)}"
        return f"{base} {faixa} a dos achados sem essa característica. {NOTA_RAZAO_DE_CHANCES}"
    if not infinito and sup < 1:
        return f"{base} entre {_razao(inf)} e {_razao(sup)} a dos achados sem essa característica (menor). {NOTA_RAZAO_DE_CHANCES}"
    limites = f"de {_razao(inf)} a {'mais' if infinito else _razao(sup)}"
    return (f"{sujeito}: não há evidência de diferença na chance (odds) de serem confirmados "
            f"(o intervalo vai {limites} e inclui 1x, que significa sem efeito). {NOTA_RAZAO_DE_CHANCES}")
