BEGIN;

ALTER TABLE public.products
    ADD COLUMN IF NOT EXISTS supplier TEXT,
    ADD COLUMN IF NOT EXISTS invoice_number TEXT,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ;

ALTER TABLE public.products
    ALTER COLUMN current_stock DROP DEFAULT,
    ALTER COLUMN parent_stock DROP DEFAULT,
    ALTER COLUMN min_stock_level DROP DEFAULT;

ALTER TABLE public.products
    ALTER COLUMN current_stock TYPE NUMERIC USING current_stock::numeric,
    ALTER COLUMN parent_stock TYPE NUMERIC USING parent_stock::numeric,
    ALTER COLUMN min_stock_level TYPE NUMERIC USING min_stock_level::numeric;

UPDATE public.products
SET current_stock = COALESCE(current_stock, 0),
    parent_stock = COALESCE(parent_stock, 0),
    min_stock_level = COALESCE(min_stock_level, 0),
    created_at = COALESCE(created_at, NOW());

ALTER TABLE public.products
    ALTER COLUMN current_stock SET DEFAULT 0,
    ALTER COLUMN current_stock SET NOT NULL,
    ALTER COLUMN parent_stock SET DEFAULT 0,
    ALTER COLUMN parent_stock SET NOT NULL,
    ALTER COLUMN min_stock_level SET DEFAULT 0,
    ALTER COLUMN min_stock_level SET NOT NULL,
    ALTER COLUMN created_at SET DEFAULT NOW(),
    ALTER COLUMN created_at SET NOT NULL;

CREATE INDEX IF NOT EXISTS ix_products_supplier ON public.products (supplier);
CREATE INDEX IF NOT EXISTS ix_products_invoice_number ON public.products (invoice_number);
CREATE INDEX IF NOT EXISTS ix_products_created_at ON public.products (created_at);

COMMIT;
