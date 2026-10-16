"""Refinamento da busca a partir da triagem de escopo feita por LLM. Funcoes puras (sem I/O): dicionarios e listas entram e saem.

Entrada comum, `linhas`: o veredito ATUAL de cada item (uma linha por item, como a tabela `triagem_escopo`), com as chaves
`item_id`, `uf`, `status` (elegivel | quarentena | excluido), `valido` (1 ou 0), `termos_consulta` (lista JSON dos textos das
consultas que acharam o item), `categoria_motivo`, `termo_gerador`, `sinal_negativo`, `dominio_tematico` e `escopo_geografico`.
Linhas com `valido = 0` falharam em alguma conferencia: nunca entram nos percentuais nem nas validacoes, so sao contadas a parte.

Nada aqui decide pela pessoa: o veredito do modelo e uma opiniao, e o "dano colateral" de cada operador negativo sugerido e
medido contra os itens bons (elegiveis, em quarentena ou incluidos pela triagem humana) para que nenhuma consulta nova perca
um artigo que serviria.
"""
import json
import re
import unicodedata
from collections import Counter

STATUS = ("elegivel", "quarentena", "excluido")
NAO_ELEGIVEIS = ("quarentena", "excluido")
LIMITE_COLATERAIS = 5               # quantos itens de dano colateral se listam por operador
FRACAO_ARRISCADO = 0.05             # ate 5% dos itens que contem o operador: arriscado; acima disso: perigoso
LIMITE_EXEMPLOS = 5                 # exemplos no payload da sintese por termo
TAMANHO_EXEMPLO = 100               # caracteres de cada texto de exemplo no payload
PALAVRAS_VAZIAS = frozenset({"a", "as", "o", "os", "e", "de", "da", "das", "do", "dos", "em", "na", "no", "para", "por",
                             "com", "um", "uma"})
VEREDITOS = ("seguro", "arriscado", "perigoso")

_RX_NAO_ALFANUM = re.compile(r"[^a-z0-9]+")


def normalizar_texto(texto):
    """Minusculas, sem acentos, e tudo que nao for letra ou numero vira um espaco (sem espacos nas pontas)."""
    if texto is None:
        return ""
    sem_acento = "".join(c for c in unicodedata.normalize("NFKD", str(texto).lower()) if not unicodedata.combining(c))
    return _RX_NAO_ALFANUM.sub(" ", sem_acento).strip()


def contem_frase(texto_normalizado, frase_normalizada):
    """A frase aparece no texto como palavra inteira ou sequencia de palavras inteiras (ambos ja normalizados)."""
    return bool(frase_normalizada) and f" {frase_normalizada} " in f" {texto_normalizado} "


def termos_da_linha(linha):
    """Textos das consultas que acharam o item, sem repeticao e sem vazios. Aceita lista JSON, texto JSON ou texto puro."""
    bruto = linha.get("termos_consulta")
    if isinstance(bruto, (list, tuple)):
        valores = list(bruto)
    elif bruto in (None, ""):
        return []
    else:
        try:
            lido = json.loads(bruto)
        except (TypeError, ValueError):
            lido = str(bruto)
        valores = lido if isinstance(lido, list) else [lido]
    return list(dict.fromkeys(t for t in (str(v).strip() for v in valores if v is not None) if t))


def _valida(linha):
    v = linha.get("valido")
    return v is None or int(v) == 1


def _chave_item(linha):
    return (linha.get("item_id"), linha.get("uf") or "")


def _pct(parte, total):
    return round(100 * parte / total, 1) if total else None


def _mais_frequente(contador):
    """(valor, quantidade) do mais frequente; empate pelo texto, para o resultado nao depender da ordem das linhas."""
    if not contador:
        return None, 0
    valor = sorted(contador.items(), key=lambda kv: (-kv[1], str(kv[0])))[0]
    return valor[0], valor[1]


def _ordenado(contador):
    return dict(sorted(contador.items(), key=lambda kv: (-kv[1], str(kv[0]))))


def ficha_por_termo(linhas):
    """Ficha de ruido de cada termo de consulta. Um item conta uma vez para cada termo que o achou.

    Devolve uma lista de dicionarios ordenada pela taxa de ruido (do mais ao menos ruidoso; empate: mais itens, depois o texto):
    `termo`, `n_itens` (linhas validas), `n_invalidos`, `n_elegivel`, `n_quarentena`, `n_excluido`, `pct_*` (0 a 100, uma casa),
    `pct_ruido` (excluido + quarentena sobre o total), `categoria_top` (motivo mais frequente entre os nao elegiveis),
    `categorias` e `dominios` (contagens entre os nao elegiveis), `dominio_top`, `n_internacional`, `pct_internacional` (entre todos
    os itens validos do termo) e `termo_gerador_top`."""
    termos = {}
    for l in linhas:
        for t in termos_da_linha(l):
            a = termos.setdefault(t, {"status": Counter(), "invalidos": 0, "categorias": Counter(), "dominios": Counter(),
                                      "internacional": 0, "geradores": Counter()})
            if not _valida(l):
                a["invalidos"] += 1
                continue
            if l.get("status") not in STATUS:
                continue
            a["status"][l["status"]] += 1
            if l.get("escopo_geografico") == "internacional":
                a["internacional"] += 1
            if l.get("termo_gerador"):
                a["geradores"][l["termo_gerador"]] += 1
            if l["status"] in NAO_ELEGIVEIS:
                if l.get("categoria_motivo"):
                    a["categorias"][l["categoria_motivo"]] += 1
                if l.get("dominio_tematico"):
                    a["dominios"][l["dominio_tematico"]] += 1
    fichas = []
    for t, a in termos.items():
        n = sum(a["status"].values())
        e, q, x = (a["status"][s] for s in STATUS)
        cat, _ = _mais_frequente(a["categorias"])
        dom, _ = _mais_frequente(a["dominios"])
        ger, ger_n = _mais_frequente(a["geradores"])
        fichas.append({"termo": t, "n_itens": n, "n_invalidos": a["invalidos"], "n_elegivel": e, "n_quarentena": q, "n_excluido": x,
                       "pct_elegivel": _pct(e, n), "pct_quarentena": _pct(q, n), "pct_excluido": _pct(x, n),
                       "pct_ruido": _pct(q + x, n), "categoria_top": cat, "categorias": _ordenado(a["categorias"]),
                       "dominio_top": dom, "dominios": _ordenado(a["dominios"]), "n_internacional": a["internacional"],
                       "pct_internacional": _pct(a["internacional"], n), "termo_gerador_top": ger, "termo_gerador_top_n": ger_n})
    fichas.sort(key=lambda f: (-(f["pct_ruido"] if f["pct_ruido"] is not None else -1), -f["n_itens"], f["termo"]))
    return fichas


def matriz_ruido(linhas):
    """Contagem de (termo_gerador, categoria_motivo, dominio_tematico) nas linhas validas nao elegiveis, da maior para a menor."""
    c = Counter((l.get("termo_gerador"), l.get("categoria_motivo"), l.get("dominio_tematico"))
                for l in linhas if _valida(l) and l.get("status") in NAO_ELEGIVEIS)
    ordem = sorted(c.items(), key=lambda kv: (-kv[1], tuple(str(x) for x in kv[0])))
    return [{"termo_gerador": g, "categoria_motivo": m, "dominio_tematico": d, "n": n} for (g, m, d), n in ordem]


def _palavras_protegidas(protegidos):
    """Palavras (normalizadas, sem artigos e preposicoes) de cada expressao protegida: 'reconhecimento facial' protege as duas."""
    palavras = set()
    for p in protegidos or ():
        palavras.update(w for w in normalizar_texto(p).split() if w not in PALAVRAS_VAZIAS)
    return palavras


def _veredito(n_colateral, n_corpus, protegida):
    if protegida:
        return "perigoso"
    if n_colateral == 0:
        return "seguro"
    return "arriscado" if n_colateral <= FRACAO_ARRISCADO * n_corpus else "perigoso"


def avaliar_negativos(linhas, corpus, protegidos=()):
    """Valida cada `sinal_negativo` sugerido em itens `excluido` contra os itens bons do corpus.

    `corpus`: todos os itens da mesma fonte, `{"id", "uf", "titulo", "resumo", "incluido_humano"}` (`id` e `uf` casam com
    `item_id` e `uf` das linhas; `incluido_humano` = a triagem humana incluiu o item). O texto e titulo + resumo, comparado
    sem acento nem maiuscula, por palavra inteira (ou frase inteira).

    Dano colateral de um operador = itens do corpus que contem o texto e sao `elegivel`, `quarentena` ou incluidos pelos humanos.
    Veredito: `seguro` (nenhum), `arriscado` (de 1 item ate 5% dos que contem o texto), `perigoso` (mais que isso). Frase com
    alguma palavra de `protegidos` (as palavras centrais do tema) e sempre `perigoso`.

    Devolve `{"negativos": [...], "por_termo": {termo: [...]}}`. Cada negativo traz `sinal`, `chave`, `n_sugerido_por` (itens
    `excluido` que o sugeriram), `n_no_corpus`, `n_excluidos_atingidos` (itens `excluido` que ele tiraria), `n_colateral`
    (`n_colateral_elegivel`, `n_colateral_quarentena`, `n_colateral_humano`), `ids_colaterais` e `colaterais` (ate 5),
    `pct_colateral`, `protegida` e `veredito`. Em `por_termo`, para cada termo, os operadores nao perigosos que tirariam
    algum item `excluido` ou `quarentena` dele: `ganho` (`ganho_excluido` + `ganho_quarentena`) contra `perda_elegivel`
    (itens `elegivel` ou incluidos pelos humanos do termo que ele tambem tiraria); `seguro_no_termo` = perda zero."""
    validas = [l for l in linhas if _valida(l) and l.get("status") in STATUS]
    por_item = {_chave_item(l): l for l in validas}
    sugeridos = {}
    for l in validas:
        chave = normalizar_texto(l.get("sinal_negativo"))
        if l["status"] == "excluido" and chave:
            s = sugeridos.setdefault(chave, {"n": 0, "formas": Counter()})
            s["n"] += 1
            s["formas"][str(l["sinal_negativo"]).strip()] += 1
    textos = []
    for i in corpus:
        texto = normalizar_texto(f"{i.get('titulo') or ''} {i.get('resumo') or i.get('snippet') or ''}")
        textos.append((i, texto, por_item.get((i.get("id"), i.get("uf") or ""))))
    protegidas = _palavras_protegidas(protegidos)
    termos_por_item = {k: termos_da_linha(l) for k, l in por_item.items()}

    negativos, por_termo = [], {}
    for chave, s in sugeridos.items():
        atingidos = [(i, v) for i, texto, v in textos if contem_frase(texto, chave)]
        colaterais = [(i, v) for i, v in atingidos
                      if (v is not None and v["status"] in ("elegivel", "quarentena")) or i.get("incluido_humano")]
        n_corpus, n_col = len(atingidos), len(colaterais)
        protegida = any(w in protegidas for w in chave.split())
        negativos.append({
            "sinal": _mais_frequente(s["formas"])[0], "chave": chave, "n_sugerido_por": s["n"], "n_no_corpus": n_corpus,
            "n_excluidos_atingidos": sum(1 for _, v in atingidos if v is not None and v["status"] == "excluido"),
            "n_colateral": n_col,
            "n_colateral_elegivel": sum(1 for _, v in colaterais if v is not None and v["status"] == "elegivel"),
            "n_colateral_quarentena": sum(1 for _, v in colaterais if v is not None and v["status"] == "quarentena"),
            "n_colateral_humano": sum(1 for i, _ in colaterais if i.get("incluido_humano")),
            "ids_colaterais": [i.get("id") for i, _ in colaterais[:LIMITE_COLATERAIS]],
            "colaterais": [{"id": i.get("id"), "uf": i.get("uf") or "", "titulo": i.get("titulo"),
                            "status": v["status"] if v is not None else None, "incluido_humano": bool(i.get("incluido_humano"))}
                           for i, v in colaterais[:LIMITE_COLATERAIS]],
            "pct_colateral": _pct(n_col, n_corpus) if n_corpus else 0.0, "protegida": protegida,
            "veredito": _veredito(n_col, n_corpus, protegida)})
        if negativos[-1]["veredito"] == "perigoso":
            continue                                   # (inclui as frases protegidas) nunca se sugere adicionar
        # por termo: so entram itens que ja tem veredito, e portanto termos de consulta conhecidos
        ganhos = {}
        for i, _ in atingidos:
            k = (i.get("id"), i.get("uf") or "")
            v = por_item.get(k)
            if v is None:
                continue
            for t in termos_por_item[k]:
                g = ganhos.setdefault(t, {"excluido": 0, "quarentena": 0, "perda": 0})
                if v["status"] == "excluido":
                    g["excluido"] += 1
                elif v["status"] == "quarentena":
                    g["quarentena"] += 1
                if v["status"] == "elegivel" or i.get("incluido_humano"):
                    g["perda"] += 1
        for t, g in ganhos.items():
            if g["excluido"] + g["quarentena"]:
                por_termo.setdefault(t, []).append({
                    "sinal": negativos[-1]["sinal"], "chave": chave, "veredito": negativos[-1]["veredito"],
                    "ganho": g["excluido"] + g["quarentena"], "ganho_excluido": g["excluido"],
                    "ganho_quarentena": g["quarentena"], "perda_elegivel": g["perda"], "seguro_no_termo": g["perda"] == 0})
    negativos.sort(key=lambda n: (VEREDITOS.index(n["veredito"]), -n["n_excluidos_atingidos"], n["chave"]))
    for t in por_termo:
        por_termo[t].sort(key=lambda n: (n["perda_elegivel"] > 0, -n["ganho"], n["perda_elegivel"], n["chave"]))
    return {"negativos": negativos, "por_termo": por_termo}


def _curto(texto, limite=TAMANHO_EXEMPLO):
    texto = " ".join(str(texto or "").split())
    return texto if len(texto) <= limite else texto[:limite - 1].rstrip() + "…"


def payload_sintese_termo(termo, ficha, negativos, exemplos):
    """Payload compacto, so com numeros agregados, que uma chamada posterior ao modelo recebera para propor consultas refinadas.

    `ficha`: a ficha do termo (de `ficha_por_termo`; pode ser None); `negativos`: a lista do termo em `por_termo` (so entram
    os `seguro_no_termo`, ate 5); `exemplos`: itens `{"titulo", "status", "categoria_motivo", "justificativa"}` (ate 5, textos
    curtos). Nao chama o modelo."""
    f = ficha or {}
    seguros = [{"sinal": n["sinal"], "ganho": n["ganho"], "perda_elegivel": n["perda_elegivel"]}
               for n in negativos or () if n.get("seguro_no_termo") and n.get("veredito") != "perigoso"]
    return {
        "termo": termo,
        "n_itens": f.get("n_itens", 0),
        "contagens": {"elegivel": f.get("n_elegivel", 0), "quarentena": f.get("n_quarentena", 0), "excluido": f.get("n_excluido", 0)},
        "pct_ruido": f.get("pct_ruido"),
        "pct_internacional": f.get("pct_internacional"),
        "categorias": dict(list((f.get("categorias") or {}).items())[:3]),
        "dominios": dict(list((f.get("dominios") or {}).items())[:3]),
        "termo_gerador_top": f.get("termo_gerador_top"),
        "negativos_seguros": seguros[:LIMITE_EXEMPLOS],
        "exemplos": [{"titulo": _curto(e.get("titulo")), "status": e.get("status"), "categoria_motivo": e.get("categoria_motivo"),
                      "justificativa": _curto(e.get("justificativa"))} for e in list(exemplos or ())[:LIMITE_EXEMPLOS]],
    }
