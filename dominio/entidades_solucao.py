"""Resolucao de entidades de `nome_solucao` (RC23): o modelo escreve o mesmo sistema de varios jeitos ("SPiA", "SPIA", "Sistema de
Policiamento por Inteligencia Artificial"; "BO Facil", "B.O. Facil"). Aqui os nomes brutos viram ENTIDADES, so com regras
deterministicas e a biblioteca padrao, sem I/O e sem chamar modelo. O valor bruto NUNCA e alterado no banco: este modulo so agrupa
para exibir, e cada fusao diz qual camada a fez e por que.

Entrada: `contagens` = {(nome_bruto, uf): n_achados} e a lista de `SolucaoConhecida`. Saida: `Resolucao` (entidades, variantes, camadas).

TRES CAMADAS, aplicadas nesta ordem de confianca (a camada de uma variante e a MAIS FRACA da cadeia que a liga ao nome canonico):

  1. CADASTRO (config/solucoes_conhecidas.py). Um nome bruto cuja forma normalizada (sem acento, caixa, pontuacao; "B.O." vira "BO") e igual ao
     nome ou a um apelido de uma solucao conhecida entra na entidade dela. Tambem vale o nome sem a UF no fim ("SPiA - PI") e cada lado dos
     formatos "Nome (SIGLA)" / "SIGLA - Nome". REGRA DA UF: a solucao cadastrada para PI so absorve nomes brutos de achados do PI (ou de UF
     desconhecida, ""), a menos que o cadastro declare `outras_ufs` (as UFs em que o mesmo nome identifica a mesma solucao; "*" = todas).
     Dois cadastros diferentes nunca se fundem entre si.
  2. SIGLA <-> NOME POR EXTENSO (sem cadastro). (a) As iniciais do nome por extenso, sem artigos e preposicoes (de da do dos das por para em na
     no e com ao a o), formam a sigla de outro nome curto da mesma UF: "Sistema de Policiamento por Inteligencia Artificial" -> SPIA (tambem
     sem o prefixo generico: PIA; e com siglas de 2 ou 3 letras em maiusculas inteiras: "... por IA" -> SPIA). Nao conta numero. A sigla
     precisa ter de 3 a 8 caracteres. (b) O proprio valor segue "Nome por Extenso (SIGLA)", "SIGLA - Nome por Extenso" ou "Nome - SIGLA"
     (travessao e dois-pontos valem): liga o valor, o nome por extenso e a sigla que existirem soltos nos dados. SIGLA = uma palavra de 2 a 8
     letras ou numeros com mais da metade das letras em maiusculas (e nunca uma UF). Uma UF no fim e tolerada ("SPIA PI" com achado do PI).
  3. SEMELHANCA LEXICAL (mais fraca, sempre sinalizada). Compara as palavras de conteudo, sem acento, caixa, pontuacao, UF final, artigos e
     prefixo generico (Sistema, Projeto, Programa, Plataforma, Operacao, App, Aplicativo). Funde quando: (i) as grafias sao iguais depois disso
     ("BO Facil" = "B.O. Facil" = "BOFacil"; "Projeto Vigia" = "Vigia"; "Sistema SPiA" = "SPiA"); ou (ii) tem o mesmo numero de palavras, a razao
     de `difflib.SequenceMatcher` e >= 0,88 e cada par de palavras e igual, plural (+s/+es) ou, em palavras de 7 letras ou mais, parecido (razao
     >= 0,85: erro de digitacao). Palavras curtas que diferem em uma letra ("norte"/"sorte", "nuvem"/"nuven") sao tratadas como nomes diferentes.
     Barreiras: os numeros (arabicos e romanos, "4.0" = 4 e 0) devem ser os mesmos e na mesma ordem; nunca entre UFs diferentes; nome com
     3 caracteres ou menos (sem espacos) so se funde por grafia normalizada IDENTICA; dois prefixos genericos diferentes ("Operacao Verao" x
     "Programa Verao") nao se fundem diretamente.

Todas as ligacoes sao decididas por pares de nomes (nao por ordem de chegada) e a particao e o fecho transitivo delas: acrescentar um nome nunca
separa uma entidade existente, e a ordem de entrada nao muda nada. A unica excecao sao dois cadastros ligados por um mesmo nome: a ligacao
mais forte vence (desempate pela ordem do cadastro).

NOME CANONICO: o nome oficial do cadastro, se a entidade tem um; senao a forma bruta mais frequente (soma dos achados); empate: a bem
formatada (tem maiuscula sem ser tudo em maiusculas, ou e sigla curta toda em maiusculas), depois a com mais letras acentuadas (a grafia
correta), depois a mais curta, depois a primeira em ordem dos caracteres (maiuscula antes de minuscula)."""
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

from dominio.solucoes import SolucaoConhecida, normalizar

LIMIAR_SEMELHANCA = 0.88            # razao minima de SequenceMatcher entre os nomes comparados (camada 3)
LIMIAR_PALAVRA_LONGA = 0.85         # razao minima entre palavras de 7 letras ou mais para valer como erro de digitacao
LIMIAR_QUASE = 0.70                 # so para o diagnostico: pares recusados a partir desta razao aparecem como "quase fusoes"
MIN_SIGLA, MAX_SIGLA = 3, 8         # tamanho da sigla gerada pelas iniciais (camada 2)
MAX_CURTO = 3                       # nomes assim curtos (sem espacos) so se fundem por grafia normalizada identica

PALAVRAS_VAZIAS = frozenset("de da do dos das por para em na no e com ao a o".split())
PREFIXOS_GENERICOS = ("sistema", "projeto", "programa", "plataforma", "operacao", "app", "aplicativo")
UFS = frozenset("ac al am ap ba ce df es go ma mg ms mt pa pb pe pi pr rj rn ro rr rs sc se sp to".split())
ROMANOS = {r: i + 1 for i, r in enumerate("i ii iii iv v vi vii viii ix x xi xii xiii xiv xv xvi xvii xviii xix xx".split())}

ROTULO_CAMADA = {0: "nome do próprio achado", 1: "pelo cadastro", 2: "sigla e nome por extenso", 3: "unificado por semelhança"}

_PONTOS_DE_SIGLA = re.compile(r"(?<!\w)(?:[^\W\d_]\.)+(?:[^\W\d_](?!\w))?")     # "B.O." / "B.O" / "S.P.I.A."
_PALAVRA = re.compile(r"[^\W_]+")
_ENTRE_PARENTESES = re.compile(r"^\s*(?P<a>[^()]+?)\s*\(\s*(?P<b>[^()]+?)\s*\)\s*$")
_COM_TRACO = re.compile(r"^\s*(?P<a>.+?)(?:\s+[-–—]\s+|\s*:\s+)(?P<b>.+?)\s*$")


# ---------- resultado ----------
@dataclass(frozen=True)
class Variante:
    """Uma forma bruta (nome, UF) dentro de uma entidade. `camada` 0 = e a propria forma canonica; 1, 2 ou 3 = a camada mais fraca da cadeia
    de fusoes ate o nome canonico; `motivo` explica a ligacao em portugues."""
    bruto: str
    uf: str
    n: int
    camada: int
    motivo: str = ""

    @property
    def rotulo_camada(self):
        return ROTULO_CAMADA[self.camada]


@dataclass(frozen=True)
class Entidade:
    canonico: str
    ufs: tuple
    n: int                                  # achados somados de todas as variantes
    variantes: tuple                        # tuple[Variante], da mais citada para a menos
    conhecida: object = None                # SolucaoConhecida do cadastro, ou None

    @property
    def unificada(self):
        """Mais de uma grafia bruta foi reunida (ou o nome oficial do cadastro difere da unica grafia achada)."""
        return len({v.bruto for v in self.variantes}) > 1 or any(v.bruto != self.canonico for v in self.variantes)

    @property
    def camada_max(self):
        return max((v.camada for v in self.variantes), default=0)

    @property
    def outras_grafias(self):
        """Grafias brutas diferentes do nome canonico, sem repeticao, da mais citada para a menos."""
        vistas = []
        for v in self.variantes:
            if v.bruto != self.canonico and v.bruto not in vistas:
                vistas.append(v.bruto)
        return vistas

    @property
    def pares(self):
        return tuple((v.bruto, v.uf) for v in self.variantes)


@dataclass(frozen=True)
class Resolucao:
    entidades: tuple                        # tuple[Entidade], do nome mais citado para o menos
    recusados: tuple = ()                   # so com diagnostico=True: (bruto_a, bruto_b, uf, razao, motivo_da_recusa)
    _por_no: dict = None

    def entidade_de(self, bruto, uf):
        """A entidade de um nome bruto (como esta no banco) naquela UF, ou None se o nome nao entrou na resolucao."""
        return (self._por_no or {}).get((bruto, uf or ""))

    def canonico_de(self, bruto, uf):
        e = self.entidade_de(bruto, uf)
        return e.canonico if e else bruto

    @property
    def canonico_por_bruto(self):
        return {(v.bruto, v.uf): e.canonico for e in self.entidades for v in e.variantes}

    @property
    def camada_por_bruto(self):
        return {(v.bruto, v.uf): v.camada for e in self.entidades for v in e.variantes}

    @property
    def variantes_por_canonico(self):
        """{canonico: [(bruto, n)]}: entidades de UFs diferentes com o mesmo rotulo ficam juntas aqui; use `entidades` para separa-las."""
        saida = {}
        for e in self.entidades:
            saida.setdefault(e.canonico, []).extend((v.bruto, v.n) for v in e.variantes)
        return saida

    def entidades_do_nome(self, canonico):
        return [e for e in self.entidades if e.canonico == canonico]

    def pares_do_canonico(self, canonico):
        """[(nome_bruto, uf)] de todas as variantes das entidades com este nome canonico (para filtrar os achados)."""
        return [p for e in self.entidades_do_nome(canonico) for p in e.pares]

    def entidade_da_conhecida(self, conhecida):
        for e in self.entidades:
            if e.conhecida == conhecida:
                return e
        return None

    @property
    def n_achados(self):
        return sum(e.n for e in self.entidades)


# ---------- normalizacao ----------
def _sem_pontos_de_sigla(texto):
    return _PONTOS_DE_SIGLA.sub(lambda m: m.group().replace(".", ""), str(texto or ""))


def _palavras(bruto):
    """[(palavra normalizada, e_sigla_em_maiusculas)] do texto, com "B.O." ja colado em "BO"."""
    saida = []
    for p in _PALAVRA.findall(unicodedata.normalize("NFC", _sem_pontos_de_sigla(bruto))):
        maiuscula = p.isupper() and 2 <= len(p) <= 3
        saida.extend((t, maiuscula) for t in normalizar(p).split())
    return saida


def chave(nome):
    """Forma normalizada usada para comparar: sem acento, caixa, pontuacao; "B.O. Fácil" = "BO Facil" = "bo facil"."""
    return " ".join(t for t, _ in _palavras(nome))


def _numero(token):
    if token.isdigit():
        return int(token)
    return ROMANOS.get(token)


def _assinatura_numerica(tokens):
    return tuple(n for n in map(_numero, tokens) if n is not None)


def _parece_sigla(texto):
    """Uma palavra de 2 a 8 caracteres com mais da metade das letras em maiusculas, que nao e uma UF."""
    t = _sem_pontos_de_sigla(texto).strip()
    if not re.fullmatch(r"[^\W_]{2,8}", t):
        return False
    letras = [c for c in t if c.isalpha()]
    maiusculas = sum(c.isupper() for c in letras)
    return len(letras) >= 2 and maiusculas >= max(2, (len(letras) + 1) // 2) and normalizar(t).strip() not in UFS


def _partes_do_formato(bruto):
    """(nome por extenso, sigla) se o valor segue "Nome (SIGLA)", "SIGLA - Nome" ou "Nome - SIGLA"; senao None."""
    m = _ENTRE_PARENTESES.match(bruto) or _COM_TRACO.match(bruto)
    if not m:
        return None
    a, b = m.group("a").strip(), m.group("b").strip()
    for extenso, sigla in ((a, b), (b, a)):
        if _parece_sigla(sigla) and not _parece_sigla(extenso) and len(chave(extenso).split()) >= 2:
            return extenso, sigla
    return None


# ---------- perfil de um nome ----------
class _No:
    """Um nome comparavel: forma bruta (ou nome/apelido de um cadastro) com a UF e o que as camadas precisam saber dele."""
    __slots__ = ("bruto", "uf", "n", "virtual", "ufs", "conhecida", "indice", "tokens", "chave", "assinatura", "partes", "chaves_partes",
                 "prefixo", "conteudo", "compacto", "acronimos", "tem_sigla")

    def __init__(self, bruto, uf, n=0, virtual=False, ufs=frozenset(), conhecida=None, indice=-1):
        self.bruto, self.uf, self.n, self.virtual, self.ufs, self.conhecida, self.indice = bruto, uf, n, virtual, ufs, conhecida, indice
        palavras = _palavras(bruto)
        if len(palavras) > 1 and uf and palavras[-1][0] == uf.lower():           # UF no fim: tolerada
            palavras = palavras[:-1]
        self.tokens = tuple(t for t, _ in palavras)
        self.chave = " ".join(self.tokens)
        self.assinatura = _assinatura_numerica(self.tokens)
        formato = _partes_do_formato(bruto)
        self.partes = formato
        self.chaves_partes = frozenset({chave(formato[0]), chave(formato[1])}) if formato else frozenset()
        # forma de comparacao da camada 3: sem prefixo generico (se sobrar algo que nao seja palavra vazia) e sem palavras vazias
        resto = list(self.tokens)
        self.prefixo = None
        if len(resto) > 1 and resto[0] in PREFIXOS_GENERICOS and resto[1] not in PALAVRAS_VAZIAS:
            self.prefixo, resto = resto[0], resto[1:]
        # numerais romanos viram arabicos na comparacao: "Paz II" = "Paz 2"
        self.conteudo = tuple(str(_numero(t)) if _numero(t) is not None else t for t in resto if t not in PALAVRAS_VAZIAS)
        self.compacto = "".join(self.conteudo)
        self.tem_sigla = (len(self.tokens) == 1 and MIN_SIGLA <= len(self.tokens[0]) <= MAX_SIGLA
                          and not self.tokens[0].isdigit())
        self.acronimos = self._acronimos(palavras)

    def _acronimos(self, palavras):
        """Siglas que as iniciais do nome por extenso formam (camada 2a). Vazio para nomes de uma palavra so."""
        itens = [(t, m) for t, m in palavras if t not in PALAVRAS_VAZIAS and _numero(t) is None]
        if len(itens) < 2:
            return frozenset()
        variantes = [itens]
        if itens[0][0] in PREFIXOS_GENERICOS and len(itens) > 2:
            variantes.append(itens[1:])
        saida = set()
        for v in variantes:
            saida.add("".join(t[0] for t, _ in v))
            saida.add("".join(t if m else t[0] for t, m in v))              # "por IA": a sigla de 2 ou 3 letras entra inteira
        return frozenset(a for a in saida if MIN_SIGLA <= len(a) <= MAX_SIGLA)

    def aceita_uf(self, outro):
        """Regra da UF entre dois nos (ver o topo do modulo)."""
        if self.virtual and outro.virtual:
            return False
        if self.virtual or outro.virtual:
            v, r = (self, outro) if self.virtual else (outro, self)
            return r.uf == "" or "*" in v.ufs or r.uf in v.ufs
        return self.uf == outro.uf


# ---------- camadas ----------
def _palavras_parecidas(x, y):
    if x == y:
        return True
    if x.isdigit() or y.isdigit():
        return False
    curta, longa = sorted((x, y), key=len)
    if len(curta) >= 4 and (longa == curta + "s" or longa == curta + "es"):
        return True
    return len(curta) >= 7 and SequenceMatcher(None, x, y).ratio() >= LIMIAR_PALAVRA_LONGA


def _camada1(r, k):
    """Liga o nome bruto `r` ao nome/apelido `k` (no virtual de um cadastro). Devolve o motivo ou None."""
    if not r.aceita_uf(k):
        return None
    alvo = k.chave
    papel = "nome" if k.bruto == k.conhecida.nome else "apelido"
    if alvo and alvo == r.chave:
        return f"cadastro: «{r.bruto}» equivale ao {papel} cadastrado «{k.bruto}» de {k.conhecida.nome}"
    if r.partes and alvo in {chave(r.partes[0]), chave(r.partes[1])}:
        return f"cadastro: «{r.bruto}» traz «{k.bruto}» ({papel} cadastrado de {k.conhecida.nome}) no formato Nome (SIGLA)"
    return None


def _camada2(a, b):
    """Sigla e nome por extenso (iniciais ou formato Nome (SIGLA)). Devolve o motivo ou None. Simetrica."""
    if a.assinatura != b.assinatura:
        return None
    for curto, longo in ((a, b), (b, a)):
        if curto.tem_sigla and longo.partes is None and curto.tokens[0] in longo.acronimos:
            return f"sigla e nome por extenso: as iniciais de «{longo.bruto}» formam {curto.tokens[0].upper()} («{curto.bruto}»)"
    for com_formato, outro in ((a, b), (b, a)):
        if com_formato.partes and outro.partes is None and outro.chave in com_formato.chaves_partes:
            return f"formato Nome (SIGLA): «{com_formato.bruto}» liga «{com_formato.partes[1]}» a «{com_formato.partes[0]}»"
    if a.partes and b.partes and a.chaves_partes & b.chaves_partes:
        return f"formato Nome (SIGLA): «{a.bruto}» e «{b.bruto}» compartilham nome ou sigla"
    return None


def _camada3(a, b):
    """Semelhanca lexical. Devolve (razao, motivo, None) se funde ou (razao, None, motivo_da_recusa) se recusa. Nao olha a UF."""
    if not a.conteudo or not b.conteudo:
        return 0.0, None, "sem palavras de conteudo"
    if a.assinatura != b.assinatura:
        ra = SequenceMatcher(None, a.compacto, b.compacto).ratio()
        return ra, None, f"numerais diferentes ({'/'.join(map(str, a.assinatura)) or 'nenhum'} e {'/'.join(map(str, b.assinatura)) or 'nenhum'})"
    if a.prefixo and b.prefixo and a.prefixo != b.prefixo:
        ra = SequenceMatcher(None, a.compacto, b.compacto).ratio()
        return ra, None, f"prefixos genéricos diferentes ({a.prefixo} e {b.prefixo})"
    curto = min(len(a.compacto), len(b.compacto)) <= MAX_CURTO
    if curto:
        if a.chave == b.chave:
            return 1.0, "grafia equivalente (caixa, acento e pontuação desconsiderados)", None
        ra = SequenceMatcher(None, a.compacto, b.compacto).ratio()
        return ra, None, "nome muito curto (3 caracteres ou menos) só se funde por grafia idêntica"
    if a.chave == b.chave:
        return 1.0, "grafia equivalente (caixa, acento e pontuação desconsiderados)", None
    if a.compacto == b.compacto:
        return 1.0, "mesmo nome sem prefixo genérico, artigos ou espaços", None
    texto_a, texto_b = " ".join(a.conteudo), " ".join(b.conteudo)
    razao = SequenceMatcher(None, texto_a, texto_b).ratio()
    if len(a.conteudo) != len(b.conteudo):
        return razao, None, "número de palavras diferente"
    if razao < LIMIAR_SEMELHANCA:
        return razao, None, f"semelhança abaixo de {LIMIAR_SEMELHANCA:.2f}".replace(".", ",")
    for x, y in zip(a.conteudo, b.conteudo):
        if not _palavras_parecidas(x, y):
            return razao, None, f"palavras diferentes («{x}» e «{y}»)"
    return razao, f"semelhança lexical {razao:.2f}".replace(".", ",") + f": «{a.bruto}» ~ «{b.bruto}»", None


# ---------- resolucao ----------
class _Conjuntos:
    """Uniao-busca. Cada conjunto sabe de qual cadastro e (dois cadastros diferentes nunca se unem)."""

    def __init__(self, n):
        self.pai = list(range(n))
        self.cadastro = [None] * n

    def raiz(self, i):
        while self.pai[i] != i:
            self.pai[i] = self.pai[self.pai[i]]
            i = self.pai[i]
        return i

    def unir(self, i, j):
        a, b = self.raiz(i), self.raiz(j)
        if a == b:
            return True
        if self.cadastro[a] is not None and self.cadastro[b] is not None and self.cadastro[a] != self.cadastro[b]:
            return False
        self.pai[b] = a
        self.cadastro[a] = self.cadastro[a] if self.cadastro[a] is not None else self.cadastro[b]
        return True


def _bem_formatada(s):
    """Tem maiuscula sem ser tudo em maiusculas, ou e sigla curta (ate 6 letras) toda em maiusculas. Tudo em minusculas nao e."""
    s = s.strip()
    letras = [c for c in s if c.isalpha()]
    if not letras or s == s.lower():
        return False
    return len(letras) <= 6 if s == s.upper() else True


def _chave_canonica(bruto, freq):
    """Menor chave = melhor nome: mais achados; bem formatada; com acentos (grafia correta em portugues); mais curta; ordem dos caracteres."""
    acentuadas = sum(1 for c in bruto if c.isalpha() and not c.isascii())
    return (-freq, 0 if _bem_formatada(bruto) else 1, -acentuadas, len(bruto.strip()), bruto)


def resolver_entidades(contagens, conhecidas=(), diagnostico=False):
    """Agrupa os nomes brutos em entidades (ver o topo do modulo).

    `contagens`: {(nome_bruto, uf): n_achados} (ou um iteravel de pares ((nome, uf), n)). Nomes em branco sao ignorados; `uf` None vira "".
    `conhecidas`: iteravel de SolucaoConhecida. `diagnostico=True` tambem guarda em `Resolucao.recusados` os pares parecidos que NAO foram
    fundidos e o motivo (para auditar quase-acertos). Deterministica: nao depende da ordem de entrada."""
    itens = contagens.items() if hasattr(contagens, "items") else contagens
    soma = {}
    for (bruto, uf), n in itens:
        if bruto is None or not str(bruto).strip():
            continue
        soma[(str(bruto), str(uf or ""))] = soma.get((str(bruto), str(uf or "")), 0) + int(n)
    brutos = [_No(b, u, n) for (b, u), n in sorted(soma.items())]
    conhecidas = list(conhecidas)

    virtuais = []                                           # nos dos nomes e apelidos de cada cadastro
    for i, k in enumerate(conhecidas):
        ufs = frozenset({k.uf, *getattr(k, "outras_ufs", ())})
        vistos = set()
        for nome in (k.nome, *k.apelidos):
            if chave(nome) and chave(nome) not in vistos:
                vistos.add(chave(nome))
                virtuais.append(_No(nome, k.uf, virtual=True, ufs=ufs, conhecida=k, indice=i))
    nos = brutos + virtuais
    conj = _Conjuntos(len(nos))
    primeiro_virtual = {}
    for j, v in enumerate(virtuais, len(brutos)):
        conj.cadastro[j] = v.indice
        if v.indice in primeiro_virtual:
            conj.unir(primeiro_virtual[v.indice], j)
        else:
            primeiro_virtual[v.indice] = j

    ligacoes = []                                           # (camada, -razao, ordem, i, j, motivo)
    recusados = []
    ordem = lambda i, j: (nos[i].bruto, nos[j].bruto, nos[i].uf, nos[j].uf)  # noqa: E731
    for i, r in enumerate(brutos):
        for j in range(len(brutos), len(nos)):
            motivo = _camada1(r, nos[j])
            if motivo:
                ligacoes.append((1, -1.0, (nos[j].indice, r.bruto, r.uf), i, j, motivo))
    for i in range(len(nos)):
        for j in range(i + 1, len(nos)):
            a, b = nos[i], nos[j]
            if a.virtual and b.virtual:
                continue
            if a.aceita_uf(b):
                motivo = _camada2(a, b)
                if motivo:
                    ligacoes.append((2, -1.0, ordem(i, j), i, j, motivo))
                    continue
                razao, motivo, recusa = _camada3(a, b)
                if motivo:
                    ligacoes.append((3, -razao, ordem(i, j), i, j, motivo))
                elif diagnostico and razao >= LIMIAR_QUASE:
                    recusados.append((a.bruto, b.bruto, a.uf or b.uf, round(razao, 3), recusa))
            elif diagnostico:
                razao, motivo, _ = _camada3(a, b)
                if razao >= LIMIAR_QUASE or motivo:
                    ufa = a.uf if not a.virtual else "/".join(sorted(a.ufs))
                    ufb = b.uf if not b.virtual else "/".join(sorted(b.ufs))
                    recusados.append((a.bruto, b.bruto, f"{ufa} x {ufb}", round(razao, 3), "UFs diferentes (só o cadastro, com outras_ufs, liga UFs)"))
    ligacoes.sort(key=lambda x: (x[0], x[1], x[2]))
    aceitas = []
    for camada, nr, ord_, i, j, motivo in ligacoes:
        if conj.unir(i, j):
            aceitas.append((camada, i, j, motivo))
        elif diagnostico:
            recusados.append((nos[i].bruto, nos[j].bruto, nos[i].uf or nos[j].uf, round(-nr, 3), "ligaria dois cadastros diferentes"))

    grupos = {}
    for i in range(len(nos)):
        grupos.setdefault(conj.raiz(i), []).append(i)
    entidades, por_no = [], {}
    for membros in grupos.values():
        raizes = [i for i in membros if i < len(brutos)]
        if not raizes:
            continue
        entidade = _montar(membros, nos, len(brutos), aceitas, conhecidas)
        entidades.append(entidade)
        for v in entidade.variantes:
            por_no[(v.bruto, v.uf)] = entidade
    entidades.sort(key=lambda e: (-e.n, e.canonico.casefold(), e.canonico, e.ufs))
    return Resolucao(tuple(entidades), tuple(sorted(set(recusados), key=lambda x: (-x[3], x[0], x[1], x[2]))), por_no)


def _montar(membros, nos, n_brutos, aceitas, conhecidas):
    conjunto = set(membros)
    brutos = [i for i in membros if i < n_brutos]
    virtuais = [i for i in membros if i >= n_brutos]
    cadastro = conhecidas[nos[virtuais[0]].indice] if virtuais else None
    if cadastro is not None:
        canonico, partida = cadastro.nome, list(virtuais)
    else:
        freq = {}
        for i in brutos:
            freq[nos[i].bruto] = freq.get(nos[i].bruto, 0) + nos[i].n
        canonico = min(freq, key=lambda b: _chave_canonica(b, freq[b]))
        partida = [min((i for i in brutos if nos[i].bruto == canonico), key=lambda i: nos[i].uf)]
    # camada mais fraca do caminho do canonico ate cada no: busca em largura permitindo camadas 1, depois 2, depois 3
    vizinhos = {}
    for camada, i, j, motivo in aceitas:
        if i in conjunto and j in conjunto:
            vizinhos.setdefault(i, []).append((j, camada, motivo))
            vizinhos.setdefault(j, []).append((i, camada, motivo))
    for lista in vizinhos.values():
        lista.sort(key=lambda x: (x[1], nos[x[0]].bruto, nos[x[0]].uf))
    alcancado = {i: (0, "") for i in partida}
    for teto in (1, 2, 3):
        fila = list(alcancado)
        while fila:
            atual = fila.pop(0)
            for viz, camada, motivo in vizinhos.get(atual, ()):
                if camada <= teto and viz not in alcancado:
                    base = alcancado[atual][0]
                    via = "" if atual in partida else f" (via «{nos[atual].bruto}»)"
                    alcancado[viz] = (max(base, camada), motivo + via)
                    fila.append(viz)
    variantes = []
    for i in brutos:
        camada, motivo = alcancado.get(i, (3, ""))
        if nos[i].bruto == canonico:
            camada, motivo = 0, ""
        variantes.append(Variante(nos[i].bruto, nos[i].uf, nos[i].n, camada, motivo))
    variantes.sort(key=lambda v: (-v.n, v.bruto, v.uf))
    return Entidade(canonico, tuple(sorted({v.uf for v in variantes})), sum(v.n for v in variantes), tuple(variantes), cadastro)
