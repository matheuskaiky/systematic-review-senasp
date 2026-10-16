"""Glossario da pagina "Sobre os dados": dados puros (sem I/O), em portugues claro.

Estrutura: SECOES e uma lista de secoes `{"id", "titulo", "intro", "entradas"}`; cada entrada e
`{"id", "termo", "texto"}` e, nos status, tambem `"status"` (a chave do vocabulario, para a pagina mostrar a definicao
oficial, em ingles, que vai para o prompt). O `id` de cada entrada e a ancora: outras paginas podem apontar para
`/sobre#<id>`. Toda chave de `config.vocabulario` e de `painel.rotulos` tem entrada, com o prefixo de PREFIXOS
(`tests/test_glossario.py` confere).
"""
from painel import rotulos

# prefixo da ancora para cada tabela de chaves (a chave vem depois do hifen)
PREFIXOS = {
    "TECNOLOGIAS": "tecnologia", "STATUS": "status", "CONFIANCA": "confianca", "ORIGEM_TEXTO": "origem",
    "VERIFICACAO": "verificacao", "MOTIVOS_DESCARTE": "descarte", "MOTIVOS_FALHA": "falha",
}


def _e(id_, termo, texto, **extra):
    return {"id": id_, "termo": termo, "texto": texto, **extra}


_NUMEROS = [
    _e("kpi-consultas-web", "Consultas web",
       "Quantas buscas na web foram feitas e aceitas pelo provedor: uma por estado (UF), tecnologia e modelo de consulta. "
       "Cada consulta tem um custo estimado e uma resposta bruta guardada."),
    _e("kpi-resultados", "Resultados",
       "Quantos links as consultas devolveram, contando repetições. O mesmo endereço pode aparecer em várias consultas."),
    _e("kpi-urls-unicas", "URLs únicas",
       "Quantos endereços diferentes sobraram depois de juntar os resultados repetidos. É o conjunto de onde saem as páginas a baixar."),
    _e("kpi-paginas-selecionadas", "Páginas selecionadas",
       "URLs que passaram pelos filtros de seleção (fonte oficial, palavras-chave no título ou no trecho, limite por UF) e "
       "que o pipeline tentou baixar. As demais ficam registradas com o motivo do descarte."),
    _e("kpi-paginas-baixadas", "Páginas baixadas",
       "Páginas selecionadas cujo download foi tentado e respondeu. Um download pode funcionar e mesmo assim não render texto."),
    _e("kpi-paginas-com-texto", "Páginas com texto",
       "Páginas baixadas de onde foi possível extrair texto legível. Só essas vão para o classificador com o texto da página."),
    _e("kpi-classificacoes", "Classificações",
       "Quantas vezes o modelo de linguagem leu uma página (ou, sem texto, só o título e o trecho do buscador) e respondeu. "
       "Uma classificação pode não ter nenhum achado."),
    _e("kpi-achados", "Achados",
       "Cada par tecnologia-status que o modelo apontou numa página, com um trecho literal como evidência. "
       "Um achado é uma hipótese a verificar por uma pessoa, não um resultado confirmado."),
    _e("kpi-evidencia-confere", "Evidência confere",
       "Percentual dos achados cujo trecho citado existe de fato no texto enviado ao modelo. Veja o termo “Evidência confere”, "
       "mais adiante, para o que isso garante e o que não garante."),
    _e("kpi-verificados", "Verificados",
       "Percentual dos achados que uma pessoa já revisou, confirmando o status ou descartando o achado. "
       "É o andamento do trabalho humano, não a qualidade do modelo."),
    _e("kpi-confirmados", "Confirmados",
       "Achados verificados por uma pessoa e mantidos (com o status reportado ou outro, corrigido por ela). Os descartados não entram."),
    _e("kpi-ufs-confirmadas", "UFs com achado confirmado",
       "Em quantos estados há ao menos um achado confirmado de secretaria estadual. É o número que vai para o texto da pesquisa, "
       "por isso depende da verificação humana."),
    _e("kpi-gasto-real", "Gasto real (todas as execuções)",
       "Soma do custo gravado em todas as chamadas externas, inclusive as de execuções fora do relatório (testes e pilotos custam "
       "dinheiro mesmo sem entrar nas contagens). Na busca web o custo é o preço configurado por requisição, uma estimativa; "
       "para conferir, compare com o saldo do provedor."),
]

_TECNOLOGIAS = {
    "reconhecimento_facial": "Sistemas que identificam ou comparam rostos em imagens de câmeras, fotos ou bancos de dados.",
    "leitura_placas": "Câmeras ou programas que leem placas de veículos automaticamente, por exemplo em rodovias e vias urbanas.",
    "videomonitoramento_inteligente": "Câmeras com análise automática de imagem (detecção de eventos, objetos ou comportamentos), "
                                      "diferentes de câmeras que só gravam.",
    "analise_preditiva": "Modelos que usam dados históricos para prever onde ou quando crimes tendem a ocorrer e orientar o policiamento.",
    "outra_ia": "Qualquer outra aplicação de inteligência artificial em segurança pública que não se encaixe nas quatro anteriores.",
}

_STATUS = {
    "em_uso": "A tecnologia já funciona no dia a dia da instituição. É o único status que indica uso comprovado em operação.",
    "piloto": "Há teste, projeto-piloto ou implantação parcial: funciona, mas ainda não é o uso pleno.",
    "licitacao": "Existe licitação, pregão, contrato ou aquisição em andamento ou já assinada, sem que o texto prove que a "
                 "tecnologia já opera.",
    "anunciado": "A instituição anunciou ou planeja a tecnologia para o futuro, mas o texto não mostra contrato nem operação.",
    "em_estudo": "A tecnologia está sendo estudada, avaliada ou desenvolvida internamente, sem piloto, compra nem data de "
                 "implantação anunciada.",
    "apenas_citado": "A página só menciona a tecnologia de forma genérica, sem indício de que a instituição a use ou pretenda usá-la.",
    "descartado": "Não é um status do modelo: é uma decisão humana. A pessoa que revisa marca como descartado o achado que está errado "
                  "(a página não fala da tecnologia, o trecho não sustenta o achado, a fonte não serve). Achados descartados não contam "
                  "como confirmados.",
}

_CONFIANCA = {
    "alta": "O próprio modelo disse estar bastante seguro, e a leitura foi feita sobre o texto da página. Mesmo assim o achado "
            "precisa de verificação humana.",
    "media": "O modelo indicou segurança moderada: o trecho sugere o achado, mas deixa alguma dúvida (por exemplo, status incerto).",
    "baixa": "O modelo indicou pouca segurança, ou a leitura veio só do título e do trecho do buscador (snippet). "
             "Vale olhar primeiro estes achados na revisão.",
}

_ORIGEM = {
    "pagina": "O modelo leu o texto extraído da página inteira (até o limite de caracteres enviados). É a leitura mais confiável.",
    "snippet": "A página não pôde ser baixada ou não rendeu texto, então o modelo leu só o título e o pequeno trecho que o buscador "
               "mostrou. Como o contexto é mínimo, a confiança é sempre baixa.",
}

_VERIFICACAO = {
    "pendente": "Ninguém revisou o achado ainda. Aparece como “Não verificado”.",
    "confirmado": "Uma pessoa revisou e manteve o achado, com o status reportado pelo modelo ou com outro, corrigido por ela.",
    "descartado": "Uma pessoa revisou e concluiu que o achado está incorreto. Fica guardado, com o histórico da decisão, mas não conta.",
}

_DESCARTE = {
    "dominio_excluido": "A página é de um site que a pesquisa decidiu ignorar (por exemplo, redes sociais ou vídeos). "
                        "Foi encontrada, mas não será baixada.",
    "nao_oficial": "O endereço não é de um órgão público (não termina em .gov.br ou equivalente) e a configuração aceita só fontes "
                   "oficiais nesta etapa.",
    "prefiltro_palavras": "Nem o título nem o trecho do buscador contêm alguma das palavras-chave da pesquisa, então a página foi "
                          "considerada improvável e não foi baixada. A auditoria do pré-filtro mede se isso perde achados.",
    "limite_por_uf": "O estado já tinha atingido o número máximo de páginas a baixar. As páginas mais bem posicionadas entram "
                     "primeiro; as demais ficam registradas como descartadas por limite.",
}

_FALHA = {
    "texto_insuficiente": "A página foi baixada, mas o texto extraído é curto demais para ser lido (por exemplo, uma página que só "
                          "carrega depois, com JavaScript). O classificador usa só o título e o trecho do buscador.",
    "tipo_nao_suportado": "O arquivo não é de um tipo que o pipeline sabe ler (por exemplo, um arquivo compactado). "
                          "O tipo aparece entre parênteses.",
    "erro": "Houve um erro inesperado ao extrair o texto. O detalhe aparece entre parênteses e a resposta bruta continua guardada.",
}

_EXECUCOES = [
    _e("execucao-concluida", "Concluída", "A execução terminou sem interrupção: todas as etapas dela rodaram até o fim."),
    _e("execucao-em_andamento", "Em andamento",
       "A execução começou e ainda não registrou o fim. Se o pipeline foi encerrado à força, ela fica assim até ser retomada "
       "ou marcada como interrompida."),
    _e("execucao-interrompida", "Interrompida",
       "A execução parou no meio (limite de crédito, queda de conexão ou ordem do pesquisador). Os dados já gravados valem; "
       "é possível retomar de onde parou."),
    _e("execucao-falhou", "Falhou", "A execução terminou com erro antes de produzir resultado útil. Veja as chamadas e o log para a causa."),
    _e("fora-do-relatorio", "Fora do relatório",
       "Marca de uma execução de teste ou piloto que o pesquisador tirou das contas. Nada é apagado: os dados continuam no banco e "
       "nas telas por execução, mas deixam de entrar nas somas, nos resumos por UF e no PRISMA. O gasto real continua contando "
       "todas as execuções."),
    _e("idempotencia", "Idempotência",
       "Repetir a mesma etapa não repete o trabalho nem o gasto: uma chamada que já deu certo na execução não é feita de novo. "
       "Por isso é seguro retomar uma execução interrompida, e importar a mesma planilha duas vezes não duplica nada."),
    _e("config-hash", "Hash da configuração",
       "Impressão digital curta da configuração completa da execução (provedores, termos, filtros, prompt, vocabulário). Duas "
       "execuções com o mesmo hash foram feitas com as mesmas regras, o que permite reproduzir e comparar resultados. "
       "Mudar pausas entre chamadas não altera o hash."),
    _e("commit-git", "Versão do código (commit)",
       "Identificador da versão do código usada na execução. Se havia alterações não gravadas, aparece como “sujo”, seguido de "
       "um código do conteúdo: a execução não é reproduzível só pelo commit."),
    _e("custo-estimado", "Custo estimado e custo real",
       "O custo gravado em cada chamada é calculado com os preços configurados e com os tokens informados pela API. É uma "
       "estimativa; o saldo do provedor, quando existe, é a conferência."),
    _e("chamada-bruta", "Resposta bruta",
       "Cópia exata do que o provedor devolveu, guardada em arquivo com impressão digital (hash). É a evidência de que o dado "
       "não foi alterado depois da coleta."),
]

_ESCOPO = [
    _e("estadual", "Secretaria estadual",
       "Achado sobre o órgão de segurança do governo do estado. É o foco da pesquisa e o que aparece como “estadual” nas tabelas."),
    _e("municipal", "Secretaria ou guarda municipal",
       "Achado sobre um município (guarda municipal, secretaria da prefeitura). É guardado com o nome da cidade e a UF e não "
       "se mistura com os resultados estaduais."),
    _e("fonte-oficial", "Fonte oficial (.gov.br)",
       "O endereço pertence a um órgão público. Fonte oficial pesa mais como prova do que uma reportagem, mas a revisão humana "
       "continua necessária."),
    _e("fonte-oficial-final", "Fonte oficial depois do redirecionamento",
       "Alguns endereços redirecionam para outro site ao serem abertos. A fonte oficial “final” olha o domínio onde a página foi "
       "de fato lida, e é ela que as telas mostram quando existe. Atenção ao caso de um link oficial que termina em site não oficial."),
    _e("snippet", "Snippet",
       "O título e o pequeno trecho que o buscador mostra junto de cada resultado. Serve de último recurso quando a página não "
       "pode ser lida."),
    _e("texto-cortado", "Texto cortado",
       "O modelo lê no máximo um número fixo de caracteres por página. Quando o texto passa do limite, a página mostra onde o "
       "corte ocorreu; o que ficou depois dele nunca foi visto pelo modelo."),
]

_EVIDENCIA = [
    _e("evidencia-confere", "Evidência confere",
       "O trecho que o modelo citou foi encontrado, palavra por palavra, no texto enviado a ele (ignorando maiúsculas, acentos e "
       "espaços repetidos). Isso só garante que o trecho existe, não que ele sustenta o achado. A comparação é feita sem usar "
       "o modelo."),
    _e("evidencia-nao-localizada", "Evidência não localizada",
       "O trecho citado não aparece no texto enviado, em geral porque o modelo parafraseou ou resumiu em vez de copiar. "
       "O achado pode até estar certo, mas precisa de atenção especial: a tela mostra a passagem mais parecida, como aproximação."),
    _e("evidencia-cita-tecnologia", "Evidência cita a tecnologia",
       "Verificação branda: o trecho contém alguma palavra do nome da tecnologia (por exemplo, “placas” para leitura de placas). "
       "Se não contém, o achado sobe na fila de revisão. É uma ajuda para priorizar, não uma decisão."),
    _e("evidencia-cita-lgpd", "Evidência cita a LGPD",
       "O trecho menciona a Lei Geral de Proteção de Dados ou proteção de dados. Para saber quantos achados tratam de LGPD, use "
       "esta marca e não a do modelo, que às vezes marca LGPD sem que o trecho a cite."),
]

_LITERATURA = [
    _e("artigo-unico", "Artigo único",
       "O mesmo estudo pode ser achado por vários termos e em várias bases. O sistema junta as repetições (pelo título) e conta "
       "cada artigo uma vez."),
    _e("termo-de-busca", "Termo de busca",
       "Cada termo é uma consulta própria, identificada por um código (T01, T02...). Os termos e suas versões em inglês ficam "
       "registrados com a execução."),
    _e("achado-por-varios-termos", "Achado por 2 ou mais termos",
       "Artigos que apareceram em pelo menos dois termos diferentes. Muita sobreposição entre dois termos indica que um deles "
       "acrescenta pouco à busca."),
    _e("bases-manuais", "Buscas manuais (IEEE, ACM, Scopus, SBC OpenLib)",
       "Bases consultadas por uma pessoa no site da própria base. O sistema só conhece o que for informado por planilha: o "
       "número de resultados e os artigos importados. O que não foi informado aparece como “não informado”, nunca como zero."),
    _e("relevancia", "Relevância (Brasil + tema)",
       "Ajuda para priorizar a triagem: o programa procura, no título, no resumo, nos autores e no link de cada artigo, sinais de "
       "que ele é brasileiro (Brasil, estados, cidades, polícias, domínio .br) e de que trata de segurança pública (polícia, "
       "crime, vigilância, perícia, sistema prisional). As listas de palavras ficam à vista na página de artigos. É uma "
       "heurística: pode errar para os dois lados, não exclui nem esconde nada e não decide por você."),
    _e("relevancia-alta", "Relevância alta",
       "O artigo tem sinal de Brasil e sinal de tema. É o grupo a olhar primeiro, mas continua sujeito à decisão de quem faz a triagem."),
    _e("relevancia-media", "Relevância média",
       "O artigo tem só um dos dois sinais: ou parece brasileiro mas o tema não aparece (por exemplo, repositório .br com assunto "
       "genérico), ou trata do tema mas sem sinal de Brasil (por exemplo, policiamento preditivo em outro país). Vale conferir caso a caso."),
    _e("relevancia-baixa", "Relevância baixa",
       "Nenhum dos marcadores foi encontrado. Não significa que o artigo seja irrelevante: o título e o resumo podem usar palavras "
       "fora das listas. Por isso a triagem continua cobrindo todos os artigos."),
    _e("triagem-titulo-resumo", "Triagem por título e resumo",
       "Primeira leitura de cada artigo: uma pessoa decide, só pelo título e pelo resumo, se ele merece leitura completa."),
    _e("triagem-texto-completo", "Triagem por texto completo",
       "Segunda leitura, só dos artigos incluídos na primeira: a pessoa lê o artigo inteiro e confirma ou não a inclusão. "
       "É a decisão que define o conjunto final."),
    _e("triagem-incluir", "Incluir", "A pessoa decidiu que o artigo atende aos critérios e segue para a próxima etapa."),
    _e("triagem-excluir", "Excluir",
       "A pessoa decidiu que o artigo não atende aos critérios. O motivo é registrado e aparece no fluxo PRISMA."),
    _e("triagem-pendente", "Pendente", "Ninguém decidiu ainda sobre o artigo naquela etapa."),
    _e("prisma", "Fluxo PRISMA",
       "Diagrama padrão de revisões sistemáticas, que conta quantos registros entraram e saíram em cada etapa. Os números vêm "
       "direto do banco."),
    _e("prisma-identificacao", "PRISMA: identificação",
       "Quantos registros as buscas trouxeram (Google Scholar e bases manuais) e quantos eram duplicados entre termos e entre bases."),
    _e("prisma-triagem", "PRISMA: triagem", "Quantos artigos únicos foram lidos por título e resumo, e quantos foram incluídos, excluídos ou ficaram pendentes."),
    _e("prisma-elegibilidade", "PRISMA: elegibilidade",
       "Quantos artigos incluídos na triagem foram avaliados pelo texto completo e com que resultado."),
    _e("prisma-inclusao", "PRISMA: inclusão", "Quantos artigos compõem o conjunto final da revisão."),
    _e("prisma-nao-informado", "Não informado, não executado",
       "“Não informado” significa que uma busca manual ainda não foi importada; “não executado” significa que a busca no Google "
       "Scholar não foi rodada. Em ambos os casos o número real é desconhecido, não zero."),
]


def _por_chave(tabela, nome, textos, extra=None):
    prefixo = PREFIXOS[nome]
    return [_e(f"{prefixo}-{k}", tabela[k], textos[k], **({"status": k} if extra and k in extra else {})) for k in tabela if k in textos]


SECOES = [
    {"id": "numeros", "titulo": "Números da visão geral e do funil",
     "intro": "Os números das telas consideram só as execuções marcadas para o relatório, exceto o gasto real.", "entradas": _NUMEROS},
    {"id": "tecnologias", "titulo": "Tecnologias pesquisadas",
     "intro": "As cinco categorias do vocabulário da pesquisa. O modelo só pode usar estas.",
     "entradas": _por_chave(rotulos.TECNOLOGIAS, "TECNOLOGIAS", _TECNOLOGIAS)},
    {"id": "status", "titulo": "Status do achado",
     "intro": "O status diz em que estágio a instituição está com a tecnologia. A definição oficial, em inglês, é a que o modelo recebe "
              "no prompt; a explicação em português é a deste painel.",
     "entradas": _por_chave(rotulos.STATUS, "STATUS", _STATUS, extra=set(_STATUS) - {"descartado"})},
    {"id": "confianca", "titulo": "Confiança do modelo",
     "intro": "O modelo declara sua confiança em cada achado. Ela ajuda a priorizar a revisão e nunca substitui a verificação humana.",
     "entradas": _por_chave(rotulos.CONFIANCA, "CONFIANCA", _CONFIANCA) + [
         _e("confianca-snippet", "Por que a leitura só de snippet é sempre baixa",
            "Com apenas o título e o trecho do buscador, o modelo não vê o contexto da página e pode se enganar com facilidade. "
            "Por isso o sistema rebaixa para baixa qualquer achado vindo só de snippet, mesmo que o modelo tenha dito alta; a "
            "confiança que o modelo devolveu fica guardada ao lado, para auditoria.")]},
    {"id": "evidencia", "titulo": "Evidência e origem do texto",
     "intro": "A evidência é o trecho literal que sustenta o achado. As marcas abaixo são conferências automáticas, sem modelo, "
              "para ajudar a revisão.",
     "entradas": _EVIDENCIA + _por_chave(rotulos.ORIGEM_TEXTO, "ORIGEM_TEXTO", _ORIGEM)},
    {"id": "verificacao", "titulo": "Verificação humana",
     "intro": "Todo achado nasce não verificado. Só a decisão de uma pessoa o confirma ou descarta.",
     "entradas": _por_chave(rotulos.VERIFICACAO, "VERIFICACAO", _VERIFICACAO)},
    {"id": "descartes", "titulo": "Motivos de descarte de páginas",
     "intro": "Páginas encontradas na busca que não foram baixadas. Nenhuma some: cada descarte fica registrado com o motivo.",
     "entradas": _por_chave(rotulos.MOTIVOS_DESCARTE, "MOTIVOS_DESCARTE", _DESCARTE)},
    {"id": "falhas", "titulo": "Motivos de falha na extração do texto",
     "intro": "Páginas baixadas de que não saiu texto utilizável.", "entradas": _por_chave(rotulos.MOTIVOS_FALHA, "MOTIVOS_FALHA", _FALHA)},
    {"id": "escopo", "titulo": "Escopo e fontes", "intro": "O que cada achado descreve e de onde veio.", "entradas": _ESCOPO},
    {"id": "execucoes", "titulo": "Execuções, reprodutibilidade e custos",
     "intro": "Cada passagem do pipeline é uma execução, com situação, configuração e gasto próprios.", "entradas": _EXECUCOES},
    {"id": "literatura", "titulo": "Literatura e PRISMA",
     "intro": "Termos da segunda parte da pesquisa: artigos científicos, triagem e fluxo PRISMA.", "entradas": _LITERATURA},
]


def ids_de_ancoras():
    """Todas as ancoras do glossario, na ordem em que aparecem (secoes e entradas)."""
    return [s["id"] for s in SECOES] + [e["id"] for s in SECOES for e in s["entradas"]]
