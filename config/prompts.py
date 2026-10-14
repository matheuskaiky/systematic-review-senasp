from config.vocabulario import STATUS

PROMPT_VERSAO = "v1"

_DEFINICOES = "\n".join(f"- {k}: {v}" for k, v in STATUS.items())

PROMPT_SISTEMA = (
    "You analyze text from web pages about public security in Brazil.\n"
    "Rules:\n"
    "1. Use EXCLUSIVELY the text provided. Do not use outside knowledge.\n"
    "2. Identify only AI technologies used or planned by public security agencies of "
    "the TARGET STATE indicated.\n"
    "3. For each finding, copy into 'evidencia' a LITERAL excerpt of the text (up to 300 "
    "characters), without changing a single word.\n"
    "4. If the text does not support any finding for the target state, return "
    "relevante=false and achados=[].\n"
    "5. 'fornecedor': company name if it appears in the text; otherwise, an empty string.\n"
    "6. 'menciona_lgpd': true only if the excerpt addresses LGPD (the Brazilian data "
    "protection law) or data protection.\n"
    "Status definitions:\n" + _DEFINICOES
)

PROMPT_USUARIO = (
    "TARGET STATE: {nome} ({uf})\n"
    "URL: {url}\n"
    "Title: {titulo}\n"
    "Text origin: {origem}\n\n"
    "TEXT:\n{texto}"
)
