-- Token de envio por usuario (D98): so o hash e o comeco do token; um por usuario.

CREATE TABLE IF NOT EXISTS tokens_api (
    usuario_id BIGINT PRIMARY KEY REFERENCES usuarios(usuario_id),
    token_hash TEXT COLLATE "C" NOT NULL UNIQUE,
    inicio TEXT COLLATE "C" NOT NULL,
    criado_em TEXT COLLATE "C" NOT NULL,
    ultimo_uso TEXT COLLATE "C"
);
