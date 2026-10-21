import logging
import time
from dominio.servicos import chave_filtros_busca, hash_chave
from aplicacao.comum import item_gravado, registrar_falha_apos_chamada, resultados_validos


def executar(repo, bruto, busca, run_id, consultas, perfis, segredos, pausa, limite=None):
    chamadas = repo.chaves_com_chamada(run_id, "busca_web")   # o --limite vale para a execucao inteira, retomadas incluidas
    for c in consultas:
        filtros = perfis[c.perfil]
        chave = hash_chave("busca_web", busca.nome, c.id, chave_filtros_busca(filtros))
        if repo.ja_feito(run_id, chave):
            continue
        if limite and chave not in chamadas and len(chamadas) >= limite:
            break
        resp = busca.buscar(c, filtros)
        try:
            chamadas.add(chave)
            validos = resultados_validos(resp, c.id)
        except BaseException as e:
            # a chamada paga ja respondeu: fica registrada como falha (conta no --limite) e a excecao original segue
            registrar_falha_apos_chamada(repo, bruto, run_id, "busca_web", "consulta_web", c.id, chave, resp.chamada,
                                         segredos, e, "falha_ao_validar", uf=c.uf)
            raise
        with item_gravado(repo, bruto, run_id, "busca_web", "consulta_web", c.id, chave, resp.chamada, segredos,
                          uf=c.uf) as chamada_id:
            novas = repo.salvar_resultados_web(chamada_id, run_id, c, validos) if resp.chamada.sucesso else 0
            repo.atualizar_chamada(chamada_id, n_retornados=len(resp.resultados), n_novos=novas)
        logging.info("[%s] ok=%s results=%d new_urls=%d lat=%sms", c.id, resp.chamada.sucesso,
                     len(resp.resultados), novas, resp.chamada.latencia_ms)
        time.sleep(pausa)
