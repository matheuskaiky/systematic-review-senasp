# key -> label used in the search queries
# (kept in Portuguese on purpose: the searches target Brazilian, Portuguese-language sites)
TECNOLOGIAS = {
    "reconhecimento_facial": "reconhecimento facial",
    "leitura_placas": "leitura de placas de veículos",
    "videomonitoramento_inteligente": "videomonitoramento inteligente câmeras",
    "analise_preditiva": "análise preditiva policiamento preditivo",
    "outra_ia": "inteligência artificial",
}

# key -> definition (goes into the prompt automatically)
STATUS = {
    "em_uso": "the technology is already deployed and operating",
    "piloto": "test, pilot project or partial deployment",
    "licitacao": "tender, auction, contract or acquisition in progress or signed",
    "anunciado": "announcement or future plan, with no proven contract or operation",
    "apenas_citado": "generic mention, with no indication of deployment by the agency",
}

STATUS_FINAL_EXTRA = ("descartado",)   # human decision: incorrect finding
CONFIANCA = ("alta", "media", "baixa")
