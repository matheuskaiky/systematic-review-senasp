"""Configuracao da triagem de escopo por LLM (comando `triar-escopo`).

Os criterios de escopo do prompt sao um RASCUNHO a partir do objetivo do projeto e dependem da confirmacao do
pesquisador: eles estao aqui, em constantes de texto, para serem editados em um unico lugar. Mudou o texto, mude
`PROMPT_TRIAGEM_VERSAO`: a versao fica gravada em cada linha de `triagem_escopo` e decide o que ja foi triado.

O texto do prompt e em ingles e a saida em portugues (convencao D1 do projeto). Este modulo nao faz parte do
`snapshot_config()` de `config/settings.py` (a execucao grava a configuracao da triagem em separado).
"""
from dominio.triagem_escopo import ConfigTriagem, SEM_CATEGORIA

PROMPT_TRIAGEM_VERSAO = "t2"   # t2 (16/10/2026): a excecao dos anos antigos passou a ser usada (ver a secao 8 de docs/GUIA_DO_PROJETO.md)

# ----- vocabularios fechados (os valores do enum sao em portugues) -----
STATUS = ("elegivel", "quarentena", "excluido")
CONFIANCA = ("alta", "media", "baixa")
CATEGORIAS_MOTIVO = (
    "FORA_SEGURANCA_PUBLICA", "SEM_IA_OU_TECNOLOGIA", "METODOLOGIA_IRRELEVANTE", "AMBIGUIDADE_LEXICAL",
    "FORA_DO_RECORTE_TEMPORAL", "FORA_DO_RECORTE_GEOGRAFICO", "RUIDO_WEB",
)
DOMINIOS_TEMATICOS = (
    "seguranca_publica", "justica_penal", "defesa_militar", "ciberseguranca", "saude", "educacao",
    "agropecuaria_meio_ambiente", "industria_engenharia", "transito_transporte", "administracao_publica",
    "direito_etica_geral", "computacao_geral", "negocios_economia", "outro",
)
ESCOPOS_GEOGRAFICOS = ("brasil", "internacional", "indeterminado")
TIPOS_DOCUMENTO = (
    "artigo_periodico", "artigo_congresso", "livro_capitulo", "tese_dissertacao", "relatorio_tecnico",
    "noticia_pagina_institucional", "outro", "indeterminado",
)

# ----- tamanhos e custo -----
LOTE_PADRAO = 10                     # itens por chamada
LOTE_MAXIMO = 50                     # acima disso o comando recusa (a janela de contexto nao limita; a saida e a revisao sim)
JANELA_CONTEXTO_TOKENS = 1_048_576   # entrada maxima do gemini-3.5-flash-lite (documentacao oficial, conferida em 16/10/2026)
ANO_MINIMO = 2022                    # artigo com ano conhecido anterior a este esta fora do recorte temporal por padrao
SNIPPET_MAX_CHARS = 1200             # o resumo enviado ao modelo (e conferido pelo codigo) e cortado aqui
MAX_CUSTO_PADRAO_USD = 0.20          # teto de custo por execucao quando --max-custo nao e informado
MAX_TOKENS_SAIDA = 8192              # um lote de 10 itens precisa de ~2.000 tokens de saida, mais o raciocinio
MAX_FALHAS_POR_LOTE = 3              # apos N falhas do mesmo lote na mesma execucao, o lote e abandonado
PAUSA_SEGUNDOS = 0.5

# Nivel gratuito do Gemini: 500 requisicoes por dia por projeto e por modelo. O numero vem do corpo real do erro 429
# observado em 15/10/2026 (quotaId GenerateRequestsPerDayPerProjectPerModel-FreeTier) e PODE SER OUTRO no nivel pago.
# A cota e compartilhada com as demais etapas que usam o mesmo modelo e a mesma chave (a classificacao).
LIMITE_DIARIO_GRATUITO = 500

# Estimativa de custo (ordem de grandeza: nao ha o tokenizador oficial; 3,4 caracteres por token e uma aproximacao)
CARACTERES_POR_TOKEN = 3.4
TOKENS_METADADOS_POR_ITEM = 50
TOKENS_FIXOS_POR_CHAMADA = 1500      # instrucoes e esquema
SAIDA_POR_ITEM = {"baixo": 90, "medio": 120, "alto": 160}                 # tokens de saida por item
RACIOCINIO_POR_CHAMADA = {"baixo": 100, "medio": 300, "alto": 600}        # tokens de raciocinio por chamada

# ----- prompt -----
_BASE_SISTEMA = """You screen search results for a systematic review on artificial intelligence (AI) in Brazilian public security.
Write all free text in Brazilian Portuguese (pt-BR). Use the enum values exactly as listed.

SCOPE (draft criteria):
{escopo}

DECISION RULE (asymmetric, important):
- "elegivel": plausibly useful for the scope.
- "excluido": ONLY when you are ABSOLUTELY CERTAIN, from the title and snippet, that the item is useless for the scope.
  Then "confianca" must be "alta".
- "quarentena": anything else, including missing, truncated or ambiguous information. WHEN IN DOUBT, "quarentena".
- TEMPORAL RULE: an article with a known publication year before 2022 is out of scope by default: status "excluido",
  categoria_motivo FORA_DO_RECORTE_TEMPORAL, confianca "alta". EXCEPTION, which you MUST apply when it fits: if the
  article is directly about AI or automated data analysis applied to public security, policing, forensics or criminal
  justice (Brazilian or not), or is a Brazilian study that is clearly useful for the scope, do NOT exclude it by date:
  answer "quarentena" with categoria_motivo FORA_DO_RECORTE_TEMPORAL (the date is the only reason it is not "elegivel"),
  or "elegivel" if it is clearly foundational or highly pertinent, and say in "justificativa" why it may still be useful.
  Articles before 2022 that are off-topic, generic or only tangentially related stay "excluido". Unknown year: no
  temporal rule.
- A non-Brazilian item is NOT excluded for that reason alone (it may be useful background). Record it
  in "escopo_geografico". Exclude it only if it is also off-topic.

REASON CATEGORIES (required when status is "quarentena" or "excluido"; use "NENHUMA" when "elegivel"):
FORA_SEGURANCA_PUBLICA (not about public security, policing, forensics, criminal justice or social defense),
SEM_IA_OU_TECNOLOGIA (public security, but no AI or automated data analysis),
METODOLOGIA_IRRELEVANTE (generic outreach, shallow opinion, no data, not scientific or technical),
AMBIGUIDADE_LEXICAL (a polysemic query term captured outside the intended context),
FORA_DO_RECORTE_TEMPORAL (published before 2022),
FORA_DO_RECORTE_GEOGRAFICO (non-Brazilian AND not transferable; use only with "quarentena" unless also off-topic),
RUIDO_WEB (error page, catalog without text, indexing noise).

INPUT: one item per line, as JSON. Return exactly one object per item, in any order, echoing its "id" unchanged.
Never skip an item and never repeat an id.

OTHER FIELDS:
- "justificativa": at most 20 words, objective.
- "termo_gerador_ruido": the ONE term from the item's "query_terms" list, copied exactly, that most likely caused this
  item to be captured. Empty string if "elegivel".
- "sinal_negativo": a word or short phrase (at most 3 words) copied LITERALLY from the title or snippet that
  characterizes this kind of noise and could be used as a negative search operator. Empty string if none, if "elegivel",
  or if the phrase is central to the research topic (never suggest excluding a core topic word).
- "dominio_tematico": one of {dominios}.
- "escopo_geografico": {geograficos}.
- "tipo_documento": {tipos}.
Judge only what the title and snippet show. Do not invent facts."""

_ESCOPO_ARTIGOS = """- Articles: IN SCOPE if the document addresses AI or automated data-analysis technologies (facial recognition and
  biometrics, automatic license-plate reading, intelligent video monitoring or video analytics, predictive policing and
  crime analytics, chatbots and virtual police stations, command-and-control centers with AI, drones with AI,
  gunshot detection, machine learning or big data) applied to public security, policing, forensics, criminal justice
  or the penal system. Brazilian context is preferred. Publication year must be 2022 or later."""

_ESCOPO_WEB = """- Web results: IN SCOPE if the page is from, or about, a Brazilian public-security body and describes the use,
  procurement, pilot, announcement or study of such technologies (AI or automated data-analysis technologies: facial
  recognition and biometrics, automatic license-plate reading, intelligent video monitoring or video analytics,
  predictive policing and crime analytics, chatbots and virtual police stations, command-and-control centers with AI,
  drones with AI, gunshot detection, machine learning or big data)."""


def _sistema(escopo):
    # a base tem chaves literais? Nao: so os marcadores abaixo; usa replace para nao depender de format
    return (_BASE_SISTEMA.replace("{escopo}", escopo)
            .replace("{dominios}", ", ".join(DOMINIOS_TEMATICOS))
            .replace("{geograficos}", ", ".join(ESCOPOS_GEOGRAFICOS))
            .replace("{tipos}", ", ".join(TIPOS_DOCUMENTO)))


SISTEMA_ARTIGO = _sistema(_ESCOPO_ARTIGOS)
SISTEMA_WEB = _sistema(_ESCOPO_WEB)

# Mensagem do usuario: `{n}` itens, `{origem}` descreve a fonte, `{linhas}` e uma linha JSON por item.
USUARIO_TEMPLATE = (
    "Screen the following {n} items ({origem}). Return one object per item, echoing each \"id\".\n"
    "Items (one JSON object per line):\n{linhas}"
)
ORIGEM_ARTIGO = "scholarly articles found by academic searches"
ORIGEM_WEB = "web search results about Brazilian state public-security bodies"

CONFIG = ConfigTriagem(
    versao=PROMPT_TRIAGEM_VERSAO,
    sistema_artigo=SISTEMA_ARTIGO, sistema_web=SISTEMA_WEB,
    usuario_template=USUARIO_TEMPLATE, origem_artigo=ORIGEM_ARTIGO, origem_web=ORIGEM_WEB,
    status=STATUS, confianca=CONFIANCA, categorias_motivo=CATEGORIAS_MOTIVO,
    dominios_tematicos=DOMINIOS_TEMATICOS, escopos_geograficos=ESCOPOS_GEOGRAFICOS, tipos_documento=TIPOS_DOCUMENTO,
    lote_padrao=LOTE_PADRAO, lote_maximo=LOTE_MAXIMO, janela_contexto_tokens=JANELA_CONTEXTO_TOKENS,
    ano_minimo=ANO_MINIMO, snippet_max_chars=SNIPPET_MAX_CHARS, max_custo_padrao_usd=MAX_CUSTO_PADRAO_USD,
    caracteres_por_token=CARACTERES_POR_TOKEN, tokens_metadados_por_item=TOKENS_METADADOS_POR_ITEM,
    tokens_fixos_por_chamada=TOKENS_FIXOS_POR_CHAMADA,
    saida_por_item=dict(SAIDA_POR_ITEM), raciocinio_por_chamada=dict(RACIOCINIO_POR_CHAMADA))

# ----- triagem curta dos artigos anteriores a ANO_MINIMO (D80): so relevancia e escopo geografico -----
PROMPT_TRIAGEM_CURTA_VERSAO = "c1"
LOTE_PADRAO_CURTA = 40
LOTE_MAXIMO_CURTA = 100
SNIPPET_MAX_CHARS_CURTA = 300
TOKENS_FIXOS_POR_CHAMADA_CURTA = 400
TOKENS_METADADOS_POR_ITEM_CURTA = 15
SAIDA_POR_ITEM_CURTA = {"baixo": 15, "medio": 20, "alto": 25}
ORIGEM_ARTIGO_CURTA = "scholarly articles published before 2022"

SISTEMA_CURTO = """You rate the relevance of scholarly articles published before 2022 for a systematic review on artificial intelligence (AI) in Brazilian public security.
Judge only the title and snippet. Do not invent facts.

"relevancia":
- "alta": directly about AI or automated data analysis applied to public security, policing, forensics, criminal justice
  or the penal system (Brazilian or not), or a Brazilian study clearly useful for that scope.
- "media": related to the scope but indirect, or the title and snippet are not enough to decide.
- "baixa": off-topic, generic or only tangentially related.
When in doubt between "baixa" and another level, answer "media".

"confianca": how sure you are of "relevancia": alta, media or baixa. A "baixa" relevance without "alta" confidence is kept
for human review.

"escopo_geografico": brasil, internacional or indeterminado.

INPUT: one item per line, as JSON. Return exactly one object per item, echoing its "id" unchanged.
Never skip an item and never repeat an id."""

CONFIG_CURTA = ConfigTriagem(
    versao=PROMPT_TRIAGEM_CURTA_VERSAO,
    sistema_artigo=SISTEMA_CURTO, sistema_web="",
    usuario_template=USUARIO_TEMPLATE, origem_artigo=ORIGEM_ARTIGO_CURTA, origem_web="",
    status=STATUS, confianca=CONFIANCA, categorias_motivo=CATEGORIAS_MOTIVO,
    dominios_tematicos=DOMINIOS_TEMATICOS, escopos_geograficos=ESCOPOS_GEOGRAFICOS, tipos_documento=TIPOS_DOCUMENTO,
    lote_padrao=LOTE_PADRAO_CURTA, lote_maximo=LOTE_MAXIMO_CURTA, janela_contexto_tokens=JANELA_CONTEXTO_TOKENS,
    ano_minimo=ANO_MINIMO, snippet_max_chars=SNIPPET_MAX_CHARS_CURTA, max_custo_padrao_usd=MAX_CUSTO_PADRAO_USD,
    caracteres_por_token=CARACTERES_POR_TOKEN, tokens_metadados_por_item=TOKENS_METADADOS_POR_ITEM_CURTA,
    tokens_fixos_por_chamada=TOKENS_FIXOS_POR_CHAMADA_CURTA,
    saida_por_item=dict(SAIDA_POR_ITEM_CURTA), raciocinio_por_chamada=dict(RACIOCINIO_POR_CHAMADA), curta=True)

# a categoria que a regra de seguranca trata a parte esta no dominio; o marcador "sem categoria" tambem
assert SEM_CATEGORIA not in CATEGORIAS_MOTIVO

# ----- triagem da busca de vies algoritmico (banco `vies`, D111): o escopo combinado para esta busca -----
# Os artigos do Scholar e as referencias da web achados pelos conjuntos A e B. A saida preenche as colunas "Tipo de
# fonte", "Pais/escopo" e "Topicos e palavras-chave" do modelo de referencias; relevancia, eixo e justificativa vao alem
# do modelo e aparecem so na pagina de cada resultado.
PROMPT_TRIAGEM_VIES_VERSAO = "v1"
RELEVANCIAS_VIES = ("alta", "media", "baixa", "fora_do_escopo")
# Os 43 tipos-base aprovados (D110), em ordem alfabetica; o sufixo e posto pelo codigo, nunca pelo modelo
TIPOS_FONTE = (
    "Artigo científico", "Artigo jurídico", "Artigo técnico", "Capítulo de livro", "Dissertação",
    "Documento de especialista", "Documento de trabalho", "Documento internacional", "Documento regulatório",
    "Documento técnico", "Dossiê", "Estudo de caso", "Estudo empírico", "Jornalismo investigativo", "Livro",
    "Manifesto técnico", "Manual técnico", "Norma", "Norma técnica", "Nota de pesquisa", "Notícia oficial",
    "Periódico institucional", "Petição", "Policy brief", "Policy paper", "Projeto", "Projeto de pesquisa", "Regulação",
    "Relatório", "Relatório governamental", "Relatório institucional", "Relatório técnico", "Reportagem", "Resolução",
    "Revisão bibliométrica", "Revisão de escopo", "Revisão narrativa", "Revisão sistemática", "TCC",
    "Trabalho acadêmico", "Verbete", "Working paper", "Solução tecnológica / produto",
)
TIPOS_FONTE_PRIMARIA = ("Norma", "Norma técnica", "Regulação", "Resolução", "Documento regulatório")
TIPOS_LITERATURA_CIENTIFICA = (
    "Artigo científico", "Artigo jurídico", "Capítulo de livro", "Dissertação", "Livro", "Revisão bibliométrica",
    "Revisão de escopo", "Revisão narrativa", "Revisão sistemática", "TCC", "Trabalho acadêmico",
)
SUFIXOS_TIPO_FONTE = {t: ("" if t in TIPOS_LITERATURA_CIENTIFICA else
                          " / fonte primária" if t in TIPOS_FONTE_PRIMARIA else " / literatura cinzenta")
                      for t in TIPOS_FONTE}
SEM_EIXO = "Nenhum"
LOTE_PADRAO_VIES = 10
LOTE_MAXIMO_VIES = 25                # 25 itens x ~220 tokens de saida, mais o raciocinio, cabem em MAX_TOKENS_SAIDA
TOKENS_FIXOS_POR_CHAMADA_VIES = 2000  # o prompt (~1.300 tokens) e o esquema (~550)
SNIPPET_MAX_CHARS_VIES = 1200
MAX_CUSTO_PADRAO_VIES_USD = 0.50
SAIDA_POR_ITEM_VIES = {"baixo": 120, "medio": 160, "alto": 220}
ORIGEM_ARTIGO_VIES = "scholarly articles found by Google Scholar searches in Portuguese"
ORIGEM_REFERENCIA_VIES = "web pages found by web searches in Portuguese"

_SISTEMA_VIES = """You screen search results for a literature review on artificial intelligence (AI) in public security,
with emphasis on ALGORITHMIC BIAS, CRIMINAL INVESTIGATION, DISCRIMINATION and ETHICS.
Write all free text in Brazilian Portuguese (pt-BR). Use the enum values exactly as listed.

SCOPE (agreed for this research):
- The searches combined: artificial intelligence + public security + algorithmic bias + criminal investigation; and
  artificial intelligence + public security + algorithmic bias + discrimination + ethics. Searches were in Portuguese.
- Include traditional scientific literature AND grey literature (websites, technical documents, reports, documents not
  published in scientific databases), technological solutions, products, empirical studies, regulation and anything
  related to the subject. Items from any country and any year may be useful.
- Out of scope: items unrelated to AI or automated decision systems, or unrelated to public security, policing,
  criminal investigation, forensics, criminal justice or the rights affected by them.

"relevancia":
- "alta": directly about AI or algorithms in public security, policing, criminal investigation, forensics or criminal
  justice AND about bias, discrimination, ethics, rights or governance; or an empirical study, technological solution or
  product in that area.
- "media": AI in public security without the bias or ethics angle; or bias and ethics of AI in another area that
  transfers clearly to public security.
- "baixa": only tangentially related.
- "fora_do_escopo": unrelated. Use it ONLY when you are certain; then "confianca" must be "alta".
When in doubt, prefer the higher level.

"confianca": how sure you are of "relevancia": alta, media or baixa.

"tipo_fonte": exactly one of: {tipos}.
Choose the closest type from what the title, snippet, authors and URL show (a news site: "Reportagem"; a government
news page: "Notícia oficial"; a vendor page: "Solução tecnológica / produto"; a law: "Regulação" or "Norma").

"pais_escopo": the country or scope of the item, short, in Portuguese, as in "Brasil", "Brasil / SP", "EUA",
"Reino Unido", "União Europeia", "América Latina", "Internacional" or "Global". At most 40 characters. If the item does
not show it, answer "Indeterminado" (never guess "Brasil" only because the search was in Portuguese).

"topicos": 1 to 5 short topics, in Portuguese, each at most 6 words, as a spreadsheet would list them: the first one
capitalized, the others in lower case, acronyms kept (IA, LGPD, COMPAS). For example ["Reconhecimento facial",
"viés interseccional", "avaliação"]. Details of the source type (for example "conferência", "ensaio controlado") go
here, not in "tipo_fonte". Never query codes, never the whole title.

"eixo": the ONE exploration axis that fits best, or "{sem_eixo}": {eixos}.

"justificativa": at most 25 words, objective, saying why the item has this relevance.

INPUT: one item per line, as JSON, with "id", "query_terms" (the searches that found it), "titulo", "resumo" (the
search snippet), "autores_publicacao" (authors, venue and year, for articles), "ano" (null if unknown), "url" and "host".
Return exactly one object per item, echoing its "id" unchanged. Never skip an item and never repeat an id. Judge only
what the item shows. Do not invent facts."""


def sistema_vies(eixos):
    """O prompt de sistema da triagem de vies com os 6 eixos do esquema de exploracao (nome: perguntas)."""
    return (_SISTEMA_VIES.replace("{tipos}", "; ".join(TIPOS_FONTE)).replace("{sem_eixo}", SEM_EIXO)
            .replace("{eixos}", " ".join(f'"{e}" ({q})' for e, q in eixos.items())))


def config_vies(eixos):
    """A configuracao da triagem do banco `vies`. `eixos`: os 6 eixos do esquema de exploracao (config.eixos_tematicos)."""
    return ConfigTriagem(
        versao=PROMPT_TRIAGEM_VIES_VERSAO,
        sistema_artigo=sistema_vies(eixos), sistema_web=sistema_vies(eixos),
        usuario_template=USUARIO_TEMPLATE, origem_artigo=ORIGEM_ARTIGO_VIES, origem_web=ORIGEM_REFERENCIA_VIES,
        status=STATUS, confianca=CONFIANCA, categorias_motivo=CATEGORIAS_MOTIVO,
        dominios_tematicos=DOMINIOS_TEMATICOS, escopos_geograficos=ESCOPOS_GEOGRAFICOS, tipos_documento=TIPOS_DOCUMENTO,
        lote_padrao=LOTE_PADRAO_VIES, lote_maximo=LOTE_MAXIMO_VIES, janela_contexto_tokens=JANELA_CONTEXTO_TOKENS,
        ano_minimo=0, snippet_max_chars=SNIPPET_MAX_CHARS_VIES, max_custo_padrao_usd=MAX_CUSTO_PADRAO_VIES_USD,
        caracteres_por_token=CARACTERES_POR_TOKEN, tokens_metadados_por_item=TOKENS_METADADOS_POR_ITEM,
        tokens_fixos_por_chamada=TOKENS_FIXOS_POR_CHAMADA_VIES,
        saida_por_item=dict(SAIDA_POR_ITEM_VIES), raciocinio_por_chamada=dict(RACIOCINIO_POR_CHAMADA),
        vies=True, relevancias=RELEVANCIAS_VIES, tipos_fonte=TIPOS_FONTE, sufixos_tipo_fonte=dict(SUFIXOS_TIPO_FONTE),
        eixos=tuple(eixos), sem_eixo=SEM_EIXO)


assert len(TIPOS_FONTE) == len(set(TIPOS_FONTE)) == 43
