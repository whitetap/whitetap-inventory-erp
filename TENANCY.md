# Tenant deployment

The deployed entry point is `app_fixed_final:app`. This code assumes the tenant
schema has already been migrated; it does not run schema migrations or create
tenants automatically. It also no longer performs request-time schema changes.

Before deploying, take and verify a restorable backup and test on a restored,
disposable PostgreSQL copy. Verify that every business table mapped in
`app_fixed_final.py`, including `usage_logs`, `quotations` and their item tables,
has a non-null `tenant_id` referencing `tenants`, and that every existing row
belongs to the correct tenant. Check related rows have matching tenant IDs.
Existing rows and tokens are expected to belong to the `whitetap` tenant.

Verify database constraints independently: category names, normalized client
names, invoice numbers, quotation numbers and purchase order numbers must be
unique per tenant rather than globally; `tenant_users` must prevent duplicate
case-insensitive email addresses within a tenant. Tenant-aware foreign keys are
required for database-level isolation of related business rows. This code does not change existing
SKU uniqueness or repair existing duplicates. SQLAlchemy model declarations do
not modify constraints in an existing database.

Run `migrations/product_categories_tenant_name.sql` against a verified backup
or staging copy before deploying the category seeding change, then apply it to
production during a controlled migration. It replaces the known global category
name constraint with `(tenant_id, name)` without deleting category rows. It also
removes the known legacy standalone unique index `ix_product_categories_name`
when that index uniquely covers only `name`. If another single-column global
unique index exists, it aborts and rolls back so
that the index can be inspected. Existing duplicate `(tenant_id, name)` pairs
also make the migration fail without changing the table.

Set `DATABASE_URL` and a new, long, random `SECRET_KEY` in the hosting
environment. Changing the secret signs out existing sessions. HTTPS is required
by the default secure session cookie. For local HTTP development only, set
`SESSION_COOKIE_SECURE=false`. Configure login rate limiting at the reverse
proxy; account lockout, password reset and multi-factor authentication are not
implemented here.

Public organization signup is enabled by default. Set
`PUBLIC_SIGNUP_ENABLED=false` to disable signup while provisioning and
verifying the initial owner, or whenever public registrations should be paused.
The form at `/signup` creates an organization and its first administrator in one
transaction, generates a unique URL slug, and redirects to its login page.
The public landing page displays the signup form only when enabled. Existing
users can enter their organization's slug to reach its login page; organization
names are not publicly listed. The tenant table has no active/inactive status.
Signup rejects email addresses already used by any tenant, case-insensitively;
other provisioning paths continue to permit the same email in different tenants.
PostgreSQL application signup and the user-provisioning command use the same
transaction advisory lock. External writers must honor that lock or enforce
equivalent database constraints to avoid concurrent duplicate email creation.

Signup does not verify email addresses, implement recovery, CAPTCHA, rate
limits, or organization approval. Configure rate limiting and abuse protection
at the reverse proxy and consider email verification before exposing the signup
form to the public. Signup with an empty user table will prevent the initial-admin
bootstrap from running on subsequent startups; provision the owner first.

Provision accounts using the deployment environment after confirming the
`whitetap` tenant exists:

Alternatively, to bootstrap the first account automatically at startup, set
`INITIAL_ADMIN_PASSWORD` to a strong password of at least 12 characters and
optionally set `INITIAL_ADMIN_EMAIL` (defaults to `admin@whitetap.com`). The
bootstrap runs when importing the Gunicorn application, and only creates a user
when the entire `tenant_users` table is empty. It requires the `whitetap` tenant
to have ID 1 and fails startup if that tenant or the supplied credentials are
invalid. PostgreSQL startup workers coordinate with a transaction advisory lock;
do not provision users concurrently through another process that does not take
the same lock. If the password is absent, startup skips the bootstrap without a
database check. Remove the initial password from the deployment environment
after the account has been created and verified, so it cannot be reused if the
user table is later emptied. Never commit it or put it in a command-line argument.

For further accounts, use:

```shell
flask --app app_fixed_final create-tenant-user --tenant-slug whitetap --role admin
flask --app app_fixed_final create-tenant-user --tenant-slug whitetap --role staff
```

The command prompts for email and password; passwords are hashed with Werkzeug.
Create accounts for each company and staff member. It does not create companies
or provide a super-admin dashboard. Passwords must be at least 12 characters.
Do not pass passwords on the command line.

Users sign in at `/<tenant_slug>/login`. All staff routes now require an account;
admin routes require the `admin` role. Old unprefixed application routes resolve
only to Whitetap and still require authentication. Existing supplier links
`/po/respond/<token>` continue to resolve only to Whitetap; new links use
`/po/respond/<tenant_slug>/<token>`. Unsafe requests require the CSRF token from
the form or the `X-CSRF-Token` header.

ORM queries and bulk deletes are scoped to the current tenant, while normal
business writes check tenant ownership and references. Raw SQL through the ORM
session is rejected during tenant requests, and bulk inserts and updates are
rejected. These are application-level controls, not PostgreSQL row-level
security: direct connections, SQL executed outside request handling, and future
code bypassing the ORM require their own protection. Use a restricted database
role and review all new code and database access paths.

Run `python -m unittest discover -s tests -v` to exercise the isolated SQLite
tests. They do not validate PostgreSQL migrations, actual production constraints,
or real production data.

For PostgreSQL smoke tests, create a disposable local database named `erp_test`,
set `ERP_TEST_DATABASE_URL` to its local PostgreSQL connection URL, and run
`python tests/postgres_smoke.py`. The test creates and removes its own schema;
it requires permission to create schemas and does not inspect the live database.

The dashboard's today's usage count matches the ISO date prefix of `created_at`
directly using `LIKE`, so the PostgreSQL column must be text or VARCHAR and
its values must begin with `YYYY-MM-DD`. Usage-log report and export date filters still cast
`created_at` to `DATE` on PostgreSQL. For those filters, text values
must be valid PostgreSQL date/timestamp input, and timestamp-with-time-zone
values are interpreted in the database session time zone. Casting may prevent
use of a plain `created_at` index. Usage-log values returned as dates or ISO
timestamp strings are normalized to Python datetimes for display; invalid
values fail explicitly. Verify the live column type and data before deployment.
SQLite tests use its `date()` function because SQLite's
`CAST(... AS DATE)` does not implement PostgreSQL date semantics.
