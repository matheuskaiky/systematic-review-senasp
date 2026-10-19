"""Tokens --an-* de analises.css (cores de DADOS dos gráficos). Fonte única: o gerador monta os quatro blocos a partir daqui.

Paleta fixa para daltônicos (Okabe-Ito nas séries; estágios de maturidade em azul-escuro → cinza; semáforos em verde/âmbar/vermelho). Os valores abaixo são os do
analises.css original do projeto, sem mudança: o que a v5 muda nesta folha é a moldura da página, não as cores dos dados. A exceção é o mapa de calor, que
acompanha --calor-1..4 de painel.css (exigência de tests/test_painel_navegacao.py): sai calculado em calor() com o texto de cada nível escolhido por contraste.
"""
import re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tokens as T

# tokens que apontam para painel.css por var() sem valor de reserva (exigência do teste NA): nome sem o prefixo --an- -> token de painel.css
VARS = {
    "texto": "--texto", "suave": "--texto-suave", "borda": "--borda", "fundo": "--superficie", "acento": "--acento", "perigo": "--perigo", "ok": "--ok",
    "ok-fundo": "--ok-fundo", "perigo-fundo": "--perigo-fundo", "alerta": "--alerta", "alerta-fundo": "--alerta-fundo",
    "descartado-ln": "--perigo", "k-quase": "--ok", "cal-alta": "--ok",
}

# tema claro: literais (nome sem o prefixo --an-)
CLARO = {
    "em_uso": "#12306b",
    "em_uso-ln": "#2f5aa8",
    "em_uso-tx": "#ffffff",
    "piloto": "#9cc7ee",
    "piloto-ln": "#4f86c0",
    "piloto-tx": "#0b2540",
    "licitacao": "#237a4b",
    "licitacao-ln": "#5fb88a",
    "licitacao-tx": "#ffffff",
    "anunciado": "#f2c14e",
    "anunciado-ln": "#b8860b",
    "anunciado-tx": "#3b2a00",
    "em_estudo": "#b5bcc6",
    "em_estudo-ln": "#7d8795",
    "em_estudo-tx": "#1c2430",
    "apenas_citado": "#eceff3",
    "apenas_citado-ln": "#6b7686",
    "apenas_citado-tx": "#3d4756",
    "descartado": "#f6d5d6",
    "descartado-tx": "#7a1a1d",
    "s0": "#0072B2",
    "s1": "#D55E00",
    "s2": "#009E73",
    "s3": "#CC79A7",
    "s4": "#E69F00",
    "s5": "#56B4E9",
    "s6": "#6a4c93",
    "s7": "#6b7280",
    "pad-ln": "rgba(255,255,255,.62)",
    "f1": "#b85400",
    "f1-ln": "rgba(255,255,255,.62)",
    "k-fraca": "#e7a3a5",
    "k-fraca-ln": "#a3262a",
    "k-razoavel": "#f4b183",
    "k-razoavel-ln": "#8a4a10",
    "k-moderada": "#f2c14e",
    "k-moderada-ln": "#8a6410",
    "k-substancial": "#8fcfa8",
    "k-substancial-ln": "#1b7a4b",
    "k-quase-ln": "rgba(255,255,255,.55)",
    "cal-alta-ln": "rgba(255,255,255,.55)",
    "cal-media": "#e0a526",
    "cal-media-ln": "#6b4a00",
    "cal-baixa": "#c9494d",
    "cal-baixa-ln": "rgba(255,255,255,.7)",
    "res-mais3": "#1f5f8b",
    "res-mais3-ln": "rgba(255,255,255,.55)",
    "res-mais2": "#7fb0dc",
    "res-mais2-ln": "rgba(0,0,0,.3)",
    "res-zero": "#e8ecf1",
    "res-zero-ln": "#e8ecf1",
    "res-menos2": "#f5b97a",
    "res-menos2-ln": "rgba(0,0,0,.3)",
    "res-menos3": "#b85400",
    "res-menos3-ln": "rgba(255,255,255,.55)",
    "fx": "#d1383d",
    "fx-ln": "rgba(255,255,255,.7)",
    "ic": "rgba(31,95,139,.16)",
    "ic-ln": "rgba(31,95,139,.75)",
    "nv-aberto": "#2e8b57",
    "nv-aberto-ln": "rgba(255,255,255,.5)",
    "nv-parcial": "#e0a526",
    "nv-parcial-ln": "#6b4a00",
    "nv-fechado": "#b3282d",
    "nv-fechado-ln": "rgba(255,255,255,.7)",
}

# tema escuro: só o que muda (todos os literais do claro, menos o que não troca)
ESCURO = {
    "em_uso": "#a9d1fa",
    "em_uso-ln": "#7fb0e6",
    "em_uso-tx": "#0a1f38",
    "piloto": "#6fa8dc",
    "piloto-ln": "#3f78b4",
    "piloto-tx": "#0a1f38",
    "licitacao": "#3f9f6e",
    "licitacao-ln": "#1d6b43",
    "licitacao-tx": "#04170d",
    "anunciado": "#d9a73a",
    "anunciado-ln": "#8a6410",
    "anunciado-tx": "#2b1f00",
    "em_estudo": "#5f6a78",
    "em_estudo-ln": "#8a96a6",
    "em_estudo-tx": "#ffffff",
    "apenas_citado": "#222a35",
    "apenas_citado-ln": "#7b8594",
    "apenas_citado-tx": "#c3cbd6",
    "descartado": "#4a2326",
    "descartado-tx": "#f5b5b8",
    "s0": "#56a8e0",
    "s1": "#f08a4b",
    "s2": "#3fc79a",
    "s3": "#e39bc3",
    "s4": "#f2b84a",
    "s5": "#7fcaf0",
    "s6": "#a58bd1",
    "s7": "#a8a8a8",
    "pad-ln": "rgba(0,0,0,.45)",
    "f1": "#f0a35e",
    "f1-ln": "rgba(0,0,0,.45)",
    "k-fraca": "#8a3a3d",
    "k-fraca-ln": "#f5b5b8",
    "k-razoavel": "#b8733a",
    "k-razoavel-ln": "#2b1500",
    "k-moderada": "#d9a73a",
    "k-moderada-ln": "#2b1f00",
    "k-substancial": "#3f9f6e",
    "k-substancial-ln": "#04170d",
    "k-quase-ln": "rgba(0,0,0,.4)",
    "cal-alta-ln": "rgba(0,0,0,.4)",
    "cal-media": "#e8b45a",
    "cal-media-ln": "#2b1f00",
    "cal-baixa": "#f08a8d",
    "cal-baixa-ln": "rgba(0,0,0,.45)",
    "res-mais3": "#8fc0ea",
    "res-mais3-ln": "rgba(0,0,0,.4)",
    "res-mais2": "#3f6f9c",
    "res-mais2-ln": "rgba(255,255,255,.35)",
    "res-zero": "#2a323d",
    "res-zero-ln": "#2a323d",
    "res-menos2": "#8f5a24",
    "res-menos2-ln": "rgba(255,255,255,.35)",
    "res-menos3": "#f0a35e",
    "res-menos3-ln": "rgba(0,0,0,.4)",
    "fx": "#f08a8d",
    "fx-ln": "rgba(0,0,0,.45)",
    "ic": "rgba(143,192,234,.16)",
    "ic-ln": "rgba(143,192,234,.8)",
    "nv-aberto": "#62c28e",
    "nv-aberto-ln": "rgba(0,0,0,.4)",
    "nv-parcial": "#e8b45a",
    "nv-parcial-ln": "#2b1f00",
    "nv-fechado": "#f08a8d",
    "nv-fechado-ln": "rgba(0,0,0,.45)",
}

TEXTO_ESCURO = "#0b1620"   # texto sobre os níveis claros do mapa de calor
TEXTO_CLARO = "#ffffff"


def _melhor_texto(fundo):
    return max((TEXTO_ESCURO, TEXTO_CLARO), key=lambda t: T.contraste(fundo, t))


def calor(tema):
    """--an-calor0..4 e --an-calor-tx0..4: o mesmo valor de --calor-1..4 de painel.css; o nível 0 (sem dados) é a superfície do tema."""
    t = "escuro" if tema == "escuro" else "claro"
    out = {"calor0": T.valor("--superficie", t)}
    for i in range(1, 5):
        out[f"calor{i}"] = T.valor(f"--calor-{i}", t)
    out["calor-tx0"] = T.valor("--texto", t)
    for i in range(1, 5):
        out[f"calor-tx{i}"] = _melhor_texto(out[f"calor{i}"])
    return out


def claro():
    d = dict(CLARO)
    d.update(calor("claro"))
    return d


def escuro():
    d = dict(ESCURO)
    d.update(calor("escuro"))
    return d


def impressao():
    """O papel é sempre o tema claro: literais claros e, no lugar dos var(), o valor de impressão do token de painel.css (sem var(), como o teste exige)."""
    d = claro()
    for k, tok in VARS.items():
        d[k] = T.valor(tok, "impressao")
    return d
