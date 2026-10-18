"""Modelos de planilha do catalogo de referencias (comando exportar-referencias). Um modelo novo entra aqui, sem mudar codigo."""
from dominio.modelos import ModeloPlanilhaReferencias

_COLUNAS_PROFESSOR = (
    ("ID", "id"),
    ("Categoria", "categoria"),
    ("Autor/Instituicao", "autor"),
    ("Ano", "ano"),
    ("Titulo", "titulo"),
    ("Tipo de fonte", "tipo_fonte"),
    ("Pais/escopo", "pais_escopo"),
    ("Topicos e palavras-chave", "topicos"),
    ("URL", "url"),
    ("Prioridade de leitura", "prioridade"),
    ("Status de leitura", "status_leitura"),
    ("Notas", "notas"),
)

MODELOS_REFERENCIAS = {
    "padrao": ModeloPlanilhaReferencias(
        "padrao",
        "referencias.xlsx",
        _COLUNAS_PROFESSOR + (
            ("Eixo tematico", "eixo"),
            ("Citacoes", "citacoes"),
            ("Termos", "termos"),
            ("Triagem do modelo", "triagem_modelo"),
            ("Decisao humana", "decisao_humana"),
        ),
        (
            ("Referencias", None),
            ("Referencias_Brasil", "brasil"),
            ("Referencias_Internacional", "internacional"),
        ),
        explicar_colunas=True,
    ),
    "professor": ModeloPlanilhaReferencias(
        "professor",
        "referencias_modelo_professor.xlsx",
        _COLUNAS_PROFESSOR,
        (
            ("Todas as Referencias", None),
            ("Brasil", "brasil"),
            ("Internacional", "internacional"),
        ),
    ),
}

MODELO_REFERENCIAS_PADRAO = "padrao"
