-- Triagem da busca de vies algoritmico (banco `vies`): tipo de fonte com o sufixo (D110), pais ou escopo por extenso,
-- topicos separados por "; " e um dos 6 eixos de exploracao. As mesmas colunas de adaptadores/schema.sql.

ALTER TABLE triagem_escopo ADD COLUMN IF NOT EXISTS tipo_fonte TEXT COLLATE "C";
ALTER TABLE triagem_escopo ADD COLUMN IF NOT EXISTS pais_escopo TEXT COLLATE "C";
ALTER TABLE triagem_escopo ADD COLUMN IF NOT EXISTS topicos TEXT COLLATE "C";
ALTER TABLE triagem_escopo ADD COLUMN IF NOT EXISTS eixo TEXT COLLATE "C";
