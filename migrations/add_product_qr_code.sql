BEGIN;

ALTER TABLE public.products
    ADD COLUMN IF NOT EXISTS qr_code VARCHAR(64);

UPDATE public.products
SET qr_code = 'WTI-' || upper(replace(id::text, '-', ''))
WHERE qr_code IS NULL OR btrim(qr_code) = '';

ALTER TABLE public.products
    ALTER COLUMN qr_code
    SET DEFAULT ('WTI-' || upper(replace(gen_random_uuid()::text, '-', '')));

CREATE UNIQUE INDEX IF NOT EXISTS ux_products_qr_code
    ON public.products (qr_code);

ALTER TABLE public.products
    ALTER COLUMN qr_code SET NOT NULL;

COMMIT;
