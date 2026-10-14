import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd
from dominio.modelos import CandidatoDownload, ItemClassificacao
from dominio.servicos import normalizar_url, dominio_de, eh_oficial, chave_dedup_titulo
from infra.util import agora


def _v(x):
    return None if pd.isna(x) else x


class RepositorioSQLite:
    def __init__(self, caminho):
        caminho = Path(caminho)
        caminho.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(caminho)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript((Path(__file__).parent / "schema.sql").read_text(encoding="utf-8"))

    # ---------- utilities ----------
    def _inserir(self, tabela, **c):
        cols = ", ".join(c)
        marcas = ", ".join("?" for _ in c)
        return self.conn.execute(f"INSERT INTO {tabela} ({cols}) VALUES ({marcas})", tuple(c.values())).lastrowid

    def confirmar(self):
        self.conn.commit()

    # ---------- run ----------
    def iniciar_execucao(self, comando, config_hash, config_json, commit_git, retomar=None, run_origem=None):
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
            self.conn.commit()
            return retomar
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
        self._inserir("execucoes", run_id=run_id, iniciado_em=agora(), comando=comando,
                      config_hash=config_hash, config_json=config_json, commit_git=commit_git,
                      run_origem=run_origem)
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
        self.conn.executemany(
            "INSERT OR REPLACE INTO selecao_download (run_id, url_id, uf, selecionada, motivo) VALUES (?,?,?,?,?)",
            [(run_id, *l) for l in linhas])

    def urls_selecionadas(self, run_id):
        return [(l["url_id"], l["url"]) for l in self.conn.execute(
            """SELECT DISTINCT s.url_id, u.url_original AS url FROM selecao_download s
               JOIN urls u ON u.url_id=s.url_id WHERE s.run_id=? AND s.selecionada=1 ORDER BY s.url_id""",
            (run_id,)).fetchall()]

    def salvar_pagina(self, run_id, url_id, chamada_id, arquivo, texto, texto_path):
        return self._inserir(
            "paginas", run_id=run_id, url_id=url_id, chamada_id=chamada_id, url_final=arquivo.url_final,
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
            WHERE s.run_id=? AND s.selecionada=1
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
                          confianca=a.confianca)
        return cid

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
            "Chamadas": "SELECT * FROM chamadas ORDER BY chamada_id",
            "Metricas_termo": "SELECT * FROM v_metricas_por_termo",
            "Artigos": "SELECT * FROM artigos ORDER BY citacoes DESC",
            "Artigos_ano": "SELECT * FROM v_artigos_por_ano",
            "Multi_termo": "SELECT * FROM v_artigos_multi_termo",
            "Sobreposicao": "SELECT * FROM v_sobreposicao_termos",
            "Triagem": """SELECT a.artigo_id, a.titulo, a.ano, a.link, a.citacoes,
                                 COALESCE(t.decisao,'pendente') AS decisao, t.motivo,
                                 t.confirmado_em_base, t.link_confirmado, t.revisor
                          FROM artigos a LEFT JOIN triagem t ON t.artigo_id=a.artigo_id
                          ORDER BY a.citacoes DESC""",
            "Buscas_manuais": "SELECT * FROM buscas_manuais ORDER BY base, termo_id",
            "Manuais_resumo": "SELECT * FROM v_manuais_resumo",
        }
        return {k: pd.read_sql_query(v, self.conn) for k, v in consultas.items()}

    def importar_buscas_manuais(self, df):
        n = 0
        for _, r in df[df["n_resultados"].notna()].iterrows():
            self._inserir("buscas_manuais", base=r["base"], termo_id=r["termo_id"], string_base=_v(r["string_base"]),
                          filtros=_v(r["filtros"]), n_resultados=int(r["n_resultados"]),
                          n_apos_filtro=None if pd.isna(r["n_apos_filtro"]) else int(r["n_apos_filtro"]),
                          n_selecionados=None if pd.isna(r["n_selecionados"]) else int(r["n_selecionados"]),
                          data_busca=_v(r["data_busca"]), observacao=_v(r["observacao"]))
            n += 1
        self.conn.commit()
        return n

    def importar_triagem(self, df):
        validos = {"pendente", "incluir", "excluir"}
        for _, r in df.iterrows():
            dec = str(_v(r["decisao"]) or "pendente").strip().lower()
            if dec not in validos:
                raise SystemExit(f"Invalid decision for article {r['artigo_id']}: {dec}")
            self.conn.execute(
                """INSERT INTO triagem (artigo_id, decisao, motivo, confirmado_em_base, link_confirmado, revisor, revisado_em)
                   VALUES (?,?,?,?,?,?,datetime('now'))
                   ON CONFLICT(artigo_id) DO UPDATE SET decisao=excluded.decisao, motivo=excluded.motivo,
                     confirmado_em_base=excluded.confirmado_em_base, link_confirmado=excluded.link_confirmado,
                     revisor=excluded.revisor, revisado_em=excluded.revisado_em""",
                (int(r["artigo_id"]), dec, _v(r["motivo"]), _v(r["confirmado_em_base"]),
                 _v(r["link_confirmado"]), _v(r["revisor"])))
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
            self.conn.execute(
                """UPDATE achados SET verificado=1, status_final=?, verificado_por=?, verificado_em=datetime('now'),
                   observacao=? WHERE achado_id=?""",
                (final, _v(r["verificado_por"]), _v(r["observacao"]), int(r["achado_id"])))
            n += 1
        self.conn.commit()
        return n
