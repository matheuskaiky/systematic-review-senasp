def esquema_classificacao(tecnologias, status, confianca):
    """NEUTRAL JSON Schema. Each adapter converts it to its provider's dialect."""
    return {
        "type": "object",
        "properties": {
            "relevante": {"type": "boolean",
                          "description": "true if the text supports at least one finding for the target state"},
            "achados": {"type": "array", "items": {
                "type": "object",
                "properties": {
                    "tecnologia": {"type": "string", "enum": list(tecnologias)},
                    "status": {"type": "string", "enum": list(status)},
                    "fornecedor": {"type": "string", "description": "vendor company or empty string"},
                    "menciona_lgpd": {"type": "boolean"},
                    "evidencia": {"type": "string", "description": "LITERAL excerpt of the text, up to 300 characters"},
                    "confianca": {"type": "string", "enum": list(confianca)},
                    "nome_solucao": {"type": "string",
                                     "description": "official proper name of the tool/system/program as written in the text, or empty string"},
                },
                "required": ["tecnologia", "status", "fornecedor", "menciona_lgpd", "evidencia", "confianca", "nome_solucao"],
            }},
        },
        "required": ["relevante", "achados"],
    }
