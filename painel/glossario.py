"""Glossario da pagina "Sobre os dados": dados puros (sem I/O), em portugues claro.

Estrutura: SECOES e uma lista de secoes `{"id", "titulo", "intro", "entradas"}`; cada entrada e
`{"id", "termo", "texto"}` e, nos status, tambem `"status"` (a chave do vocabulario, para a pagina mostrar a definicao
oficial, em ingles, que vai para o prompt). O `id` de cada entrada e a ancora: outras paginas podem apontar para
`/sobre#<id>`. Toda chave de `config.vocabulario` e de `painel.rotulos` tem entrada, com o prefixo de PREFIXOS
(`tests/test_glossario.py` confere). No banco vies, o glossário próprio desta pesquisa é SECOES_VIES.
"""
from painel import rotulos, rotulos_escopo

# prefixo da ancora para cada tabela de chaves (a chave vem depois do hifen)
PREFIXOS = {
    "TECNOLOGIAS": "tecnologia", "STATUS": "status", "CONFIANCA": "confianca", "ORIGEM_TEXTO": "origem",
    "VERIFICACAO": "verificacao", "MOTIVOS_DESCARTE": "descarte", "MOTIVOS_FALHA": "falha", "MOTIVOS_DOWNLOAD": "download",
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
       "Quantas páginas (pares página-UF) o modelo de linguagem leu e classificou, contando só a classificação vigente de cada uma "
       "(ver “Classificação vigente”). Lê o texto da página ou, sem texto, só o título e o trecho do buscador. "
       "Uma classificação pode não ter nenhum achado."),
    _e("kpi-achados", "Achados",
       "Cada par tecnologia-status que o modelo apontou numa página, com um trecho literal como evidência, contando só os da "
       "classificação vigente de cada página. "
       "Um achado é uma hipótese a verificar por uma pessoa, não um resultado confirmado."),
    _e("classificacao-vigente", "Classificação vigente",
       "Quando uma página foi classificada mais de uma vez, só uma classificação conta nos números: a que já tem achado verificado por "
       "uma pessoa (decisão humana nunca é trocada sozinha); senão a de resposta válida; senão a feita com o texto da página, "
       "que vale mais que a feita só com o trecho do buscador; senão a mais recente. Nada é apagado: as outras ficam no banco, "
       "e um achado antigo continua abrindo, com o aviso de que foi substituído."),
    _e("kpi-evidencia-confere", "Evidência confere",
       "Percentual dos achados cujo trecho citado existe de fato no texto enviado ao modelo. Veja o termo “Evidência confere”, "
       "mais adiante, para o que isso garante e o que não garante."),
    _e("kpi-verificados", "Verificados",
       "Percentual dos achados que uma pessoa já revisou, confirmando o status ou descartando o achado. "
       "É o andamento do trabalho humano, não a qualidade do modelo."),
    _e("kpi-confirmados", "Confirmados",
       "Achados verificados por uma pessoa e mantidos (com o status reportado ou outro, corrigido por ela). Os descartados não entram."),
    _e("kpi-ufs-confirmadas", "UFs com achado confirmado",
       "Em quantos estados há ao menos um achado confirmado (a conta também incluiria achados municipais, que ainda não existem). É o número que vai para o texto da pesquisa, "
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
    "outra_ia": "Qualquer outra aplicação de inteligência artificial em segurança pública que não se encaixe nas demais categorias.",
    "atendimento_virtual": "Serviço ao cidadão por canal virtual (site, WhatsApp, chatbot, assistente ou delegacia virtual), como o registro "
                           "de boletim de ocorrência online, quando o texto diz que usa inteligência artificial ou automação.",
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
    "nao_oficial": "O endereço não é de um órgão público (aqui só vale quem termina em .gov.br) e a configuração aceita só fontes "
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

_DOWNLOAD = {
    "bloqueado_por_robots": "O robots.txt do site (arquivo em que o site diz o que os programas podem ler) foi lido com sucesso e proíbe "
                            "esta página para o pipeline. É uma proibição do próprio site, e o pipeline a respeita; a página não foi requisitada.",
    "robots_inacessivel": "Não foi possível ler o robots.txt do site (erro do servidor, tempo esgotado ou falha de rede), mesmo depois de "
                          "algumas tentativas. Pela RFC 9309 e pela política do pesquisador, sem poder ler as regras o pipeline assume "
                          "que tudo é proibido e não baixa a página. Não é uma proibição do site: costuma ser uma falha passageira, e "
                          "a leitura é repetida quando passam alguns minutos.",
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
    _e("diferenca-saldo", "Diferença de créditos (execução)",
       "Consumo de créditos do provedor (saldo no início menos o saldo no fim da passada) menos as chamadas bem-sucedidas "
       "registradas. Zero: o provedor cobrou o que o sistema registrou. Negativa: cobrou menos (busca não cobrada, como uma "
       "resposta em cache, ou saldo final lido antes de refletir a última busca). Positiva: créditos gastos fora da execução. "
       "Não indica erro nos dados; o sistema guarda só o número do saldo, não a resposta da conta."),
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
    _e("nome-solucao", "Nome da solução",
       "O nome próprio da ferramenta, sistema ou programa do achado (por exemplo, “BO Fácil” ou “SPiA”), como está escrito no texto. "
       "O modelo o preenche mesmo quando o trecho de evidência só diz “a ferramenta”, porque o nome pode estar em outro parágrafo. "
       "O sistema só guarda o nome se ele aparece no texto enviado ao modelo (título e endereço incluídos); um nome inventado é "
       "descartado e fica contado. Em branco (“—”) quer dizer que nenhum nome próprio apareceu. A evidência continua sendo um trecho literal."),
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
    _e("achado-por-varios-termos", "Achado por 2 ou mais termos ou bases",
       "Artigos achados por pelo menos dois termos do Google Scholar ou por pelo menos duas origens somadas: cada termo diferente do "
       "Scholar conta uma vez e cada base manual (IEEE, ACM, Scopus, SBC OpenLib) conta uma vez. É o mesmo critério do número da "
       "Visão da literatura e do filtro “Mais de um termo” da lista de artigos. Só os termos do Scholar aparecem na aba "
       "Multi_termo e nas faixas da análise de termos. Muita sobreposição entre dois termos indica que um deles acrescenta pouco à busca."),
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
       "Quantos registros as buscas trouxeram (Google Scholar e bases manuais), quantos eram duplicados entre termos e entre bases e "
       "quantos foram removidos por ferramenta automática antes da triagem humana."),
    _e("prisma-removidos-automatico", "PRISMA: removidos por ferramenta automática",
       "Artigos que a triagem de escopo do modelo excluiu (veredito atual válido) e sobre os quais nenhuma pessoa decidiu incluir ou "
       "excluir. O PRISMA 2020 pede esse número à parte, sem decisão humana. Nada é apagado: se uma pessoa decidir sobre o artigo, "
       "ele volta ao fluxo humano e deixa de contar aqui. É o que separa os artigos únicos do total da busca dos artigos que seguem "
       "para a triagem por título e resumo."),
    _e("prisma-triagem", "PRISMA: triagem",
       "Quantos artigos únicos (já sem os removidos por ferramenta automática) foram lidos por título e resumo, e quantos foram "
       "incluídos, excluídos ou ficaram pendentes."),
    _e("prisma-elegibilidade", "PRISMA: elegibilidade",
       "Quantos artigos incluídos na triagem foram avaliados pelo texto completo e com que resultado."),
    _e("prisma-inclusao", "PRISMA: inclusão", "Quantos artigos compõem o conjunto final da revisão."),
    _e("prisma-nao-informado", "Não informado, não executado",
       "“Não informado” significa que uma busca manual ainda não foi importada; “não executado” significa que a busca no Google "
       "Scholar não foi rodada. Em ambos os casos o número real é desconhecido, não zero."),
]

_ESCOPO_LLM = [
    _e("triagem-escopo", "Triagem de escopo pelo modelo",
       "O modelo de linguagem lê o título e o resumo de cada artigo (ou resultado web) e diz se ele serve ao escopo da pesquisa: "
       "elegível, quarentena ou excluído. É uma opinião registrada à parte da sua decisão, usada para ajustar as consultas de busca. "
       "Nada é apagado: o excluído fica oculto das listas por padrão (quarentena temporária) e uma decisão humana sempre prevalece."),
    _e("escopo-status-elegivel", "Triagem LLM: elegível", rotulos_escopo.STATUS_EXPLICA["elegivel"]),
    _e("escopo-status-quarentena", "Triagem LLM: quarentena", rotulos_escopo.STATUS_EXPLICA["quarentena"]),
    _e("escopo-status-excluido", "Triagem LLM: excluído pelo modelo", rotulos_escopo.STATUS_EXPLICA["excluido"]),
] + [_e("escopo-categoria-" + k.lower(), "Motivo: " + rotulos_escopo.CATEGORIAS[k], rotulos_escopo.CATEGORIAS_EXPLICA[k])
     for k in rotulos_escopo.CATEGORIAS] + [
    _e("ficha-ruido", "Ficha de ruído por termo",
       "Para cada consulta da busca, a parcela de itens elegíveis, em quarentena e excluídos pelo modelo, o motivo e a área mais frequentes "
       "do ruído e a parcela de itens internacionais. O ruído é a soma de excluídos e em quarentena sobre o total. Só linhas com a "
       "conferência automática aprovada entram nos percentuais."),
    _e("termo-gerador", "Termo gerador",
       "Entre as consultas que encontraram um item, a que o modelo aponta como provável causa de ele ter sido capturado por engano. "
       "O programa confere que é uma das consultas da busca, para poder contar quantos itens ruidosos cada termo gerou."),
    _e("sinal-negativo", "Sinal negativo",
       "Palavra ou expressão (até três palavras) copiada do título ou do resumo de um item excluído que caracteriza aquele ruído e "
       "poderia virar um operador negativo na busca. É uma sugestão do modelo: antes de usá-la, veja o dano colateral."),
    _e("dano-colateral", "Dano colateral de um operador negativo",
       "Quantos itens bons (elegíveis, em quarentena ou incluídos por você) também contêm o sinal negativo e se perderiam se a consulta o "
       "excluísse. Zero é seguro; até 5% dos itens que contêm o texto é arriscado; mais que isso, ou uma palavra central do tema, é perigoso."),
    _e("dominio-tematico", "Área temática",
       "A área de onde vem o item segundo o modelo (saúde, educação, agropecuária, trânsito...), entre uma lista fechada. Mostra de onde "
       "vem o ruído de cada termo e que tipo de operador negativo ajudaria."),
    _e("escopo-geografico", "Escopo geográfico",
       "Se o item trata do Brasil, é internacional ou indeterminado. Item internacional não é excluído só por isso, porque pode servir de "
       "referência; mas um termo que só traz literatura estrangeira indica que a consulta precisa de foco no Brasil."),
    _e("conferencia-automatica-escopo", "Conferência automática da triagem",
       "Depois de cada resposta do modelo o programa confere, sem usar o modelo, se os campos são válidos, se o termo gerador é um dos termos "
       "da busca e se o sinal negativo existe no texto; e rebaixa para quarentena toda exclusão sem confiança alta. Linhas que falham ficam "
       "marcadas e fora dos percentuais."),
]


_SOLUCOES = [
    _e("solucao-conhecida", "Solução conhecida",
       "Sistema de IA de segurança pública que o pesquisador sabe que existe e informa em config/solucoes_conhecidas.py (nome, UF e, se quiser, "
       "apelidos). A página Soluções conhecidas mostra se a coleta o encontrou nos resultados da busca, no texto das páginas baixadas e nos achados. "
       "É uma medida de revocação da coleta, não um resultado da pesquisa; a lista é sua e não entra na configuração das execuções."),
    _e("entidade-solucao", "Entidade de solução",
       "O mesmo sistema, mesmo escrito de jeitos diferentes pelo modelo (“SPiA”, “SPIA”, “Sistema de Policiamento por Inteligência Artificial”; "
       "“BO Fácil”, “B.O. Fácil”). O painel reúne essas grafias em uma entidade, só com regras fixas e sem usar o modelo, em três camadas de confiança: "
       "pelo cadastro (nome ou apelido de uma solução conhecida, na mesma UF), sigla e nome por extenso (as iniciais do nome formam a sigla, ou o formato "
       "“Nome (SIGLA)”) e unificado por semelhança (a mais fraca: grafia equivalente ou muito parecida, com os mesmos números e na mesma UF, o que separa "
       "“Operação Paz I” de “Operação Paz II”). Nunca se reúne entre UFs diferentes, e o valor que o modelo escreveu fica intacto no banco e na planilha: a "
       "tela da ocorrência o mostra em “Como o modelo escreveu”. O nome mostrado é o oficial do cadastro ou, nas soluções novas, a grafia mais frequente. "
       "Cada grafia reunida mostra a camada e o motivo, para você conferir e, se discordar, cadastrar a solução com seus apelidos."),
    _e("busca-no-texto", "Busca no texto",
       "Procura de um nome ou frase em todo o texto extraído das páginas já baixadas, e não só na evidência dos achados. Ignora acentos e maiúsculas "
       "e, com a opção de palavra inteira, não acha o nome dentro de outra palavra. Só enxerga páginas baixadas: não achar o nome não prova "
       "que a solução não é usada."),
]


_AUDITORIA_IA = [
    _e("revisao-independente", "Revisão independente",
       "Duas ou mais pessoas decidem sobre os mesmos achados cada uma por conta própria, sem ver a decisão da outra. Entra pelo comando "
       "achados-importar com a opção --independente: a decisão vai só para o histórico e não muda a decisão final do achado. É a única "
       "revisão que conta para medir se os revisores concordam."),
    _e("kappa-achados", "Kappa de Cohen entre revisores (achados)",
       "Mede quanto dois revisores concordam em confirmar ou descartar um achado, além do que o acaso explicaria: 0 é igual ao acaso e 1 é "
       "concordância perfeita. Vem com o percentual de concordância e a faixa de leitura (fraca, razoável, moderada, substancial, quase "
       "perfeita), que é uma convenção e não uma lei. Quando quase todos os achados têm o mesmo desfecho, o kappa pode ser baixo mesmo com muita "
       "concordância; se todos os achados do par têm um só desfecho, ele não pode ser calculado."),
    _e("discordancias-achados", "Discordâncias dos achados",
       "Achados em que dois revisores decidiram diferente (um confirmou e o outro descartou, ou deram status diferentes). É a pauta da reunião "
       "de consenso e sai na aba Discordancias_achados da exportação, com a decisão de cada um e a decisão final."),
    _e("falso-negativo", "Falso negativo (aplicação perdida)",
       "Página em que havia uma aplicação de IA e o modelo não marcou nenhum achado. É o erro que faz o levantamento deixar de ver algo, e só "
       "se descobre quando uma pessoa lê páginas que o modelo deixou sem achado."),
    _e("auditoria-negativos", "Auditoria dos negativos do modelo",
       "Conferência humana de uma amostra sorteada de páginas que o modelo classificou sem nenhum achado. A pessoa diz, página a página, se havia "
       "uma aplicação de IA que o modelo perdeu (1) ou se o modelo acertou (0). Dá a taxa de falso negativo e, com ela, uma ideia da revocação "
       "do modelo. O sorteio é reproduzível (mesma semente, mesma amostra) e proporcional ao tamanho de cada UF."),
    _e("limite-superior-95", "Limite superior de 95%",
       "Com 95% de confiança, a taxa verdadeira não passa deste valor. É calculado de forma exata (binomial) e vale mesmo com amostras pequenas "
       "ou nenhum erro encontrado. Se ele fica abaixo da meta (5% ou 2%), a meta está provada; se não, a amostra ainda é pequena demais."),
    _e("amostra-zero-erros", "Amostra com zero erros",
       "Quantas páginas a pessoa precisa conferir, sem achar nenhuma aplicação perdida, para provar que a taxa de falso negativo está abaixo da "
       "meta. O número é calculado pelo sistema e cresce quando a meta fica mais rigorosa. Se aparecer algum erro, é preciso conferir mais."),
    _e("prontidao-metodologica", "Prontidão metodológica",
       "Quanto já foi rotulado por uma pessoa em relação ao mínimo que cada análise exige para rodar: a regressão logística (H2) pede 200 achados "
       "verificados e 40 na classe menos frequente; a análise bibliométrica (H5), 50 decisões de triagem e 10 de cada tipo; a auditoria dos negativos, "
       "o número de páginas calculado pelo sistema (59 para a meta de 5%). Os números são os mesmos que os scripts de análise usam para recusar ou rodar. "
       "Aparece na página inicial e em Análises, Visão geral. Para gerar só as linhas que faltam: python main.py rotulagem-modelo."),
    _e("classe-minoritaria", "Classe minoritária",
       "Na regressão logística, o menor dos dois grupos do desfecho (achados confirmados ou achados descartados). Com poucos casos num dos grupos o "
       "ajuste não é confiável; por isso a análise exige pelo menos 40 na classe minoritária, além dos 200 achados verificados."),
    _e("amostra-enriquecida", "Amostra enriquecida",
       "Seleção em que entram de propósito os itens com mais chance de erro (evidência que não confere ou que não cita a tecnologia, texto só de snippet, "
       "confiança baixa), para que o grupo menos frequente chegue ao mínimo. Serve à regressão, mas NÃO estima a precisão global do modelo, porque os "
       "erros estão em excesso na amostra. Para a precisão global é preciso uma amostra aleatória (rotulagem-modelo --aleatoria)."),
    _e("folga-rotulagem", "Folga da rotulagem",
       "Margem percentual (padrão 10%) somada ao que falta para o mínimo, para cobrir linhas que a pessoa pule ou deixe em branco. A folga não vale para "
       "a auditoria dos negativos nem para a amostra extra de falsa exclusão, cujos tamanhos já supõem zero erros."),
    _e("pagina-nao-verificavel", "Página não verificável",
       "Página que o download não conseguiu verificar porque o robots.txt do site seguiu inacessível (erro do servidor, tempo esgotado ou falha "
       "de rede) em três leituras seguidas ou em pelo menos duas tentativas de download. Não é o mesmo que proibida pelo site: não sabemos o que o "
       "site decidiu. Por política (RFC 9309) ela fica fora da coleta, e o levantamento pode ter deixado de ver conteúdo nela."),
    _e("pagina-inexistente-404", "Página inexistente (404 ou 410)",
       "A última tentativa de baixar a página recebeu o erro 404 ou 410: ela não existe mais ou mudou de endereço. É uma falha da página, não "
       "uma proibição do site nem uma falha da coleta."),
    _e("ultima-tentativa-download", "Última tentativa de download",
       "Uma mesma página pode ter sido tentada em mais de uma execução. Para dizer o que ficou sem verificação vale só a tentativa mais recente "
       "de cada página: se a segunda tentativa deu certo, a falha da primeira não conta."),
]


def _por_chave(tabela, nome, textos, extra=None):
    prefixo = PREFIXOS[nome]
    return [_e(f"{prefixo}-{k}", tabela[k], textos[k], **({"status": k} if extra and k in extra else {})) for k in tabela if k in textos]


SECOES = [
    {"id": "numeros", "titulo": "Números da visão geral e do funil",
     "intro": "Os números das telas consideram só as execuções marcadas para o relatório, exceto o gasto real.", "entradas": _NUMEROS},
    {"id": "tecnologias", "titulo": "Tecnologias pesquisadas",
     "intro": "As seis categorias do vocabulário da pesquisa. O modelo só pode usar estas.",
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
    {"id": "download", "titulo": "Motivos de bloqueio no download",
     "intro": "Páginas que o pipeline não baixou por causa do robots.txt do site. As duas situações são diferentes e aparecem separadas.",
     "entradas": _por_chave(rotulos.MOTIVOS_DOWNLOAD, "MOTIVOS_DOWNLOAD", _DOWNLOAD)},
    {"id": "escopo", "titulo": "Escopo e fontes", "intro": "O que cada achado descreve e de onde veio.", "entradas": _ESCOPO},
    {"id": "execucoes", "titulo": "Execuções, reprodutibilidade e custos",
     "intro": "Cada passagem do pipeline é uma execução, com situação, configuração e gasto próprios.", "entradas": _EXECUCOES},
    {"id": "literatura", "titulo": "Literatura e PRISMA",
     "intro": "Termos da segunda parte da pesquisa: artigos científicos, triagem e fluxo PRISMA.", "entradas": _LITERATURA},
    {"id": "triagem-escopo-llm", "titulo": "Triagem de escopo pelo modelo",
     "intro": "O modelo opina, item a item, se o resultado serve ao escopo; a pesquisa usa a opinião para refinar as consultas, sem apagar nem decidir nada.",
     "entradas": _ESCOPO_LLM},
    {"id": "solucoes-conhecidas", "titulo": "Soluções conhecidas e busca no texto",
     "intro": "Duas telas para conferir se a coleta encontra o que o pesquisador já conhece.", "entradas": _SOLUCOES},
    {"id": "auditoria-ia", "titulo": "Confiança na IA e páginas não verificadas",
     "intro": "Como se mede o que o modelo acerta e o que ele deixa passar, e o que a coleta não conseguiu ver.", "entradas": _AUDITORIA_IA},
]

EXECUCOES_REUSADAS = [
    "execucao-concluida", "execucao-em_andamento", "execucao-interrompida", "execucao-falhou", "idempotencia",
    "config-hash", "commit-git", "chamada-bruta", "custo-estimado"
]

_do_real = {e["id"]: e for e in _EXECUCOES}
_execucoes_reusadas = [_do_real[i] for i in EXECUCOES_REUSADAS]

SECOES_VIES = [
    {"id": "unidades", "titulo": "Unidades de contagem",
     "intro": "Cada número desta pesquisa conta uma destas unidades. Números de unidades diferentes não se somam.",
     "entradas": [
         _e("chamada", "Chamada",
            "Um pedido feito a um provedor externo: uma consulta à busca na web, uma página de resultados de uma consulta no "
            "Google Scholar ou um lote de itens enviado ao modelo da triagem. Cada chamada fica registrada com os parâmetros "
            "enviados e, quando o provedor respondeu, com a resposta bruta e, se o provedor tem preço configurado, com o custo "
            "estimado em dólares. O Google Scholar é contado em créditos do serviço, medidos por execução, sem preço em dólares."),
         _e("ocorrencia", "Ocorrência",
            "Um resultado devolvido por uma chamada de busca. O mesmo trabalho pode voltar em várias consultas, e cada volta é "
            "uma ocorrência. Na busca na web, as ocorrências do mesmo endereço formam uma referência da web; no Google Scholar, "
            "as do mesmo título formam um artigo do Scholar."),
         _e("artigo-scholar", "Artigo do Scholar",
            "Um trabalho encontrado pelo Google Scholar, contado uma vez mesmo quando várias consultas o devolvem. Dois "
            "resultados são o mesmo artigo quando o título é igual depois de normalizado (sem acentos, maiúsculas nem "
            "pontuação). Apesar do nome, pode ser uma dissertação, um livro, um capítulo ou outro trabalho que o Scholar indexa."),
         _e("referencia-web", "Referência da web",
            "Uma página encontrada pela busca na web, contada uma vez mesmo quando várias consultas a devolvem. Dois resultados "
            "são a mesma referência quando o endereço é igual depois de normalizado (domínio em minúsculas e sem “www”, sem "
            "barras no fim do caminho, sem o trecho após “#”, com os parâmetros em qualquer ordem e sem os de rastreamento, que "
            "são os que começam por “utm_” e “fbclid”, “gclid”, “mc_cid” e “mc_eid”; “http” e “https” contam como endereços "
            "diferentes, e as maiúsculas do caminho e a porta contam). Pode ser um artigo, uma notícia, um relatório, uma norma ou a página de um produto."),
         _e("item", "Item",
            "Um artigo do Scholar ou uma referência da web. É a unidade da triagem pelo modelo: o mesmo trabalho encontrado nas "
            "duas fontes são dois itens, cada um com a sua classificação."),
         _e("obra", "Obra",
            "O item depois de juntar a referência da web que repete um artigo do Scholar, por ter o mesmo endereço normalizado "
            "ou o mesmo título normalizado. A obra assim juntada conta uma vez, e nas análises por obra vale a classificação do "
            "artigo do Scholar. A junção é um procedimento automático, não uma conferência bibliográfica: títulos escritos de "
            "forma diferente não são reconhecidos como a mesma obra, e possíveis duplicatas que restam ainda não foram "
            "examinadas por uma pessoa."),
     ]},
    {"id": "busca", "titulo": "Busca",
     "intro": "De onde vêm os itens. A Metodologia descreve os filtros, a profundidade e as execuções de cada fonte.",
     "entradas": [
         _e("conjuntos-consultas", "Conjuntos de consultas A, B e C",
            "As quinze consultas da busca, em português, em três conjuntos de cinco. O conjunto A combina termos de "
            "inteligência artificial, segurança pública, viés algorítmico e investigação criminal; o B, de inteligência "
            "artificial, segurança pública, viés algorítmico, discriminação e ética; o C trata das aplicações da inteligência "
            "artificial na segurança pública, na investigação criminal e no policiamento, inclusive o reconhecimento facial e "
            "as soluções tecnológicas. As mesmas consultas foram usadas na busca na web e no Google Scholar."),
         _e("busca-web", "Busca na web",
            "Busca em páginas da internet feita pelo serviço Perplexity, uma chamada por consulta. Devolve o endereço, o "
            "título e um trecho de cada página."),
         _e("google-scholar", "Google Scholar",
            "Buscador acadêmico consultado por meio do serviço SerpApi, uma chamada por página de resultados de cada consulta. "
            "Devolve o título, um trecho, os autores e a publicação de cada trabalho e, quando a fonte informa, o número de "
            "citações."),
     ]},
    {"id": "triagem-modelo", "titulo": "Triagem pelo modelo (versão v2)",
     "intro": "Um modelo de linguagem leu cada item e atribuiu os rótulos abaixo. São classificações automatizadas, não decisões "
              "de pesquisadores.",
     "entradas": [
         _e("triagem-escopo", "Triagem pelo modelo",
            "Classificação de cada item por um modelo de linguagem, com as instruções da versão v2, que cobrem os dois ângulos "
            "da pesquisa: o viés algorítmico e as aplicações tecnológicas da IA na segurança pública. O modelo é instruído a "
            "julgar pelo que o próprio item mostra (título, trecho, autores, ano e endereço), nunca pela consulta que o "
            "encontrou. As classificações de uma versão anterior (v1) continuam guardadas; as análises usam a v2, e a ocultação "
            "usa a classificação mais recente de cada item."),
         _e("relevancia", "Relevância",
            "O quanto o item trata do tema da pesquisa, segundo o modelo, em quatro níveis. O modelo é instruído a escolher "
            "entre alta e média pelo que o item mostra e, na dúvida entre manter e excluir, a manter. A relevância é um rótulo "
            "do modelo, não a decisão de uma pessoa de incluir ou excluir o item da revisão; o artigo que o modelo põe fora do "
            "escopo com confiança alta, numa resposta que passou na conferência automática, fica oculto, como explica “Item "
            "oculto pelo modelo”."),
         _e("relevancia-alta", "Relevância alta", "Segundo o modelo: " + rotulos.RELEVANCIA_V2["alta"] + "."),
         _e("relevancia-media", "Relevância média", "Segundo o modelo: " + rotulos.RELEVANCIA_V2["media"] + "."),
         _e("relevancia-baixa", "Relevância baixa", "Segundo o modelo: " + rotulos.RELEVANCIA_V2["baixa"] + "."),
         _e("relevancia-fora-do-escopo", "Fora do escopo", "Segundo o modelo: " + rotulos.RELEVANCIA_V2["fora_do_escopo"] + "."),
         _e("confianca-modelo", "Confiança do modelo",
            "O quanto o modelo diz estar seguro da relevância que deu: alta, média ou baixa. É uma declaração do próprio "
            "modelo, não uma medida de acerto."),
         _e("elegivel", "Elegível",
            "Relevância alta ou média segundo o modelo. É um rótulo técnico da triagem automática, não a inclusão do item na "
            "revisão."),
         _e("no-escopo", "No escopo",
            "Relevância alta, média ou baixa segundo o modelo. Ficam de fora os itens fora do escopo e os que não têm triagem "
            "válida."),
         _e("angulo", "Ângulo predominante",
            "O recorte do item, segundo o modelo: viés algorítmico, quando o tema central é viés, discriminação, equidade, "
            "ética, direitos, transparência, responsabilização ou governança da IA ou de algoritmos; ou aplicações "
            "tecnológicas, quando o tema central é o uso, a implantação, o desempenho, os produtos ou as soluções de IA ou de "
            "tecnologia, sem centrar o viés ou a ética. É um só ângulo por item, o que domina o título e o trecho; não quer "
            "dizer que a obra trate só desse tema."),
         _e("tipo-fonte", "Tipo de fonte",
            "Um entre 43 tipos fixos (artigo científico, dissertação, relatório, reportagem, norma, solução tecnológica e "
            "outros), escolhido pelo modelo. O sistema acrescenta o grupo: literatura científica, literatura cinzenta ou fonte "
            "primária (normas e regulação)."),
         _e("pais-escopo", "País ou escopo",
            "O país ou a abrangência do item segundo o modelo, em texto curto (por exemplo, Brasil, EUA, União Europeia ou "
            "Internacional). Quando o item não mostra, fica “Indeterminado”: o modelo é instruído a não supor Brasil só porque "
            "a busca foi em português."),
         _e("topicos", "Tópicos",
            "De um a cinco temas curtos que o modelo tira do item. Nas análises, os tópicos que aparecem como palavra ou "
            "expressão de alguma consulta ficam marcados como “termo de busca” e contam como os demais."),
         _e("eixo", "Eixo de exploração",
            "Um dos seis eixos de exploração definidos para a pesquisa, ou nenhum, escolhido pelo modelo. Os eixos foram "
            "pensados para o viés algorítmico, e itens sobre aplicações podem ficar sem eixo."),
         _e("justificativa", "Justificativa",
            "Frase curta em que o modelo diz por que deu aquela relevância; ele é instruído a usar até 25 palavras. Aparece na "
            "página de cada item."),
         _e("conferencia-automatica", "Conferência automática",
            "Depois de cada resposta, o programa confere, sem usar o modelo, se cada campo está entre as opções e dentro dos "
            "tamanhos permitidos. Uma resposta com algum campo fora disso fica marcada como inválida, e o item conta como sem "
            "triagem válida. A conferência olha o formato da resposta, não se a classificação está certa."),
     ]},
    {"id": "apresentacao", "titulo": "O que fica oculto e o que é decisão humana",
     "intro": "Como as telas tratam a classificação do modelo e a decisão de uma pessoa. Nada é apagado do banco.",
     "entradas": [
         _e("oculto-pelo-modelo", "Item oculto pelo modelo",
            "Um artigo do Scholar que o modelo pôs fora do escopo, com confiança alta e numa resposta que passou na "
            "conferência automática, fica oculto das listas de artigos enquanto nenhuma pessoa decidir sobre ele. Uma resposta "
            "fora do escopo sem confiança alta não oculta nada. O artigo oculto não é apagado: quem tem acesso pode mostrá-lo "
            "pelo filtro da lista, e a decisão de uma pessoa sempre prevalece. As referências da web não são ocultadas: a tela "
            "Referências mostra todas."),
         _e("decisao-humana", "Decisão humana",
            "A decisão de triagem registrada por uma pessoa sobre um artigo do Scholar (incluir ou excluir). É diferente da "
            "classificação do modelo e prevalece sobre ela. As referências da web ainda não passam por triagem humana. "
            "Enquanto não houver decisões humanas, os números da triagem são só do modelo."),
         _e("validacao-humana", "Validação humana da triagem",
            "Conferência, por uma pessoa que não vê a resposta do modelo no formulário, de uma amostra de 40 itens com triagem válida e tipo "
            "de fonte, sorteada uma só vez por estratos de relevância. Mede a concordância entre a pessoa e o modelo em quatro "
            "campos (relevância, grupo da fonte, eixo e país) e na elegibilidade; a concordância da elegibilidade para todos os "
            "itens triados é estimada pesando cada estrato pelo seu tamanho, e só quando todos os estratos têm resposta."),
         _e("sinais-brasil-tema", "Sinais de Brasil e de tema",
            "Ajuda de priorização nas listas de artigos: uma busca de palavras no título, no resumo, nos autores e no endereço "
            "procura sinais de que o artigo é brasileiro e de que trata de segurança pública. Não é a relevância da triagem "
            "pelo modelo e não oculta nem exclui nada."),
     ]},
    {"id": "execucoes", "titulo": "Execuções e reprodutibilidade",
     "intro": "Cada passagem de uma etapa é uma execução, com situação, configuração e custo próprios.",
     "entradas": _execucoes_reusadas},
]

SUBTITULO_REAL = (
    "O que cada número, status e motivo desta ferramenta significa, em linguagem simples. Os mesmos termos aparecem "
    "nas telas e na planilha Excel exportada."
)
SUBTITULO_VIES = (
    "O que significam as unidades de contagem, os rótulos da triagem pelo modelo e as regras de apresentação "
    "desta pesquisa, em linguagem simples."
)


def subtitulo(banco) -> str:
    return SUBTITULO_VIES if banco == "vies" else SUBTITULO_REAL


def secoes(banco):
    return SECOES_VIES if banco == "vies" else SECOES


def ids_de_ancoras(banco="real"):
    """Todas as ancoras do glossario, na ordem em que aparecem (secoes e entradas)."""
    secs = secoes(banco)
    return [s["id"] for s in secs] + [e["id"] for s in secs for e in s["entradas"]]
