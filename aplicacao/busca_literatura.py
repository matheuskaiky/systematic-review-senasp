"""Busca de literatura cientifica e cinzenta na web (D103 a D106): um pedido por consulta de cada conjunto, sem UF nem
tecnologia; cada resultado guarda o conjunto e a consulta que o trouxe."""
import logging
import time
from dominio.modelos import ConsultaWeb
from dominio.servicos import chave_filtros_busca, hash_chave
from aplicacao.comum import item_gravado, registrar_falha_apos_chamada, resultados_validos


def executar(repo, bruto, busca, run_id, conjuntos, filtros, segredos, pausa, limite=None):
    """`conjuntos`: lista de (nome do conjunto, termos), na ordem em que as consultas sao feitas."""
    chamadas = repo.chaves_com_chamada(run_id, "busca_literatura")   # o --limite vale para a execucao inteira
    texto_filtros = chave_filtros_busca(filtros)
    for conjunto, termos in conjuntos:
        for t in termos:
            chave = hash_chave("busca_literatura", busca.nome, t.id, texto_filtros)
            if repo.ja_feito(run_id, chave):
                continue
            if limite and chave not in chamadas and len(chamadas) >= limite:
                return
            c = ConsultaWeb(t.id, t.query, t.idioma, "", "", t.id, "literatura")
            resp = busca.buscar(c, filtros)
            try:
                chamadas.add(chave)
                validos = resultados_validos(resp, t.id)
            except BaseException as e:
                # a chamada paga ja respondeu: fica registrada como falha (conta no --limite) e a excecao original segue
                registrar_falha_apos_chamada(repo, bruto, run_id, "busca_literatura", "consulta_literatura", t.id, chave,
                                             resp.chamada, segredos, e, "falha_ao_validar")
                raise
            with item_gravado(repo, bruto, run_id, "busca_literatura", "consulta_literatura", t.id, chave, resp.chamada,
                              segredos) as chamada_id:
                novas = repo.salvar_referencias_web(chamada_id, run_id, conjunto, t.id, validos) if resp.chamada.sucesso else 0
                repo.atualizar_chamada(chamada_id, n_retornados=len(resp.resultados), n_novos=novas)
            logging.info("[%s %s] ok=%s results=%d new_refs=%d lat=%sms", conjunto, t.id, resp.chamada.sucesso,
                         len(resp.resultados), novas, resp.chamada.latencia_ms)
            time.sleep(pausa)
