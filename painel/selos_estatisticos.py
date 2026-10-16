"""Selos e frases em linguagem simples para os resultados do módulo estatístico (funções puras, sem I/O).

Os textos seguem o plano de visualização (seção 7.1, item 2). As classes CSS ficam em `static/analises.css`
e combinam com `.selo` de `painel.css` (`<span class="selo ev-forte">...</span>`).
"""
import math

_NIVEIS = {
    "forte": ("ev-forte", "✔ Evidência forte (p < 0,01)", "Padrão estatisticamente comprovado (altíssima confiança)"),
    "moderada": ("ev-moderada", "◐ Evidência moderada (0,01 ≤ p < 0,05)", "Diferença relevante detectada"),
    "insuficiente": ("ev-insuficiente", "○ Sem evidência suficiente (p ≥ 0,05)",
                     "Diferença dentro da margem do acaso (amostra ainda pequena ou comportamento igual)"),
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


def frase_odds(rotulo, or_, ic_inf, ic_sup):
    """Transforma uma razão de chances (odds ratio) com IC 95% em frase direta.

    Ex.: frase_odds("citação literal verificada", 8.5, 6.0, 11.2) ->
    "Achados com citação literal verificada têm entre 6x e 11x mais chance de serem confirmados pelo perito humano."
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
    if inf > 1:
        faixa = f"pelo menos {_vezes(inf)}" if infinito else f"entre {_vezes(inf)} e {_vezes(sup)}"
        return f"{sujeito} têm {faixa} mais chance de serem confirmados pelo perito humano."
    if not infinito and sup < 1:
        return f"{sujeito} têm entre {_vezes(1 / sup)} e {_vezes(1 / inf)} menos chance de serem confirmados pelo perito humano."
    limites = f"de {_vezes(inf)} a {'mais' if infinito else _vezes(sup)}"
    return (f"{sujeito}: não há evidência de que tenham mais ou menos chance de serem confirmados "
            f"(o intervalo vai {limites} e inclui 1x, que significa sem efeito).")
