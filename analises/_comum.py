"""Utilidades comuns dos scripts de análise: argumentos, pasta de saída, figuras (SVG e PNG) e texto de resultado.

Não depende do código do sistema nem do painel. Importa o matplotlib só dentro das funções que desenham."""
import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SAIDA_PADRAO = RAIZ / "outputs" / "analises"
SEMENTE = 20261016          # semente fixa de todos os sorteios (bootstrap, dados sintéticos)

# Cores: uma por papel (identidade), tinta cinza para texto e grade.
AZUL, LARANJA, CINZA, TINTA = "#2a6fbb", "#c9611a", "#8a8f98", "#2b2f36"


def ler_argumentos(descricao, extras=None):
    """Parser padrão: --saida, --banco, --selftest. `extras(parser)` acrescenta opções do script."""
    p = argparse.ArgumentParser(description=descricao)
    p.add_argument("--saida", type=Path, default=SAIDA_PADRAO, help="pasta de saída (padrão: outputs/analises/)")
    p.add_argument("--banco", type=Path, default=None, help="banco SQLite (padrão: data/busca.db); sempre aberto só para leitura")
    p.add_argument("--selftest", action="store_true", help="roda com dados sintéticos, sem abrir o banco")
    if extras:
        extras(p)
    return p.parse_args()


def preparar_saida(pasta):
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def novo_grafico(largura=7.0, altura=4.2):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 10, "axes.edgecolor": CINZA, "axes.labelcolor": TINTA, "text.color": TINTA,
                         "xtick.color": TINTA, "ytick.color": TINTA, "axes.spines.top": False,
                         "axes.spines.right": False, "axes.grid": True, "grid.color": "#e3e5e8", "grid.linewidth": 0.6,
                         "svg.fonttype": "none"})
    fig, ax = plt.subplots(figsize=(largura, altura))
    return fig, ax


def salvar_figura(fig, pasta, nome):
    """Grava `nome`.svg e `nome`.png e devolve os dois caminhos."""
    import matplotlib.pyplot as plt
    fig.tight_layout()
    caminhos = []
    for ext in ("svg", "png"):
        c = Path(pasta) / f"{nome}.{ext}"
        fig.savefig(c, dpi=150 if ext == "png" else None, facecolor="white")
        caminhos.append(c)
    plt.close(fig)
    return caminhos


def escrever_texto(pasta, nome, linhas):
    c = Path(pasta) / nome
    c.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return c


def escrever_csv(pasta, nome, df):
    c = Path(pasta) / nome
    df.to_csv(c, index=False)
    return c


def dados_insuficientes(motivo):
    """Mensagem padrão (em português) de recusa por falta de dados; encerra com código 2."""
    print(f"DADOS INSUFICIENTES: {motivo}", file=sys.stderr)
    sys.exit(2)
