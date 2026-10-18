CAMPOS_CATALOGO = (
    "id",
    "categoria",
    "eixo",
    "autor",
    "ano",
    "titulo",
    "tipo_fonte",
    "pais_escopo",
    "topicos",
    "url",
    "prioridade",
    "status_leitura",
    "notas",
    "citacoes",
    "termos",
    "triagem_modelo",
    "decisao_humana",
)

PRIORIDADES = ("Alta", "Media", "Baixa")
STATUS_LEITURA = ("Nao iniciado", "Em leitura", "Lido", "Descartado")
STATUS_LEITURA_PADRAO = "Nao iniciado"

_TIPOS = {
    "artigo_periodico": "Artigo cientifico",
    "artigo_congresso": "Artigo de congresso",
    "tese_dissertacao": "Tese ou dissertacao",
    "livro_capitulo": "Livro ou capitulo",
    "relatorio_tecnico": "Relatorio tecnico",
    "noticia_pagina_institucional": "Reportagem ou pagina institucional",
    "outro": "Outro",
}

SIGNIFICADO_COLUNAS = {
    "ID": "Identificador do trabalho no banco (artigos.artigo_id).",
    "Categoria": "Grupo do acervo, preenchido pelo pesquisador (lista na aba Legenda).",
    "Autor/Instituicao": "Autores, como o Google Scholar informa (parte antes do veiculo).",
    "Ano": "Ano de publicacao.",
    "Titulo": "Titulo do trabalho.",
    "Tipo de fonte": "Tipo de documento segundo a triagem de escopo do modelo de linguagem.",
    "Pais/escopo": "Brasil, Internacional ou Indeterminado, segundo a triagem de escopo do modelo de linguagem.",
    "Topicos e palavras-chave": "Consultas dos termos que acharam o trabalho e o dominio tematico atribuido pela triagem de escopo.",
    "URL": "Endereco do trabalho.",
    "Prioridade de leitura": "Alta, Media ou Baixa, preenchida pelo pesquisador.",
    "Status de leitura": "Nao iniciado, Em leitura, Lido ou Descartado, preenchido pelo pesquisador.",
    "Notas": "Anotacoes livres do pesquisador.",
    "Eixo tematico": "Eixo do indice tematico, preenchido pelo pesquisador (lista na aba Indice_Tematico).",
    "Citacoes": "Citacoes informadas pelo Google Scholar na coleta.",
    "Termos": "Identificadores dos termos que acharam o trabalho.",
    "Triagem do modelo": "Status da triagem de escopo do modelo de linguagem (elegivel ou quarentena).",
    "Decisao humana": "Decisao da triagem humana (incluir ou pendente).",
}


def autor_de(autores_publicacao):
    return "" if not autores_publicacao else autores_publicacao.split(" - ", 1)[0].strip()


def rotulo_pais(escopo):
    return {"brasil": "Brasil", "internacional": "Internacional"}.get(escopo, "Indeterminado")


def rotulo_tipo(tipo):
    return _TIPOS.get(tipo, "Indeterminado")


def validar_leitura(linha, categorias, eixos):
    erros = []
    item_id = linha.get("id")

    def _vazio(v):
        return v is None or (isinstance(v, str) and not v.strip())

    cat = linha.get("categoria")
    if not _vazio(cat) and cat not in categorias:
        erros.append(f"ID {item_id}: Categoria invalida: '{cat}'")

    eixo = linha.get("eixo")
    if not _vazio(eixo) and eixo not in eixos:
        erros.append(f"ID {item_id}: Eixo tematico invalida: '{eixo}'")

    prio = linha.get("prioridade")
    if not _vazio(prio) and prio not in PRIORIDADES:
        erros.append(f"ID {item_id}: Prioridade de leitura invalida: '{prio}'")

    st = linha.get("status_leitura")
    if not _vazio(st) and st not in STATUS_LEITURA:
        erros.append(f"ID {item_id}: Status de leitura invalida: '{st}'")

    return erros
