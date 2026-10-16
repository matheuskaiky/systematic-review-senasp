"""O que cada etapa de entrada vai processar: candidatos de download e itens de classificacao, com os filtros de resgate.

Funcoes so de leitura (nenhuma chamada externa e nenhuma gravacao): `download.executar` e `classificacao.executar` as
usam para decidir o que fazer e `main.py --listar` as usa para mostrar o que seria feito, com o mesmo resultado."""
from dominio.entrada import motivo_falha_download_valido, descricao_motivos_falha_download
from dominio.servicos import selecionar_candidatos, escolher_auditoria


def validar_motivo_falha(motivo):
    """Encerra com a lista de motivos validos se `--so-falha` receber um motivo desconhecido."""
    if motivo is not None and not motivo_falha_download_valido(motivo):
        raise SystemExit(f"Motivo inválido em --so-falha: {motivo!r}. Motivos válidos: {descricao_motivos_falha_download()}.")


def _restringir_a_urls(itens, urls, rotulo):
    """Mantem so os `url_id` pedidos em --urls; encerra se nenhum deles esta entre os candidatos."""
    if not urls:
        return itens
    pedidos = {int(u) for u in urls}
    mantidos = [i for i in itens if i.url_id in pedidos]
    if not mantidos:
        raise SystemExit(f"Nenhum dos url_id de --urls ({', '.join(str(u) for u in sorted(pedidos))}) é {rotulo} "
                         "das execuções indicadas em --de (e das UFs pedidas).")
    return mantidos


def planejar_download(repo, run_origens, politica, ufs=None, auditoria=0, semente="", so_sem_pagina=False, so_falha=None,
                      urls=None, excluir_run=None):
    """(candidatos, decisao, amostra): candidatos que sobraram dos filtros, a decisao de `selecionar_candidatos` sobre
    eles e o conjunto (url_id, uf) da amostra de auditoria.

    Os filtros de resgate (`--urls`, `--so-sem-pagina`, `--so-falha`) valem ANTES de `selecionar_candidatos`: o limite
    por UF conta so os candidatos do resgate. `excluir_run` e a execucao em curso: o que ela mesma baixou nao muda o que
    ela selecionou ao ser retomada."""
    validar_motivo_falha(so_falha)
    cands = [c for c in repo.candidatos_download(run_origens) if not ufs or c.uf in ufs]
    cands = _restringir_a_urls(cands, urls, "candidato a download")
    if so_sem_pagina:
        com_pagina = repo.urls_com_pagina_ok(excluir_run)
        cands = [c for c in cands if c.url_id not in com_pagina]
    if so_falha:
        ultimas = repo.ultimas_tentativas_download(excluir_run)
        cands = [c for c in cands if ultimas.get(c.url_id) == ("falha_download", so_falha)]
    decisao = selecionar_candidatos(cands, politica)
    amostra = {(c.url_id, c.uf) for c, _, _ in escolher_auditoria(decisao, auditoria, semente)}
    return cands, decisao, amostra


def planejar_classificacao(repo, run_origens, ufs=None, urls=None, so_nao_classificadas=False, prompt_versao=None,
                           classificador=None, excluir_run=None):
    """Itens a classificar, na ordem do repositorio (uf, url_id). `so_nao_classificadas` pula os pares (url_id, uf) que ja
    tem classificacao valida com o MESMO `prompt_versao` e o mesmo `classificador` em alguma execucao do relatorio: uma
    nova versao do prompt reclassifica de proposito."""
    itens = [i for i in repo.itens_para_classificar(run_origens) if not ufs or i.uf in ufs]
    itens = _restringir_a_urls(itens, urls, "item a classificar")
    if so_nao_classificadas:
        feitos = repo.classificados_validos(prompt_versao, classificador, excluir_run)
        itens = [i for i in itens if (i.url_id, i.uf) not in feitos]
    return itens
