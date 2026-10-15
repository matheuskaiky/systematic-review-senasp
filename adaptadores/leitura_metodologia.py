class LeituraMetodologia:
    """Leituras da pagina Metodologia e do relatorio estatico. Mistura em LeituraPainelSQLite: usa self._consulta e self._um.
    So le; todos os numeros vem das views r_* (execucoes marcadas para o relatorio), exceto o gasto real e a lista de execucoes."""

    def _provedores(self, etapa):
        return [l["provedor"] for l in self._consulta(
            "SELECT DISTINCT provedor FROM r_chamadas WHERE etapa=? ORDER BY provedor", (etapa,))]

    def _runs(self, etapa):
        return [l["run_id"] for l in self._consulta(
            """SELECT c.run_id FROM r_chamadas c JOIN execucoes e ON e.run_id=c.run_id WHERE c.etapa=?
               GROUP BY c.run_id ORDER BY MIN(e.iniciado_em), c.run_id""", (etapa,))]

    def fatos_metodologia(self, n_ufs=27):
        """Dicionario simples com os fatos que o texto de metodologia descreve. Nada e calculado alem de contagens:
        o que nao existe vem como 0, None ou lista vazia (o texto diz que falta, nunca inventa)."""
        execucoes = self._consulta("""SELECT run_id, comando, status, iniciado_em, finalizado_em, config_hash, commit_git,
                                             no_relatorio, motivo_exclusao
                                      FROM execucoes ORDER BY iniciado_em, run_id""")
        retomadas = self._consulta("""SELECT run_id, COUNT(*) AS n FROM execucoes_retomadas GROUP BY run_id ORDER BY run_id""")

        # ---------- busca academica ----------
        ac = self._um("""SELECT COUNT(*) AS n_requisicoes, COALESCE(SUM(sucesso), 0) AS n_ok,
                                COUNT(DISTINCT alvo_id) AS n_termos,
                                COALESCE(SUM(CASE WHEN sucesso=1 THEN n_retornados END), 0) AS n_retornados,
                                MIN(requisitado_em) AS primeira, MAX(requisitado_em) AS ultima
                         FROM r_chamadas WHERE etapa='busca_academica'""")
        ac["n_falhas"] = ac["n_requisicoes"] - ac["n_ok"]
        ac["provedores"] = self._provedores("busca_academica")
        ac["run_ids"] = self._runs("busca_academica")
        ac["termos"] = self._consulta("""
            SELECT c.alvo_id AS termo_id, t.query, t.idioma, COUNT(*) AS n_requisicoes,
                   (SELECT COUNT(DISTINCT o.artigo_id) FROM r_ocorrencias o WHERE o.termo_id=c.alvo_id) AS n_artigos
            FROM r_chamadas c LEFT JOIN v_termos t ON t.termo_id=c.alvo_id
            WHERE c.etapa='busca_academica' GROUP BY c.alvo_id ORDER BY c.alvo_id""")
        ac["n_artigos_scholar"] = self._um("SELECT COUNT(DISTINCT artigo_id) AS n FROM r_ocorrencias")["n"]

        # ---------- buscas manuais ----------
        importados = {l["base"]: l["n"] for l in self._consulta(
            "SELECT base, COUNT(DISTINCT artigo_id) AS n FROM ocorrencias_manuais GROUP BY base")}
        manuais = self._consulta("""
            SELECT base, COUNT(*) AS n_buscas, SUM(n_resultados) AS total_resultados, SUM(n_apos_filtro) AS total_apos_filtro,
                   SUM(n_selecionados) AS total_selecionados, MIN(NULLIF(data_busca, '')) AS primeira, MAX(NULLIF(data_busca, '')) AS ultima
            FROM buscas_manuais GROUP BY base ORDER BY base""")
        vistas = set()
        for m in manuais:
            m["n_artigos_importados"] = importados.get(m["base"], 0)
            vistas.add(m["base"])
        manuais += [{"base": b, "n_buscas": 0, "total_resultados": None, "total_apos_filtro": None, "total_selecionados": None,
                     "primeira": None, "ultima": None, "n_artigos_importados": n} for b, n in sorted(importados.items()) if b not in vistas]

        tri = self.contagem_triagem()
        prisma = {l["ordem"]: l["valor"] for l in self._consulta("SELECT ordem, valor FROM v_prisma")}
        literatura = {"n_artigos": self._um("SELECT COUNT(*) AS n FROM r_artigos")["n"],
                      "n_artigos_manuais": self._um("SELECT COUNT(DISTINCT artigo_id) AS n FROM ocorrencias_manuais")["n"],
                      "triagem": tri, "prisma": prisma}

        # ---------- busca web e download ----------
        web = self._um("""SELECT COUNT(*) AS n_requisicoes, COALESCE(SUM(sucesso), 0) AS n_ok,
                                 MIN(requisitado_em) AS primeira, MAX(requisitado_em) AS ultima
                          FROM r_chamadas WHERE etapa='busca_web'""")
        web["n_falhas"] = web["n_requisicoes"] - web["n_ok"]
        web["provedores"] = self._provedores("busca_web")
        web["run_ids"] = self._runs("busca_web")
        web["modelos_consulta"] = [l["modelo_id"] for l in self._consulta(
            """SELECT DISTINCT substr(consulta_id, 1, instr(consulta_id || '-', '-') - 1) AS modelo_id
               FROM r_resultados_web ORDER BY modelo_id""")]
        web["urls_oficiais"] = self._um("""SELECT COUNT(DISTINCT r.url_id) AS n FROM r_resultados_web r
                                           JOIN urls u ON u.url_id=r.url_id WHERE u.fonte_oficial=1""")["n"]
        web["descartes"] = self._consulta("""SELECT COALESCE(motivo, 'sem_motivo') AS motivo, COUNT(*) AS n FROM r_selecao_download
                                             WHERE selecionada=0 GROUP BY 1 ORDER BY n DESC, motivo""")
        web["funil"] = self.funil()

        # ---------- classificacao ----------
        classificacao = {
            "provedores": self._provedores("classificacao"),
            "run_ids": self._runs("classificacao"),
            "classificadores": self._consulta("""
                SELECT k.classificador, k.prompt_versao, COUNT(DISTINCT k.classificacao_id) AS n_classificacoes,
                       COUNT(DISTINCT CASE WHEN k.json_valido=1 THEN k.classificacao_id END) AS n_json_valido,
                       COUNT(a.achado_id) AS n_achados, COALESCE(SUM(a.evidencia_confere=1), 0) AS n_evidencia_ok
                FROM r_classificacoes k LEFT JOIN achados a ON a.classificacao_id=k.classificacao_id
                GROUP BY k.classificador, k.prompt_versao ORDER BY n_classificacoes DESC, k.classificador, k.prompt_versao"""),
            "n_so_snippet": self._um("SELECT COUNT(*) AS n FROM r_classificacoes WHERE origem_texto='snippet'")["n"],
            "n_invalidas": self._um("SELECT COUNT(*) AS n FROM v_classificacoes_invalidas")["n"],
            "n_fora_vocabulario": self._um("SELECT COUNT(*) AS n FROM r_achados_descartados")["n"],
        }

        # ---------- achados, verificacao humana, UFs ----------
        achados = self._um("""
            SELECT COUNT(*) AS total, COALESCE(SUM(evidencia_confere=1), 0) AS evidencia_ok,
                   COALESCE(SUM(verificado), 0) AS verificados,
                   COALESCE(SUM(verificado=1 AND COALESCE(status_final, '')<>'descartado'), 0) AS confirmados,
                   COALESCE(SUM(verificado=1 AND status_final='descartado'), 0) AS descartados,
                   COALESCE(SUM(verificado=0 AND COALESCE(evidencia_confere, 0)=0), 0) AS pendentes_sem_evidencia,
                   COUNT(DISTINCT CASE WHEN verificado=1 THEN NULLIF(TRIM(verificado_por), '') END) AS n_revisores
            FROM r_achados""")
        achados["confirmados_por_tecnologia"] = self._consulta("""
            SELECT tecnologia, COUNT(*) AS n FROM v_secretarias_confirmadas GROUP BY tecnologia ORDER BY n DESC, tecnologia""")
        # secao 16 da especificacao; o total de UFs vem do chamador (a especificacao fixa 27)
        ufs = self._um("""SELECT COALESCE(SUM(CASE WHEN n_confirmados > 0 THEN 1 ELSE 0 END), 0) AS uf_confirmada,
                                 COALESCE(SUM(CASE WHEN n_achados > 0 AND n_confirmados = 0 THEN 1 ELSE 0 END), 0) AS uf_so_classificado,
                                 ? - COUNT(*) AS uf_sem_achados
                          FROM v_resumo_uf""", (int(n_ufs),))
        ufs["n_ufs"] = int(n_ufs)
        ufs["confirmadas"] = [l["uf"] for l in self._consulta("SELECT uf FROM v_resumo_uf WHERE n_confirmados > 0 ORDER BY uf")]
        municipal = self._um("""SELECT COUNT(*) AS n_cidades, COALESCE(SUM(n_achados), 0) AS n_achados,
                                       COALESCE(SUM(n_confirmados), 0) AS n_confirmados FROM v_resumo_municipio""")
        municipal["cidades"] = self._consulta("SELECT uf, cidade, n_achados, n_confirmados FROM v_resumo_municipio ORDER BY uf, cidade")

        # ---------- custos ----------
        custos = {
            "por_etapa": self._consulta("""
                SELECT etapa, provedor, COUNT(*) AS n_chamadas, COALESCE(SUM(sucesso), 0) AS n_ok, COUNT(custo_usd) AS n_com_custo,
                       ROUND(COALESCE(SUM(custo_usd), 0), 4) AS custo_usd,
                       COALESCE(SUM(sucesso=1 AND custo_usd IS NULL), 0) AS n_ok_sem_custo
                FROM r_chamadas GROUP BY etapa, provedor ORDER BY etapa, provedor"""),
            "gasto_real": self._consulta("""SELECT provedor, no_relatorio, n_chamadas, n_ok, custo_registrado_usd, n_ok_sem_custo
                                            FROM v_gasto_real ORDER BY provedor, no_relatorio"""),
        }
        return {"execucoes": execucoes, "retomadas": retomadas, "academico": ac, "manuais": manuais, "literatura": literatura,
                "web": web, "classificacao": classificacao, "achados": achados, "ufs": ufs, "municipal": municipal,
                "custos": custos}
