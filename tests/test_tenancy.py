import os
import re
import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

os.environ['DATABASE_URL'] = 'sqlite://'
os.environ['SECRET_KEY'] = 'test-secret-not-for-production'
os.environ['SESSION_COOKIE_SECURE'] = 'false'
os.environ['INITIAL_ADMIN_PASSWORD'] = ''

from flask import g, url_for, template_rendered
from sqlalchemy import event, select, text
from werkzeug.security import generate_password_hash

from app_fixed_final import (
    app, db, Tenant, TenantUser, Product, PurchaseOrder, UsageLog
)


class TenantIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config.update(TESTING=True)
        with app.app_context():
            db.create_all()
            db.session.add_all([
                Tenant(id=1, name='Whitetap', slug='whitetap'),
                Tenant(id=2, name='Other', slug='other'),
                TenantUser(id=1, tenant_id=1, email='admin@example.test',
                           password_hash=generate_password_hash('whitetap-password'), role='admin'),
                TenantUser(id=2, tenant_id=2, email='admin@example.test',
                           password_hash=generate_password_hash('other-password'), role='staff'),
            ])
            db.session.commit()
        cls.product_ids = [uuid4(), uuid4()]
        for tenant_id in (1, 2):
            with app.test_request_context('/'):
                g.current_tenant = db.session.get(Tenant, tenant_id)
                db.session.add(Product(
                    id=cls.product_ids[tenant_id - 1], sku=f'SKU-{tenant_id}',
                    qr_code=f'QR-{tenant_id}', name=f'Product {tenant_id}',
                    current_stock=Decimal('5'), parent_stock=Decimal('0'),
                    min_stock_level=Decimal('0')
                ))
                db.session.add(PurchaseOrder(
                    id=tenant_id, po_number=f'PO-{tenant_id}', supplier='Supplier',
                    currency='USD', vat_mode='exempt', vat_rate=0,
                    subtotal=0, vat_amount=0, total=0,
                    approval_token=f'token-{tenant_id}-abcdefghijklmnop'
                ))
                db.session.commit()

    @classmethod
    def tearDownClass(cls):
        with app.app_context():
            db.session.remove()
            db.drop_all()

    def setUp(self):
        self.client = app.test_client()

    def login(self, slug, password):
        page = self.client.get(f'/{slug}/login')
        token = re.search(rb'name="csrf_token" value="([^"]+)"', page.data).group(1).decode()
        return self.client.post(f'/{slug}/login', data={
            'csrf_token': token, 'email': 'admin@example.test', 'password': password
        })

    def test_tenant_login_and_isolated_lookup(self):
        response = self.login('whitetap', 'whitetap-password')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith('/whitetap/admin-dashboard'))
        own = self.client.get('/whitetap/api/products/lookup?identifier=SKU-1')
        other = self.client.get('/whitetap/api/products/lookup?identifier=SKU-2')
        self.assertEqual(own.status_code, 200)
        self.assertEqual(other.status_code, 404)
        self.assertEqual(self.client.get('/other/api/products/lookup?identifier=SKU-2').status_code, 401)

    def test_legacy_routes_are_whitetap_only(self):
        self.login('other', 'other-password')
        self.assertEqual(self.client.get('/api/products/lookup?identifier=SKU-1').status_code, 401)
        self.login('whitetap', 'whitetap-password')
        self.assertEqual(self.client.get('/api/products/lookup?identifier=SKU-1').status_code, 200)
        self.assertEqual(self.client.get('/not-a-tenant/login').status_code, 404)

    def test_staff_cannot_access_admin_or_mutation_routes(self):
        self.login('other', 'other-password')
        self.assertEqual(self.client.get('/other/admin-dashboard').status_code, 403)
        with self.client.session_transaction() as sess:
            sess['csrf_token'] = 'a' * 32
        self.assertEqual(self.client.post('/other/admin/add-product', data={
            'csrf_token': 'a' * 32
        }).status_code, 403)

    def test_supplier_token_is_scoped_and_legacy_link_works(self):
        self.assertEqual(self.client.get('/po/respond/whitetap/token-1-abcdefghijklmnop').status_code, 200)
        self.assertEqual(self.client.get('/po/respond/other/token-1-abcdefghijklmnop').status_code, 404)
        self.assertEqual(self.client.get('/po/respond/token-1-abcdefghijklmnop').status_code, 200)
        self.assertEqual(self.client.get('/po/respond/token-2-abcdefghijklmnop').status_code, 404)

    def test_bulk_delete_and_cross_tenant_reference(self):
        with app.test_request_context('/'):
            g.current_tenant = db.session.get(Tenant, 1)
            self.assertEqual(Product.query.filter_by(id=self.product_ids[1]).delete(), 0)
            db.session.rollback()
            db.session.add(UsageLog(
                id=1, product_id=self.product_ids[1], quantity_used=1, technician_name='Test'
            ))
            with self.assertRaises(ValueError):
                db.session.flush()
            db.session.rollback()

    def test_aggregate_queries_and_bulk_updates(self):
        with app.test_request_context('/'):
            g.current_tenant = db.session.get(Tenant, 1)
            self.assertEqual(db.session.query(Product.sku).all(), [('SKU-1',)])
            with self.assertRaises(RuntimeError):
                Product.query.update({'current_stock': 999})
            db.session.rollback()
            with self.assertRaises(RuntimeError):
                db.session.execute(text('SELECT * FROM products'))
            with self.assertRaises(RuntimeError):
                db.session.execute(select(Product).from_statement(text('SELECT * FROM products')))

    def test_url_building_uses_tenant_and_supplier_route(self):
        with app.test_request_context('/'):
            g.current_tenant = db.session.get(Tenant, 2)
            self.assertEqual(url_for('staff_inventory'), '/other/staff-inventory')
            self.assertEqual(
                url_for('supplier_po_response', token='token-2-abcdefghijklmnop'),
                '/po/respond/other/token-2-abcdefghijklmnop'
            )

    def test_issue_product_and_reject_other_tenant_product(self):
        self.login('whitetap', 'whitetap-password')
        with self.client.session_transaction() as sess:
            sess['csrf_token'] = 'b' * 32
        data = {
            'csrf_token': 'b' * 32, 'product_id': str(self.product_ids[1]),
            'quantity_used': '1', 'technician_name': 'Test'
        }
        self.client.post('/whitetap/issue-item', data=data)
        with app.test_request_context('/'):
            g.current_tenant = db.session.get(Tenant, 1)
            self.assertEqual(UsageLog.query.count(), 0)
        data['product_id'] = str(self.product_ids[0])
        self.client.post('/whitetap/issue-item', data=data)
        with app.test_request_context('/'):
            g.current_tenant = db.session.get(Tenant, 1)
            self.assertEqual(UsageLog.query.count(), 1)
            self.assertEqual(Product.query.get(self.product_ids[0]).current_stock, 4)

    def test_existing_pages_render_with_tenant_links(self):
        self.login('whitetap', 'whitetap-password')
        for path in (
            '/whitetap/', '/whitetap/admin-dashboard', '/whitetap/staff-inventory',
            '/whitetap/staff/quotations', '/whitetap/staff/purchase-orders',
            '/whitetap/admin/proforma-invoices', '/whitetap/admin/usage-logs',
            '/whitetap/admin/added-products', '/whitetap/export-products'
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
        page = self.client.get('/whitetap/staff-inventory')
        self.assertIn(b'/whitetap/api/products/lookup', page.data)
        self.assertIn(b'/whitetap/api/tint-recipes', page.data)

    def test_dashboard_usage_count_is_direct_and_tenant_scoped(self):
        created_ids = []
        today = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
        try:
            for tenant_id, created_at in (
                (1, today), (1, today - timedelta(days=1)), (2, today)
            ):
                with app.test_request_context('/'):
                    g.current_tenant = db.session.get(Tenant, tenant_id)
                    log = UsageLog(
                        product_id=self.product_ids[tenant_id - 1],
                        quantity_used=1, technician_name='Count test', created_at=created_at
                    )
                    db.session.add(log)
                    db.session.flush()
                    created_ids.append((tenant_id, log.id))
                    db.session.commit()

            statements = []
            contexts = []

            def record_sql(conn, cursor, statement, parameters, context, executemany):
                if 'count(' in statement.lower() and 'usage_logs' in statement.lower():
                    statements.append(statement)

            def record_template(sender, template, context, **extra):
                if template.name == 'admin.html':
                    contexts.append(context)

            self.login('whitetap', 'whitetap-password')
            with app.app_context():
                engine = db.engine
            event.listen(engine, 'before_cursor_execute', record_sql)
            template_rendered.connect(record_template, app, weak=False)
            try:
                response = self.client.get('/whitetap/admin-dashboard')
            finally:
                event.remove(engine, 'before_cursor_execute', record_sql)
                template_rendered.disconnect(record_template, app)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(contexts[0]['today_logs'], 1)
            self.assertEqual(len(statements), 1)
            self.assertNotIn('anon_1', statements[0].lower())
            self.assertIn('usage_logs.tenant_id', statements[0].lower())
        finally:
            for tenant_id, log_id in created_ids:
                with app.test_request_context('/'):
                    g.current_tenant = db.session.get(Tenant, tenant_id)
                    UsageLog.query.filter_by(id=log_id).delete()
                    db.session.commit()

    def test_csrf_required_for_state_changes(self):
        self.login('whitetap', 'whitetap-password')
        response = self.client.post('/whitetap/admin/add-product', data={})
        self.assertEqual(response.status_code, 400)


if __name__ == '__main__':
    unittest.main()
