BEGIN;

ALTER TABLE public.product_categories
    DROP CONSTRAINT IF EXISTS product_categories_name_key;

DO $$
DECLARE
    existing_definition text;
    global_index text;
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_index i
        JOIN pg_class index_class ON index_class.oid = i.indexrelid
        JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attname = 'name'
        WHERE i.indrelid = 'public.product_categories'::regclass
          AND index_class.relname = 'ix_product_categories_name'
          AND i.indisunique
          AND i.indnkeyatts = 1
          AND i.indkey[0] = a.attnum
          AND i.indpred IS NULL
          AND NOT EXISTS (SELECT 1 FROM pg_constraint c WHERE c.conindid = i.indexrelid)
    ) THEN
        DROP INDEX public.ix_product_categories_name;
    END IF;

    SELECT pg_get_constraintdef(oid)
    INTO existing_definition
    FROM pg_constraint
    WHERE conrelid = 'public.product_categories'::regclass
      AND conname = 'product_categories_tenant_name_key';

    IF existing_definition IS NULL THEN
        ALTER TABLE public.product_categories
            ADD CONSTRAINT product_categories_tenant_name_key UNIQUE (tenant_id, name);
    ELSIF existing_definition <> 'UNIQUE (tenant_id, name)' THEN
        RAISE EXCEPTION 'product_categories_tenant_name_key has unexpected definition: %',
            existing_definition;
    END IF;

    SELECT index_class.relname
    INTO global_index
    FROM pg_index i
    JOIN pg_class index_class ON index_class.oid = i.indexrelid
    JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attname = 'name'
    WHERE i.indrelid = 'public.product_categories'::regclass
      AND i.indisunique
      AND i.indnkeyatts = 1
      AND i.indkey[0] = a.attnum
    LIMIT 1;

    IF global_index IS NOT NULL THEN
        RAISE EXCEPTION 'Another global unique index on product_categories.name remains: %. Inspect it before migrating.', global_index;
    END IF;
END $$;

COMMIT;
