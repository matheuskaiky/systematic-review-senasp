from dominio.catalogo import (
    STATUS_LEITURA_PADRAO,
    autor_de,
    rotulo_pais,
    rotulo_tipo,
)


def montar_catalogo(linhas):
    """Monta a lista de referencias com todos os campos de CAMPOS_CATALOGO a partir das linhas do banco."""
    catalogo = []
    for r in linhas:
        consultas = r.get("consultas") or ""
        dominio_tematico = r.get("dominio_tematico") or ""
        topicos = "; ".join(p for p in (consultas, dominio_tematico) if p)

        item = {
            "id": r["artigo_id"],
            "categoria": r.get("categoria") or "",
            "eixo": r.get("eixo") or "",
            "prioridade": r.get("prioridade") or "",
            "notas": r.get("notas") or "",
            "status_leitura": r.get("status_leitura") or STATUS_LEITURA_PADRAO,
            "autor": autor_de(r.get("autores_publicacao")),
            "ano": r.get("ano"),
            "titulo": r.get("titulo"),
            "tipo_fonte": rotulo_tipo(r.get("tipo_documento")),
            "pais_escopo": rotulo_pais(r.get("escopo_geografico")),
            "topicos": topicos,
            "url": r.get("link"),
            "citacoes": r.get("citacoes"),
            "termos": r.get("termos") or "",
            "triagem_modelo": r.get("status_escopo") or "",
            "decisao_humana": r.get("decisao") or "pendente",
        }
        catalogo.append(item)

    catalogo.sort(key=lambda x: (x["pais_escopo"] != "Brasil", -(x["citacoes"] or 0), x["id"]))
    return catalogo
