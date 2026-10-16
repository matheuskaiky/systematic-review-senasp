from config.vocabulario import STATUS

# v2: regra 7 e linha "Output language" (entradas em en-US, saidas em pt-BR)
# v3: status em_estudo; regra 3 exige trecho que nomeie a tecnologia; regra 6 olha so o trecho citado
# v4: campo nome_solucao (nome proprio da ferramenta, resolvido pelo texto da pagina); 'evidencia' continua 100% literal
PROMPT_VERSAO = "v4"
# Por que o nome NAO vai dentro da evidencia (por exemplo, "[BO Fácil] a ferramenta utiliza..."): a checagem `evidencia_confere`
# exige trecho literal do texto enviado, e um trecho com prefixo entre colchetes seria marcado como "não confere" e perderia a
# auditoria. O pesquisador aceitou garantir que `nome_solucao` esteja preenchido em vez de enriquecer a evidencia; o nome ainda
# precisa aparecer no texto enviado (aplicacao/classificacao.py descarta o que o modelo inventar).

_DEFINICOES = "\n".join(f"- {k}: {v}" for k, v in STATUS.items())

SYSTEM_PROMPT = (
    "You analyze text from web pages about public security in Brazil.\n"
    "Rules:\n"
    "1. Use EXCLUSIVELY the text provided. Do not use outside knowledge.\n"
    "2. Identify only AI technologies used or planned by public security agencies of "
    "the TARGET STATE indicated.\n"
    "3. For each finding, copy into 'evidencia' a LITERAL excerpt of the text (up to 300 "
    "characters), without changing a single word. Choose a passage that itself names or describes the "
    "technology of the finding; do not pick a nearby sentence that leaves the technology out.\n"
    "4. If the text does not support any finding for the target state, return "
    "relevante=false and achados=[].\n"
    "5. 'fornecedor': company name if it appears in the text; otherwise, an empty string.\n"
    "6. 'menciona_lgpd': look ONLY at the 'evidencia' excerpt you copied. It is true only if that excerpt "
    "itself addresses LGPD (the Brazilian data protection law) or data protection. If those words do not "
    "appear in the excerpt, it must be false, even when other parts of the page mention them.\n"
    "7. 'nome_solucao': the official PROPER NAME of the tool, system, program or platform of the finding, exactly "
    "as it is written in the text (examples: \"BO Fácil\", \"SPiA\"). The name may appear in another paragraph than "
    "the excerpt you quote in 'evidencia', which may only say \"a ferramenta\", \"o sistema\" or \"a iniciativa\": "
    "resolve that reference using the whole text provided. If no proper name appears in the text, use an empty "
    "string. Never invent, translate, shorten or complete a name: it must appear in the text provided. Do NOT "
    "add the name (or anything else) to 'evidencia'; 'evidencia' stays a 100% literal excerpt.\n"
    "8. Language: these instructions are written in English (en-US). Write every free-text value "
    "you produce in Brazilian Portuguese (pt-BR). Never translate 'evidencia' or 'nome_solucao': they must be copied "
    "exactly as they appear in the source text. JSON keys and enumerated values stay exactly as "
    "defined in the schema.\n"
    "Status definitions:\n" + _DEFINICOES
)

USER_PROMPT = (
    "TARGET STATE: {nome} ({uf})\n"
    "URL: {url}\n"
    "Title: {titulo}\n"
    "Text origin: {origem}\n"
    "Output language: Brazilian Portuguese (pt-BR) for any free text; copy 'evidencia' verbatim "
    "from the text below, without translating.\n\n"
    "TEXT:\n{texto}"
)
