"""Rotulos em portugues para toda chave que aparece na tela. As definicoes dos status vem de config/vocabulario."""
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
