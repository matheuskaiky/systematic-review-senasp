"""Entrada das etapas de download e classificacao: execucoes de origem (`--de`) e motivos de falha de download.

`execucoes.run_origem` e uma coluna TEXT unica: com varias execucoes de origem, guarda os run_id separados por virgula, na
ordem em que foram dadas. Esta e a UNICA funcao que separa esse valor; todo consumidor (repositorio, leituras do painel,
`main.py`) passa por ela."""
import re

# Motivos de falha de DOWNLOAD que `v_resultado_download.motivo` produz (schema.sql), alem de http_<codigo>.
# Falhas de extracao (pagina baixada, sem texto) nao entram: o filtro `--so-falha` olha a tentativa de download.
MOTIVOS_FALHA_DOWNLOAD = ("bloqueado_por_robots", "robots_inacessivel", "erro_de_leitura", "erro_de_rede")
_HTTP = re.compile(r"^http_[1-5]\d\d$")


def separar_runs(valor):
    """Lista de run_id (sem repeticoes, na ordem dada) a partir de None, de um texto "a,b" ou de uma lista/tupla.

    Aceita tambem listas cujos itens trazem virgulas (ex.: ["a,b", "c"]); espacos e itens vazios sao ignorados."""
    if not valor:
        return []
    itens = [valor] if isinstance(valor, str) else list(valor)
    runs = []
    for item in itens:
        for run in str(item).split(","):
            run = run.strip()
            if run and run not in runs:
                runs.append(run)
    return runs


def juntar_runs(valor):
    """Valor de `execucoes.run_origem` (texto com virgulas) para uma ou varias execucoes; None se nao houver."""
    return ",".join(separar_runs(valor)) or None


def motivo_falha_download_valido(motivo):
    return motivo in MOTIVOS_FALHA_DOWNLOAD or bool(_HTTP.match(motivo or ""))


def descricao_motivos_falha_download():
    return ", ".join(MOTIVOS_FALHA_DOWNLOAD) + ", http_<codigo> (por exemplo http_403, http_404)"
