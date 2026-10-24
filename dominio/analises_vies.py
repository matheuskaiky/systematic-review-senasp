"""Analises da busca de vies algoritmico (banco `vies`, D111 e D116): a composicao do corpus (fonte, relevancia, tipo de
fonte, eixo, topicos, ano, pais/escopo, dominio) e o rendimento das consultas, dos conjuntos e das ferramentas. Sem I/O:
recebe as linhas que o painel ja le (referencias da web, artigos das consultas e a triagem mais recente de cada item).

Duas bases de contagem, sempre ditas na tela:
- por fonte (relevancia, grupos de literatura, consultas, ferramentas, dominios): cada item da sua fonte, mesmo que a
  mesma obra apareca nas duas;
- de conteudo (tipos, eixos, topicos, paises): cada obra uma vez (`obras`), so as que a triagem deixou no escopo;
- de origem (conjuntos): cada obra uma vez, todas (inclusive as fora do escopo), na uniao dos conjuntos dos seus itens."""
import copy
import re
import unicodedata
from collections import Counter
from itertools import combinations

from dominio.casos_estaduais import ano_da_data
from dominio.servicos import normalizar_url

FONTE_WEB, FONTE_SCHOLAR = "Web", "Scholar"
FONTE_DA_ETAPA = {"busca_literatura": FONTE_WEB, "busca_academica": FONTE_SCHOLAR}   # a etapa que gravou as chamadas
SEM_CONJUNTO = "Sem conjunto"      # a obra sem nenhum dos conjuntos configurados
SEM_ANGULO = "sem_angulo"          # coluna do recorte ausente (sem triagem valida, triagem v1) ou fora da lista configurada
RELEVANCIAS = ("alta", "media", "baixa", "fora_do_escopo")
ELEGIVEIS = ("alta", "media")                      # alta e media dao "elegivel" na triagem (D116)
SEM_TRIAGEM = "sem triagem válida"
GRUPO_CIENTIFICA, GRUPO_CINZENTA, GRUPO_PRIMARIA = "Literatura científica", "Literatura cinzenta", "Fonte primária"
GRUPOS = (GRUPO_CIENTIFICA, GRUPO_CINZENTA, GRUPO_PRIMARIA)
SUFIXO_CINZENTA, SUFIXO_PRIMARIA = " / literatura cinzenta", " / fonte primária"
SEM_EIXO = "Sem eixo"
SEM_ANO = "Sem ano"
PAISES_SEM_LUGAR = ("indeterminado",)              # pais/escopo que nao diz lugar: fica fora do denominador do Brasil
# variantes de um mesmo topico (plural e singular), juntadas pela chave; so o que se viu nos dados, sem radicalizar palavras
VARIANTES_TOPICOS = {"vieses algorítmicos": "viés algorítmico", "vieses raciais": "viés racial"}
# segundos niveis de dominio de pais (".com.br", ".gov.br", ".co.uk", ".ac.uk"...): o dominio registravel tem tres partes.
# Heuristica sem a lista publica de sufixos (nenhuma biblioteca nova): sufixo fora desta lista conta como dominio comum.
SEGUNDOS_NIVEIS = ("com", "org", "gov", "edu", "jus", "leg", "net", "mil", "art", "blog", "ind", "inf", "mus", "nom", "rec",
                   "co", "ac", "or", "ne", "go", "gob", "gouv")


def _lista(texto):
    return sorted({p.strip() for p in (texto or "").split(",") if p.strip()})


def grupo_do_tipo(tipo_fonte):
    """O grupo da literatura pelo sufixo que o codigo pos no tipo de fonte (D110); None sem tipo."""
    if not tipo_fonte:
        return None
    if tipo_fonte.endswith(SUFIXO_PRIMARIA):
        return GRUPO_PRIMARIA
    if tipo_fonte.endswith(SUFIXO_CINZENTA):
        return GRUPO_CINZENTA
    return GRUPO_CIENTIFICA


def _da_triagem(t):
    """Os campos da triagem mais recente do item, so quando ela passou nas conferencias (`valido`)."""
    if not t or not t.get("valido"):
        return {"relevancia": None, "tipo_fonte": None, "pais": None, "topicos": [], "eixo": None, "confianca": None,
                "recorte": None}
    return {"relevancia": t.get("status_bruto"), "tipo_fonte": t.get("tipo_fonte"), "pais": t.get("pais_escopo"),
            "recorte": t.get("recorte"),          # angulo predominante da triagem v2, como gravado (None na v1)
            "topicos": [x.strip() for x in (t.get("topicos") or "").split(";") if x.strip()], "eixo": t.get("eixo"),
            "confianca": t.get("confianca")}


def itens(linhas_web, linhas_artigos, conjunto_da_consulta, triagens):
    """Um dicionario por item do corpus: as referencias da web e os artigos achados pelas consultas dos conjuntos, com a
    triagem valida mais recente. So contam as consultas configuradas (`conjunto_da_consulta`). `triagens`:
    {(fonte, item_id): linha}, fonte "referencia" ou "artigo". O ano do artigo e o do Scholar (publicacao); o da referencia
    da web e o da data do resultado, que e a data da pagina, nao a da publicacao."""
    saida = []
    for l in linhas_web:
        consultas = [c for c in _lista(l["consultas"]) if c in conjunto_da_consulta]
        saida.append({"id": f"W-{l['referencia_id']}", "fonte": FONTE_WEB, "ano": ano_da_data(l["data_pub"]),
                      "consultas": consultas, "conjuntos": sorted({conjunto_da_consulta[c] for c in consultas}),
                      "dominio": l["dominio"] or "", "url": l["url_original"] or "", "titulo": l["titulo"] or "",
                      **_da_triagem(triagens.get(("referencia", l["referencia_id"])))})
    for l in linhas_artigos:
        consultas = [c for c in _lista(l["consultas"]) if c in conjunto_da_consulta]
        ano = l["ano"] if isinstance(l["ano"], int) and not isinstance(l["ano"], bool) else None
        saida.append({"id": f"A-{l['artigo_id']}", "fonte": FONTE_SCHOLAR, "ano": ano, "consultas": consultas,
                      "conjuntos": sorted({conjunto_da_consulta[c] for c in consultas}), "dominio": "",
                      "url": l["link"] or "", "titulo": l["titulo"] or "",
                      **_da_triagem(triagens.get(("artigo", l["artigo_id"])))})
    return saida


def _chave_texto(texto):
    """Chave de contagem de um rotulo livre: NFC, espacos juntados e sem diferenca de maiuscula."""
    return " ".join(unicodedata.normalize("NFC", texto).split()).casefold()


def _maiuscula_inicial(texto):
    """'viés algorítmico' -> 'Viés algorítmico' (o resto fica como esta: siglas como IA e LGPD nao mudam)."""
    return texto[:1].upper() + texto[1:]


def chave_titulo(titulo):
    """A chave de mesma obra pelo titulo: as palavras de letras e numeros, sem acento e sem diferenca de maiuscula, de
    qualquer alfabeto. Para texto latino e a regra de `servicos.chave_dedup_titulo` (D104); outros alfabetos mantem as
    letras (aquela regra as apaga, e titulos diferentes so em outro alfabeto viravam a mesma chave). None quando o titulo
    nao tem nenhuma letra nem numero (nao identifica a obra)."""
    if not isinstance(titulo, str):
        return None
    sem_acento = "".join(c for c in unicodedata.normalize("NFKD", titulo) if not unicodedata.combining(c))
    palavras = re.findall(r"[^\W_]+", sem_acento.casefold())
    return " ".join(palavras) or None


def _repetidos_por_criterio(lista):
    """(ids repetidos pela URL normalizada, ids repetidos so pelo titulo normalizado) das referencias da web que sao a
    mesma obra de um artigo do Scholar (D104)."""
    urls = {normalizar_url(i["url"]) for i in lista if i["fonte"] == FONTE_SCHOLAR and i["url"]}
    titulos = {chave_titulo(i["titulo"]) for i in lista if i["fonte"] == FONTE_SCHOLAR} - {None}
    web = [i for i in lista if i["fonte"] == FONTE_WEB]
    por_url = {i["id"] for i in web if i["url"] and normalizar_url(i["url"]) in urls}
    por_titulo = {i["id"] for i in web if i["id"] not in por_url and chave_titulo(i["titulo"]) in titulos}
    return por_url, por_titulo


def repetidos_na_web(lista):
    """Os ids das referencias da web que sao a mesma obra de um artigo do Scholar: URL normalizada igual ou titulo
    normalizado igual (D104)."""
    por_url, por_titulo = _repetidos_por_criterio(lista)
    return por_url | por_titulo


def obras(lista):
    """Cada obra uma vez: a referencia da web repetida de um artigo do Scholar sai (fica o artigo)."""
    repetidos = repetidos_na_web(lista)
    return [i for i in lista if i["id"] not in repetidos]


def resumo(lista):
    """Os numeros do panorama: itens por fonte, obras distintas, com triagem valida, relevancia alta e fora do escopo."""
    por_fonte = Counter(i["fonte"] for i in lista)
    triados = [i for i in lista if i["relevancia"]]
    por_url, por_titulo = _repetidos_por_criterio(lista)
    repetidos = por_url | por_titulo
    return {"n_itens": len(lista), "n_web": por_fonte[FONTE_WEB], "n_scholar": por_fonte[FONTE_SCHOLAR],
            "n_obras": len(lista) - len(repetidos), "n_em_ambas_fontes": len(repetidos),
            "n_ambas_por_url": len(por_url), "n_ambas_so_por_titulo": len(por_titulo), "n_triados": len(triados),
            "n_alta": sum(1 for i in triados if i["relevancia"] == "alta"),
            "n_fora": sum(1 for i in triados if i["relevancia"] == "fora_do_escopo")}


def relevancia_por_fonte(lista):
    """{fonte: {relevancia | SEM_TRIAGEM: n}} nas duas fontes, na ordem das relevancias."""
    saida = {}
    for fonte in (FONTE_WEB, FONTE_SCHOLAR):
        c = Counter(i["relevancia"] or SEM_TRIAGEM for i in lista if i["fonte"] == fonte)
        saida[fonte] = {r: c.get(r, 0) for r in RELEVANCIAS + (SEM_TRIAGEM,)}
    return saida


def no_escopo(lista):
    """Os itens que a triagem nao tirou do escopo (relevancia alta, media ou baixa)."""
    return [i for i in lista if i["relevancia"] in ("alta", "media", "baixa")]


def contagem(valores, ordem=()):
    """[(rotulo, n)] do mais frequente para o menos (empate pelo rotulo); os rotulos de `ordem` ausentes aparecem com 0."""
    c = Counter(valores)
    return sorted(((r, c.get(r, 0)) for r in set(c) | set(ordem)), key=lambda x: (-x[1], x[0]))


def tipos_por_grupo_e_fonte(lista):
    """{(grupo, fonte): n} dos itens no escopo (por fonte: cada item da sua fonte)."""
    return Counter((grupo_do_tipo(i["tipo_fonte"]), i["fonte"]) for i in no_escopo(lista) if i["tipo_fonte"])


def relevancia_por_grupo(lista):
    """{(grupo, relevancia): n} das obras com tipo de fonte (todas as relevancias, inclusive fora do escopo)."""
    return Counter((grupo_do_tipo(i["tipo_fonte"]), i["relevancia"]) for i in obras(lista) if i["tipo_fonte"] and i["relevancia"])


def tipos(lista):
    """[(tipo de fonte, n)] das obras no escopo."""
    return contagem([i["tipo_fonte"] for i in no_escopo(obras(lista)) if i["tipo_fonte"]])


def eixos(lista, todos=()):
    """[(eixo, n)] das obras no escopo; os eixos de `todos` sem nenhuma obra aparecem com 0; SEM_EIXO no fim, se houver."""
    escopo = no_escopo(obras(lista))
    linhas = contagem([i["eixo"] for i in escopo if i["eixo"]], ordem=todos)
    sem = sum(1 for i in escopo if not i["eixo"])
    return linhas + ([(SEM_EIXO, sem)] if sem else [])


def eixo_por_relevancia(lista):
    """{(eixo, relevancia): n} das obras no escopo."""
    return Counter((i["eixo"] or SEM_EIXO, i["relevancia"]) for i in no_escopo(obras(lista)))


def topicos(lista, textos_das_consultas=()):
    """Os topicos das obras no escopo, sem diferenca de maiuscula, acento composto ou espaco, com as variantes de
    VARIANTES_TOPICOS juntadas; cada topico conta uma vez por obra. Devolve todos numa lista so, [(rotulo, obras,
    termo_de_busca)], do mais citado para o menos (empate: pelo rotulo); `termo_de_busca` diz se o topico aparece, como
    palavra ou expressao inteira, no texto de alguma consulta (uma caracteristica do topico, que conta como os demais).
    Rotulo: a forma canonica da variante ou a forma escrita mais frequente (empate: a primeira em ordem alfabetica), com
    maiuscula inicial."""
    busca = [_chave_texto(t) for t in textos_das_consultas]
    canonicas = set(VARIANTES_TOPICOS.values())
    contagem_chave, formas = Counter(), {}
    for i in no_escopo(obras(lista)):
        vistos = set()
        for t in i["topicos"]:
            k = _chave_texto(t)
            k = VARIANTES_TOPICOS.get(k, k)
            if k in vistos:
                continue
            vistos.add(k)
            contagem_chave[k] += 1
            formas.setdefault(k, Counter())[" ".join(unicodedata.normalize("NFC", t).split())] += 1
    rotulo = {k: _maiuscula_inicial(k if k in canonicas else sorted(f.items(), key=lambda x: (-x[1], x[0]))[0][0])
              for k, f in formas.items()}
    ordenados = sorted(contagem_chave.items(), key=lambda x: (-x[1], rotulo[x[0]]))
    na_busca = {k for k in contagem_chave if any(re.search(rf"(?<!\w){re.escape(k)}(?!\w)", b) for b in busca)}
    return [(rotulo[k], v, k in na_busca) for k, v in ordenados]


def anos_scholar(lista):
    """[(ano, n)] dos artigos do Scholar no escopo com ano conhecido (o ano de publicacao), em ordem crescente."""
    return sorted(Counter(i["ano"] for i in no_escopo(lista) if i["fonte"] == FONTE_SCHOLAR and i["ano"] is not None).items())


def por_ano(lista):
    """{ano | SEM_ANO: {fonte: n}} dos itens no escopo (Scholar: ano de publicacao; web: ano da data da pagina), anos em
    ordem crescente e SEM_ANO no fim; anos sem nenhum item ficam de fora."""
    c = Counter((i["ano"] if i["ano"] is not None else SEM_ANO, i["fonte"]) for i in no_escopo(lista))
    anos = sorted({a for a, _ in c if a != SEM_ANO}) + [SEM_ANO]
    return {a: {f: c.get((a, f), 0) for f in (FONTE_WEB, FONTE_SCHOLAR)} for a in anos
            if any(c.get((a, f)) for f in (FONTE_WEB, FONTE_SCHOLAR))}


def paises(lista, n=12):
    """[(pais/escopo, n)] das obras no escopo, sem diferenca de maiuscula ou espaco (rotulo: a forma mais frequente)."""
    formas = {}
    for i in no_escopo(obras(lista)):
        if i["pais"]:
            formas.setdefault(_chave_texto(i["pais"]), Counter())[" ".join(i["pais"].split())] += 1
    linhas = [(sorted(f.items(), key=lambda x: (-x[1], x[0]))[0][0], sum(f.values())) for f in formas.values()]
    return sorted(linhas, key=lambda x: (-x[1], x[0]))[:n]


def categoria_pais(pais):
    """'brasil' quando qualquer parte do pais/escopo (separado por '/') e Brasil; 'indeterminado' sem pais ou com
    'Indeterminado'; 'outro' no resto."""
    if not pais or _chave_texto(pais) in PAISES_SEM_LUGAR:
        return "indeterminado"
    return "brasil" if "brasil" in [_chave_texto(p) for p in pais.split("/")] else "outro"


def brasil(lista):
    """(obras no escopo sobre o Brasil, obras no escopo com lugar definido): o Brasil conta quando qualquer parte do
    pais/escopo (separado por '/') e 'Brasil'; 'Indeterminado' fica fora do denominador."""
    categorias = [categoria_pais(i["pais"]) for i in no_escopo(obras(lista))]
    return categorias.count("brasil"), len(categorias) - categorias.count("indeterminado")


def consultas(lista, ids_por_conjunto):
    """Uma linha por consulta (na ordem dos conjuntos e das consultas): itens achados por fonte, itens que so ela achou, e
    quantos tem triagem valida, relevancia alta, elegivel (alta ou media) e fora do escopo."""
    saida = []
    for conjunto, ids in ids_por_conjunto.items():
        for cid in ids:
            achados = [i for i in lista if cid in i["consultas"]]
            saida.append({"conjunto": conjunto, "consulta": cid,
                          "web": sum(1 for i in achados if i["fonte"] == FONTE_WEB),
                          "scholar": sum(1 for i in achados if i["fonte"] == FONTE_SCHOLAR),
                          "exclusivos": sum(1 for i in achados if i["consultas"] == [cid]),
                          "triados": sum(1 for i in achados if i["relevancia"]),
                          "alta": sum(1 for i in achados if i["relevancia"] == "alta"),
                          "elegiveis": sum(1 for i in achados if i["relevancia"] in ELEGIVEIS),
                          "fora": sum(1 for i in achados if i["relevancia"] == "fora_do_escopo")})
    return saida


def obras_com_origem(lista):
    """(obras, ambiguas): as mesmas obras de `obras(lista)`, na mesma ordem, cada uma copiada com `membros` [(fonte, id)]
    e `conjuntos_da_obra` (a uniao dos conjuntos dos membros, em ordem alfabetica). A referencia da web que `obras` tira
    por repetir um artigo do Scholar (URL normalizada igual; sem ela, titulo normalizado igual) soma os seus conjuntos aos
    desse artigo quando ele e um so; se casa com mais de um artigo, nao e atribuida a nenhum e o seu id volta em `ambiguas`
    (para decidir depois). Cada obra e uma copia profunda: a entrada nao muda, nem pelas listas da saida."""
    por_url, por_titulo = {}, {}
    for a in lista:
        if a["fonte"] == FONTE_SCHOLAR:
            if a["url"]:
                por_url.setdefault(normalizar_url(a["url"]), set()).add(a["id"])
            chave = chave_titulo(a["titulo"])
            if chave is not None:
                por_titulo.setdefault(chave, set()).add(a["id"])
    repetidos_url, repetidos_titulo = _repetidos_por_criterio(lista)
    extras, ambiguas = {}, []
    for i in lista:
        if i["id"] in repetidos_url:
            alvos = por_url[normalizar_url(i["url"])]
        elif i["id"] in repetidos_titulo:
            alvos = por_titulo[chave_titulo(i["titulo"])]
        else:
            continue
        if len(alvos) == 1:
            extras.setdefault(next(iter(alvos)), []).append(i)
        else:
            ambiguas.append(i["id"])
    saida = []
    for o in obras(lista):
        membros = [o] + extras.get(o["id"], [])
        saida.append({**copy.deepcopy(o), "membros": [(m["fonte"], m["id"]) for m in membros],
                      "conjuntos_da_obra": sorted({c for m in membros for c in m["conjuntos"]})})
    return saida, ambiguas


def combinacoes(nomes):
    """Os rotulos das combinacoes nao vazias de `nomes`, das menores para as maiores e, em cada tamanho, na ordem de
    `nomes`: ("A", "B") -> ["Só A", "Só B", "A + B"]."""
    return [f"Só {g[0]}" if len(g) == 1 else " + ".join(g) for n in range(1, len(nomes) + 1) for g in combinations(nomes, n)]


def conjuntos_por_obra(lista, nomes):
    """({rotulo: obras}, ambiguas): cada obra (de `obras_com_origem`) na combinacao exata dos conjuntos de `nomes` que a
    acharam, em todas as combinacoes de `combinacoes(nomes)` e por fim SEM_CONJUNTO (a obra sem nenhum conjunto de `nomes`;
    um conjunto fora de `nomes` nao conta). `ambiguas`: os ids das referencias da web sem obra atribuida."""
    obras_, ambiguas = obras_com_origem(lista)
    c = Counter(_combinacao_da_obra(o, nomes) for o in obras_)
    return {r: c.get(r, 0) for r in combinacoes(nomes) + [SEM_CONJUNTO]}, ambiguas


def _combinacao_da_obra(obra, nomes):
    """O rotulo da combinacao exata dos conjuntos de `nomes` que acharam a obra (de `obras_com_origem`); SEM_CONJUNTO sem
    nenhum."""
    achados = [n for n in nomes if n in obra["conjuntos_da_obra"]]
    if not achados:
        return SEM_CONJUNTO
    return f"Só {achados[0]}" if len(achados) == 1 else " + ".join(achados)


def origem_por_angulo(lista, nomes, recortes):
    """A matriz origem x angulo predominante das obras elegiveis (relevancia alta ou media da triagem da obra).

    Linhas: `combinacoes(nomes)` e por fim SEM_CONJUNTO; colunas: `recortes` (as chaves do recorte, na ordem dada) e por
    fim SEM_ANGULO (recorte ausente ou fora de `recortes`). Cada obra elegivel conta uma vez, numa linha e numa coluna.
    A obra e a de `obras_com_origem` (a mesma deduplicacao; com artigo do Scholar, a relevancia e o recorte sao os dele).
    Devolve {"matriz": {linha: {coluna: n}}, "linhas", "colunas", "elegiveis": n, "fora": obras nao elegiveis (relevancia
    baixa, fora do escopo ou sem triagem valida), "divergentes": obras da matriz cujo recorte (o do artigo do Scholar,
    quando ha) e um de `recortes` e que tem outro item com um recorte diferente, tambem de `recortes` (vale o da obra; a
    divergencia fica contada), "ambiguas": ids das referencias da web sem obra}. A entrada nao muda."""
    obras_, ambiguas = obras_com_origem(lista)
    linhas = combinacoes(nomes) + [SEM_CONJUNTO]
    colunas = list(recortes) + [SEM_ANGULO]
    matriz = {l: {c: 0 for c in colunas} for l in linhas}
    recorte_do_item = {i["id"]: i["recorte"] for i in lista}
    fora = divergentes = 0
    for o in obras_:
        if o["relevancia"] not in ELEGIVEIS:
            fora += 1
            continue
        if o["recorte"] in recortes and any(recorte_do_item[i] in recortes and recorte_do_item[i] != o["recorte"]
                                            for _, i in o["membros"][1:]):
            divergentes += 1
        matriz[_combinacao_da_obra(o, nomes)][o["recorte"] if o["recorte"] in recortes else SEM_ANGULO] += 1
    return {"matriz": matriz, "linhas": linhas, "colunas": colunas, "elegiveis": len(obras_) - fora, "fora": fora,
            "divergentes": divergentes, "ambiguas": ambiguas}


def dominio_registravel(dominio):
    """'new.scielo.br' -> 'scielo.br'; 'pt.scribd.com' -> 'scribd.com'; 'basedeconhecimento.cgu.gov.br' -> 'cgu.gov.br'."""
    partes = [p for p in (dominio or "").casefold().split(".") if p]
    if len(partes) >= 3 and len(partes[-1]) == 2 and partes[-2] in SEGUNDOS_NIVEIS:
        return ".".join(partes[-3:])
    return ".".join(partes[-2:])


def dominios(lista, n=15):
    """([(dominio registravel, n)] dos `n` mais frequentes, total de dominios distintos) das referencias da web no escopo."""
    linhas = contagem([dominio_registravel(i["dominio"]) for i in no_escopo(lista) if i["fonte"] == FONTE_WEB and i["dominio"]])
    return linhas[:n], len(linhas)


def relevancia_por_ferramenta(linhas, lista):
    """As linhas de `dominio.analises_ferramentas.linhas` das buscas desta busca de vies, com a relevancia dos itens da
    fonte de cada uma: alta, elegiveis, fora do escopo e custo (US$ ou creditos) por item elegivel. A fonte de uma busca tem
    um provedor so; com mais de um, os itens da fonte aparecem em cada linha."""
    saida = []
    for l in linhas:
        fonte = FONTE_DA_ETAPA.get(l["etapa"])
        if fonte is None:
            continue
        da_fonte = [i for i in lista if i["fonte"] == fonte]
        eleg = sum(1 for i in da_fonte if i["relevancia"] in ELEGIVEIS)
        saida.append({**l, "fonte": fonte, "alta": sum(1 for i in da_fonte if i["relevancia"] == "alta"), "elegiveis": eleg,
                      "fora": sum(1 for i in da_fonte if i["relevancia"] == "fora_do_escopo"),
                      "custo_por_elegivel": l["custo_usd"] / eleg if eleg and l["custo_usd"] else None,
                      "creditos_por_elegivel": l["creditos"] / eleg if eleg and l["creditos"] else None})
    return saida
