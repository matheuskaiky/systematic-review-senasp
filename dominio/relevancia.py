"""Relevancia "Brasil + seguranca publica" de um artigo: heuristica transparente para ORDENAR e FILTRAR a triagem.

Funcao pura (sem I/O). Olha so o titulo, o resumo (snippet), o texto de autores/publicacao e o link do artigo e procura
dois tipos de marcadores, listados abaixo como constantes visiveis para qualquer pessoa auditar:

- Brasil: o artigo parece brasileiro (nome do pais, estados, cidades, instituicoes, dominio `.br`).
- Tema: o artigo parece tratar de seguranca publica (policia, crime, vigilancia, forense, sistema prisional...).

Niveis: "alta" (Brasil E tema), "media" (so um dos dois) e "baixa" (nenhum). E uma AJUDA de priorizacao, nao um criterio de
inclusao: nada e excluido, escondido ou decidido por ela; quem decide e a pessoa que faz a triagem. Frases sem marcador
(por exemplo, "aprendizado de maquina" ou "reconhecimento facial" sozinhos) nao contam como tema; "seguranca" sozinha tambem
nao (poderia ser seguranca da informacao), so as formas compostas ("seguranca publica", "public safety"...).

Como o casamento funciona: o texto e passado para minusculas, sem acentos, e tudo que nao for letra ou numero vira espaco.
Cada marcador so casa como palavra inteira (assim "pm" ou "br" nao casam dentro de "ampm" ou "abrir"). Um marcador terminado
em `*` e um radical: casa a palavra que comeca por ele (`brasileir*` casa brasileiro, brasileiras...). Marcadores escritos com
acento sao comparados sem acento. O dominio `.br` so e procurado no link e no campo de autores/publicacao (onde o Google
Scholar costuma mostrar o site de origem), nunca no titulo ou no resumo.
"""
import re
import unicodedata
from urllib.parse import urlsplit

NIVEIS = ("alta", "media", "baixa")

# ---------------------------------------------------------------------------------------------------------------------
# Marcadores de Brasil. Evitados de proposito: "para" (estado do Para: e a preposicao), "acre" (unidade de area em ingles),
# "natal", "salvador", "fortaleza", "vitoria", "palmas" (palavras comuns) e a sigla "pm" (tambem "da tarde").
# Observacao: "sbc" tambem designa "computador de placa unica" em ingles; aqui conta como Brasil (Sociedade Brasileira de
# Computacao), o que no maximo sobe um artigo para "media" e fica visivel nos sinais.
# ---------------------------------------------------------------------------------------------------------------------
MARCADORES_BRASIL = (
    # o pais
    "brasil", "brazil", "brazilian", "brasileir*",
    # estados (nomes que nao se confundem com palavras comuns)
    "alagoas", "amapá", "amazonas", "bahia", "ceará", "distrito federal", "espírito santo", "goiás", "maranhão",
    "mato grosso", "minas gerais", "paraíba", "paraná", "pernambuco", "piauí", "rio de janeiro", "rio grande do norte",
    "rio grande do sul", "rondônia", "roraima", "santa catarina", "são paulo", "sergipe", "tocantins",
    "estado do pará", "estado do acre",
    # cidades conhecidas
    "brasília", "belo horizonte", "curitiba", "porto alegre", "manaus", "goiânia", "campinas", "florianópolis", "teresina",
    "joão pessoa", "cuiabá", "são luís", "aracaju", "recife", "niterói", "porto velho", "maceió", "belém",
    # forcas de seguranca e instituicoes
    "polícia militar", "polícia civil", "polícia federal", "polícia rodoviária federal", "guarda municipal", "senasp",
    "ministério da justiça", "ibge", "cnpq", "sbc", "lgpd", "lei geral de proteção de dados",
    # universidades (siglas) e termos tipicamente brasileiros
    "usp", "unicamp", "ufmg", "ufrj", "ufpi", "ufrgs", "ufsc", "unb", "favela*",
)

# Hosts brasileiros que nao terminam em `.br` (o dominio `.br` e tratado a parte, no link e em autores/publicacao).
DOMINIOS_BRASIL_SEM_BR = ("unesc.net",)

# ---------------------------------------------------------------------------------------------------------------------
# Marcadores de tema (seguranca publica). Evitados de proposito: "security" e "seguranca" sozinhos (ciberseguranca),
# "machine learning", "reconhecimento facial" e "computer vision" (tecnologias, nao o tema), e o radical "polic*" (casaria
# "policy"/"policies"): as formas de "policia" estao listadas uma a uma.
# ---------------------------------------------------------------------------------------------------------------------
MARCADORES_TEMA = (
    # seguranca publica
    "segurança pública", "public security", "public safety", "segurança urbana", "ordem pública", "public order",
    "defesa social", "guarda municipal",
    # policia
    "polícia", "policial", "policiais", "policiamento", "police", "policing", "law enforcement", "inteligência policial",
    "viatura*", "delegacia*",
    # crime e violencia
    "crime", "crimes", "crimin*", "delito", "delitos", "homicídio*", "homicide*", "furto*", "roubo*", "violência urbana",
    "urban violence",
    # vigilancia e perícia
    "vigilância", "surveillance", "videomonitoramento", "videovigilância", "forense*", "forensic*",
    # sistema penal e prisional
    "penal", "prisão", "prisões", "prison*", "prisional", "penitenciári*", "presídio*",
)

_RX_SEM_ESPACO = re.compile(r"[^a-z0-9]+")
# nome de host terminado em .br dentro de um texto livre
_RX_HOST_BR = re.compile(r"(?<![a-z0-9-])(?:[a-z0-9-]+\.)+br(?![a-z0-9-])")


def _normalizar(texto):
    """Minusculas, sem acentos, e tudo que nao for letra ou numero vira um espaco."""
    if texto is None:
        return ""
    sem_acento = "".join(c for c in unicodedata.normalize("NFKD", str(texto).lower()) if not unicodedata.combining(c))
    return " " + _RX_SEM_ESPACO.sub(" ", sem_acento).strip() + " "


def _compilar(marcadores):
    """Devolve (regex unica, {marcador normalizado: marcador como escrito}); frases mais longas primeiro."""
    rotulos, partes = {}, []
    for m in sorted(marcadores, key=lambda x: (-len(x), x)):
        radical = m.endswith("*")
        norm = _normalizar(m.rstrip("*")).strip()
        if not radical:
            rotulos[norm] = m
        partes.append(re.escape(norm).replace(r"\ ", " ") + (r"[a-z0-9]*" if radical else ""))
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(partes) + r")(?![a-z0-9])"), rotulos


_RX_BRASIL, _ROTULOS_BRASIL = _compilar(MARCADORES_BRASIL)
_RX_TEMA, _ROTULOS_TEMA = _compilar(MARCADORES_TEMA)


def _achar(rx, rotulos, texto_normalizado):
    """Sinais encontrados, sem repeticao, na ordem em que aparecem no texto."""
    vistos = []
    for m in rx.finditer(texto_normalizado):
        sinal = rotulos.get(m.group(0), m.group(0))
        if sinal not in vistos:
            vistos.append(sinal)
    return vistos


def _host_do_link(link):
    texto = str(link or "").strip().lower()
    if not texto:
        return ""
    try:
        return (urlsplit(texto if "//" in texto else "//" + texto).hostname or "")
    except ValueError:
        return ""


def _sinais_de_dominio(link, autores):
    """Sinais de dominio brasileiro: `.br` (host do link ou nome de site no texto de autores/publicacao) e hosts conhecidos."""
    host = _host_do_link(link)
    sinais = []
    if host.endswith(".br") or _RX_HOST_BR.search(str(autores or "").lower()):
        sinais.append(".br")
    hosts = [host] + re.findall(r"(?<![a-z0-9-])(?:[a-z0-9-]+\.)+[a-z]{2,}", str(autores or "").lower())
    for dominio in DOMINIOS_BRASIL_SEM_BR:
        if any(h == dominio or h.endswith("." + dominio) for h in hosts):
            sinais.append(dominio)
    return sinais


def pontuar_relevancia(titulo, snippet, autores_publicacao, link):
    """Avalia um artigo. Devolve {"brasil", "tema", "nivel", "sinais", "sinais_brasil", "sinais_tema", "pontos"}.

    `sinais` junta os marcadores encontrados (Brasil primeiro, depois tema), sem repeticao, para mostrar na tela.
    `pontos` serve so para ordenar: 10 por categoria presente, mais 1 por sinal distinto (ate 5 por categoria) e mais 1
    por sinal que aparece no titulo (ate 5). Entradas vazias ou None sao aceitas."""
    texto = _normalizar(" ".join(str(p) for p in (titulo, snippet, autores_publicacao) if p))
    sinais_brasil = _achar(_RX_BRASIL, _ROTULOS_BRASIL, texto) + _sinais_de_dominio(link, autores_publicacao)
    sinais_tema = _achar(_RX_TEMA, _ROTULOS_TEMA, texto)
    brasil, tema = bool(sinais_brasil), bool(sinais_tema)
    nivel = "alta" if brasil and tema else "media" if brasil or tema else "baixa"
    no_titulo = _normalizar(titulo)
    n_titulo = len(_achar(_RX_BRASIL, _ROTULOS_BRASIL, no_titulo)) + len(_achar(_RX_TEMA, _ROTULOS_TEMA, no_titulo))
    pontos = (10 if brasil else 0) + (10 if tema else 0) + min(len(sinais_brasil), 5) + min(len(sinais_tema), 5) + min(n_titulo, 5)
    return {"brasil": brasil, "tema": tema, "nivel": nivel, "sinais": list(dict.fromkeys(sinais_brasil + sinais_tema)),
            "sinais_brasil": sinais_brasil, "sinais_tema": sinais_tema, "pontos": pontos}
