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
    run_origem    TEXT,                             -- C5: run (--de) that holds the input of this one
    ambiente_json TEXT,                             -- versoes, pausas e argumentos da execucao (fora do hash)
    no_relatorio  INTEGER NOT NULL DEFAULT 1,       -- 0 = execucao de teste/piloto: fora das views agregadas do relatorio
    motivo_exclusao TEXT,
    excluida_em   TEXT
);

-- cada retomada (--retomar) acrescenta uma linha: o codigo e o ambiente podem ser outros que os da execucao original
CREATE TABLE IF NOT EXISTS execucoes_retomadas (
    retomada_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT NOT NULL REFERENCES execucoes(run_id),
    retomado_em   TEXT NOT NULL,
    commit_git    TEXT,
    ambiente_json TEXT
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
    etapa              TEXT NOT NULL,               -- busca_academica | busca_web | busca_literatura | download | classificacao
    provedor           TEXT NOT NULL,
    operacao           TEXT,
    alvo_tipo          TEXT,                        -- termo | consulta_web | consulta_literatura | url | item
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
-- v_gasto_real pergunta, para cada chamada sem custo, se o provedor registra custo em alguma outra (EXISTS por provedor):
-- sem este indice cada pergunta varre a tabela inteira (medido: 533 ms -> poucos ms com 2.300 chamadas)
CREATE INDEX IF NOT EXISTS ix_chamadas_provedor_custo ON chamadas(provedor, custo_usd);
-- itens com chamada numa execucao e etapa (o --limite vale para a execucao inteira, retomadas incluidas)
CREATE INDEX IF NOT EXISTS ix_chamadas_run_etapa_chave ON chamadas(run_id, etapa, chave_idempotencia);

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
    revisado_em        TEXT,
    decisao_texto_completo TEXT,                        -- pendente | incluir | excluir (etapa de elegibilidade)
    motivo_texto_completo  TEXT
);
-- historico de decisoes de triagem: cada importacao com valor novo por (artigo, revisor) vira uma linha
CREATE TABLE IF NOT EXISTS triagem_revisoes (
    revisao_id INTEGER PRIMARY KEY AUTOINCREMENT,
    artigo_id  INTEGER NOT NULL REFERENCES artigos(artigo_id),
    revisor    TEXT NOT NULL,
    decisao    TEXT NOT NULL,
    motivo     TEXT,
    decisao_texto_completo TEXT,
    motivo_texto_completo  TEXT,
    importado_em TEXT NOT NULL,
    independente INTEGER NOT NULL DEFAULT 0          -- 1 = revisao independente (so historico); so estas entram no kappa
);
-- artigos informados a mao nas buscas manuais (IEEE, ACM, Scopus, SBC OpenLib); entram em `artigos` para deduplicar
CREATE TABLE IF NOT EXISTS ocorrencias_manuais (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    artigo_id   INTEGER NOT NULL REFERENCES artigos(artigo_id),
    base        TEXT NOT NULL,
    termo_id    TEXT NOT NULL,
    data_busca  TEXT NOT NULL DEFAULT '',
    posicao     INTEGER,
    importado_em TEXT,
    UNIQUE (artigo_id, base, termo_id, data_busca)
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
    data_pub     TEXT,
    cidade       TEXT                                 -- NULL = secretaria estadual; preenchido = municipal
);
CREATE TABLE IF NOT EXISTS selecao_download (       -- EVERY decision to download or discard is recorded
    run_id      TEXT NOT NULL REFERENCES execucoes(run_id),
    url_id      INTEGER NOT NULL REFERENCES urls(url_id),
    uf          TEXT NOT NULL,
    selecionada INTEGER NOT NULL,
    motivo      TEXT,                                -- dominio_excluido | nao_oficial | prefiltro_palavras | limite_por_uf
    auditoria   INTEGER NOT NULL DEFAULT 0,          -- 1 = descartada pelo pre-filtro, mas baixada e classificada para auditar o filtro
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
    motivo_falha  TEXT,
    dominio_final TEXT,                              -- dominio de url_final (apos redirecionamentos)
    fonte_oficial_final INTEGER                      -- 1 se o dominio final e oficial (.gov.br)
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
    cidade              TEXT,                        -- NULL = estadual; preenchido = secretaria municipal
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
    confianca_original TEXT,                         -- confianca devolvida pelo modelo, antes do rebaixamento
    evidencia_cita_tecnologia INTEGER,               -- 1 = o trecho cita um termo da tecnologia (heuristica, sem LLM)
    evidencia_cita_lgpd INTEGER,                     -- 1 = o trecho cita LGPD ou protecao de dados (heuristica)
    nome_solucao      TEXT,                          -- nome proprio da solucao (prompt v4), so se aparece no texto enviado; NULL = sem nome
    verificado        INTEGER NOT NULL DEFAULT 0,
    status_final      TEXT,                          -- human decision
    verificado_por    TEXT,
    verificado_em     TEXT,
    observacao        TEXT
);
CREATE INDEX IF NOT EXISTS ix_achados_classificacao ON achados(classificacao_id);
-- as consultas de candidatos e de itens a classificar buscam por (url_id, uf) e (url_id, run_id) em subconsultas correlacionadas:
-- sem estes indices `itens_para_classificar` levava 8,5 s numa copia local e minutos no banco real em /mnt/c (16/10/2026)
CREATE INDEX IF NOT EXISTS ix_resultados_web_url_uf ON resultados_web(url_id, uf, resultado_id);
CREATE INDEX IF NOT EXISTS ix_paginas_url_run ON paginas(url_id, run_id);
-- achados que o modelo devolveu fora do vocabulario controlado: descartados, mas guardados para auditoria
CREATE TABLE IF NOT EXISTS achados_descartados (
    descartado_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    classificacao_id INTEGER NOT NULL REFERENCES classificacoes(classificacao_id),
    uf               TEXT,
    tecnologia       TEXT,
    status           TEXT,
    fornecedor       TEXT,
    menciona_lgpd    INTEGER,
    evidencia        TEXT,
    confianca        TEXT,
    motivo           TEXT                     -- tecnologia_fora_do_vocabulario | status_fora_do_vocabulario
);
-- historico da verificacao humana dos achados
CREATE TABLE IF NOT EXISTS achados_revisoes (
    revisao_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    achado_id      INTEGER NOT NULL REFERENCES achados(achado_id),
    verificado_por TEXT NOT NULL,
    status_final   TEXT,
    observacao     TEXT,
    importado_em   TEXT NOT NULL,
    anterior_json  TEXT,                  -- estado antes de uma decisao do painel (permite desfazer)
    posterior_json TEXT,                  -- estado que a decisao produziu: o desfazer so vale se o achado ainda esta assim
    desfeita       INTEGER NOT NULL DEFAULT 0,
    independente   INTEGER NOT NULL DEFAULT 0   -- 1 = revisao independente (achados-importar --independente): so historico; so estas entram no kappa
);
-- auditoria amostral do que o modelo NAO marcou (classificacoes sem achado): mede os falsos negativos, isto e, a revocacao global.
-- Uma linha por (classificacao, revisor); `tinha_aplicacao` = 1 se a pessoa achou na pagina uma aplicacao de IA que o modelo perdeu.
CREATE TABLE IF NOT EXISTS auditoria_negativos (
    auditoria_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    classificacao_id INTEGER NOT NULL REFERENCES classificacoes(classificacao_id),
    url_id           INTEGER NOT NULL REFERENCES urls(url_id),
    uf               TEXT NOT NULL,
    revisor          TEXT NOT NULL,
    revisado_em      TEXT NOT NULL,
    tinha_aplicacao  INTEGER NOT NULL CHECK (tinha_aplicacao IN (0, 1)),   -- 1 = o modelo perdeu uma aplicacao; 0 = o modelo acertou
    tecnologia       TEXT,                                                  -- do vocabulario; so quando tinha_aplicacao = 1
    observacao       TEXT,
    UNIQUE (classificacao_id, revisor)
);

-- ===== Triagem de escopo feita por LLM (opiniao registrada a parte: nunca altera `triagem` nem `achados`) =====
-- Um item e um artigo (fonte='artigo', item_id = artigo_id, uf = '') ou um resultado web (fonte='web', item_id = url_id,
-- uf = a UF da busca). 'excluido' so vale com confianca alta (a regra e do codigo); o item continua visivel (quarentena
-- temporaria) para servir a analise das consultas.
CREATE TABLE IF NOT EXISTS triagem_escopo (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id             TEXT NOT NULL REFERENCES execucoes(run_id),
    chamada_id         INTEGER REFERENCES chamadas(chamada_id),     -- a chamada (lote) que respondeu
    fonte              TEXT NOT NULL,                                -- artigo | web | referencia (busca de vies)
    item_id            INTEGER NOT NULL,
    uf                 TEXT NOT NULL DEFAULT '',
    provedor           TEXT,                                         -- serpapi_scholar, perplexity_search, serpapi_google
    termos_consulta    TEXT,                                         -- JSON: textos das consultas (termos) que acharam o item
    status             TEXT NOT NULL,                                -- elegivel | quarentena | excluido (depois da regra de seguranca)
    status_bruto       TEXT,                                         -- o que o modelo disse, antes do rebaixamento
    confianca          TEXT,                                         -- alta | media | baixa
    categoria_motivo   TEXT,                                         -- taxonomia (NULL se elegivel)
    justificativa      TEXT,                                         -- ate 20 palavras
    termo_gerador      TEXT,                                         -- um dos termos da consulta (conferido pelo codigo)
    sinal_negativo     TEXT,                                         -- trecho literal do titulo/resumo (conferido pelo codigo)
    dominio_tematico   TEXT,
    escopo_geografico  TEXT,                                         -- brasil | internacional | indeterminado
    tipo_documento     TEXT,
    valido             INTEGER NOT NULL DEFAULT 1,                   -- 0 = alguma conferencia falhou
    problemas          TEXT,                                         -- JSON: o que falhou
    prompt_versao      TEXT,
    criado_em          TEXT NOT NULL,
    tipo_fonte         TEXT,                                         -- triagem da busca de vies: tipo com o sufixo (D110)
    pais_escopo        TEXT,                                         -- triagem da busca de vies: pais ou escopo, por extenso
    topicos            TEXT,                                         -- triagem da busca de vies: topicos separados por "; "
    eixo               TEXT,                                         -- triagem da busca de vies: um dos 6 eixos de exploracao
    recorte            TEXT,                                         -- triagem do vies, prompt v2: vies_algoritmico ou aplicacoes_tecnologicas
    UNIQUE (run_id, fonte, item_id, uf)
);
CREATE INDEX IF NOT EXISTS ix_triagem_escopo_item ON triagem_escopo(fonte, item_id, uf);

CREATE TABLE IF NOT EXISTS leitura_referencias (
    artigo_id      INTEGER PRIMARY KEY REFERENCES artigos(artigo_id),
    categoria      TEXT,
    eixo           TEXT,
    prioridade     TEXT,
    status_leitura TEXT NOT NULL DEFAULT 'Nao iniciado',
    notas          TEXT,
    atualizado_em  TEXT
);

-- ===== Execucoes dentro do relatorio =====
-- As views agregadas leem estas views (r_*), que deixam de fora as execucoes marcadas com no_relatorio = 0
-- (pilotos e testes: `python main.py execucao-excluir <run_id>`). Views por execucao e de auditoria usam as tabelas.
DROP VIEW IF EXISTS r_chamadas;
CREATE VIEW r_chamadas AS
SELECT c.* FROM chamadas c JOIN execucoes e ON e.run_id = c.run_id WHERE e.no_relatorio = 1;
DROP VIEW IF EXISTS r_resultados_web;
CREATE VIEW r_resultados_web AS
SELECT r.* FROM resultados_web r JOIN execucoes e ON e.run_id = r.run_id WHERE e.no_relatorio = 1;
DROP VIEW IF EXISTS r_ocorrencias;
CREATE VIEW r_ocorrencias AS
SELECT o.* FROM ocorrencias o JOIN execucoes e ON e.run_id = o.run_id WHERE e.no_relatorio = 1;
DROP VIEW IF EXISTS r_selecao_download;
CREATE VIEW r_selecao_download AS
SELECT s.* FROM selecao_download s JOIN execucoes e ON e.run_id = s.run_id WHERE e.no_relatorio = 1;
DROP VIEW IF EXISTS r_paginas;
CREATE VIEW r_paginas AS
SELECT p.* FROM paginas p JOIN execucoes e ON e.run_id = p.run_id WHERE e.no_relatorio = 1;
-- HISTORICO: toda classificacao das execucoes do relatorio (uma pagina classificada duas vezes aparece duas vezes). Serve a
-- metricas de DESEMPENHO e CUSTO do classificador (por versao do prompt), nunca a contagens de paginas ou achados.
DROP VIEW IF EXISTS r_classificacoes_historico;
CREATE VIEW r_classificacoes_historico AS
SELECT k.* FROM classificacoes k JOIN execucoes e ON e.run_id = k.run_id WHERE e.no_relatorio = 1;
DROP VIEW IF EXISTS r_achados_historico;
CREATE VIEW r_achados_historico AS
SELECT a.* FROM achados a JOIN r_classificacoes_historico k ON k.classificacao_id = a.classificacao_id;
-- CLASSIFICACAO VIGENTE: uma por par (url_id, uf) entre as execucoes do relatorio. Vale, nesta ordem:
--   (a) a que tem achado verificado por humano (a mais recente delas): decisao humana nunca e substituida sozinha;
--   (b) senao, a de JSON valido;  (c) senao, a de texto da pagina sobre a de so snippet (snippet novo nao troca texto completo antigo);
--   (d) senao, a mais recente (maior requisitado_em da chamada; empate pelo maior classificacao_id).
-- Nada e apagado: o historico fica nas tabelas e em r_classificacoes_historico; so a contagem muda. Contagens de paginas e achados leem esta view.
DROP VIEW IF EXISTS r_classificacoes;
CREATE VIEW r_classificacoes AS
WITH base AS (
    SELECT k.classificacao_id, k.url_id, k.uf, COALESCE(k.json_valido, 0) AS valido,
           (SELECT c.requisitado_em FROM chamadas c WHERE c.chamada_id = k.chamada_id) AS requisitado_em,
           CASE WHEN k.origem_texto = 'pagina' THEN 1 ELSE 0 END AS pagina,
           CASE WHEN v.classificacao_id IS NULL THEN 0 ELSE 1 END AS humano
    FROM r_classificacoes_historico k
    LEFT JOIN (SELECT DISTINCT classificacao_id FROM achados WHERE verificado = 1) v ON v.classificacao_id = k.classificacao_id),
ranque AS (
    SELECT classificacao_id,
           ROW_NUMBER() OVER (PARTITION BY url_id, uf ORDER BY humano DESC,
                              CASE WHEN humano = 1 THEN 0 ELSE valido END DESC,
                              CASE WHEN humano = 1 THEN 0 ELSE pagina END DESC,
                              requisitado_em DESC, classificacao_id DESC) AS posicao
    FROM base)
SELECT k.* FROM classificacoes k JOIN ranque r ON r.classificacao_id = k.classificacao_id WHERE r.posicao = 1;
DROP VIEW IF EXISTS r_achados;
CREATE VIEW r_achados AS
SELECT a.* FROM achados a JOIN r_classificacoes k ON k.classificacao_id = a.classificacao_id;
DROP VIEW IF EXISTS r_achados_descartados;
CREATE VIEW r_achados_descartados AS
SELECT d.* FROM achados_descartados d JOIN r_classificacoes k ON k.classificacao_id = d.classificacao_id;
-- artigo que so apareceu em execucao fora do relatorio nao conta; artigos das buscas manuais sempre contam
DROP VIEW IF EXISTS r_artigos;
CREATE VIEW r_artigos AS
SELECT a.* FROM artigos a WHERE a.artigo_id IN (SELECT artigo_id FROM r_ocorrencias UNION SELECT artigo_id FROM ocorrencias_manuais);
-- triagem humana so dos artigos do relatorio: artigo que so apareceu em execucao fora do relatorio nao entra nas contagens
DROP VIEW IF EXISTS r_triagem;
CREATE VIEW r_triagem AS
SELECT t.* FROM triagem t WHERE t.artigo_id IN (SELECT artigo_id FROM r_artigos);

-- Origem efetiva de cada classificacao: o dominio final da pagina (apos redirecionamentos), quando houve download.
DROP VIEW IF EXISTS v_fonte_da_classificacao;
CREATE VIEW v_fonte_da_classificacao AS
SELECT k.classificacao_id, COALESCE(p.dominio_final, u.dominio) AS dominio_efetivo,
       COALESCE(p.fonte_oficial_final, u.fonte_oficial) AS fonte_oficial_efetiva
FROM classificacoes k JOIN urls u ON u.url_id = k.url_id LEFT JOIN paginas p ON p.pagina_id = k.pagina_id;

-- ===== Metric views =====
DROP VIEW IF EXISTS v_funil;
CREATE VIEW v_funil AS
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
  (SELECT COUNT(*) FROM achados a JOIN classificacoes k ON k.classificacao_id=a.classificacao_id WHERE k.run_id=e.run_id AND a.verificado=1) AS achados_verificados,
  (SELECT COUNT(*) FROM selecao_download s WHERE s.run_id=e.run_id AND s.auditoria=1) AS pares_auditoria,
  (SELECT COUNT(DISTINCT p.pagina_id) FROM paginas p JOIN selecao_download s ON s.run_id=p.run_id AND s.url_id=p.url_id
     WHERE p.run_id=e.run_id AND s.auditoria=1 AND s.selecionada=0) AS paginas_auditoria,
  (SELECT COUNT(*) FROM achados a JOIN classificacoes k ON k.classificacao_id=a.classificacao_id
     WHERE k.run_id=e.run_id AND EXISTS (SELECT 1 FROM v_pares_auditoria pa WHERE pa.url_id=k.url_id AND pa.uf=k.uf)) AS achados_auditoria
FROM execucoes e;

DROP VIEW IF EXISTS v_custos;
CREATE VIEW v_custos AS
SELECT run_id, etapa, provedor, COUNT(*) AS n_chamadas, SUM(sucesso) AS n_ok,
       COUNT(*)-SUM(sucesso) AS n_falhas, SUM(tokens_entrada) AS tokens_entrada,
       SUM(tokens_saida) AS tokens_saida, ROUND(SUM(custo_usd),4) AS custo_usd,
       ROUND(AVG(latencia_ms)) AS latencia_media_ms
FROM chamadas GROUP BY run_id, etapa, provedor;

DROP VIEW IF EXISTS v_falhas;
CREATE VIEW v_falhas AS
SELECT run_id, etapa, provedor, SUBSTR(erro,1,60) AS erro, COUNT(*) AS n
FROM chamadas WHERE sucesso=0 GROUP BY run_id, etapa, provedor, SUBSTR(erro,1,60);

DROP VIEW IF EXISTS v_dominios;
CREATE VIEW v_dominios AS
SELECT u.dominio, u.fonte_oficial, COUNT(*) AS n_resultados, COUNT(DISTINCT r.uf) AS n_ufs
FROM r_resultados_web r JOIN urls u ON u.url_id=r.url_id
GROUP BY u.dominio, u.fonte_oficial ORDER BY n_resultados DESC;

DROP VIEW IF EXISTS v_metricas_busca_web;
CREATE VIEW v_metricas_busca_web AS
SELECT run_id, uf, tecnologia, perfil, COUNT(*) AS n_resultados, COUNT(DISTINCT url_id) AS n_urls
FROM resultados_web GROUP BY run_id, uf, tecnologia, perfil;

DROP VIEW IF EXISTS v_descartes;
CREATE VIEW v_descartes AS
SELECT run_id, COALESCE(motivo,'selecionada') AS motivo, COUNT(*) AS n
FROM selecao_download GROUP BY run_id, COALESCE(motivo,'selecionada');

DROP VIEW IF EXISTS v_achados_revisao;
CREATE VIEW v_achados_revisao AS
SELECT a.achado_id, k.run_id, a.uf, a.tecnologia, a.status_reportado, a.fornecedor, a.menciona_lgpd,
       a.evidencia, a.evidencia_confere, a.confianca, k.origem_texto, k.classificador,
       u.url_original AS url, u.dominio, u.fonte_oficial,
       a.verificado, a.status_final, a.verificado_por, a.verificado_em, a.observacao,
       EXISTS (SELECT 1 FROM v_pares_auditoria pa WHERE pa.url_id = k.url_id AND pa.uf = k.uf) AS auditoria,
       p.dominio_final, p.fonte_oficial_final,
       a.evidencia_cita_tecnologia, a.evidencia_cita_lgpd, k.cidade, a.nome_solucao
FROM achados a
JOIN r_classificacoes k ON k.classificacao_id=a.classificacao_id   -- fila de revisao: so a classificacao vigente de execucoes do relatorio
JOIN urls u ON u.url_id=k.url_id
LEFT JOIN paginas p ON p.pagina_id=k.pagina_id
ORDER BY a.verificado, a.evidencia_confere, a.evidencia_cita_tecnologia, a.uf;

DROP VIEW IF EXISTS v_secretarias_confirmadas;
CREATE VIEW v_secretarias_confirmadas AS      -- C4: achados verificados e nao descartados, por UF e tecnologia
SELECT a.uf, k.cidade, a.tecnologia, a.status_final, a.fornecedor, a.menciona_lgpd, a.evidencia,
       u.url_original AS url, f.dominio_efetivo AS dominio, f.fonte_oficial_efetiva AS fonte_oficial,
       a.achado_id, a.verificado_por, a.verificado_em, a.nome_solucao
FROM r_achados a
JOIN r_classificacoes k ON k.classificacao_id=a.classificacao_id
JOIN urls u ON u.url_id=k.url_id
JOIN v_fonte_da_classificacao f ON f.classificacao_id=k.classificacao_id
WHERE a.verificado=1 AND COALESCE(a.status_final,'')<>'descartado'
ORDER BY a.uf, k.cidade, a.tecnologia, a.achado_id;

DROP VIEW IF EXISTS v_resumo_municipio;
CREATE VIEW v_resumo_municipio AS                  -- so secretarias municipais (achados com cidade)
SELECT k.uf, k.cidade,
  COUNT(*) AS n_achados,
  SUM(a.verificado) AS n_verificados,
  SUM(CASE WHEN a.verificado=1 AND COALESCE(a.status_final,'')<>'descartado' THEN 1 ELSE 0 END) AS n_confirmados,
  SUM(COALESCE(a.evidencia_confere,0)) AS n_evidencia_ok
FROM r_achados a JOIN r_classificacoes k ON k.classificacao_id=a.classificacao_id
WHERE k.cidade IS NOT NULL
GROUP BY k.uf, k.cidade;

DROP VIEW IF EXISTS v_resumo_uf;
CREATE VIEW v_resumo_uf AS
SELECT a.uf,
  COUNT(*) AS n_achados,
  SUM(a.verificado) AS n_verificados,
  SUM(CASE WHEN a.verificado=1 AND COALESCE(a.status_final,'')<>'descartado' THEN 1 ELSE 0 END) AS n_confirmados,
  SUM(COALESCE(a.evidencia_confere,0)) AS n_evidencia_ok,
  SUM(f.fonte_oficial_efetiva) AS n_fonte_oficial
FROM r_achados a
JOIN r_classificacoes k ON k.classificacao_id=a.classificacao_id
JOIN v_fonte_da_classificacao f ON f.classificacao_id=k.classificacao_id
GROUP BY a.uf;

DROP VIEW IF EXISTS v_metricas_por_termo;
CREATE VIEW v_metricas_por_termo AS
SELECT run_id, alvo_id AS termo_id, COUNT(*) AS n_requisicoes, SUM(sucesso) AS n_sucesso,
       COUNT(*)-SUM(sucesso) AS n_falhas, MAX(total_reportado) AS total_reportado_aprox,
       SUM(n_retornados) AS n_retornados, SUM(n_novos) AS n_novos_artigos,
       ROUND(AVG(latencia_ms)) AS latencia_media_ms
FROM chamadas WHERE etapa='busca_academica' GROUP BY run_id, alvo_id;

DROP VIEW IF EXISTS v_artigos_por_ano;
CREATE VIEW v_artigos_por_ano AS
SELECT ano, COUNT(*) AS n_artigos FROM r_artigos GROUP BY ano ORDER BY ano;

DROP VIEW IF EXISTS v_artigos_multi_termo;
CREATE VIEW v_artigos_multi_termo AS
SELECT a.artigo_id, a.titulo, a.ano, a.citacoes, COUNT(DISTINCT o.termo_id) AS n_termos
FROM r_artigos a JOIN r_ocorrencias o ON o.artigo_id=a.artigo_id
GROUP BY a.artigo_id ORDER BY n_termos DESC, COALESCE(a.citacoes,0) DESC;

DROP VIEW IF EXISTS v_sobreposicao_termos;
CREATE VIEW v_sobreposicao_termos AS
SELECT o1.termo_id AS termo_a, o2.termo_id AS termo_b, COUNT(DISTINCT o1.artigo_id) AS n_em_comum
FROM r_ocorrencias o1 JOIN r_ocorrencias o2 ON o1.artigo_id=o2.artigo_id AND o1.termo_id<o2.termo_id
GROUP BY o1.termo_id, o2.termo_id;

DROP VIEW IF EXISTS v_manuais_resumo;
CREATE VIEW v_manuais_resumo AS
SELECT base, COUNT(*) AS n_buscas, SUM(n_resultados) AS total_resultados,
       SUM(n_apos_filtro) AS total_apos_filtro, SUM(n_selecionados) AS total_selecionados
FROM buscas_manuais GROUP BY base;

-- ===== Metricas para o relatorio: rendimento dos termos, PRISMA, rendimento da busca web, qualidade do LLM =====

-- Metadados dos termos (idioma, grupo) vindos do snapshot de configuracao; vale a definicao da execucao mais recente.
DROP VIEW IF EXISTS v_termos;
CREATE VIEW v_termos AS
SELECT termo_id, query, idioma, grupo, pai FROM (
    SELECT json_extract(j.value, '$.id') AS termo_id, json_extract(j.value, '$.query') AS query,
           json_extract(j.value, '$.idioma') AS idioma, json_extract(j.value, '$.grupo') AS grupo,
           json_extract(j.value, '$.pai') AS pai,
           ROW_NUMBER() OVER (PARTITION BY json_extract(j.value, '$.id') ORDER BY e.iniciado_em DESC, e.rowid DESC) AS rn
    FROM execucoes e, json_each(e.config_json, '$.termos') j)
WHERE rn = 1;

-- Rendimento por termo (todas as execucoes, artigos distintos). Um termo cujo n_incluidos_exclusivos e 0 nao
-- traz nenhum artigo incluido que outro termo nao traga.
DROP VIEW IF EXISTS v_rendimento_termo;
CREATE VIEW v_rendimento_termo AS
WITH art_termo AS (SELECT DISTINCT termo_id, artigo_id FROM r_ocorrencias),
     por_artigo AS (SELECT artigo_id, COUNT(*) AS n_termos FROM art_termo GROUP BY artigo_id),
     por_termo AS (SELECT alvo_id AS termo_id, COUNT(*) AS n_requisicoes, COUNT(DISTINCT pagina) AS n_paginas,
                          MAX(total_reportado) AS total_reportado_aprox
                   FROM r_chamadas WHERE etapa='busca_academica' GROUP BY alvo_id)
SELECT at.termo_id, t.query, t.idioma, t.grupo, pt.n_requisicoes, pt.n_paginas, pt.total_reportado_aprox,
       COUNT(*) AS n_artigos,
       ROUND(100.0 * COUNT(*) / NULLIF(pt.total_reportado_aprox, 0), 2) AS cobertura_pct,
       COALESCE(SUM(pa.n_termos = 1), 0) AS n_exclusivos,
       ROUND(100.0 * SUM(pa.n_termos = 1) / COUNT(*), 1) AS pct_exclusivos,
       COALESCE(SUM(tr.decisao = 'incluir'), 0) AS n_incluidos,
       COALESCE(SUM(tr.decisao = 'excluir'), 0) AS n_excluidos,
       COALESCE(SUM(tr.artigo_id IS NULL OR tr.decisao = 'pendente'), 0) AS n_pendentes,
       ROUND(100.0 * SUM(tr.decisao = 'incluir') / NULLIF(SUM(tr.decisao IN ('incluir', 'excluir')), 0), 1) AS taxa_inclusao_pct,
       COALESCE(SUM(tr.decisao = 'incluir' AND pa.n_termos = 1), 0) AS n_incluidos_exclusivos,
       COALESCE(SUM(tr.decisao = 'incluir' AND tr.decisao_texto_completo = 'incluir'), 0) AS n_incluidos_finais
FROM art_termo at
JOIN por_artigo pa ON pa.artigo_id = at.artigo_id
LEFT JOIN triagem tr ON tr.artigo_id = at.artigo_id
LEFT JOIN por_termo pt ON pt.termo_id = at.termo_id
LEFT JOIN v_termos t ON t.termo_id = at.termo_id
GROUP BY at.termo_id
ORDER BY n_incluidos DESC, taxa_inclusao_pct DESC, n_artigos DESC;

-- Pares de termos: sobreposicao normalizada (Jaccard), contencao e ganho da uniao, com os incluidos.
DROP VIEW IF EXISTS v_pares_termos;
CREATE VIEW v_pares_termos AS
WITH art_termo AS (SELECT DISTINCT termo_id, artigo_id FROM r_ocorrencias),
     tamanho AS (SELECT at.termo_id, COUNT(*) AS n, COALESCE(SUM(tr.decisao = 'incluir'), 0) AS n_incl
                 FROM art_termo at LEFT JOIN triagem tr ON tr.artigo_id = at.artigo_id GROUP BY at.termo_id)
SELECT a.termo_id AS termo_a, b.termo_id AS termo_b, ta.n AS n_a, tb.n AS n_b,
       COUNT(*) AS n_em_comum, ta.n + tb.n - COUNT(*) AS n_uniao,
       ROUND(1.0 * COUNT(*) / (ta.n + tb.n - COUNT(*)), 3) AS jaccard,
       ROUND(100.0 * COUNT(*) / MIN(ta.n, tb.n), 1) AS pct_do_menor_contido,
       COALESCE(SUM(tr.decisao = 'incluir'), 0) AS n_incluidos_em_comum,
       ta.n_incl + tb.n_incl - COALESCE(SUM(tr.decisao = 'incluir'), 0) AS n_incluidos_uniao
FROM art_termo a
JOIN art_termo b ON a.artigo_id = b.artigo_id AND a.termo_id < b.termo_id
JOIN tamanho ta ON ta.termo_id = a.termo_id
JOIN tamanho tb ON tb.termo_id = b.termo_id
LEFT JOIN triagem tr ON tr.artigo_id = a.artigo_id
GROUP BY a.termo_id, b.termo_id
ORDER BY jaccard DESC;

-- O que os equivalentes em ingles acrescentam: artigos achados so por termos pt, so por en, ou por ambos.
DROP VIEW IF EXISTS v_ganho_por_idioma;
CREATE VIEW v_ganho_por_idioma AS
WITH por_artigo AS (
    SELECT o.artigo_id, MAX(t.idioma = 'pt') AS tem_pt, MAX(t.idioma = 'en') AS tem_en
    FROM r_ocorrencias o JOIN v_termos t ON t.termo_id = o.termo_id GROUP BY o.artigo_id)
SELECT CASE WHEN p.tem_pt = 1 AND p.tem_en = 1 THEN 'ambos' WHEN p.tem_pt = 1 THEN 'apenas_pt' ELSE 'apenas_en' END AS achado_por,
       COUNT(*) AS n_artigos,
       COALESCE(SUM(tr.decisao = 'incluir'), 0) AS n_incluidos,
       COALESCE(SUM(tr.decisao = 'excluir'), 0) AS n_excluidos
FROM por_artigo p LEFT JOIN triagem tr ON tr.artigo_id = p.artigo_id
GROUP BY achado_por;

-- Rendimento por pagina do Scholar (cada ocorrencia conta uma vez): justifica MAX_PAGINAS_ACADEMICO.
DROP VIEW IF EXISTS v_rendimento_por_pagina;
CREATE VIEW v_rendimento_por_pagina AS
SELECT c.pagina, COUNT(*) AS n_ocorrencias, COUNT(DISTINCT o.artigo_id) AS n_artigos,
       COALESCE(SUM(tr.decisao = 'incluir'), 0) AS n_incluidos,
       COALESCE(SUM(tr.decisao = 'excluir'), 0) AS n_excluidos,
       ROUND(100.0 * SUM(tr.decisao = 'incluir') / NULLIF(SUM(tr.decisao IN ('incluir', 'excluir')), 0), 1) AS taxa_inclusao_pct
FROM r_ocorrencias o
JOIN r_chamadas c ON c.chamada_id = o.chamada_id
LEFT JOIN triagem tr ON tr.artigo_id = o.artigo_id
GROUP BY c.pagina ORDER BY c.pagina;

-- Curva de descoberta na ordem das chamadas (requisitado_em, empate por chamada_id; depende da ordem; mostra o esgotamento de novidades).
DROP VIEW IF EXISTS v_curva_descoberta;
CREATE VIEW v_curva_descoberta AS
SELECT c.chamada_id, c.alvo_id AS termo_id, c.pagina, c.n_retornados, c.n_novos,
       ROUND(100.0 * c.n_novos / NULLIF(c.n_retornados, 0), 1) AS pct_novos,
       SUM(c.n_novos) OVER (ORDER BY c.requisitado_em, c.chamada_id) AS novos_acumulado
FROM r_chamadas c WHERE c.etapa = 'busca_academica' AND c.sucesso = 1;

-- Numeros do fluxo PRISMA (identificacao, triagem por titulo e resumo, elegibilidade por texto completo, inclusao).
-- Se houver mais de uma execucao de busca academica, os registros somam todas.
-- `removidos_escopo` = artigos do relatorio que a triagem de escopo do modelo excluiu (veredito atual valido: a linha de maior
-- (`criado_em`, `id`) por artigo, com valido = 1 e status = 'excluido') E sobre os quais nenhuma pessoa decidiu incluir/excluir. Decisao humana
-- sempre vence: artigo excluido pelo modelo e triado por uma pessoa continua no fluxo humano. E a mesma regra de `llm_oculto`
-- da lista de artigos. O PRISMA 2020 pede os registros removidos por ferramenta de automacao antes da triagem.
DROP VIEW IF EXISTS v_prisma;
CREATE VIEW v_prisma AS
WITH removidos_escopo AS (
    SELECT COUNT(*) AS n FROM r_artigos a
    WHERE EXISTS (SELECT 1 FROM triagem_escopo te
                  WHERE te.id = (SELECT x.id FROM triagem_escopo x WHERE x.fonte = 'artigo' AND x.item_id = a.artigo_id AND x.uf = ''
                                ORDER BY x.criado_em DESC, x.id DESC LIMIT 1)
                    AND te.valido = 1 AND te.status = 'excluido')
      AND COALESCE((SELECT t.decisao FROM triagem t WHERE t.artigo_id = a.artigo_id), 'pendente') NOT IN ('incluir', 'excluir'))
SELECT 1 AS ordem, 'identificacao' AS fase, 'execucoes de busca academica' AS metrica,
       (SELECT COUNT(DISTINCT run_id) FROM r_chamadas WHERE etapa = 'busca_academica') AS valor
UNION ALL SELECT 2, 'identificacao', 'Google Scholar: registros retornados',
       COALESCE((SELECT SUM(n_retornados) FROM r_chamadas WHERE etapa = 'busca_academica' AND sucesso = 1), 0)
UNION ALL SELECT 3, 'identificacao', 'buscas manuais: registros retornados (contagem informada)',
       COALESCE((SELECT SUM(n_resultados) FROM buscas_manuais), 0)
UNION ALL SELECT 4, 'identificacao', 'Google Scholar: duplicatas entre termos removidas',
       (SELECT COUNT(*) FROM r_ocorrencias) - (SELECT COUNT(DISTINCT artigo_id) FROM r_ocorrencias)
UNION ALL SELECT 5, 'identificacao', 'Google Scholar: artigos unicos', (SELECT COUNT(DISTINCT artigo_id) FROM r_ocorrencias)
UNION ALL SELECT 6, 'identificacao', 'buscas manuais: apos filtro da base (contagem informada)',
       COALESCE((SELECT SUM(n_apos_filtro) FROM buscas_manuais), 0)
UNION ALL SELECT 7, 'identificacao', 'buscas manuais: selecionados (contagem informada)',
       COALESCE((SELECT SUM(n_selecionados) FROM buscas_manuais), 0)
UNION ALL SELECT 8, 'identificacao', 'buscas manuais: artigos importados (por base)',
       (SELECT COUNT(DISTINCT artigo_id || '|' || base) FROM ocorrencias_manuais)
UNION ALL SELECT 9, 'identificacao', 'registros (artigo x fonte) apos remover duplicatas entre termos',
       (SELECT COUNT(*) FROM (SELECT DISTINCT artigo_id, fonte FROM v_ocorrencias_fonte))
UNION ALL SELECT 10, 'identificacao', 'duplicatas entre fontes removidas',
       (SELECT COUNT(*) FROM (SELECT DISTINCT artigo_id, fonte FROM v_ocorrencias_fonte)) - (SELECT COUNT(*) FROM r_artigos)
UNION ALL SELECT 11, 'identificacao', 'removidos por ferramenta automatica (triagem de escopo do modelo, sem decisao humana)',
       (SELECT n FROM removidos_escopo)
UNION ALL SELECT 12, 'triagem', 'artigos unicos para triagem', (SELECT COUNT(*) FROM r_artigos) - (SELECT n FROM removidos_escopo)
UNION ALL SELECT 13, 'triagem', 'avaliados por titulo e resumo',
       (SELECT COUNT(*) FROM r_triagem WHERE decisao IN ('incluir', 'excluir'))
UNION ALL SELECT 14, 'triagem', 'excluidos por titulo e resumo', (SELECT COUNT(*) FROM r_triagem WHERE decisao = 'excluir')
UNION ALL SELECT 15, 'triagem', 'incluidos por titulo e resumo', (SELECT COUNT(*) FROM r_triagem WHERE decisao = 'incluir')
UNION ALL SELECT 16, 'triagem', 'pendentes de titulo e resumo',
       (SELECT COUNT(*) FROM r_artigos) - (SELECT n FROM removidos_escopo) - (SELECT COUNT(*) FROM r_triagem WHERE decisao IN ('incluir', 'excluir'))
UNION ALL SELECT 17, 'elegibilidade', 'avaliados por texto completo',
       (SELECT COUNT(*) FROM r_triagem WHERE decisao = 'incluir' AND decisao_texto_completo IN ('incluir', 'excluir'))
UNION ALL SELECT 18, 'elegibilidade', 'excluidos por texto completo',
       (SELECT COUNT(*) FROM r_triagem WHERE decisao = 'incluir' AND decisao_texto_completo = 'excluir')
UNION ALL SELECT 19, 'elegibilidade', 'aguardando texto completo',
       (SELECT COUNT(*) FROM r_triagem WHERE decisao = 'incluir' AND COALESCE(decisao_texto_completo, 'pendente') = 'pendente')
UNION ALL SELECT 20, 'inclusao', 'incluidos no estudo (texto completo)',
       (SELECT COUNT(*) FROM r_triagem WHERE decisao = 'incluir' AND decisao_texto_completo = 'incluir');

DROP VIEW IF EXISTS v_motivos_exclusao;
CREATE VIEW v_motivos_exclusao AS
SELECT etapa, motivo, n FROM (
    SELECT 'titulo_resumo' AS etapa, COALESCE(NULLIF(TRIM(motivo), ''), '(sem motivo)') AS motivo, COUNT(*) AS n
    FROM r_triagem WHERE decisao = 'excluir' GROUP BY 2
    UNION ALL
    SELECT 'texto_completo', COALESCE(NULLIF(TRIM(motivo_texto_completo), ''), '(sem motivo)'), COUNT(*)
    FROM r_triagem WHERE decisao = 'incluir' AND decisao_texto_completo = 'excluir' GROUP BY 2)
ORDER BY etapa DESC, n DESC, motivo;

-- Registro de buscas (anexo do protocolo): cada requisicao ao Scholar e cada busca manual, com string, filtros e data.
DROP VIEW IF EXISTS v_registro_buscas;
CREATE VIEW v_registro_buscas AS
SELECT 'Google Scholar (SerpApi)' AS fonte, c.alvo_id AS termo_id,
       json_extract(c.parametros_json, '$.q') AS string_busca,
       'idioma=' || COALESCE(json_extract(c.parametros_json, '$.hl'), '') ||
       '; por_pagina=' || COALESCE(json_extract(c.parametros_json, '$.num'), '') ||
       '; ano_inicial=' || COALESCE(json_extract(c.parametros_json, '$.as_ylo'), '') ||
       '; ano_final=' || COALESCE(json_extract(c.parametros_json, '$.as_yhi'), '') ||
       '; idioma_resultados=' || COALESCE(json_extract(c.parametros_json, '$.lr'), '') AS filtros,
       c.pagina, c.requisitado_em AS data_busca, c.n_retornados AS n_resultados,
       c.total_reportado AS total_reportado_aprox, c.sucesso, c.run_id, e.config_hash, e.no_relatorio
FROM chamadas c JOIN execucoes e ON e.run_id = c.run_id
WHERE c.etapa = 'busca_academica'
UNION ALL
SELECT m.base, m.termo_id, m.string_base, m.filtros, NULL, m.data_busca, m.n_resultados, NULL, 1, NULL, NULL, 1
FROM buscas_manuais m;

-- ===== Task 1: rendimento da busca web e qualidade da classificacao =====

-- Situacao de cada par (url, uf): tem achado? foi verificado? foi confirmado? (todas as execucoes)
DROP VIEW IF EXISTS v_status_url;
CREATE VIEW v_status_url AS
SELECT k.url_id, k.uf, COUNT(a.achado_id) AS n_achados,
       COALESCE(MAX(a.verificado), 0) AS verificado,
       COALESCE(MAX(CASE WHEN a.verificado = 1 AND COALESCE(a.status_final, '') <> 'descartado' THEN 1 ELSE 0 END), 0) AS confirmado
FROM r_classificacoes k LEFT JOIN r_achados a ON a.classificacao_id = k.classificacao_id
GROUP BY k.url_id, k.uf;

-- Do modelo de consulta ate o achado confirmado, por modelo x perfil x tecnologia consultada.
DROP VIEW IF EXISTS v_rendimento_busca_web;
CREATE VIEW v_rendimento_busca_web AS
WITH pares AS (
    SELECT DISTINCT substr(r.consulta_id, 1, instr(r.consulta_id, '-') - 1) AS modelo_id, r.perfil, r.tecnologia,
           r.url_id, r.uf, r.consulta_id FROM r_resultados_web r)
SELECT p.modelo_id, p.perfil, p.tecnologia,
       COUNT(DISTINCT p.consulta_id) AS n_consultas_com_resultado,
       COUNT(DISTINCT p.url_id || '|' || p.uf) AS n_urls,
       ROUND(100.0 * COUNT(DISTINCT CASE WHEN u.fonte_oficial = 1 THEN p.url_id || '|' || p.uf END)
             / COUNT(DISTINCT p.url_id || '|' || p.uf), 1) AS pct_oficiais,
       COUNT(DISTINCT CASE WHEN s.n_achados > 0 THEN p.url_id || '|' || p.uf END) AS n_urls_com_achado,
       COUNT(DISTINCT CASE WHEN s.verificado = 1 THEN p.url_id || '|' || p.uf END) AS n_urls_verificadas,
       COUNT(DISTINCT CASE WHEN s.confirmado = 1 THEN p.url_id || '|' || p.uf END) AS n_urls_confirmadas
FROM pares p
JOIN urls u ON u.url_id = p.url_id
LEFT JOIN v_status_url s ON s.url_id = p.url_id AND s.uf = p.uf
GROUP BY p.modelo_id, p.perfil, p.tecnologia
ORDER BY n_urls_confirmadas DESC, n_urls DESC;

-- O segundo modelo de consulta acrescenta o que o primeiro nao traz?
DROP VIEW IF EXISTS v_sobreposicao_modelos;
CREATE VIEW v_sobreposicao_modelos AS
WITH mu AS (SELECT DISTINCT substr(consulta_id, 1, instr(consulta_id, '-') - 1) AS modelo_id, url_id, uf FROM r_resultados_web),
     tamanho AS (SELECT modelo_id, COUNT(*) AS n FROM mu GROUP BY modelo_id)
SELECT a.modelo_id AS modelo_a, b.modelo_id AS modelo_b, ta.n AS n_urls_a, tb.n AS n_urls_b,
       COUNT(*) AS n_em_comum, ta.n + tb.n - COUNT(*) AS n_uniao,
       ROUND(1.0 * COUNT(*) / (ta.n + tb.n - COUNT(*)), 3) AS jaccard,
       (SELECT COUNT(*) FROM mu x JOIN v_status_url s ON s.url_id = x.url_id AND s.uf = x.uf
         WHERE x.modelo_id = a.modelo_id AND s.confirmado = 1
           AND NOT EXISTS (SELECT 1 FROM mu y WHERE y.modelo_id = b.modelo_id AND y.url_id = x.url_id AND y.uf = x.uf)) AS confirmadas_so_em_a,
       (SELECT COUNT(*) FROM mu x JOIN v_status_url s ON s.url_id = x.url_id AND s.uf = x.uf
         WHERE x.modelo_id = b.modelo_id AND s.confirmado = 1
           AND NOT EXISTS (SELECT 1 FROM mu y WHERE y.modelo_id = a.modelo_id AND y.url_id = x.url_id AND y.uf = x.uf)) AS confirmadas_so_em_b
FROM mu a
JOIN mu b ON a.url_id = b.url_id AND a.uf = b.uf AND a.modelo_id < b.modelo_id
JOIN tamanho ta ON ta.modelo_id = a.modelo_id
JOIN tamanho tb ON tb.modelo_id = b.modelo_id
GROUP BY a.modelo_id, b.modelo_id;

-- Rendimento por posicao do resultado: justifica max_resultados.
DROP VIEW IF EXISTS v_rendimento_por_posicao;
CREATE VIEW v_rendimento_por_posicao AS
SELECT r.posicao, COUNT(*) AS n_resultados, COUNT(DISTINCT r.url_id || '|' || r.uf) AS n_urls,
       COALESCE(SUM(s.verificado = 1), 0) AS n_verificados,
       COALESCE(SUM(s.confirmado = 1), 0) AS n_confirmados,
       ROUND(100.0 * SUM(s.confirmado = 1) / NULLIF(SUM(s.verificado = 1), 0), 1) AS taxa_confirmacao_pct
FROM r_resultados_web r LEFT JOIN v_status_url s ON s.url_id = r.url_id AND s.uf = r.uf
GROUP BY r.posicao ORDER BY r.posicao;

-- Consultas que devolveram zero resultados, por modelo e tecnologia.
DROP VIEW IF EXISTS v_consultas_vazias;
CREATE VIEW v_consultas_vazias AS
SELECT substr(alvo_id, 1, instr(alvo_id, '-') - 1) AS modelo_id,
       substr(substr(alvo_id, instr(alvo_id, '-') + 1), instr(substr(alvo_id, instr(alvo_id, '-') + 1), '-') + 1) AS tecnologia,
       COUNT(*) AS n_consultas, SUM(COALESCE(n_retornados, 0) = 0) AS n_sem_resultado,
       ROUND(100.0 * SUM(COALESCE(n_retornados, 0) = 0) / COUNT(*), 1) AS pct_sem_resultado
FROM r_chamadas WHERE etapa = 'busca_web' AND sucesso = 1
GROUP BY modelo_id, tecnologia;

-- Matriz final do relatorio: achados confirmados por UF, tecnologia e status final.
DROP VIEW IF EXISTS v_cobertura_uf_tecnologia;
CREATE VIEW v_cobertura_uf_tecnologia AS
SELECT a.uf, a.tecnologia, a.status_final, COUNT(DISTINCT k.url_id) AS n_fontes,
       COUNT(DISTINCT CASE WHEN f.fonte_oficial_efetiva = 1 THEN k.url_id END) AS n_fontes_oficiais
FROM r_achados a
JOIN r_classificacoes k ON k.classificacao_id = a.classificacao_id
JOIN v_fonte_da_classificacao f ON f.classificacao_id = k.classificacao_id
WHERE a.verificado = 1 AND COALESCE(a.status_final, '') <> 'descartado'
GROUP BY a.uf, a.tecnologia, a.status_final ORDER BY a.uf, a.tecnologia, a.status_final;

-- Quanto o LLM acerta (segundo a verificacao humana), por confianca, origem do texto, evidencia e fonte oficial.
DROP VIEW IF EXISTS v_precisao_llm;
CREATE VIEW v_precisao_llm AS
SELECT a.confianca, k.origem_texto, a.evidencia_confere, f.fonte_oficial_efetiva AS fonte_oficial, COUNT(*) AS n_achados,
       COALESCE(SUM(a.verificado = 1), 0) AS n_verificados,
       COALESCE(SUM(a.verificado = 1 AND COALESCE(a.status_final, '') <> 'descartado'), 0) AS n_confirmados,
       ROUND(100.0 * SUM(a.verificado = 1 AND COALESCE(a.status_final, '') <> 'descartado')
             / NULLIF(SUM(a.verificado = 1), 0), 1) AS taxa_confirmacao_pct
FROM r_achados a
JOIN r_classificacoes k ON k.classificacao_id = a.classificacao_id
JOIN v_fonte_da_classificacao f ON f.classificacao_id = k.classificacao_id
GROUP BY a.confianca, k.origem_texto, a.evidencia_confere, f.fonte_oficial_efetiva
ORDER BY n_achados DESC;

-- Onde o humano corrigiu o LLM: status reportado x status final (so achados verificados).
DROP VIEW IF EXISTS v_correcoes_humanas;
CREATE VIEW v_correcoes_humanas AS
SELECT status_reportado, status_final, status_reportado = status_final AS manteve, COUNT(*) AS n
FROM r_achados WHERE verificado = 1
GROUP BY status_reportado, status_final ORDER BY n DESC;

-- Qualidade e custo por classificador, versao do prompt e origem do texto. Le o HISTORICO (toda chamada feita), nao so a
-- classificacao vigente: o custo e o desempenho de uma versao do prompt valem mesmo quando outra classificacao a substituiu.
DROP VIEW IF EXISTS v_qualidade_classificacao;
CREATE VIEW v_qualidade_classificacao AS
WITH por_classificacao AS (
    SELECT k.classificacao_id, k.classificador, k.prompt_versao, k.origem_texto, k.json_valido, k.relevante,
           k.texto_truncado, k.n_achados_invalidos, k.chamada_id, COUNT(a.achado_id) AS n_achados,
           COALESCE(SUM(a.evidencia_confere = 1), 0) AS n_evidencia_ok
    FROM r_classificacoes_historico k LEFT JOIN r_achados_historico a ON a.classificacao_id = k.classificacao_id
    GROUP BY k.classificacao_id)
SELECT p.classificador, p.prompt_versao, p.origem_texto, COUNT(*) AS n_classificacoes,
       ROUND(100.0 * SUM(p.json_valido) / COUNT(*), 1) AS pct_json_valido,
       ROUND(100.0 * SUM(p.relevante) / COUNT(*), 1) AS pct_relevante,
       ROUND(1.0 * SUM(p.n_achados) / COUNT(*), 2) AS achados_por_classificacao,
       ROUND(100.0 * SUM(p.n_evidencia_ok) / NULLIF(SUM(p.n_achados), 0), 1) AS pct_achados_evidencia_ok,
       SUM(p.n_achados_invalidos) AS n_achados_fora_do_vocabulario,
       ROUND(100.0 * SUM(p.texto_truncado) / COUNT(*), 1) AS pct_texto_truncado,
       SUM(c.tokens_entrada) AS tokens_entrada, SUM(c.tokens_saida) AS tokens_saida,
       ROUND(SUM(c.custo_usd), 4) AS custo_usd, ROUND(AVG(c.latencia_ms)) AS latencia_media_ms
FROM por_classificacao p JOIN r_chamadas c ON c.chamada_id = p.chamada_id
GROUP BY p.classificador, p.prompt_versao, p.origem_texto;

-- Resultado do download e da extracao de cada URL selecionada (inclui downloads que falharam e URLs nao tentadas).
DROP VIEW IF EXISTS v_extracao;
CREATE VIEW v_extracao AS
SELECT resultado, motivo, COALESCE(fonte_oficial_final, fonte_oficial) AS fonte_oficial, COALESCE(content_type, '') AS content_type,
       COUNT(DISTINCT run_id || '|' || url_id) AS n_urls,
       ROUND(100.0 * COUNT(DISTINCT run_id || '|' || url_id)
             / (SELECT COUNT(DISTINCT run_id || '|' || url_id) FROM v_resultado_download WHERE no_relatorio = 1), 1) AS pct
FROM v_resultado_download WHERE no_relatorio = 1
GROUP BY resultado, motivo, COALESCE(fonte_oficial_final, fonte_oficial), COALESCE(content_type, '') ORDER BY n_urls DESC;

-- Custos e eficiencia gerais (todas as execucoes).
DROP VIEW IF EXISTS v_eficiencia;
CREATE VIEW v_eficiencia AS
SELECT
  COALESCE((SELECT SUM(custo_usd) FROM r_chamadas), 0) AS custo_total_usd,
  (SELECT COUNT(*) FROM r_chamadas WHERE etapa = 'busca_academica' AND sucesso = 1) AS creditos_scholar,
  (SELECT COUNT(*) FROM r_chamadas WHERE etapa = 'busca_web' AND sucesso = 1) AS requisicoes_busca_web,
  (SELECT COUNT(DISTINCT url_id || '|' || uf) FROM v_status_url WHERE confirmado = 1) AS fontes_confirmadas,
  ROUND((SELECT SUM(custo_usd) FROM r_chamadas) / NULLIF((SELECT COUNT(*) FROM v_status_url WHERE confirmado = 1), 0), 4) AS custo_por_fonte_confirmada_usd,
  (SELECT COUNT(*) FROM r_triagem WHERE decisao = 'incluir') AS artigos_incluidos,
  ROUND(1.0 * (SELECT COUNT(*) FROM r_chamadas WHERE etapa = 'busca_academica' AND sucesso = 1)
        / NULLIF((SELECT COUNT(*) FROM r_triagem WHERE decisao = 'incluir'), 0), 2) AS creditos_por_artigo_incluido;

-- ===== Auditoria da coleta: o que aconteceu com cada item selecionado =====

-- Resultado de cada URL selecionada para download: ok, falha de download (com motivo), falha de extracao ou nao tentada.
-- Motivos de bloqueio: `bloqueado_por_robots` = o robots.txt foi lido e proibe (proibido pelo site; tambem o valor antigo, de
-- antes de `main.py migrar-robots`); `robots_inacessivel` = o robots.txt nao pode ser lido (5xx, tempo esgotado, rede) e a
-- politica da RFC 9309 mandou bloquear.
DROP VIEW IF EXISTS v_resultado_download;
CREATE VIEW v_resultado_download AS
WITH ultima AS (SELECT run_id, alvo_id, MAX(chamada_id) AS chamada_id FROM chamadas WHERE etapa = 'download' GROUP BY run_id, alvo_id)
SELECT s.run_id, s.url_id, s.uf, s.auditoria, u.dominio, u.fonte_oficial, p.dominio_final, p.fonte_oficial_final,
       COALESCE(p.dominio_final <> u.dominio, 0) AS redirecionou_de_dominio, e.no_relatorio, c.chamada_id, c.http_status, c.erro,
       c.tentativas, p.pagina_id, p.content_type, p.extracao_ok,
       CASE WHEN c.chamada_id IS NULL THEN 'nao_tentada'
            WHEN c.sucesso = 0 THEN 'falha_download'
            WHEN p.extracao_ok = 1 THEN 'ok'
            ELSE 'falha_extracao' END AS resultado,
       CASE WHEN c.chamada_id IS NULL THEN 'limite_ou_interrompida'
            WHEN c.sucesso = 0 THEN CASE WHEN c.erro LIKE 'bloqueado_por_robots%' THEN 'bloqueado_por_robots'
                                         WHEN c.erro LIKE 'robots_inacessivel%' THEN 'robots_inacessivel'
                                         WHEN c.erro LIKE 'erro_de_leitura%' THEN 'erro_de_leitura'
                                         WHEN c.erro LIKE 'HTTP %' AND c.http_status IS NOT NULL THEN 'http_' || c.http_status
                                         ELSE 'erro_de_rede' END
            WHEN p.extracao_ok = 1 THEN 'ok'
            WHEN p.motivo_falha LIKE 'erro:%' THEN substr(p.motivo_falha, 1, instr(p.motivo_falha || '(', '(') - 1)
            ELSE COALESCE(p.motivo_falha, 'sem_pagina') END AS motivo
FROM selecao_download s
JOIN urls u ON u.url_id = s.url_id
JOIN execucoes e ON e.run_id = s.run_id
LEFT JOIN ultima l ON l.run_id = s.run_id AND l.alvo_id = CAST(s.url_id AS TEXT)
LEFT JOIN chamadas c ON c.chamada_id = l.chamada_id
LEFT JOIN paginas p ON p.chamada_id = c.chamada_id
WHERE s.selecionada = 1 OR s.auditoria = 1;

-- Resultado de cada par (url, uf) selecionado para classificacao: classificado, falha na chamada ou nao classificado.
DROP VIEW IF EXISTS v_resultado_classificacao;
CREATE VIEW v_resultado_classificacao AS
SELECT s.run_id AS run_selecao, s.url_id, s.uf, s.auditoria, u.dominio, u.fonte_oficial,
       CASE WHEN EXISTS (SELECT 1 FROM classificacoes k WHERE k.url_id = s.url_id AND k.uf = s.uf AND k.json_valido = 1) THEN 'classificado'
            WHEN EXISTS (SELECT 1 FROM classificacoes k WHERE k.url_id = s.url_id AND k.uf = s.uf) THEN 'classificado_json_invalido'
            WHEN EXISTS (SELECT 1 FROM chamadas c WHERE c.etapa = 'classificacao' AND c.alvo_id = s.url_id || ':' || s.uf AND c.sucesso = 0)
                 THEN 'falha_chamada'
            ELSE 'nao_classificado' END AS resultado,
       EXISTS (SELECT 1 FROM paginas p WHERE p.run_id = s.run_id AND p.url_id = s.url_id AND p.extracao_ok = 1) AS tem_texto_de_pagina,
       EXISTS (SELECT 1 FROM resultados_web r WHERE r.url_id = s.url_id AND r.uf = s.uf
               AND (COALESCE(r.titulo, '') <> '' OR COALESCE(r.snippet, '') <> '')) AS tem_snippet,
       CASE WHEN EXISTS (SELECT 1 FROM classificacoes k WHERE k.url_id = s.url_id AND k.uf = s.uf AND k.json_valido = 1) THEN NULL
            WHEN EXISTS (SELECT 1 FROM classificacoes k WHERE k.url_id = s.url_id AND k.uf = s.uf) THEN 'json_invalido: ver Classif_invalidas'
            WHEN EXISTS (SELECT 1 FROM chamadas c WHERE c.etapa = 'classificacao' AND c.alvo_id = s.url_id || ':' || s.uf AND c.sucesso = 0)
                 THEN COALESCE((SELECT substr(c.erro, 1, 80) FROM chamadas c WHERE c.etapa = 'classificacao'
                                AND c.alvo_id = s.url_id || ':' || s.uf AND c.sucesso = 0 ORDER BY c.requisitado_em DESC, c.chamada_id DESC LIMIT 1), 'falha_chamada')
            WHEN NOT EXISTS (SELECT 1 FROM paginas p WHERE p.run_id = s.run_id AND p.url_id = s.url_id AND p.extracao_ok = 1)
                 AND NOT EXISTS (SELECT 1 FROM resultados_web r WHERE r.url_id = s.url_id AND r.uf = s.uf
                                 AND (COALESCE(r.titulo, '') <> '' OR COALESCE(r.snippet, '') <> '')) THEN 'sem_texto_utilizavel'
            WHEN NOT EXISTS (SELECT 1 FROM paginas p WHERE p.run_id = s.run_id AND p.url_id = s.url_id AND p.extracao_ok = 1)
                 THEN 'sem_texto_de_pagina_e_snippet_nao_usado_ou_interrompida'
            ELSE 'nao_processado_limite_ou_interrompida' END AS motivo
FROM selecao_download s JOIN urls u ON u.url_id = s.url_id
WHERE s.selecionada = 1 OR s.auditoria = 1;

-- Achados que o modelo devolveu fora do vocabulario controlado (descartados, mas guardados).
DROP VIEW IF EXISTS v_achados_descartados;
CREATE VIEW v_achados_descartados AS
SELECT motivo, tecnologia, status, COUNT(*) AS n FROM r_achados_descartados
GROUP BY motivo, tecnologia, status ORDER BY n DESC;

-- Confianca devolvida pelo modelo x confianca gravada (o snippet rebaixa para baixa).
DROP VIEW IF EXISTS v_confianca_ajustada;
CREATE VIEW v_confianca_ajustada AS
SELECT k.origem_texto, a.confianca_original, a.confianca, a.confianca_original <> a.confianca AS ajustada, COUNT(*) AS n
FROM r_achados a JOIN r_classificacoes k ON k.classificacao_id = a.classificacao_id
WHERE a.confianca_original IS NOT NULL
GROUP BY k.origem_texto, a.confianca_original, a.confianca ORDER BY n DESC;

-- Saldo do provedor por passada (execucao original e cada retomada): cada `inicio` casa com o `fim` seguinte,
-- e as chamadas bem-sucedidas contadas sao as feitas entre os dois. Passada interrompida: saldo_fim e consumo ficam nulos.
DROP VIEW IF EXISTS v_saldos;
CREATE VIEW v_saldos AS
WITH inicios AS (
    SELECT s.id, s.run_id, s.provedor, s.valor, s.registrado_em,
           ROW_NUMBER() OVER (PARTITION BY s.run_id, s.provedor ORDER BY s.id) AS passada,
           LEAD(s.id) OVER (PARTITION BY s.run_id, s.provedor ORDER BY s.id) AS proximo_id,
           LEAD(s.registrado_em) OVER (PARTITION BY s.run_id, s.provedor ORDER BY s.id) AS proximo_em
    FROM saldos s WHERE s.momento = 'inicio'),
 passadas AS (
    SELECT i.run_id, i.provedor, i.passada, i.valor AS saldo_inicio, i.registrado_em AS iniciou_em, i.proximo_em,
           (SELECT f.valor FROM saldos f WHERE f.run_id = i.run_id AND f.provedor = i.provedor AND f.momento = 'fim'
              AND f.id > i.id AND (i.proximo_id IS NULL OR f.id < i.proximo_id) ORDER BY f.id DESC LIMIT 1) AS saldo_fim,
           (SELECT f.registrado_em FROM saldos f WHERE f.run_id = i.run_id AND f.provedor = i.provedor AND f.momento = 'fim'
              AND f.id > i.id AND (i.proximo_id IS NULL OR f.id < i.proximo_id) ORDER BY f.id DESC LIMIT 1) AS terminou_em
    FROM inicios i),
 contagem AS (
    SELECT p.*, p.saldo_inicio - p.saldo_fim AS consumo,
           (SELECT COUNT(*) FROM chamadas c WHERE c.run_id = p.run_id AND c.provedor = p.provedor AND c.sucesso = 1
              AND c.requisitado_em >= p.iniciou_em
              AND (COALESCE(p.terminou_em, p.proximo_em) IS NULL OR c.requisitado_em <= COALESCE(p.terminou_em, p.proximo_em))) AS chamadas_ok
    FROM passadas p)
SELECT run_id, provedor, passada, saldo_inicio, saldo_fim, consumo, chamadas_ok, consumo - chamadas_ok AS diferenca
FROM contagem;

-- Passadas de cada execucao: a original e cada retomada, com o commit e o ambiente de cada uma.
DROP VIEW IF EXISTS v_passadas;
CREATE VIEW v_passadas AS
SELECT run_id, 1 AS passada, 'original' AS tipo, iniciado_em AS inicio, commit_git, ambiente_json FROM execucoes
UNION ALL
SELECT run_id, 1 + ROW_NUMBER() OVER (PARTITION BY run_id ORDER BY retomada_id), 'retomada', retomado_em, commit_git, ambiente_json
FROM execucoes_retomadas;

-- O total que o Scholar reporta e aproximado e varia entre paginas: quanto?
DROP VIEW IF EXISTS v_total_reportado_estabilidade;
CREATE VIEW v_total_reportado_estabilidade AS
SELECT alvo_id AS termo_id, COUNT(*) AS n_paginas, MIN(total_reportado) AS total_min, MAX(total_reportado) AS total_max,
       ROUND(AVG(total_reportado)) AS total_medio,
       ROUND(100.0 * (MAX(total_reportado) - MIN(total_reportado)) / NULLIF(MAX(total_reportado), 0), 1) AS variacao_pct
FROM r_chamadas WHERE etapa = 'busca_academica' AND sucesso = 1 AND total_reportado IS NOT NULL
GROUP BY alvo_id;

-- ===== Fontes (Scholar e bases manuais) =====

DROP VIEW IF EXISTS v_ocorrencias_fonte;
CREATE VIEW v_ocorrencias_fonte AS
SELECT DISTINCT artigo_id, 'Google Scholar' AS fonte, termo_id FROM r_ocorrencias
UNION
SELECT DISTINCT artigo_id, base, termo_id FROM ocorrencias_manuais;

-- Que fonte traz artigos (e incluidos) que as outras nao trazem?
DROP VIEW IF EXISTS v_rendimento_fonte;
CREATE VIEW v_rendimento_fonte AS
WITH af AS (SELECT DISTINCT artigo_id, fonte FROM v_ocorrencias_fonte),
     por_artigo AS (SELECT artigo_id, COUNT(*) AS n_fontes FROM af GROUP BY artigo_id)
SELECT af.fonte, COUNT(*) AS n_artigos,
       COALESCE(SUM(pa.n_fontes = 1), 0) AS n_exclusivos,
       ROUND(100.0 * SUM(pa.n_fontes = 1) / COUNT(*), 1) AS pct_exclusivos,
       COALESCE(SUM(tr.decisao = 'incluir'), 0) AS n_incluidos,
       COALESCE(SUM(tr.decisao = 'excluir'), 0) AS n_excluidos,
       COALESCE(SUM(tr.artigo_id IS NULL OR tr.decisao = 'pendente'), 0) AS n_pendentes,
       ROUND(100.0 * SUM(tr.decisao = 'incluir') / NULLIF(SUM(tr.decisao IN ('incluir', 'excluir')), 0), 1) AS taxa_inclusao_pct,
       COALESCE(SUM(tr.decisao = 'incluir' AND pa.n_fontes = 1), 0) AS n_incluidos_exclusivos,
       COALESCE(SUM(tr.decisao = 'incluir' AND tr.decisao_texto_completo = 'incluir'), 0) AS n_incluidos_finais
FROM af JOIN por_artigo pa ON pa.artigo_id = af.artigo_id
LEFT JOIN triagem tr ON tr.artigo_id = af.artigo_id
GROUP BY af.fonte ORDER BY n_incluidos DESC, taxa_inclusao_pct DESC, n_artigos DESC;

DROP VIEW IF EXISTS v_sobreposicao_fontes;
CREATE VIEW v_sobreposicao_fontes AS
WITH af AS (SELECT DISTINCT artigo_id, fonte FROM v_ocorrencias_fonte),
     tamanho AS (SELECT fonte, COUNT(*) AS n FROM af GROUP BY fonte)
SELECT a.fonte AS fonte_a, b.fonte AS fonte_b, ta.n AS n_a, tb.n AS n_b, COUNT(*) AS n_em_comum,
       ta.n + tb.n - COUNT(*) AS n_uniao, ROUND(1.0 * COUNT(*) / (ta.n + tb.n - COUNT(*)), 3) AS jaccard,
       COALESCE(SUM(tr.decisao = 'incluir'), 0) AS n_incluidos_em_comum
FROM af a JOIN af b ON a.artigo_id = b.artigo_id AND a.fonte < b.fonte
JOIN tamanho ta ON ta.fonte = a.fonte JOIN tamanho tb ON tb.fonte = b.fonte
LEFT JOIN triagem tr ON tr.artigo_id = a.artigo_id
GROUP BY a.fonte, b.fonte ORDER BY jaccard DESC;

-- Termo x fonte: o mesmo termo rende o mesmo no Scholar e nas bases?
DROP VIEW IF EXISTS v_rendimento_termo_fonte;
CREATE VIEW v_rendimento_termo_fonte AS
SELECT o.fonte, o.termo_id, COUNT(DISTINCT o.artigo_id) AS n_artigos,
       COALESCE(SUM(tr.decisao = 'incluir'), 0) AS n_incluidos,
       COALESCE(SUM(tr.decisao = 'excluir'), 0) AS n_excluidos,
       ROUND(100.0 * SUM(tr.decisao = 'incluir') / NULLIF(SUM(tr.decisao IN ('incluir', 'excluir')), 0), 1) AS taxa_inclusao_pct
FROM (SELECT DISTINCT artigo_id, fonte, termo_id FROM v_ocorrencias_fonte) o
LEFT JOIN triagem tr ON tr.artigo_id = o.artigo_id
GROUP BY o.fonte, o.termo_id ORDER BY o.fonte, o.termo_id;

-- ===== Combinacoes de termos (consultas compostas que derivam de um termo, campo `pai`) =====

-- O contexto acrescentado melhora a precisao do termo? O que a consulta composta traz a mais ou deixa de trazer?
DROP VIEW IF EXISTS v_ganho_contexto;
CREATE VIEW v_ganho_contexto AS
SELECT t.termo_id AS termo_composto, t.pai AS termo_pai, t.query,
       c.n_artigos AS n_artigos_composto, p.n_artigos AS n_artigos_pai,
       COALESCE(par.n_em_comum, 0) AS n_em_comum,
       c.n_artigos - COALESCE(par.n_em_comum, 0) AS so_no_composto,
       p.n_artigos - COALESCE(par.n_em_comum, 0) AS so_no_pai,
       c.n_incluidos AS n_incluidos_composto, p.n_incluidos AS n_incluidos_pai,
       COALESCE(par.n_incluidos_em_comum, 0) AS n_incluidos_em_comum,
       c.n_incluidos - COALESCE(par.n_incluidos_em_comum, 0) AS incluidos_so_no_composto,
       p.n_incluidos - COALESCE(par.n_incluidos_em_comum, 0) AS incluidos_so_no_pai,
       c.taxa_inclusao_pct AS taxa_inclusao_composto_pct, p.taxa_inclusao_pct AS taxa_inclusao_pai_pct
FROM v_termos t
JOIN v_rendimento_termo c ON c.termo_id = t.termo_id
JOIN v_rendimento_termo p ON p.termo_id = t.pai
LEFT JOIN v_pares_termos par ON par.termo_a = MIN(t.termo_id, t.pai) AND par.termo_b = MAX(t.termo_id, t.pai)
WHERE COALESCE(t.pai, '') <> '';

-- ===== Auditoria do pre-filtro de palavras-chave =====

-- Pares (url, uf) que so foram baixados e classificados por causa da auditoria (nunca foram selecionados de fato).
DROP VIEW IF EXISTS v_pares_auditoria;
CREATE VIEW v_pares_auditoria AS
SELECT DISTINCT s.url_id, s.uf FROM selecao_download s
WHERE s.auditoria = 1 AND s.selecionada = 0
  AND NOT EXISTS (SELECT 1 FROM selecao_download x WHERE x.url_id = s.url_id AND x.uf = s.uf AND x.selecionada = 1);

-- Entre as URLs descartadas pelo pre-filtro, uma amostra foi baixada e classificada: quantas tinham achado?
DROP VIEW IF EXISTS v_auditoria_prefiltro;
CREATE VIEW v_auditoria_prefiltro AS
WITH amostra AS (SELECT run_id, url_id, uf FROM r_selecao_download WHERE auditoria = 1),
     descartadas AS (SELECT run_id, COUNT(*) AS n FROM r_selecao_download WHERE selecionada = 0 AND motivo = 'prefiltro_palavras' GROUP BY run_id)
SELECT a.run_id, d.n AS n_descartadas_prefiltro, COUNT(*) AS n_amostra,
       COALESCE(SUM(st.url_id IS NOT NULL), 0) AS n_classificadas,
       COALESCE(SUM(st.n_achados > 0), 0) AS n_com_achado,
       COALESCE(SUM(st.verificado = 1), 0) AS n_verificadas,
       COALESCE(SUM(st.confirmado = 1), 0) AS n_confirmadas,
       ROUND(100.0 * SUM(st.n_achados > 0) / NULLIF(SUM(st.url_id IS NOT NULL), 0), 1) AS taxa_com_achado_pct,
       ROUND(1.0 * d.n * SUM(st.n_achados > 0) / NULLIF(SUM(st.url_id IS NOT NULL), 0), 1) AS estimativa_com_achado_entre_descartadas
FROM amostra a
LEFT JOIN v_status_url st ON st.url_id = a.url_id AND st.uf = a.uf
LEFT JOIN descartadas d ON d.run_id = a.run_id
GROUP BY a.run_id;

-- ===== Revisao por mais de uma pessoa =====
-- So entram revisoes independentes (triagem-importar --independente); uma reimportacao normal nao contamina o kappa.
-- Convencao: o revisor chamado 'consenso' guarda a decisao final e fica fora da concordancia.

DROP VIEW IF EXISTS v_ultima_revisao_triagem;
CREATE VIEW v_ultima_revisao_triagem AS
SELECT r.artigo_id, r.revisor, r.decisao, r.motivo
FROM triagem_revisoes r
WHERE r.independente = 1
  AND r.revisao_id = (SELECT MAX(x.revisao_id) FROM triagem_revisoes x
                      WHERE x.artigo_id = r.artigo_id AND x.revisor = r.revisor AND x.independente = 1)
  AND r.revisor <> 'consenso' AND r.decisao IN ('incluir', 'excluir');

-- Concordancia entre cada par de revisores, com o kappa de Cohen (duas categorias: incluir e excluir).
DROP VIEW IF EXISTS v_concordancia_revisores;
CREATE VIEW v_concordancia_revisores AS
WITH pares AS (
    SELECT a.revisor AS revisor_a, b.revisor AS revisor_b, a.decisao AS da, b.decisao AS db
    FROM v_ultima_revisao_triagem a JOIN v_ultima_revisao_triagem b ON a.artigo_id = b.artigo_id AND a.revisor < b.revisor),
 tot AS (
    SELECT revisor_a, revisor_b, COUNT(*) AS n,
           SUM(da = 'incluir' AND db = 'incluir') AS n11, SUM(da = 'incluir' AND db = 'excluir') AS n10,
           SUM(da = 'excluir' AND db = 'incluir') AS n01, SUM(da = 'excluir' AND db = 'excluir') AS n00
    FROM pares GROUP BY revisor_a, revisor_b),
 base AS (
    SELECT *, ((n11 + n10) * 1.0 / n) * ((n11 + n01) * 1.0 / n) + ((n01 + n00) * 1.0 / n) * ((n10 + n00) * 1.0 / n) AS pe FROM tot)
SELECT revisor_a, revisor_b, n AS n_artigos_em_comum, n11 AS ambos_incluem, n00 AS ambos_excluem, n10 + n01 AS discordancias,
       ROUND(100.0 * (n11 + n00) / n, 1) AS concordancia_pct,
       ROUND((((n11 + n00) * 1.0 / n) - pe) / NULLIF(1 - pe, 0), 3) AS kappa
FROM base;

-- Artigos em que dois revisores decidiram diferente: pauta da reuniao de consenso.
DROP VIEW IF EXISTS v_discordancias_triagem;
CREATE VIEW v_discordancias_triagem AS
SELECT a.artigo_id, ar.titulo, a.revisor AS revisor_a, a.decisao AS decisao_a, a.motivo AS motivo_a,
       b.revisor AS revisor_b, b.decisao AS decisao_b, b.motivo AS motivo_b, t.decisao AS decisao_final
FROM v_ultima_revisao_triagem a
JOIN v_ultima_revisao_triagem b ON a.artigo_id = b.artigo_id AND a.revisor < b.revisor AND a.decisao <> b.decisao
JOIN artigos ar ON ar.artigo_id = a.artigo_id
LEFT JOIN triagem t ON t.artigo_id = a.artigo_id
ORDER BY a.artigo_id;

-- Gasto de cada provedor em TODAS as execucoes (dentro e fora do relatorio). `n_ok_sem_custo` conta chamadas bem-sucedidas
-- sem custo gravado em provedores que registram custo em outras chamadas (execucoes feitas antes do custo ser gravado).
DROP VIEW IF EXISTS v_gasto_real;
CREATE VIEW v_gasto_real AS
SELECT c.provedor, e.no_relatorio, COUNT(*) AS n_chamadas, COALESCE(SUM(c.sucesso), 0) AS n_ok,
       ROUND(COALESCE(SUM(c.custo_usd), 0), 4) AS custo_registrado_usd,
       COALESCE(SUM(c.sucesso = 1 AND c.custo_usd IS NULL
                    AND EXISTS (SELECT 1 FROM chamadas x WHERE x.provedor = c.provedor AND x.custo_usd IS NOT NULL)), 0) AS n_ok_sem_custo
FROM chamadas c JOIN execucoes e ON e.run_id = c.run_id
GROUP BY c.provedor, e.no_relatorio;

-- Classificacoes cuja resposta nao e um JSON valido e que nao tem outra classificacao valida do mesmo par (url, uf):
-- o par NAO pode ser tratado como "sem achados". `finish_reason` (nos extras da chamada) ajuda a ver a causa.
DROP VIEW IF EXISTS v_classificacoes_invalidas;
CREATE VIEW v_classificacoes_invalidas AS
SELECT k.classificacao_id, k.run_id, k.url_id, k.uf, k.classificador, k.prompt_versao, k.origem_texto,
       json_extract(c.extras_json, '$.finish_reason') AS finish_reason, c.tokens_saida, substr(k.resposta_texto, 1, 200) AS inicio_da_resposta
FROM r_classificacoes k JOIN chamadas c ON c.chamada_id = k.chamada_id
WHERE k.json_valido = 0;       -- r_classificacoes so traz a vigente do par, que e invalida apenas se nenhuma outra do par for valida

-- A evidencia citada sustenta o achado? `evidencia_confere` so mede se o trecho existe no texto; estas duas checagens
-- (sem LLM) medem se ele cita um termo da tecnologia e se o flag de LGPD do modelo tem respaldo no proprio trecho.
-- Comportamento do modelo por versao do prompt: le o historico, como v_qualidade_classificacao.
DROP VIEW IF EXISTS v_consistencia_evidencia;
CREATE VIEW v_consistencia_evidencia AS
SELECT k.classificador, k.prompt_versao, COUNT(*) AS n_achados,
       COALESCE(SUM(a.evidencia_cita_tecnologia = 1), 0) AS n_evidencia_cita_tecnologia,
       ROUND(100.0 * SUM(a.evidencia_cita_tecnologia = 1) / NULLIF(SUM(a.evidencia_cita_tecnologia IS NOT NULL), 0), 1) AS pct_evidencia_cita_tecnologia,
       COALESCE(SUM(a.menciona_lgpd = 1), 0) AS n_lgpd_modelo,
       COALESCE(SUM(a.menciona_lgpd = 1 AND a.evidencia_cita_lgpd = 1), 0) AS n_lgpd_modelo_com_respaldo,
       COALESCE(SUM(a.menciona_lgpd = 1 AND COALESCE(a.evidencia_cita_lgpd, 0) = 0), 0) AS n_lgpd_modelo_sem_respaldo,
       COALESCE(SUM(COALESCE(a.menciona_lgpd, 0) = 0 AND a.evidencia_cita_lgpd = 1), 0) AS n_lgpd_no_trecho_sem_flag
FROM r_achados_historico a JOIN r_classificacoes_historico k ON k.classificacao_id = a.classificacao_id
GROUP BY k.classificador, k.prompt_versao;

-- ===== Revisao por mais de uma pessoa: achados (Tarefa 1) =====
-- Espelha as views da triagem. So entram revisoes independentes (achados-importar --independente); o revisor 'consenso'
-- fica fora. Desfecho = confirmado (qualquer status_final diferente de 'descartado') ou descartado.

DROP VIEW IF EXISTS v_ultima_revisao_achados;
CREATE VIEW v_ultima_revisao_achados AS
SELECT r.achado_id, r.verificado_por AS revisor, r.status_final, r.observacao,
       CASE WHEN r.status_final = 'descartado' THEN 'descartado' ELSE 'confirmado' END AS desfecho
FROM achados_revisoes r
WHERE r.independente = 1
  AND r.revisao_id = (SELECT MAX(x.revisao_id) FROM achados_revisoes x
                      WHERE x.achado_id = r.achado_id AND x.verificado_por = r.verificado_por AND x.independente = 1)
  AND r.verificado_por <> 'consenso' AND r.status_final IS NOT NULL;

-- Concordancia entre cada par de revisores nos achados que os dois revisaram de forma independente: kappa de Cohen sobre o
-- desfecho (confirmado x descartado, mesma conta de v_concordancia_revisores) e, a parte, quantos deram exatamente o mesmo status_final.
DROP VIEW IF EXISTS v_concordancia_revisores_achados;
CREATE VIEW v_concordancia_revisores_achados AS
WITH pares AS (
    SELECT a.revisor AS revisor_a, b.revisor AS revisor_b, a.desfecho AS da, b.desfecho AS db,
           CASE WHEN a.status_final = b.status_final THEN 1 ELSE 0 END AS status_igual
    FROM v_ultima_revisao_achados a JOIN v_ultima_revisao_achados b ON a.achado_id = b.achado_id AND a.revisor < b.revisor),
 tot AS (
    SELECT revisor_a, revisor_b, COUNT(*) AS n, SUM(status_igual) AS n_status_iguais,
           SUM(da = 'confirmado' AND db = 'confirmado') AS n11, SUM(da = 'confirmado' AND db = 'descartado') AS n10,
           SUM(da = 'descartado' AND db = 'confirmado') AS n01, SUM(da = 'descartado' AND db = 'descartado') AS n00
    FROM pares GROUP BY revisor_a, revisor_b),
 base AS (
    SELECT *, ((n11 + n10) * 1.0 / n) * ((n11 + n01) * 1.0 / n) + ((n01 + n00) * 1.0 / n) * ((n10 + n00) * 1.0 / n) AS pe FROM tot)
SELECT revisor_a, revisor_b, n AS n_achados_em_comum, n11 AS ambos_confirmam, n00 AS ambos_descartam, n10 + n01 AS discordancias,
       ROUND(100.0 * (n11 + n00) / n, 1) AS concordancia_pct,
       ROUND((((n11 + n00) * 1.0 / n) - pe) / NULLIF(1 - pe, 0), 3) AS kappa,
       n_status_iguais, ROUND(100.0 * n_status_iguais / n, 1) AS concordancia_status_pct
FROM base;

-- Achados em que dois revisores decidiram diferente (desfecho ou status_final): pauta da reuniao de consenso, com a decisao final.
DROP VIEW IF EXISTS v_discordancias_achados;
CREATE VIEW v_discordancias_achados AS
SELECT a.achado_id, ac.uf, ac.tecnologia, u.url_original AS url, ac.evidencia,
       a.revisor AS revisor_a, a.status_final AS status_a, a.observacao AS observacao_a,
       b.revisor AS revisor_b, b.status_final AS status_b, b.observacao AS observacao_b,
       CASE WHEN a.desfecho <> b.desfecho THEN 'confirmado_x_descartado' ELSE 'status_diferente' END AS tipo_discordancia,
       ac.status_final AS status_final, ac.verificado
FROM v_ultima_revisao_achados a
JOIN v_ultima_revisao_achados b ON a.achado_id = b.achado_id AND a.revisor < b.revisor AND a.status_final <> b.status_final
JOIN achados ac ON ac.achado_id = a.achado_id
JOIN classificacoes k ON k.classificacao_id = ac.classificacao_id
JOIN urls u ON u.url_id = k.url_id
ORDER BY CASE WHEN a.desfecho <> b.desfecho THEN 0 ELSE 1 END, a.achado_id;

-- ===== Auditoria do que o modelo nao marcou =====
-- Universo da auditoria: classificacoes VIGENTES de JSON valido, feitas sobre o texto da pagina (nao snippet), em que o modelo
-- nao devolveu nenhum achado (sem achados gravados e n_achados = 0, ou relevante = 0).
DROP VIEW IF EXISTS v_negativos_auditaveis;
CREATE VIEW v_negativos_auditaveis AS
SELECT k.classificacao_id, k.url_id, k.uf, k.run_id, k.classificador, k.prompt_versao, k.pagina_id
FROM r_classificacoes k
WHERE k.json_valido = 1 AND k.origem_texto = 'pagina'
  AND (COALESCE(k.n_achados, 0) = 0 OR COALESCE(k.relevante, 0) = 0)
  AND NOT EXISTS (SELECT 1 FROM achados a WHERE a.classificacao_id = k.classificacao_id);
-- Unidade = a classificacao (se mais de um revisor conferiu a mesma, vale a posicao conservadora: basta um achar a aplicacao).
-- So conta classificacoes das execucoes do relatorio. `n_auditadas` so tem sentido na linha `total`; nas linhas `tecnologia`
-- (so as aplicacoes perdidas, por tecnologia) a coluna `n_com_aplicacao_perdida` conta classificacoes distintas.
DROP VIEW IF EXISTS v_auditoria_negativos;
CREATE VIEW v_auditoria_negativos AS
WITH por_classificacao AS (
    SELECT n.classificacao_id, MAX(n.tinha_aplicacao) AS perdida
    FROM auditoria_negativos n JOIN r_classificacoes_historico k ON k.classificacao_id = n.classificacao_id
    GROUP BY n.classificacao_id)
SELECT 'total' AS grupo, NULL AS tecnologia, COUNT(*) AS n_auditadas, COALESCE(SUM(perdida), 0) AS n_com_aplicacao_perdida,
       ROUND(100.0 * SUM(perdida) / NULLIF(COUNT(*), 0), 1) AS taxa_perdida_pct
FROM por_classificacao
UNION ALL
SELECT 'tecnologia', COALESCE(n.tecnologia, '(sem tecnologia)'), NULL, COUNT(DISTINCT n.classificacao_id), NULL
FROM auditoria_negativos n JOIN r_classificacoes_historico k ON k.classificacao_id = n.classificacao_id
WHERE n.tinha_aplicacao = 1 GROUP BY COALESCE(n.tecnologia, '(sem tecnologia)');

-- sugestoes sobre uma decisao ja tomada (D78): quem nao e o autor sugere outro valor; o autor ou um administrador aceita ou descarta
CREATE TABLE IF NOT EXISTS sugestoes (
    sugestao_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    alvo_tipo     TEXT NOT NULL CHECK (alvo_tipo IN ('achado', 'artigo')),
    alvo_id       INTEGER NOT NULL,
    valor         TEXT NOT NULL,
    motivo        TEXT NOT NULL DEFAULT '',
    autor         TEXT NOT NULL,
    autor_chave   TEXT NOT NULL,                  -- nome do autor normalizado (NFC + casefold), para comparar pessoas
    estado_alvo   TEXT NOT NULL,                  -- ficha da decisao que o autor viu (hash de todos os campos da decisao)
    valor_alvo    TEXT NOT NULL,                  -- valor da decisao que o autor viu (status_final / decisao)
    criado_em     TEXT NOT NULL,
    situacao      TEXT NOT NULL DEFAULT 'aberta' CHECK (situacao IN ('aberta', 'aceita', 'descartada')),
    resolvido_por TEXT,
    resolvido_em  TEXT
);
CREATE INDEX IF NOT EXISTS ix_sugestoes_alvo ON sugestoes(alvo_tipo, alvo_id, situacao);
CREATE UNIQUE INDEX IF NOT EXISTS ux_sugestoes_aberta ON sugestoes(alvo_tipo, alvo_id, autor_chave, valor, estado_alvo) WHERE situacao = 'aberta';

-- Envio de execucoes do computador local para a nuvem (D99, D100): quem enviou cada execucao e a correspondencia entre o
-- numero local de cada linha e o numero dela neste banco. No banco local ficam vazias.
CREATE TABLE IF NOT EXISTS envios_execucao (
    run_id            TEXT PRIMARY KEY,
    usuario_id        INTEGER NOT NULL,             -- a conta (tokens_api) que enviou primeiro; so ela reenvia
    primeiro_envio_em TEXT NOT NULL,
    ultimo_envio_em   TEXT NOT NULL,
    n_envios          INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS origem_ids (
    run_id     TEXT NOT NULL,
    tabela     TEXT NOT NULL,
    id_local   INTEGER NOT NULL,
    id_central INTEGER NOT NULL,
    PRIMARY KEY (run_id, tabela, id_local)
);
-- leitura de uma execucao inteira (o pacote do envio e a juntada) sem varrer a tabela
CREATE INDEX IF NOT EXISTS ix_execucoes_retomadas_run ON execucoes_retomadas(run_id);
CREATE INDEX IF NOT EXISTS ix_saldos_run ON saldos(run_id);
CREATE INDEX IF NOT EXISTS ix_ocorrencias_run ON ocorrencias(run_id);
CREATE INDEX IF NOT EXISTS ix_resultados_web_run ON resultados_web(run_id);
CREATE INDEX IF NOT EXISTS ix_paginas_run ON paginas(run_id);
CREATE INDEX IF NOT EXISTS ix_classificacoes_run ON classificacoes(run_id);

-- ===== Busca de literatura cientifica e cinzenta na web (D103 a D106) =====
-- Uma linha por URL normalizada achada pela busca de literatura (fora de `urls`, que e da Tarefa 1).
CREATE TABLE IF NOT EXISTS referencias_web (
    referencia_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    url_normalizada  TEXT NOT NULL UNIQUE,
    url_original     TEXT NOT NULL,
    dominio          TEXT NOT NULL,
    primeira_vez_run TEXT NOT NULL,
    primeira_vez_em  TEXT NOT NULL
);
-- Cada resultado de cada consulta, com o conjunto (A, B) e a consulta (LA1, ...) que trouxe a referencia.
CREATE TABLE IF NOT EXISTS ocorrencias_web (
    ocorrencia_id INTEGER PRIMARY KEY AUTOINCREMENT,
    chamada_id    INTEGER NOT NULL REFERENCES chamadas(chamada_id),
    run_id        TEXT NOT NULL,
    conjunto      TEXT NOT NULL,
    consulta_id   TEXT NOT NULL,
    referencia_id INTEGER NOT NULL REFERENCES referencias_web(referencia_id),
    posicao       INTEGER,
    titulo        TEXT,
    snippet       TEXT,
    data_pub      TEXT
);
CREATE INDEX IF NOT EXISTS ix_ocorrencias_web_run ON ocorrencias_web(run_id);
CREATE INDEX IF NOT EXISTS ix_ocorrencias_web_referencia ON ocorrencias_web(referencia_id);

-- Validacao humana da triagem do banco `vies` por amostra (RB34): a amostra sorteada, a resposta do modelo no momento do
-- sorteio e a da pessoa, que confere sem ver a do modelo.
CREATE TABLE IF NOT EXISTS validacao_vies (
    ordem             INTEGER PRIMARY KEY,
    fonte             TEXT NOT NULL CHECK (fonte IN ('artigo', 'referencia')),
    item_id           INTEGER NOT NULL,
    triagem_id        INTEGER NOT NULL REFERENCES triagem_escopo(id),
    estrato           TEXT NOT NULL,
    estrato_tamanho   INTEGER NOT NULL,
    modelo_relevancia TEXT NOT NULL,
    modelo_grupo      TEXT,
    modelo_eixo       TEXT NOT NULL,
    modelo_pais       TEXT NOT NULL,
    relevancia        TEXT,
    grupo             TEXT,
    eixo              TEXT,
    pais              TEXT,
    revisor           TEXT,
    respondido_em     TEXT,
    sorteado_em       TEXT NOT NULL,
    UNIQUE (fonte, item_id)
);
