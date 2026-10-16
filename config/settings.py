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

# Perplexity Search API: US$ 5,00 por 1.000 requisicoes, cobradas por requisicao bem-sucedida e sem custo por token
# (docs.perplexity.ai/docs/getting-started/pricing, consultado em 14/10/2026). O modo `search_type: "fast"`
# custa US$ 1,00 por 1.000; para usa-lo, corpo_extra={"search_type": "fast"} e preco 0.001 (decisao do pesquisador).
PRECO_BUSCA_WEB_USD = 0.005     # per request

# Options per adapter (never put API keys here)
OPCOES = {
    "perplexity_search": {
        # TODO(verificar): demais campos extras aceitos pela API Perplexity Search (pais, idioma, datas); `search_type` existe
        "corpo_extra": {},   # extra fields accepted by the API (country, language, dates...). Check the documentation.
        "preco_por_requisicao_usd": PRECO_BUSCA_WEB_USD,   # gravado em chamadas.custo_usd a cada requisicao aceita
    },
    "serpapi_google": {"pais": "br"},
    "serpapi_scholar": {},
    "requests": {
        # {email} e trocado pela composicao com o valor da variavel EMAIL_PESQUISADOR_ENV (nunca fixo aqui)
        "user_agent": "AcademicResearch-AIPublicSecurity/1.0 (contact: {email})",
        "timeout": 30,
        "max_bytes": 8_000_000,
        "respeitar_robots": True,
        "tempo_maximo": 120,                  # prazo total por download, em segundos (timeout vale por leitura)
        "max_redirecionamentos": 5,
        # robots.txt com 5xx ou ilegivel: "permitir" (especificacao) ou "bloquear" (RFC 9309).
        # Decisao do pesquisador (14/10/2026): bloquear.
        "robots_se_inacessivel": "bloquear",
    },
    "padrao": {"min_chars": 200},
    "gemini": {
        # Identificador e precos conferidos na documentacao oficial em 14/10/2026 (ai.google.dev): modelo
        # gemini-3.5-flash-lite; US$ 0,30 por 1M tokens de entrada e US$ 2,50 de saida (raciocinio conta como saida).
        # O raciocinio vem ligado em nivel minimo por padrao, e max_output_tokens inclui os tokens de raciocinio.
        "modelo": "gemini-3.5-flash-lite",
        "temperatura": 0.0,
        "max_tokens_saida": 4096,
        "preco_entrada_por_m": 0.3,   # US$ per 1M tokens
        "preco_saida_por_m": 2.5,
        # Formato do esquema: o guia oficial de saida estruturada (consultado em 14/10/2026) documenta
        # generationConfig.responseFormat.text.{mimeType, schema} com JSON Schema; decisao do pesquisador: seguir a
        # documentacao. Na referencia REST o mimeType e um enum (APPLICATION_JSON): a 1a chamada real, com o texto
        # "application/json" do exemplo do guia, recebeu HTTP 400. Alternativas: "responseSchema" (formato da
        # especificacao) e "responseJsonSchema".
        # TODO(verificar): aceitacao de APPLICATION_JSON pelo modelo, confirmada so por uma chamada real bem-sucedida.
        # A documentacao rotula o generateContent como "Legacy" (a API nova e a Interactions API).
        "formato_esquema": "responseFormat",
    },
    "openai_compat": {
        "url": "https://api.openai.com/v1/chat/completions",
        "modelo": "PREENCHA",
        "temperatura": 0.0,
        "max_tokens": 4096,
        # C14: alguns modelos rejeitam `max_tokens` (esperam "max_completion_tokens") ou qualquer temperatura
        # (use temperatura None para omitir o campo). TODO(verificar): o que cada provedor aceita.
        "campo_max_tokens": "max_tokens",
        "usar_response_format": False,
        "preco_entrada_por_m": None,
        "preco_saida_por_m": None,
    },
    "sqlite": {"caminho": DATA_DIR / "busca.db"},
    "local": {"raiz": DATA_DIR / "raw"},
    "excel": {"pasta": OUT_DIR},
}

# adapter name -> environment variable holding the key
SEGREDOS = {
    "perplexity_search": "PERPLEXITY_API_KEY",
    "serpapi_google": "SERPAPI_KEY",
    "serpapi_scholar": "SERPAPI_KEY",
    "gemini": "GEMINI_API_KEY",
    "openai_compat": "LLM_API_KEY",
}

# variavel de ambiente com o e-mail de contato do pesquisador (vai no User-Agent dos downloads)
EMAIL_PESQUISADOR_ENV = "RESEARCHER_EMAIL"

PAUSAS = {"busca_academica": 1.0, "busca_web": 0.5, "download": 1.0, "classificacao": 0.5}

# max_falhas_por_item: apos N chamadas com falha para o mesmo item na mesma execucao, o item e abandonado (evita pagar
# de novo, a cada --retomar, uma resposta que falha sempre igual, como a truncada por MAX_TOKENS)
CLASSIFICACAO = {"max_chars_texto": 60_000, "usar_snippet_se_falhar": True, "max_falhas_por_item": 3}

# max_falhas_por_pagina: apos N chamadas de download com falha para a mesma pagina na mesma execucao, a pagina e abandonada
# nas retomadas (--retomar), sem insistir indefinidamente em um site fora do ar ou que recusa sempre.
# Entra em `snapshot_config()`: muda o hash de configuracao das execucoes NOVAS; as execucoes antigas ja terminaram e
# guardam o hash que tinham (nao ha retomada delas com esta versao).
DOWNLOAD = {"max_falhas_por_pagina": 3}


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
        "modelos_web_municipais": c.MODELOS_WEB_MUNICIPAIS, "municipios": c.MUNICIPIOS,
        "politica_download": c.POLITICA_DOWNLOAD, "ufs": c.UFS,
        "tecnologias": v.TECNOLOGIAS, "status": v.STATUS,
        "prompt_versao": p.PROMPT_VERSAO, "prompt_sistema": p.SYSTEM_PROMPT,
        "prompt_usuario": p.USER_PROMPT, "classificacao": CLASSIFICACAO,
        "download": DOWNLOAD,
    }
    texto = json.dumps(conteudo, sort_keys=True, ensure_ascii=False, default=_plano)
    return {"json": texto, "hash": hashlib.sha256(texto.encode()).hexdigest()[:12]}
