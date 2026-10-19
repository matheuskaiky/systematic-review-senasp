"""Leituras do painel sobre o banco SQLite. Abre uma conexao somente leitura por consulta e nunca roda o schema."""
import json
import sqlite3
from pathlib import Path

LIMITE_POR_PAGINA = 200
FILTRO_BRASIL = ("sim", "certo", "talvez", "fora", "sem")   # opcoes do filtro `brasil` de /literatura/artigos

# ordem da fila de revisao (secao 17 da especificacao): nao verificados primeiro, depois evidencia que nao confere,
# texto so de snippet, confianca baixa e fonte nao oficial
ORDEM_FILA = ("verificado, COALESCE(evidencia_confere, 0), COALESCE(evidencia_cita_tecnologia, 0), "
              "CASE origem_texto WHEN 'snippet' THEN 0 ELSE 1 END, "
              "CASE confianca WHEN 'baixa' THEN 0 WHEN 'media' THEN 1 ELSE 2 END, "
              "COALESCE(fonte_oficial_final, fonte_oficial, 0), uf, achado_id")


from adaptadores.leitura_analises import LeituraAnalises
from adaptadores.leitura_classificadores import LeituraClassificadores
from adaptadores.leitura_metodologia import LeituraMetodologia
from adaptadores.leitura_solucoes import LeituraSolucoes
from adaptadores.leitura_termos_cobertura import LeituraTermosCobertura
from adaptadores.leitura_termos_ruido import LeituraTermosRuido
from adaptadores.leitura_triagem_escopo import LeituraTriagemEscopo
from dominio.entrada import separar_runs
from dominio.relevancia import NIVEIS, pontuar_relevancia
from dominio.sugestoes import CAMPOS_ACHADO, CAMPOS_ARTIGO, ficha_da_decisao


class LeituraPainelSQLite(LeituraClassificadores, LeituraMetodologia, LeituraTriagemEscopo, LeituraAnalises, LeituraTermosCobertura,
                          LeituraTermosRuido, LeituraSolucoes):
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

    def estado_decisao(self, alvo_tipo, alvo_id):
        """Ficha da decisao de hoje de um achado ou artigo (a mesma que a gravacao confere); None se o item nao existe."""
        if alvo_tipo == "achado":
            l = self._um(f"SELECT {', '.join(CAMPOS_ACHADO)} FROM achados WHERE achado_id=?", (alvo_id,))
            return None if l is None else ficha_da_decisao(tuple(l[c] for c in CAMPOS_ACHADO))
        if self._um("SELECT 1 AS um FROM artigos WHERE artigo_id=?", (alvo_id,)) is None:
            return None
        t = self._um(f"SELECT {', '.join(CAMPOS_ARTIGO)} FROM triagem WHERE artigo_id=?", (alvo_id,))
        return ficha_da_decisao(tuple(t[c] for c in CAMPOS_ARTIGO) if t else (None,) * len(CAMPOS_ARTIGO))

    def _tem_sugestoes(self):
        return bool(self._consulta("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sugestoes'"))

    def sugestoes_abertas(self, alvo_tipo, alvo_id):
        """Sugestoes abertas de um item, na ordem em que foram feitas."""
        if not self._tem_sugestoes():
            return []
        return self._consulta("""SELECT sugestao_id, valor, motivo, autor, criado_em, estado_alvo, valor_alvo FROM sugestoes
                                 WHERE alvo_tipo=? AND alvo_id=? AND situacao='aberta' ORDER BY sugestao_id""", (alvo_tipo, alvo_id))

    def sugestao(self, sugestao_id):
        """Uma sugestao (todas as colunas) ou None."""
        if not self._tem_sugestoes():
            return None
        return self._um("SELECT * FROM sugestoes WHERE sugestao_id=?", (sugestao_id,))

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

    def cidades(self):
        """Cidades que tem achado (so secretarias municipais), para o filtro."""
        return [l["cidade"] for l in self._consulta(
            "SELECT DISTINCT cidade FROM v_achados_revisao WHERE cidade IS NOT NULL ORDER BY cidade")]

    def resumo_ufs(self):
        return self._consulta("SELECT * FROM v_resumo_uf ORDER BY uf")

    # ---------- execucoes e chamadas ----------
    def execucoes(self):
        linhas = self._consulta("""
            SELECT e.run_id, e.comando, e.status, e.iniciado_em, e.finalizado_em, e.run_origem, e.config_hash, e.commit_git,
                   e.no_relatorio, e.motivo_exclusao,
                   (SELECT COUNT(*) FROM chamadas c WHERE c.run_id=e.run_id) AS n_chamadas,
                   (SELECT COUNT(*) FROM chamadas c WHERE c.run_id=e.run_id AND c.sucesso=0) AS n_falhas,
                   (SELECT COALESCE(SUM(custo_usd), 0) FROM chamadas c WHERE c.run_id=e.run_id) AS custo_usd
            FROM execucoes e ORDER BY e.iniciado_em DESC, e.run_id DESC""")
        for l in linhas:
            l["runs_origem"] = separar_runs(l["run_origem"])        # `run_origem` guarda varias, separadas por virgula
        return linhas

    def execucao(self, run_id):
        e = self._um("""SELECT run_id, comando, status, iniciado_em, finalizado_em, run_origem, config_hash, config_json,
                               commit_git, metricas_json, ambiente_json, no_relatorio, motivo_exclusao, excluida_em
                        FROM execucoes WHERE run_id=?""", (run_id,))
        if e is None:
            return None
        e["funil"] = self._um("SELECT * FROM v_funil WHERE run_id=?", (run_id,)) or {}
        e["custos"] = self._consulta("SELECT * FROM v_custos WHERE run_id=? ORDER BY etapa, provedor", (run_id,))
        e["falhas"] = self._consulta("SELECT etapa, provedor, erro, n FROM v_falhas WHERE run_id=? ORDER BY n DESC", (run_id,))
        e["descartes"] = self._consulta("SELECT motivo, n FROM v_descartes WHERE run_id=? ORDER BY n DESC", (run_id,))
        e["saldos"] = self._consulta("SELECT * FROM v_saldos WHERE run_id=? ORDER BY provedor, passada", (run_id,))
        e["retomadas"] = self._consulta("SELECT retomado_em, commit_git FROM execucoes_retomadas WHERE run_id=? ORDER BY retomada_id", (run_id,))
        e["falhas_download"] = self._consulta("""SELECT COALESCE(motivo_falha, 'ok') AS motivo, COUNT(*) AS n FROM paginas
                                                 WHERE run_id=? AND extracao_ok=0 GROUP BY motivo_falha ORDER BY n DESC""", (run_id,))
        e["runs_origem"] = separar_runs(e["run_origem"])
        # `run_origem` guarda varias execucoes separadas por virgula: procura o run_id como um item inteiro da lista
        e["run_destino"] = [l["run_id"] for l in self._consulta(
            "SELECT run_id FROM execucoes WHERE instr(',' || run_origem || ',', ',' || ? || ',') > 0 ORDER BY iniciado_em", (run_id,))]
        return e

    def opcoes_chamadas(self):
        return {"etapas": [l["etapa"] for l in self._consulta("SELECT DISTINCT etapa FROM chamadas ORDER BY etapa")],
                "provedores": [l["provedor"] for l in self._consulta("SELECT DISTINCT provedor FROM chamadas ORDER BY provedor")],
                "runs": [l["run_id"] for l in self._consulta("SELECT run_id FROM execucoes ORDER BY iniciado_em DESC")]}

    def chamadas(self, filtros, pagina=1, por_pagina=50):
        por_pagina = min(max(int(por_pagina), 1), LIMITE_POR_PAGINA)
        cond, args = [], []
        for chave, coluna in (("run", "run_id"), ("etapa", "etapa"), ("provedor", "provedor"), ("uf", "uf")):
            if filtros.get(chave) not in (None, ""):
                cond.append(f"{coluna} = ?")
                args.append(filtros[chave])
        if filtros.get("resultado") in ("ok", "falha"):
            cond.append("sucesso = ?")
            args.append(1 if filtros["resultado"] == "ok" else 0)
        # bloqueios pelo robots.txt: o motivo e o comeco do texto de erro (com ou sem `_apos_redirecionamento`), como na view v_resultado_download
        motivo = {"robots_proibido": "bloqueado_por_robots", "robots_inacessivel": "robots_inacessivel"}.get(filtros.get("resultado"))
        if motivo:
            cond.append("sucesso = 0 AND erro LIKE ?")
            args.append(motivo + "%")
        q = (filtros.get("q") or "").strip()
        if q:
            cond.append("(erro LIKE ? ESCAPE '\\' OR alvo_id LIKE ? ESCAPE '\\')")
            args += ["%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"] * 2
        onde = (" WHERE " + " AND ".join(cond)) if cond else ""
        total = self._um(f"SELECT COUNT(*) AS n FROM chamadas{onde}", args)["n"]
        itens = self._consulta(
            f"""SELECT chamada_id, run_id, etapa, provedor, operacao, alvo_tipo, alvo_id, uf, sucesso, http_status, tentativas,
                       latencia_ms, custo_usd, tokens_entrada, tokens_saida, erro, requisitado_em
                FROM chamadas{onde} ORDER BY chamada_id DESC LIMIT ? OFFSET ?""", args + [por_pagina, (pagina - 1) * por_pagina])
        return {"total": total, "pagina": pagina, "por_pagina": por_pagina, "itens": itens}

    def chamada(self, chamada_id):
        c = self._um("SELECT * FROM chamadas WHERE chamada_id=?", (chamada_id,))
        if c is None:
            return None
        c["classificacao"] = self._um("""SELECT classificacao_id, uf, cidade, origem_texto, texto_truncado, n_chars_enviados, relevante,
                                                json_valido, n_achados, n_achados_invalidos, resposta_texto, prompt_versao
                                         FROM classificacoes WHERE chamada_id=?""", (chamada_id,))
        solucao = "a.nome_solucao, " if self._tem_coluna("achados", "nome_solucao") else ""
        c["achados"] = self._consulta(f"""SELECT {solucao}a.achado_id, a.tecnologia, a.status_reportado, a.confianca, a.evidencia_confere
                                         FROM achados a JOIN classificacoes k ON k.classificacao_id=a.classificacao_id
                                         WHERE k.chamada_id=? ORDER BY a.achado_id""", (chamada_id,)) if c["classificacao"] else []
        c["pagina_baixada"] = self._um("""SELECT pagina_id, url_final, http_status, content_type, n_bytes, truncado, texto_path, n_chars,
                                         extrator, extracao_ok, motivo_falha FROM paginas WHERE chamada_id=?""", (chamada_id,))
        return c

    # ---------- literatura ----------
    _ORDEM_ARTIGOS = "(n_termos + n_bases_manuais) DESC, COALESCE(citacoes, 0) DESC, artigo_id"
    @property
    def _BASE_ARTIGOS(self):
        """Artigos com a triagem humana e, quando existe, o veredito atual da triagem de escopo por LLM (`llm_*`)."""
        juncao, colunas = self.juncao_triagem_escopo_artigos()
        return f"""
        SELECT a.artigo_id, a.titulo, a.ano, a.citacoes, a.link, a.autores_publicacao, a.snippet,
               (SELECT COUNT(DISTINCT o.termo_id) FROM r_ocorrencias o WHERE o.artigo_id=a.artigo_id) AS n_termos,
               (SELECT COUNT(DISTINCT m.base) FROM ocorrencias_manuais m WHERE m.artigo_id=a.artigo_id) AS n_bases_manuais,
               COALESCE(t.decisao, 'pendente') AS decisao, t.motivo, t.revisor, t.revisado_em,
               COALESCE(t.decisao_texto_completo, 'pendente') AS decisao_texto_completo, t.motivo_texto_completo,
               t.confirmado_em_base, t.link_confirmado, {colunas}
        FROM r_artigos a LEFT JOIN triagem t ON t.artigo_id=a.artigo_id {juncao}"""

    @staticmethod
    def _onde_artigos(filtros):
        cond, args = [], []
        if filtros.get("decisao") in ("pendente", "incluir", "excluir"):
            cond.append("decisao = ?")
            args.append(filtros["decisao"])
        llm = filtros.get("llm")
        if llm == "sem_avaliacao":
            cond.append("llm_status IS NULL")
        elif llm in ("elegivel", "quarentena", "excluido"):
            cond.append("llm_status = ?")
            args.append(llm)
        elif llm == "oculto":
            cond.append("llm_oculto = 1")
        elif llm != "todos":                       # padrao: some o que o modelo excluiu, salvo decisao humana (nunca apaga)
            cond.append("llm_oculto = 0")
        if filtros.get("multi") == "1":
            cond.append("(n_termos + n_bases_manuais) >= 2")
        if filtros.get("termo"):
            cond.append("artigo_id IN (SELECT artigo_id FROM r_ocorrencias WHERE termo_id = ?)")
            args.append(filtros["termo"])
        if filtros.get("base"):
            cond.append("artigo_id IN (SELECT artigo_id FROM ocorrencias_manuais WHERE base = ?)")
            args.append(filtros["base"])
        for chave, op in (("ano_de", ">="), ("ano_ate", "<=")):
            if str(filtros.get(chave, "")).isdigit():
                cond.append(f"ano {op} ?")
                args.append(int(filtros[chave]))
        q = (filtros.get("q") or "").strip()
        if q:
            cond.append("(titulo LIKE ? ESCAPE '\\' OR snippet LIKE ? ESCAPE '\\' OR autores_publicacao LIKE ? ESCAPE '\\')")
            args += ["%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"] * 3
        return (" WHERE " + " AND ".join(cond)) if cond else "", args

    @staticmethod
    def _pontuar(item):
        item["relevancia"] = pontuar_relevancia(item.get("titulo"), item.get("snippet"), item.get("autores_publicacao"), item.get("link"))
        return item

    def _artigos_em_memoria(self, filtros, onde, args):
        """Todos os artigos dos filtros SQL, na ordem da triagem, ja com a relevancia, filtrados por `rel` e, se pedido,
        reordenados por relevancia (ordenacao estavel: empates mantem a ordem da triagem). A relevancia e calculada em Python,
        por isso este caminho le tudo e pagina na memoria; o acervo e de alguns milhares de artigos."""
        linhas = self._consulta(f"SELECT * FROM ({self._BASE_ARTIGOS}){onde} ORDER BY {self._ORDEM_ARTIGOS}", args)
        itens = [self._pontuar(l) for l in linhas]
        if filtros.get("rel") in NIVEIS:
            itens = [i for i in itens if i["relevancia"]["nivel"] == filtros["rel"]]
        if filtros.get("brasil") in FILTRO_BRASIL:
            itens = [i for i in itens if self.relacao_com_o_brasil(i)[filtros["brasil"]]]
        if filtros.get("ordem") == "relevancia":
            itens.sort(key=lambda i: -i["relevancia"]["pontos"])
        return itens

    @staticmethod
    def relacao_com_o_brasil(item):
        """Dois indicios independentes de que o artigo tem a ver com o Brasil: o TEXTO cita o Brasil (marcadores no titulo, resumo,
        autores ou link: `dominio/relevancia.py`) e a IA (veredito atual da triagem de escopo, so se valido) avaliou
        `escopo_geografico = brasil`. As categorias abaixo NAO se sobrepoem, exceto `sim` (a uniao de `certo` e `talvez`):
        certo = os dois indicios; talvez = so um; fora = a IA diz internacional e o texto nao cita o Brasil;
        sem = nenhum indicio e a IA nao disse internacional (indeterminado ou sem avaliacao).
        Devolve o valor de cada opcao do filtro `brasil` para este item."""
        texto = bool(item["relevancia"]["brasil"])
        ia = item.get("llm_escopo") == "brasil"
        fora = item.get("llm_escopo") == "internacional" and not texto
        return {"sim": texto or ia, "certo": texto and ia, "talvez": texto != ia, "fora": fora, "sem": not texto and not ia and not fora}

    @staticmethod
    def _precisa_de_pontuacao(filtros):
        return filtros.get("rel") in NIVEIS or filtros.get("brasil") in FILTRO_BRASIL or filtros.get("ordem") == "relevancia"

    def artigos(self, filtros, pagina=1, por_pagina=50):
        por_pagina = min(max(int(por_pagina), 1), LIMITE_POR_PAGINA)
        onde, args = self._onde_artigos(filtros)
        if self._precisa_de_pontuacao(filtros):
            todos = self._artigos_em_memoria(filtros, onde, args)
            inicio = (pagina - 1) * por_pagina
            return {"total": len(todos), "pagina": pagina, "por_pagina": por_pagina, "itens": todos[inicio:inicio + por_pagina],
                    "ocultos_llm": self._n_ocultos_llm(filtros)}
        base = f"SELECT * FROM ({self._BASE_ARTIGOS}){onde}"
        total = self._um(f"SELECT COUNT(*) AS n FROM ({base})", args)["n"]
        itens = self._consulta(f"{base} ORDER BY {self._ORDEM_ARTIGOS} LIMIT ? OFFSET ?", args + [por_pagina, (pagina - 1) * por_pagina])
        return {"total": total, "pagina": pagina, "por_pagina": por_pagina, "itens": [self._pontuar(i) for i in itens],
                "ocultos_llm": self._n_ocultos_llm(filtros)}

    def _n_ocultos_llm(self, filtros):
        """Quantos artigos os mesmos filtros mostrariam a mais se os excluidos pelo modelo aparecessem (0 se o filtro ja os mostra)."""
        if filtros.get("llm") in ("todos", "sem_avaliacao", "elegivel", "quarentena", "excluido", "oculto"):
            return 0
        f = {**filtros, "llm": "oculto"}
        onde, args = self._onde_artigos(f)
        if self._precisa_de_pontuacao(f):
            return len(self._artigos_em_memoria(f, onde, args))
        return self._um(f"SELECT COUNT(*) AS n FROM (SELECT * FROM ({self._BASE_ARTIGOS}){onde})", args)["n"]

    def ids_fila_triagem(self, filtros):
        onde, args = self._onde_artigos({**filtros, "decisao": "pendente"})
        if self._precisa_de_pontuacao(filtros):
            return [i["artigo_id"] for i in self._artigos_em_memoria(filtros, onde, args)]
        return [l["artigo_id"] for l in self._consulta(
            f"SELECT artigo_id FROM (SELECT * FROM ({self._BASE_ARTIGOS}){onde}) ORDER BY {self._ORDEM_ARTIGOS}", args)]

    def contagem_relevancia(self):
        """Quantos artigos do relatorio caem em cada nivel de relevancia (alta, media, baixa), sem os ocultos pelo modelo."""
        contagem = {n: 0 for n in NIVEIS}
        for l in self._consulta(f"SELECT titulo, snippet, autores_publicacao, link FROM ({self._BASE_ARTIGOS}) WHERE llm_oculto = 0"):
            contagem[pontuar_relevancia(l["titulo"], l["snippet"], l["autores_publicacao"], l["link"])["nivel"]] += 1
        return contagem

    def artigo(self, artigo_id):
        a = self._um(f"SELECT * FROM ({self._BASE_ARTIGOS}) WHERE artigo_id=?", (artigo_id,))
        if a is None:
            return None
        self._pontuar(a)
        a["llm"] = self.veredito_artigo(artigo_id)
        a["ocorrencias"] = self._consulta("""SELECT o.termo_id, o.run_id, o.posicao, o.citacoes_no_momento, c.pagina
                                             FROM r_ocorrencias o LEFT JOIN chamadas c ON c.chamada_id=o.chamada_id
                                             WHERE o.artigo_id=? ORDER BY o.termo_id, o.ocorrencia_id""", (artigo_id,))
        a["manuais"] = self._consulta("""SELECT base, termo_id, data_busca, posicao FROM ocorrencias_manuais
                                         WHERE artigo_id=? ORDER BY base, termo_id""", (artigo_id,))
        a["historico"] = self._consulta("""SELECT revisor, decisao, motivo, decisao_texto_completo, motivo_texto_completo, importado_em,
                                                  independente FROM triagem_revisoes WHERE artigo_id=? ORDER BY revisao_id DESC""", (artigo_id,))
        return a

    def contagem_triagem(self):
        """Triagem humana dos artigos que aparecem por padrao; `ocultos_llm` = excluidos pelo modelo e ainda sem decisao humana."""
        d = self._um(f"""SELECT COUNT(*) AS total,
                                COALESCE(SUM(decisao='incluir'), 0) AS incluidos, COALESCE(SUM(decisao='excluir'), 0) AS excluidos,
                                COALESCE(SUM(decisao='pendente'), 0) AS pendentes
                         FROM (SELECT decisao FROM ({self._BASE_ARTIGOS}) WHERE llm_oculto = 0)""")
        d["ocultos_llm"] = self._um(f"SELECT COALESCE(SUM(llm_oculto), 0) AS n FROM ({self._BASE_ARTIGOS})")["n"]
        return d

    def literatura(self):
        return {
            "por_ano": self._consulta("SELECT ano, n_artigos FROM v_artigos_por_ano WHERE ano IS NOT NULL ORDER BY ano"),
            "sem_ano": (self._um("SELECT COALESCE(SUM(n_artigos), 0) AS n FROM v_artigos_por_ano WHERE ano IS NULL") or {}).get("n", 0),
            "por_termo": self._consulta("""SELECT termo_id, COUNT(DISTINCT artigo_id) AS n_artigos FROM r_ocorrencias
                                           GROUP BY termo_id ORDER BY termo_id"""),
            "sobreposicao": self._consulta("SELECT termo_a, termo_b, n_em_comum FROM v_sobreposicao_termos"),
            "mais_citados": self._consulta("""SELECT artigo_id, titulo, ano, citacoes FROM r_artigos WHERE citacoes IS NOT NULL
                                              ORDER BY citacoes DESC, artigo_id LIMIT 10"""),
            "manuais": self._consulta("SELECT * FROM v_manuais_resumo ORDER BY base"),
            "n_artigos": self._um(f"SELECT COUNT(*) AS n FROM ({self._BASE_ARTIGOS}) WHERE llm_oculto = 0")["n"],
            # mesma regra do filtro `multi=1` da lista: termos distintos do Scholar + bases manuais distintas >= 2
            "n_multi": self._um(f"""SELECT COUNT(*) AS n FROM ({self._BASE_ARTIGOS})
                                    WHERE llm_oculto = 0 AND (n_termos + n_bases_manuais) >= 2""")["n"],
            "n_ocultos_llm": self._um(f"SELECT COALESCE(SUM(llm_oculto), 0) AS n FROM ({self._BASE_ARTIGOS})")["n"],
            "sem_citacoes": self._um("SELECT COUNT(*) AS n FROM r_artigos WHERE citacoes IS NULL")["n"],
        }

    def prisma(self):
        return {"caixas": self._consulta("SELECT ordem, fase, metrica, valor FROM v_prisma ORDER BY ordem"),
                "motivos": self._consulta("SELECT etapa, motivo, n FROM v_motivos_exclusao"),
                "n_buscas_manuais": self._um("SELECT COUNT(*) AS n FROM buscas_manuais")["n"],
                "n_buscas_scholar": self._um("SELECT COUNT(*) AS n FROM r_chamadas WHERE etapa='busca_academica'")["n"]}

    def historico_triagem_existe(self, artigo_id):
        return self._um("SELECT 1 AS x FROM triagem_revisoes WHERE artigo_id=? LIMIT 1", (artigo_id,)) is not None

    # ---------- achados ----------
    def _tem_solucao_na_fila(self):
        """O banco aberto ja tem `nome_solucao` na view da fila? (banco anterior ao prompt v4: a busca ignora o campo.)"""
        return any(l["name"] == "nome_solucao" for l in self._consulta("PRAGMA table_info(v_achados_revisao)"))

    @staticmethod
    def _onde(filtros, com_solucao=False):
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
        simples("cidade", "cidade")
        if filtros.get("esfera") == "estadual":
            cond.append("cidade IS NULL")
        elif filtros.get("esfera") == "municipal":
            cond.append("cidade IS NOT NULL")
        if filtros.get("evidencia") in ("0", "1"):
            cond.append("COALESCE(evidencia_confere, 0) = ?")
            args.append(int(filtros["evidencia"]))
        if filtros.get("oficial") in ("0", "1"):
            cond.append("COALESCE(fonte_oficial_final, fonte_oficial, 0) = ?")
            args.append(int(filtros["oficial"]))
        if filtros.get("solucao") == "nomeada":                 # so achados em que o modelo citou o nome proprio da solucao
            cond.append("(nome_solucao IS NOT NULL AND TRIM(nome_solucao) <> '')" if com_solucao else "0")   # banco antigo: nenhuma tem nome
        pares = filtros.get("solucao_pares")                    # entidade (RC23): todas as grafias brutas (nome, uf) reunidas sob um nome canonico
        if pares is not None:
            if com_solucao and pares:
                cond.append("(" + " OR ".join("(nome_solucao = ? AND uf = ?)" for _ in pares) + ")")
                args += [x for par in pares for x in par]
            else:
                cond.append("0")                                # nome desconhecido, ou banco antigo sem a coluna: nenhum achado
        v = filtros.get("verificacao")
        if v == "pendente":
            cond.append("verificado = 0")
        elif v == "confirmado":
            cond.append("verificado = 1 AND COALESCE(status_final,'') <> 'descartado'")
        elif v == "descartado":
            cond.append("verificado = 1 AND status_final = 'descartado'")
        q = (filtros.get("q") or "").strip()
        if q:
            campos = ["evidencia", "fornecedor", "url"] + (["nome_solucao"] if com_solucao else [])
            cond.append("(" + " OR ".join(f"{c} LIKE ? ESCAPE '\\'" for c in campos) + ")")
            padrao = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            args += [padrao] * len(campos)
        return (" WHERE " + " AND ".join(cond)) if cond else "", args

    def achados(self, filtros, pagina=1, por_pagina=50):
        por_pagina = min(max(int(por_pagina), 1), LIMITE_POR_PAGINA)
        pagina = max(int(pagina), 1)
        onde, args = self._onde(filtros, self._tem_solucao_na_fila())
        total = self._um(f"SELECT COUNT(*) AS n FROM v_achados_revisao{onde}", args)["n"]
        itens = self._consulta(
            f"SELECT * FROM v_achados_revisao{onde} ORDER BY {ORDEM_FILA} LIMIT ? OFFSET ?",
            args + [por_pagina, (pagina - 1) * por_pagina])
        return {"total": total, "pagina": pagina, "por_pagina": por_pagina, "itens": itens}

    def ids_fila_revisao(self, filtros):
        onde, args = self._onde({**filtros, "verificacao": "pendente"}, self._tem_solucao_na_fila())
        return [l["achado_id"] for l in self._consulta(
            f"SELECT achado_id FROM v_achados_revisao{onde} ORDER BY {ORDEM_FILA}", args)]

    def achado(self, achado_id):
        solucao = "a.nome_solucao, " if self._tem_coluna("achados", "nome_solucao") else ""
        a = self._um(f"""
            SELECT {solucao}a.achado_id, a.uf, a.tecnologia, a.status_reportado, a.fornecedor, a.menciona_lgpd, a.evidencia,
                   a.evidencia_confere, a.confianca, a.confianca_original, a.evidencia_cita_tecnologia,
                   a.evidencia_cita_lgpd, a.verificado, a.status_final, a.verificado_por, a.verificado_em, a.observacao,
                   k.classificacao_id, k.run_id, k.url_id, k.pagina_id, k.origem_texto, k.texto_truncado,
                   k.n_chars_enviados, k.classificador, k.prompt_versao, k.cidade, k.relevante, k.n_achados,
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
        a.setdefault("nome_solucao", None)
        # classificacao vigente do par (url, uf): se nao e a deste achado, ele foi substituido por uma classificacao mais recente
        # (ou melhor: ver r_classificacoes no schema). Continua abrindo, com aviso.
        vigente = self._um("SELECT classificacao_id, run_id, prompt_versao, origem_texto FROM r_classificacoes WHERE url_id=? AND uf=?",
                           (a["url_id"], a["uf"]))
        a["substituido_por"] = None
        if vigente and a["no_relatorio"] == 1 and vigente["classificacao_id"] != a["classificacao_id"]:
            vigente["achados"] = self._consulta(
                "SELECT achado_id, tecnologia, status_reportado, verificado, status_final FROM achados WHERE classificacao_id=? ORDER BY achado_id",
                (vigente["classificacao_id"],))
            a["substituido_por"] = vigente
        a["outros_achados_da_pagina"] = self._consulta(
            """SELECT achado_id, tecnologia, status_reportado, verificado, status_final FROM achados
               WHERE classificacao_id=? AND achado_id<>? ORDER BY achado_id""", (a["classificacao_id"], achado_id))
        return a

    def historico_achado(self, achado_id):
        # a revisao independente (cega, so para o kappa) nao aparece aqui: um revisor nao ve a decisao do outro antes do consenso
        sql = """SELECT verificado_por, status_final, observacao, importado_em, desfeita
                 FROM achados_revisoes WHERE achado_id=? {} ORDER BY revisao_id DESC"""
        try:
            return self._consulta(sql.format("AND independente=0"), (achado_id,))
        except sqlite3.OperationalError:          # banco ainda sem a coluna `independente` (aberto so para leitura, antes da migracao)
            return self._consulta(sql.format(""), (achado_id,))

    def tem_decisao_para_desfazer(self, achado_id):
        """Ha uma decisao do painel nao desfeita E o achado ainda esta como ela o deixou (senao o desfazer seria recusado)."""
        l = self._um("""SELECT posterior_json FROM achados_revisoes WHERE achado_id=? AND anterior_json IS NOT NULL
                        AND posterior_json IS NOT NULL AND desfeita=0 ORDER BY revisao_id DESC LIMIT 1""", (achado_id,))
        atual = self._um("""SELECT verificado, status_final, verificado_por, verificado_em, observacao FROM achados
                            WHERE achado_id=?""", (achado_id,))
        return l is not None and atual is not None and json.loads(l["posterior_json"]) == atual

    def atividade_por_revisor(self) -> list[dict]:
        """Contabiliza eventos de decisão em achados e triagem agrupados por revisor e dia."""
        sql = """
            SELECT revisor, dia, SUM(achados) AS achados, SUM(artigos) AS artigos FROM (
              SELECT TRIM(verificado_por) AS revisor, substr(importado_em, 1, 10) AS dia, COUNT(*) AS achados, 0 AS artigos
              FROM achados_revisoes WHERE desfeita = 0 AND TRIM(COALESCE(verificado_por, '')) <> '' GROUP BY 1, 2
              UNION ALL
              SELECT TRIM(revisor), substr(importado_em, 1, 10), 0, COUNT(*)
              FROM triagem_revisoes WHERE TRIM(COALESCE(revisor, '')) <> '' GROUP BY 1, 2)
            GROUP BY revisor, dia ORDER BY dia DESC, revisor
        """
        return self._consulta(sql)

    def titulos_artigos(self, ids):
        """Titulo de cada artigo da lista (janela da fila lateral)."""
        if not ids:
            return {}
        marcas = ",".join("?" * len(ids))
        return {l["artigo_id"]: l["titulo"] for l in self._consulta(
            f"SELECT artigo_id, titulo FROM r_artigos WHERE artigo_id IN ({marcas})", tuple(ids))}

    def resumo_achados(self, ids):
        """Tecnologia, UF e cidade de cada achado da lista (janela da fila lateral)."""
        if not ids:
            return {}
        marcas = ",".join("?" * len(ids))
        return {l["achado_id"]: l for l in self._consulta(
            f"SELECT achado_id, tecnologia, uf, cidade FROM v_achados_revisao WHERE achado_id IN ({marcas})", tuple(ids))}

