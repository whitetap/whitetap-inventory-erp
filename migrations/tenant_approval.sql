BEGIN;

LOCK TABLE public.tenants IN ACCESS EXCLUSIVE MODE;

DO $$
DECLARE
    has_status boolean;
    has_active boolean;
BEGIN
    SELECT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema = 'public' AND table_name = 'tenants' AND column_name = 'approval_status'),
           EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema = 'public' AND table_name = 'tenants' AND column_name = 'is_active')
    INTO has_status, has_active;
    IF has_status <> has_active THEN
        RAISE EXCEPTION 'Only one approval column exists; inspect the schema before migrating';
    END IF;
    IF NOT has_status THEN
        ALTER TABLE public.tenants ADD COLUMN approval_status VARCHAR(50);
        ALTER TABLE public.tenants ADD COLUMN is_active BOOLEAN;
        UPDATE public.tenants SET approval_status = 'approved', is_active = TRUE;
    END IF;
END $$;

ALTER TABLE public.tenants ALTER COLUMN approval_status SET DEFAULT 'pending';
ALTER TABLE public.tenants ALTER COLUMN is_active SET DEFAULT FALSE;
ALTER TABLE public.tenants ALTER COLUMN approval_status SET NOT NULL;
ALTER TABLE public.tenants ALTER COLUMN is_active SET NOT NULL;

COMMIT;
