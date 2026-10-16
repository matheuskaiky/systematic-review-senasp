"""Leituras da triagem de escopo feita por LLM (tabela `triagem_escopo`). Mistura em LeituraPainelSQLite: usa
self._consulta(sql, args) e self._um(sql, args). So le; nunca grava. Toda leitura e defensiva: em um banco antigo, sem a
tabela, devolve resultados vazios em vez de falhar.

O veredito ATUAL de um item e a linha de maior `id` para (fonte, item_id, uf). Por padrao vale a ultima linha de cada item,
venha de que execucao vier; com `run` so contam as linhas daquela execucao.

Para `fonte = 'web'`, `item_id` e o `url_id` (a pagina e o titulo/resumo vem do resultado de busca mais recente da UF)."""
from dominio.refinamento_busca import STATUS, termos_da_linha
from dominio.relevancia import pontuar_relevancia

FONTES = ("artigo", "web")
MAX_POR_PAGINA = 200
_COLUNAS = ("id", "run_id", "chamada_id", "fonte", "item_id", "uf", "provedor", "termos_consulta", "status", "status_bruto",
            "confianca", "categoria_motivo", "justificativa", "termo_gerador", "sinal_negativo", "dominio_tematico",
            "escopo_geografico", "tipo_documento", "valido", "problemas", "prompt_versao", "criado_em")
_LISTA = ", ".join(f"te.{c}" for c in _COLUNAS)


def oculto_por_padrao(linha):
    """Excluido pelo modelo (e a conferencia automatica passou): some das listas por padrao, mas nunca do banco."""
    return linha.get("status") == "excluido" and int(linha.get("valido") if linha.get("valido") is not None else 1) == 1


class LeituraTriagemEscopo:
    def tem_triagem_escopo(self):
        return self._um("SELECT 1 AS x FROM sqlite_master WHERE type='table' AND name='triagem_escopo'") is not None

    @staticmethod
    def _onde_atual(fonte, run=None):
        """Condicao SQL (sobre `te`) das linhas que valem: a mais recente por item, ou todas as da execucao `run`."""
        if run:
            return "te.fonte = ? AND te.run_id = ?", [fonte, run]
        return ("te.fonte = ? AND te.id IN (SELECT MAX(id) FROM triagem_escopo WHERE fonte = ? GROUP BY item_id, uf)", [fonte, fonte])

    # ---------- execucoes ----------
    def execucoes_triagem_escopo(self):
        """Execucoes que gravaram vereditos: quantas linhas, de que fonte, versao do prompt e custo das chamadas (lotes)."""
        if not self.tem_triagem_escopo():
            return []
        return self._consulta("""
            SELECT te.run_id, COUNT(*) AS n_linhas, COALESCE(SUM(1 - te.valido), 0) AS n_invalidos,
                   group_concat(DISTINCT te.fonte) AS fontes, group_concat(DISTINCT te.prompt_versao) AS prompt_versao,
                   MAX(te.criado_em) AS criado_em, e.iniciado_em, e.status AS status_execucao, e.no_relatorio,
                   (SELECT SUM(c.custo_usd) FROM chamadas c WHERE c.chamada_id IN
                      (SELECT DISTINCT x.chamada_id FROM triagem_escopo x WHERE x.run_id = te.run_id)) AS custo_usd
            FROM triagem_escopo te LEFT JOIN execucoes e ON e.run_id = te.run_id
            GROUP BY te.run_id ORDER BY MAX(te.id) DESC""")

    def fontes_com_triagem_escopo(self):
        if not self.tem_triagem_escopo():
            return {}
        # itens distintos (o veredito atual de cada um), nao as linhas gravadas: pilotos e repeticoes inflariam a conta
        return {l["fonte"]: l["n"] for l in self._consulta(
            "SELECT te.fonte, COUNT(*) AS n FROM triagem_escopo te WHERE te.id IN "
            "(SELECT MAX(id) FROM triagem_escopo GROUP BY fonte, item_id, uf) GROUP BY te.fonte")}

    # ---------- vereditos ----------
    def veredictos(self, fonte, run=None):
        """Todos os vereditos atuais da fonte, so com as colunas da tabela (sem o texto dos itens), do mais antigo ao mais novo."""
        if fonte not in FONTES or not self.tem_triagem_escopo():
            return []
        onde, args = self._onde_atual(fonte, run)
        return self._consulta(f"SELECT {_LISTA} FROM triagem_escopo te WHERE {onde} ORDER BY te.id", args)

    def resumo_triagem_escopo(self, fonte, run=None):
        """Contagens do que esta valendo: por status, motivo, escopo geografico e area tematica (so linhas validas), as
        invalidas a parte, quantas exclusoes foram rebaixadas pela regra de seguranca e o custo das chamadas dos lotes."""
        vazio = {"n_total": 0, "n_validos": 0, "n_invalidos": 0, "n_rebaixados": 0, "por_status": {s: 0 for s in STATUS},
                 "por_categoria": {}, "por_escopo": {}, "por_dominio": {}, "por_confianca": {}, "custo_usd": None, "n_chamadas": 0}
        if fonte not in FONTES or not self.tem_triagem_escopo():
            return vazio
        onde, args = self._onde_atual(fonte, run)

        def contar(coluna, valido=True):
            filtro = " AND te.valido = 1" if valido else ""
            return {l["k"]: l["n"] for l in self._consulta(
                f"SELECT te.{coluna} AS k, COUNT(*) AS n FROM triagem_escopo te WHERE {onde}{filtro} AND te.{coluna} IS NOT NULL "
                f"GROUP BY te.{coluna} ORDER BY n DESC, k", args)}

        t = self._um(f"""SELECT COUNT(*) AS n, COALESCE(SUM(te.valido = 1), 0) AS validos,
                                COALESCE(SUM(te.status_bruto = 'excluido' AND te.status <> 'excluido'), 0) AS rebaixados
                         FROM triagem_escopo te WHERE {onde}""", args)
        custo = self._um(f"""SELECT SUM(c.custo_usd) AS custo, COUNT(*) AS n FROM chamadas c WHERE c.chamada_id IN
                             (SELECT DISTINCT te.chamada_id FROM triagem_escopo te WHERE {onde} AND te.chamada_id IS NOT NULL)""", args)
        por_status = {s: 0 for s in STATUS}
        por_status.update(contar("status"))
        return {"n_total": t["n"], "n_validos": t["validos"], "n_invalidos": t["n"] - t["validos"], "n_rebaixados": t["rebaixados"],
                "por_status": por_status, "por_categoria": contar("categoria_motivo"), "por_escopo": contar("escopo_geografico"),
                "por_dominio": contar("dominio_tematico"), "por_confianca": contar("confianca"),
                "custo_usd": custo["custo"] if custo and custo["n"] else None, "n_chamadas": custo["n"] if custo else 0}

    # ---------- corpus para a validacao dos operadores negativos ----------
    def corpus_triagem_escopo(self, fonte):
        """Todos os itens da fonte (com ou sem veredito): id, uf, titulo, resumo e se a pessoa ja decidiu que o item serve
        (artigo: triagem humana `incluir`, em titulo/resumo ou texto completo; web: achado verificado e nao descartado)."""
        if fonte == "artigo":
            return self._consulta("""
                SELECT a.artigo_id AS id, '' AS uf, a.titulo, a.snippet AS resumo,
                       COALESCE(t.decisao = 'incluir' OR t.decisao_texto_completo = 'incluir', 0) AS incluido_humano
                FROM artigos a LEFT JOIN triagem t ON t.artigo_id = a.artigo_id ORDER BY a.artigo_id""")
        if fonte == "web":
            return self._consulta("""
                SELECT r.url_id AS id, r.uf, r.titulo, r.snippet AS resumo,
                       EXISTS (SELECT 1 FROM achados a JOIN classificacoes k ON k.classificacao_id = a.classificacao_id
                               WHERE k.url_id = r.url_id AND k.uf = r.uf AND a.verificado = 1
                                 AND COALESCE(a.status_final, '') <> 'descartado') AS incluido_humano
                FROM resultados_web r WHERE r.resultado_id IN (SELECT MAX(resultado_id) FROM resultados_web GROUP BY url_id, uf)
                ORDER BY r.url_id, r.uf""")
        return []

    # ---------- lista paginada ----------
    @staticmethod
    def _filtrar(linhas, filtros):
        """Filtros da lista, em Python (o termo esta num JSON). Sem `status` informado, a lista mostra elegivel e quarentena e
        os excluidos pelo modelo ficam de fora (so `status=excluido` ou `status=todos` os mostram). Devolve (mostradas, n_ocultas)."""
        def passa(l):
            for chave in ("categoria_motivo", "dominio_tematico", "escopo_geografico", "confianca"):
                if filtros.get(chave) and l.get(chave) != filtros[chave]:
                    return False
            if filtros.get("valido") in ("0", "1") and int(l["valido"]) != int(filtros["valido"]):
                return False
            if filtros.get("termo") and filtros["termo"] not in termos_da_linha(l):
                return False
            return True

        base = [l for l in linhas if passa(l)]
        status = filtros.get("status")
        if status in STATUS:
            return [l for l in base if l["status"] == status], 0
        if status == "todos":
            return base, 0
        mostradas = [l for l in base if not oculto_por_padrao(l)]
        return mostradas, len(base) - len(mostradas)

    def itens_triagem_escopo(self, fonte, filtros, pagina=1, por_pagina=50, run=None):
        """Pagina da lista de itens com veredito, ja com o texto do item. O mais ruidoso primeiro (excluido, quarentena,
        elegivel) e, dentro do status, a ordem de gravacao. `ocultos` = quantos excluidos pelo modelo o filtro padrao escondeu."""
        por_pagina = min(max(int(por_pagina), 1), MAX_POR_PAGINA)
        pagina = max(int(pagina), 1)
        linhas, ocultos = self._filtrar(self.veredictos(fonte, run), filtros)
        ordem = {"excluido": 0, "quarentena": 1, "elegivel": 2}
        linhas.sort(key=lambda l: (ordem.get(l["status"], 3), l["id"]))
        inicio = (pagina - 1) * por_pagina
        fatia = linhas[inicio:inicio + por_pagina]
        dados = self._dados_dos_itens(fonte, fatia)
        itens = [{**l, **dados.get((l["item_id"], l["uf"]), {"titulo": None, "resumo": None, "link": None})} for l in fatia]
        return {"total": len(linhas), "pagina": pagina, "por_pagina": por_pagina, "itens": itens, "ocultos": ocultos}

    def _dados_dos_itens(self, fonte, linhas):
        ids = sorted({l["item_id"] for l in linhas})
        if not ids:
            return {}
        marcas = ",".join("?" * len(ids))
        if fonte == "artigo":
            out = {}
            for a in self._consulta(f"""
                    SELECT a.artigo_id, a.titulo, a.snippet AS resumo, a.ano, a.link, a.autores_publicacao,
                           COALESCE(t.decisao, 'pendente') AS decisao
                    FROM artigos a LEFT JOIN triagem t ON t.artigo_id = a.artigo_id WHERE a.artigo_id IN ({marcas})""", ids):
                a["relevancia"] = pontuar_relevancia(a["titulo"], a["resumo"], a["autores_publicacao"], a["link"])
                out[(a["artigo_id"], "")] = a
            return out
        return {(r["url_id"], r["uf"]): {"titulo": r["titulo"], "resumo": r["snippet"], "link": r["url"], "tecnologia": r["tecnologia"]}
                for r in self._consulta(f"""
                    SELECT r.url_id, r.uf, r.titulo, r.snippet, r.tecnologia, u.url_original AS url
                    FROM resultados_web r JOIN urls u ON u.url_id = r.url_id
                    WHERE r.url_id IN ({marcas}) AND r.resultado_id IN
                      (SELECT MAX(resultado_id) FROM resultados_web WHERE url_id IN ({marcas}) GROUP BY url_id, uf)""", ids + ids)}

    def itens_por_chaves(self, fonte, chaves):
        """Titulo e link de itens `(item_id, uf)`, para listar o dano colateral com ligacao ao item."""
        linhas = [{"item_id": i, "uf": uf} for i, uf in chaves]
        return self._dados_dos_itens(fonte, linhas) if linhas else {}

    def opcoes_triagem_escopo(self, fonte, run=None):
        """Valores que existem nos vereditos atuais, para os filtros: motivos, areas, escopos, confiancas e termos (por frequencia)."""
        linhas = self.veredictos(fonte, run)
        termos = {}
        for l in linhas:
            for t in termos_da_linha(l):
                termos[t] = termos.get(t, 0) + 1
        return {"categorias": sorted({l["categoria_motivo"] for l in linhas if l["categoria_motivo"]}),
                "dominios": sorted({l["dominio_tematico"] for l in linhas if l["dominio_tematico"]}),
                "escopos": sorted({l["escopo_geografico"] for l in linhas if l["escopo_geografico"]}),
                "confiancas": sorted({l["confianca"] for l in linhas if l["confianca"]}),
                "termos": sorted(termos, key=lambda t: (-termos[t], t))}

    # ---------- um artigo ----------
    def veredito_artigo(self, artigo_id):
        """O veredito atual de um artigo (ultima linha, de qualquer execucao), ou None."""
        if not self.tem_triagem_escopo():
            return None
        return self._um(f"""SELECT {_LISTA} FROM triagem_escopo te WHERE te.fonte = 'artigo' AND te.item_id = ? AND te.uf = ''
                            ORDER BY te.id DESC LIMIT 1""", (artigo_id,))

    # ---------- artigos na lista e na fila: o que esta oculto pelo modelo ----------
    def juncao_triagem_escopo_artigos(self):
        """(JOIN, colunas) que trazem o veredito atual de cada artigo `a` para as consultas de artigos. `llm_oculto` e 1 quando o
        modelo excluiu o artigo (conferencia valida) E nenhuma pessoa decidiu sobre ele: decisao humana sempre vence."""
        if not self.tem_triagem_escopo():
            return "", ("NULL AS llm_status, NULL AS llm_categoria, NULL AS llm_valido, NULL AS llm_justificativa, NULL AS llm_escopo, 0 AS llm_oculto")
        return (
            "LEFT JOIN triagem_escopo te ON te.id = (SELECT MAX(x.id) FROM triagem_escopo x "
            "WHERE x.fonte = 'artigo' AND x.item_id = a.artigo_id AND x.uf = '')",
            "te.status AS llm_status, te.categoria_motivo AS llm_categoria, te.valido AS llm_valido, "
            "te.justificativa AS llm_justificativa, "
            "CASE WHEN te.valido = 1 THEN te.escopo_geografico END AS llm_escopo, "
            "COALESCE(te.status = 'excluido' AND te.valido = 1 AND COALESCE(t.decisao, 'pendente') = 'pendente', 0) AS llm_oculto")
