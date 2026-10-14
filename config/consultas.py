from dominio.modelos import (Termo, ModeloConsultaWeb, FiltrosBusca,
                             FiltrosAcademicos, PoliticaDownload)

# ---------- Task 2: academic terms (Scholar + manual searches) ----------
TERMOS = [
    Termo("T01", '"artificial intelligence" AND "public security"', "en", "geral"),
    Termo("T02", '"facial recognition" AND police', "en", "reconhecimento_facial"),
    Termo("T03", '"predictive policing"', "en", "preditivo"),
    Termo("T04", '"inteligência artificial" AND "segurança pública"', "pt", "geral"),
    # >>> COLE AQUI O RESTANTE DA SUA LISTA, um Termo(...) por linha
]
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
for _m in MODELOS_WEB:
    assert _m.perfil in PERFIS_BUSCA_WEB, f"Nonexistent profile: {_m.perfil}"
