"""Numeros, moeda, datas e duracoes no formato pt-BR."""
from datetime import datetime


def numero(n):
    return "—" if n is None else f"{int(n):,}".replace(",", ".")


def decimal(x, casas=1):
    return "—" if x is None else f"{x:.{casas}f}".replace(".", ",")


def pct(parte, total):
    return "—" if not total else f"{100 * (parte or 0) / total:.0f}%".replace(".", ",")


def moeda_usd(v):
    if v is None:
        return "—"
    casas = 2 if v == 0 or abs(v) >= 0.01 else 4
    return "US$ " + f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _data(iso):
    try:
        return datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return None


def data_hora(iso):
    d = _data(iso)
    return "—" if d is None else d.strftime("%d/%m/%Y %H:%M")


def duracao(inicio, fim):
    a, b = _data(inicio), _data(fim)
    if a is None or b is None:
        return "—"
    s = max(int((b - a).total_seconds()), 0)
    if s < 60:
        return f"{s} s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m} min {s} s"
    h, m = divmod(m, 60)
    return f"{h} h {m} min"
