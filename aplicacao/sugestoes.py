"""Casos de uso das sugestoes (D78). O painel decide quem pode sugerir e quem pode resolver; aqui ficam as regras do dado."""
from dominio.sugestoes import validar_sugestao


def criar(repo, alvo_tipo, alvo_id, valor, motivo, autor, estado, status_permitidos):
    try:
        v, m = validar_sugestao(alvo_tipo, valor, motivo, status_permitidos)
    except ValueError as e:
        raise SystemExit(str(e))
    return repo.criar_sugestao(alvo_tipo, alvo_id, v, m, autor, estado)


def aceitar(repo, sugestao_id, resolvedor, status_permitidos):
    repo.aceitar_sugestao(sugestao_id, resolvedor, status_permitidos)


def descartar(repo, sugestao_id, resolvedor):
    repo.descartar_sugestao(sugestao_id, resolvedor)
