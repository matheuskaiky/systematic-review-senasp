import json
import logging
import time
from dataclasses import asdict
from dominio.servicos import hash_chave
from aplicacao.comum import registrar_chamada


def executar(repo, bruto, academico, run_id, termos, filtros, max_paginas, segredos, pausa):
    for termo in termos:
        for p in range(max_paginas):
            inicio = p * filtros.por_pagina
            chave = hash_chave("busca_academica", academico.nome, termo.id,
                               json.dumps(asdict(filtros), sort_keys=True), inicio)
            if repo.ja_feito(run_id, chave):
                continue
            pag = academico.buscar_pagina(termo, inicio, filtros)
            chamada_id, _ = registrar_chamada(repo, bruto, run_id, "busca_academica", "termo", termo.id,
                                              chave, pag.chamada, segredos, pagina=p + 1)
            novos = repo.salvar_artigos(chamada_id, run_id, termo.id, pag.artigos) if pag.chamada.sucesso else 0
            repo.atualizar_chamada(chamada_id, total_reportado=pag.total_reportado,
                                   n_retornados=len(pag.artigos), n_novos=novos)
            repo.confirmar()
            logging.info("[%s p%d] ok=%s returned=%d new=%d approx_total=%s lat=%sms", termo.id, p + 1,
                         pag.chamada.sucesso, len(pag.artigos), novos, pag.total_reportado, pag.chamada.latencia_ms)
            time.sleep(pausa)
            if not pag.chamada.sucesso or len(pag.artigos) < filtros.por_pagina:
                break
