"""Sugestoes sobre uma decisao ja tomada (D78): validacao pura do valor e do motivo, ficha da decisao e chave do autor."""
import hashlib
import json
import unicodedata

CAMPOS_ACHADO = ("verificado", "status_final", "verificado_por", "verificado_em", "observacao")
CAMPOS_ARTIGO = ("decisao", "motivo", "confirmado_em_base", "link_confirmado", "revisor", "revisado_em", "decisao_texto_completo",
                 "motivo_texto_completo")


def ficha_da_decisao(valores):
    """Identifica o estado completo de uma decisao: muda quando qualquer campo muda, mesmo dentro do mesmo segundo."""
    return hashlib.sha256(json.dumps(list(valores), ensure_ascii=False, default=str).encode("utf-8")).hexdigest()[:20]


def chave_autor(nome):
    """Nome de pessoa para comparacao: sem espacos nas pontas, Unicode NFC e sem distinguir maiusculas (D78)."""
    return unicodedata.normalize("NFC", str(nome or "").strip()).casefold()


ALVOS = ("achado", "artigo")
DECISOES_ARTIGO = ("incluir", "excluir")
MOTIVO_MAX = 2000
MSG_MOTIVO_EXCLUIR = "Informe o motivo da exclusão: ele entra nos motivos de exclusão do PRISMA"


def validar_sugestao(alvo_tipo, valor, motivo, status_permitidos):
    """Devolve (valor normalizado, motivo como veio, ou "" se ausente). Erros (ValueError), nesta ordem: tipo de item, valor
    vazio, valor fora do vocabulario, motivo longo, exclusao de artigo sem motivo."""
    if alvo_tipo not in ALVOS:
        raise ValueError(f"Tipo de item inválido: {alvo_tipo!r}.")
    v = str(valor or "").strip().lower()
    if not v:
        raise ValueError("Escolha o valor sugerido.")
    if alvo_tipo == "achado" and v not in status_permitidos:
        raise ValueError(f"Valor sugerido inválido para o achado: {str(valor).strip()!r}.")
    if alvo_tipo == "artigo" and v not in DECISOES_ARTIGO:
        raise ValueError(f"Valor sugerido inválido para o artigo: {str(valor).strip()!r}.")
    m = "" if motivo is None else str(motivo)
    if len(m) > MOTIVO_MAX:
        raise ValueError(f"O motivo passa de {MOTIVO_MAX} caracteres.")
    if alvo_tipo == "artigo" and v == "excluir" and not m.strip():
        raise ValueError(MSG_MOTIVO_EXCLUIR)
    return v, m
