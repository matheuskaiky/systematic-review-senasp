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


def trecho_mais_parecido(evidencia, texto, minimo=0.35, candidatos=12):
    """Quando a evidencia nao consta no texto: (inicio, fim, similaridade 0-1) do trecho mais parecido, por
    sentencas/paragrafos, ou None. E uma aproximacao para ajudar o humano, nunca uma prova.

    Para nao rodar o difflib em milhares de sentencas (60 mil caracteres levavam ~0,7 s), um pre-filtro barato escolhe as
    `candidatos` sentencas com mais palavras em comum com a evidencia, e so nelas se calcula a similaridade."""
    e = normalizar_texto(evidencia)
    if not e or not texto:
        return None
    palavras_e = set(e.split())
    pecas = []
    for m in re.finditer(r"[^\n]+", texto):
        inicio = m.start()
        for parte in re.finditer(r".+?(?:[.!?](?=\s)|$)", m.group(), flags=re.S):
            n = normalizar_texto(parte.group())
            if len(n) < 8:
                continue
            comuns = len(palavras_e & set(n.split()))
            if comuns:
                pecas.append((comuns / len(palavras_e), inicio + parte.start(), inicio + parte.end(), n))
    pecas.sort(key=lambda x: -x[0])
    melhor = None
    for _, ini, fim, n in pecas[:candidatos]:
        sm = difflib.SequenceMatcher(None, e, n, autojunk=False)
        if sm.real_quick_ratio() < minimo or sm.quick_ratio() < minimo:
            continue
        r = sm.ratio()
        if melhor is None or r > melhor[2]:
            melhor = (ini, fim, r)
    return melhor if melhor and melhor[2] >= minimo else None


# ---------- configuracao e respostas brutas: leitura sem expor segredos ----------
_CHAVES_SECRETAS = {"api_key", "apikey", "authorization", "x-goog-api-key", "key", "token", "password", "senha", "secret", "access_token"}


def _eh_secreta(chave):
    k = str(chave).lower()
    return k in _CHAVES_SECRETAS or k.endswith(("_key", "_token", "_secret", "_password"))


def mascarar_segredos(valor):
    """Copia do valor (dict/lista aninhados) com `***` no lugar do que esta sob chaves de segredo (api_key, authorization...)."""
    if isinstance(valor, dict):
        return {k: ("***" if _eh_secreta(k) and v not in (None, "") else mascarar_segredos(v)) for k, v in valor.items()}
    if isinstance(valor, list):
        return [mascarar_segredos(v) for v in valor]
    return valor


def _rotulo_item(item, i):
    return f"{item['id']}" if isinstance(item, dict) and "id" in item else str(i)


def _achatar(valor, caminho, saida):
    if isinstance(valor, dict):
        for k, v in valor.items():
            _achatar(v, f"{caminho}.{k}" if caminho else str(k), saida)
        if not valor and caminho:
            saida[caminho] = {}
    elif isinstance(valor, list):
        for i, v in enumerate(valor):
            _achatar(v, f"{caminho}[{_rotulo_item(v, i)}]", saida)
        if not valor and caminho:
            saida[caminho] = []
    else:
        saida[caminho] = valor


def diff_config(a, b):
    """Diferencas entre duas configuracoes (dicts vindos de config_json): lista de (caminho, valor_a, valor_b, tipo) com
    tipo em {'alterado', 'so_em_a', 'so_em_b'}. Listas de itens com `id` sao pareadas pelo id; as demais, pela posicao."""
    fa, fb = {}, {}
    _achatar(a or {}, "", fa)
    _achatar(b or {}, "", fb)
    saida = []
    for caminho in sorted(set(fa) | set(fb)):
        if caminho in fa and caminho in fb:
            if fa[caminho] != fb[caminho]:
                saida.append((caminho, fa[caminho], fb[caminho], "alterado"))
        elif caminho in fa:
            saida.append((caminho, fa[caminho], None, "so_em_a"))
        else:
            saida.append((caminho, None, fb[caminho], "so_em_b"))
    return saida
