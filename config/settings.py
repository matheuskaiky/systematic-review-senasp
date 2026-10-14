import json
import hashlib
from dataclasses import asdict, is_dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DATA_DIR = RAIZ / "data"
LOG_DIR = RAIZ / "logs"
OUT_DIR = RAIZ / "outputs"

# >>> TO SWAP A PIECE, CHANGE THE NAME HERE (and register the adapter, see section 12)
PROVEDORES = {
    "busca_web": "perplexity_search",       # alternative: "serpapi_google"
    "academico": "serpapi_scholar",
    "fetcher": "requests",
    "extrator": "padrao",
    "classificador": "gemini",              # alternative: "openai_compat"
    "armazenamento": "sqlite",
    "bruto": "local",
    "exportador": "excel",
}

# Options per adapter (never put API keys here)
OPCOES = {
    "perplexity_search": {
        # TODO(verificar): campos extras aceitos pela API Perplexity Search (pais, idioma, datas)
        "corpo_extra": {},   # extra fields accepted by the API (country, language, dates...). Check the documentation.
    },
    "serpapi_google": {"pais": "br"},
    "serpapi_scholar": {},
    "requests": {
        "user_agent": "AcademicResearch-AIPublicSecurity/1.0 (contact: SEU_EMAIL)",
        "timeout": 30,
        "max_bytes": 8_000_000,
        "respeitar_robots": True,
    },
    "padrao": {"min_chars": 200},
    "gemini": {
        # The "latest" alias changes over time. For reproducibility, pin the exact version.
        # TODO(verificar): identificador atual do modelo Gemini, formato do responseSchema e precos
        "modelo": "gemini-flash-latest",
        "temperatura": 0.0,
        "max_tokens_saida": 4096,
        "preco_entrada_por_m": None,   # US$ per 1M tokens (fill in with the current price)
        "preco_saida_por_m": None,
    },
    "openai_compat": {
        "url": "https://api.openai.com/v1/chat/completions",
        "modelo": "PREENCHA",
        "temperatura": 0.0,
        "max_tokens": 4096,
        "usar_response_format": False,
        "preco_entrada_por_m": None,
        "preco_saida_por_m": None,
    },
    "sqlite": {"caminho": DATA_DIR / "busca.db"},
    "local": {"raiz": DATA_DIR / "raw"},
    "excel": {},
}

# adapter name -> environment variable holding the key
SEGREDOS = {
    "perplexity_search": "PERPLEXITY_API_KEY",
    "serpapi_google": "SERPAPI_KEY",
    "serpapi_scholar": "SERPAPI_KEY",
    "gemini": "GEMINI_API_KEY",
    "openai_compat": "LLM_API_KEY",
}

PAUSAS = {"busca_academica": 1.0, "busca_web": 0.5, "download": 1.0, "classificacao": 0.5}

# TODO(verificar): preco atual da Perplexity Search API por requisicao
PRECO_BUSCA_WEB_USD = 0.005     # per request (check the current price)

CLASSIFICACAO = {"max_chars_texto": 60_000, "usar_snippet_se_falhar": True}


def _plano(obj):
    """Serializa o que o json nao conhece; caminhos saem relativos a RAIZ (C12)."""
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, Path):
        try:
            return obj.relative_to(RAIZ).as_posix()
        except ValueError:
            return str(obj)
    return str(obj)


def snapshot_config():
    """Full snapshot of this run's configuration, with a hash."""
    from config import consultas as c, prompts as p, vocabulario as v
    conteudo = {
        "provedores": PROVEDORES,
        "opcoes": OPCOES,
        "termos": c.TERMOS, "filtros_academicos": c.FILTROS_ACADEMICOS,
        "max_paginas_academico": c.MAX_PAGINAS_ACADEMICO,
        "modelos_web": c.MODELOS_WEB, "perfis_busca_web": c.PERFIS_BUSCA_WEB,
        "politica_download": c.POLITICA_DOWNLOAD, "ufs": c.UFS,
        "tecnologias": v.TECNOLOGIAS, "status": v.STATUS,
        "prompt_versao": p.PROMPT_VERSAO, "prompt_sistema": p.PROMPT_SISTEMA,
        "prompt_usuario": p.PROMPT_USUARIO, "classificacao": CLASSIFICACAO,
    }
    texto = json.dumps(conteudo, sort_keys=True, ensure_ascii=False, default=_plano)
    return {"json": texto, "hash": hashlib.sha256(texto.encode()).hexdigest()[:12]}
