from dominio.entrada import separar_runs

_EXECUCOES_CLASSIFICAR = """
    SELECT e.run_id, e.status, e.iniciado_em, e.finalizado_em, e.run_origem, e.no_relatorio, e.motivo_exclusao,
           (SELECT COUNT(*) FROM classificacoes k WHERE k.run_id=e.run_id) AS n_classificacoes,
           (SELECT group_concat(DISTINCT k.classificador) FROM classificacoes k WHERE k.run_id=e.run_id) AS classificador,
           (SELECT group_concat(DISTINCT k.prompt_versao) FROM classificacoes k WHERE k.run_id=e.run_id) AS prompt_versao
    FROM execucoes e WHERE e.comando='classificar'"""


class LeituraClassificadores:
    """Leituras da pagina Classificadores. Mistura em LeituraPainelSQLite: usa self._consulta(sql, args) e self._um(sql, args)."""

    def execucoes_classificacao(self):
        """Execucoes do comando `classificar` (dentro ou fora do relatorio), da mais recente para a mais antiga."""
        return [self._com_origens(l) for l in
                self._consulta(_EXECUCOES_CLASSIFICAR + " ORDER BY e.iniciado_em DESC, e.rowid DESC")]

    def execucao_classificacao(self, run_id):
        return self._com_origens(self._um(_EXECUCOES_CLASSIFICAR + " AND e.run_id=?", (run_id,)))

    @staticmethod
    def _com_origens(linha):
        """`run_origem` guarda varias execucoes separadas por virgula: acrescenta a lista `runs_origem`."""
        if linha is not None:
            linha["runs_origem"] = separar_runs(linha["run_origem"])
        return linha

    def classificacoes_para_comparar(self, run_id):
        """Uma linha por classificacao da execucao, com o custo e os tokens da chamada que a produziu."""
        return self._consulta("""
            SELECT k.classificacao_id, k.url_id, k.uf, k.relevante, k.json_valido, k.n_achados,
                   u.url_original AS url, c.custo_usd, c.tokens_entrada, c.tokens_saida
            FROM classificacoes k
            JOIN urls u ON u.url_id = k.url_id
            LEFT JOIN chamadas c ON c.chamada_id = k.chamada_id
            WHERE k.run_id = ? ORDER BY k.classificacao_id""", (run_id,))

    def achados_para_comparar(self, run_id):
        return self._consulta("""
            SELECT a.achado_id, a.classificacao_id, a.tecnologia, a.status_reportado, a.confianca, a.evidencia_confere
            FROM achados a JOIN classificacoes k ON k.classificacao_id = a.classificacao_id
            WHERE k.run_id = ? ORDER BY a.achado_id""", (run_id,))
