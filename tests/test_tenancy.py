import os
import re
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

os.environ['DATABASE_URL'] = 'sqlite://'
os.environ['SECRET_KEY'] = 'test-secret-not-for-production'
os.environ['SESSION_COOKIE_SECURE'] = 'false'
os.environ['INITIAL_ADMIN_PASSWORD'] = ''
os.environ.pop('PUBLIC_SIGNUP_ENABLED', None)

from flask import g, url_for, template_rendered
from sqlalchemy import event, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session, aliased
from werkzeug.security import check_password_hash, generate_password_hash

from app_fixed_final import (
    app, db, Tenant, TenantUser, Product, ProductCategory, PurchaseOrder, UsageLog,
    Client, ProformaInvoice, usage_period_bounds, get_project_invoice_lines, tenant_products
)


class TenantIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config.update(TESTING=True)
        with app.app_context():
            db.create_all()
            db.session.add_all([
                Tenant(id=1, name='Whitetap', slug='whitetap', approval_status='approved', is_active=True),
                Tenant(id=2, name='Other', slug='other', approval_status='approved', is_active=True),
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
        env_patch = patch.dict(os.environ, {'SUPER_ADMIN_PASSWORD': '', 'INITIAL_ADMIN_PASSWORD': ''})
        env_patch.start()
        self.addCleanup(env_patch.stop)
        original_signup_setting = app.config['PUBLIC_SIGNUP_ENABLED']
        self.addCleanup(app.config.update, PUBLIC_SIGNUP_ENABLED=original_signup_setting)

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

    def test_inventory_surfaces_are_isolated_between_tenants(self):
        created = []
        try:
            for tenant_id, label in ((1, 'ALPHAPRIVATE'), (2, 'BETAPRIVATE')):
                with app.test_request_context('/'):
                    g.current_tenant = db.session.get(Tenant, tenant_id)
                    category = ProductCategory(name=f'{label} category')
                    db.session.add(category)
                    db.session.flush()
                    product = Product(
                        name=f'{label} product', sku=f'PNT-CRP-{label}',
                        qr_code=f'QR-{label}', supplier=f'{label} supplier',
                        unit_of_measure='private-unit-' + label, category_id=category.id,
                        current_stock=1, parent_stock=0, min_stock_level=2
                    )
                    db.session.add(product)
                    db.session.flush()
                    created.append((tenant_id, product.id, category.id))
                    db.session.commit()

            for slug, password, own, other in (
                ('whitetap', 'whitetap-password', 'ALPHAPRIVATE', 'BETAPRIVATE'),
                ('other', 'other-password', 'BETAPRIVATE', 'ALPHAPRIVATE')
            ):
                self.login(slug, password)
                for suffix in (
                    '/staff-inventory', '/export-products', '/export-inventory',
                    '/export-paints', '/export-carpets', '/staff/quotations',
                    f'/staff/purchase-orders?supplier={own}%20supplier'
                ):
                    with self.subTest(slug=slug, route=suffix):
                        response = self.client.get(f'/{slug}{suffix}')
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(response.headers.get('Cache-Control'), 'no-store')
                        self.assertIn(own.encode(), response.data)
                        self.assertNotIn(other.encode(), response.data)
                response = self.client.get(f'/{slug}/api/products/lookup?identifier=PNT-CRP-{other}')
                self.assertEqual(response.status_code, 404)
                response = self.client.get(f'/{slug}/api/products/lookup?identifier=PNT-CRP-{own}')
                self.assertEqual(response.status_code, 200)
            self.login('whitetap', 'whitetap-password')
            for suffix in ('/admin-dashboard?view=inventory', '/admin/added-products'):
                response = self.client.get('/whitetap' + suffix)
                self.assertEqual(response.status_code, 200)
                self.assertIn(b'ALPHAPRIVATE', response.data)
                self.assertNotIn(b'BETAPRIVATE', response.data)
            self.assertEqual(self.client.get(f'/whitetap/edit-product/{created[1][1]}').status_code, 404)
            with self.client.session_transaction() as sess:
                sess['csrf_token'] = 'i' * 32
            response = self.client.post('/whitetap/admin/add-product', data={
                'csrf_token': 'i' * 32, 'name': 'Forbidden category', 'sku': 'FORBIDDEN-CATEGORY',
                'unit_of_measure': 'each', 'category_id': str(created[1][2])
            }, follow_redirects=True)
            self.assertIn(b'Please choose a valid category', response.data)
            with app.test_request_context('/'):
                g.current_tenant = db.session.get(Tenant, 1)
                self.assertIsNone(tenant_products().filter_by(sku='FORBIDDEN-CATEGORY').first())
            with app.test_request_context('/'):
                g.current_tenant = db.session.get(Tenant, 2)
                self.assertIsNotNone(db.session.get(Product, created[1][1]))
                g.current_tenant = db.session.get(Tenant, 1)
                self.assertIsNone(tenant_products().filter_by(id=created[1][1]).first())
        finally:
            for tenant_id, product_id, category_id in created:
                with app.test_request_context('/'):
                    g.current_tenant = db.session.get(Tenant, tenant_id)
                    Product.query.filter_by(id=product_id).delete()
                    ProductCategory.query.filter_by(id=category_id).delete()
                    db.session.commit()

    def test_business_inserts_receive_current_tenant(self):
        with app.app_context(), self.assertRaises(RuntimeError):
            tenant_products()
        with app.test_request_context('/'):
            g.current_tenant = db.session.get(Tenant, 2)
            try:
                category = ProductCategory(name='Ownership test')
                client = Client(id=91001, name='Ownership test', normalized_name='ownership test')
                order = PurchaseOrder(
                    id=91002, po_number='OWNERSHIP-TEST', supplier='Supplier',
                    currency='USD', vat_mode='exempt', vat_rate=0,
                    subtotal=0, vat_amount=0, total=0
                )
                db.session.add_all([category, client, order])
                db.session.flush()
                product = Product(
                    name='Ownership test', sku='OWNERSHIP', category_id=category.id,
                    current_stock=0, parent_stock=0, min_stock_level=0
                )
                invoice = ProformaInvoice(
                    id=91003, invoice_number='OWNERSHIP-TEST', client_id=client.id,
                    project_ref='test', currency='USD', tax_mode='exempt', tax_rate=0,
                    subtotal=0, tax_amount=0, total=0
                )
                db.session.add_all([product, invoice])
                db.session.flush()
                for item in (category, client, order, product, invoice):
                    self.assertEqual(item.tenant_id, 2)
                db.session.add(Product(name='Wrong owner', tenant_id=1))
                with self.assertRaises(RuntimeError):
                    db.session.flush()
            finally:
                db.session.rollback()

    def test_owner_approval_lock_unlock_and_existing_sessions(self):
        owner = app.test_client()
        original = app.config['SUPER_ADMIN_PASSWORD_HASH']
        app.config['SUPER_ADMIN_PASSWORD_HASH'] = generate_password_hash('owner-test-password')
        self.addCleanup(app.config.update, SUPER_ADMIN_PASSWORD_HASH=original)
        self.login('whitetap', 'whitetap-password')
        self.assertEqual(self.client.get('/super-admin/tenants').status_code, 302)
        self.assertEqual(self.client.get('/super-admin/dashboard').status_code, 302)
        self.assertEqual(owner.get('/super-admin/tenants').status_code, 302)
        self.assertEqual(owner.post('/super-admin/tenants/1/lock').status_code, 400)
        page = owner.get('/super-admin/owner-login')
        token = re.search(rb'name="csrf_token" value="([^"]+)"', page.data).group(1).decode()
        self.assertEqual(owner.post('/super-admin/tenants/1/lock').status_code, 400)
        response = owner.post('/super-admin/owner-login', data={'csrf_token': token, 'password': 'wrong'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(owner.get('/super-admin/tenants').status_code, 302)
        response = owner.post('/super-admin/owner-login', data={'csrf_token': token, 'password': 'owner-test-password'})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith('/super-admin/dashboard'))
        page = owner.get('/super-admin/dashboard')
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.headers.get('Cache-Control'), 'no-store')
        self.assertIn(b'Whitetap', page.data)
        self.assertIn(b'admin@example.test', page.data)
        self.assertIn(b'No administrator', page.data)
        self.assertIn(b'Signup date', page.data)
        self.assertIn(b'Initial admin email', page.data)
        self.assertEqual(owner.get('/super-admin/tenants').status_code, 200)
        token = re.search(rb'name="csrf_token" value="([^"]+)"', page.data).group(1).decode()
        self.assertEqual(owner.post('/super-admin/tenants/1/lock', data={'csrf_token': token}).status_code, 302)
        try:
            self.assertEqual(self.client.get('/whitetap/api/products/lookup?identifier=SKU-1').status_code, 403)
            self.assertEqual(self.client.get('/po/respond/whitetap/token-1-abcdefghijklmnop').status_code, 403)
            response = self.login('whitetap', 'whitetap-password')
            self.assertEqual(response.status_code, 403)
            self.assertIn(b'This account has been locked', response.data)
            self.assertEqual(owner.post('/super-admin/tenants/1/unlock', data={'csrf_token': token}).status_code, 302)
            self.assertEqual(self.login('whitetap', 'whitetap-password').status_code, 302)
            self.assertEqual(self.client.get('/po/respond/whitetap/token-1-abcdefghijklmnop').status_code, 200)
            self.assertEqual(self.client.get('/whitetap/api/products/lookup?identifier=SKU-1').status_code, 200)
            with app.test_request_context('/'):
                g.current_tenant = db.session.get(Tenant, 1)
                self.assertIsNotNone(db.session.get(Product, self.product_ids[0]))
                self.assertIsNotNone(PurchaseOrder.query.filter_by(po_number='PO-1').first())
            with app.app_context():
                tenant = db.session.get(Tenant, 1)
                tenant.approval_status, tenant.is_active = 'suspended', True
                db.session.commit()
            self.assertEqual(self.client.get('/po/respond/whitetap/token-1-abcdefghijklmnop').status_code, 403)
            self.assertEqual(self.login('whitetap', 'whitetap-password').status_code, 403)
            self.assertEqual(owner.post('/super-admin/tenants/1/unlock', data={'csrf_token': token}).status_code, 302)
            self.assertEqual(owner.post('/super-admin/tenants/1/approve', data={'csrf_token': token}).status_code, 409)
            self.assertEqual(owner.post('/super-admin/tenants/99999/lock', data={'csrf_token': token}).status_code, 404)
            with owner.session_transaction() as owner_session:
                owner_session['super_admin_issued'] = (datetime.now(timezone.utc) - timedelta(minutes=31)).timestamp()
            self.assertEqual(owner.get('/super-admin/tenants').status_code, 302)
            owner.post('/super-admin/owner-login', data={'csrf_token': token, 'password': 'owner-test-password'})
            self.assertEqual(owner.get('/super-admin/tenants').status_code, 200)
            app.config['SUPER_ADMIN_PASSWORD_HASH'] = generate_password_hash('rotated-test-password')
            self.assertEqual(owner.get('/super-admin/tenants').status_code, 302)
        finally:
            with app.app_context():
                tenant = db.session.get(Tenant, 1)
                tenant.approval_status, tenant.is_active = 'approved', True
                db.session.commit()

    def test_owner_access_disabled_without_password(self):
        original = app.config['SUPER_ADMIN_PASSWORD_HASH']
        app.config['SUPER_ADMIN_PASSWORD_HASH'] = ''
        self.addCleanup(app.config.update, SUPER_ADMIN_PASSWORD_HASH=original)
        self.assertEqual(self.client.get('/super-admin/owner-login').status_code, 503)
        self.assertEqual(self.client.get('/super-admin/tenants').status_code, 503)
        self.assertEqual(self.client.get('/super-admin/dashboard').status_code, 503)

    def test_owner_environment_password_precedence_fallback_and_rotation(self):
        original = app.config['SUPER_ADMIN_PASSWORD_HASH']
        app.config['SUPER_ADMIN_PASSWORD_HASH'] = ''
        self.addCleanup(app.config.update, SUPER_ADMIN_PASSWORD_HASH=original)
        os.environ['INITIAL_ADMIN_PASSWORD'] = 'initial-password-test'
        page = self.client.get('/super-admin/owner-login')
        self.assertEqual(page.status_code, 200)
        token = re.search(rb'name="csrf_token" value="([^"]+)"', page.data).group(1).decode()
        self.assertEqual(self.client.post('/super-admin/owner-login', data={
            'csrf_token': token, 'password': 'initial-password-test'
        }).status_code, 302)
        self.assertEqual(self.client.get('/super-admin/dashboard').status_code, 200)
        os.environ['SUPER_ADMIN_PASSWORD'] = 'dedicated-password-test'
        self.assertEqual(self.client.get('/super-admin/dashboard').status_code, 302)
        page = self.client.get('/super-admin/owner-login')
        token = re.search(rb'name="csrf_token" value="([^"]+)"', page.data).group(1).decode()
        self.assertEqual(self.client.post('/super-admin/owner-login', data={
            'csrf_token': token, 'password': 'initial-password-test'
        }).status_code, 200)
        app.config['SUPER_ADMIN_PASSWORD_HASH'] = generate_password_hash('hash-password-test')
        self.assertEqual(self.client.post('/super-admin/owner-login', data={
            'csrf_token': token, 'password': 'hash-password-test'
        }).status_code, 200)
        self.assertEqual(self.client.post('/super-admin/owner-login', data={
            'csrf_token': token, 'password': 'dedicated-password-test'
        }).status_code, 302)
        self.assertEqual(self.client.get('/super-admin/dashboard').status_code, 200)
        os.environ['SUPER_ADMIN_PASSWORD'] = ''
        self.assertEqual(self.client.get('/super-admin/dashboard').status_code, 302)
        page = self.client.get('/super-admin/owner-login')
        token = re.search(rb'name="csrf_token" value="([^"]+)"', page.data).group(1).decode()
        self.assertEqual(self.client.post('/super-admin/owner-login', data={
            'csrf_token': token, 'password': 'initial-password-test'
        }).status_code, 200)
        self.assertEqual(self.client.post('/super-admin/owner-login', data={
            'csrf_token': token, 'password': 'hash-password-test'
        }).status_code, 302)
        app.config['SUPER_ADMIN_PASSWORD_HASH'] = ''
        self.assertEqual(self.client.get('/super-admin/dashboard').status_code, 302)
        os.environ['INITIAL_ADMIN_PASSWORD'] = ''
        self.assertEqual(self.client.get('/super-admin/owner-login').status_code, 503)

    def test_company_named_super_admin_keeps_its_login_route(self):
        with app.app_context():
            tenant = Tenant(name='Company Super Admin', slug='super-admin', approval_status='approved', is_active=True)
            db.session.add(tenant)
            db.session.flush()
            user = TenantUser(tenant_id=tenant.id, email='company@example.test',
                              password_hash=generate_password_hash('company-password'), role='admin')
            db.session.add(user)
            db.session.commit()
            tenant_id, user_id = tenant.id, user.id
        try:
            page = self.client.get('/super-admin/login')
            self.assertEqual(page.status_code, 200)
            self.assertIn(b'Company Super Admin', page.data)
            token = re.search(rb'name="csrf_token" value="([^"]+)"', page.data).group(1).decode()
            response = self.client.post('/super-admin/login', data={
                'csrf_token': token, 'email': 'company@example.test', 'password': 'company-password'
            })
            self.assertTrue(response.location.endswith('/super-admin/admin-dashboard'))
        finally:
            with app.app_context():
                db.session.delete(db.session.get(TenantUser, user_id))
                db.session.delete(db.session.get(Tenant, tenant_id))
                db.session.commit()

    def test_public_signup_provisions_unique_slug_and_admin(self):
        self.assertTrue(app.config['PUBLIC_SIGNUP_ENABLED'])
        page = self.client.get('/')
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'action="/signup"', page.data)
        self.assertIn(b'minlength="12"', page.data)
        self.assertIn(b'/static/css/landing.css', page.data)
        token = re.search(rb'name="csrf_token" value="([^"]+)"', page.data).group(1).decode()
        response = self.client.post('/signup', data={
            'csrf_token': token, 'organization_name': 'Other',
            'email': ' New@Example.test ', 'password': 'new-password-123'
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith('/other-2/login'))
        with app.app_context():
            tenant = Tenant.query.filter_by(slug='other-2').one()
            user = TenantUser.query.filter_by(tenant_id=tenant.id).one()
            self.assertEqual((user.email, user.role), ('new@example.test', 'admin'))
            self.assertTrue(check_password_hash(user.password_hash, 'new-password-123'))
            self.assertEqual((tenant.approval_status, tenant.is_active), ('pending', False))
            tenant_id, user_id = tenant.id, user.id
        with app.test_request_context('/'):
            g.current_tenant = db.session.get(Tenant, tenant_id)
            self.assertEqual(ProductCategory.query.count(), 0)

        def cleanup_signup():
            with app.test_request_context('/'):
                g.current_tenant = db.session.get(Tenant, tenant_id)
                ProductCategory.query.delete()
                db.session.commit()
            with app.app_context():
                db.session.delete(db.session.get(TenantUser, user_id))
                db.session.delete(db.session.get(Tenant, tenant_id))
                db.session.commit()
        self.addCleanup(cleanup_signup)
        login_page = self.client.get(response.location)
        token = re.search(rb'name="csrf_token" value="([^"]+)"', login_page.data).group(1).decode()
        login_response = self.client.post('/other-2/login', data={
            'csrf_token': token, 'email': 'new@example.test', 'password': 'new-password-123'
        })
        self.assertEqual(login_response.status_code, 403)
        self.assertIn(b'pending approval by the system administrator', login_response.data)
        original_hash = app.config['SUPER_ADMIN_PASSWORD_HASH']
        app.config['SUPER_ADMIN_PASSWORD_HASH'] = generate_password_hash('owner-test-password')
        self.addCleanup(app.config.update, SUPER_ADMIN_PASSWORD_HASH=original_hash)
        owner = app.test_client()
        owner_page = owner.get('/super-admin/owner-login')
        owner_token = re.search(rb'name="csrf_token" value="([^"]+)"', owner_page.data).group(1).decode()
        owner.post('/super-admin/owner-login', data={'csrf_token': owner_token, 'password': 'owner-test-password'})
        owner_page = owner.get('/super-admin/tenants')
        self.assertIn(b'new@example.test', owner_page.data)
        self.assertIn(b'Pending', owner_page.data)
        self.assertIn(b'Locked', owner_page.data)
        owner_token = re.search(rb'name="csrf_token" value="([^"]+)"', owner_page.data).group(1).decode()
        self.assertEqual(owner.post(f'/super-admin/tenants/{tenant_id}/unlock', data={'csrf_token': owner_token}).status_code, 409)
        self.assertEqual(owner.post(f'/super-admin/tenants/{tenant_id}/approve', data={'csrf_token': owner_token}).status_code, 302)
        login_response = self.client.post('/other-2/login', data={
            'csrf_token': token, 'email': 'new@example.test', 'password': 'new-password-123'
        })
        self.assertTrue(login_response.location.endswith('/other-2/admin-dashboard'))
        self.assertEqual(self.client.get(login_response.location).status_code, 200)
        inventory_page = self.client.get('/other-2/admin-dashboard?view=inventory')
        self.assertIn(b'No products or categories yet', inventory_page.data)
        staff_page = self.client.get('/other-2/staff-inventory')
        self.assertIn(b'No products or categories yet', staff_page.data)
        self.assertIn(b'Good day, Other staff', staff_page.data)
        self.assertEqual(self.client.get('/other-2/api/products/lookup?identifier=SKU-1').status_code, 404)
        self.assertEqual(self.client.get('/whitetap/api/products/lookup?identifier=SKU-1').status_code, 401)

    def test_signup_validation_and_csrf(self):
        app.config['PUBLIC_SIGNUP_ENABLED'] = False
        self.assertEqual(self.client.get('/signup').status_code, 404)
        app.config['PUBLIC_SIGNUP_ENABLED'] = True
        self.addCleanup(app.config.update, PUBLIC_SIGNUP_ENABLED=False)
        self.assertEqual(self.client.post('/signup', data={}).status_code, 400)
        page = self.client.get('/signup')
        token = re.search(rb'name="csrf_token" value="([^"]+)"', page.data).group(1).decode()
        base = {'csrf_token': token, 'organization_name': 'Test Company',
                'email': 'valid@example.test', 'password': 'long-enough-password'}
        for overrides in (
            {'organization_name': '!!!'},
            {'organization_name': 'x' * 101},
            {'email': 'invalid'},
            {'email': 'ADMIN@EXAMPLE.TEST'},
            {'password': 'short'},
        ):
            data = dict(base, **overrides)
            with self.subTest(data=data):
                self.assertEqual(self.client.post('/signup', data=data).status_code, 400)
        with app.app_context():
            self.assertIsNone(Tenant.query.filter_by(slug='test-company').first())

    def test_company_greeting_and_saved_categories_are_tenant_specific(self):
        created_categories = []
        product_id = None
        try:
            with app.test_request_context('/'):
                g.current_tenant = db.session.get(Tenant, 2)
                category = ProductCategory(name='Other company category')
                db.session.add(category)
                db.session.flush()
                created_categories.append((2, category.id))
                db.session.commit()

            self.login('whitetap', 'whitetap-password')
            with self.client.session_transaction() as sess:
                sess['csrf_token'] = 'c' * 32
            response = self.client.post('/whitetap/admin/add-product', data={
                'csrf_token': 'c' * 32, 'name': 'Custom category product', 'sku': 'CUSTOM-1',
                'unit_of_measure': 'each', 'category_id': '__custom__',
                'custom_category_name': 'My saved category', 'current_stock': '1',
            })
            self.assertEqual(response.status_code, 302)
            with app.test_request_context('/'):
                g.current_tenant = db.session.get(Tenant, 1)
                product = Product.query.filter_by(sku='CUSTOM-1').one()
                product_id = product.id
                category = ProductCategory.query.filter_by(name='My saved category').one()
                created_categories.append((1, category.id))
                self.assertEqual(product.category_id, category.id)
                self.assertEqual(ProductCategory.query.count(), 1)

            for path in ('/whitetap/staff-inventory', '/whitetap/admin-dashboard?view=inventory'):
                page = self.client.get(path)
                self.assertEqual(page.status_code, 200)
                self.assertIn(b'My saved category', page.data)
                self.assertNotIn(b'Other company category', page.data)
                self.assertNotIn(b'Aviation paints &amp; pigments', page.data)
            page = self.client.get('/whitetap/staff-inventory')
            self.assertIn(b'Good day, Whitetap staff', page.data)
            self.assertIn(b'data-company-name="Whitetap"', page.data)
            self.assertIn(b'Uncategorized', page.data)
            page = self.client.get(f'/whitetap/edit-product/{self.product_ids[0]}')
            self.assertIn(b'Select a category', page.data)
            self.assertNotIn(b'Other supplies', page.data)

            self.login('other', 'other-password')
            page = self.client.get('/other/staff-inventory')
            self.assertEqual(page.status_code, 200)
            self.assertIn(b'Good day, Other staff', page.data)
            self.assertIn(b'data-company-name="Other"', page.data)
            self.assertIn(b'Other company category', page.data)
            self.assertNotIn(b'My saved category', page.data)
        finally:
            if product_id:
                with app.test_request_context('/'):
                    g.current_tenant = db.session.get(Tenant, 1)
                    Product.query.filter_by(id=product_id).delete()
                    db.session.commit()
            for tenant_id, category_id in created_categories:
                with app.test_request_context('/'):
                    g.current_tenant = db.session.get(Tenant, tenant_id)
                    ProductCategory.query.filter_by(id=category_id).delete()
                    db.session.commit()

    def test_public_landing_uses_private_organization_login(self):
        app.config['PUBLIC_SIGNUP_ENABLED'] = False
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Organization signup is currently unavailable', response.data)
        self.assertNotIn(b'action="/signup"', response.data)
        self.assertNotIn(b'Whitetap', response.data)
        self.assertNotIn(b'/whitetap/login', response.data)
        self.assertNotIn(b'Staff Inventory Portal', response.data)
        self.assertEqual(
            self.client.get('/organization-login?slug=OTHER').location,
            '/other/login'
        )
        self.assertEqual(
            self.client.get('/organization-login?slug=whitetap').location,
            '/whitetap/login'
        )
        self.assertEqual(self.client.get('/organization-login?slug=../../other').location, '/')
        self.assertEqual(self.client.get('/unknown-company/login').status_code, 404)

    def test_edit_product_checks_uuid_and_tenant(self):
        self.login('whitetap', 'whitetap-password')
        self.assertEqual(self.client.get(f'/whitetap/edit-product/{self.product_ids[0]}').status_code, 200)
        self.assertEqual(self.client.get(f'/whitetap/edit-product/{self.product_ids[1]}').status_code, 404)
        self.assertEqual(self.client.get('/whitetap/edit-product/invalid-id').status_code, 404)

    def test_signup_rolls_back_if_user_creation_fails(self):
        app.config['PUBLIC_SIGNUP_ENABLED'] = True
        self.addCleanup(app.config.update, PUBLIC_SIGNUP_ENABLED=False)
        page = self.client.get('/signup')
        token = re.search(rb'name="csrf_token" value="([^"]+)"', page.data).group(1).decode()
        with patch('app_fixed_final.generate_password_hash', side_effect=RuntimeError('test failure')):
            with self.assertRaises(RuntimeError):
                self.client.post('/signup', data={
                    'csrf_token': token, 'organization_name': 'Rollback Test',
                    'email': 'rollback@example.test', 'password': 'long-enough-password'
                })
        with app.app_context():
            self.assertIsNone(Tenant.query.filter_by(slug='rollback-test').first())

    def test_routes_have_no_duplicate_path_and_method(self):
        routes = set()
        for rule in app.url_map.iter_rules():
            for method in rule.methods - {'HEAD', 'OPTIONS'}:
                key = (rule.rule, method)
                self.assertNotIn(key, routes)
                routes.add(key)

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

    def test_usage_logs_scope_reads_deletes_and_writes_through_product(self):
        created_ids = []
        try:
            for tenant_id in (1, 2):
                with app.test_request_context('/'):
                    g.current_tenant = db.session.get(Tenant, tenant_id)
                    log = UsageLog(
                        product_id=self.product_ids[tenant_id - 1], quantity_used=1,
                        technician_name='Isolation', project_ref=f'owner-{tenant_id}'
                    )
                    db.session.add(log)
                    db.session.flush()
                    created_ids.append(log.id)
                    db.session.commit()

            with app.test_request_context('/'):
                g.current_tenant = db.session.get(Tenant, 1)
                self.assertEqual(
                    db.session.query(UsageLog.project_ref).filter(UsageLog.project_ref.like('owner-%')).all(),
                    [('owner-1',)]
                )
                log_alias = aliased(UsageLog)
                self.assertEqual(
                    db.session.query(log_alias.id).filter(log_alias.id.in_(created_ids)).all(),
                    [(created_ids[0],)]
                )
                self.assertEqual(UsageLog.query.filter_by(id=created_ids[1]).delete(), 0)
                own_log = db.session.get(UsageLog, created_ids[0])
                own_log.product_id = self.product_ids[1]
                with self.assertRaises(ValueError):
                    db.session.flush()
                db.session.rollback()

            with app.test_request_context('/'):
                g.current_tenant = db.session.get(Tenant, 2)
                other_log = db.session.get(UsageLog, created_ids[1])
                g.current_tenant = db.session.get(Tenant, 1)
                other_log.technician_name = 'Unauthorized'
                with self.assertRaises(RuntimeError):
                    db.session.flush()
                db.session.rollback()
        finally:
            for tenant_id, log_id in enumerate(created_ids, start=1):
                with app.test_request_context('/'):
                    g.current_tenant = db.session.get(Tenant, tenant_id)
                    UsageLog.query.filter_by(id=log_id).delete()
                    db.session.commit()

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
        today = datetime.combine(datetime.now().date(), datetime.min.time())
        try:
            for tenant_id, created_at in (
                (1, today), (1, today + timedelta(days=1) - timedelta(microseconds=1)),
                (1, today - timedelta(microseconds=1)), (1, today + timedelta(days=1)), (2, today)
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
            postgres_statements = []
            contexts = []

            def record_sql(conn, cursor, statement, parameters, context, executemany):
                if 'count(' in statement.lower() and 'usage_logs' in statement.lower():
                    statements.append(statement)

            def record_template(sender, template, context, **extra):
                if template.name == 'admin.html':
                    contexts.append(context)

            def record_orm(execute_state):
                if execute_state.is_select and 'count(' in str(execute_state.statement).lower():
                    compiled = execute_state.statement.compile(dialect=postgresql.dialect())
                    if 'usage_logs' in str(compiled).lower():
                        postgres_statements.append((str(compiled), compiled.params))

            self.login('whitetap', 'whitetap-password')
            with app.app_context():
                engine = db.engine
            event.listen(engine, 'before_cursor_execute', record_sql)
            event.listen(Session, 'do_orm_execute', record_orm)
            template_rendered.connect(record_template, app, weak=False)
            try:
                response = self.client.get('/whitetap/admin-dashboard')
            finally:
                event.remove(engine, 'before_cursor_execute', record_sql)
                event.remove(Session, 'do_orm_execute', record_orm)
                template_rendered.disconnect(record_template, app)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(contexts[0]['today_logs'], 2)
            self.assertEqual(len(statements), 1)
            self.assertNotIn('anon_1', statements[0].lower())
            self.assertNotIn('usage_logs.tenant_id', statements[0].lower())
            self.assertRegex(statements[0].lower(), r'products(?:_\d+)?\.tenant_id\s*=')
            self.assertEqual(len(postgres_statements), 1)
            pg_sql, pg_parameters = postgres_statements[0]
            self.assertRegex(pg_sql, r'usage_logs\.created_at\s+>=')
            self.assertRegex(pg_sql, r'usage_logs\.created_at\s+<\s')
            for forbidden in ('CAST(', 'LIKE', 'SUBSTR(', 'DATE('):
                self.assertNotIn(forbidden, pg_sql.upper())
            self.assertNotIn('usage_logs.tenant_id', pg_sql.lower())
            self.assertRegex(pg_sql.lower(), r'products(?:_\d+)?\.tenant_id\s*=')
            self.assertIn(today, pg_parameters.values())
            self.assertIn(today + timedelta(days=1), pg_parameters.values())
        finally:
            for tenant_id, log_id in created_ids:
                with app.test_request_context('/'):
                    g.current_tenant = db.session.get(Tenant, tenant_id)
                    UsageLog.query.filter_by(id=log_id).delete()
                    db.session.commit()

    def test_usage_period_filters_dates_and_tenants(self):
        created_ids = []
        today = datetime.combine(datetime.now().date(), datetime.min.time())
        try:
            for tenant_id, created_at, label in (
                (1, today, 'start'), (1, today + timedelta(days=1) - timedelta(microseconds=1), 'end'),
                (1, today - timedelta(microseconds=1), 'before'),
                (1, today + timedelta(days=1), 'after'), (2, today, 'other')
            ):
                with app.test_request_context('/'):
                    g.current_tenant = db.session.get(Tenant, tenant_id)
                    log = UsageLog(
                        product_id=self.product_ids[tenant_id - 1], quantity_used=1,
                        technician_name=f'boundary-{label}',
                        project_ref='period-filter-test', created_at=created_at
                    )
                    db.session.add(log)
                    db.session.flush()
                    created_ids.append((tenant_id, log.id))
                    db.session.commit()
            self.login('whitetap', 'whitetap-password')
            postgres_statements = []

            def record_orm(execute_state):
                if execute_state.is_select and 'usage_logs' in str(execute_state.statement):
                    compiled = execute_state.statement.compile(dialect=postgresql.dialect())
                    postgres_statements.append((str(compiled), compiled.params))

            event.listen(Session, 'do_orm_execute', record_orm)
            self.addCleanup(event.remove, Session, 'do_orm_execute', record_orm)
            for path in (
                '/whitetap/admin/usage-logs?period=daily&project_ref=period-filter-test',
                '/whitetap/export-logs?period=daily&project_ref=period-filter-test'
            ):
                with self.subTest(path=path):
                    postgres_statements.clear()
                    response = self.client.get(path)
                    self.assertEqual(response.status_code, 200)
                    for label in ('start', 'end'):
                        self.assertIn(f'boundary-{label}'.encode(), response.data)
                    for label in ('before', 'after', 'other'):
                        self.assertNotIn(f'boundary-{label}'.encode(), response.data)
                    filtered = [(sql, params) for sql, params in postgres_statements
                                if 'usage_logs.created_at >=' in sql]
                    self.assertEqual(len(filtered), 1)
                    pg_sql, params = filtered[0]
                    self.assertIn('usage_logs.created_at < ', pg_sql)
                    for forbidden in ('CAST(', 'SUBSTR(', 'DATE('):
                        self.assertNotIn(forbidden, pg_sql.upper())
                    self.assertIn(today, params.values())
                    self.assertIn(today + timedelta(days=1), params.values())
            response = self.client.get('/whitetap/export-logs?period=all&project_ref=period-filter-test')
            self.assertEqual(response.status_code, 200)
            for label in ('before', 'start', 'end', 'after'):
                self.assertIn(f'boundary-{label}'.encode(), response.data)
            self.assertNotIn(b'boundary-other', response.data)
        finally:
            for tenant_id, log_id in created_ids:
                with app.test_request_context('/'):
                    g.current_tenant = db.session.get(Tenant, tenant_id)
                    UsageLog.query.filter_by(id=log_id).delete()
                    db.session.commit()

    def test_usage_period_bounds(self):
        today = date(2026, 11, 12)
        expected_end = datetime(2026, 11, 13)
        for period, expected_start in (
            ('daily', datetime(2026, 11, 12)), ('weekly', datetime(2026, 11, 9)),
            ('monthly', datetime(2026, 11, 1)), ('quarterly', datetime(2026, 10, 1)),
            ('yearly', datetime(2026, 1, 1))
        ):
            with self.subTest(period=period):
                self.assertEqual(usage_period_bounds(period, today), (expected_start, expected_end))
        self.assertIsNone(usage_period_bounds('all', today))

    def test_added_products_rolling_range_excludes_future_and_other_tenants(self):
        created_ids = []
        now = datetime.now(timezone.utc)
        try:
            for tenant_id, label, created_at in (
                (1, 'within', now - timedelta(days=1)),
                (1, 'old', now - timedelta(days=8)),
                (1, 'future', now + timedelta(days=1)),
                (2, 'other', now - timedelta(days=1)),
            ):
                with app.test_request_context('/'):
                    g.current_tenant = db.session.get(Tenant, tenant_id)
                    product = Product(
                        name=f'Range-{label}', supplier='range-test-supplier',
                        current_stock=0, parent_stock=0, min_stock_level=0, created_at=created_at
                    )
                    db.session.add(product)
                    db.session.flush()
                    created_ids.append((tenant_id, product.id))
                    db.session.commit()
            self.login('whitetap', 'whitetap-password')
            response = self.client.get('/whitetap/admin/added-products?period=7&supplier=range-test-supplier')
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'Range-within', response.data)
            for label in ('old', 'future', 'other'):
                self.assertNotIn(f'Range-{label}'.encode(), response.data)
            response = self.client.get('/whitetap/admin/added-products?period=all&supplier=range-test-supplier')
            self.assertEqual(response.status_code, 200)
            for label in ('within', 'old', 'future'):
                self.assertIn(f'Range-{label}'.encode(), response.data)
            self.assertNotIn(b'Range-other', response.data)
        finally:
            for tenant_id, product_id in created_ids:
                with app.test_request_context('/'):
                    g.current_tenant = db.session.get(Tenant, tenant_id)
                    Product.query.filter_by(id=product_id).delete()
                    db.session.commit()

    def test_project_invoice_lines_aggregate_only_current_tenant(self):
        created_ids = []
        try:
            for tenant_id in (1, 2):
                with app.test_request_context('/'):
                    g.current_tenant = db.session.get(Tenant, tenant_id)
                    log = UsageLog(
                        product_id=self.product_ids[tenant_id - 1], quantity_used=-2,
                        technician_name='Technician', project_ref='invoice-aggregate-test'
                    )
                    db.session.add(log)
                    db.session.flush()
                    created_ids.append((tenant_id, log.id))
                    db.session.commit()
                    lines = get_project_invoice_lines('invoice-aggregate-test')
                    self.assertEqual(len(lines), 1)
                    self.assertEqual(lines[0]['product_id'], self.product_ids[tenant_id - 1])
                    self.assertEqual(lines[0]['quantity'], 2)
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
