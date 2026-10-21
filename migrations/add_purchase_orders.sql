BEGIN;

CREATE TABLE IF NOT EXISTS public.purchase_orders (
    id BIGSERIAL PRIMARY KEY,
    po_number VARCHAR(40) NOT NULL UNIQUE,
    supplier TEXT NOT NULL,
    currency VARCHAR(3) NOT NULL CHECK (currency IN ('USD', 'KES')),
    vat_mode VARCHAR(10) NOT NULL CHECK (vat_mode IN ('standard', 'exempt')),
    vat_rate NUMERIC(5, 2) NOT NULL,
    subtotal NUMERIC(14, 2) NOT NULL,
    vat_amount NUMERIC(14, 2) NOT NULL,
    total NUMERIC(14, 2) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_purchase_orders_supplier
    ON public.purchase_orders (supplier);

CREATE TABLE IF NOT EXISTS public.purchase_order_items (
    id BIGSERIAL PRIMARY KEY,
    purchase_order_id BIGINT NOT NULL
        REFERENCES public.purchase_orders(id) ON DELETE CASCADE,
    product_id UUID,
    product_sku TEXT,
    product_name TEXT NOT NULL,
    quantity NUMERIC(14, 3) NOT NULL,
    unit TEXT,
    unit_cost NUMERIC(14, 2) NOT NULL,
    line_total NUMERIC(14, 2) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_purchase_order_items_order_id
    ON public.purchase_order_items (purchase_order_id);

ALTER TABLE public.purchase_orders ALTER COLUMN status TYPE VARCHAR(30);
ALTER TABLE public.purchase_orders
    ADD COLUMN IF NOT EXISTS supplier_emails TEXT,
    ADD COLUMN IF NOT EXISTS approval_token VARCHAR(64),
    ADD COLUMN IF NOT EXISTS supplier_comment TEXT,
    ADD COLUMN IF NOT EXISTS invoice_number VARCHAR(120),
    ADD COLUMN IF NOT EXISTS waybill_number VARCHAR(120),
    ADD COLUMN IF NOT EXISTS driver_phone VARCHAR(60),
    ADD COLUMN IF NOT EXISTS status_updated_at TIMESTAMPTZ;
CREATE UNIQUE INDEX IF NOT EXISTS ix_purchase_orders_approval_token
    ON public.purchase_orders (approval_token);

ALTER TABLE public.purchase_order_items
    ADD COLUMN IF NOT EXISTS supplier_included BOOLEAN,
    ADD COLUMN IF NOT EXISTS supplier_quantity NUMERIC(14, 3),
    ADD COLUMN IF NOT EXISTS supplier_unit_cost NUMERIC(14, 2);

CREATE TABLE IF NOT EXISTS public.purchase_order_events (
    id BIGSERIAL PRIMARY KEY,
    purchase_order_id BIGINT NOT NULL
        REFERENCES public.purchase_orders(id) ON DELETE CASCADE,
    status VARCHAR(30) NOT NULL,
    actor VARCHAR(20) NOT NULL DEFAULT 'staff',
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_purchase_order_events_order_id
    ON public.purchase_order_events (purchase_order_id);

COMMIT;
