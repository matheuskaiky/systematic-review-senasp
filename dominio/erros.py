"""Erros de dominio que as etapas usam para parar de forma controlada."""


class CotaDiariaEsgotada(Exception):
    """O provedor recusou a chamada porque a cota DIARIA acabou (por exemplo, o nivel gratuito de um provedor de LLM).

    Repetir hoje nao adianta e cada tentativa so gasta tempo: a etapa para, a execucao fica como interrompida e se
    retoma depois da renovacao da cota com `--retomar`. `renova_em_s` e o tempo de espera que o provedor informou."""

    def __init__(self, provedor, detalhe="", renova_em_s=None):
        self.provedor, self.detalhe, self.renova_em_s = provedor, detalhe, renova_em_s
        espera = f" (o provedor diz para tentar de novo em {_hms(renova_em_s)})" if renova_em_s else ""
        super().__init__(f"Cota diária do provedor '{provedor}' esgotada{espera}. {detalhe}".strip())


def _hms(segundos):
    s = int(segundos)
    return f"{s // 3600}h{(s % 3600) // 60:02d}min"
