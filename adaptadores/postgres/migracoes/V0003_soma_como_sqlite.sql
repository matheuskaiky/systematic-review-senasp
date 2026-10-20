-- SUM com a regra do SQLite (3.43+): inteiros somam como inteiro; reais somam com compensacao de erro (Kahan-Babuska-
-- Neumaier), o que o sum() do PostgreSQL nao faz; condicoes somam 0/1. As views e as leituras usam compat_soma no
-- lugar de SUM (adaptadores/postgres/traducao.py). NULL e ignorado; sem valor, o resultado e NULL.

CREATE OR REPLACE FUNCTION compat_soma_int(acc bigint, v bigint) RETURNS bigint LANGUAGE sql IMMUTABLE AS
$$ SELECT CASE WHEN v IS NULL THEN acc ELSE COALESCE(acc, 0) + v END $$;
CREATE OR REPLACE AGGREGATE compat_soma(bigint) (SFUNC = compat_soma_int, STYPE = bigint);
CREATE OR REPLACE FUNCTION compat_soma_int4(acc bigint, v integer) RETURNS bigint LANGUAGE sql IMMUTABLE AS
$$ SELECT CASE WHEN v IS NULL THEN acc ELSE COALESCE(acc, 0) + v END $$;
CREATE OR REPLACE AGGREGATE compat_soma(integer) (SFUNC = compat_soma_int4, STYPE = bigint);
CREATE OR REPLACE AGGREGATE compat_soma(boolean) (SFUNC = compat_soma_bool, STYPE = bigint);

CREATE OR REPLACE FUNCTION compat_kbn(st double precision[], v double precision) RETURNS double precision[] LANGUAGE plpgsql
IMMUTABLE AS $$
DECLARE
    s double precision;
    c double precision;
    t double precision;
BEGIN
    IF v IS NULL THEN RETURN st; END IF;
    IF st IS NULL THEN RETURN ARRAY[v, 0::double precision]; END IF;
    s := st[1];
    c := st[2];
    t := s + v;
    IF abs(s) >= abs(v) THEN c := c + ((s - t) + v); ELSE c := c + ((v - t) + s); END IF;
    RETURN ARRAY[t, c];
END $$;
CREATE OR REPLACE FUNCTION compat_kbn_fim(st double precision[]) RETURNS double precision LANGUAGE sql IMMUTABLE AS
$$ SELECT CASE WHEN st IS NULL THEN NULL ELSE st[1] + st[2] END $$;
CREATE OR REPLACE AGGREGATE compat_soma(double precision) (SFUNC = compat_kbn, STYPE = double precision[], FINALFUNC = compat_kbn_fim);
