"""Rotulos em portugues para toda chave que aparece na tela. As definicoes dos status vem de config/vocabulario."""
NOMES_PESQUISA = {"real": "Secretarias Estaduais de Segurança Pública",
                  "vies": "Viés Algorítmico e Inteligência Artificial na Segurança Pública"}
TECNOLOGIAS = {
    "reconhecimento_facial": "Reconhecimento facial",
    "leitura_placas": "Leitura de placas de veículos",
    "videomonitoramento_inteligente": "Videomonitoramento inteligente",
    "analise_preditiva": "Análise preditiva / policiamento preditivo",
    "outra_ia": "Outra aplicação de IA",
    "atendimento_virtual": "Atendimento virtual (BO online, chatbot, WhatsApp)",
}
STATUS = {
    "em_uso": "Em uso", "piloto": "Piloto", "licitacao": "Licitação/contrato", "anunciado": "Anunciado",
    "em_estudo": "Em estudo", "apenas_citado": "Apenas citado", "descartado": "Descartado (achado incorreto)",
}
CONFIANCA = {"alta": "Alta", "media": "Média", "baixa": "Baixa"}
# etapas que fazem chamadas externas (chamadas.etapa)
ETAPAS = {"busca_academica": "busca acadêmica", "busca_web": "busca web", "busca_literatura": "busca de literatura na web",
          "download": "download de páginas", "classificacao": "classificação", "triagem_escopo": "triagem de escopo"}
# o que e cada ferramenta (chamadas.provedor, como o banco gravou), para a legenda das analises; provedor sem rotulo aparece
# com o proprio nome, e os modelos de linguagem pelo prefixo antes de ":"
FERRAMENTAS = {"perplexity_search": "API de busca na web do Perplexity", "serpapi_scholar": "Google Scholar, pela SerpApi",
               "serpapi_google": "busca do Google, pela SerpApi", "requests": "download direto das páginas, sem serviço pago"}
FAMILIAS_DE_MODELO = {"gemini": "modelo de linguagem Gemini", "openai_compat": "modelo de linguagem compatível com a API da OpenAI"}


def rotulo_ferramenta(provedor):
    """'gemini:gemini-3.5-flash-lite' -> 'modelo de linguagem Gemini (gemini-3.5-flash-lite)'; desconhecido: o proprio nome."""
    if provedor in FERRAMENTAS:
        return FERRAMENTAS[provedor]
    familia, _, modelo = (provedor or "").partition(":")
    if familia in FAMILIAS_DE_MODELO:
        return f"{FAMILIAS_DE_MODELO[familia]} ({modelo})" if modelo else FAMILIAS_DE_MODELO[familia]
    return provedor or "—"


# relevancia da triagem da busca de vies (gravada em triagem_escopo.status_bruto, D116)
RELEVANCIA_VIES = {"alta": "Alta", "media": "Média", "baixa": "Baixa", "fora_do_escopo": "Fora do escopo"}
ORIGEM_TEXTO = {"pagina": "Texto completo", "snippet": "Somente snippet"}
# O que "Somente snippet" quer dizer, para quem vê o selo (o modelo não leu a página)
EXPLICACAO_SNIPPET = ("O modelo não leu a página: recebeu só o título e o resumo do resultado de busca. A confiança fica limitada a "
                      "“baixa” e o trecho citado vem apenas desse resumo.")
MOTIVOS_DESCARTE = {
    "dominio_excluido": "Domínio na lista de exclusão", "nao_oficial": "Fonte não oficial",
    "prefiltro_palavras": "Sem palavras-chave no título/snippet", "limite_por_uf": "Limite de páginas por UF",
}
MOTIVOS_FALHA = {
    "texto_insuficiente": "Texto insuficiente na página", "tipo_nao_suportado": "Tipo de arquivo não suportado",
    "erro": "Erro na extração",
}
# Motivos de bloqueio do download (valores de `v_resultado_download.motivo` ligados ao robots.txt)
MOTIVOS_DOWNLOAD = {
    "bloqueado_por_robots": "Proibido pelo site (diretiva Disallow do robots.txt)",
    "robots_inacessivel": "Bloqueio preventivo (RFC 9309): robots.txt do site indisponível",
}
# Explicação curta de cada motivo (o que aconteceu e se foi decisão do site)
EXPLICACAO_MOTIVOS_DOWNLOAD = {
    "bloqueado_por_robots": "O robots.txt foi lido (HTTP 200) e a diretiva Disallow proíbe esta página: foi decisão do site.",
    "robots_inacessivel": "O robots.txt não pôde ser lido (erro 5xx, tempo esgotado ou falha de rede). Pela RFC 9309 a coleta assume que "
                          "tudo é proibido e não baixa a página: não foi decisão do site.",
}
APOS_REDIRECIONAMENTO = "após redirecionamento"
VERIFICACAO = {"pendente": "Não verificado", "confirmado": "Verificado", "descartado": "Descartado"}

# rotulos do fluxo PRISMA: a view v_prisma guarda a chave sem acento (usada no SQL e nos testes); a tela mostra o texto abaixo
PRISMA = {
    "execucoes de busca academica": "execuções de busca acadêmica",
    "Google Scholar: artigos unicos": "Google Scholar: artigos únicos",
    "buscas manuais: apos filtro da base (contagem informada)": "buscas manuais: após filtro da base (contagem informada)",
    "registros (artigo x fonte) apos remover duplicatas entre termos": "registros (artigo × fonte) após remover duplicatas entre termos",
    "removidos por ferramenta automatica (triagem de escopo do modelo, sem decisao humana)": "removidos por ferramenta automática (triagem de escopo do modelo, sem decisão humana)",
    "artigos unicos para triagem": "artigos únicos para triagem",
    "avaliados por titulo e resumo": "avaliados por título e resumo",
    "excluidos por titulo e resumo": "excluídos por título e resumo",
    "incluidos por titulo e resumo": "incluídos por título e resumo",
    "pendentes de titulo e resumo": "pendentes de título e resumo",
    "excluidos por texto completo": "excluídos por texto completo",
    "incluidos no estudo (texto completo)": "incluídos no estudo (texto completo)",
}


def rotulo(tabela, chave, padrao=None):
    return tabela.get(chave, padrao if padrao is not None else (chave or "—"))


def motivo_robots(erro):
    """Classifica o `erro` de uma chamada de download pelo robots.txt. Devolve None se o erro não é de robots.txt; senão
    {"chave": "bloqueado_por_robots" | "robots_inacessivel", "rotulo", "explicacao", "apos_redirecionamento": bool}.
    O motivo vem no começo do texto: `bloqueado_por_robots`, `robots_inacessivel` ou, depois de um redirecionamento,
    `<motivo>_apos_redirecionamento: <url>` (a mesma leitura da view v_resultado_download)."""
    texto = str(erro or "")
    for chave, rotulo in MOTIVOS_DOWNLOAD.items():
        if texto.startswith(chave):
            apos = texto[len(chave):].startswith("_apos_redirecionamento")
            return {"chave": chave, "rotulo": rotulo + (f", {APOS_REDIRECIONAMENTO}" if apos else ""),
                    "explicacao": EXPLICACAO_MOTIVOS_DOWNLOAD[chave], "apos_redirecionamento": apos}
    return None


def motivo_falha(valor):
    """`tipo_nao_suportado:application/zip` e `erro:...` trazem detalhe depois dos dois pontos."""
    if not valor:
        return "—"
    base, _, detalhe = str(valor).partition(":")
    return MOTIVOS_FALHA.get(base, base) + (f" ({detalhe[:60]})" if detalhe else "")
