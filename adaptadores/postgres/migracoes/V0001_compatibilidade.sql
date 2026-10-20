-- Funcoes de compatibilidade: dao ao PostgreSQL a semantica do SQLite que as views e as leituras do painel usam,
-- para que o mesmo texto SQL valha nos dois bancos (ADR-postgresql-neon). Nao muda dado nenhum.

-- SUM(condicao): no SQLite a condicao vale 0/1; soma ignora NULL e devolve NULL se nao houve valor
CREATE OR REPLACE FUNCTION compat_soma_bool(acc bigint, v boolean) RETURNS bigint LANGUAGE sql IMMUTABLE AS
$$ SELECT CASE WHEN v IS NULL THEN acc ELSE COALESCE(acc, 0) + v::int END $$;
CREATE OR REPLACE AGGREGATE sum(boolean) (SFUNC = compat_soma_bool, STYPE = bigint);

-- MAX(condicao) e MIN(condicao): 0/1, NULL se nao houve valor
CREATE OR REPLACE FUNCTION compat_max_bool(acc integer, v boolean) RETURNS integer LANGUAGE sql IMMUTABLE AS
$$ SELECT CASE WHEN v IS NULL THEN acc ELSE GREATEST(COALESCE(acc, 0), v::int) END $$;
CREATE OR REPLACE AGGREGATE max(boolean) (SFUNC = compat_max_bool, STYPE = integer);
CREATE OR REPLACE FUNCTION compat_min_bool(acc integer, v boolean) RETURNS integer LANGUAGE sql IMMUTABLE AS
$$ SELECT CASE WHEN v IS NULL THEN acc ELSE LEAST(COALESCE(acc, 1), v::int) END $$;
CREATE OR REPLACE AGGREGATE min(boolean) (SFUNC = compat_min_bool, STYPE = integer);

-- ROUND(numero real, casas) com a regra do SQLite: arredonda o valor binario exato do numero, metade para longe do zero
-- (2.675 e guardado como 2.67499999... e vira 2.67). Casas negativas valem 0; acima de 2^52 o numero volta como esta.
CREATE OR REPLACE FUNCTION round(x double precision, n integer) RETURNS double precision LANGUAGE plpgsql IMMUTABLE STRICT AS $$
DECLARE
    a double precision := abs(x);
    e integer;
    k integer;
    m numeric;
    dois_k numeric;
    escala numeric;
    q numeric;
    resto numeric;
BEGIN
    IF n < 0 THEN n := 0; END IF;
    IF n > 30 THEN n := 30; END IF;
    IF a = 0 OR a > 4503599627370496.0 OR a <> a THEN RETURN x; END IF;
    IF n = 0 THEN                                           -- o SQLite soma 0,5 em ponto flutuante e trunca
        RETURN trunc(x + CASE WHEN x < 0 THEN -0.5::double precision ELSE 0.5::double precision END);
    END IF;
    e := floor(log(2.0, a::numeric))::integer;
    WHILE power(2.0::double precision, e) > a LOOP e := e - 1; END LOOP;
    WHILE power(2.0::double precision, e + 1) <= a LOOP e := e + 1; END LOOP;
    k := 52 - e;                                            -- a * 2^k e inteiro exato (< 2^53)
    m := (a * power(2.0::double precision, k))::bigint::numeric;
    dois_k := power(2::numeric, k);
    escala := power(10::numeric, n);
    q := floor(m * escala / dois_k);
    resto := m * escala - q * dois_k;
    IF 2 * resto >= dois_k THEN q := q + 1; END IF;
    RETURN (sign(x)::numeric * q / escala)::double precision;
END $$;

-- instr(texto, trecho): posicao a partir de 1, 0 se nao houver
CREATE OR REPLACE FUNCTION instr(texto text, trecho text) RETURNS integer LANGUAGE sql IMMUTABLE STRICT AS
$$ SELECT strpos(texto, trecho) $$;

-- GROUP_CONCAT(valor, separador) e GROUP_CONCAT(valor): ignora NULL
CREATE OR REPLACE FUNCTION compat_concat(acc text, v text, sep text) RETURNS text LANGUAGE sql IMMUTABLE AS
$$ SELECT CASE WHEN v IS NULL THEN acc WHEN acc IS NULL THEN v ELSE acc || sep || v END $$;
CREATE OR REPLACE AGGREGATE group_concat(text, text) (SFUNC = compat_concat, STYPE = text);
CREATE OR REPLACE FUNCTION compat_concat1(acc text, v text) RETURNS text LANGUAGE sql IMMUTABLE AS
$$ SELECT CASE WHEN v IS NULL THEN acc WHEN acc IS NULL THEN v ELSE acc || ',' || v END $$;
CREATE OR REPLACE AGGREGATE group_concat(text) (SFUNC = compat_concat1, STYPE = text);

-- json_extract(documento, '$.a.b'): o valor como texto (caminhos simples, os unicos usados)
CREATE OR REPLACE FUNCTION json_extract(doc text, caminho text) RETURNS text LANGUAGE sql IMMUTABLE STRICT AS
$$ SELECT doc::jsonb #>> string_to_array(substr(caminho, 3), '.') $$;

-- substr(texto, inicio, tamanho) com a regra do SQLite para tamanho negativo (os caracteres antes do inicio; nunca erro)
CREATE OR REPLACE FUNCTION compat_substr(t text, s bigint, n bigint) RETURNS text LANGUAGE sql IMMUTABLE STRICT AS
$$ SELECT CASE WHEN n >= 0 THEN substr(t, s::integer, n::integer)
              ELSE substr(t, GREATEST(s + n, 1)::integer, GREATEST(-n - GREATEST(1 - (s + n), 0), 0)::integer) END $$;
CREATE OR REPLACE FUNCTION compat_substr(t text, s bigint) RETURNS text LANGUAGE sql IMMUTABLE STRICT AS
$$ SELECT substr(t, s::integer) $$;
