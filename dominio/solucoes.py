"""Solucoes conhecidas (RC17) e busca no texto (RC16): regras puras de casamento de nomes, sem I/O.

Regra de casamento (a mesma em toda a busca):
  1. `normalizar` tira acentos, passa para minusculas, troca toda sequencia de caracteres que nao sao letras ou numeros por UM espaco
     e poe um espaco no comeco e no fim. "BO-Fácil!" e "bo facil" ficam iguais: " bo facil ".
  2. `casar(texto_norm, termo_norm)` e uma busca de trecho sobre os textos ja normalizados. Como o termo normalizado vem com os espacos das
     pontas, o casamento e de PALAVRA (ou frase) INTEIRA: "spia" casa em "o SPiA foi" e NAO casa em "espiando" nem em "spiano".
     Para a busca por trecho qualquer (sem fronteira de palavra), o chamador tira os espacos das pontas do termo (`.strip()`).
  3. Plural, sigla colada ("BOFacil") e erro de digitacao NAO casam: o pesquisador informa as variantes como apelidos.

`trecho_ao_redor` devolve o pedaco do texto ORIGINAL (com acentos e maiusculas) ao redor do achado, para mostrar com destaque. Para isso
guarda, para cada caractere do texto normalizado, a posicao do caractere de origem. Nunca levanta erro por causa de Unicode estranho."""
import re
import unicodedata
from dataclasses import dataclass

_COMBINANTES = re.compile("[̀-ͯ]+")
_NAO_ALFANUM = re.compile(r"[\W_]+")
_ESPACOS = re.compile(r"\s+")


@dataclass(frozen=True)
class SolucaoConhecida:
    """Uma solucao de IA que o pesquisador sabe que existe, para medir se a coleta a encontra."""
    nome: str
    uf: str
    apelidos: tuple = ()
    observacao: str = ""


def _base(texto):
    """NFKD, minusculas sem contexto (casefold) e sem marcas de acento; ainda com pontuacao."""
    return _COMBINANTES.sub("", unicodedata.normalize("NFKD", str(texto or "")).casefold())


class _Tabela(dict):
    """Tabela de `str.translate`: cada caractere vira o seu equivalente normalizado (minusculo, sem acento, pontuacao -> espaco) e o
    resultado de cada caractere novo fica guardado. Traduzir caractere a caractere e equivalente a normalizar o texto inteiro (nenhuma
    regra depende do contexto) e muito mais rapido que `unicodedata.normalize` mais expressoes regulares sobre todo o texto."""

    def __missing__(self, codigo):
        valor = _NAO_ALFANUM.sub(" ", _base(chr(codigo)))
        self[codigo] = valor
        return valor


_TABELA = _Tabela()
for _i in range(128):
    _TABELA[_i] = chr(_i).lower() if chr(_i).isalnum() else " "


def normalizar(texto):
    """Texto sem acentos, em minusculas, so com letras e numeros separados por um espaco, com um espaco em cada ponta."""
    miolo = " ".join(str(texto or "").translate(_TABELA).split())
    return f" {miolo} " if miolo else " "


def casar(texto_norm, termo_norm):
    """True se o termo (ja normalizado) esta no texto (ja normalizado). Termo vazio nunca casa. Ver a regra no topo do modulo."""
    return bool(termo_norm.strip()) and termo_norm in texto_norm


def variantes_da_solucao(solucao):
    """Nome e apelidos, normalizados (com espacos nas pontas), sem repeticao e sem vazios, na ordem em que foram informados."""
    vistas = []
    for t in (solucao.nome, *solucao.apelidos):
        n = normalizar(t)
        if n.strip() and n not in vistas:
            vistas.append(n)
    return vistas


_FIM_DE_BRANCO = re.compile(r"\s")
_PEDACO = 2048                       # tamanho aproximado dos pedacos em que o texto e percorrido ao mapear posicoes


def _mapear_pedaco(pedaco):
    """mapa[i] = posicao em `pedaco` do caractere de origem de norm[i], onde norm e o pedaco normalizado, sem espaco nas pontas.
    Percorre caractere a caractere (devagar): so e chamado para o pedaco que contem o trecho achado."""
    mapa, anterior_espaco = [], True
    for i, c in enumerate(pedaco):
        for n in _TABELA[ord(c)]:
            if n == " ":
                if anterior_espaco:
                    continue
                anterior_espaco = True
            else:
                anterior_espaco = False
            mapa.append(i)
    return mapa


def _posicoes_originais(texto, alvos):
    """{p: posicao em `texto`} para cada posicao p de `alvos` no texto normalizado COM o espaco inicial (a de `normalizar(texto)`).
    O texto e percorrido em pedacos cortados em espacos em branco (que nunca partem uma palavra); a tabela de cada pedaco e montada
    so quando ele contem um alvo, o que torna a busca de poucos trechos em textos grandes cerca de dez vezes mais rapida."""
    alvos = sorted(set(alvos))
    saida, k, n, ini, pos = {}, 0, len(texto), 0, 1
    while ini < n and k < len(alvos):
        fim = min(ini + _PEDACO, n)
        if fim < n:
            m = _FIM_DE_BRANCO.search(texto, fim)
            fim = m.end() if m else n
        palavras = texto[ini:fim].translate(_TABELA).split()
        if palavras:
            tamanho = sum(map(len, palavras)) + len(palavras) - 1
            if alvos[k] < pos + tamanho:
                mapa = _mapear_pedaco(texto[ini:fim])
                while k < len(alvos) and alvos[k] < pos + tamanho:
                    saida[alvos[k]] = ini + mapa[alvos[k] - pos]
                    k += 1
            pos += tamanho + 1
        ini = fim
    return saida


def _compacto(s):
    return _ESPACOS.sub(" ", s)


def trechos_ao_redor(texto, termo, largura=160, inteira=True, maximo=2, texto_norm=None):
    """Ate `maximo` trechos (antes, achado, depois) no texto ORIGINAL, sem se sobrepor. `largura` e o numero de caracteres de cada lado;
    quando o texto continua alem do recorte, o lado ganha reticencias. `inteira`: palavra/frase inteira (padrao) ou trecho qualquer.
    `texto_norm`: `normalizar(texto)` ja calculado (quem busca em muitos textos o guarda), para nao refazer a conta."""
    texto = str(texto or "")
    alvo = normalizar(termo)
    nucleo = alvo.strip()
    if not nucleo or maximo < 1:
        return []
    busca = alvo if inteira else nucleo
    deslocamento = busca.find(nucleo)
    norm = texto_norm if texto_norm is not None else normalizar(texto)
    achados, inicio = [], 0
    while len(achados) < maximo:
        p = norm.find(busca, inicio)
        if p < 0:
            break
        achados.append(p + deslocamento)
        inicio = achados[-1] + len(nucleo)
    mapa = _posicoes_originais(texto, [x for p in achados for x in (p, p + len(nucleo) - 1)])
    trechos = []
    for p in achados:
        ini_o, fim_o = mapa[p], mapa[p + len(nucleo) - 1] + 1
        a0, b0 = max(ini_o - largura, 0), min(fim_o + largura, len(texto))
        antes = _compacto(texto[a0:ini_o]).lstrip() if a0 else _compacto(texto[a0:ini_o])
        depois = _compacto(texto[fim_o:b0]).rstrip() if b0 < len(texto) else _compacto(texto[fim_o:b0])
        trechos.append((("…" if a0 else "") + antes, texto[ini_o:fim_o], depois + ("…" if b0 < len(texto) else "")))
    return trechos


def trecho_ao_redor(texto, termo, largura=160, inteira=True, texto_norm=None):
    """O primeiro trecho de `trechos_ao_redor`, ou None quando o texto nao cita o termo."""
    r = trechos_ao_redor(texto, termo, largura, inteira, 1, texto_norm)
    return r[0] if r else None


# ---------- situacao de uma solucao conhecida ----------
NAO_APARECEU = "nao_apareceu_nos_resultados"
SO_NOS_RESULTADOS = "apareceu_nos_resultados_pagina_nao_baixada"
PAGINA_SEM_ACHADO = "pagina_baixada_nenhum_achado_cita_o_nome"
EM_ACHADOS = "citada_em_achados"
SITUACOES = (NAO_APARECEU, SO_NOS_RESULTADOS, PAGINA_SEM_ACHADO, EM_ACHADOS)

_ROTULOS = {
    NAO_APARECEU: "Não apareceu nos resultados da busca",
    SO_NOS_RESULTADOS: "Apareceu nos resultados, mas nenhuma página baixada cita o nome",
    PAGINA_SEM_ACHADO: "Está no texto de página baixada, mas nenhum achado cita o nome",
    EM_ACHADOS: "Citada em achados",
}
_EXPLICACOES = {
    NAO_APARECEU: "O nome não está em nenhum título ou resumo de resultado de busca desta UF nem no texto das páginas baixadas. "
                  "A coleta não a encontrou. Isso NÃO prova que a solução não é usada: a busca devolve poucos resultados por consulta, "
                  "o ranking muda de uma execução para outra e nem toda consulta cobre este tipo de solução.",
    SO_NOS_RESULTADOS: "O nome aparece no título ou no resumo de resultados de busca, mas nenhuma página baixada o cita. Falta baixar a "
                       "página que o cita (ela pode ter ficado fora do limite de downloads ou só ter aparecido em uma execução de teste).",
    PAGINA_SEM_ACHADO: "O nome aparece no texto de página(s) já baixada(s), mas nenhum achado o cita pelo nome. A ideia pode estar nos achados "
                       "dessas páginas, descrita sem o nome (o classificador não guarda o nome da solução). Falta ligar a página ao achado.",
    EM_ACHADOS: "Pelo menos um achado cita o nome na evidência (ou no campo do nome da solução). A coleta encontrou, baixou e classificou "
                "a solução.",
}


def situacao_da_solucao(n_resultados, n_paginas, n_achados_nome):
    """O ponto mais avancado do funil que a solucao alcancou: achados que citam o nome, depois paginas baixadas que o citam, depois
    resultados de busca que o citam, ou nenhum. Os tres numeros contam itens que CITAM O NOME (nao o total de itens da UF)."""
    if n_achados_nome > 0:
        return EM_ACHADOS
    if n_paginas > 0:
        return PAGINA_SEM_ACHADO
    if n_resultados > 0:
        return SO_NOS_RESULTADOS
    return NAO_APARECEU


def rotulo_da_situacao(situacao):
    return _ROTULOS.get(situacao, situacao)


def explicacao_da_situacao(situacao):
    return _EXPLICACOES.get(situacao, "")
