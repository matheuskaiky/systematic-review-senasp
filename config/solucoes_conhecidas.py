"""Solucoes conhecidas: sistemas de IA de seguranca publica que o pesquisador sabe que existem, para conferir se a coleta os encontra
(pagina /solucoes do painel).

Esta lista e do pesquisador (dado de pesquisa), nao entra no hash da configuracao e nao muda nenhum resultado: so alimenta a conferencia.
Acrescente aqui outras solucoes conhecidas; so `main.py` le este arquivo.

Alem de conferir a coleta, a lista alimenta a camada 1 da unificacao de grafias de `nome_solucao` no painel (RC23): o nome e os apelidos
reunem, sob o nome oficial, as grafias que o modelo escreveu nos achados da MESMA UF. Se o mesmo nome identifica o mesmo sistema em outras
UFs, declare `outras_ufs=("SP", "RJ")` (ou `("*",)` para todas). O valor guardado no banco nunca e alterado."""
from dominio.solucoes import SolucaoConhecida

SOLUCOES_CONHECIDAS = (
    # "B.O. Fácil" e "B.O Fácil": grafias que o modelo e as paginas da SSP-PI usam (a normalizacao tira a pontuacao, entao viram "b o facil")
    SolucaoConhecida("BO Fácil", "PI", apelidos=("B.O. Fácil",),
                     observacao="Registro de boletim de ocorrência pelo WhatsApp, da SSP-PI. Ver docs/CASO_BO_FACIL.md."),
    SolucaoConhecida("SPiA", "PI", apelidos=("SPIA", "Sistema de Policiamento por Inteligência Artificial"),
                     observacao="Sistema de policiamento por inteligência artificial do Piauí."),
)
