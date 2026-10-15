from dominio.modelos import (Termo, ModeloConsultaWeb, FiltrosBusca,
                             FiltrosAcademicos, PoliticaDownload)

# ---------- Task 2: academic terms (Scholar + manual searches) ----------
# Lista da pesquisa (docs/termos.md): cada termo vira uma frase exata entre aspas.
# O grupo e a categoria da tabela (secao 4.1). Termos novos seguem a secao 4.2, com o codigo
# de justificativa em comentario (o Termo nao guarda a justificativa).
TERMOS = [
    # ----- T01 a T21: lista pre-definida (secao 4.1), em portugues -----
    # Reconhecimento e identificacao
    Termo("T01", '"reconhecimento facial"', "pt", "reconhecimento_identificacao"),
    Termo("T02", '"reconhecimento facial em tempo real"', "pt", "reconhecimento_identificacao"),
    Termo("T03", '"biometria facial"', "pt", "reconhecimento_identificacao"),
    Termo("T04", '"reconhecimento de voz"', "pt", "reconhecimento_identificacao"),
    # Video e monitoramento
    Termo("T05", '"videomonitoramento inteligente"', "pt", "video_monitoramento"),
    Termo("T06", '"videoanálise"', "pt", "video_monitoramento"),
    Termo("T07", '"câmeras inteligentes"', "pt", "video_monitoramento"),
    Termo("T08", '"leitura automática de placas"', "pt", "video_monitoramento"),
    # Analise preditiva (T11, T12 e T21 sem o parentetico; o parentetico virou termo proprio: T22 a T24)
    Termo("T09", '"policiamento preditivo"', "pt", "analise_preditiva"),
    Termo("T10", '"análise preditiva de criminalidade"', "pt", "analise_preditiva"),
    Termo("T11", '"mapeamento de pontos quentes"', "pt", "analise_preditiva"),
    Termo("T12", '"avaliação de risco por algoritmos"', "pt", "analise_preditiva"),
    # Dados e automacao
    Termo("T13", '"inteligência artificial na segurança pública"', "pt", "dados_automacao"),
    Termo("T14", '"big data na segurança pública"', "pt", "dados_automacao"),
    Termo("T15", '"aprendizado de máquina"', "pt", "dados_automacao"),
    Termo("T16", '"análise de vínculos"', "pt", "dados_automacao"),
    # Atendimento e triagem
    Termo("T17", '"chatbot e atendimento automatizado"', "pt", "atendimento_triagem"),
    Termo("T18", '"delegacia virtual inteligente"', "pt", "atendimento_triagem"),
    # Outras aplicacoes
    Termo("T19", '"detecção de disparo de arma de fogo"', "pt", "outras_aplicacoes"),
    Termo("T20", '"drones com inteligência artificial"', "pt", "outras_aplicacoes"),
    Termo("T21", '"centro integrado de comando e controle com IA"', "pt", "outras_aplicacoes"),

    # ----- T22 a T24: termos que estavam entre parenteses na lista (J1: variacao de T11, T12 e T21) -----
    Termo("T22", '"hotspots"', "pt", "analise_preditiva"),                       # J1 de T11
    Termo("T23", '"justiça atuarial"', "pt", "analise_preditiva"),               # J1 de T12
    Termo("T24", '"CICC com IA"', "pt", "outras_aplicacoes"),                    # J1 de T21

    # ----- T25 a T46: equivalentes em ingles (J1: variacao do termo indicado), para IEEE, ACM e Scopus -----
    Termo("T25", '"facial recognition"', "en", "reconhecimento_identificacao"),                     # J1 de T01
    Termo("T26", '"real-time facial recognition"', "en", "reconhecimento_identificacao"),           # J1 de T02
    Termo("T27", '"facial biometrics"', "en", "reconhecimento_identificacao"),                      # J1 de T03
    Termo("T28", '"voice recognition"', "en", "reconhecimento_identificacao"),                      # J1 de T04
    Termo("T29", '"intelligent video surveillance"', "en", "video_monitoramento"),                  # J1 de T05
    Termo("T30", '"video analytics"', "en", "video_monitoramento"),                                 # J1 de T06
    Termo("T31", '"smart cameras"', "en", "video_monitoramento"),                                   # J1 de T07
    Termo("T32", '"automatic license plate recognition"', "en", "video_monitoramento"),             # J1 de T08
    Termo("T33", '"predictive policing"', "en", "analise_preditiva"),                               # J1 de T09
    Termo("T34", '"predictive crime analysis"', "en", "analise_preditiva"),                         # J1 de T10
    Termo("T35", '"crime hotspot mapping"', "en", "analise_preditiva"),                             # J1 de T11
    Termo("T36", '"algorithmic risk assessment"', "en", "analise_preditiva"),                       # J1 de T12
    Termo("T37", '"actuarial justice"', "en", "analise_preditiva"),                                 # J1 de T23
    Termo("T38", '"artificial intelligence in public security"', "en", "dados_automacao"),          # J1 de T13
    Termo("T39", '"big data in public security"', "en", "dados_automacao"),                         # J1 de T14
    Termo("T40", '"machine learning"', "en", "dados_automacao"),                                    # J1 de T15
    Termo("T41", '"link analysis"', "en", "dados_automacao"),                                       # J1 de T16
    Termo("T42", '"chatbot and automated service"', "en", "atendimento_triagem"),                   # J1 de T17
    Termo("T43", '"intelligent virtual police station"', "en", "atendimento_triagem"),              # J1 de T18
    Termo("T44", '"gunshot detection"', "en", "outras_aplicacoes"),                                 # J1 de T19
    Termo("T45", '"drones with artificial intelligence"', "en", "outras_aplicacoes"),               # J1 de T20
    Termo("T46", '"integrated command and control center with AI"', "en", "outras_aplicacoes"),     # J1 de T21
]
# Consultas combinadas (termo + contexto) sao opcionais e ficam DESLIGADAS: cada uma custa ate MAX_PAGINAS_ACADEMICO
# creditos. Decida com os dados de `Termos_rendimento` (termos de baixa taxa_inclusao_pct sao candidatos) e confira
# o efeito em `Ganho_contexto`. Exemplo (nao ativo):
#   from dominio.servicos import termo_composto
#   TERMOS += [termo_composto("T47", TERMOS[39], '"public security" OR police')]    # "machine learning" + contexto
BASES_MANUAIS = ("IEEE", "ACM", "Scopus", "SBC OpenLib")

FILTROS_ACADEMICOS = FiltrosAcademicos(ano_inicial=2019, ano_final=None, por_pagina=20)
MAX_PAGINAS_ACADEMICO = 3          # 3 pages = up to 60 results per term

# ---------- Task 1: web queries ----------
UFS = {
    "AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas", "BA": "Bahia",
    "CE": "Ceará", "DF": "Distrito Federal", "ES": "Espírito Santo", "GO": "Goiás",
    "MA": "Maranhão", "MT": "Mato Grosso", "MS": "Mato Grosso do Sul",
    "MG": "Minas Gerais", "PA": "Pará", "PB": "Paraíba", "PR": "Paraná",
    "PE": "Pernambuco", "PI": "Piauí", "RJ": "Rio de Janeiro",
    "RN": "Rio Grande do Norte", "RS": "Rio Grande do Sul", "RO": "Rondônia",
    "RR": "Roraima", "SC": "Santa Catarina", "SP": "São Paulo", "SE": "Sergipe",
    "TO": "Tocantins",
}

# Each template generates 1 query per state x technology. {tec}, {nome}, {uf} are filled in.
# (Templates stay in Portuguese on purpose: they search Brazilian government sites.)
MODELOS_WEB = [
    ModeloConsultaWeb("M01", "{tec} Secretaria de Segurança Pública {nome}", perfil="oficial"),
    ModeloConsultaWeb("M02", "{tec} segurança pública {nome} {uf}", perfil="geral"),
]

# Secretarias MUNICIPAIS (vazio = so as estaduais). Preencha as duas listas para buscar cidades; nada foi inventado aqui:
#   MUNICIPIOS = {"PI": ["Teresina"]}      (UF -> cidades escolhidas pelo pesquisador)
#   MODELOS_WEB_MUNICIPAIS = [ModeloConsultaWeb("M11", "{tec} Secretaria Municipal de Segurança {cidade} {uf}", perfil="oficial")]
# Cada consulta municipal grava a cidade em resultados_web, classificacoes e nos achados (coluna `cidade`).
MUNICIPIOS = {}
MODELOS_WEB_MUNICIPAIS = []

# NEUTRAL filter profiles; each adapter translates them to its own provider.
# Warning: do not mix allowlist and denylist in the same profile (some APIs reject it).
PERFIS_BUSCA_WEB = {
    "oficial": FiltrosBusca(dominios_incluir=(".gov.br",), max_resultados=10),
    "geral": FiltrosBusca(
        dominios_excluir=("reddit.com", "pinterest.com", "facebook.com",
                          "instagram.com", "quora.com"),
        max_resultados=10),
}

# Which URLs are worth downloading (cost and time control).
# (Keywords stay in Portuguese on purpose: they are matched against Portuguese titles/snippets.)
POLITICA_DOWNLOAD = PoliticaDownload(
    palavras_chave=("reconhecimento facial", "câmera", "camera", "videomonitoramento",
                    "inteligência artificial", "inteligencia artificial", "placas",
                    "preditiv", "licitação", "licitacao", "pregão", "pregao", "edital",
                    "monitoramento"),
    max_urls_por_uf=40,
    dominios_excluir=("youtube.com", "tiktok.com", "twitter.com", "x.com"),
    apenas_oficiais=False,
)

assert len({t.id for t in TERMOS}) == len(TERMOS), "Duplicate term IDs"
assert len({m.id for m in MODELOS_WEB}) == len(MODELOS_WEB), "Duplicate template IDs"
assert len(UFS) == 27, "The state list must have 27 entries"
assert len({m.id for m in MODELOS_WEB + MODELOS_WEB_MUNICIPAIS}) == len(MODELOS_WEB + MODELOS_WEB_MUNICIPAIS), "Duplicate template IDs"
for _m in MODELOS_WEB + MODELOS_WEB_MUNICIPAIS:
    assert _m.perfil in PERFIS_BUSCA_WEB, f"Nonexistent profile: {_m.perfil}"
