"""Rotulos e explicacoes, em portugues claro, dos campos da triagem de escopo feita por LLM. Dados puros (sem I/O).
O que a tela mostra para uma chave desconhecida e a propria chave, nunca um erro."""
STATUS = {"elegivel": "Elegível", "quarentena": "Quarentena", "excluido": "Excluído pelo modelo"}
STATUS_ICONE = {"elegivel": "✔", "quarentena": "◐", "excluido": "✕"}
STATUS_EXPLICA = {
    "elegivel": "O modelo julga o item possivelmente útil para o escopo da pesquisa. Aparece normalmente nas listas.",
    "quarentena": "O modelo tem dúvida (informação ausente, cortada ou ambígua) e, na dúvida, não exclui. Aparece normalmente nas listas, "
                  "com o motivo da dúvida.",
    "excluido": "O modelo classificou o item como fora do escopo, com confiança alta, e a conferência automática aprovou a resposta. "
                "Fica oculto das listas por padrão (quarentena temporária), mas nunca é apagado: você pode "
                "mostrá-lo a qualquer momento e a sua decisão sempre prevalece.",
}
CATEGORIAS = {
    "FORA_SEGURANCA_PUBLICA": "fora de segurança pública", "SEM_IA_OU_TECNOLOGIA": "sem IA ou tecnologia",
    "METODOLOGIA_IRRELEVANTE": "metodologia irrelevante", "AMBIGUIDADE_LEXICAL": "ambiguidade lexical",
    "FORA_DO_RECORTE_TEMPORAL": "fora do recorte temporal", "FORA_DO_RECORTE_GEOGRAFICO": "fora do recorte geográfico",
    "RUIDO_WEB": "ruído web",
}
CATEGORIAS_EXPLICA = {
    "FORA_SEGURANCA_PUBLICA": "O item não trata de segurança pública, policiamento, perícia, justiça criminal ou defesa social "
                              "(por exemplo, um artigo de saúde ou de agricultura que casou com um termo da busca).",
    "SEM_IA_OU_TECNOLOGIA": "O item trata de segurança pública, mas não de inteligência artificial nem de análise automatizada de dados.",
    "METODOLOGIA_IRRELEVANTE": "Divulgação genérica, opinião superficial, sem dados e sem caráter científico ou técnico.",
    "AMBIGUIDADE_LEXICAL": "Um termo da consulta tem mais de um sentido e capturou o item fora do contexto que a pesquisa quer.",
    "FORA_DO_RECORTE_TEMPORAL": "Artigo publicado antes de 2022. Por padrão fica fora do recorte; só deixa de ser excluído se o modelo o "
                                "achar útil mesmo assim (aí aparece como elegível ou em quarentena e a justificativa diz por quê).",
    "FORA_DO_RECORTE_GEOGRAFICO": "Item estrangeiro e sem utilidade para o contexto brasileiro. Sozinho só leva à quarentena, porque "
                                  "literatura internacional pode servir de referência; só é excluído se também estiver fora do tema.",
    "RUIDO_WEB": "Página de erro, catálogo sem texto ou ruído de indexação do buscador.",
}
DOMINIOS = {
    "seguranca_publica": "Segurança pública", "justica_penal": "Justiça penal", "defesa_militar": "Defesa e militar",
    "ciberseguranca": "Cibersegurança", "saude": "Saúde", "educacao": "Educação",
    "agropecuaria_meio_ambiente": "Agropecuária e meio ambiente", "industria_engenharia": "Indústria e engenharia",
    "transito_transporte": "Trânsito e transporte", "administracao_publica": "Administração pública",
    "direito_etica_geral": "Direito e ética (geral)", "computacao_geral": "Computação (geral)",
    "negocios_economia": "Negócios e economia", "outro": "Outro",
}
ESCOPOS = {"brasil": "Brasil", "internacional": "Internacional", "indeterminado": "Indeterminado"}
TIPOS = {
    "artigo_periodico": "Artigo de periódico", "artigo_congresso": "Artigo de congresso", "livro_capitulo": "Livro ou capítulo",
    "tese_dissertacao": "Tese ou dissertação", "relatorio_tecnico": "Relatório técnico",
    "noticia_pagina_institucional": "Notícia ou página institucional", "outro": "Outro", "indeterminado": "Indeterminado",
}
FILTRO_STATUS = {"": "elegível e quarentena (padrão)", "todos": "todos, inclusive excluídos", "elegivel": "só elegíveis",
                 "quarentena": "só em quarentena", "excluido": "só excluídos pelo modelo"}
VEREDITOS = {"seguro": "Seguro", "arriscado": "Arriscado", "perigoso": "Perigoso"}
VEREDITO_ICONE = {"seguro": "✔", "arriscado": "⚠", "perigoso": "✕"}
VEREDITO_EXPLICA = {
    "seguro": "Nenhum item bom (elegível, em quarentena ou incluído por você) contém o texto.",
    "arriscado": "Alguns itens bons contêm o texto, mas são poucos (até 5% dos itens que o contêm).",
    "perigoso": "Muitos itens bons contêm o texto, ou o texto é uma palavra central do tema. Não use sem conferir.",
}


def rotulo(tabela, chave, padrao=None):
    return tabela.get(chave, padrao if padrao is not None else (chave or "—"))
