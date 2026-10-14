PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS execucoes (
    run_id        TEXT PRIMARY KEY,
    iniciado_em   TEXT NOT NULL,
    finalizado_em TEXT,
    comando       TEXT,
    config_hash   TEXT NOT NULL,
    config_json   TEXT NOT NULL,
    commit_git    TEXT,
    status        TEXT NOT NULL DEFAULT 'em_andamento',
    metricas_json TEXT,
    run_origem    TEXT                              -- C5: run (--de) that holds the input of this one
);

CREATE TABLE IF NOT EXISTS metricas_run (          -- free-form counters per run (no schema change needed)
    run_id TEXT NOT NULL REFERENCES execucoes(run_id),
    chave  TEXT NOT NULL,
    valor  REAL,
    PRIMARY KEY (run_id, chave)
);

CREATE TABLE IF NOT EXISTS saldos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES execucoes(run_id),
    provedor TEXT NOT NULL,
    momento TEXT NOT NULL,                          -- inicio | fim
    valor REAL,
    registrado_em TEXT
);

-- Every external call (search, download, classification) becomes a row
CREATE TABLE IF NOT EXISTS chamadas (
    chamada_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id             TEXT NOT NULL REFERENCES execucoes(run_id),
    etapa              TEXT NOT NULL,               -- busca_academica | busca_web | download | classificacao
    provedor           TEXT NOT NULL,
    operacao           TEXT,
    alvo_tipo          TEXT,                        -- termo | consulta_web | url | item
    alvo_id            TEXT,
    uf                 TEXT,
    pagina             INTEGER,
    parametros_json    TEXT NOT NULL,
    chave_idempotencia TEXT NOT NULL,
    requisitado_em     TEXT NOT NULL,
    http_status        INTEGER,
    sucesso            INTEGER NOT NULL DEFAULT 0,
    tentativas         INTEGER,
    latencia_ms        INTEGER,
    id_externo         TEXT,
    total_reportado    INTEGER,
    n_retornados       INTEGER,
    n_novos            INTEGER,
    tokens_entrada     INTEGER,
    tokens_saida       INTEGER,
    custo_usd          REAL,
    erro               TEXT,
    raw_path           TEXT,
    raw_sha256         TEXT,
    extras_json        TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_chamadas_idem
    ON chamadas(run_id, chave_idempotencia) WHERE sucesso = 1;

-- ===== Task 2: literature =====
CREATE TABLE IF NOT EXISTS artigos (
    artigo_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chave_dedup        TEXT NOT NULL UNIQUE,
    titulo             TEXT NOT NULL,
    link               TEXT,
    autores_publicacao TEXT,
    ano                INTEGER,
    snippet            TEXT,
    citacoes           INTEGER,
    primeira_vez_run   TEXT,
    primeira_vez_em    TEXT
);
CREATE TABLE IF NOT EXISTS ocorrencias (
    ocorrencia_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    chamada_id          INTEGER NOT NULL REFERENCES chamadas(chamada_id),
    artigo_id           INTEGER NOT NULL REFERENCES artigos(artigo_id),
    termo_id            TEXT NOT NULL,
    run_id              TEXT NOT NULL,
    posicao             INTEGER,
    citacoes_no_momento INTEGER
);
CREATE TABLE IF NOT EXISTS triagem (
    artigo_id          INTEGER PRIMARY KEY REFERENCES artigos(artigo_id),
    decisao            TEXT NOT NULL DEFAULT 'pendente',   -- pendente | incluir | excluir
    motivo             TEXT,
    confirmado_em_base TEXT,
    link_confirmado    TEXT,
    revisor            TEXT,
    revisado_em        TEXT
);
CREATE TABLE IF NOT EXISTS buscas_manuais (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    base           TEXT NOT NULL,
    termo_id       TEXT NOT NULL,
    string_base    TEXT,
    filtros        TEXT,
    n_resultados   INTEGER,
    n_apos_filtro  INTEGER,
    n_selecionados INTEGER,
    data_busca     TEXT,
    observacao     TEXT
);

-- ===== Task 1: secretariats =====
CREATE TABLE IF NOT EXISTS urls (                   -- one row per normalized (deduplicated) URL
    url_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    url_normalizada  TEXT NOT NULL UNIQUE,
    url_original     TEXT NOT NULL,
    dominio          TEXT,
    fonte_oficial    INTEGER,
    primeira_vez_run TEXT,
    primeira_vez_em  TEXT
);
CREATE TABLE IF NOT EXISTS resultados_web (
    resultado_id INTEGER PRIMARY KEY AUTOINCREMENT,
    chamada_id   INTEGER NOT NULL REFERENCES chamadas(chamada_id),
    run_id       TEXT NOT NULL,
    consulta_id  TEXT NOT NULL,
    uf           TEXT NOT NULL,
    tecnologia   TEXT,
    perfil       TEXT,
    url_id       INTEGER NOT NULL REFERENCES urls(url_id),
    posicao      INTEGER,
    titulo       TEXT,
    snippet      TEXT,
    data_pub     TEXT
);
CREATE TABLE IF NOT EXISTS selecao_download (       -- EVERY decision to download or discard is recorded
    run_id      TEXT NOT NULL REFERENCES execucoes(run_id),
    url_id      INTEGER NOT NULL REFERENCES urls(url_id),
    uf          TEXT NOT NULL,
    selecionada INTEGER NOT NULL,
    motivo      TEXT,                                -- dominio_excluido | nao_oficial | prefiltro_palavras | limite_por_uf
    PRIMARY KEY (run_id, url_id, uf)
);
CREATE TABLE IF NOT EXISTS paginas (
    pagina_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT NOT NULL,
    url_id        INTEGER NOT NULL REFERENCES urls(url_id),
    chamada_id    INTEGER NOT NULL REFERENCES chamadas(chamada_id),
    url_final     TEXT,
    http_status   INTEGER,
    content_type  TEXT,
    n_bytes       INTEGER,
    truncado      INTEGER,
    texto_path    TEXT,
    n_chars       INTEGER,
    extrator      TEXT,
    extracao_ok   INTEGER,
    motivo_falha  TEXT
);
CREATE TABLE IF NOT EXISTS classificacoes (
    classificacao_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    chamada_id          INTEGER NOT NULL REFERENCES chamadas(chamada_id),
    run_id              TEXT NOT NULL,
    url_id              INTEGER NOT NULL REFERENCES urls(url_id),
    pagina_id           INTEGER REFERENCES paginas(pagina_id),
    uf                  TEXT NOT NULL,
    origem_texto        TEXT,                        -- pagina | snippet
    texto_truncado      INTEGER,
    n_chars_enviados    INTEGER,
    classificador       TEXT,
    prompt_versao       TEXT,
    relevante           INTEGER,
    json_valido         INTEGER,
    n_achados           INTEGER,
    n_achados_invalidos INTEGER,
    resposta_texto      TEXT
);
CREATE TABLE IF NOT EXISTS achados (
    achado_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    classificacao_id  INTEGER NOT NULL REFERENCES classificacoes(classificacao_id),
    uf                TEXT NOT NULL,
    tecnologia        TEXT,
    status_reportado  TEXT,
    fornecedor        TEXT,
    menciona_lgpd     INTEGER,
    evidencia         TEXT,
    evidencia_confere INTEGER,                       -- 1 = the excerpt exists in the text that was sent
    confianca         TEXT,
    verificado        INTEGER NOT NULL DEFAULT 0,
    status_final      TEXT,                          -- human decision
    verificado_por    TEXT,
    verificado_em     TEXT,
    observacao        TEXT
);

-- ===== Metric views =====
CREATE VIEW IF NOT EXISTS v_funil AS
SELECT e.run_id,
  (SELECT COUNT(*) FROM chamadas c WHERE c.run_id=e.run_id AND c.etapa='busca_web' AND c.sucesso=1) AS consultas_web_ok,
  (SELECT COUNT(*) FROM resultados_web r WHERE r.run_id=e.run_id) AS resultados,
  (SELECT COUNT(DISTINCT url_id) FROM resultados_web r WHERE r.run_id=e.run_id) AS urls_unicas,
  (SELECT COUNT(*) FROM selecao_download s WHERE s.run_id=e.run_id AND s.selecionada=1) AS pares_url_uf_selecionados,
  (SELECT COUNT(*) FROM selecao_download s WHERE s.run_id=e.run_id AND s.selecionada=0) AS pares_descartados,
  (SELECT COUNT(*) FROM paginas p WHERE p.run_id=e.run_id) AS paginas_baixadas,
  (SELECT COUNT(*) FROM paginas p WHERE p.run_id=e.run_id AND p.extracao_ok=1) AS paginas_com_texto,
  (SELECT COUNT(*) FROM classificacoes k WHERE k.run_id=e.run_id) AS classificacoes,
  (SELECT COUNT(*) FROM achados a JOIN classificacoes k ON k.classificacao_id=a.classificacao_id WHERE k.run_id=e.run_id) AS achados,
  (SELECT COUNT(*) FROM achados a JOIN classificacoes k ON k.classificacao_id=a.classificacao_id WHERE k.run_id=e.run_id AND a.evidencia_confere=1) AS achados_evidencia_ok,
  (SELECT COUNT(*) FROM achados a JOIN classificacoes k ON k.classificacao_id=a.classificacao_id WHERE k.run_id=e.run_id AND a.verificado=1) AS achados_verificados
FROM execucoes e;

CREATE VIEW IF NOT EXISTS v_custos AS
SELECT run_id, etapa, provedor, COUNT(*) AS n_chamadas, SUM(sucesso) AS n_ok,
       COUNT(*)-SUM(sucesso) AS n_falhas, SUM(tokens_entrada) AS tokens_entrada,
       SUM(tokens_saida) AS tokens_saida, ROUND(SUM(custo_usd),4) AS custo_usd,
       ROUND(AVG(latencia_ms)) AS latencia_media_ms
FROM chamadas GROUP BY run_id, etapa, provedor;

CREATE VIEW IF NOT EXISTS v_falhas AS
SELECT run_id, etapa, provedor, SUBSTR(erro,1,60) AS erro, COUNT(*) AS n
FROM chamadas WHERE sucesso=0 GROUP BY run_id, etapa, provedor, SUBSTR(erro,1,60);

CREATE VIEW IF NOT EXISTS v_dominios AS
SELECT u.dominio, u.fonte_oficial, COUNT(*) AS n_resultados, COUNT(DISTINCT r.uf) AS n_ufs
FROM resultados_web r JOIN urls u ON u.url_id=r.url_id
GROUP BY u.dominio, u.fonte_oficial ORDER BY n_resultados DESC;

CREATE VIEW IF NOT EXISTS v_metricas_busca_web AS
SELECT run_id, uf, tecnologia, perfil, COUNT(*) AS n_resultados, COUNT(DISTINCT url_id) AS n_urls
FROM resultados_web GROUP BY run_id, uf, tecnologia, perfil;

CREATE VIEW IF NOT EXISTS v_descartes AS
SELECT run_id, COALESCE(motivo,'selecionada') AS motivo, COUNT(*) AS n
FROM selecao_download GROUP BY run_id, COALESCE(motivo,'selecionada');

CREATE VIEW IF NOT EXISTS v_achados_revisao AS
SELECT a.achado_id, k.run_id, a.uf, a.tecnologia, a.status_reportado, a.fornecedor, a.menciona_lgpd,
       a.evidencia, a.evidencia_confere, a.confianca, k.origem_texto, k.classificador,
       u.url_original AS url, u.dominio, u.fonte_oficial,
       a.verificado, a.status_final, a.verificado_por, a.observacao
FROM achados a
JOIN classificacoes k ON k.classificacao_id=a.classificacao_id
JOIN urls u ON u.url_id=k.url_id
ORDER BY a.verificado, a.evidencia_confere, a.uf;

CREATE VIEW IF NOT EXISTS v_resumo_uf AS
SELECT a.uf,
  COUNT(*) AS n_achados,
  SUM(a.verificado) AS n_verificados,
  SUM(CASE WHEN a.verificado=1 AND COALESCE(a.status_final,'')<>'descartado' THEN 1 ELSE 0 END) AS n_confirmados,
  SUM(COALESCE(a.evidencia_confere,0)) AS n_evidencia_ok,
  SUM(u.fonte_oficial) AS n_fonte_oficial
FROM achados a
JOIN classificacoes k ON k.classificacao_id=a.classificacao_id
JOIN urls u ON u.url_id=k.url_id
GROUP BY a.uf;

CREATE VIEW IF NOT EXISTS v_metricas_por_termo AS
SELECT run_id, alvo_id AS termo_id, COUNT(*) AS n_requisicoes, SUM(sucesso) AS n_sucesso,
       COUNT(*)-SUM(sucesso) AS n_falhas, MAX(total_reportado) AS total_reportado_aprox,
       SUM(n_retornados) AS n_retornados, SUM(n_novos) AS n_novos_artigos,
       ROUND(AVG(latencia_ms)) AS latencia_media_ms
FROM chamadas WHERE etapa='busca_academica' GROUP BY run_id, alvo_id;

CREATE VIEW IF NOT EXISTS v_artigos_por_ano AS
SELECT ano, COUNT(*) AS n_artigos FROM artigos GROUP BY ano ORDER BY ano;

CREATE VIEW IF NOT EXISTS v_artigos_multi_termo AS
SELECT a.artigo_id, a.titulo, a.ano, a.citacoes, COUNT(DISTINCT o.termo_id) AS n_termos
FROM artigos a JOIN ocorrencias o ON o.artigo_id=a.artigo_id
GROUP BY a.artigo_id ORDER BY n_termos DESC, a.citacoes DESC;

CREATE VIEW IF NOT EXISTS v_sobreposicao_termos AS
SELECT o1.termo_id AS termo_a, o2.termo_id AS termo_b, COUNT(DISTINCT o1.artigo_id) AS n_em_comum
FROM ocorrencias o1 JOIN ocorrencias o2 ON o1.artigo_id=o2.artigo_id AND o1.termo_id<o2.termo_id
GROUP BY o1.termo_id, o2.termo_id;

CREATE VIEW IF NOT EXISTS v_manuais_resumo AS
SELECT base, COUNT(*) AS n_buscas, SUM(n_resultados) AS total_resultados,
       SUM(n_apos_filtro) AS total_apos_filtro, SUM(n_selecionados) AS total_selecionados
FROM buscas_manuais GROUP BY base;
