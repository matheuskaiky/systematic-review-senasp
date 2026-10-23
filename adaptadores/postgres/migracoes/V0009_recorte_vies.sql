-- Triagem da busca de vies, prompt v2: o recorte de cada item (vies_algoritmico ou aplicacoes_tecnologicas). A mesma
-- coluna de adaptadores/schema.sql.

ALTER TABLE triagem_escopo ADD COLUMN IF NOT EXISTS recorte TEXT COLLATE "C";
