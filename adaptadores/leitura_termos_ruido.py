"""Leituras da analise por termo e da auditoria do pre-filtro (RE7) e do teste barato de combinacoes (RD12). Mistura em
LeituraPainelSQLite: usa self._ler(sql, args), que devolve [] se a tabela ou a view nao existe. So le; nunca grava; nenhuma
chamada externa. Os calculos ficam em `dominio/analise_termos.py` (e em `dominio/refinamento_busca.py`); aqui so se le o banco
e se monta a entrada.

Tudo e SUGESTAO PARA AVALIACAO DO PESQUISADOR: nada e aplicado. `elegivel` e opiniao do modelo sobre o escopo (tabela
`triagem_escopo`, veredito atual = maior (criado_em, id) por (fonte, item_id, uf)), nao achado confirmado."""
import json

from dominio import analise_termos as at
from dominio import refinamento_busca as refino

_TE_ATUAL = ("SELECT te.* FROM triagem_escopo te WHERE te.fonte = ? AND te.id = "
             "(SELECT x.id FROM triagem_escopo x WHERE x.fonte = ? AND x.item_id = te.item_id AND x.uf = te.uf "
             "ORDER BY x.criado_em DESC, x.id DESC LIMIT 1)")
_COLUNAS_REFINO = ("item_id, uf, status, valido, termos_consulta, categoria_motivo, termo_gerador, sinal_negativo, "
                   "dominio_tematico, escopo_geografico")
LIMITE_PADRAO_CANDIDATAS = 20          # candidatas por termo devolvidas na simulacao
LIMITE_PADRAO_NEGATIVOS = 30           # operadores negativos devolvidos
LIMITE_PADRAO_MATRIZ = 40              # linhas da matriz termo x motivo x area
GANHO_MINIMO_NEGATIVO = 3              # excluidos que um operador seguro precisa tirar para contar como "de ganho relevante"


def _i(v):
    return int(v) if v is not None else 0


class LeituraTermosRuido:
    """Leituras de RE7 e RD12. Mistura em LeituraPainelSQLite (usa self._ler)."""

    def _tem_triagem_escopo_termos(self):
        return bool(self._ler("SELECT 1 AS x FROM sqlite_master WHERE type='table' AND name='triagem_escopo'"))

    def _termos_conhecidos(self):
        """{texto da consulta com espacos colapsados: {termo_id, query, idioma, grupo}} de `v_termos`."""
        return {" ".join(str(t["query"] or "").split()): t
                for t in self._ler("SELECT termo_id, query, idioma, grupo FROM v_termos")}

    # ---------- RE7a. auditoria do pre-filtro (web) ----------
    def analise_prefiltro_web(self):
        """Compara os resultados web triados pelo modelo com a decisao de download da coleta principal (a execucao mais
        recente cujo `comando` e `pipeline-uf` e que gravou `selecao_download`; o id nao e fixo no codigo). Os itens sao os
        pares (url, uf); o texto e o titulo e o resumo da busca, como o pre-filtro os viu.

        Devolve o dicionario de `dominio.analise_termos.auditar_prefiltro` mais {run_id, comando, prefiltro (as palavras lidas
        do `config_json` dessa execucao), n_selecao, n_sem_triagem, tem_dados}: `grupos` (selecionados, nao selecionados e cada
        motivo, com `elegivel` e `util` = proporcao {k, n, pct, ic_inf, ic_sup} de Wilson 95%), `limite_por_uf` ({limite, por_uf:
        [{uf, n_candidatos, n_no_limite, n_triados, n_elegiveis_perdidos, n_uteis_perdidos, teto_necessario, downloads_extras}],
        n_elegiveis_perdidos, teto_necessario, curva: [{teto, elegiveis_capturados, uteis_capturados, downloads_extras}]}),
        `desempenho_prefiltro` (por palavra do pre-filtro) e `palavras_candidatas` ([{palavra, n_frente, n_fundo, pct_frente,
        pct_fundo, log_chances, lift, capturados: {n, n_elegivel, elegivel}}]).

        Exemplo (abreviado): {"run_id": "2026...", "grupos": [{"chave": "selecionada", "n": 1080, "n_elegivel": 860, "elegivel":
        {"k": 860, "n": 1080, "pct": 79.6, "ic_inf": 77.1, "ic_sup": 81.9}}, ...], "palavras_candidatas": [{"palavra": "..."}]}.
        Sem a tabela `triagem_escopo` ou sem coleta principal, devolve as mesmas chaves zeradas e `tem_dados` falso."""
        vazio = at.auditar_prefiltro([], ())
        vazio.update({"run_id": None, "comando": "pipeline-uf", "prefiltro": [], "n_selecao": 0, "n_sem_triagem": 0, "tem_dados": False})
        if not self._tem_triagem_escopo_termos():
            return vazio
        run = self._ler("""SELECT e.run_id, json_extract(e.config_json, '$.politica_download') AS politica FROM execucoes e
                           WHERE e.comando = 'pipeline-uf' AND EXISTS (SELECT 1 FROM selecao_download s WHERE s.run_id = e.run_id)
                           ORDER BY e.iniciado_em DESC, e.rowid DESC LIMIT 1""")
        if not run:
            return vazio
        run_id = run[0]["run_id"]
        try:
            politica = json.loads(run[0]["politica"]) if run[0]["politica"] else {}
        except (TypeError, ValueError):
            politica = {}
        prefiltro = [str(p) for p in politica.get("palavras_chave") or []]
        limite = int(politica.get("max_urls_por_uf") or 40)
        selecao = {(l["url_id"], l["uf"]): l for l in self._ler(
            "SELECT url_id, uf, selecionada, motivo FROM selecao_download WHERE run_id = ?", (run_id,))}
        busca = {(l["url_id"], l["uf"]): l for l in self._ler(
            """SELECT url_id, uf, COALESCE(MAX(titulo), '') AS titulo, COALESCE(MAX(snippet), '') AS resumo,
                      MIN(posicao) AS melhor_posicao, COUNT(*) AS n_ocorrencias
               FROM resultados_web WHERE run_id = ? GROUP BY url_id, uf""", (run_id,))}
        triados = self._ler("SELECT item_id, uf, status, valido FROM (" + _TE_ATUAL + ")", ("web", "web"))
        itens, vistos = [], set()
        for t in triados:
            chave = (t["item_id"], t["uf"])
            s, b = selecao.get(chave), busca.get(chave, {})
            vistos.add(chave)
            itens.append({"item_id": t["item_id"], "uf": t["uf"], "status": t["status"], "valido": t["valido"],
                          "selecionada": s["selecionada"] if s else None, "motivo": s["motivo"] if s else None,
                          "titulo": b.get("titulo", ""), "resumo": b.get("resumo", ""),
                          "n_ocorrencias": b.get("n_ocorrencias"), "melhor_posicao": b.get("melhor_posicao")})
        r = at.auditar_prefiltro(itens, prefiltro, limite)
        r.update({"run_id": run_id, "comando": "pipeline-uf", "prefiltro": prefiltro, "n_selecao": len(selecao),
                  "n_sem_triagem": sum(1 for k in selecao if k not in vistos), "tem_dados": bool(itens)})
        return r

    # ---------- RE7b. ruido por termo (artigos) ----------
    def analise_ruido_por_termo(self, protegidos=None, limite_negativos=LIMITE_PADRAO_NEGATIVOS, limite_matriz=LIMITE_PADRAO_MATRIZ):
        """Ficha de ruido de cada termo de busca dos artigos (reaproveita `refinamento_busca.ficha_por_termo`, `matriz_ruido` e
        `avaliar_negativos`) e a tabela "termo -> n -> % elegivel (Wilson) -> principal motivo de ruido -> area tematica do ruido
        -> acao sugerida" (`analise_termos.tabela_por_termo`; a regra da acao vem em cada linha).

        Devolve {n_itens, n_invalidos, n_termos, tem_dados, tabela: [{termo, termo_id, grupo, n, n_elegivel, n_quarentena,
        n_excluido, elegivel: {k, n, pct, ic_inf, ic_sup}, motivo_top, n_motivo_top, dominio_top, n_dominio_top, pct_dominio_top,
        pct_internacional, acao, regra, observacao}], fichas (as de `ficha_por_termo` + termo_id + grupo), matriz: [{termo_gerador,
        categoria_motivo, dominio_tematico, n}], negativos: [operadores de `avaliar_negativos`, os `limite_negativos` primeiros],
        negativos_por_termo: {termo: [{sinal, veredito, ganho, perda_elegivel, seguro_no_termo, ...}]}, n_negativos (todos os
        avaliados), por_veredito: {seguro, arriscado, perigoso: quantos}, n_termos_com_negativo_seguro, n_negativos_seguros_de_ganho (seguros que tirariam
        `ganho_minimo_negativo` ou mais excluidos), ganho_minimo_negativo}.
        `protegidos`: palavras centrais que tornam um operador negativo "perigoso" (padrao: `analise_termos.PALAVRAS_CENTRAIS_PADRAO`).
        Sem a tabela `triagem_escopo`, tudo vazio."""
        vazio = {"n_itens": 0, "n_invalidos": 0, "n_termos": 0, "tem_dados": False, "tabela": [], "fichas": [], "matriz": [],
                 "negativos": [], "negativos_por_termo": {}, "n_negativos": 0,
                 "por_veredito": {v: 0 for v in refino.VEREDITOS}, "n_termos_com_negativo_seguro": 0,
                 "n_negativos_seguros_de_ganho": 0, "ganho_minimo_negativo": GANHO_MINIMO_NEGATIVO}
        if not self._tem_triagem_escopo_termos():
            return vazio
        linhas = self._ler(f"SELECT {_COLUNAS_REFINO} FROM ({_TE_ATUAL})", ("artigo", "artigo"))
        if not linhas:
            return vazio
        conhecidos = self._termos_conhecidos()
        fichas = refino.ficha_por_termo(linhas)
        for f in fichas:
            t = conhecidos.get(" ".join(f["termo"].split()))
            f["termo_id"], f["grupo"] = (t["termo_id"], t["grupo"]) if t else (None, None)
        corpus = self._ler("""SELECT a.artigo_id AS id, '' AS uf, a.titulo, a.snippet AS resumo,
                                     COALESCE(t.decisao = 'incluir' OR t.decisao_texto_completo = 'incluir', 0) AS incluido_humano
                              FROM artigos a LEFT JOIN triagem t ON t.artigo_id = a.artigo_id ORDER BY a.artigo_id""")
        aval = refino.avaliar_negativos(linhas, corpus, at.PALAVRAS_CENTRAIS_PADRAO if protegidos is None else protegidos)
        validas = [l for l in linhas if _i(l["valido"]) == 1]
        return {"n_itens": len(validas), "n_invalidos": len(linhas) - len(validas), "n_termos": len(fichas), "tem_dados": True,
                "tabela": at.tabela_por_termo(fichas), "fichas": fichas, "matriz": refino.matriz_ruido(linhas)[:max(int(limite_matriz), 0)],
                "negativos": aval["negativos"][:max(int(limite_negativos), 0)], "negativos_por_termo": aval["por_termo"],
                "n_negativos": len(aval["negativos"]),
                "por_veredito": {v: sum(1 for n in aval["negativos"] if n["veredito"] == v) for v in refino.VEREDITOS},
                "n_negativos_seguros_de_ganho": sum(1 for n in aval["negativos"]
                                                    if n["veredito"] == "seguro" and n["n_excluidos_atingidos"] >= GANHO_MINIMO_NEGATIVO),
                "ganho_minimo_negativo": GANHO_MINIMO_NEGATIVO,
                "n_termos_com_negativo_seguro": sum(1 for lista in aval["por_termo"].values() if any(x["seguro_no_termo"] for x in lista))}

    # ---------- RD12. simulacao de consulta composta ----------
    def analise_simulacao_contexto(self, termo_id=None, limite=LIMITE_PADRAO_CANDIDATAS):
        """Teste barato de combinacoes, sem credito do Scholar: cada candidata de contexto vira um FILTRO sobre os resultados ja
        guardados do termo (`r_ocorrencias`, titulo e resumo dos artigos, veredito atual da `triagem_escopo`). Candidatas por termo:
        as padrao ("candidatas, nao aprovadas": `analise_termos.CONTEXTOS_PADRAO`, em ingles para termos em ingles, e um grupo OU) e
        as achadas por contraste entre elegiveis e excluidos do termo.

        `termo_id`: so esse termo (None = todos os que tem resultados triados). `limite`: maximo de candidatas devolvidas por termo
        (as de mais ruido removido; `n_candidatas` diz quantas existiam).

        Devolve {tem_dados, n_termos, n_pares, limite_perda, limites: [texto], aviso, termos: [{termo_id, termo, idioma, grupo, n,
        n_elegivel, n_quarentena, n_excluido, elegivel, amostra_pequena, n_candidatas, candidatas: [{id, rotulo, alternativas,
        origem ('padrao' | 'automatica'), aprovada (sempre False), n_passam, retencao_elegivel, ruido_removido, pct_elegivel_resultante
        (cada um {k, n, pct, ic_inf, ic_sup}), perda_elegivel, perda_elegivel_pct, quarentena_removida, perde_muitos_uteis,
        amostra_pequena}]}], agregado: [candidata padrao somada sobre os termos]}. A unidade e o par (termo, artigo).
        Exemplo: o termo T09 com 40 itens, 25 elegiveis: candidata "polícia" -> retencao_elegivel {k: 23, n: 25, pct: 92.0},
        ruido_removido {k: 9, n: 12, pct: 75.0}, perda_elegivel 2, perde_muitos_uteis False."""
        vazio = {"tem_dados": False, "n_termos": 0, "n_pares": 0, "limite_perda": at.LIMITE_PERDA_UTEIS,
                 "limites": list(at.LIMITES_SIMULACAO), "aviso": at.AVISO_PREFILTRO, "termos": [], "agregado": []}
        if not self._tem_triagem_escopo_termos():
            return vazio
        args = (termo_id,) if termo_id else ()
        pares = self._ler(f"""
            SELECT d.termo_id, a.artigo_id AS item_id, a.titulo, a.snippet AS resumo, te.status, te.valido
            FROM (SELECT DISTINCT artigo_id, termo_id FROM r_ocorrencias{' WHERE termo_id = ?' if termo_id else ''}) d
            JOIN artigos a ON a.artigo_id = d.artigo_id
            JOIN triagem_escopo te ON te.id = (SELECT x.id FROM triagem_escopo x
                                               WHERE x.fonte = 'artigo' AND x.item_id = a.artigo_id AND x.uf = ''
                                               ORDER BY x.criado_em DESC, x.id DESC LIMIT 1)
            ORDER BY d.termo_id, a.artigo_id""", args)
        if not pares:
            return vazio
        info = {t["termo_id"]: t for t in self._ler("SELECT termo_id, query, idioma, grupo FROM v_termos")}
        por_termo = {}
        for p in pares:
            por_termo.setdefault(p["termo_id"], []).append(p)
        limite = max(int(limite), 0)
        termos, simulacoes = [], []
        for tid in sorted(por_termo):
            meta = info.get(tid, {})
            itens = por_termo[tid]
            cands = at.candidatas_do_termo(itens, meta.get("query"), meta.get("idioma"))
            sim = at.simular_contextos(itens, cands)
            simulacoes.append(sim)
            if not sim["n"]:
                continue
            termos.append({"termo_id": tid, "termo": meta.get("query"), "idioma": meta.get("idioma"), "grupo": meta.get("grupo"),
                           "n": sim["n"], "n_elegivel": sim["n_elegivel"], "n_quarentena": sim["n_quarentena"],
                           "n_excluido": sim["n_excluido"], "elegivel": sim["elegivel"], "amostra_pequena": sim["amostra_pequena"],
                           "n_candidatas": len(sim["candidatas"]), "candidatas": sim["candidatas"][:limite]})
        return {"tem_dados": bool(termos), "n_termos": len(termos), "n_pares": sum(t["n"] for t in termos),
                "limite_perda": at.LIMITE_PERDA_UTEIS, "limites": list(at.LIMITES_SIMULACAO), "aviso": at.AVISO_PREFILTRO,
                "termos": termos, "agregado": at.agregar_simulacoes(simulacoes)}
