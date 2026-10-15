"""Rotulos em portugues para toda chave que aparece na tela. As definicoes dos status vem de config/vocabulario."""
TECNOLOGIAS = {
    "reconhecimento_facial": "Reconhecimento facial",
    "leitura_placas": "Leitura de placas de veículos",
    "videomonitoramento_inteligente": "Videomonitoramento inteligente",
    "analise_preditiva": "Análise preditiva / policiamento preditivo",
    "outra_ia": "Outra aplicação de IA",
}
STATUS = {
    "em_uso": "Em uso", "piloto": "Piloto", "licitacao": "Licitação/contrato", "anunciado": "Anunciado",
    "em_estudo": "Em estudo", "apenas_citado": "Apenas citado", "descartado": "Descartado (achado incorreto)",
}
CONFIANCA = {"alta": "Alta", "media": "Média", "baixa": "Baixa"}
ORIGEM_TEXTO = {"pagina": "Texto da página", "snippet": "Somente snippet"}
MOTIVOS_DESCARTE = {
    "dominio_excluido": "Domínio na lista de exclusão", "nao_oficial": "Fonte não oficial",
    "prefiltro_palavras": "Sem palavras-chave no título/snippet", "limite_por_uf": "Limite de páginas por UF",
}
MOTIVOS_FALHA = {
    "texto_insuficiente": "Texto insuficiente na página", "tipo_nao_suportado": "Tipo de arquivo não suportado",
    "erro": "Erro na extração",
}
VERIFICACAO = {"pendente": "Não verificado", "confirmado": "Verificado", "descartado": "Descartado"}


def rotulo(tabela, chave, padrao=None):
    return tabela.get(chave, padrao if padrao is not None else (chave or "—"))


def motivo_falha(valor):
    """`tipo_nao_suportado:application/zip` e `erro:...` trazem detalhe depois dos dois pontos."""
    if not valor:
        return "—"
    base, _, detalhe = str(valor).partition(":")
    return MOTIVOS_FALHA.get(base, base) + (f" ({detalhe[:60]})" if detalhe else "")
