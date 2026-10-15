"""Leituras do painel sobre o banco SQLite. Abre uma conexao somente leitura por consulta e nunca roda o schema."""
import sqlite3
from pathlib import Path

LIMITE_POR_PAGINA = 200

# ordem da fila de revisao (secao 17 da especificacao): nao verificados primeiro, depois evidencia que nao confere,
# texto so de snippet, confianca baixa e fonte nao oficial
ORDEM_FILA = ("verificado, COALESCE(evidencia_confere, 0), COALESCE(evidencia_cita_tecnologia, 0), "
              "CASE origem_texto WHEN 'snippet' THEN 0 ELSE 1 END, "
              "CASE confianca WHEN 'baixa' THEN 0 WHEN 'media' THEN 1 ELSE 2 END, "
              "COALESCE(fonte_oficial_final, fonte_oficial, 0), uf, achado_id")


class LeituraPainelSQLite:
    def __init__(self, caminho):
        self._caminho = Path(caminho)

    def existe(self):
        return self._caminho.exists()

    def _consulta(self, sql, args=()):
        conn = sqlite3.connect(f"file:{self._caminho.as_posix()}?mode=ro", uri=True)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout = 5000")
            return [dict(l) for l in conn.execute(sql, args).fetchall()]
        finally:
            conn.close()

    def _um(self, sql, args=()):
        linhas = self._consulta(sql, args)
        return linhas[0] if linhas else None

    # ---------- visao geral ----------
    def funil(self):
        return self._um("""
            SELECT
              (SELECT COUNT(*) FROM r_chamadas WHERE etapa='busca_web' AND sucesso=1) AS consultas_web,
              (SELECT COUNT(*) FROM r_resultados_web) AS resultados,
              (SELECT COUNT(DISTINCT url_id) FROM r_resultados_web) AS urls_unicas,
              (SELECT COUNT(*) FROM selecao_download s JOIN execucoes e ON e.run_id=s.run_id
                WHERE e.no_relatorio=1 AND s.selecionada=1) AS selecionadas,
              (SELECT COUNT(*) FROM paginas p JOIN execucoes e ON e.run_id=p.run_id WHERE e.no_relatorio=1) AS paginas,
              (SELECT COUNT(*) FROM paginas p JOIN execucoes e ON e.run_id=p.run_id
                WHERE e.no_relatorio=1 AND p.extracao_ok=1) AS paginas_com_texto,
              (SELECT COUNT(*) FROM r_classificacoes) AS classificacoes,
              (SELECT COALESCE(SUM(relevante), 0) FROM r_classificacoes) AS relevantes,
              (SELECT COUNT(*) FROM r_achados) AS achados,
              (SELECT COALESCE(SUM(verificado), 0) FROM r_achados) AS verificados,
              (SELECT COUNT(*) FROM v_secretarias_confirmadas) AS confirmados""")

    def resumo_geral(self):
        d = self._um("""
            SELECT
              (SELECT COUNT(*) FROM r_achados) AS achados,
              (SELECT COALESCE(SUM(evidencia_confere), 0) FROM r_achados) AS evidencia_ok,
              (SELECT COUNT(DISTINCT uf) FROM r_achados) AS ufs_com_achados,
              (SELECT COUNT(DISTINCT uf) FROM v_secretarias_confirmadas) AS ufs_confirmadas,
              (SELECT COALESCE(SUM(custo_usd), 0) FROM chamadas) AS custo_total_usd,
              (SELECT COUNT(*) FROM chamadas WHERE sucesso=0) AS chamadas_com_falha,
              (SELECT COUNT(*) FROM artigos) AS artigos,
              (SELECT COUNT(*) FROM triagem WHERE decisao<>'pendente') AS artigos_triados,
              (SELECT COUNT(*) FROM execucoes WHERE status<>'concluida') AS execucoes_nao_concluidas""")
        d.update(self.funil())
        return d

    def contagem_revisao(self):
        return self._um("""
            SELECT COUNT(*) AS total, COALESCE(SUM(verificado), 0) AS verificados,
                   COALESCE(SUM(CASE WHEN verificado=1 AND COALESCE(status_final,'')<>'descartado' THEN 1 ELSE 0 END), 0) AS confirmados,
                   COALESCE(SUM(CASE WHEN verificado=1 AND status_final='descartado' THEN 1 ELSE 0 END), 0) AS descartados,
                   COALESCE(SUM(CASE WHEN verificado=0 AND COALESCE(evidencia_confere,0)=0 THEN 1 ELSE 0 END), 0) AS pendentes_sem_evidencia
            FROM v_achados_revisao""")

    def execucoes_recentes(self, n=5):
        return self._consulta("""
            SELECT e.run_id, e.comando, e.status, e.iniciado_em, e.finalizado_em, e.no_relatorio,
                   (SELECT COALESCE(SUM(custo_usd), 0) FROM chamadas c WHERE c.run_id=e.run_id) AS custo_usd
            FROM execucoes e ORDER BY e.iniciado_em DESC, e.run_id DESC LIMIT ?""", (min(max(int(n), 1), 50),))

    def resumo_ufs(self):
        return self._consulta("SELECT * FROM v_resumo_uf ORDER BY uf")

    # ---------- achados ----------
    @staticmethod
    def _onde(filtros):
        cond, args = [], []

        def simples(chave, coluna):
            if filtros.get(chave) not in (None, ""):
                cond.append(f"{coluna} = ?")
                args.append(filtros[chave])

        simples("uf", "uf")
        simples("tecnologia", "tecnologia")
        simples("status", "status_reportado")
        simples("confianca", "confianca")
        simples("origem", "origem_texto")
        if filtros.get("evidencia") in ("0", "1"):
            cond.append("COALESCE(evidencia_confere, 0) = ?")
            args.append(int(filtros["evidencia"]))
        if filtros.get("oficial") in ("0", "1"):
            cond.append("COALESCE(fonte_oficial_final, fonte_oficial, 0) = ?")
            args.append(int(filtros["oficial"]))
        v = filtros.get("verificacao")
        if v == "pendente":
            cond.append("verificado = 0")
        elif v == "confirmado":
            cond.append("verificado = 1 AND COALESCE(status_final,'') <> 'descartado'")
        elif v == "descartado":
            cond.append("verificado = 1 AND status_final = 'descartado'")
        q = (filtros.get("q") or "").strip()
        if q:
            cond.append("(evidencia LIKE ? ESCAPE '\\' OR fornecedor LIKE ? ESCAPE '\\' OR url LIKE ? ESCAPE '\\')")
            padrao = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            args += [padrao] * 3
        return (" WHERE " + " AND ".join(cond)) if cond else "", args

    def achados(self, filtros, pagina=1, por_pagina=50):
        por_pagina = min(max(int(por_pagina), 1), LIMITE_POR_PAGINA)
        pagina = max(int(pagina), 1)
        onde, args = self._onde(filtros)
        total = self._um(f"SELECT COUNT(*) AS n FROM v_achados_revisao{onde}", args)["n"]
        itens = self._consulta(
            f"SELECT * FROM v_achados_revisao{onde} ORDER BY {ORDEM_FILA} LIMIT ? OFFSET ?",
            args + [por_pagina, (pagina - 1) * por_pagina])
        return {"total": total, "pagina": pagina, "por_pagina": por_pagina, "itens": itens}

    def ids_fila_revisao(self, filtros):
        onde, args = self._onde({**filtros, "verificacao": "pendente"})
        return [l["achado_id"] for l in self._consulta(
            f"SELECT achado_id FROM v_achados_revisao{onde} ORDER BY {ORDEM_FILA}", args)]

    def achado(self, achado_id):
        a = self._um("""
            SELECT a.achado_id, a.uf, a.tecnologia, a.status_reportado, a.fornecedor, a.menciona_lgpd, a.evidencia,
                   a.evidencia_confere, a.confianca, a.confianca_original, a.evidencia_cita_tecnologia,
                   a.evidencia_cita_lgpd, a.verificado, a.status_final, a.verificado_por, a.verificado_em, a.observacao,
                   k.classificacao_id, k.run_id, k.url_id, k.pagina_id, k.origem_texto, k.texto_truncado,
                   k.n_chars_enviados, k.classificador, k.prompt_versao, k.relevante, k.n_achados,
                   u.url_original AS url, u.dominio, u.fonte_oficial,
                   p.url_final, p.texto_path, p.extracao_ok, p.dominio_final, p.fonte_oficial_final, p.http_status,
                   e.no_relatorio, e.config_hash
            FROM achados a
            JOIN classificacoes k ON k.classificacao_id=a.classificacao_id
            JOIN urls u ON u.url_id=k.url_id
            LEFT JOIN paginas p ON p.pagina_id=k.pagina_id
            JOIN execucoes e ON e.run_id=k.run_id
            WHERE a.achado_id=?""", (achado_id,))
        if a is None:
            return None
        origem = self._um("""SELECT titulo, snippet FROM resultados_web WHERE url_id=? AND uf=?
                             ORDER BY resultado_id DESC LIMIT 1""", (a["url_id"], a["uf"])) or {}
        a["titulo"], a["snippet"] = origem.get("titulo"), origem.get("snippet")
        a["outros_achados_da_pagina"] = self._consulta(
            """SELECT achado_id, tecnologia, status_reportado, verificado, status_final FROM achados
               WHERE classificacao_id=? AND achado_id<>? ORDER BY achado_id""", (a["classificacao_id"], achado_id))
        return a

    def historico_achado(self, achado_id):
        return self._consulta("""SELECT verificado_por, status_final, observacao, importado_em, desfeita
                                 FROM achados_revisoes WHERE achado_id=? ORDER BY revisao_id DESC""", (achado_id,))

    def tem_decisao_para_desfazer(self, achado_id):
        return self._um("""SELECT 1 AS x FROM achados_revisoes WHERE achado_id=? AND anterior_json IS NOT NULL
                           AND desfeita=0 LIMIT 1""", (achado_id,)) is not None
