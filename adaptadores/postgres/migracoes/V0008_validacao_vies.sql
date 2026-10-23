-- Validacao humana da triagem do banco `vies` por amostra (RB34). As mesmas colunas de adaptadores/schema.sql.

CREATE TABLE IF NOT EXISTS validacao_vies (
    ordem             BIGINT PRIMARY KEY,
    fonte             TEXT COLLATE "C" NOT NULL CHECK (fonte IN ('artigo', 'referencia')),
    item_id           BIGINT NOT NULL,
    triagem_id        BIGINT NOT NULL REFERENCES triagem_escopo(id),
    estrato           TEXT COLLATE "C" NOT NULL,
    estrato_tamanho   BIGINT NOT NULL,
    modelo_relevancia TEXT COLLATE "C" NOT NULL,
    modelo_grupo      TEXT COLLATE "C",
    modelo_eixo       TEXT COLLATE "C" NOT NULL,
    modelo_pais       TEXT COLLATE "C" NOT NULL,
    relevancia        TEXT COLLATE "C",
    grupo             TEXT COLLATE "C",
    eixo              TEXT COLLATE "C",
    pais              TEXT COLLATE "C",
    revisor           TEXT COLLATE "C",
    respondido_em     TEXT COLLATE "C",
    sorteado_em       TEXT COLLATE "C" NOT NULL,
    UNIQUE (fonte, item_id)
);
