"""Referencias da busca de vies algoritmico (D102 a D111) no modelo de planilha de referencias (D103): uma linha por
referencia da busca web e por artigo do Scholar achado pelas consultas dos conjuntos. Sem I/O: recebe as linhas
lidas do banco. Nesta etapa o tipo de fonte, o pais/escopo e os topicos ficam vazios (vem da triagem, D110) e nao ha juncao entre as
duas fontes (D104)."""
from dominio.casos_estaduais import ano_da_data
from dominio.servicos import chave_sem_acento

COLUNAS = ("ID", "Autor/Instituição", "Ano", "Título", "Tipo de fonte", "País/escopo", "Tópicos e palavras-chave", "URL",
           "Prioridade de leitura", "Status de leitura", "Notas")
LARGURAS = (12, 56, 12, 60, 59, 19, 60, 60, 23, 19, 12)          # as do modelo ampliado
COLUNAS_EXTRAS = ("Fonte da busca", "Conjunto")
COLUNA_EXECUCAO = "Execução"          # so na tela: as execucoes que acharam a referencia (o arquivo baixado nao leva)
COLUNAS_TELA = COLUNAS + (COLUNA_EXECUCAO,) + COLUNAS_EXTRAS      # na tela, logo ao lado das 11 colunas do modelo
COLUNAS_ESQUEMA = ("Eixo", "Perguntas de exploração")
LARGURAS_ESQUEMA = (35, 60)
ABA_REFERENCIAS, ABA_ESQUEMA = "Referências ampliadas", "Esquema de exploração"     # os nomes das abas do modelo ampliado
STATUS_NAO_INICIADO = "Não iniciado"     # como na planilha de referências do modelo (com acento)
FONTE_WEB, FONTE_SCHOLAR = "Web", "Scholar"         # sem o nome do provedor: trocar de provedor nao muda a tela


def _lista(texto):
    """'LA2,LA1,LA2' -> 'LA1, LA2' (sem repeticao, em ordem)."""
    return ", ".join(sorted({p.strip() for p in (texto or "").split(",") if p.strip()}))


def _base(id_, autor, ano, titulo, url, fonte, conjuntos, execucoes):
    return {"ID": id_, "Autor/Instituição": autor or "", "Ano": ano, "Título": titulo or "", "Tipo de fonte": "",
            "País/escopo": "", "Tópicos e palavras-chave": "",        # temas por extenso: vêm da triagem, nunca códigos
            "URL": url or "", "Prioridade de leitura": "", "Status de leitura": STATUS_NAO_INICIADO, "Notas": "",
            "Fonte da busca": fonte, "Conjunto": _lista(conjuntos),
            COLUNA_EXECUCAO: [e for e in _lista(execucoes).split(", ") if e]}


def linha_web(l):
    """Uma referencia da web: o autor e o dominio do site; titulo e data do resultado mais recente."""
    return _base(f"W-{l['referencia_id']}", l["dominio"], ano_da_data(l["data_pub"]), l["titulo"], l["url_original"],
                 FONTE_WEB, l["conjuntos"], l["execucoes"])


def linha_artigo(l, conjunto_da_consulta):
    """Um artigo do Scholar: os autores sao a parte de `autores_publicacao` antes do ' - '."""
    autores = (l["autores_publicacao"] or "").split(" - ")[0].strip()
    consultas = _lista(l["consultas"])
    conjuntos = ",".join(conjunto_da_consulta.get(c, "") for c in consultas.split(", ") if c)
    return _base(f"A-{l['artigo_id']}", autores, l["ano"] if isinstance(l["ano"], int) else None, l["titulo"], l["link"],
                 FONTE_SCHOLAR, conjuntos, l["execucoes"])


COLUNAS_DA_TRIAGEM = {"Tipo de fonte": "tipo_fonte", "País/escopo": "pais_escopo", "Tópicos e palavras-chave": "topicos"}


def com_triagem(linha, triagem):
    """A linha com "Tipo de fonte", "País/escopo" e "Tópicos e palavras-chave" da triagem da busca de viés, quando a
    triagem mais recente do item passou nas conferências (`valido`); senão, a linha como está (colunas vazias)."""
    if not triagem or not triagem.get("valido"):
        return linha
    return {**linha, **{coluna: triagem.get(campo) or "" for coluna, campo in COLUNAS_DA_TRIAGEM.items()}}


def referencias(linhas_web, linhas_artigos, conjunto_da_consulta, triagens=None):
    """Todas as linhas, do ano mais recente para o mais antigo (sem ano no fim), empate pelo ID. `triagens`:
    {(fonte, item_id): linha da triagem}, com fonte "referencia" ou "artigo"."""
    triagens = triagens or {}
    todas = ([com_triagem(linha_web(l), triagens.get(("referencia", l["referencia_id"]))) for l in linhas_web]
             + [com_triagem(linha_artigo(l, conjunto_da_consulta), triagens.get(("artigo", l["artigo_id"])))
                for l in linhas_artigos])
    todas.sort(key=lambda r: (r["Ano"] is None, -(r["Ano"] or 0), r["ID"][0], int(r["ID"][2:])))
    return todas


def filtrar(linhas, conjunto="", fonte="", texto=""):
    """Os filtros da tela: conjunto (A ou B), fonte da busca e um texto procurado no titulo, no autor e na URL, sem
    diferenca de acento nem de maiuscula."""
    procura = chave_sem_acento(texto.strip())
    if texto.strip() and not procura:          # so caracteres que a chave descarta: nada casa, em vez de tudo
        return []
    saida = []
    for r in linhas:
        if conjunto and conjunto not in r["Conjunto"].split(", "):
            continue
        if fonte and r["Fonte da busca"] != fonte:
            continue
        if procura and procura not in chave_sem_acento(" ".join((r["Título"], r["Autor/Instituição"], r["URL"]))):
            continue
        saida.append(r)
    return saida
