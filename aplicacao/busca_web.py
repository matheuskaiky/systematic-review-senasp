import json
import logging
import time
from dataclasses import asdict
from dominio.servicos import hash_chave
from aplicacao.comum import registrar_chamada


def executar(repo, bruto, busca, run_id, consultas, perfis, segredos, pausa, limite=None):
    feitas = 0
    for c in consultas:
        if limite and feitas >= limite:
            break
        filtros = perfis[c.perfil]
        chave = hash_chave("busca_web", busca.nome, c.id, json.dumps(asdict(filtros), sort_keys=True))
        if repo.ja_feito(run_id, chave):
            continue
        resp = busca.buscar(c, filtros)
        chamada_id, _ = registrar_chamada(repo, bruto, run_id, "busca_web", "consulta_web", c.id, chave,
                                          resp.chamada, segredos, uf=c.uf)
        novas = repo.salvar_resultados_web(chamada_id, run_id, c, resp.resultados) if resp.chamada.sucesso else 0
        repo.atualizar_chamada(chamada_id, n_retornados=len(resp.resultados), n_novos=novas)
        repo.confirmar()
        feitas += 1
        logging.info("[%s] ok=%s results=%d new_urls=%d lat=%sms", c.id, resp.chamada.sucesso,
                     len(resp.resultados), novas, resp.chamada.latencia_ms)
        time.sleep(pausa)
