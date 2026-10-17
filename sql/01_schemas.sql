-- staging = out/ ki clean CSVs (sab TEXT), dw = star schema (Power BI yahan se parhega)
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS dw;

-- Kharab date par script girne ki bajaye NULL deta hai (data drop 2 identical nahi hoga)
CREATE OR REPLACE FUNCTION dw.safe_date(t TEXT) RETURNS DATE LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
  IF t IS NULL OR t !~ '^\d{4}-\d{2}-\d{2}' THEN RETURN NULL; END IF;
  RETURN left(t,10)::date;
EXCEPTION WHEN others THEN RETURN NULL;
END $$;

-- 'Rs. 1,500' jaisi value ko bhi number bana deta hai, ya NULL (script nahi girta)
CREATE OR REPLACE FUNCTION dw.safe_num(t TEXT) RETURNS NUMERIC LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
  RETURN NULLIF(regexp_replace(t, '[^0-9.\-]', '', 'g'), '')::numeric;
EXCEPTION WHEN others THEN RETURN NULL;
END $$;
