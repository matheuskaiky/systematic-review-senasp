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
# Termos compostos (piloto de 6 termos-pai x 2 sintaxes e ampliacao): desligados por padrao, rodam apenas quando citados em --termos.
from dominio.servicos import termo_composto

_PAIS_TERMOS = {t.id: t for t in TERMOS}
_CONTEXTOS_COMPOSTOS = {
    "pt": {
        "A": '"segurança pública" OR polícia OR policiamento',
        "B": '"segurança pública"',
    },
    "en": {
        "A": '(Brazil OR Brazilian) AND ("public security" OR police OR policing)',
        "B": "Brazil police",
    },
}

# Piloto inicial (6 termos-pai x 2 sintaxes: T47 a T58)
_COMPOSTOS_PILOTO = (
    ("T47", "T15", "A"), ("T48", "T15", "B"),
    ("T49", "T06", "A"), ("T50", "T06", "B"),
    ("T51", "T01", "A"), ("T52", "T01", "B"),
    ("T53", "T25", "A"), ("T54", "T25", "B"),
    ("T55", "T40", "A"), ("T56", "T40", "B"),
    ("T57", "T33", "A"), ("T58", "T33", "B"),
)

# Ampliacao de 17/10/2026: variante B nos pais com total >= 100 ainda nao testados, A tambem nos genericos (total >= 5000); sem T06.
_COMPOSTOS_AMPLIACAO = (
    ("T59", "T03", "B"),
    ("T60", "T04", "B"),
    ("T61", "T07", "B"),
    ("T62", "T16", "B"),
    ("T63", "T26", "B"),
    ("T64", "T27", "B"),
    ("T65", "T28", "B"),
    ("T66", "T28", "A"),
    ("T67", "T29", "B"),
    ("T68", "T30", "B"),
    ("T69", "T31", "B"),
    ("T70", "T31", "A"),
    ("T71", "T32", "B"),
    ("T72", "T35", "B"),
    ("T73", "T36", "B"),
    ("T74", "T41", "B"),
    ("T75", "T41", "A"),
    ("T76", "T44", "B"),
)


def _montar_composto(termo_id, pai_id, variante):
    pai = _PAIS_TERMOS[pai_id]
    cfg = _CONTEXTOS_COMPOSTOS[pai.idioma]
    if variante == "A":
        return termo_composto(termo_id, pai, cfg["A"])
    return Termo(termo_id, f"{pai.query} {cfg['B']}", pai.idioma, pai.grupo, pai.id)


TERMOS_COMPOSTOS = [_montar_composto(tid, pid, var) for tid, pid, var in _COMPOSTOS_PILOTO + _COMPOSTOS_AMPLIACAO]

BASES_MANUAIS = ("IEEE", "ACM", "Scopus", "SBC OpenLib")

FILTROS_ACADEMICOS = FiltrosAcademicos(ano_inicial=None, ano_final=None, por_pagina=20)  # D79: sem filtro de ano na busca; o recorte de ano e feito na analise
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

# ---------- Busca de literatura cientifica e cinzenta (D103, D104, D105) ----------
# Consultas aprovadas pelo pesquisador em 21/10/2026, por conjunto de termos do orientador. Cada consulta e um pedido
# proprio (D105), sem aspas, e a mesma lista serve as duas fontes (Perplexity e Scholar).
CONJUNTOS_LITERATURA = {
    "A": (
        Termo("LA1", "inteligência artificial segurança pública viés algorítmico investigação criminal", "pt", "conjunto_A"),
        Termo("LA2", "inteligência artificial investigação criminal viés algorítmico", "pt", "conjunto_A"),
        Termo("LA3", "inteligência artificial segurança pública viés algorítmico", "pt", "conjunto_A"),
        Termo("LA4", "inteligência artificial segurança pública investigação criminal", "pt", "conjunto_A"),
        Termo("LA5", "viés algorítmico investigação criminal segurança pública", "pt", "conjunto_A"),
    ),
    "B": (
        Termo("LB1", "inteligência artificial segurança pública viés algorítmico discriminação ética", "pt", "conjunto_B"),
        Termo("LB2", "inteligência artificial segurança pública discriminação", "pt", "conjunto_B"),
        Termo("LB3", "inteligência artificial segurança pública ética", "pt", "conjunto_B"),
        Termo("LB4", "viés algorítmico discriminação segurança pública", "pt", "conjunto_B"),
        Termo("LB5", "inteligência artificial viés algorítmico ética", "pt", "conjunto_B"),
    ),
}
# Filtros da busca web desta frente (D103): 20 resultados por consulta, so paginas em portugues, pais Brasil.
FILTROS_LITERATURA_WEB = FiltrosBusca(max_resultados=20, idiomas=("pt",), pais="BR")

# Which URLs are worth downloading (cost and time control).
# (Keywords stay in Portuguese on purpose: they are matched against Portuguese titles/snippets.)
POLITICA_DOWNLOAD = PoliticaDownload(
    palavras_chave=("reconhecimento facial", "câmera", "camera", "videomonitoramento",
                    "inteligência artificial", "inteligencia artificial", "placas",
                    "preditiv", "licitação", "licitacao", "pregão", "pregao", "edital",
                    "monitoramento",
                    # RC14: tecnologia atendimento_virtual (sem estas palavras o pre-filtro descartaria o titulo/snippet)
                    "chatbot", "whatsapp", "atendimento virtual", "delegacia virtual", "boletim de ocorrencia"),
    max_urls_por_uf=40,
    dominios_excluir=("youtube.com", "tiktok.com", "twitter.com", "x.com"),
    apenas_oficiais=False,
)

assert len({t.id for t in TERMOS}) == len(TERMOS), "Duplicate term IDs"
assert len({t.id for t in TERMOS + TERMOS_COMPOSTOS}) == len(TERMOS + TERMOS_COMPOSTOS), "Duplicate term IDs across TERMOS and TERMOS_COMPOSTOS"
_ids_termos = {t.id for t in TERMOS}
assert all(t.pai in _ids_termos for t in TERMOS_COMPOSTOS), "Every pai of TERMOS_COMPOSTOS must exist in TERMOS"
_ids_literatura = [t.id for ts in CONJUNTOS_LITERATURA.values() for t in ts]
assert len(set(_ids_literatura)) == len(_ids_literatura), "Duplicate term IDs in CONJUNTOS_LITERATURA"
assert not set(_ids_literatura) & {t.id for t in TERMOS + TERMOS_COMPOSTOS}, "CONJUNTOS_LITERATURA ids must not reuse TERMOS ids"
assert len({m.id for m in MODELOS_WEB}) == len(MODELOS_WEB), "Duplicate template IDs"
assert len(UFS) == 27, "The state list must have 27 entries"
assert len({m.id for m in MODELOS_WEB + MODELOS_WEB_MUNICIPAIS}) == len(MODELOS_WEB + MODELOS_WEB_MUNICIPAIS), "Duplicate template IDs"
for _m in MODELOS_WEB + MODELOS_WEB_MUNICIPAIS:
    assert _m.perfil in PERFIS_BUSCA_WEB, f"Nonexistent profile: {_m.perfil}"
