"""Casos de uso da revisao humana dos achados (usados pelo painel). As regras de validacao vivem no repositorio e em
`dominio.servicos.normalizar_status_final`, as mesmas da importacao da planilha."""


def verificar_achado(repo, achado_id, status_final, revisor, observacao, status_permitidos, versao=None):
    repo.verificar_achado(achado_id, status_final, revisor, observacao, status_permitidos, versao)


def desfazer_decisao(repo, achado_id):
    repo.desfazer_ultima_decisao(achado_id)


def revogar_verificacao(repo, achado_id, revisor, motivo, versao=None):
    if not str(motivo or "").strip():
        raise SystemExit("Informe o motivo da revogação")
    if not str(revisor or "").strip():
        raise SystemExit("Informe o nome do revisor")
    repo.desverificar_achado(achado_id, revisor, str(motivo).strip(), versao)
