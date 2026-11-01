"""Regras de apresentação da pesquisa na Visão Geral pública."""

MARCADOR = "PREENCHA"

SECOES = (
    ("descricao", "Sobre a pesquisa"),
    ("perguntas", "Perguntas de pesquisa"),
    ("metodo", "Como a pesquisa é feita"),
    ("abrangencia", "Abrangência"),
    ("limitacoes", "Limitações"),
    ("instituicao", "Instituição e contato"),
)

MAX_PARAGRAFOS = 10
MAX_CARACTERES = 2000

_LISTAS = {
    "perguntas": "ol",
    "limitacoes": "ul",
}


def secoes_publicas(textos) -> dict:
    """Retorna as seções públicas válidas separadas em 'antes' e 'depois', na ordem de SECOES."""
    if type(textos) is not dict:
        return {"antes": [], "depois": []}

    antes = []
    depois = []

    for idx, (s_id, s_titulo) in enumerate(SECOES):
        if s_id not in textos:
            continue
        v = textos[s_id]
        if type(v) is not tuple:
            continue
        if not (1 <= len(v) <= MAX_PARAGRAFOS):
            continue
        valido = True
        for p in v:
            if type(p) is not str:
                valido = False
                break
            if not p.strip():
                valido = False
                break
            if MARCADOR in p:
                valido = False
                break
            if len(p) > MAX_CARACTERES:
                valido = False
                break
        if not valido:
            continue

        item = {
            "id": s_id,
            "titulo": s_titulo,
            "lista": _LISTAS.get(s_id),
            "paragrafos": list(v),
        }
        if idx < 4:
            antes.append(item)
        else:
            depois.append(item)

    return {"antes": antes, "depois": depois}
