import hashlib
import json
import logging
import sqlite3
import uuid
from urllib.parse import urlsplit
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from dominio.modelos import CandidatoDownload, ItemClassificacao
from dominio.servicos import (normalizar_url, dominio_de, eh_oficial, chave_dedup_titulo, palavras_chave_tecnologia,
                              evidencia_cita_termo, evidencia_cita_lgpd, normalizar_status_final)
from dominio.entrada import separar_runs, juntar_runs
from infra.sqlite_wal import ligar_wal
from infra.util import agora
from dominio.sugestoes import CAMPOS_ACHADO, CAMPOS_ARTIGO, chave_autor, ficha_da_decisao


def _v(x):
    return None if pd.isna(x) else x


def _int(x):
    return None if pd.isna(x) else int(x)


NAO_TRIADO = "nao-triado"              # valor de `versao` de um artigo sem decisao na triagem
NAO_VERIFICADO = "nao-verificado"      # valor de `versao` de um achado ainda sem verificacao


# colunas acrescentadas depois da primeira versao do schema: bancos antigos as recebem ao abrir
_COLUNAS_NOVAS = {
    "execucoes": {"ambiente_json": "TEXT", "no_relatorio": "INTEGER NOT NULL DEFAULT 1", "motivo_exclusao": "TEXT",
                  "excluida_em": "TEXT"},
    "paginas": {"dominio_final": "TEXT", "fonte_oficial_final": "INTEGER"},
    "selecao_download": {"auditoria": "INTEGER NOT NULL DEFAULT 0"},
    "achados": {"confianca_original": "TEXT", "evidencia_cita_tecnologia": "INTEGER", "evidencia_cita_lgpd": "INTEGER",
                "nome_solucao": "TEXT"},
    "triagem": {"decisao_texto_completo": "TEXT", "motivo_texto_completo": "TEXT"},
    "triagem_revisoes": {"independente": "INTEGER NOT NULL DEFAULT 0"},
    "achados_revisoes": {"anterior_json": "TEXT", "posterior_json": "TEXT", "desfeita": "INTEGER NOT NULL DEFAULT 0",
                         "independente": "INTEGER NOT NULL DEFAULT 0"},
    "resultados_web": {"cidade": "TEXT"},
    "classificacoes": {"cidade": "TEXT"},
}


class RepositorioSQLite:
    def __init__(self, caminho):
        caminho = Path(caminho)
        caminho.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(caminho)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        # Quem GRAVA espera ate 60 s por um bloqueio de leitura (o painel aberto pode estar lendo, e em /mnt/c uma leitura
        # lenta segura o banco). Com 5 s, uma classificacao longa morria com "database is locked" (16/10/2026).
        self.conn.execute("PRAGMA busy_timeout = 60000")
        # WAL: quem le nao espera quem grava (um escritor por vez continua valendo). O modo fica gravado no arquivo, entao so se
        # troca uma vez (a troca precisa do banco sem outra conexao aberta). synchronous=FULL vale por conexao e prioriza a
        # durabilidade das decisoes humanas confirmadas.
        ligar_wal(self.conn, caminho)
        self.conn.execute("PRAGMA synchronous = FULL")
        self._preparar_esquema()
        self._garantir_colunas()

    @staticmethod
    def _assinatura_do_esquema():
        texto = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
        return texto, hashlib.sha256((texto + json.dumps(_COLUNAS_NOVAS, sort_keys=True)).encode()).hexdigest()

    @classmethod
    def esquema_atualizado(cls, caminho):
        """So le (modo somente leitura): o esquema gravado no banco tem a mesma assinatura do codigo atual? Banco que nao
        existe conta como atualizado (quem o cria aplica o esquema). Serve ao painel, que abre o banco so para leitura."""
        caminho = Path(caminho)
        if not caminho.exists():
            return True
        conn = sqlite3.connect(f"file:{caminho.as_posix()}?mode=ro", uri=True)
        try:
            guardada = conn.execute("SELECT valor FROM meta_schema WHERE chave='assinatura'").fetchone()
        except sqlite3.Error:
            return False
        finally:
            conn.close()
        return bool(guardada) and guardada[0] == cls._assinatura_do_esquema()[1]

    def _preparar_esquema(self):
        """Cria ou atualiza o esquema SO quando ele mudou. Antes, cada processo que abria o banco derrubava e recriava as
        ~60 views, uma gravacao longa em /mnt/c que bloqueava quem ja estava gravando ("database is locked", 16/10/2026).
        A assinatura (hash do `schema.sql` e das colunas novas) fica em `meta_schema`; igual = nenhuma gravacao ao abrir."""
        texto, assinatura = self._assinatura_do_esquema()
        if self.conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta_schema'").fetchone():
            guardada = self.conn.execute("SELECT valor FROM meta_schema WHERE chave='assinatura'").fetchone()
            if guardada and guardada[0] == assinatura:
                return
        self.conn.executescript(texto)
        self._garantir_colunas()
        self.conn.execute("CREATE TABLE IF NOT EXISTS meta_schema (chave TEXT PRIMARY KEY, valor TEXT)")
        self.conn.execute("INSERT OR REPLACE INTO meta_schema (chave, valor) VALUES ('assinatura', ?)", (assinatura,))
        self.conn.commit()

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

    def desfazer(self):
        self.conn.rollback()

    def pendente(self):
        """Ha gravacao ainda nao confirmada na transacao aberta."""
        return self.conn.in_transaction

    # ---------- run ----------
    def validar_runs_origem(self, runs):
        """Cada execucao de origem (--de) precisa existir; encerra com mensagem para a primeira que faltar."""
        for run in separar_runs(runs):
            if not self.conn.execute("SELECT 1 FROM execucoes WHERE run_id=?", (run,)).fetchone():
                raise SystemExit(f"Execução indicada em --de não encontrada: {run}")

    def iniciar_execucao(self, comando, config_hash, config_json, commit_git, retomar=None, run_origem=None,
                         ambiente_json=None):
        """`run_origem`: um run_id, ou varios (lista, ou texto separado por virgulas). A coluna `execucoes.run_origem`
        continua TEXT unica e guarda os run_id separados por virgula, na ordem dada (`dominio.entrada.separar_runs`
        os separa de novo)."""
        # C5: toda execucao indicada em --de precisa existir
        self.validar_runs_origem(run_origem)
        run_origem = juntar_runs(run_origem)
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

    def argumentos_da_execucao(self, run_id):
        """Argumentos da linha de comando com que a execucao foi criada (execucoes.ambiente_json): {} se nao houver registro
        (execucao inexistente ou coluna NULL), None se o registro estiver ilegivel (texto vazio, JSON invalido ou sem o formato
        esperado)."""
        linha = self.conn.execute("SELECT ambiente_json FROM execucoes WHERE run_id=?", (run_id,)).fetchone()
        if not linha or linha["ambiente_json"] is None:
            return {}
        try:
            ambiente = json.loads(linha["ambiente_json"])
        except ValueError:
            return None
        argumentos = ambiente.get("argumentos", {}) if isinstance(ambiente, dict) else None
        return argumentos if isinstance(argumentos, dict) else None

    def obter_run_origem(self, run_id):
        """C5: run_origem guardado para a execucao (None se nao houver). Com varias origens e o texto como foi gravado,
        separado por virgulas; use `dominio.entrada.separar_runs` para obter a lista."""
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

    def chaves_com_chamada(self, run_id, etapa):
        """Chaves dos itens que ja tiveram ao menos uma chamada (com sucesso ou nao) nesta execucao e etapa: o --limite conta estes."""
        return {l[0] for l in self.conn.execute("SELECT DISTINCT chave_idempotencia FROM chamadas WHERE run_id=? AND etapa=?",
                                                (run_id, etapa))}

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
                          posicao=r.posicao, titulo=r.titulo, snippet=r.snippet, data_pub=r.data,
                          cidade=consulta.cidade or None)
        return novas

    def candidatos_download(self, run_origens):
        """Candidatos a download de UMA ou MAIS execucoes de busca (`run_origens`: texto ou lista), sem repeticao por
        (url_id, uf). Do resultado mais recente (maior `resultado_id`) vem o titulo, o snippet e a cidade; a posicao e
        a menor de todas e `n_ocorrencias` soma as ocorrencias de todas as execucoes. Ordem deterministica: (uf, url_id)."""
        runs = separar_runs(run_origens)
        if not runs:
            return []
        linhas = self.conn.execute(f"""
            SELECT r.resultado_id, r.url_id, u.url_original AS url, r.uf, u.dominio, u.fonte_oficial,
                   r.titulo, r.snippet, r.posicao, r.cidade
            FROM resultados_web r JOIN urls u ON u.url_id=r.url_id
            WHERE r.run_id IN ({",".join("?" for _ in runs)}) ORDER BY r.resultado_id""", runs).fetchall()
        por_par = {}
        for l in linhas:
            chave = (l["url_id"], l["uf"])
            d = por_par.setdefault(chave, {"n": 0, "pos": None, "cidade": None})
            d["n"] += 1
            d["linha"] = l                                  # a ultima (mais recente) sobrescreve
            if l["posicao"] is not None and (d["pos"] is None or l["posicao"] < d["pos"]):
                d["pos"] = l["posicao"]
            if l["cidade"]:
                d["cidade"] = l["cidade"]
        return [CandidatoDownload(l["url_id"], l["url"], l["uf"], l["dominio"], l["titulo"] or "", l["snippet"] or "",
                                  d["pos"], d["n"], bool(l["fonte_oficial"]), d["cidade"] or "")
                for _, d in sorted(por_par.items()) for l in (d["linha"],)]

    def urls_com_pagina_ok(self, excluir_run=None):
        """url_id com ao menos uma pagina de texto extraido (`extracao_ok = 1`) em QUALQUER execucao, dentro ou fora do
        relatorio. `excluir_run` ignora as paginas dessa execucao (uma retomada nao muda o que a execucao ja selecionou)."""
        return {l[0] for l in self.conn.execute(
            "SELECT DISTINCT url_id FROM paginas WHERE extracao_ok=1 AND run_id <> ?", (excluir_run or "",))}

    def ultimas_tentativas_download(self, excluir_run=None):
        """{url_id: (resultado, motivo)} da tentativa de download MAIS RECENTE de cada url, em qualquer execucao
        (`v_resultado_download`: `resultado` ok, falha_download ou falha_extracao; `motivo` como na view). Urls nunca
        tentadas nao aparecem. `excluir_run` ignora as tentativas dessa execucao."""
        saida = {}
        for l in self.conn.execute("""
                SELECT url_id, resultado, motivo FROM v_resultado_download
                WHERE chamada_id IS NOT NULL AND run_id <> ? ORDER BY chamada_id""", (excluir_run or "",)):
            saida[l["url_id"]] = (l["resultado"], l["motivo"])
        return saida

    def classificados_validos(self, prompt_versao, classificador, excluir_run=None):
        """{(url_id, uf)} com classificacao valida (`json_valido = 1`) feita com este prompt e este classificador em
        alguma execucao DENTRO do relatorio (`no_relatorio = 1`). `excluir_run` ignora as classificacoes dessa execucao."""
        return {(l[0], l[1]) for l in self.conn.execute(
            """SELECT DISTINCT k.url_id, k.uf FROM classificacoes k JOIN execucoes e ON e.run_id=k.run_id
               WHERE k.json_valido=1 AND k.prompt_versao=? AND k.classificador=? AND e.no_relatorio=1 AND k.run_id <> ?""",
            (prompt_versao, classificador, excluir_run or ""))}

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

    def itens_para_classificar(self, run_origens):
        """Itens (url_id, uf) selecionados para download em UMA ou MAIS execucoes de download (`run_origens`: texto ou
        lista), sem repeticao. A pagina de cada item e a MAIS RECENTE com texto extraido entre essas execucoes (se nenhuma
        tiver texto, a mais recente, sem texto). Titulo, snippet e cidade vem do resultado de busca mais recente.
        Ordem deterministica: (uf, url_id)."""
        runs = separar_runs(run_origens)
        if not runs:
            return []
        marcas = ",".join("?" for _ in runs)
        linhas = self.conn.execute(f"""
            SELECT s.url_id, s.uf, u.url_original AS url,
                   (SELECT titulo  FROM resultados_web r WHERE r.url_id=s.url_id AND r.uf=s.uf ORDER BY r.resultado_id DESC LIMIT 1) AS titulo,
                   (SELECT snippet FROM resultados_web r WHERE r.url_id=s.url_id AND r.uf=s.uf ORDER BY r.resultado_id DESC LIMIT 1) AS snippet,
                   p.pagina_id, CASE WHEN p.extracao_ok=1 THEN p.texto_path END AS texto_path,
                   (SELECT cidade FROM resultados_web r WHERE r.url_id=s.url_id AND r.uf=s.uf
                    AND r.cidade IS NOT NULL ORDER BY r.resultado_id DESC LIMIT 1) AS cidade
            FROM (SELECT DISTINCT url_id, uf FROM selecao_download
                  WHERE run_id IN ({marcas}) AND (selecionada=1 OR auditoria=1)) s
            JOIN urls u ON u.url_id=s.url_id
            LEFT JOIN paginas p ON p.pagina_id=COALESCE(
                (SELECT MAX(pagina_id) FROM paginas WHERE url_id=s.url_id AND run_id IN ({marcas}) AND extracao_ok=1),
                (SELECT MAX(pagina_id) FROM paginas WHERE url_id=s.url_id AND run_id IN ({marcas})))
            ORDER BY s.uf, s.url_id""", runs * 3).fetchall()
        return [ItemClassificacao(l["url_id"], l["uf"], l["url"], l["titulo"], l["snippet"],
                                  l["pagina_id"], l["texto_path"], l["cidade"] or "") for l in linhas]

    def salvar_classificacao(self, chamada_id, run_id, item, entrada, classificador, prompt_versao,
                             resultado, achados, n_invalidos):
        cid = self._inserir(
            "classificacoes", chamada_id=chamada_id, run_id=run_id, url_id=item.url_id, pagina_id=item.pagina_id,
            uf=item.uf, origem_texto=entrada.origem, texto_truncado=int(entrada.truncado),
            n_chars_enviados=len(entrada.texto), classificador=classificador, cidade=item.cidade or None, prompt_versao=prompt_versao,
            relevante=int(resultado.relevante), json_valido=int(resultado.json_valido),
            n_achados=len(achados), n_achados_invalidos=n_invalidos, resposta_texto=resultado.texto_resposta)
        for a in achados:
            self._inserir("achados", classificacao_id=cid, uf=item.uf, tecnologia=a.tecnologia,
                          status_reportado=a.status, fornecedor=a.fornecedor or None,
                          menciona_lgpd=int(a.menciona_lgpd), evidencia=a.evidencia,
                          evidencia_confere=None if a.evidencia_confere is None else int(a.evidencia_confere),
                          confianca=a.confianca, confianca_original=a.confianca_original,
                          evidencia_cita_tecnologia=None if a.evidencia_cita_tecnologia is None else int(a.evidencia_cita_tecnologia),
                          evidencia_cita_lgpd=None if a.evidencia_cita_lgpd is None else int(a.evidencia_cita_lgpd),
                          nome_solucao=a.nome_solucao or None)
        return cid

    def salvar_achados_descartados(self, classificacao_id, descartados):
        """descartados: [(Achado, motivo)] devolvidos pelo modelo fora do vocabulario controlado."""
        uf = self.conn.execute("SELECT uf FROM classificacoes WHERE classificacao_id=?", (classificacao_id,)).fetchone()[0]
        for a, motivo in descartados:
            self._inserir("achados_descartados", classificacao_id=classificacao_id, uf=uf, tecnologia=a.tecnologia,
                          status=a.status, fornecedor=a.fornecedor or None, menciona_lgpd=int(a.menciona_lgpd),
                          evidencia=a.evidencia, confianca=a.confianca, motivo=motivo)

    # ---------- triagem de escopo por LLM ----------
    def itens_para_triagem_escopo(self, fonte):
        """Itens a triar, como dicionarios simples, em ordem estavel (so execucoes dentro do relatorio).

        `artigo`: um por artigo de `r_artigos`, com os ids dos termos que o acharam (Scholar primeiro, na ordem em que
        apareceram; depois as buscas manuais) e as bases manuais de origem. `web`: um por (url_id, uf) de
        `r_resultados_web`, com titulo e snippet da ocorrencia de snippet mais longo (empate: a mais recente), as
        tecnologias e os modelos de consulta que a acharam, o provedor da ocorrencia mais recente e a decisao de download
        (`selecionado`: True se alguma execucao a selecionou; `motivo_descarte`: o ultimo motivo, se nunca foi selecionada).
        Os TEXTOS dos termos nao estao no banco: quem chama os resolve (`dominio.triagem_escopo.montar_termos`)."""
        if fonte == "artigo":
            return self._itens_artigo()
        if fonte == "web":
            return self._itens_web()
        raise ValueError(f"fonte deve ser 'artigo' ou 'web', nao {fonte!r}")

    def _itens_artigo(self):
        termos, origens = {}, {}
        for l in self.conn.execute("SELECT artigo_id, termo_id FROM r_ocorrencias ORDER BY ocorrencia_id"):
            termos.setdefault(l["artigo_id"], []).append(l["termo_id"])
        com_scholar = set(termos)
        for l in self.conn.execute("SELECT artigo_id, termo_id, base FROM ocorrencias_manuais ORDER BY id"):
            termos.setdefault(l["artigo_id"], []).append(l["termo_id"])
            origens.setdefault(l["artigo_id"], []).append(l["base"])
        saida = []
        for a in self.conn.execute("SELECT * FROM r_artigos ORDER BY artigo_id").fetchall():
            link = a["link"]
            try:
                host = urlsplit(link).hostname or "" if link else ""
            except ValueError:
                host = ""
            i = a["artigo_id"]
            saida.append({"item_id": i, "fonte": "artigo", "uf": "",
                          "provedor": "serpapi_scholar" if i in com_scholar else "manual",
                          "titulo": a["titulo"], "resumo": a["snippet"] or "",
                          "autores_publicacao": a["autores_publicacao"] or "", "ano": a["ano"], "link": link, "host": host,
                          "termos_ids": list(dict.fromkeys(termos.get(i, []))),
                          "origens_manuais": list(dict.fromkeys(origens.get(i, [])))})
        return saida

    def _itens_web(self):
        decisao = {}
        for l in self.conn.execute("SELECT url_id, uf, selecionada, motivo FROM r_selecao_download ORDER BY run_id"):
            d = decisao.setdefault((l["url_id"], l["uf"]), {"selecionado": False, "motivo": None})
            if l["selecionada"]:
                d["selecionado"], d["motivo"] = True, None
            elif not d["selecionado"]:
                d["motivo"] = l["motivo"]
        grupos = {}
        for l in self.conn.execute(
                """SELECT r.resultado_id, r.url_id, r.uf, r.tecnologia, r.consulta_id, r.titulo, r.snippet, r.cidade,
                          u.url_original, u.dominio, c.provedor
                   FROM r_resultados_web r JOIN urls u ON u.url_id = r.url_id
                   LEFT JOIN chamadas c ON c.chamada_id = r.chamada_id ORDER BY r.resultado_id"""):
            g = grupos.setdefault((l["url_id"], l["uf"]), {"linhas": []})
            g["linhas"].append(l)
        saida = []
        for (url_id, uf), g in sorted(grupos.items()):
            linhas = g["linhas"]
            melhor = max(linhas, key=lambda l: (len(l["snippet"] or ""), l["resultado_id"]))
            d = decisao.get((url_id, uf), {"selecionado": None, "motivo": None})
            tecnologias = list(dict.fromkeys(l["tecnologia"] for l in linhas if l["tecnologia"]))
            saida.append({"item_id": url_id, "fonte": "web", "uf": uf, "provedor": linhas[-1]["provedor"],
                          "titulo": melhor["titulo"] or "", "resumo": melhor["snippet"] or "",
                          "url": melhor["url_original"], "host": melhor["dominio"] or "",
                          "tecnologia": tecnologias[0] if tecnologias else "", "tecnologias": tecnologias,
                          "modelos_ids": list(dict.fromkeys(l["consulta_id"].split("-")[0] for l in linhas)),
                          "cidade": next((l["cidade"] for l in linhas if l["cidade"]), ""),
                          "selecionado": d["selecionado"], "motivo_descarte": d["motivo"]})
        return saida

    def salvar_triagem_escopo(self, run_id, chamada_id, prompt_versao, linhas):
        """Grava as linhas validadas de um lote. Idempotente por (run_id, fonte, item_id, uf): repetir substitui."""
        for l in linhas:
            self.conn.execute(
                """INSERT INTO triagem_escopo (run_id, chamada_id, fonte, item_id, uf, provedor, termos_consulta, status,
                       status_bruto, confianca, categoria_motivo, justificativa, termo_gerador, sinal_negativo,
                       dominio_tematico, escopo_geografico, tipo_documento, valido, problemas, prompt_versao, criado_em)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(run_id, fonte, item_id, uf) DO UPDATE SET
                       chamada_id=excluded.chamada_id, provedor=excluded.provedor, termos_consulta=excluded.termos_consulta,
                       status=excluded.status, status_bruto=excluded.status_bruto, confianca=excluded.confianca,
                       categoria_motivo=excluded.categoria_motivo, justificativa=excluded.justificativa,
                       termo_gerador=excluded.termo_gerador, sinal_negativo=excluded.sinal_negativo,
                       dominio_tematico=excluded.dominio_tematico, escopo_geografico=excluded.escopo_geografico,
                       tipo_documento=excluded.tipo_documento, valido=excluded.valido, problemas=excluded.problemas,
                       prompt_versao=excluded.prompt_versao, criado_em=excluded.criado_em""",
                (run_id, chamada_id, l["fonte"], l["item_id"], l["uf"] or "", l.get("provedor"),
                 json.dumps(l.get("termos_consulta") or [], ensure_ascii=False), l["status"], l.get("status_bruto"),
                 l.get("confianca"), l.get("categoria_motivo"), l.get("justificativa"), l.get("termo_gerador"),
                 l.get("sinal_negativo"), l.get("dominio_tematico"), l.get("escopo_geografico"), l.get("tipo_documento"),
                 int(bool(l["valido"])), json.dumps(l.get("problemas") or [], ensure_ascii=False), prompt_versao, agora()))
        return len(linhas)

    def triagem_escopo_ja_feita(self, run_id, fonte, item_id, uf=""):
        """O item ja tem linha de triagem de escopo nesta execucao?"""
        return self.conn.execute("SELECT 1 FROM triagem_escopo WHERE run_id=? AND fonte=? AND item_id=? AND uf=?",
                                 (run_id, fonte, item_id, uf or "")).fetchone() is not None

    def triagem_escopo_feita_por_versao(self, fonte, prompt_versao):
        """{(item_id, uf)} que o modelo ja respondeu, em qualquer execucao, com esta versao do prompt. Linhas em que o
        modelo nao respondeu (id ausente, JSON invalido: `status_bruto` nulo) nao contam: o item pode ser repetido."""
        return {(l["item_id"], l["uf"]) for l in self.conn.execute(
            "SELECT item_id, uf FROM triagem_escopo WHERE fonte=? AND prompt_versao=? AND status_bruto IS NOT NULL",
            (fonte, prompt_versao))}

    def triagem_escopo_respondida(self, fonte):
        """{(item_id, uf)} que o modelo ja respondeu (`status_bruto` nao nulo), em qualquer execucao e com qualquer versao
        do prompt."""
        return {(l["item_id"], l["uf"]) for l in self.conn.execute(
            "SELECT item_id, uf FROM triagem_escopo WHERE fonte=? AND status_bruto IS NOT NULL", (fonte,))}

    def custo_execucao(self, run_id):
        """Custo (US$) ja gravado em `chamadas` para a execucao."""
        return self.conn.execute("SELECT COALESCE(SUM(custo_usd), 0) FROM chamadas WHERE run_id=?", (run_id,)).fetchone()[0]

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
            "Municipios": "SELECT * FROM v_resumo_municipio",
            "Chamadas": "SELECT * FROM chamadas ORDER BY chamada_id",
            "Metricas_termo": "SELECT * FROM v_metricas_por_termo",
            "Artigos": "SELECT * FROM artigos ORDER BY COALESCE(citacoes,0) DESC, artigo_id",
            "Artigos_ano": "SELECT * FROM v_artigos_por_ano",
            "Multi_termo": "SELECT * FROM v_artigos_multi_termo",
            "Sobreposicao": "SELECT * FROM v_sobreposicao_termos",
            "Triagem": """SELECT a.artigo_id, a.titulo, a.ano, a.link, a.citacoes,
                                 (SELECT e.status || CASE WHEN e.categoria_motivo IS NOT NULL
                                                          THEN ': ' || e.categoria_motivo ELSE '' END
                                  FROM triagem_escopo e WHERE e.fonte='artigo' AND e.item_id=a.artigo_id AND e.uf=''
                                  ORDER BY e.id DESC LIMIT 1) AS triagem_llm,
                                 COALESCE(t.decisao,'pendente') AS decisao, t.motivo,
                                 t.confirmado_em_base, t.link_confirmado, t.revisor, t.revisado_em,
                                 t.decisao_texto_completo, t.motivo_texto_completo
                          FROM artigos a LEFT JOIN triagem t ON t.artigo_id=a.artigo_id
                          ORDER BY COALESCE(a.citacoes,0) DESC, a.artigo_id""",
            # opiniao do modelo (a ultima por item), sem esconder nada: `excluido` e `quarentena` aparecem junto com os demais
            "Triagem_escopo": """SELECT e.fonte, e.item_id, e.uf,
                                        CASE e.fonte WHEN 'artigo' THEN (SELECT a.titulo FROM artigos a WHERE a.artigo_id=e.item_id)
                                                     ELSE (SELECT u.url_original FROM urls u WHERE u.url_id=e.item_id) END AS item,
                                        e.status, e.status_bruto, e.confianca, e.categoria_motivo, e.justificativa,
                                        e.termo_gerador, e.sinal_negativo, e.dominio_tematico, e.escopo_geografico,
                                        e.tipo_documento, e.valido, e.problemas, e.termos_consulta, e.provedor,
                                        e.prompt_versao, e.run_id, e.chamada_id, e.criado_em
                                 FROM triagem_escopo e
                                 WHERE e.id = (SELECT MAX(x.id) FROM triagem_escopo x
                                               WHERE x.fonte=e.fonte AND x.item_id=e.item_id AND x.uf=e.uf)
                                 ORDER BY e.fonte, e.item_id, e.uf""",
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
            "Revisores_kappa_achados": "SELECT * FROM v_concordancia_revisores_achados",
            "Discordancias_achados": "SELECT * FROM v_discordancias_achados",
            "Auditoria_negativos": "SELECT * FROM v_auditoria_negativos",
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

    @staticmethod
    def _carimbo(valor):
        """Carimbo de tempo de uma celula da planilha como texto ('' se vazia)."""
        v = _v(valor)
        return "" if v is None else str(v).strip()

    def _ids_validos(self, pares, coluna, tabela, chave, rotulo):
        """Confere, antes de gravar qualquer coisa, que todo identificador da planilha e um inteiro que existe.
        `pares` = [(linha da planilha, valor)], com o cabecalho na linha 1. Devolve os inteiros na mesma ordem."""
        ids = []
        for linha, bruto in pares:
            try:
                ids.append(int(float(str(bruto).strip())))
            except (TypeError, ValueError):
                raise SystemExit(f"{coluna} invalido: {bruto!r} (linha {linha})")
        existentes = {r[0] for r in self.conn.execute(
            f"SELECT {chave} FROM {tabela} WHERE {chave} IN ({','.join('?' for _ in ids) or 'NULL'})", ids)}
        for (linha, _), i in zip(pares, ids):
            if i not in existentes:
                raise SystemExit(f"{rotulo} inexistente: {i} (linha {linha})")
        return ids

    def importar_triagem(self, df, so_historico=False):
        """Importa a aba Triagem. Toda decisao entra no historico (`triagem_revisoes`), por revisor.

        Com so_historico=True a decisao NAO altera `triagem` (revisao independente, antes do consenso).
        Tudo e validado antes da primeira gravacao: um erro de digitacao nao deixa o lote pela metade.
        """
        validos = {"pendente", "incluir", "excluir"}
        tem_tc = "decisao_texto_completo" in df.columns
        ids = self._ids_validos([(pos + 2, v) for pos, v in enumerate(df["artigo_id"])], "artigo_id", "artigos", "artigo_id", "Artigo")
        self.conflitos_importacao = []
        confere_versao = "revisado_em" in df.columns and not so_historico
        atuais = {}
        if confere_versao:
            atuais = {r[0]: (r[1] or "") for r in self.conn.execute("SELECT artigo_id, revisado_em FROM triagem")}
        linhas = []
        for pos, (_, r) in enumerate(df.iterrows()):
            dec = str(_v(r["decisao"]) or "pendente").strip().lower()
            if dec not in validos:
                raise SystemExit(f"Invalid decision for article {ids[pos]}: {dec} (linha {pos + 2})")
            tc = motivo_tc = None
            if tem_tc:
                tc = str(_v(r["decisao_texto_completo"]) or "").strip().lower() or None
                if tc is not None and tc not in validos:
                    raise SystemExit(f"Invalid full-text decision for article {ids[pos]}: {tc} (linha {pos + 2})")
                if "motivo_texto_completo" in df.columns:
                    motivo_tc = _v(r["motivo_texto_completo"])
            if confere_versao and self._carimbo(r["revisado_em"]) != atuais.get(ids[pos], ""):
                self.conflitos_importacao.append((ids[pos], pos + 2))        # o banco mudou depois da exportacao
                continue                                                      # (o erro de digitacao acima ja foi pego)
            linhas.append((ids[pos], r, dec, tc, motivo_tc))
        for artigo_id, r, dec, tc, motivo_tc in linhas:
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
        return len(df) - len(self.conflitos_importacao)

    def _estado_achado(self, achado_id):
        l = self.conn.execute("""SELECT verificado, status_final, verificado_por, verificado_em, observacao FROM achados
                                 WHERE achado_id=?""", (achado_id,)).fetchone()
        if l is None:
            raise SystemExit(f"Achado inexistente: {achado_id}")
        return dict(l)

    def _iniciar_escrita(self, achado_id, versao=None):
        """Abre uma transacao que ja trava o banco para escrita (nenhuma outra escrita entra entre a conferencia e a
        gravacao) e confere a versao da pagina: `versao` e o `verificado_em` que o revisor viu (`NAO_VERIFICADO` se nao havia; o
        formulario nao pode mandar texto vazio, que o FastAPI trata como ausente)."""
        if not self.conn.in_transaction:
            self.conn.execute("BEGIN IMMEDIATE")
        estado = self._estado_achado(achado_id)
        if versao is not None and (estado["verificado_em"] or NAO_VERIFICADO) != versao:
            quem = f" (verificado por {estado['verificado_por']})" if estado["verificado"] else ""
            raise SystemExit(f"O achado {achado_id} mudou depois que a página foi aberta{quem}: recarregue a página e decida de novo")
        return estado

    def _gravar_verificacao(self, achado_id, final, por, obs, com_desfazer=False, so_historico=False):
        """`so_historico` (revisao independente): a decisao entra so em `achados_revisoes` (independente = 1) e o achado
        nao muda; a deduplicacao vale por (achado, revisor, tipo), como na triagem."""
        revisor = str(por or "").strip() or "(sem revisor)"
        quando = agora()
        if so_historico:
            ultima = self.conn.execute(
                """SELECT status_final, observacao FROM achados_revisoes WHERE achado_id=? AND verificado_por=? AND independente=1
                   ORDER BY revisao_id DESC LIMIT 1""", (achado_id, revisor)).fetchone()
            if ultima is None or tuple(ultima) != (final, obs):
                self._inserir("achados_revisoes", achado_id=achado_id, verificado_por=revisor, status_final=final,
                              observacao=obs, importado_em=quando, independente=1)
            return
        anterior = json.dumps(self._estado_achado(achado_id), ensure_ascii=False) if com_desfazer else None
        self.conn.execute(
            """UPDATE achados SET verificado=1, status_final=?, verificado_por=?, verificado_em=?,
               observacao=? WHERE achado_id=?""", (final, por, quando, obs, achado_id))
        if com_desfazer:
            # decisao do painel: sempre uma linha, para poder desfazer; guarda tambem o estado que ela produziu
            posterior = json.dumps({"verificado": 1, "status_final": final, "verificado_por": por,
                                    "verificado_em": quando, "observacao": obs}, ensure_ascii=False)
            self._inserir("achados_revisoes", achado_id=achado_id, verificado_por=revisor, status_final=final,
                          observacao=obs, importado_em=quando, anterior_json=anterior, posterior_json=posterior)
            return
        # importacao: so grava se mudou em relacao a ultima verificacao da mesma pessoa
        ultima = self.conn.execute(
            """SELECT status_final, observacao FROM achados_revisoes WHERE achado_id=? AND verificado_por=? AND independente=0
               ORDER BY revisao_id DESC LIMIT 1""", (achado_id, revisor)).fetchone()
        if ultima is None or tuple(ultima) != (final, obs):
            self._inserir("achados_revisoes", achado_id=achado_id, verificado_por=revisor, status_final=final,
                          observacao=obs, importado_em=quando)

    def verificar_achado(self, achado_id, status_final, revisor, observacao=None, status_permitidos=None, versao=None):
        """Decisao humana de um achado (painel). Valida o status com a mesma regra da importacao, exige o revisor e,
        com `versao`, recusa a decisao se o achado mudou desde que a pagina foi aberta."""
        revisor = str(revisor or "").strip()
        if not revisor:
            raise SystemExit("Informe o nome do revisor")
        final = normalizar_status_final(status_final, status_permitidos) if status_permitidos is not None \
            else (str(status_final).strip().lower() or None)
        if final is None:
            raise SystemExit(f"Invalid status_final for finding {achado_id}: {str(status_final).strip()!r}")
        try:
            self._iniciar_escrita(achado_id, versao)
            self._gravar_verificacao(achado_id, final, revisor, (observacao or "").strip() or None, com_desfazer=True)
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise

    def registrar_triagem(self, artigo_id, decisao, revisor, motivo=None, confirmado_em_base=None, link_confirmado=None,
                          etapa="titulo_resumo", versao=None):
        """Decisao humana sobre um artigo (painel), uma por vez. `etapa`: 'titulo_resumo' ou 'texto_completo' (so para
        artigo incluido). Entra no historico (`triagem_revisoes`) e, com `versao`, recusa a decisao se a triagem do artigo
        mudou desde que a pagina foi aberta (`NAO_TRIADO` se nao havia decisao)."""
        validos = {"pendente", "incluir", "excluir"}
        decisao = str(decisao or "").strip().lower()
        revisor = str(revisor or "").strip()
        if decisao not in validos:
            raise SystemExit(f"Invalid decision for article {artigo_id}: {decisao}")
        if not revisor:
            raise SystemExit("Informe o nome do revisor")
        if etapa not in ("titulo_resumo", "texto_completo"):
            raise SystemExit(f"Etapa invalida: {etapa}")
        motivo = (motivo or "").strip() or None
        try:
            if not self.conn.in_transaction:
                self.conn.execute("BEGIN IMMEDIATE")
            if not self.conn.execute("SELECT 1 FROM artigos WHERE artigo_id=?", (artigo_id,)).fetchone():
                raise SystemExit(f"Artigo inexistente: {artigo_id}")
            atual = self.conn.execute("SELECT * FROM triagem WHERE artigo_id=?", (artigo_id,)).fetchone()
            if versao is not None and ((atual["revisado_em"] if atual else None) or NAO_TRIADO) != versao:
                quem = f" (por {atual['revisor']})" if atual and atual["revisor"] else ""
                raise SystemExit(f"A triagem do artigo {artigo_id} mudou depois que a página foi aberta{quem}: "
                                 "recarregue a página e decida de novo")
            quando = agora()
            if etapa == "titulo_resumo":
                tc = atual["decisao_texto_completo"] if atual else None
                motivo_tc = atual["motivo_texto_completo"] if atual else None
                self.conn.execute(
                    """INSERT INTO triagem (artigo_id, decisao, motivo, confirmado_em_base, link_confirmado, revisor, revisado_em)
                       VALUES (?,?,?,?,?,?,?)
                       ON CONFLICT(artigo_id) DO UPDATE SET decisao=excluded.decisao, motivo=excluded.motivo,
                         confirmado_em_base=excluded.confirmado_em_base, link_confirmado=excluded.link_confirmado,
                         revisor=excluded.revisor, revisado_em=excluded.revisado_em""",
                    (artigo_id, decisao, motivo, (confirmado_em_base or "").strip() or None,
                     (link_confirmado or "").strip() or None, revisor, quando))
            else:
                if not atual or atual["decisao"] != "incluir":
                    raise SystemExit(f"O artigo {artigo_id} precisa estar incluído por título e resumo antes da etapa de texto completo")
                tc, motivo_tc = decisao, motivo
                self.conn.execute("""UPDATE triagem SET decisao_texto_completo=?, motivo_texto_completo=?, revisor=?, revisado_em=?
                                     WHERE artigo_id=?""", (tc, motivo_tc, revisor, quando, artigo_id))
                decisao, motivo = atual["decisao"], atual["motivo"]
            self._registrar_revisao_triagem(artigo_id, revisor, decisao, motivo, tc, motivo_tc, 0)
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise

    def _decisao_atual(self, alvo_tipo, alvo_id):
        """(decidido, valor, autor, ficha, versao) da decisao de hoje de um achado ou de um artigo (titulo e resumo)."""
        if alvo_tipo == "achado":
            l = self.conn.execute(f"SELECT {', '.join(CAMPOS_ACHADO)} FROM achados WHERE achado_id=?", (alvo_id,)).fetchone()
            if l is None:
                raise SystemExit(f"Achado inexistente: {alvo_id!r}")
            return (bool(l["verificado"]), l["status_final"], l["verificado_por"], ficha_da_decisao(tuple(l)),
                    l["verificado_em"] or NAO_VERIFICADO)
        if not self.conn.execute("SELECT 1 FROM artigos WHERE artigo_id=?", (alvo_id,)).fetchone():
            raise SystemExit(f"Artigo inexistente: {alvo_id!r}")
        t = self.conn.execute(f"SELECT {', '.join(CAMPOS_ARTIGO)} FROM triagem WHERE artigo_id=?", (alvo_id,)).fetchone()
        if t is not None and t["decisao_texto_completo"] is not None:
            raise SystemExit("Este artigo já tem decisão de texto completo: as sugestões valem só para a triagem por título e resumo.")
        valores = tuple(t) if t is not None else (None,) * len(CAMPOS_ARTIGO)
        decidido = t is not None and t["decisao"] in ("incluir", "excluir")
        return (decidido, (t["decisao"] if t else None), (t["revisor"] if t else None), ficha_da_decisao(valores),
                (t["revisado_em"] if t else None) or NAO_TRIADO)

    def criar_sugestao(self, alvo_tipo, alvo_id, valor, motivo, autor, estado):
        """Grava uma sugestao aberta sobre a decisao atual de um achado ou artigo (D78). `estado` e a ficha que a pagina mostrou."""
        try:
            if alvo_tipo not in ("achado", "artigo"):
                raise SystemExit(f"Tipo de item inválido: {alvo_tipo!r}.")
            autor = str(autor or "").strip()
            if not autor:
                raise SystemExit("Informe o nome do revisor")
            if not (type(alvo_id) is int and 1 <= alvo_id <= 9223372036854775807):
                raise SystemExit(f"{'Achado' if alvo_tipo == 'achado' else 'Artigo'} inexistente: {alvo_id!r}")
            if not self.conn.in_transaction:
                self.conn.execute("BEGIN IMMEDIATE")
            decidido, atual_valor, atual_autor, ficha, _ = self._decisao_atual(alvo_tipo, alvo_id)
            if estado != ficha:
                raise SystemExit("A decisão deste item mudou depois que a página foi aberta: recarregue a página antes de sugerir")
            if not decidido:
                raise SystemExit("Só se sugere sobre um item já decidido.")
            chave = chave_autor(autor)
            if chave == chave_autor(atual_autor):
                raise SystemExit("Quem tomou a decisão não sugere: decida de novo.")
            if valor == atual_valor:
                raise SystemExit("O valor sugerido é igual à decisão atual.")
            if self.conn.execute("""SELECT 1 FROM sugestoes WHERE alvo_tipo=? AND alvo_id=? AND autor_chave=? AND valor=?
                                    AND estado_alvo=? AND situacao='aberta'""", (alvo_tipo, alvo_id, chave, valor, ficha)).fetchone():
                raise SystemExit("Você já sugeriu este valor para este item.")
            cur = self.conn.execute("""INSERT INTO sugestoes (alvo_tipo, alvo_id, valor, motivo, autor, autor_chave, estado_alvo, valor_alvo,
                                       criado_em, situacao) VALUES (?,?,?,?,?,?,?,?,?,'aberta')""",
                                    (alvo_tipo, alvo_id, valor, motivo, autor, chave, ficha, atual_valor, agora()))
            self.conn.commit()
            return cur.lastrowid
        except BaseException:
            self.conn.rollback()
            raise

    def _abrir_sugestao(self, sugestao_id, resolvedor):
        resolvedor = str(resolvedor or "").strip()
        if not resolvedor:
            raise SystemExit("Informe o nome do revisor")
        if not (type(sugestao_id) is int and 1 <= sugestao_id <= 9223372036854775807):
            raise SystemExit(f"Sugestão inexistente: {sugestao_id!r}")
        if not self.conn.in_transaction:
            self.conn.execute("BEGIN IMMEDIATE")
        s = self.conn.execute("SELECT * FROM sugestoes WHERE sugestao_id=?", (sugestao_id,)).fetchone()
        if s is None:
            raise SystemExit(f"Sugestão inexistente: {sugestao_id!r}")
        if s["situacao"] != "aberta":
            raise SystemExit("Esta sugestão já foi resolvida.")
        return dict(s), resolvedor

    def aceitar_sugestao(self, sugestao_id, resolvedor, status_permitidos):
        """Aceita: a sugestao vira uma decisao nova de quem aceita, pela gravacao de sempre, na mesma transacao; as outras
        sugestoes abertas do item sao descartadas."""
        try:
            s, resolvedor = self._abrir_sugestao(sugestao_id, resolvedor)
            if chave_autor(resolvedor) == s["autor_chave"]:
                raise SystemExit("Quem sugeriu não aceita a própria sugestão.")
            _, _, _, ficha, versao = self._decisao_atual(s["alvo_tipo"], s["alvo_id"])
            if ficha != s["estado_alvo"]:
                raise SystemExit("Esta sugestão foi feita sobre uma decisão que já mudou: descarte-a ou sugira de novo.")
            quando = agora()
            self.conn.execute("UPDATE sugestoes SET situacao='aceita', resolvido_por=?, resolvido_em=? WHERE sugestao_id=?",
                              (resolvedor, quando, sugestao_id))
            self.conn.execute("""UPDATE sugestoes SET situacao='descartada', resolvido_por=?, resolvido_em=?
                                 WHERE alvo_tipo=? AND alvo_id=? AND situacao='aberta' AND sugestao_id<>?""",
                              (resolvedor, quando, s["alvo_tipo"], s["alvo_id"], sugestao_id))
            if s["alvo_tipo"] == "achado":
                obs = s["motivo"] if s["motivo"].strip() else self._estado_achado(s["alvo_id"])["observacao"]
                self.verificar_achado(s["alvo_id"], s["valor"], resolvedor, obs, status_permitidos, versao)
            else:
                t = self.conn.execute("SELECT confirmado_em_base, link_confirmado FROM triagem WHERE artigo_id=?", (s["alvo_id"],)).fetchone()
                self.registrar_triagem(s["alvo_id"], s["valor"], resolvedor, s["motivo"], t["confirmado_em_base"] if t else None,
                                       t["link_confirmado"] if t else None, "titulo_resumo", versao)
        except BaseException:
            self.conn.rollback()
            raise

    def descartar_sugestao(self, sugestao_id, resolvedor):
        """Descarta: a decisao atual nao muda."""
        try:
            s, resolvedor = self._abrir_sugestao(sugestao_id, resolvedor)
            self.conn.execute("UPDATE sugestoes SET situacao='descartada', resolvido_por=?, resolvido_em=? WHERE sugestao_id=?",
                              (resolvedor, agora(), sugestao_id))
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise

    def desfazer_ultima_decisao(self, achado_id):
        """Volta o achado ao estado anterior a ultima decisao do painel que ainda nao foi desfeita, mas so se o achado
        ainda esta como essa decisao o deixou: se outra pessoa verificou depois (painel ou planilha), recusa."""
        try:
            atual = self._iniciar_escrita(achado_id)
            l = self.conn.execute("""SELECT revisao_id, anterior_json, posterior_json FROM achados_revisoes WHERE achado_id=?
                                     AND anterior_json IS NOT NULL AND posterior_json IS NOT NULL AND desfeita=0
                                     ORDER BY revisao_id DESC LIMIT 1""", (achado_id,)).fetchone()
            if l is None:
                raise SystemExit(f"Nada a desfazer no achado {achado_id}")
            if json.loads(l["posterior_json"]) != atual:
                quem = f" por {atual['verificado_por']}" if atual["verificado"] else ""
                raise SystemExit(f"O achado {achado_id} foi alterado depois desta decisão{quem}: desfazer apagaria esse "
                                 "trabalho. Se a verificação atual estiver errada, use Revogar verificação")
            e = json.loads(l["anterior_json"])
            self.conn.execute("""UPDATE achados SET verificado=?, status_final=?, verificado_por=?, verificado_em=?,
                                 observacao=? WHERE achado_id=?""",
                              (e["verificado"], e["status_final"], e["verificado_por"], e["verificado_em"], e["observacao"], achado_id))
            self.conn.execute("UPDATE achados_revisoes SET desfeita=1 WHERE revisao_id=?", (l["revisao_id"],))
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise

    def desverificar_achado(self, achado_id, revisor, motivo, versao=None):
        """Revoga a verificacao (verificado = 0, sem status final) e registra isso no historico. Diferente de
        `desfazer_ultima_decisao`: nao volta a nenhum estado anterior, tira a verificacao (de qualquer origem)."""
        try:
            estado = self._iniciar_escrita(achado_id, versao)
            if not estado["verificado"]:
                raise SystemExit(f"Achado {achado_id} nao esta verificado")
            self.conn.execute("""UPDATE achados SET verificado=0, status_final=NULL, verificado_por=NULL, verificado_em=NULL
                                 WHERE achado_id=?""", (achado_id,))
            posterior = {"verificado": 0, "status_final": None, "verificado_por": None, "verificado_em": None,
                         "observacao": estado["observacao"]}
            self._inserir("achados_revisoes", achado_id=achado_id, verificado_por=str(revisor or "").strip() or "(sem revisor)",
                          status_final=None, observacao=f"verificacao desfeita: {motivo}".strip(": "), importado_em=agora(),
                          anterior_json=json.dumps(estado, ensure_ascii=False), posterior_json=json.dumps(posterior, ensure_ascii=False))
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise

    def copia_de_seguranca(self, pasta, manter=10, sufixo="painel"):
        """Copia consistente do banco (API de backup do SQLite) em `pasta`, chamada `<banco>_<sufixo>_<data>.db`; mantem as
        `manter` mais recentes com esse sufixo (`manter=None` mantem todas)."""
        pasta = Path(pasta)
        pasta.mkdir(parents=True, exist_ok=True)
        nome = Path(self.conn.execute("PRAGMA database_list").fetchone()["file"]).stem
        destino = pasta / f"{nome}_{sufixo}_{datetime.now():%Y%m%d_%H%M%S}.db"
        copia = sqlite3.connect(destino)
        try:
            self.conn.backup(copia)
        finally:
            copia.close()
        if manter is not None:
            for antiga in sorted(pasta.glob(f"{nome}_{sufixo}_*.db"))[:-manter]:
                antiga.unlink()
        return str(destino)

    def reclassificar_bloqueios_robots(self, aplicar=False, pasta_backup=None):
        """Separa, nas chamadas de download ja gravadas, a proibicao do site da falha de leitura do robots.txt.

        Antes, `bloqueado_por_robots` valia para os dois casos. Cada chamada com `erro LIKE 'bloqueado_por_robots%'` e decidida
        pelo status do robots.txt guardado em `extras_json` (`robots_status`; nas variantes de redirecionamento, o do
        ultimo salto `robots_salto_N` cuja consulta proibiu): 2xx = o robots.txt foi lido e proibe, a chamada fica como esta;
        >= 500 ou sem status (tempo esgotado, rede) = nao foi possivel le-lo, vira `robots_inacessivel` (ou
        `robots_inacessivel_apos_redirecionamento: <url>`); qualquer outro status fica como esta e e contado a parte.

        Sem `aplicar` so conta (nada e gravado). Com `aplicar` faz antes uma copia de seguranca (`pasta_backup`, padrao a pasta
        `backups` ao lado do banco), atualiza `chamadas.erro` e `extras_json` (`robots_inacessivel = true`, `erro_anterior`)
        numa unica transacao e registra os totais no log. Idempotente: as linhas ja migradas nao casam mais com o filtro.
        Nao mexe nos arquivos brutos nem em outra tabela. Devolve {total, mantidas_proibido, para_inacessivel,
        outro_status, atualizadas, backup, por_classe: {...}}."""
        linhas = self.conn.execute("SELECT chamada_id, erro, extras_json FROM chamadas "
                                   "WHERE etapa='download' AND erro LIKE 'bloqueado_por_robots%' ORDER BY chamada_id").fetchall()
        res = {"total": len(linhas), "mantidas_proibido": 0, "para_inacessivel": 0, "outro_status": 0, "atualizadas": 0,
               "backup": None, "por_classe": {"status_2xx": 0, "status_5xx": 0, "sem_status": 0, "outro_status": 0}}
        mudancas = []
        prefixo_salto = "bloqueado_por_robots_apos_redirecionamento"
        for l in linhas:
            try:
                extras = json.loads(l["extras_json"] or "{}")
            except ValueError:
                extras = {}
            erro = l["erro"]
            salto = erro.startswith(prefixo_salto)
            if salto:
                saltos = sorted((int(k[len("robots_salto_"):-len("_permitido")]) for k, v in extras.items()
                                 if k.startswith("robots_salto_") and k.endswith("_permitido") and v is False), reverse=True)
                status = extras.get(f"robots_salto_{saltos[0]}_status") if saltos else None
            else:
                status = extras.get("robots_status")
            if not isinstance(status, int) or isinstance(status, bool):
                status = None
            if status is None:
                classe = "sem_status"
            elif 200 <= status < 300:
                classe = "status_2xx"
            elif status >= 500:
                classe = "status_5xx"
            else:
                classe = "outro_status"
            res["por_classe"][classe] += 1
            if classe == "status_2xx":
                res["mantidas_proibido"] += 1
            elif classe == "outro_status":
                res["outro_status"] += 1
            else:
                res["para_inacessivel"] += 1
                novo_erro = "robots_inacessivel" + erro[len("bloqueado_por_robots"):]
                if salto:
                    novo_erro = "robots_inacessivel_apos_redirecionamento" + erro[len(prefixo_salto):]
                extras["robots_inacessivel"] = True
                extras["erro_anterior"] = erro
                mudancas.append((novo_erro, json.dumps(extras, ensure_ascii=False, default=str), l["chamada_id"]))
        if not aplicar or not mudancas:
            return res
        res["backup"] = self.copia_de_seguranca(pasta_backup or Path(self.conn.execute("PRAGMA database_list").fetchone()["file"]).parent / "backups",
                                                manter=None, sufixo="antes_migrar_robots")
        try:
            self.conn.executemany("UPDATE chamadas SET erro=?, extras_json=? WHERE chamada_id=?", mudancas)
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise
        res["atualizadas"] = len(mudancas)
        logging.info("migrar-robots: %d chamadas de download com bloqueado_por_robots | mantidas como proibicao do site: %d | "
                     "reclassificadas para robots_inacessivel: %d | outro status: %d | copia: %s", res["total"],
                     res["mantidas_proibido"], res["para_inacessivel"], res["outro_status"], res["backup"])
        return res

    def fechar(self):
        self.conn.close()

    def importar_verificacao_achados(self, df, status_permitidos, so_historico=False):
        """Importa a aba Achados. So linhas com verificado = 1 entram; verificado = 0 e ignorado de proposito (uma
        planilha exportada antes do trabalho de outro revisor nao pode apagar o que ele fez): para desfazer uma
        verificacao use `desverificar_achado` (painel). Tudo e validado antes da primeira gravacao.

        Com so_historico=True (revisao independente, `achados-importar --independente`) a decisao NAO altera o achado: entra
        so no historico (`achados_revisoes.independente = 1`) e alimenta o kappa entre revisores; nao ha conferencia de versao,
        porque nada do achado e sobrescrito."""
        selecionadas = []
        for pos, (_, r) in enumerate(df.iterrows()):
            try:
                marcado = not pd.isna(r["verificado"]) and int(float(r["verificado"])) == 1
            except (TypeError, ValueError):
                raise SystemExit(f"verificado invalido: {r['verificado']!r} (linha {pos + 2})")
            if marcado:
                selecionadas.append((pos, r))
        ids = self._ids_validos([(pos + 2, r["achado_id"]) for pos, r in selecionadas], "achado_id", "achados",
                                "achado_id", "Achado")
        self.conflitos_importacao = []
        registros = []
        confere_versao = "verificado_em" in df.columns and not so_historico
        atuais = {r[0]: (r[1] or "") for r in self.conn.execute("SELECT achado_id, verificado_em FROM achados")} if confere_versao else {}
        for (pos, r), achado_id in zip(selecionadas, ids):
            bruto_final = _v(r["status_final"])
            final = normalizar_status_final(bruto_final, status_permitidos)
            if final is None:
                raise SystemExit(f"Invalid status_final for finding {achado_id}: "
                                 f"{None if bruto_final is None else str(bruto_final).strip()!r} (linha {pos + 2})")
            if confere_versao and self._carimbo(r["verificado_em"]) != atuais.get(achado_id, ""):
                self.conflitos_importacao.append((achado_id, pos + 2))       # verificado por outra pessoa depois da exportacao
                continue
            registros.append((achado_id, final, _v(r["verificado_por"]), _v(r["observacao"])))
        if registros and not so_historico:
            marcas = ",".join("?" for _ in registros)
            fora = [r[0] for r in self.conn.execute(
                f"""SELECT a.achado_id FROM achados a JOIN classificacoes k ON k.classificacao_id=a.classificacao_id
                    JOIN execucoes e ON e.run_id=k.run_id WHERE e.no_relatorio=0 AND a.achado_id IN ({marcas})""",
                [x[0] for x in registros])]
            if fora:
                logging.warning("Achados de execucao fora do relatorio (nao entram em Secretarias nem em Resumo_UF): %s",
                                ", ".join(str(i) for i in sorted(fora)))
        for achado_id, final, por, obs in registros:
            self._gravar_verificacao(achado_id, final, por, obs, so_historico=so_historico)
        self.conn.commit()
        return len(registros)

    def candidatos_auditoria_negativos(self):
        """Paginas que o modelo classificou SEM achados e que ainda nao foram conferidas por ninguem (`v_negativos_auditaveis`
        menos as que ja estao em `auditoria_negativos`): classificacao_id, uf, url_id, url, texto_path (arquivo do texto
        extraido, para a pessoa ler), classificador, prompt_versao, run_id. Ja conferidas ficam fora, para uma nova amostra
        continuar o sorteio sem repetir pagina."""
        return [dict(l) for l in self.conn.execute(
            """SELECT n.classificacao_id, n.uf, n.url_id, u.url_original AS url, p.texto_path, n.classificador, n.prompt_versao,
                      n.run_id
               FROM v_negativos_auditaveis n JOIN urls u ON u.url_id = n.url_id LEFT JOIN paginas p ON p.pagina_id = n.pagina_id
               WHERE NOT EXISTS (SELECT 1 FROM auditoria_negativos a WHERE a.classificacao_id = n.classificacao_id)
               ORDER BY n.classificacao_id""")]

    def resumo_auditoria_negativos(self):
        """{n_auditadas, n_perdidas, n_universo} da auditoria dos negativos: paginas conferidas (por classificacao, como
        `v_auditoria_negativos`), quantas tinham aplicacao perdida e o universo auditavel (`v_negativos_auditaveis`)."""
        t = self.conn.execute("SELECT n_auditadas, n_com_aplicacao_perdida FROM v_auditoria_negativos WHERE grupo = 'total'").fetchone()
        universo = self.conn.execute("SELECT COUNT(*) FROM v_negativos_auditaveis").fetchone()[0]
        return {"n_auditadas": int(t[0] or 0) if t else 0, "n_perdidas": int(t[1] or 0) if t else 0, "n_universo": int(universo)}

    def achados_para_rotulagem(self):
        """Todos os achados vigentes (as colunas da aba Achados da exportacao, `v_achados_revisao`) mais `fonte_oficial_efetiva`
        (a mesma que `analises/h2_logistica.py` usa como preditor), como dicionarios, por `achado_id`. Inclui os ja verificados:
        quem chama conta e filtra. So le."""
        return [dict(l) for l in self.conn.execute(
            """SELECT v.*, COALESCE(v.fonte_oficial_final, v.fonte_oficial) AS fonte_oficial_efetiva
               FROM v_achados_revisao v ORDER BY v.achado_id""")]

    def artigos_para_rotulagem(self):
        """Artigos de `r_artigos` com o necessario para montar a aba Triagem da exportacao (mesmas colunas) e para estratificar:
        `titulo`, `snippet` e `autores_publicacao` (relevancia), `status_escopo` e `valido_escopo` (ultimo veredito do modelo,
        None se nao houve) e `decisao` ('pendente' se a pessoa ainda nao decidiu). Por `artigo_id`. So le."""
        return [dict(l) for l in self.conn.execute(
            """SELECT a.artigo_id, a.titulo, a.ano, a.link, a.citacoes, a.autores_publicacao, a.snippet,
                      e.status AS status_escopo, e.valido AS valido_escopo,
                      CASE WHEN e.status IS NULL THEN NULL
                           ELSE e.status || CASE WHEN e.categoria_motivo IS NOT NULL THEN ': ' || e.categoria_motivo ELSE '' END END AS triagem_llm,
                      COALESCE(t.decisao, 'pendente') AS decisao, t.motivo, t.confirmado_em_base, t.link_confirmado, t.revisor,
                      t.revisado_em, t.decisao_texto_completo, t.motivo_texto_completo
               FROM r_artigos a
               LEFT JOIN triagem t ON t.artigo_id = a.artigo_id
               LEFT JOIN triagem_escopo e ON e.id = (SELECT MAX(x.id) FROM triagem_escopo x
                                                     WHERE x.fonte = 'artigo' AND x.item_id = a.artigo_id AND x.uf = '')
               ORDER BY a.artigo_id""")]

    def linhas_catalogo(self):
        """Uma consulta SQL com as linhas do catalogo de referencias a partir de `r_artigos`."""
        sql = """
        WITH ult_triagem AS (
            SELECT item_id AS artigo_id, status AS status_escopo, tipo_documento, escopo_geografico, dominio_tematico
            FROM triagem_escopo
            WHERE fonte = 'artigo' AND uf = '' AND valido = 1
              AND id IN (
                  SELECT MAX(id) FROM triagem_escopo
                  WHERE fonte = 'artigo' AND uf = '' AND valido = 1
                  GROUP BY item_id
              )
        ),
        art_consultas AS (
            SELECT artigo_id, GROUP_CONCAT(query, '; ') AS consultas
            FROM (
                SELECT DISTINCT ro.artigo_id, vt.query
                FROM r_ocorrencias ro
                JOIN v_termos vt ON vt.termo_id = ro.termo_id
                ORDER BY vt.query
            )
            GROUP BY artigo_id
        ),
        art_termos AS (
            SELECT artigo_id, GROUP_CONCAT(termo_id, ', ') AS termos
            FROM (
                SELECT DISTINCT artigo_id, termo_id
                FROM r_ocorrencias
                ORDER BY termo_id
            )
            GROUP BY artigo_id
        )
        SELECT a.artigo_id, a.titulo, a.ano, a.link, a.autores_publicacao, a.citacoes,
               ut.status_escopo, ut.tipo_documento, ut.escopo_geografico, ut.dominio_tematico,
               ac.consultas, at.termos,
               COALESCE(tr.decisao, 'pendente') AS decisao,
               lr.categoria, lr.eixo, lr.prioridade, lr.status_leitura, lr.notas
        FROM r_artigos a
        LEFT JOIN ult_triagem ut ON ut.artigo_id = a.artigo_id
        LEFT JOIN triagem tr ON tr.artigo_id = a.artigo_id
        LEFT JOIN art_consultas ac ON ac.artigo_id = a.artigo_id
        LEFT JOIN art_termos at ON at.artigo_id = a.artigo_id
        LEFT JOIN leitura_referencias lr ON lr.artigo_id = a.artigo_id
        WHERE (ut.status_escopo IS NULL OR ut.status_escopo <> 'excluido')
          AND COALESCE(tr.decisao, 'pendente') <> 'excluir'
        ORDER BY a.artigo_id
        """
        return [dict(l) for l in self.conn.execute(sql)]

    def salvar_leitura(self, linhas):
        """Salva campos de leitura de referencias preenchidos em planilha."""
        if not linhas:
            return 0
        ids = [int(l["artigo_id"]) for l in linhas]
        ph = ",".join("?" for _ in ids)
        existentes = {r[0] for r in self.conn.execute(f"SELECT artigo_id FROM artigos WHERE artigo_id IN ({ph})", ids)}
        for l in linhas:
            if l["artigo_id"] not in existentes:
                raise ValueError(f"ID {l['artigo_id']}: nao existe no banco")

        atuais = {r["artigo_id"]: dict(r) for r in self.conn.execute(
            f"SELECT artigo_id, categoria, eixo, prioridade, status_leitura, notas FROM leitura_referencias WHERE artigo_id IN ({ph})",
            ids
        )}
        alteradas = 0
        for l in linhas:
            artigo_id = int(l["artigo_id"])
            cat = l["categoria"]
            eixo = l["eixo"]
            prio = l["prioridade"]
            status = l["status_leitura"] or "Nao iniciado"
            notas = l["notas"]
            atual = atuais.get(artigo_id)
            if atual is None:
                if cat is None and eixo is None and prio is None and status == "Nao iniciado" and notas is None:
                    continue
            else:
                if (atual["categoria"] == cat and
                    atual["eixo"] == eixo and
                    atual["prioridade"] == prio and
                    atual["status_leitura"] == status and
                    atual["notas"] == notas):
                    continue
            self.conn.execute(
                """INSERT INTO leitura_referencias (artigo_id, categoria, eixo, prioridade, status_leitura, notas, atualizado_em)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(artigo_id) DO UPDATE SET
                       categoria=excluded.categoria,
                       eixo=excluded.eixo,
                       prioridade=excluded.prioridade,
                       status_leitura=excluded.status_leitura,
                       notas=excluded.notas,
                       atualizado_em=excluded.atualizado_em""",
                (artigo_id, cat, eixo, prio, status, notas, agora())
            )
            atuais[artigo_id] = {
                "artigo_id": artigo_id,
                "categoria": cat,
                "eixo": eixo,
                "prioridade": prio,
                "status_leitura": status,
                "notas": notas,
            }
            alteradas += 1
        self.conn.commit()
        return alteradas

    def importar_auditoria_negativos(self, registros):
        """Grava as respostas da auditoria (saida de `dominio.auditoria_negativos.validar_respostas`). Tudo e conferido antes
        da primeira gravacao: a classificacao precisa existir, nao ter achados e, se a planilha traz `url_id` e `uf`, bater
        com o banco. Idempotente: a mesma resposta do mesmo revisor nao grava de novo; uma resposta DIFERENTE para o mesmo
        (classificacao, revisor) nao sobrescreve nada e e devolvida em `conflitos` [(classificacao_id, revisor, linha)].
        Devolve {novas, iguais, conflitos}."""
        pares = [(r["linha"], r["classificacao_id"]) for r in registros]
        self._ids_validos(pares, "classificacao_id", "classificacoes", "classificacao_id", "Classificação")
        res = {"novas": 0, "iguais": 0, "conflitos": []}
        novas = []
        for r in registros:
            k = self.conn.execute("SELECT url_id, uf FROM classificacoes WHERE classificacao_id=?", (r["classificacao_id"],)).fetchone()
            if self.conn.execute("SELECT 1 FROM achados WHERE classificacao_id=?", (r["classificacao_id"],)).fetchone():
                raise SystemExit(f"A classificação {r['classificacao_id']} tem achados: não é uma página sem achado (linha {r['linha']})")
            if (r["url_id"] and str(r["url_id"]).split(".")[0] != str(k["url_id"])) or (r["uf"] and r["uf"] != k["uf"]):
                raise SystemExit(f"url_id e uf não conferem com a classificação {r['classificacao_id']} (linha {r['linha']})")
            antes = self.conn.execute("SELECT tinha_aplicacao, tecnologia FROM auditoria_negativos WHERE classificacao_id=? AND revisor=?",
                                      (r["classificacao_id"], r["revisor"])).fetchone()
            if antes is None:
                novas.append((r, k))
            elif tuple(antes) == (r["tinha_aplicacao"], r["tecnologia"]):
                res["iguais"] += 1
            else:
                res["conflitos"].append((r["classificacao_id"], r["revisor"], r["linha"]))
        for r, k in novas:
            self._inserir("auditoria_negativos", classificacao_id=r["classificacao_id"], url_id=k["url_id"], uf=k["uf"],
                          revisor=r["revisor"], revisado_em=agora(), tinha_aplicacao=r["tinha_aplicacao"],
                          tecnologia=r["tecnologia"], observacao=r["observacao"])
        self.conn.commit()
        res["novas"] = len(novas)
        return res

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
