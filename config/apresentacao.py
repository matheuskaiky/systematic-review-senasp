"""Textos da apresentação pública de cada pesquisa (Visão Geral para quem não entrou). Cada seção é uma tupla de parágrafos; a seção com PREENCHA ou fora do formato não aparece. Os textos são escritos pelo pesquisador."""

APRESENTACAO = {
    "real": {
        "descricao": ("Levantamento de evidências públicas sobre o uso, a experimentação, a contratação e o estudo de inteligência "
                      "artificial pelas secretarias estaduais de segurança pública do Brasil, com uma busca na literatura acadêmica "
                      "sobre o tema.",),
        "perguntas": ("Quais unidades da federação usam, testam, contratam ou estudam inteligência artificial na segurança "
                      "pública, como reconhecimento facial, leitura de placas, videomonitoramento inteligente, análise preditiva "
                      "e atendimento virtual?",
                      "O que a literatura acadêmica relata sobre aplicações de inteligência artificial na segurança pública no "
                      "Brasil?"),
        "metodo": ("Procedimento nas secretarias: buscas na web por unidade da federação e por tecnologia; leitura das páginas "
                   "encontradas, respeitando as regras de acesso de cada site; classificação das páginas por um modelo de "
                   "linguagem, que deve citar o trecho literal em que se apoia; conferência automática de que esse trecho está na "
                   "página; e verificação de cada achado por um pesquisador.",
                   "Procedimento na literatura: buscas no Google Scholar e buscas manuais nas bases IEEE, ACM, Scopus e SBC "
                   "OpenLib, remoção de duplicatas e triagem dos artigos por pesquisadores, registrada no fluxo PRISMA.",
                   "Estas etapas descrevem o procedimento da pesquisa, não o quanto dele já foi feito. A classificação pelo modelo "
                   "de linguagem não é uma decisão humana: só os achados e os artigos com decisão registrada por um pesquisador já "
                   "passaram pela verificação ou pela triagem."),
        "abrangencia": ("Fontes: páginas públicas na web encontradas por buscador; Google Scholar; IEEE, ACM, Scopus e SBC "
                        "OpenLib.",),
        "limitacoes": ("Os achados são identificados por um modelo de linguagem e só passam a contar como resultado da pesquisa "
                       "depois da verificação de um pesquisador; os que ainda não foram verificados não são resultados.",
                       "A ausência de menção nas páginas coletadas não significa que a tecnologia não seja usada.",
                       "A menção a uma tecnologia não comprova que ela esteja implantada.",
                       "A coleta depende do que o buscador devolve e das páginas que puderam ser lidas; sites que não permitem "
                       "leitura automática ficam de fora."),
        "instituicao": ("Pesquisa desenvolvida na Universidade Federal do Piauí (UFPI) para a Secretaria Nacional de Segurança "
                        "Pública (SENASP), do Ministério da Justiça e Segurança Pública.",),
    },
    "vies": {
        "descricao": ("Busca de literatura científica e cinzenta sobre viés algorítmico e inteligência artificial na segurança "
                      "pública, em páginas da web em português e no Google Scholar.",),
        "perguntas": ("PREENCHA",),
        "metodo": ("Procedimento: consultas na web em português e no Google Scholar, organizadas em conjuntos de consultas; "
                   "remoção de duplicatas entre as fontes; classificação automática de cada item por um modelo de linguagem "
                   "quanto ao tipo de fonte, ao país, aos tópicos e ao eixo temático; e triagem dos artigos por pesquisadores.",
                   "A classificação automática não constitui validação científica nem decisão humana. Estas etapas descrevem o "
                   "procedimento, não o quanto dele já foi feito: só os artigos com decisão registrada por um pesquisador já "
                   "passaram pela triagem humana."),
        "abrangencia": ("Fontes: páginas da web em português encontradas por buscador e Google Scholar.",),
        "limitacoes": ("Cada consulta traz só os primeiros resultados do buscador: o conjunto descreve o que a busca recuperou, não "
                       "toda a produção sobre o tema.",
                       "A classificação temática é feita por um modelo de linguagem a partir do título e do trecho devolvido pela "
                       "busca, sem leitura do texto completo.",
                       "A classificação automática não constitui validação científica. Uma conferência por pesquisadores de uma "
                       "amostra dessa classificação está prevista no método; até lá, os rótulos do modelo devem ser lidos como "
                       "exploratórios."),
        "instituicao": ("Pesquisa desenvolvida na UFPI para a SENASP.",),
    },
}
