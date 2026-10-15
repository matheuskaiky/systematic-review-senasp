"""Funcoes puras do painel (sem E/S): localizar a evidencia no texto original e achar o trecho mais parecido."""
import difflib
import re
import unicodedata

from dominio.servicos import normalizar_texto


def _normalizar_com_mapa(texto):
    """Mesma normalizacao de `normalizar_texto` (NFKD, ASCII, minusculas, espacos colapsados), devolvendo tambem,
    para cada caractere do resultado, o indice do caractere de `texto` de onde ele veio."""
    saida, mapa = [], []
    for i, c in enumerate(texto or ""):
        pedaco = unicodedata.normalize("NFKD", c).encode("ascii", "ignore").decode().lower()
        for ch in pedaco:
            if ch.isspace():
                if not saida or saida[-1] == " ":
                    continue
                saida.append(" ")
            else:
                saida.append(ch)
            mapa.append(i)
    if saida and saida[-1] == " ":
        saida.pop()
        mapa.pop()
    return "".join(saida), mapa


def localizar_evidencia(evidencia, texto):
    """(inicio, fim) da evidencia dentro do texto ORIGINAL (fim exclusivo), ou None se nao constar.
    Concorda sempre com `evidencia_confere`: so devolve None quando ela daria False."""
    e = normalizar_texto(evidencia)
    if not e:
        return None
    norm, mapa = _normalizar_com_mapa(texto)
    k = norm.find(e)
    if k < 0:
        return None
    return mapa[k], mapa[k + len(e) - 1] + 1


def trecho_mais_parecido(evidencia, texto, minimo=0.35):
    """Quando a evidencia nao consta no texto: (inicio, fim, similaridade 0-1) do trecho mais parecido, por
    sentencas/paragrafos, ou None. E uma aproximacao para ajudar o humano, nunca uma prova."""
    e = normalizar_texto(evidencia)
    if not e or not texto:
        return None
    melhor = None
    for m in re.finditer(r"[^\n]+", texto):
        inicio = m.start()
        for parte in re.finditer(r".+?(?:[.!?](?=\s)|$)", m.group(), flags=re.S):
            trecho = parte.group()
            n = normalizar_texto(trecho)
            if len(n) < 8:
                continue
            sm = difflib.SequenceMatcher(None, e, n, autojunk=False)
            if sm.real_quick_ratio() < minimo or sm.quick_ratio() < minimo:
                continue
            r = sm.ratio()
            if melhor is None or r > melhor[2]:
                melhor = (inicio + parte.start(), inicio + parte.end(), r)
    return melhor if melhor and melhor[2] >= minimo else None
