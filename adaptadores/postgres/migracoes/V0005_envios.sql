-- Envio de execucoes do local para a nuvem (D99, D100): dono de cada execucao e correspondencia dos numeros locais.

CREATE TABLE IF NOT EXISTS envios_execucao (
    run_id            TEXT COLLATE "C" PRIMARY KEY,
    usuario_id        BIGINT NOT NULL,             -- a conta (tokens_api) que enviou primeiro; so ela reenvia
    primeiro_envio_em TEXT COLLATE "C" NOT NULL,
    ultimo_envio_em   TEXT COLLATE "C" NOT NULL,
    n_envios          BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS origem_ids (
    run_id     TEXT COLLATE "C" NOT NULL,
    tabela     TEXT COLLATE "C" NOT NULL,
    id_local   BIGINT NOT NULL,
    id_central BIGINT NOT NULL,
    PRIMARY KEY (run_id, tabela, id_local)
);

-- leitura de uma execucao inteira (o pacote do envio e a juntada) sem varrer a tabela
CREATE INDEX IF NOT EXISTS ix_execucoes_retomadas_run ON execucoes_retomadas(run_id);
CREATE INDEX IF NOT EXISTS ix_saldos_run ON saldos(run_id);
CREATE INDEX IF NOT EXISTS ix_ocorrencias_run ON ocorrencias(run_id);
CREATE INDEX IF NOT EXISTS ix_resultados_web_run ON resultados_web(run_id);
CREATE INDEX IF NOT EXISTS ix_paginas_run ON paginas(run_id);
CREATE INDEX IF NOT EXISTS ix_classificacoes_run ON classificacoes(run_id);
