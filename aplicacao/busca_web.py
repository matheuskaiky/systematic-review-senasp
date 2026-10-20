import json
import logging
import time
from dataclasses import asdict
from dominio.servicos import hash_chave
from aplicacao.comum import item_gravado


def executar(repo, bruto, busca, run_id, consultas, perfis, segredos, pausa, limite=None):
    chamadas = repo.chaves_com_chamada(run_id, "busca_web")   # o --limite vale para a execucao inteira, retomadas incluidas
    for c in consultas:
        filtros = perfis[c.perfil]
        chave = hash_chave("busca_web", busca.nome, c.id, json.dumps(asdict(filtros), sort_keys=True))
        if repo.ja_feito(run_id, chave):
            continue
        if limite and chave not in chamadas and len(chamadas) >= limite:
            break
        resp = busca.buscar(c, filtros)
        chamadas.add(chave)
        with item_gravado(repo, bruto, run_id, "busca_web", "consulta_web", c.id, chave, resp.chamada, segredos,
                          uf=c.uf) as chamada_id:
            novas = repo.salvar_resultados_web(chamada_id, run_id, c, resp.resultados) if resp.chamada.sucesso else 0
            repo.atualizar_chamada(chamada_id, n_retornados=len(resp.resultados), n_novos=novas)
        logging.info("[%s] ok=%s results=%d new_urls=%d lat=%sms", c.id, resp.chamada.sucesso,
                     len(resp.resultados), novas, resp.chamada.latencia_ms)
        time.sleep(pausa)
