"""Referencias da busca de vies algoritmico (D102 a D111) no modelo de planilha de referencias (D103): uma linha por
referencia da busca web e por artigo do Scholar achado pelas consultas dos conjuntos. Sem I/O: recebe as linhas
lidas do banco. Nesta etapa o tipo de fonte, o pais/escopo e os topicos ficam vazios (vem da triagem, D110) e nao ha juncao entre as
duas fontes (D104)."""
from dominio.analises_vies import categoria_pais
from dominio.casos_estaduais import ano_da_data
from dominio.servicos import chave_sem_acento

COLUNAS = ("ID", "Autor/Instituição", "Ano", "Título", "Tipo de fonte", "País/escopo", "Tópicos e palavras-chave", "URL",
           "Prioridade de leitura", "Status de leitura", "Notas")
LARGURAS = (12, 56, 12, 60, 59, 19, 60, 60, 23, 19, 12)          # as do modelo ampliado
COLUNAS_EXTRAS = ("Fonte da busca", "Conjunto")
COLUNA_IDIOMA = "Idioma da busca"      # so do Scholar: com o filtro so portugues, sem filtro ou as duas (D123)
# chave do filtro da tela -> rotulo; o conjunto de chaves de idioma das chamadas que acharam o artigo decide o rotulo
IDIOMAS_DA_BUSCA = {"so_portugues": "Só português", "sem_filtro": "Sem filtro", "as_duas": "As duas"}
IDIOMA_OUTRO = "Outro filtro"
COLUNA_EXECUCAO = "Execução"          # na tela: as execucoes que acharam a referencia (o modelo Erico nao leva)
COLUNA_RECORTE, COLUNA_LOCAL, COLUNA_CONSULTAS = "Recorte", "Local", "Consultas"
COLUNAS_TRIAGEM_TELA = (COLUNA_RECORTE, COLUNA_LOCAL)                # da triagem v2, alem das 3 do modelo
COLUNAS_TELA = (COLUNAS + COLUNAS_TRIAGEM_TELA + (COLUNA_CONSULTAS, COLUNA_EXECUCAO) + COLUNAS_EXTRAS[:1] + (COLUNA_IDIOMA,)
                + COLUNAS_EXTRAS[1:])
# o local de cada item, pelo pais/escopo da triagem (a mesma regra das analises: analises_vies.categoria_pais)
LOCAIS = {"brasil": "Brasil", "outro": "Internacional", "indeterminado": "Indeterminado"}
ABA_COLUNAS = "Referências"           # a aba unica do download "Colunas selecionadas"
COLUNAS_ESQUEMA = ("Eixo", "Perguntas de exploração")
LARGURAS_ESQUEMA = (35, 60)
ABA_REFERENCIAS, ABA_ESQUEMA = "Referências ampliadas", "Esquema de exploração"     # os nomes das abas do modelo ampliado
LARGURA_DA_COLUNA = {**dict(zip(COLUNAS, LARGURAS)), COLUNA_RECORTE: 24, COLUNA_LOCAL: 16, COLUNA_CONSULTAS: 60,
                     COLUNA_EXECUCAO: 26, "Fonte da busca": 14, COLUNA_IDIOMA: 16, "Conjunto": 12}
STATUS_NAO_INICIADO = "Não iniciado"     # como na planilha de referências do modelo (com acento)
FONTE_WEB, FONTE_SCHOLAR = "Web", "Scholar"         # sem o nome do provedor: trocar de provedor nao muda a tela


def _lista(texto):
    """'LA2,LA1,LA2' -> 'LA1, LA2' (sem repeticao, em ordem)."""
    return ", ".join(sorted({p.strip() for p in (texto or "").split(",") if p.strip()}))


def idioma_da_busca(idiomas):
    """O rotulo da coluna "Idioma da busca" pelas chaves de idioma das chamadas que acharam o artigo ('so_portugues,sem_filtro'):
    so 'so_portugues', so 'sem_filtro', as duas; qualquer outra chave presente vale "Outro filtro"; vazio sem chave."""
    chaves = {p.strip() for p in (idiomas or "").split(",") if p.strip()}
    if not chaves:
        return ""
    if chaves == {"so_portugues"}:
        return IDIOMAS_DA_BUSCA["so_portugues"]
    if chaves == {"sem_filtro"}:
        return IDIOMAS_DA_BUSCA["sem_filtro"]
    if chaves == {"so_portugues", "sem_filtro"}:
        return IDIOMAS_DA_BUSCA["as_duas"]
    return IDIOMA_OUTRO


def _base(id_, autor, ano, titulo, url, fonte, conjuntos, execucoes, consultas="", idioma=""):
    return {"ID": id_, "Autor/Instituição": autor or "", "Ano": ano, "Título": titulo or "", "Tipo de fonte": "",
            "País/escopo": "", "Tópicos e palavras-chave": "",        # temas por extenso: vêm da triagem, nunca códigos
            "URL": url or "", "Prioridade de leitura": "", "Status de leitura": STATUS_NAO_INICIADO, "Notas": "",
            "Fonte da busca": fonte, COLUNA_IDIOMA: idioma, "Conjunto": _lista(conjuntos), COLUNA_RECORTE: "", COLUNA_LOCAL: "",
            COLUNA_CONSULTAS: [c for c in _lista(consultas).split(", ") if c],
            COLUNA_EXECUCAO: [e for e in _lista(execucoes).split(", ") if e]}


def linha_web(l):
    """Uma referencia da web: o autor e o dominio do site; titulo e data do resultado mais recente."""
    return _base(f"W-{l['referencia_id']}", l["dominio"], ano_da_data(l["data_pub"]), l["titulo"], l["url_original"],
                 FONTE_WEB, l["conjuntos"], l["execucoes"], l.get("consultas"))


def linha_artigo(l, conjunto_da_consulta):
    """Um artigo do Scholar: os autores sao a parte de `autores_publicacao` antes do ' - '."""
    autores = (l["autores_publicacao"] or "").split(" - ")[0].strip()
    consultas = _lista(l["consultas"])
    conjuntos = ",".join(conjunto_da_consulta.get(c, "") for c in consultas.split(", ") if c)
    return _base(f"A-{l['artigo_id']}", autores, l["ano"] if isinstance(l["ano"], int) else None, l["titulo"], l["link"],
                 FONTE_SCHOLAR, conjuntos, l["execucoes"], consultas, idioma_da_busca(l.get("idiomas")))


COLUNAS_DA_TRIAGEM = {"Tipo de fonte": "tipo_fonte", "País/escopo": "pais_escopo", "Tópicos e palavras-chave": "topicos"}


def com_triagem(linha, triagem, rotulos_recorte=None):
    """A linha com "Tipo de fonte", "País/escopo" e "Tópicos e palavras-chave" da triagem da busca de viés, o "Recorte"
    (o rotulo de `rotulos_recorte`; vazio sem recorte, como nas linhas da v1) e o "Local" (pelo pais/escopo), quando a
    triagem mais recente do item passou nas conferências (`valido`); senão, a linha como está (colunas vazias)."""
    if not triagem or not triagem.get("valido"):
        return linha
    return {**linha, **{coluna: triagem.get(campo) or "" for coluna, campo in COLUNAS_DA_TRIAGEM.items()},
            COLUNA_RECORTE: (rotulos_recorte or {}).get(triagem.get("recorte"), ""),
            COLUNA_LOCAL: LOCAIS[categoria_pais(triagem.get("pais_escopo"))]}


def referencias(linhas_web, linhas_artigos, conjunto_da_consulta, triagens=None, rotulos_recorte=None):
    """Todas as linhas, do ano mais recente para o mais antigo (sem ano no fim), empate pelo ID. `triagens`:
    {(fonte, item_id): linha da triagem}, com fonte "referencia" ou "artigo"; `rotulos_recorte`: {chave: rotulo}."""
    triagens = triagens or {}
    todas = ([com_triagem(linha_web(l), triagens.get(("referencia", l["referencia_id"])), rotulos_recorte) for l in linhas_web]
             + [com_triagem(linha_artigo(l, conjunto_da_consulta), triagens.get(("artigo", l["artigo_id"])), rotulos_recorte)
                for l in linhas_artigos])
    todas.sort(key=lambda r: (r["Ano"] is None, -(r["Ano"] or 0), r["ID"][0], int(r["ID"][2:])))
    return todas


def filtrar(linhas, conjunto="", fonte="", texto="", recorte="", idioma=""):
    """Os filtros da tela: conjunto, fonte da busca, recorte (o rotulo exato da coluna "Recorte"), idioma da busca (o
    rotulo exato da coluna "Idioma da busca"; as linhas da web ficam de fora) e um texto procurado no
    titulo, no autor e na URL, sem diferenca de acento nem de maiuscula."""
    procura = chave_sem_acento(texto.strip())
    if texto.strip() and not procura:          # so caracteres que a chave descarta: nada casa, em vez de tudo
        return []
    saida = []
    for r in linhas:
        if conjunto and conjunto not in r["Conjunto"].split(", "):
            continue
        if fonte and r["Fonte da busca"] != fonte:
            continue
        if recorte and r[COLUNA_RECORTE] != recorte:
            continue
        if idioma and r[COLUNA_IDIOMA] != idioma:
            continue
        if procura and procura not in chave_sem_acento(" ".join((r["Título"], r["Autor/Instituição"], r["URL"]))):
            continue
        saida.append(r)
    return saida


def colunas_escolhidas(pedidas):
    """As colunas da tela na ordem de COLUNAS_TELA: as `pedidas` (nomes exatos, repeticao ignorada) ou, sem nenhuma,
    todas; None quando alguma nao e coluna da tela."""
    if any(c not in COLUNAS_TELA for c in pedidas):
        return None
    return [c for c in COLUNAS_TELA if not pedidas or c in pedidas]


def textos_das_consultas(codigos, textos_consultas):
    """As consultas por extenso, na ordem dos codigos; o codigo fica quando o texto nao e conhecido (tela e download)."""
    return [textos_consultas.get(c, c) for c in codigos]


def valor_texto(linha, coluna, textos_consultas):
    """O valor da celula como texto, para o download "Colunas selecionadas": as consultas por extenso
    (`textos_das_consultas`), separadas por "; "; as execucoes separadas por ", "; o ano como texto; vazio sem valor."""
    v = linha[coluna]
    if coluna == COLUNA_CONSULTAS:
        return "; ".join(textos_das_consultas(v, textos_consultas))
    if coluna == COLUNA_EXECUCAO:
        return ", ".join(v)
    return "" if v is None else str(v)
