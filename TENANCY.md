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

Set `DATABASE_URL` and a new, long, random `SECRET_KEY` in the hosting
environment. Changing the secret signs out existing sessions. HTTPS is required
by the default secure session cookie. For local HTTP development only, set
`SESSION_COOKIE_SECURE=false`. Configure login rate limiting at the reverse
proxy; account lockout, password reset and multi-factor authentication are not
implemented here.

Provision accounts using the deployment environment after confirming the
`whitetap` tenant exists:

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
