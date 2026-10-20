import json
import logging
import time
from dataclasses import asdict
from dominio.servicos import hash_chave
from aplicacao.comum import item_gravado


def executar(repo, bruto, academico, run_id, termos, filtros, max_paginas, segredos, pausa):
    for termo in termos:
        for p in range(max_paginas):
            inicio = p * filtros.por_pagina
            chave = hash_chave("busca_academica", academico.nome, termo.id,
                               json.dumps(asdict(filtros), sort_keys=True), inicio)
            if repo.ja_feito(run_id, chave):
                # C8: a pagina ja feita segue a mesma regra de parada; se ela veio incompleta nao ha proxima pagina,
                # e pedi-la na retomada gastaria um credito a toa. Sem o n_retornados guardado, segue para a proxima.
                feito = repo.resultado_chamada(run_id, chave)
                if feito is not None and feito[1] is not None and feito[1] < filtros.por_pagina:
                    break
                continue
            pag = academico.buscar_pagina(termo, inicio, filtros)
            with item_gravado(repo, bruto, run_id, "busca_academica", "termo", termo.id, chave, pag.chamada, segredos,
                              pagina=p + 1) as chamada_id:
                novos = repo.salvar_artigos(chamada_id, run_id, termo.id, pag.artigos) if pag.chamada.sucesso else 0
                repo.atualizar_chamada(chamada_id, total_reportado=pag.total_reportado,
                                       n_retornados=len(pag.artigos), n_novos=novos)
            logging.info("[%s p%d] ok=%s returned=%d new=%d approx_total=%s lat=%sms", termo.id, p + 1,
                         pag.chamada.sucesso, len(pag.artigos), novos, pag.total_reportado, pag.chamada.latencia_ms)
            time.sleep(pausa)
            if not pag.chamada.sucesso or len(pag.artigos) < filtros.por_pagina:
                break
