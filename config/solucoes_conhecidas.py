"""Solucoes conhecidas: sistemas de IA de seguranca publica que o pesquisador sabe que existem, para conferir se a coleta os encontra
(pagina /solucoes do painel).

Esta lista e do pesquisador (dado de pesquisa), nao entra no hash da configuracao e nao muda nenhum resultado: so alimenta a conferencia.
Acrescente aqui outras solucoes conhecidas; so `main.py` le este arquivo."""
from dominio.solucoes import SolucaoConhecida

SOLUCOES_CONHECIDAS = (
    SolucaoConhecida("BO Fácil", "PI",
                     observacao="Registro de boletim de ocorrência pelo WhatsApp, da SSP-PI. Ver docs/CASO_BO_FACIL.md."),
    SolucaoConhecida("SPiA", "PI", apelidos=("SPIA", "Sistema de Policiamento por Inteligência Artificial"),
                     observacao="Sistema de policiamento por inteligência artificial do Piauí."),
)
