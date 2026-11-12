"""Run against a disposable local database named erp_test."""

import os
import re
import sys
from datetime import datetime
from uuid import uuid4

import psycopg2
from psycopg2 import sql
from sqlalchemy.engine import make_url


test_url = os.environ.get('ERP_TEST_DATABASE_URL')
if not test_url:
    raise SystemExit('Set ERP_TEST_DATABASE_URL to a disposable local erp_test database')
url = make_url(test_url)
if url.get_backend_name() != 'postgresql' or url.host not in ('127.0.0.1', 'localhost', '::1') or url.database != 'erp_test':
    raise SystemExit('Only a local PostgreSQL database named erp_test is allowed')

schema = f'erp_smoke_{uuid4().hex}'
admin_connection = psycopg2.connect(url.set(drivername='postgresql').render_as_string(hide_password=False))
admin_connection.autocommit = True
with admin_connection.cursor() as cursor:
    cursor.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))

try:
    options = dict(url.query)
    options['options'] = f'-csearch_path={schema}'
    os.environ['DATABASE_URL'] = url.set(query=options).render_as_string(hide_password=False)
    os.environ['SECRET_KEY'] = 'test-secret-not-for-production'
    os.environ['INITIAL_ADMIN_PASSWORD'] = ''
    os.environ['PUBLIC_SIGNUP_ENABLED'] = 'true'
    os.environ['SESSION_COOKIE_SECURE'] = 'false'
    sys.path.insert(0, os.getcwd())
    from app_fixed_final import app, db, Product, ProductCategory, Tenant, TenantUser, UsageLog
    from flask import g, template_rendered
    from werkzeug.security import generate_password_hash

    app.config['TESTING'] = True
    with app.app_context():
        db.create_all()
        db.session.add(Tenant(name='Whitetap', slug='whitetap'))
        db.session.flush()
        db.session.add(TenantUser(tenant_id=1, email='admin@example.test',
                                  password_hash=generate_password_hash('long-enough-password'), role='admin'))
        db.session.commit()
        with app.test_request_context('/'):
            g.current_tenant = db.session.get(Tenant, 1)
            product = Product(sku='SKU-1', qr_code='QR-1', name='Test product',
                              current_stock=5, parent_stock=0, min_stock_level=0)
            db.session.add(product)
            db.session.flush()
            db.session.add(UsageLog(product_id=product.id, quantity_used=-1,
                                    technician_name='Test', project_ref='TEST', created_at=datetime.now()))
            db.session.commit()

    client = app.test_client()
    page = client.get('/whitetap/login')
    assert page.status_code == 200
    token = re.search(rb'name="csrf_token" value="([^"]+)"', page.data).group(1).decode()
    assert client.post('/whitetap/login', data={
        'csrf_token': token, 'email': 'admin@example.test', 'password': 'long-enough-password'
    }).status_code == 302
    signup_client = app.test_client()
    signup_page = signup_client.get('/signup')
    token = re.search(rb'name="csrf_token" value="([^"]+)"', signup_page.data).group(1).decode()
    signup = signup_client.post('/signup', data={
        'csrf_token': token, 'organization_name': 'Second Company',
        'email': 'second@example.test', 'password': 'long-enough-password'
    })
    assert signup.status_code == 302 and signup.location.endswith('/second-company/login')
    with app.app_context(), app.test_request_context('/'):
        tenant = Tenant.query.filter_by(slug='second-company').one()
        g.current_tenant = tenant
        assert ProductCategory.query.count() > 0
        assert Product.query.count() == 0
        assert UsageLog.query.count() == 0
    for path in ('/whitetap/admin-dashboard', '/whitetap/staff-inventory',
                 '/whitetap/admin/usage-logs?period=daily', '/whitetap/export-logs?period=daily',
                 '/whitetap/admin/proforma-invoices?project_ref=TEST',
                 '/whitetap/staff/quotations', '/whitetap/staff/purchase-orders',
                 '/whitetap/admin/added-products?period=7'):
        response = client.get(path)
        assert response.status_code == 200, (path, response.status_code)

    with app.app_context():
        db.session.remove()
        db.engine.dispose()
    for column_type in ('TIMESTAMP WITH TIME ZONE', 'DATE', 'TEXT'):
        with admin_connection.cursor() as cursor:
            cursor.execute(sql.SQL('ALTER TABLE {}.usage_logs ALTER COLUMN created_at TYPE {} USING created_at::{}')
                           .format(sql.Identifier(schema), sql.SQL(column_type), sql.SQL(column_type)))
        for path in ('/whitetap/admin-dashboard', '/whitetap/staff-inventory',
                     '/whitetap/admin/usage-logs?period=daily', '/whitetap/export-logs?period=daily'):
            response = client.get(path)
            assert response.status_code == 200, (column_type, path, response.status_code)
    with admin_connection.cursor() as cursor:
        cursor.execute(sql.SQL('UPDATE {}.usage_logs SET created_at = %s').format(sql.Identifier(schema)),
                       (f'{datetime.now().date().isoformat()} invalid timestamp',))
    dashboard_counts = []

    def record_dashboard(sender, template, context, **extra):
        if template.name == 'admin.html':
            dashboard_counts.append(context['today_logs'])

    template_rendered.connect(record_dashboard, app, weak=False)
    try:
        assert client.get('/whitetap/admin-dashboard').status_code == 200
        assert dashboard_counts == [1], dashboard_counts
    finally:
        template_rendered.disconnect(record_dashboard, app)
    with app.app_context():
        db.session.remove()
        db.engine.dispose()
    print('PostgreSQL signup, tenant isolation, login, navigation, and date/timestamp/text smoke tests passed')
finally:
    with admin_connection.cursor() as cursor:
        cursor.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
    admin_connection.close()
