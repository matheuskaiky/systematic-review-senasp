import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from dominio.modelos import CandidatoDownload, ItemClassificacao
from dominio.servicos import (normalizar_url, dominio_de, eh_oficial, chave_dedup_titulo, palavras_chave_tecnologia,
                              evidencia_cita_termo, evidencia_cita_lgpd)
from infra.util import agora


def _v(x):
    return None if pd.isna(x) else x


def _int(x):
    return None if pd.isna(x) else int(x)


# colunas acrescentadas depois da primeira versao do schema: bancos antigos as recebem ao abrir
_COLUNAS_NOVAS = {
    "execucoes": {"ambiente_json": "TEXT", "no_relatorio": "INTEGER NOT NULL DEFAULT 1", "motivo_exclusao": "TEXT",
                  "excluida_em": "TEXT"},
    "paginas": {"dominio_final": "TEXT", "fonte_oficial_final": "INTEGER"},
    "selecao_download": {"auditoria": "INTEGER NOT NULL DEFAULT 0"},
    "achados": {"confianca_original": "TEXT", "evidencia_cita_tecnologia": "INTEGER", "evidencia_cita_lgpd": "INTEGER"},
    "triagem": {"decisao_texto_completo": "TEXT", "motivo_texto_completo": "TEXT"},
    "triagem_revisoes": {"independente": "INTEGER NOT NULL DEFAULT 0"},
}


class RepositorioSQLite:
    def __init__(self, caminho):
        caminho = Path(caminho)
        caminho.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(caminho)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript((Path(__file__).parent / "schema.sql").read_text(encoding="utf-8"))
        self._garantir_colunas()

    def _garantir_colunas(self):
        for tabela, colunas in _COLUNAS_NOVAS.items():
            existentes = {l["name"] for l in self.conn.execute(f"PRAGMA table_info({tabela})")}
            for coluna, tipo in colunas.items():
                if coluna not in existentes:
                    self.conn.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo}")
        # paginas gravadas antes de existir o dominio final: preenche a partir de url_final
        for linha in self.conn.execute("SELECT pagina_id, url_final FROM paginas WHERE dominio_final IS NULL AND url_final IS NOT NULL").fetchall():
            dom = dominio_de(linha["url_final"])
            self.conn.execute("UPDATE paginas SET dominio_final=?, fonte_oficial_final=? WHERE pagina_id=?",
                              (dom, int(eh_oficial(dom)), linha["pagina_id"]))
        self._preencher_checagens_de_evidencia()
        self.conn.commit()

    def _preencher_checagens_de_evidencia(self):
        """Achados gravados antes das checagens de evidencia: calcula a partir da evidencia guardada e do vocabulario
        da propria execucao (config_json). Determinístico, sem LLM."""
        configs = {}
        for l in self.conn.execute(
                """SELECT a.achado_id, a.tecnologia, a.evidencia, k.run_id FROM achados a
                   JOIN classificacoes k ON k.classificacao_id=a.classificacao_id
                   WHERE a.evidencia_cita_tecnologia IS NULL OR a.evidencia_cita_lgpd IS NULL""").fetchall():
            if l["run_id"] not in configs:
                bruto = self.conn.execute("SELECT config_json FROM execucoes WHERE run_id=?", (l["run_id"],)).fetchone()
                try:
                    configs[l["run_id"]] = json.loads(bruto[0]).get("tecnologias") or {}
                except (TypeError, ValueError):
                    configs[l["run_id"]] = {}
            rotulo = configs[l["run_id"]].get(l["tecnologia"])
            cita = int(evidencia_cita_termo(l["evidencia"], palavras_chave_tecnologia(rotulo))) if rotulo else None
            self.conn.execute("UPDATE achados SET evidencia_cita_tecnologia=?, evidencia_cita_lgpd=? WHERE achado_id=?",
                              (cita, int(evidencia_cita_lgpd(l["evidencia"])), l["achado_id"]))

    def contar_falhas(self, run_id, chave):
        """Quantas chamadas com essa chave de idempotencia falharam nesta execucao."""
        return self.conn.execute("SELECT COUNT(*) FROM chamadas WHERE run_id=? AND chave_idempotencia=? AND sucesso=0",
                                 (run_id, chave)).fetchone()[0]

    def definir_no_relatorio(self, run_id, no_relatorio, motivo=None):
        """Marca uma execucao como dentro (1) ou fora (0) das views agregadas do relatorio. Nada e apagado."""
        if not self.conn.execute("SELECT 1 FROM execucoes WHERE run_id=?", (run_id,)).fetchone():
            raise SystemExit(f"Execução não encontrada: {run_id}")
        self.conn.execute("UPDATE execucoes SET no_relatorio=?, motivo_exclusao=?, excluida_em=? WHERE run_id=?",
                          (int(bool(no_relatorio)), None if no_relatorio else motivo, None if no_relatorio else agora(), run_id))
        self.conn.commit()

    # ---------- utilities ----------
    def _inserir(self, tabela, **c):
        cols = ", ".join(c)
        marcas = ", ".join("?" for _ in c)
        return self.conn.execute(f"INSERT INTO {tabela} ({cols}) VALUES ({marcas})", tuple(c.values())).lastrowid

    def confirmar(self):
        self.conn.commit()

    # ---------- run ----------
    def iniciar_execucao(self, comando, config_hash, config_json, commit_git, retomar=None, run_origem=None,
                         ambiente_json=None):
        # C5: a execucao indicada em --de precisa existir
        if run_origem and not self.conn.execute(
                "SELECT 1 FROM execucoes WHERE run_id=?", (run_origem,)).fetchone():
            raise SystemExit(f"Execução indicada em --de não encontrada: {run_origem}")
        if retomar:
            linha = self.conn.execute("SELECT config_hash FROM execucoes WHERE run_id=?", (retomar,)).fetchone()
            if not linha:
                raise SystemExit(f"run_id not found: {retomar}")
            if linha["config_hash"] != config_hash:
                raise SystemExit("The configuration has changed since that run. Start a new one (use --de to reuse data).")
            self.conn.execute("UPDATE execucoes SET status='em_andamento' WHERE run_id=?", (retomar,))
            if run_origem:                    # sem --de na retomada, preserva o valor guardado
                self.conn.execute("UPDATE execucoes SET run_origem=? WHERE run_id=?", (run_origem, retomar))
            # o codigo e o ambiente da retomada podem ser outros: ficam registrados, sem apagar os da execucao original
            self._inserir("execucoes_retomadas", run_id=retomar, retomado_em=agora(), commit_git=commit_git,
                          ambiente_json=ambiente_json)
            self.conn.commit()
            return retomar
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]     # UTC, como `agora()`
        self._inserir("execucoes", run_id=run_id, iniciado_em=agora(), comando=comando,
                      config_hash=config_hash, config_json=config_json, commit_git=commit_git,
                      run_origem=run_origem, ambiente_json=ambiente_json)
        self.conn.commit()
        return run_id

    def obter_run_origem(self, run_id):
        """C5: run_origem guardado para a execucao (None se nao houver)."""
        linha = self.conn.execute("SELECT run_origem FROM execucoes WHERE run_id=?", (run_id,)).fetchone()
        return linha["run_origem"] if linha else None

    def _resumo(self, run_id):
        def q(sql):
            return self.conn.execute(sql, (run_id,)).fetchone()[0]
        return {
            "chamadas": q("SELECT COUNT(*) FROM chamadas WHERE run_id=?"),
            "sucesso": q("SELECT COALESCE(SUM(sucesso),0) FROM chamadas WHERE run_id=?"),
            "falhas": q("SELECT COUNT(*)-COALESCE(SUM(sucesso),0) FROM chamadas WHERE run_id=?"),
            "tokens_entrada": q("SELECT COALESCE(SUM(tokens_entrada),0) FROM chamadas WHERE run_id=?"),
            "tokens_saida": q("SELECT COALESCE(SUM(tokens_saida),0) FROM chamadas WHERE run_id=?"),
            "custo_usd": q("SELECT COALESCE(SUM(custo_usd),0) FROM chamadas WHERE run_id=?"),
            "latencia_media_ms": q("SELECT ROUND(AVG(latencia_ms)) FROM chamadas WHERE run_id=?"),
        }

    def finalizar_execucao(self, run_id, status):
        self.conn.execute("UPDATE execucoes SET finalizado_em=?, status=?, metricas_json=? WHERE run_id=?",
                          (agora(), status, json.dumps(self._resumo(run_id)), run_id))
        self.conn.commit()

    def registrar_saldo(self, run_id, provedor, momento, valor):
        self._inserir("saldos", run_id=run_id, provedor=provedor, momento=momento, valor=valor, registrado_em=agora())
        self.conn.commit()

    def registrar_metrica(self, run_id, chave, valor):
        self.conn.execute("INSERT OR REPLACE INTO metricas_run (run_id, chave, valor) VALUES (?,?,?)",
                          (run_id, chave, valor))

    # ---------- calls ----------
    def ja_feito(self, run_id, chave):
        return self.conn.execute("SELECT 1 FROM chamadas WHERE run_id=? AND chave_idempotencia=? AND sucesso=1",
                                 (run_id, chave)).fetchone() is not None

    def resultado_chamada(self, run_id, chave):
        """C8: resultado guardado de uma chamada ja concluida (sucesso, n_retornados); None se ela nao foi concluida."""
        linha = self.conn.execute(
            "SELECT sucesso, n_retornados FROM chamadas WHERE run_id=? AND chave_idempotencia=? AND sucesso=1",
            (run_id, chave)).fetchone()
        return None if linha is None else (linha["sucesso"], linha["n_retornados"])

    def salvar_chamada(self, run_id, etapa, alvo_tipo, alvo_id, chave, registro, raw_path, raw_sha256,
                       uf=None, pagina=None):
        return self._inserir(
            "chamadas", run_id=run_id, etapa=etapa, provedor=registro.provedor, operacao=registro.operacao,
            alvo_tipo=alvo_tipo, alvo_id=alvo_id, uf=uf, pagina=pagina,
            parametros_json=json.dumps(registro.parametros, ensure_ascii=False, sort_keys=True, default=str),
            chave_idempotencia=chave, requisitado_em=registro.requisitado_em, http_status=registro.http_status,
            sucesso=int(registro.sucesso), tentativas=registro.tentativas, latencia_ms=registro.latencia_ms,
            id_externo=registro.id_externo, tokens_entrada=registro.tokens_entrada,
            tokens_saida=registro.tokens_saida, custo_usd=registro.custo_usd, erro=registro.erro,
            raw_path=raw_path, raw_sha256=raw_sha256,
            extras_json=json.dumps(registro.extras, ensure_ascii=False, default=str))

    def atualizar_chamada(self, chamada_id, **campos):
        permitidos = {"total_reportado", "n_retornados", "n_novos"}
        assert set(campos) <= permitidos
        sets = ", ".join(f"{k}=?" for k in campos)
        self.conn.execute(f"UPDATE chamadas SET {sets} WHERE chamada_id=?", (*campos.values(), chamada_id))

    # ---------- literature ----------
    def salvar_artigos(self, chamada_id, run_id, termo_id, artigos):
        novos = 0
        for a in artigos:
            chave = chave_dedup_titulo(a.titulo)
            linha = self.conn.execute("SELECT artigo_id FROM artigos WHERE chave_dedup=?", (chave,)).fetchone()
            if linha:
                artigo_id = linha["artigo_id"]
                self.conn.execute("UPDATE artigos SET citacoes=COALESCE(?, citacoes) WHERE artigo_id=?",
                                  (a.citacoes, artigo_id))
            else:
                artigo_id = self._inserir("artigos", chave_dedup=chave, titulo=a.titulo, link=a.link,
                                          autores_publicacao=a.autores_publicacao, ano=a.ano, snippet=a.snippet,
                                          citacoes=a.citacoes, primeira_vez_run=run_id, primeira_vez_em=agora())
                novos += 1
            self._inserir("ocorrencias", chamada_id=chamada_id, artigo_id=artigo_id, termo_id=termo_id,
                          run_id=run_id, posicao=a.posicao, citacoes_no_momento=a.citacoes)
        return novos

    # ---------- web ----------
    def salvar_resultados_web(self, chamada_id, run_id, consulta, resultados):
        novas = 0
        for r in resultados:
            norm = normalizar_url(r.url)
            linha = self.conn.execute("SELECT url_id FROM urls WHERE url_normalizada=?", (norm,)).fetchone()
            if linha:
                url_id = linha["url_id"]
            else:
                dom = dominio_de(norm)
                url_id = self._inserir("urls", url_normalizada=norm, url_original=r.url, dominio=dom,
                                       fonte_oficial=int(eh_oficial(dom)), primeira_vez_run=run_id,
                                       primeira_vez_em=agora())
                novas += 1
            self._inserir("resultados_web", chamada_id=chamada_id, run_id=run_id, consulta_id=consulta.id,
                          uf=consulta.uf, tecnologia=consulta.tecnologia, perfil=consulta.perfil, url_id=url_id,
                          posicao=r.posicao, titulo=r.titulo, snippet=r.snippet, data_pub=r.data)
        return novas

    def candidatos_download(self, run_origem):
        linhas = self.conn.execute("""
            SELECT r.url_id, u.url_original AS url, r.uf, u.dominio, u.fonte_oficial,
                   COALESCE(MAX(r.titulo),'') AS titulo, COALESCE(MAX(r.snippet),'') AS snippet,
                   MIN(r.posicao) AS melhor_posicao, COUNT(*) AS n_ocorrencias
            FROM resultados_web r JOIN urls u ON u.url_id=r.url_id
            WHERE r.run_id=? GROUP BY r.url_id, r.uf""", (run_origem,)).fetchall()
        return [CandidatoDownload(l["url_id"], l["url"], l["uf"], l["dominio"], l["titulo"], l["snippet"],
                                  l["melhor_posicao"], l["n_ocorrencias"], bool(l["fonte_oficial"])) for l in linhas]

    def salvar_selecao(self, run_id, linhas):
        # cada linha: (url_id, uf, selecionada, motivo) ou (url_id, uf, selecionada, motivo, auditoria)
        self.conn.executemany(
            "INSERT OR REPLACE INTO selecao_download (run_id, url_id, uf, selecionada, motivo, auditoria) "
            "VALUES (?,?,?,?,?,?)", [(run_id, *l, *(0,) * (5 - len(l))) for l in linhas])

    def urls_selecionadas(self, run_id):
        return [(l["url_id"], l["url"]) for l in self.conn.execute(
            """SELECT DISTINCT s.url_id, u.url_original AS url FROM selecao_download s
               JOIN urls u ON u.url_id=s.url_id WHERE s.run_id=? AND (s.selecionada=1 OR s.auditoria=1) ORDER BY s.url_id""",
            (run_id,)).fetchall()]

    def salvar_pagina(self, run_id, url_id, chamada_id, arquivo, texto, texto_path):
        return self._inserir(
            "paginas", run_id=run_id, url_id=url_id, chamada_id=chamada_id, url_final=arquivo.url_final,
            dominio_final=dominio_de(arquivo.url_final), fonte_oficial_final=int(eh_oficial(dominio_de(arquivo.url_final))),
            http_status=arquivo.http_status, content_type=arquivo.content_type, n_bytes=len(arquivo.conteudo),
            truncado=int(arquivo.truncado), texto_path=texto_path, n_chars=len(texto.texto) if texto else 0,
            extrator=texto.extrator if texto else None, extracao_ok=int(bool(texto and texto.ok)),
            motivo_falha=texto.motivo_falha if texto else None)

    def itens_para_classificar(self, run_origem):
        linhas = self.conn.execute("""
            SELECT s.url_id, s.uf, u.url_original AS url,
                   (SELECT titulo  FROM resultados_web r WHERE r.url_id=s.url_id AND r.uf=s.uf ORDER BY r.resultado_id DESC LIMIT 1) AS titulo,
                   (SELECT snippet FROM resultados_web r WHERE r.url_id=s.url_id AND r.uf=s.uf ORDER BY r.resultado_id DESC LIMIT 1) AS snippet,
                   p.pagina_id, CASE WHEN p.extracao_ok=1 THEN p.texto_path END AS texto_path
            FROM selecao_download s
            JOIN urls u ON u.url_id=s.url_id
            LEFT JOIN paginas p ON p.pagina_id=(SELECT MAX(pagina_id) FROM paginas WHERE url_id=s.url_id AND run_id=s.run_id)
            WHERE s.run_id=? AND (s.selecionada=1 OR s.auditoria=1)
            ORDER BY s.uf, s.url_id""", (run_origem,)).fetchall()
        return [ItemClassificacao(l["url_id"], l["uf"], l["url"], l["titulo"], l["snippet"],
                                  l["pagina_id"], l["texto_path"]) for l in linhas]

    def salvar_classificacao(self, chamada_id, run_id, item, entrada, classificador, prompt_versao,
                             resultado, achados, n_invalidos):
        cid = self._inserir(
            "classificacoes", chamada_id=chamada_id, run_id=run_id, url_id=item.url_id, pagina_id=item.pagina_id,
            uf=item.uf, origem_texto=entrada.origem, texto_truncado=int(entrada.truncado),
            n_chars_enviados=len(entrada.texto), classificador=classificador, prompt_versao=prompt_versao,
            relevante=int(resultado.relevante), json_valido=int(resultado.json_valido),
            n_achados=len(achados), n_achados_invalidos=n_invalidos, resposta_texto=resultado.texto_resposta)
        for a in achados:
            self._inserir("achados", classificacao_id=cid, uf=item.uf, tecnologia=a.tecnologia,
                          status_reportado=a.status, fornecedor=a.fornecedor or None,
                          menciona_lgpd=int(a.menciona_lgpd), evidencia=a.evidencia,
                          evidencia_confere=None if a.evidencia_confere is None else int(a.evidencia_confere),
                          confianca=a.confianca, confianca_original=a.confianca_original,
                          evidencia_cita_tecnologia=None if a.evidencia_cita_tecnologia is None else int(a.evidencia_cita_tecnologia),
                          evidencia_cita_lgpd=None if a.evidencia_cita_lgpd is None else int(a.evidencia_cita_lgpd))
        return cid

    def salvar_achados_descartados(self, classificacao_id, descartados):
        """descartados: [(Achado, motivo)] devolvidos pelo modelo fora do vocabulario controlado."""
        uf = self.conn.execute("SELECT uf FROM classificacoes WHERE classificacao_id=?", (classificacao_id,)).fetchone()[0]
        for a, motivo in descartados:
            self._inserir("achados_descartados", classificacao_id=classificacao_id, uf=uf, tecnologia=a.tecnologia,
                          status=a.status, fornecedor=a.fornecedor or None, menciona_lgpd=int(a.menciona_lgpd),
                          evidencia=a.evidencia, confianca=a.confianca, motivo=motivo)

    # ---------- export and imports ----------
    def tabelas_para_exportacao(self):
        consultas = {
            "Execucoes": "SELECT * FROM execucoes ORDER BY iniciado_em",
            "Funil": "SELECT * FROM v_funil",
            "Custos": "SELECT * FROM v_custos",
            "Falhas": "SELECT * FROM v_falhas",
            "Descartes": "SELECT * FROM v_descartes",
            "Dominios": "SELECT * FROM v_dominios LIMIT 300",
            "Busca_web": "SELECT * FROM v_metricas_busca_web",
            "Achados": "SELECT * FROM v_achados_revisao",
            "Resumo_UF_bruto": "SELECT * FROM v_resumo_uf",
            "Secretarias": "SELECT * FROM v_secretarias_confirmadas",
            "Chamadas": "SELECT * FROM chamadas ORDER BY chamada_id",
            "Metricas_termo": "SELECT * FROM v_metricas_por_termo",
            "Artigos": "SELECT * FROM artigos ORDER BY citacoes DESC",
            "Artigos_ano": "SELECT * FROM v_artigos_por_ano",
            "Multi_termo": "SELECT * FROM v_artigos_multi_termo",
            "Sobreposicao": "SELECT * FROM v_sobreposicao_termos",
            "Triagem": """SELECT a.artigo_id, a.titulo, a.ano, a.link, a.citacoes,
                                 COALESCE(t.decisao,'pendente') AS decisao, t.motivo,
                                 t.confirmado_em_base, t.link_confirmado, t.revisor,
                                 t.decisao_texto_completo, t.motivo_texto_completo
                          FROM artigos a LEFT JOIN triagem t ON t.artigo_id=a.artigo_id
                          ORDER BY a.citacoes DESC""",
            "Buscas_manuais": "SELECT * FROM buscas_manuais ORDER BY base, termo_id",
            "Manuais_resumo": "SELECT * FROM v_manuais_resumo",
            # metricas para o relatorio (protocolo e justificativas)
            "Termos_rendimento": "SELECT * FROM v_rendimento_termo",
            "Termos_pares": "SELECT * FROM v_pares_termos",
            "Termos_idioma": "SELECT * FROM v_ganho_por_idioma",
            "Termos_pagina": "SELECT * FROM v_rendimento_por_pagina",
            "Curva_descoberta": "SELECT * FROM v_curva_descoberta ORDER BY chamada_id",
            "PRISMA": "SELECT fase, metrica, valor FROM v_prisma ORDER BY ordem",
            "Motivos_exclusao": "SELECT * FROM v_motivos_exclusao",
            "Registro_buscas": "SELECT * FROM v_registro_buscas",
            "Web_rendimento": "SELECT * FROM v_rendimento_busca_web",
            "Web_modelos": "SELECT * FROM v_sobreposicao_modelos",
            "Web_posicao": "SELECT * FROM v_rendimento_por_posicao",
            "Web_consultas_vazias": "SELECT * FROM v_consultas_vazias",
            "UF_tecnologia": "SELECT * FROM v_cobertura_uf_tecnologia",
            "Precisao_LLM": "SELECT * FROM v_precisao_llm",
            "Correcoes_humanas": "SELECT * FROM v_correcoes_humanas",
            "Qualidade_classif": "SELECT * FROM v_qualidade_classificacao",
            "Extracao": "SELECT * FROM v_extracao",
            "Eficiencia": "SELECT * FROM v_eficiencia",
            "Classif_invalidas": "SELECT * FROM v_classificacoes_invalidas",
            "Consistencia_evidencia": "SELECT * FROM v_consistencia_evidencia",
            "Gasto_real": "SELECT * FROM v_gasto_real",
            "Saldos": "SELECT * FROM v_saldos",
            "Metricas_run": "SELECT * FROM metricas_run",
            "Download_resultado": "SELECT * FROM v_resultado_download",
            "Classif_resultado": "SELECT * FROM v_resultado_classificacao",
            "Achados_descartados": "SELECT * FROM v_achados_descartados",
            "Confianca_ajustada": "SELECT * FROM v_confianca_ajustada",
            "Auditoria_prefiltro": "SELECT * FROM v_auditoria_prefiltro",
            "Fontes": "SELECT * FROM v_rendimento_fonte",
            "Fontes_sobreposicao": "SELECT * FROM v_sobreposicao_fontes",
            "Termos_fonte": "SELECT * FROM v_rendimento_termo_fonte",
            "Termos_total_estabilidade": "SELECT * FROM v_total_reportado_estabilidade",
            "Ganho_contexto": "SELECT * FROM v_ganho_contexto",
            "Revisores_kappa": "SELECT * FROM v_concordancia_revisores",
            "Discordancias": "SELECT * FROM v_discordancias_triagem",
            "Passadas": "SELECT * FROM v_passadas ORDER BY run_id, passada",
            "Historico_triagem": "SELECT * FROM triagem_revisoes ORDER BY revisao_id",
            "Historico_achados": "SELECT * FROM achados_revisoes ORDER BY revisao_id",
        }
        return {k: pd.read_sql_query(v, self.conn) for k, v in consultas.items()}

    def importar_buscas_manuais(self, df):
        """C7: reimportar o mesmo arquivo nao duplica nada. Uma busca e identificada por (base, termo_id, data_busca);
        a linha nova substitui a anterior de mesma chave, tudo na mesma transacao."""
        linhas = df[df["n_resultados"].notna()]
        chaves = [(r["base"], r["termo_id"], _v(r["data_busca"])) for _, r in linhas.iterrows()]
        repetidas = sorted({k for k in chaves if chaves.count(k) > 1}, key=str)
        if repetidas:
            raise SystemExit("Mais de uma linha com a mesma chave (base, termo_id, data_busca) no arquivo: "
                             + "; ".join(f"{b}/{t}/{d or 'sem data'}" for b, t, d in repetidas))
        try:
            for (_, r), (base, termo_id, data) in zip(linhas.iterrows(), chaves):
                self.conn.execute("DELETE FROM buscas_manuais WHERE base=? AND termo_id=? AND data_busca IS ?",
                                  (base, termo_id, data))
                self._inserir("buscas_manuais", base=base, termo_id=termo_id, string_base=_v(r["string_base"]),
                              filtros=_v(r["filtros"]), n_resultados=int(r["n_resultados"]),
                              n_apos_filtro=None if pd.isna(r["n_apos_filtro"]) else int(r["n_apos_filtro"]),
                              n_selecionados=None if pd.isna(r["n_selecionados"]) else int(r["n_selecionados"]),
                              data_busca=data, observacao=_v(r["observacao"]))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return len(linhas)

    def _registrar_revisao_triagem(self, artigo_id, revisor, decisao, motivo, tc, motivo_tc, independente):
        """Historico: so grava se algo mudou em relacao a ultima revisao do mesmo revisor, do mesmo tipo
        (independente ou nao), para o artigo."""
        ultima = self.conn.execute(
            """SELECT decisao, motivo, decisao_texto_completo, motivo_texto_completo FROM triagem_revisoes
               WHERE artigo_id=? AND revisor=? AND independente=? ORDER BY revisao_id DESC LIMIT 1""",
            (artigo_id, revisor, independente)).fetchone()
        if ultima is not None and tuple(ultima) == (decisao, motivo, tc, motivo_tc):
            return
        self._inserir("triagem_revisoes", artigo_id=artigo_id, revisor=revisor, decisao=decisao, motivo=motivo,
                      decisao_texto_completo=tc, motivo_texto_completo=motivo_tc, importado_em=agora(),
                      independente=independente)

    def importar_triagem(self, df, so_historico=False):
        """Importa a aba Triagem. Toda decisao entra no historico (`triagem_revisoes`), por revisor.

        Com so_historico=True a decisao NAO altera `triagem` (revisao independente, antes do consenso).
        """
        validos = {"pendente", "incluir", "excluir"}
        tem_tc = "decisao_texto_completo" in df.columns
        for _, r in df.iterrows():
            dec = str(_v(r["decisao"]) or "pendente").strip().lower()
            if dec not in validos:
                raise SystemExit(f"Invalid decision for article {r['artigo_id']}: {dec}")
            tc = motivo_tc = None
            if tem_tc:
                tc = str(_v(r["decisao_texto_completo"]) or "").strip().lower() or None
                if tc is not None and tc not in validos:
                    raise SystemExit(f"Invalid full-text decision for article {r['artigo_id']}: {tc}")
                if "motivo_texto_completo" in df.columns:
                    motivo_tc = _v(r["motivo_texto_completo"])
            artigo_id = int(r["artigo_id"])
            motivo = _v(r["motivo"])
            revisor = str(_v(r["revisor"]) or "").strip() or "(sem revisor)"
            self._registrar_revisao_triagem(artigo_id, revisor, dec, motivo, tc, motivo_tc, int(bool(so_historico)))
            if so_historico:
                continue
            self.conn.execute(
                """INSERT INTO triagem (artigo_id, decisao, motivo, confirmado_em_base, link_confirmado, revisor, revisado_em)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(artigo_id) DO UPDATE SET decisao=excluded.decisao, motivo=excluded.motivo,
                     confirmado_em_base=excluded.confirmado_em_base, link_confirmado=excluded.link_confirmado,
                     revisor=excluded.revisor, revisado_em=excluded.revisado_em""",
                (artigo_id, dec, motivo, _v(r["confirmado_em_base"]), _v(r["link_confirmado"]), _v(r["revisor"]), agora()))
            if tem_tc:
                self.conn.execute("UPDATE triagem SET decisao_texto_completo=?, motivo_texto_completo=? WHERE artigo_id=?",
                                  (tc, motivo_tc, artigo_id))
        self.conn.commit()
        return len(df)

    def importar_verificacao_achados(self, df, status_permitidos):
        n = 0
        for _, r in df.iterrows():
            if pd.isna(r["verificado"]) or int(r["verificado"]) != 1:
                continue
            final = _v(r["status_final"])
            if final not in status_permitidos:
                raise SystemExit(f"Invalid status_final for finding {r['achado_id']}: {final}")
            achado_id, por, obs = int(r["achado_id"]), _v(r["verificado_por"]), _v(r["observacao"])
            self.conn.execute(
                """UPDATE achados SET verificado=1, status_final=?, verificado_por=?, verificado_em=?,
                   observacao=? WHERE achado_id=?""", (final, por, agora(), obs, achado_id))
            # historico: so grava se mudou em relacao a ultima verificacao da mesma pessoa
            revisor = str(por or "").strip() or "(sem revisor)"
            ultima = self.conn.execute(
                """SELECT status_final, observacao FROM achados_revisoes WHERE achado_id=? AND verificado_por=?
                   ORDER BY revisao_id DESC LIMIT 1""", (achado_id, revisor)).fetchone()
            if ultima is None or tuple(ultima) != (final, obs):
                self._inserir("achados_revisoes", achado_id=achado_id, verificado_por=revisor, status_final=final,
                              observacao=obs, importado_em=agora())
            n += 1
        self.conn.commit()
        return n

    def importar_artigos_manuais(self, df):
        """Artigos informados a mao nas buscas manuais. Entram em `artigos` (deduplicados por titulo) e em
        `ocorrencias_manuais`. Reimportar o mesmo arquivo nao duplica nada. Devolve (ocorrencias novas, artigos novos)."""
        ocorrencias = novos = 0
        for _, r in df.iterrows():
            titulo = str(r["titulo"]).strip()
            chave = chave_dedup_titulo(titulo)
            link = _v(r["link"]) if "link" in df.columns else None
            linha = self.conn.execute("SELECT artigo_id FROM artigos WHERE chave_dedup=?", (chave,)).fetchone()
            if linha:
                artigo_id = linha["artigo_id"]
                if link:
                    self.conn.execute("UPDATE artigos SET link=COALESCE(link, ?) WHERE artigo_id=?", (link, artigo_id))
            else:
                artigo_id = self._inserir(
                    "artigos", chave_dedup=chave, titulo=titulo, link=link,
                    autores_publicacao=_v(r["autores_publicacao"]) if "autores_publicacao" in df.columns else None,
                    ano=_int(r["ano"]) if "ano" in df.columns else None, snippet=None,
                    citacoes=_int(r["citacoes"]) if "citacoes" in df.columns else None,
                    primeira_vez_run=f"manual:{r['base']}", primeira_vez_em=agora())
                novos += 1
            data = str(_v(r["data_busca"]) or "") if "data_busca" in df.columns else ""
            cur = self.conn.execute(
                """INSERT OR IGNORE INTO ocorrencias_manuais (artigo_id, base, termo_id, data_busca, posicao, importado_em)
                   VALUES (?,?,?,?,?,?)""",
                (artigo_id, r["base"], r["termo_id"], data,
                 _int(r["posicao"]) if "posicao" in df.columns else None, agora()))
            ocorrencias += cur.rowcount
        self.conn.commit()
        return ocorrencias, novos
