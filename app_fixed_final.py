import os
import re
import secrets
import smtplib
import unicodedata
import html as htmllib
from email.message import EmailMessage
import psycopg2
from dotenv import load_dotenv
from uuid import uuid4, UUID as PythonUUID
import csv
from io import StringIO
from flask import Flask, render_template, request, redirect, url_for, flash, session, Response, make_response, jsonify, g, abort, has_request_context
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError
from sqlalchemy import desc, text, event, inspect, UniqueConstraint, func
from sqlalchemy.engine import make_url
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Session, with_loader_criteria
from werkzeug.security import check_password_hash, generate_password_hash
import click
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

def get_database_url(drivername):
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        return None
    url = make_url(database_url)
    if url.drivername in ('postgres', 'postgresql', 'postgresql+psycopg', 'postgresql+psycopg2'):
        return url.set(drivername=drivername)
    return url

def get_conn():
    url = get_database_url('postgresql')
    return psycopg2.connect(url.render_as_string(hide_password=False))

load_dotenv()

app = Flask(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = get_database_url('postgresql+psycopg2')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('SESSION_COOKIE_SECURE', 'true').lower() == 'true'
app.config['PUBLIC_SIGNUP_ENABLED'] = os.environ.get('PUBLIC_SIGNUP_ENABLED', 'true').lower() == 'true'
if app.config['SQLALCHEMY_DATABASE_URI'] and app.config['SQLALCHEMY_DATABASE_URI'].get_backend_name() == 'postgresql':
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'creator': get_conn}

db = SQLAlchemy(app)

class Tenant(db.Model):
    __tablename__ = 'tenants'

    id = db.Column(db.BigInteger().with_variant(db.Integer, 'sqlite'), primary_key=True)
    name = db.Column(db.Text, nullable=False)
    slug = db.Column(db.String(50), nullable=False, unique=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class TenantUser(db.Model):
    __tablename__ = 'tenant_users'

    id = db.Column(db.BigInteger().with_variant(db.Integer, 'sqlite'), primary_key=True)
    tenant_id = db.Column(db.BigInteger, db.ForeignKey('tenants.id'), nullable=False, index=True)
    email = db.Column(db.String(255), nullable=False)
    password_hash = db.Column(db.Text, nullable=False)
    role = db.Column(db.String(50), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class TenantOwned:
    tenant_id = db.Column(db.BigInteger, db.ForeignKey('tenants.id'), nullable=False, index=True)


def generate_product_qr_code():
    return f'WTI-{uuid4().hex.upper()}'

class Product(TenantOwned, db.Model):
    __tablename__ = 'products'

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    sku = db.Column(db.String(50))
    qr_code = db.Column(db.String(64), nullable=False, unique=True, default=generate_product_qr_code)
    name = db.Column(db.String(100))
    supplier = db.Column(db.Text)
    invoice_number = db.Column(db.Text)
    unit_of_measure = db.Column(db.String(20))
    category_id = db.Column(UUID(as_uuid=True), db.ForeignKey('product_categories.id', ondelete='SET NULL'))
    current_stock = db.Column(db.Numeric, nullable=False, default=Decimal('0'))
    parent_stock = db.Column(db.Numeric, nullable=False, default=Decimal('0'))
    min_stock_level = db.Column(db.Numeric, nullable=False, default=Decimal('0'))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f'<Product {self.name} ({self.sku})>'

class ProductCategory(TenantOwned, db.Model):
    __tablename__ = 'product_categories'
    __table_args__ = (UniqueConstraint('tenant_id', 'name', name='product_categories_tenant_name_key'),)

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = db.Column(db.String(100), nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

class UsageLog(TenantOwned, db.Model):
    __tablename__ = 'usage_logs'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(UUID(as_uuid=True), db.ForeignKey('products.id'), nullable=False)
    product_sku = db.Column(db.String(50))
    quantity_used = db.Column(db.Float, nullable=False)
    technician_name = db.Column(db.String(100), nullable=False)
    project_ref = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    product = db.relationship('Product', lazy='joined')

class TintRecipe(TenantOwned, db.Model):
    __tablename__ = 'tint_recipes'

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    recipe_name = db.Column(db.Text, nullable=False)
    project_ref = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

class TintRecipeItem(TenantOwned, db.Model):
    __tablename__ = 'tint_recipe_items'

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    recipe_id = db.Column(db.BigInteger, db.ForeignKey('tint_recipes.id'), nullable=False, index=True)
    product_name = db.Column(db.Text, nullable=False)
    quantity = db.Column(db.Numeric, nullable=False)
    unit = db.Column(db.Text, nullable=True)
    product_id = db.Column(db.BigInteger, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

class Client(TenantOwned, db.Model):
    __tablename__ = 'clients'
    __table_args__ = (UniqueConstraint('tenant_id', 'normalized_name'),)

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    name = db.Column(db.Text, nullable=False)
    normalized_name = db.Column(db.Text, nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

class ProformaInvoice(TenantOwned, db.Model):
    __tablename__ = 'proforma_invoices'
    __table_args__ = (UniqueConstraint('tenant_id', 'invoice_number'),)

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    invoice_number = db.Column(db.String(40), nullable=False, index=True)
    client_id = db.Column(db.BigInteger, db.ForeignKey('clients.id'), nullable=False, index=True)
    project_ref = db.Column(db.Text, nullable=False)
    currency = db.Column(db.String(3), nullable=False)
    tax_mode = db.Column(db.String(10), nullable=False)
    tax_rate = db.Column(db.Numeric(5, 2), nullable=False)
    subtotal = db.Column(db.Numeric(14, 2), nullable=False)
    tax_amount = db.Column(db.Numeric(14, 2), nullable=False)
    total = db.Column(db.Numeric(14, 2), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

class ProformaInvoiceItem(TenantOwned, db.Model):
    __tablename__ = 'proforma_invoice_items'

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    invoice_id = db.Column(db.BigInteger, db.ForeignKey('proforma_invoices.id', ondelete='CASCADE'), nullable=False, index=True)
    product_id = db.Column(UUID(as_uuid=True), nullable=True)
    product_sku = db.Column(db.Text, nullable=True)
    product_name = db.Column(db.Text, nullable=False)
    quantity = db.Column(db.Numeric(14, 3), nullable=False)
    unit = db.Column(db.Text, nullable=True)
    unit_price = db.Column(db.Numeric(14, 2), nullable=False)
    line_total = db.Column(db.Numeric(14, 2), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

class Quotation(TenantOwned, db.Model):
    __tablename__ = 'quotations'
    __table_args__ = (UniqueConstraint('tenant_id', 'quotation_number'),)

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    quotation_number = db.Column(db.String(60), nullable=False, index=True)
    client_id = db.Column(db.BigInteger, db.ForeignKey('clients.id'), nullable=False, index=True)
    currency = db.Column(db.String(3), nullable=False)
    tax_mode = db.Column(db.String(10), nullable=False)
    tax_rate = db.Column(db.Numeric(5, 2), nullable=False)
    subtotal = db.Column(db.Numeric(14, 2), nullable=False)
    tax_amount = db.Column(db.Numeric(14, 2), nullable=False)
    total = db.Column(db.Numeric(14, 2), nullable=False)
    created_by = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

class QuotationItem(TenantOwned, db.Model):
    __tablename__ = 'quotation_items'

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    quotation_id = db.Column(db.BigInteger, db.ForeignKey('quotations.id', ondelete='CASCADE'), nullable=False, index=True)
    product_id = db.Column(UUID(as_uuid=True), nullable=True)
    product_sku = db.Column(db.Text, nullable=True)
    product_name = db.Column(db.Text, nullable=False)
    quantity = db.Column(db.Numeric(14, 3), nullable=False)
    unit = db.Column(db.Text, nullable=True)
    unit_price = db.Column(db.Numeric(14, 2), nullable=False)
    line_total = db.Column(db.Numeric(14, 2), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

class PurchaseOrder(TenantOwned, db.Model):
    __tablename__ = 'purchase_orders'
    __table_args__ = (UniqueConstraint('tenant_id', 'po_number'),)

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    po_number = db.Column(db.String(40), nullable=False, index=True)
    supplier = db.Column(db.Text, nullable=False, index=True)
    currency = db.Column(db.String(3), nullable=False)
    vat_mode = db.Column(db.String(10), nullable=False)
    vat_rate = db.Column(db.Numeric(5, 2), nullable=False)
    subtotal = db.Column(db.Numeric(14, 2), nullable=False)
    vat_amount = db.Column(db.Numeric(14, 2), nullable=False)
    total = db.Column(db.Numeric(14, 2), nullable=False)
    status = db.Column(db.String(30), nullable=False, default='pending')
    supplier_emails = db.Column(db.Text, nullable=True)
    approval_token = db.Column(db.String(64), nullable=True, unique=True, index=True)
    supplier_comment = db.Column(db.Text, nullable=True)
    invoice_number = db.Column(db.String(120), nullable=True)
    waybill_number = db.Column(db.String(120), nullable=True)
    driver_phone = db.Column(db.String(60), nullable=True)
    status_updated_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

class PurchaseOrderItem(TenantOwned, db.Model):
    __tablename__ = 'purchase_order_items'

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    purchase_order_id = db.Column(db.BigInteger, db.ForeignKey('purchase_orders.id', ondelete='CASCADE'), nullable=False, index=True)
    product_id = db.Column(UUID(as_uuid=True), nullable=True)
    product_sku = db.Column(db.Text, nullable=True)
    product_name = db.Column(db.Text, nullable=False)
    quantity = db.Column(db.Numeric(14, 3), nullable=False)
    unit = db.Column(db.Text, nullable=True)
    unit_cost = db.Column(db.Numeric(14, 2), nullable=False)
    line_total = db.Column(db.Numeric(14, 2), nullable=False)
    supplier_included = db.Column(db.Boolean, nullable=True)
    supplier_quantity = db.Column(db.Numeric(14, 3), nullable=True)
    supplier_unit_cost = db.Column(db.Numeric(14, 2), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

class PurchaseOrderEvent(TenantOwned, db.Model):
    __tablename__ = 'purchase_order_events'

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    purchase_order_id = db.Column(db.BigInteger, db.ForeignKey('purchase_orders.id', ondelete='CASCADE'), nullable=False, index=True)
    status = db.Column(db.String(30), nullable=False)
    actor = db.Column(db.String(20), nullable=False, default='staff')
    note = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


def current_tenant_id():
    tenant = getattr(g, 'current_tenant', None) if has_request_context() else None
    identity = inspect(tenant).identity if tenant is not None else None
    return identity[0] if identity else None


@event.listens_for(Session, 'do_orm_execute')
def enforce_tenant_scope(execute_state):
    if execute_state.is_from_statement and has_request_context():
        raise RuntimeError('ORM from_statement queries are not allowed in tenant requests')
    if not execute_state.is_orm_statement:
        if has_request_context():
            raise RuntimeError('Raw SQL is not allowed in tenant requests')
        return
    if execute_state.is_insert or execute_state.is_update:
        raise RuntimeError('Bulk ORM inserts and updates are not allowed; use the unit of work')
    if execute_state.is_select or execute_state.is_update or execute_state.is_delete:
        tenant_id = current_tenant_id()
        execute_state.statement = execute_state.statement.options(
            with_loader_criteria(
                TenantOwned, lambda model: model.tenant_id == tenant_id,
                include_aliases=True
            )
        )


TENANT_REFERENCES = {
    Product: [('category_id', ProductCategory)],
    UsageLog: [('product_id', Product)],
    TintRecipeItem: [('recipe_id', TintRecipe)],
    ProformaInvoice: [('client_id', Client)],
    ProformaInvoiceItem: [('invoice_id', ProformaInvoice), ('product_id', Product)],
    Quotation: [('client_id', Client)],
    QuotationItem: [('quotation_id', Quotation), ('product_id', Product)],
    PurchaseOrderItem: [('purchase_order_id', PurchaseOrder), ('product_id', Product)],
    PurchaseOrderEvent: [('purchase_order_id', PurchaseOrder)],
}


@event.listens_for(Session, 'before_flush')
def enforce_tenant_writes(db_session, flush_context, instances):
    objects = set(db_session.new).union(db_session.dirty, db_session.deleted)
    tenant_id = current_tenant_id()
    for obj in objects:
        if not isinstance(obj, TenantOwned):
            continue
        if tenant_id is None:
            raise RuntimeError('A tenant context is required for business writes')
        if obj in db_session.new and obj.tenant_id is None:
            obj.tenant_id = tenant_id
        if obj.tenant_id != tenant_id or (
            obj not in db_session.new and inspect(obj).attrs.tenant_id.history.has_changes()
        ):
            raise RuntimeError('Cross-tenant business write rejected')
        if obj in db_session.deleted:
            continue
        for field, target in TENANT_REFERENCES.get(type(obj), ()):
            value = getattr(obj, field)
            if value is None or (obj not in db_session.new and not inspect(obj).attrs[field].history.has_changes()):
                continue
            with db_session.no_autoflush:
                exists = db_session.query(target.id).filter(
                    target.id == value, target.tenant_id == tenant_id
                ).first()
            if not exists:
                raise ValueError(f'Invalid tenant reference: {type(obj).__name__}.{field}')


TENANT_ENDPOINTS = set()
ADMIN_ENDPOINTS = {
    'admin_dashboard', 'admin_usage_logs', 'admin_proforma_invoices',
    'proforma_invoice_detail', 'delete_proforma_invoice', 'admin_added_products',
    'admin_add_product', 'admin_transfer_stock', 'edit_product', 'delete_product',
}


def tenant_route(rule, legacy=True, **options):
    def register(view):
        endpoint = options.get('endpoint', view.__name__)
        TENANT_ENDPOINTS.add(endpoint)
        if endpoint == 'supplier_po_response':
            app.add_url_rule('/po/respond/<tenant_slug>/<token>', view_func=view, **options)
        else:
            app.add_url_rule('/<tenant_slug>' + rule, view_func=view, **options)
        if legacy:
            app.add_url_rule(rule, view_func=view, **options)
        return view
    return register


@app.url_value_preprocessor
def capture_tenant_slug(endpoint, values):
    if endpoint in TENANT_ENDPOINTS and values is not None:
        g.tenant_slug = values.pop('tenant_slug', 'whitetap')


@app.url_defaults
def add_tenant_slug(endpoint, values):
    if endpoint in TENANT_ENDPOINTS and 'tenant_slug' not in values and has_request_context():
        tenant = getattr(g, 'current_tenant', None)
        if tenant is not None:
            values['tenant_slug'] = tenant.slug


@app.before_request
def resolve_tenant_and_authenticate():
    if request.endpoint not in TENANT_ENDPOINTS and request.endpoint != 'signup':
        return
    if not app.config['SECRET_KEY']:
        raise RuntimeError('SECRET_KEY must be configured before serving requests')
    if request.endpoint == 'signup':
        if not app.config['PUBLIC_SIGNUP_ENABLED']:
            abort(404)
    else:
        tenant = Tenant.query.filter_by(slug=g.tenant_slug).first()
        if tenant is None:
            abort(404)
        g.current_tenant = tenant
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        supplied = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token', '')
        expected = session.get('csrf_token', '')
        if not expected or not secrets.compare_digest(expected.encode('utf-8'), supplied.encode('utf-8')):
            abort(400, description='Invalid CSRF token')
    if request.endpoint in ('signup', 'login', 'supplier_po_response'):
        return
    user_id = session.get('tenant_user_id')
    user = TenantUser.query.filter_by(id=user_id, tenant_id=tenant.id).first() if user_id else None
    if not user or user.role not in ('admin', 'staff'):
        session.clear()
        if request.endpoint.startswith('api_') or request.endpoint == 'delete_tint_recipe' or request.is_json:
            return jsonify({'error': 'Authentication required'}), 401
        return redirect(url_for('login'))
    g.current_user = user
    session['logged_in'] = user.role == 'admin'
    if request.endpoint in ADMIN_ENDPOINTS and user.role != 'admin':
        abort(403)


@app.template_global()
def csrf_token():
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_urlsafe(32)
    return session['csrf_token']


def lock_user_provisioning():
    if db.engine.dialect.name == 'postgresql':
        db.session.connection().exec_driver_sql(
            'SELECT pg_advisory_xact_lock(%s)', (878705603052,)
        )


@app.cli.command('create-tenant-user')
@click.option('--tenant-slug', required=True)
@click.option('--email', prompt=True)
@click.option('--role', type=click.Choice(['admin', 'staff']), default='admin', show_default=True)
@click.password_option()
def create_tenant_user(tenant_slug, email, role, password):
    """Provision a user for an existing tenant."""
    tenant = Tenant.query.filter_by(slug=tenant_slug).first()
    if tenant is None:
        raise click.ClickException('Tenant not found')
    email = email.strip().lower()
    if not EMAIL_PATTERN.fullmatch(email) or len(email) > 255:
        raise click.ClickException('Invalid email address')
    if len(password) < 12:
        raise click.ClickException('Password must contain at least 12 characters')
    lock_user_provisioning()
    if TenantUser.query.filter(
        TenantUser.tenant_id == tenant.id, db.func.lower(TenantUser.email) == email
    ).first():
        raise click.ClickException('An account with this email already exists for the tenant')
    db.session.add(TenantUser(tenant_id=tenant.id, email=email,
                              password_hash=generate_password_hash(password), role=role))
    db.session.commit()
    click.echo('Tenant user created')


PO_STATUS_LABELS = {
    'pending': 'Draft (not sent)', 'sent': 'Awaiting supplier', 'revision_requested': 'Changes proposed',
    'declined': 'Declined', 'approved': 'Approved', 'awaiting_payment': 'Awaiting payment',
    'on_credit': 'On credit', 'payment_received': 'Payment received', 'to_be_paid': 'To be paid',
    'preparing': 'Preparing order', 'packing': 'Packing', 'out_for_delivery': 'Out for delivery',
    'delivered': 'Delivered'
}
# Supplier-driven fulfilment steps after approval.
PO_NEXT_STEPS = {
    'approved': ['awaiting_payment', 'on_credit'],
    'awaiting_payment': ['payment_received'],
    'on_credit': ['to_be_paid', 'preparing'],
    'payment_received': ['preparing'],
    'to_be_paid': ['preparing'],
    'preparing': ['packing'],
    'packing': ['out_for_delivery'],
    'out_for_delivery': ['delivered']
}
PO_TRACK_ORDER = ['sent', 'approved', 'awaiting_payment', 'payment_received', 'preparing', 'packing', 'out_for_delivery', 'delivered']

@app.template_filter('money')
def money_filter(value):
    return '{:,.2f}'.format(value or 0)

@app.context_processor
def inject_po_labels():
    return {'po_status_labels': PO_STATUS_LABELS}

DEFAULT_PRODUCT_CATEGORIES = (
    'Aviation paints & pigments', 'Carpet & textile', 'Other supplies',
    'Exterior paint', 'Interior paint', 'Matt black', 'Walkway grit',
    'Anti static', 'Clear coat', 'Metallic paint', 'Carpets'
)


def seed_product_categories():
    tenant_id = current_tenant_id()
    if tenant_id is None:
        raise RuntimeError('A tenant context is required to seed product categories')
    if db.engine.dialect.name == 'postgresql':
        db.session.connection().exec_driver_sql(
            'SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))',
            (f'product-categories:{tenant_id}',)
        )
    for category_name in DEFAULT_PRODUCT_CATEGORIES:
        category = ProductCategory.query.filter(
            ProductCategory.tenant_id == tenant_id,
            db.func.lower(ProductCategory.name) == category_name.lower()
        ).first()
        if not category:
            db.session.add(ProductCategory(tenant_id=tenant_id, name=category_name))


def ensure_tint_recipe_tables():
    seed_product_categories()
    db.session.commit()

def get_product_category_name_map():
    return {str(category.id): category.name for category in ProductCategory.query.order_by(ProductCategory.name).all()}

def effective_product_category_name(product, category_names):
    saved_category = category_names.get(str(product.category_id)) if product.category_id else None
    if saved_category:
        return saved_category
    sku = (product.sku or '').upper()
    if 'PNT' in sku:
        return 'Aviation paints & pigments'
    if 'CRP' in sku:
        return 'Carpet & textile'
    return 'Other supplies'

def build_category_groups(products, categories, category_names):
    grouped = {}
    for product in products:
        grouped.setdefault(effective_product_category_name(product, category_names), []).append(product)
    groups = [{'name': category.name, 'products': grouped.pop(category.name, [])} for category in categories]
    for leftover_name in sorted(grouped):
        groups.append({'name': leftover_name, 'products': grouped[leftover_name]})
    return groups

def resolve_product_category():
    selected_id = request.form.get('category_id', '').strip()
    if selected_id == '__custom__':
        category_name = request.form.get('custom_category_name', '').strip()
        if not category_name or len(category_name) > 100:
            return None
        category = ProductCategory.query.filter(db.func.lower(ProductCategory.name) == category_name.lower()).first()
        if not category:
            category = ProductCategory(name=category_name)
            db.session.add(category)
            db.session.flush()
        return category
    if not selected_id:
        return None
    try:
        return ProductCategory.query.get(PythonUUID(selected_id))
    except (ValueError, TypeError):
        return None

def get_product_units():
    rows = db.session.query(Product.unit_of_measure).filter(
        Product.unit_of_measure.isnot(None),
        Product.unit_of_measure != ''
    ).distinct().order_by(Product.unit_of_measure).all()
    return [row[0] for row in rows]

def get_submitted_unit():
    selected_unit = request.form.get('unit_of_measure', '').strip()
    if selected_unit == '__custom__':
        return request.form.get('custom_unit_of_measure', '').strip()
    return selected_unit

USAGE_PERIOD_LABELS = {
    'daily': 'Today',
    'weekly': 'This week',
    'monthly': 'This month',
    'quarterly': 'This quarter',
    'yearly': 'This year',
    'all': 'All time'
}

def get_usage_period_start(period, today=None):
    today = today or datetime.now().date()
    if period == 'daily':
        start_date = today
    elif period == 'weekly':
        start_date = today - timedelta(days=today.weekday())
    elif period == 'monthly':
        start_date = today.replace(day=1)
    elif period == 'quarterly':
        start_date = today.replace(month=((today.month - 1) // 3) * 3 + 1, day=1)
    elif period == 'yearly':
        start_date = today.replace(month=1, day=1)
    else:
        return None
    return datetime.combine(start_date, datetime.min.time())

def normalize_client_name(name):
    return ' '.join(name.casefold().split())

def normalize_product_uuid(value):
    if value is None or value == '':
        return None
    return PythonUUID(str(value))

EMAIL_PATTERN = re.compile(r'^[^@\s<>,;]+@[^@\s<>,;]+\.[^@\s<>,;]+$')

def parse_supplier_emails(values):
    if isinstance(values, str):
        values = [values]
    emails = []
    for value in values or []:
        for part in re.split(r'[,;\s]+', str(value or '')):
            part = part.strip().lower()
            if not part:
                continue
            if len(part) > 254 or not EMAIL_PATTERN.match(part):
                raise ValueError(f'"{part}" is not a valid email address.')
            if part not in emails:
                emails.append(part)
    if len(emails) > 4:
        raise ValueError('Add no more than 4 supplier email addresses.')
    return emails

def po_email_list(order):
    return [e for e in (order.supplier_emails or '').split(',') if e]

def po_public_link(order):
    base = os.environ.get('PUBLIC_BASE_URL', '').rstrip('/')
    path = url_for('supplier_po_response', token=order.approval_token)
    if base:
        return base + path
    root = request.url_root.rstrip('/')
    if root.startswith('http://') and 'localhost' not in root and '127.0.0.1' not in root:
        root = 'https://' + root[len('http://'):]
    return root + path

def po_log_event(order, status, actor, note=None):
    order.status = status
    order.status_updated_at = datetime.now(timezone.utc)
    db.session.add(PurchaseOrderEvent(purchase_order_id=order.id, status=status, actor=actor, note=(note or None)))

def po_sync_status(order):
    # Event history is the source of truth; repair a stale status without touching other data.
    latest = PurchaseOrderEvent.query.filter_by(purchase_order_id=order.id).order_by(
        PurchaseOrderEvent.created_at.desc(), PurchaseOrderEvent.id.desc()).first()
    if latest and latest.status != order.status:
        order.status = latest.status
        order.status_updated_at = latest.created_at
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            app.logger.exception('Unable to sync purchase order status')

def po_recalculate(order, items):
    subtotal = sum((i.line_total for i in items), Decimal('0.00'))
    order.subtotal = subtotal
    order.vat_amount = (subtotal * Decimal(order.vat_rate) / Decimal('100')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    order.total = order.subtotal + order.vat_amount

def send_po_email(order, items, link, recipients):
    host = os.environ.get('SMTP_HOST')
    sender = os.environ.get('SMTP_FROM') or os.environ.get('SMTP_USER')
    if not host or not sender:
        return False, 'Email is not configured (set SMTP_HOST, SMTP_USER, SMTP_PASSWORD, SMTP_FROM).'
    rows = ''.join(
        f'<tr><td>{htmllib.escape(i.product_name)}</td><td align="right">{i.quantity:.3f} {htmllib.escape(i.unit or "")}</td>'
        f'<td align="right">{order.currency} {i.unit_cost:.2f}</td></tr>' for i in items)
    body = (
        f'<p>A purchase order <strong>{htmllib.escape(order.po_number)}</strong> is awaiting your response.</p>'
        f'<table cellpadding="6" border="1" style="border-collapse:collapse"><tr><th>Item</th><th>Qty</th><th>Unit cost</th></tr>{rows}</table>'
        f'<p>Total: <strong>{order.currency} {order.total:,.2f}</strong></p>'
        f'<p><a href="{htmllib.escape(link)}">Review, approve or decline this purchase order</a></p>'
        f'<p>If the link does not open, copy it: {htmllib.escape(link)}</p>')
    message = EmailMessage()
    message['Subject'] = f'Purchase order {order.po_number} - approval requested'
    message['From'] = sender
    message['To'] = ', '.join(recipients)
    message.set_content(f'Purchase order {order.po_number} total {order.currency} {order.total:,.2f}. Respond here: {link}')
    message.add_alternative(body, subtype='html')
    try:
        port = int(os.environ.get('SMTP_PORT', '587'))
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=20)
        else:
            server = smtplib.SMTP(host, port, timeout=20)
            server.starttls()
        with server:
            if os.environ.get('SMTP_USER'):
                server.login(os.environ['SMTP_USER'], os.environ.get('SMTP_PASSWORD', ''))
            server.send_message(message)
        return True, None
    except Exception as exc:
        app.logger.exception('Unable to send purchase order email')
        return False, f'{type(exc).__name__}: {str(exc)[:150]}'

def get_project_invoice_lines(project_ref):
    rows = db.session.query(
        Product.id,
        Product.sku,
        Product.name,
        Product.unit_of_measure,
        db.func.sum(db.func.abs(UsageLog.quantity_used)).label('quantity')
    ).join(Product, Product.id == UsageLog.product_id).filter(
        db.func.lower(UsageLog.project_ref) == project_ref.casefold(),
        UsageLog.quantity_used < 0,
        UsageLog.technician_name != 'TRANSFER_TO_STAFF'
    ).group_by(
        Product.id, Product.sku, Product.name, Product.unit_of_measure
    ).order_by(Product.name).all()
    return [{
        'product_id': row.id,
        'sku': row.sku or '-',
        'name': row.name or 'Unnamed product',
        'unit': row.unit_of_measure or '',
        'quantity': Decimal(str(row.quantity or 0)).quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)
    } for row in rows]

def organization_slug(name):
    normalized = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii')
    return re.sub(r'[^a-z0-9]+', '-', normalized.lower()).strip('-')[:50].rstrip('-')


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'GET':
        return render_template('signup.html')

    name = ' '.join(request.form.get('organization_name', '').split())
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '')
    slug_base = organization_slug(name)
    if not name or len(name) > 100 or not slug_base:
        flash('Enter an organization name of at most 100 characters containing a letter or number.', 'error')
    elif len(email) > 255 or not EMAIL_PATTERN.fullmatch(email):
        flash('Enter a valid email address.', 'error')
    elif len(password) < 12 or len(password) > 1024:
        flash('Password must contain between 12 and 1024 characters.', 'error')
    else:
        try:
            lock_user_provisioning()
            if TenantUser.query.filter(func.lower(TenantUser.email) == email).first():
                flash('This email address is already in use.', 'error')
                return render_template('signup.html', organization_name=name, email=email), 400
            slug = slug_base
            suffix = 1
            while Tenant.query.filter_by(slug=slug).first():
                suffix += 1
                suffix_text = f'-{suffix}'
                slug = slug_base[:50 - len(suffix_text)].rstrip('-') + suffix_text
            tenant = Tenant(name=name, slug=slug)
            db.session.add(tenant)
            db.session.flush()
            g.current_tenant = tenant
            seed_product_categories()
            db.session.add(TenantUser(
                tenant_id=tenant.id, email=email,
                password_hash=generate_password_hash(password), role='admin'
            ))
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            app.logger.exception('Organization signup conflicted with an existing record')
            flash('Unable to create the organization due to an account conflict. Please try again.', 'error')
            return render_template('signup.html', organization_name=name, email=email), 409
        session.clear()
        flash('Organization created. Sign in with your new administrator account.', 'success')
        return redirect(url_for('login', tenant_slug=slug))
    return render_template('signup.html', organization_name=name, email=email), 400


@app.route('/')
def landing():
    return render_template('index.html')


@app.route('/organization-login')
def organization_login():
    slug = request.args.get('slug', '').strip().lower()
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,48}[a-z0-9])?', slug):
        flash('Enter a valid organization URL slug.', 'error')
        return redirect(url_for('landing'))
    return redirect(url_for('login', tenant_slug=slug))


@tenant_route('/', legacy=False)
def index():
    return render_template('index.html')

@tenant_route('/staff-inventory')
def staff_inventory():
    ensure_tint_recipe_tables()
    category_names = get_product_category_name_map()
    search_query = request.args.get('search', '')
    activity_filter = request.args.get('activity_filter', '')
    
    all_products = Product.query.all()

    # Group products by the categories managed in the admin workspace
    product_categories = ProductCategory.query.order_by(ProductCategory.name).all()
    category_groups = build_category_groups(all_products, product_categories, category_names)

    # Apply search filter
    if search_query:
        def matches_search(p):
            return search_query.lower() in (p.name or '').lower() or search_query.lower() in (p.sku or '').lower()
        for group in category_groups:
            group['products'] = [p for p in group['products'] if matches_search(p)]

    all_items = [p for group in category_groups for p in group['products']]
    
    # Recent activity
    logs_query = UsageLog.query.order_by(desc(UsageLog.created_at))
    if activity_filter:
        logs_query = logs_query.filter(UsageLog.project_ref.ilike(f'%{activity_filter}%'))
    recent_logs = logs_query.limit(10).all()
    
    low_stock_products = [p for p in all_products if (p.current_stock or 0) < (p.min_stock_level or 0)]
    low_stock_count = len(low_stock_products)
    tint_projects = [row[0] for row in db.session.query(TintRecipe.project_ref).filter(TintRecipe.project_ref.isnot(None)).order_by(TintRecipe.project_ref).all()]

    return render_template('staff_dashboard.html', category_groups=category_groups, total_items=len(all_products), recent_logs=recent_logs, search_query=search_query, activity_filter=activity_filter, low_stock_products=low_stock_products, low_stock_count=low_stock_count, tint_projects=tint_projects, category_name_by_id=category_names)

@tenant_route('/api/products/lookup')
def api_product_lookup():
    identifier = request.args.get('identifier', '').strip()
    if not identifier:
        return jsonify({'success': False, 'error': 'Provide a QR code or SKU.'}), 400

    product = Product.query.filter(db.or_(
        db.func.lower(Product.qr_code) == identifier.casefold(),
        db.func.lower(Product.sku) == identifier.casefold()
    )).first()
    if not product:
        return jsonify({'success': False, 'error': 'No product matches this QR code or SKU.'}), 404

    return jsonify({
        'success': True,
        'product': {
            'id': str(product.id),
            'qr_code': product.qr_code,
            'sku': product.sku or '',
            'name': product.name or '',
            'parent_stock': float(product.parent_stock or 0),
            'staff_stock': float(product.current_stock or 0),
            'combined_stock': float(product.parent_stock or 0) + float(product.current_stock or 0),
            'unit_of_measure': product.unit_of_measure or ''
        }
    })

@tenant_route('/api/tint-recipes')
def api_tint_recipes():
    recipe_name = (request.args.get('recipe_name') or request.args.get('name') or '').strip()
    project_ref = request.args.get('project_ref', '').strip()
    if not recipe_name and not project_ref:
        return jsonify({'success': False, 'error': 'Provide a recipe_name, name, or project_ref.'}), 400

    try:
        ensure_tint_recipe_tables()
        filters = []
        if recipe_name:
            filters.append(db.func.lower(TintRecipe.recipe_name) == recipe_name.lower())
        if project_ref:
            filters.append(db.func.lower(TintRecipe.project_ref) == project_ref.lower())
        recipe = TintRecipe.query.filter(db.or_(*filters)).order_by(TintRecipe.updated_at.desc()).first()
        if not recipe:
            return jsonify({'success': False, 'error': 'Recipe not found.'}), 404

        items = TintRecipeItem.query.filter_by(recipe_id=recipe.id).order_by(TintRecipeItem.product_name).all()
        matched_products = Product.query.filter(Product.name.in_([item.product_name for item in items])).all() if items else []
        products_by_name = {product.name: product for product in matched_products}
        return jsonify({
            'success': True,
            'recipe': {
                'id': recipe.id,
                'recipe_name': recipe.recipe_name,
                'project_ref': recipe.project_ref,
                'created_at': recipe.created_at.isoformat() if recipe.created_at else None,
                'updated_at': recipe.updated_at.isoformat() if recipe.updated_at else None
            },
            'items': [{
                'product_id': str(products_by_name[item.product_name].id) if item.product_name in products_by_name else '',
                'stored_product_id': item.product_id,
                'sku': products_by_name[item.product_name].sku if item.product_name in products_by_name else '-',
                'name': item.product_name,
                'unit': item.unit or '',
                'quantity': format(item.quantity, 'f'),
                'available_stock': float(products_by_name[item.product_name].current_stock or 0) if item.product_name in products_by_name else 0
            } for item in items]
        })
    except Exception:
        db.session.rollback()
        app.logger.exception('Unable to load tint recipe')
        return jsonify({'success': False, 'error': 'Unable to load recipe right now.'}), 500

@tenant_route('/api/tint-recipes/<int:recipe_id>', methods=['DELETE'])
def delete_tint_recipe(recipe_id):
    try:
        ensure_tint_recipe_tables()
        recipe = TintRecipe.query.get(recipe_id)
        if not recipe:
            return jsonify({'success': False, 'error': 'Recipe not found.'}), 404

        TintRecipeItem.query.filter_by(recipe_id=recipe.id).delete(synchronize_session=False)
        db.session.delete(recipe)
        db.session.commit()
        return jsonify({'success': True, 'deleted_recipe_id': recipe_id})
    except Exception:
        db.session.rollback()
        app.logger.exception('Unable to delete tint recipe')
        return jsonify({'success': False, 'error': 'Unable to delete recipe right now.'}), 500

@tenant_route('/export-logs')
def export_logs():
    period = request.args.get('period', 'all')
    project_ref = request.args.get('project_ref', '').strip()
    if period not in USAGE_PERIOD_LABELS:
        period = 'all'
    start = get_usage_period_start(period)
    logs_query = db.session.query(UsageLog, Product.name).outerjoin(Product, Product.id == UsageLog.product_id)
    if start:
        logs_query = logs_query.filter(UsageLog.created_at >= start)
    if project_ref:
        logs_query = logs_query.filter(UsageLog.project_ref.ilike(f'%{project_ref}%'))
    logs = logs_query.order_by(desc(UsageLog.created_at)).all()
    
    output = StringIO()
    writer = csv.writer(output)
    
    writer.writerow(['Date', 'Product Name', 'Quantity', 'Technician', 'Project Reference'])
    
    for log, product_name in logs:
        writer.writerow([
            log.created_at.strftime('%Y-%m-%d %H:%M:%S') if log.created_at else '',
            product_name or 'Deleted',
            log.quantity_used,
            log.technician_name,
            log.project_ref or ''
        ])
    
    output.seek(0)
    
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=usage_report_{period}.csv'}
    )

@tenant_route('/admin/usage-logs')
def admin_usage_logs():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    period = request.args.get('period', 'daily')
    project_ref = request.args.get('project_ref', '').strip()
    if period not in USAGE_PERIOD_LABELS:
        period = 'daily'
    start = get_usage_period_start(period)
    logs_query = db.session.query(UsageLog, Product.name).outerjoin(Product, Product.id == UsageLog.product_id)
    if start:
        logs_query = logs_query.filter(UsageLog.created_at >= start)
    if project_ref:
        logs_query = logs_query.filter(UsageLog.project_ref.ilike(f'%{project_ref}%'))
    rows = logs_query.order_by(desc(UsageLog.created_at)).all()
    logs = [{
        'created_at': log.created_at,
        'product_name': product_name or 'Deleted product',
        'product_sku': log.product_sku or (log.product.sku if log.product else '-') or '-',
        'quantity_used': log.quantity_used,
        'technician_name': log.technician_name,
        'project_ref': log.project_ref or '-'
    } for log, product_name in rows]

    return render_template(
        'usage_logs.html',
        logs=logs,
        period=period,
        project_ref=project_ref,
        period_label=USAGE_PERIOD_LABELS[period],
        period_options=USAGE_PERIOD_LABELS
    )

@tenant_route('/admin/proforma-invoices', methods=['GET', 'POST'])
def admin_proforma_invoices():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    ensure_tint_recipe_tables()
    if request.method == 'POST':
        client_name = ' '.join(request.form.get('client_name', '').split())
        project_ref = request.form.get('project_ref', '').strip()
        currency = request.form.get('currency', '').upper()
        tax_mode = request.form.get('tax_mode', '')

        if not client_name or len(client_name) > 200:
            flash('Enter a client name of no more than 200 characters.', 'error')
            return redirect(url_for('admin_proforma_invoices', project_ref=project_ref, currency=currency, tax_mode=tax_mode))
        if currency not in ('USD', 'KES'):
            flash('Choose USD or KES.', 'error')
            return redirect(url_for('admin_proforma_invoices', project_ref=project_ref, client_name=client_name, tax_mode=tax_mode))
        if tax_mode not in ('standard', 'exempt'):
            flash('Choose 16% tax or tax exempt.', 'error')
            return redirect(url_for('admin_proforma_invoices', project_ref=project_ref, client_name=client_name, currency=currency))

        project_lines = get_project_invoice_lines(project_ref) if project_ref else []
        if not project_lines:
            flash('Choose a project with recorded issued products.', 'error')
            return redirect(url_for('admin_proforma_invoices', client_name=client_name, currency=currency, tax_mode=tax_mode))

        submitted_ids = set(request.form.getlist('product_id'))
        line_items = []
        for line in project_lines:
            product_id = str(line['product_id'])
            if product_id not in submitted_ids:
                flash('Invoice line items did not match the selected project.', 'error')
                return redirect(url_for('admin_proforma_invoices', project_ref=project_ref, client_name=client_name, currency=currency, tax_mode=tax_mode))
            try:
                unit_price = Decimal(request.form.get(f'unit_price_{product_id}', '').strip())
            except Exception:
                flash('Enter a valid price for every invoice line.', 'error')
                return redirect(url_for('admin_proforma_invoices', project_ref=project_ref, client_name=client_name, currency=currency, tax_mode=tax_mode))
            if not unit_price.is_finite() or unit_price < 0:
                flash('Prices must be zero or greater.', 'error')
                return redirect(url_for('admin_proforma_invoices', project_ref=project_ref, client_name=client_name, currency=currency, tax_mode=tax_mode))
            unit_price = unit_price.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            line_total = (line['quantity'] * unit_price).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            line_items.append((line, unit_price, line_total))

        try:
            client_key = normalize_client_name(client_name)
            client = Client.query.filter_by(normalized_name=client_key).first()
            if not client:
                client = Client(name=client_name, normalized_name=client_key)
                db.session.add(client)
                db.session.flush()

            subtotal = sum((line_total for _, _, line_total in line_items), Decimal('0.00'))
            tax_rate = Decimal('16.00') if tax_mode == 'standard' else Decimal('0.00')
            tax_amount = (subtotal * tax_rate / Decimal('100')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            invoice = ProformaInvoice(
                invoice_number=f"PF-{datetime.now().strftime('%Y%m%d')}-{uuid4().hex[:6].upper()}",
                client_id=client.id,
                project_ref=project_ref,
                currency=currency,
                tax_mode=tax_mode,
                tax_rate=tax_rate,
                subtotal=subtotal,
                tax_amount=tax_amount,
                total=subtotal + tax_amount
            )
            db.session.add(invoice)
            db.session.flush()
            for line, unit_price, line_total in line_items:
                db.session.add(ProformaInvoiceItem(
                    invoice_id=invoice.id,
                    product_id=line['product_id'],
                    product_sku=line['sku'],
                    product_name=line['name'],
                    quantity=line['quantity'],
                    unit=line['unit'],
                    unit_price=unit_price,
                    line_total=line_total
                ))
            db.session.commit()
            flash(f'Proforma {invoice.invoice_number} saved for {client.name}.', 'success')
            return redirect(url_for('proforma_invoice_detail', invoice_id=invoice.id))
        except Exception:
            db.session.rollback()
            app.logger.exception('Unable to create proforma invoice')
            flash('Unable to save the proforma invoice. Please try again.', 'error')
            return redirect(url_for('admin_proforma_invoices', project_ref=project_ref, client_name=client_name, currency=currency, tax_mode=tax_mode))

    project_refs = [row[0] for row in db.session.query(UsageLog.project_ref).filter(
        UsageLog.project_ref.isnot(None),
        UsageLog.project_ref != '',
        UsageLog.quantity_used < 0,
        UsageLog.technician_name != 'TRANSFER_TO_STAFF'
    ).distinct().order_by(UsageLog.project_ref).all()]
    project_ref = request.args.get('project_ref', '').strip()
    client_name = request.args.get('client_name', '').strip()
    currency = request.args.get('currency', 'KES').upper()
    if currency not in ('KES', 'USD'):
        currency = 'KES'
    tax_mode = request.args.get('tax_mode', 'standard')
    if tax_mode not in ('standard', 'exempt'):
        tax_mode = 'standard'
    invoices = db.session.query(ProformaInvoice, Client.name).join(
        Client, Client.id == ProformaInvoice.client_id
    ).order_by(ProformaInvoice.created_at.desc()).limit(100).all()
    lines = get_project_invoice_lines(project_ref) if project_ref else []
    return render_template(
        'proforma_invoices.html',
        project_refs=project_refs,
        selected_project_ref=project_ref,
        client_name=client_name,
        currency=currency,
        tax_mode=tax_mode,
        project_lines=lines,
        clients=Client.query.order_by(Client.name).all(),
        invoices=invoices
    )

@tenant_route('/admin/proforma-invoices/<int:invoice_id>')
def proforma_invoice_detail(invoice_id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    ensure_tint_recipe_tables()
    invoice = ProformaInvoice.query.get_or_404(invoice_id)
    client = Client.query.get_or_404(invoice.client_id)
    items = ProformaInvoiceItem.query.filter_by(invoice_id=invoice.id).order_by(ProformaInvoiceItem.product_name).all()
    return render_template('proforma_invoice_detail.html', invoice=invoice, client=client, items=items)

@tenant_route('/staff/quotations', methods=['GET', 'POST'])
def staff_quotations():
    ensure_tint_recipe_tables()
    if request.method == 'POST':
        quotation_number = ' '.join(request.form.get('quotation_number', '').split())
        client_name = ' '.join(request.form.get('client_name', '').split())
        currency = request.form.get('currency', '').upper()
        tax_mode = request.form.get('tax_mode', '')
        created_by = request.form.get('created_by', '').strip()

        if not quotation_number or len(quotation_number) > 60:
            flash('Enter a quotation number of no more than 60 characters.', 'error')
            return redirect(url_for('staff_quotations'))
        if not client_name or len(client_name) > 200:
            flash('Enter a client name of no more than 200 characters.', 'error')
            return redirect(url_for('staff_quotations'))
        if currency not in ('USD', 'KES'):
            flash('Choose USD or KES.', 'error')
            return redirect(url_for('staff_quotations'))
        if tax_mode not in ('standard', 'exempt'):
            flash('Choose 16% VAT or VAT exempt.', 'error')
            return redirect(url_for('staff_quotations'))
        if Quotation.query.filter(db.func.lower(Quotation.quotation_number) == quotation_number.lower()).first():
            flash(f'Quotation {quotation_number} already exists. Open it from the list below.', 'error')
            return redirect(url_for('staff_quotations'))

        descriptions = request.form.getlist('item_description')
        quantities = request.form.getlist('item_quantity')
        units = request.form.getlist('item_unit')
        prices = request.form.getlist('item_price')
        product_ids = request.form.getlist('item_product_id')
        product_skus = request.form.getlist('item_sku')
        part_numbers = request.form.getlist('item_part')

        def clean_number(value):
            return (value or '').replace(',', '').strip()

        line_items = []
        for index, description in enumerate(descriptions):
            description = ' '.join((description or '').split())
            if not description:
                continue
            if len(description) > 200:
                flash('Keep every item description under 200 characters.', 'error')
                return redirect(url_for('staff_quotations'))
            try:
                quantity = Decimal(clean_number(quantities[index] if index < len(quantities) else ''))
                unit_price = Decimal(clean_number(prices[index] if index < len(prices) else ''))
            except Exception:
                flash('Enter a valid quantity and price for every quotation line.', 'error')
                return redirect(url_for('staff_quotations'))
            if not quantity.is_finite() or quantity <= 0:
                flash('Quantities must be greater than zero.', 'error')
                return redirect(url_for('staff_quotations'))
            if not unit_price.is_finite() or unit_price < 0:
                flash('Prices must be zero or greater.', 'error')
                return redirect(url_for('staff_quotations'))
            quantity = quantity.quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)
            unit_price = unit_price.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            line_total = (quantity * unit_price).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            unit = (units[index] if index < len(units) else '').strip()[:20]
            try:
                product_id = normalize_product_uuid(product_ids[index]) if index < len(product_ids) else None
            except (ValueError, TypeError):
                flash('One or more selected products have an invalid UUID.', 'error')
                return redirect(url_for('staff_quotations'))
            part_number = (part_numbers[index] if index < len(part_numbers) else '').strip()[:50]
            product_sku = (product_skus[index] if index < len(product_skus) else '').strip()[:50] or part_number
            line_items.append({
                'description': description, 'quantity': quantity, 'unit': unit,
                'unit_price': unit_price, 'line_total': line_total,
                'product_id': product_id, 'product_sku': product_sku
            })

        if not line_items:
            flash('Add at least one quotation line item.', 'error')
            return redirect(url_for('staff_quotations'))

        try:
            client_key = normalize_client_name(client_name)
            client = Client.query.filter_by(normalized_name=client_key).first()
            if not client:
                client = Client(name=client_name, normalized_name=client_key)
                db.session.add(client)
                db.session.flush()

            subtotal = sum((item['line_total'] for item in line_items), Decimal('0.00'))
            tax_rate = Decimal('16.00') if tax_mode == 'standard' else Decimal('0.00')
            tax_amount = (subtotal * tax_rate / Decimal('100')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            quotation = Quotation(
                quotation_number=quotation_number,
                client_id=client.id,
                currency=currency,
                tax_mode=tax_mode,
                tax_rate=tax_rate,
                subtotal=subtotal,
                tax_amount=tax_amount,
                total=subtotal + tax_amount,
                created_by=created_by[:100] if created_by else None
            )
            db.session.add(quotation)
            db.session.flush()
            for item in line_items:
                db.session.add(QuotationItem(
                    quotation_id=quotation.id,
                    product_id=item['product_id'],
                    product_sku=item['product_sku'] or None,
                    product_name=item['description'],
                    quantity=item['quantity'],
                    unit=item['unit'] or None,
                    unit_price=item['unit_price'],
                    line_total=item['line_total']
                ))
            db.session.commit()
            flash(f'Quotation {quotation.quotation_number} saved for {client.name}.', 'success')
            return redirect(url_for('staff_quotation_detail', quotation_id=quotation.id))
        except Exception:
            db.session.rollback()
            app.logger.exception('Unable to create quotation')
            flash('Unable to save the quotation. Please try again.', 'error')
            return redirect(url_for('staff_quotations'))

    quotations = db.session.query(Quotation, Client.name).join(
        Client, Client.id == Quotation.client_id
    ).order_by(Quotation.created_at.desc()).limit(100).all()
    products = Product.query.order_by(Product.name).all()
    return render_template(
        'staff_quotations.html',
        quotations=quotations,
        clients=Client.query.order_by(Client.name).all(),
        products=[{
            'id': str(p.id), 'sku': p.sku or '', 'name': p.name or 'Unnamed product',
            'unit': p.unit_of_measure or ''
        } for p in products]
    )

@tenant_route('/staff/quotations/<int:quotation_id>')
def staff_quotation_detail(quotation_id):
    ensure_tint_recipe_tables()
    quotation = Quotation.query.get_or_404(quotation_id)
    client = Client.query.get_or_404(quotation.client_id)
    items = QuotationItem.query.filter_by(quotation_id=quotation.id).order_by(QuotationItem.id).all()
    return render_template('staff_quotation_detail.html', quotation=quotation, client=client, items=items)

@tenant_route('/staff/quotations/<int:quotation_id>/delete', methods=['POST'])
def delete_quotation(quotation_id):
    ensure_tint_recipe_tables()
    quotation = Quotation.query.get_or_404(quotation_id)
    try:
        QuotationItem.query.filter_by(quotation_id=quotation.id).delete()
        db.session.delete(quotation)
        db.session.commit()
        flash(f'Quotation {quotation.quotation_number} deleted.', 'success')
    except Exception:
        db.session.rollback()
        app.logger.exception('Unable to delete quotation')
        flash('Unable to delete the quotation. Please try again.', 'error')
    return redirect(url_for('staff_quotations'))

@tenant_route('/staff/purchase-orders/<int:order_id>/delete', methods=['POST'])
def delete_purchase_order(order_id):
    ensure_tint_recipe_tables()
    order = PurchaseOrder.query.get_or_404(order_id)
    try:
        PurchaseOrderItem.query.filter_by(purchase_order_id=order.id).delete()
        PurchaseOrderEvent.query.filter_by(purchase_order_id=order.id).delete()
        db.session.delete(order)
        db.session.commit()
        flash(f'Purchase order {order.po_number} deleted.', 'success')
    except Exception:
        db.session.rollback()
        app.logger.exception('Unable to delete purchase order')
        flash('Unable to delete the purchase order. Please try again.', 'error')
    return redirect(url_for('staff_purchase_orders'))

@tenant_route('/admin/proforma-invoices/<int:invoice_id>/delete', methods=['POST'])
def delete_proforma_invoice(invoice_id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    ensure_tint_recipe_tables()
    invoice = ProformaInvoice.query.get_or_404(invoice_id)
    try:
        ProformaInvoiceItem.query.filter_by(invoice_id=invoice.id).delete()
        db.session.delete(invoice)
        db.session.commit()
        flash(f'Proforma {invoice.invoice_number} deleted.', 'success')
    except Exception:
        db.session.rollback()
        app.logger.exception('Unable to delete proforma invoice')
        flash('Unable to delete the proforma invoice. Please try again.', 'error')
    return redirect(url_for('admin_proforma_invoices'))

@tenant_route('/export-products')
def export_products():
    products = Product.query.order_by(Product.name).all()
    
    output = StringIO()
    writer = csv.writer(output)
    
    writer.writerow(['SKU', 'Name', 'Unit', 'Current Stock', 'Min Level'])
    
    for product in products:
        writer.writerow([
            product.sku or '',
            product.name or '',
            product.unit_of_measure or '',
            float(product.current_stock or 0),
            float(product.min_stock_level or 0)
        ])
    
    output.seek(0)
    
    response = make_response(output.getvalue())
    response.headers['Content-Disposition'] = 'attachment; filename=current_inventory.csv'
    response.headers['Content-type'] = 'text/csv'
    
    return response

@tenant_route('/export-paints')
def export_paints():
    products = Product.query.filter(Product.sku.ilike('%PNT%')).order_by(Product.name.asc()).all()
    
    output = StringIO()
    writer = csv.writer(output)
    
    writer.writerow(['SKU', 'Name', 'Unit', 'Current Stock', 'Min Level'])
    
    for product in products:
        writer.writerow([
            product.sku or '',
            product.name or '',
            product.unit_of_measure or '',
            float(product.current_stock or 0),
            float(product.min_stock_level or 0)
        ])
    
    output.seek(0)
    
    response = make_response(output.getvalue())
    response.headers['Content-Disposition'] = 'attachment; filename=paints_inventory.csv'
    response.headers['Content-type'] = 'text/csv'
    
    return response

@tenant_route('/export-carpets')
def export_carpets():
    products = Product.query.filter(Product.sku.ilike('%CRP%')).order_by(Product.name).all()
    
    output = StringIO()
    writer = csv.writer(output)
    
    writer.writerow(['SKU', 'Name', 'Unit', 'Current Stock', 'Min Level'])
    
    for product in products:
        writer.writerow([
            product.sku or '',
            product.name or '',
            product.unit_of_measure or '',
            float(product.current_stock or 0),
            float(product.min_stock_level or 0)
        ])
    
    output.seek(0)
    
    response = make_response(output.getvalue())
    response.headers['Content-Disposition'] = 'attachment; filename=carpets_inventory.csv'
    response.headers['Content-type'] = 'text/csv'
    
    return response

@tenant_route('/export-inventory')
def export_inventory():
    products = Product.query.order_by(Product.name).all()
    
    output = StringIO()
    writer = csv.writer(output)
    
    writer.writerow(['SKU', 'Name', 'Price', 'Quantity', 'Min Level'])
    
    for product in products:
        writer.writerow([
            product.sku or '',
            product.name or '',
            'N/A',  # Price field (not in model)
            float(product.current_stock or 0),
            float(product.min_stock_level or 0)
        ])
    
    output.seek(0)
    
    response = make_response(output.getvalue())
    response.headers['Content-Disposition'] = 'attachment; filename=inventory_report.csv'
    response.headers['Content-type'] = 'text/csv'
    
    return response

@tenant_route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = TenantUser.query.filter(
            TenantUser.tenant_id == g.current_tenant.id,
            db.func.lower(TenantUser.email) == email
        ).one_or_none()
        if user and user.role in ('admin', 'staff') and check_password_hash(user.password_hash, password):
            session.clear()
            session['tenant_user_id'] = user.id
            session['logged_in'] = user.role == 'admin'
            return redirect(url_for('admin_dashboard' if user.role == 'admin' else 'staff_inventory'))
        flash('Incorrect email or password', 'error')
    return render_template('login.html')

@tenant_route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully', 'success')
    return redirect(url_for('login'))

@tenant_route('/admin-dashboard')
def admin_dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    ensure_tint_recipe_tables()
    view = request.args.get('view', 'summary')
    
    all_products = Product.query.order_by(Product.name).all()
    
    if view == 'inventory':
        display_products = Product.query.filter(Product.current_stock <= Product.min_stock_level).limit(6).all()
    else:
        display_products = all_products
        
    # Calculate summary stats (always use full dataset)
    total_items = len(all_products)
    low_stock_count = len([p for p in all_products if (p.current_stock or 0) < (p.min_stock_level or 0)])
    total_inventory_value = sum((p.current_stock or 0) for p in all_products)
    
    # Today's usage logs count
    today_logs = db.session.query(func.count(UsageLog.id)).filter(
        func.date(UsageLog.created_at) == datetime.now().date(),
        UsageLog.tenant_id == g.current_tenant.id
    ).scalar()

    product_categories = ProductCategory.query.order_by(ProductCategory.name).all()
    category_names = get_product_category_name_map()
    category_groups = build_category_groups(all_products, product_categories, category_names)

    return render_template('admin.html', view=view, display_products=display_products, all_products=all_products, total_items=total_items, low_stock_count=low_stock_count, total_inventory_value=total_inventory_value, today_logs=today_logs, unit_options=get_product_units(), product_categories=product_categories, category_name_by_id=category_names, category_groups=category_groups)

@tenant_route('/admin/added-products')
def admin_added_products():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    ensure_tint_recipe_tables()
    period = request.args.get('period', 'all')
    if period not in ('7', '30', '90', '365', 'all'):
        period = 'all'
    supplier = request.args.get('supplier', '').strip()
    invoice_number = request.args.get('invoice_number', '').strip()

    products_query = Product.query
    if period != 'all':
        start_at = datetime.now(timezone.utc) - timedelta(days=int(period))
        products_query = products_query.filter(Product.created_at >= start_at)
    if supplier:
        products_query = products_query.filter(Product.supplier.ilike(f'%{supplier}%'))
    if invoice_number:
        products_query = products_query.filter(Product.invoice_number.ilike(f'%{invoice_number}%'))

    products = products_query.order_by(Product.created_at.desc(), Product.name).all()
    return render_template(
        'added_products.html',
        products=products,
        period=period,
        supplier=supplier,
        invoice_number=invoice_number,
        category_name_by_id=get_product_category_name_map()
    )

@tenant_route('/staff/purchase-orders', methods=['GET', 'POST'])
def staff_purchase_orders():
    ensure_tint_recipe_tables()

    if request.method == 'POST':
        json_request = request.is_json
        payload = request.get_json(silent=True) if json_request else None
        form_data = payload if isinstance(payload, dict) else request.form
        supplier = ' '.join(str(form_data.get('supplier', '')).split())
        currency = str(form_data.get('currency', '')).upper()
        vat_mode = str(form_data.get('vat_mode', ''))

        def request_error(message, status=400):
            if json_request:
                return jsonify({'success': False, 'error': message}), status
            flash(message, 'error')
            return redirect(url_for('staff_purchase_orders', supplier=supplier, currency=currency, vat_mode=vat_mode))

        if not supplier or len(supplier) > 250:
            return request_error('Choose a supplier before creating a purchase order.')
        if currency not in ('USD', 'KES') or vat_mode not in ('standard', 'exempt'):
            return request_error('Choose USD or KES and a valid VAT option.')
        try:
            raw_emails = form_data.get('supplier_emails', []) if json_request else request.form.getlist('supplier_email')
            supplier_emails = parse_supplier_emails(raw_emails)
        except ValueError as exc:
            return request_error(str(exc))

        supplier_products = Product.query.filter(
            db.func.lower(Product.supplier) == supplier.casefold()
        ).all()
        products_by_id = {normalize_product_uuid(product.id): product for product in supplier_products}
        try:
            if json_request:
                raw_items = form_data.get('items', [])
                if not isinstance(raw_items, list):
                    return request_error('Purchase-order items must be provided as a list.')
                submitted_items = [
                    (normalize_product_uuid(item.get('product_id')), item.get('quantity'), item.get('unit_cost'))
                    for item in raw_items if isinstance(item, dict)
                ]
                if len(submitted_items) != len(raw_items):
                    return request_error('Each purchase-order item must be an object.')
            else:
                selected_ids = [normalize_product_uuid(value) for value in request.form.getlist('product_id')]
                submitted_items = [
                    (product_id, request.form.get(f'quantity_{product_id}', ''), request.form.get(f'unit_cost_{product_id}', ''))
                    for product_id in selected_ids
                ]
        except (ValueError, TypeError, AttributeError):
            return request_error('One or more selected products have an invalid UUID.')

        submitted_ids = [product_id for product_id, _, _ in submitted_items]
        if not submitted_ids or len(submitted_ids) != len(set(submitted_ids)) or not set(submitted_ids).issubset(products_by_id):
            return request_error('Select valid, unique products supplied by this supplier.')

        line_items = []
        for product_id, raw_quantity, raw_unit_cost in submitted_items:
            try:
                quantity = Decimal(str(raw_quantity).strip())
                unit_cost = Decimal(str(raw_unit_cost).strip())
            except Exception:
                return request_error('Enter a valid quantity and unit cost for each selected product.')
            if not quantity.is_finite() or quantity <= 0 or not unit_cost.is_finite() or unit_cost < 0:
                return request_error('Quantities must be greater than zero and unit costs cannot be negative.')
            quantity = quantity.quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)
            unit_cost = unit_cost.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            line_total = (quantity * unit_cost).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            line_items.append((products_by_id[product_id], quantity, unit_cost, line_total))

        try:
            subtotal = sum((line_total for _, _, _, line_total in line_items), Decimal('0.00'))
            vat_rate = Decimal('16.00') if vat_mode == 'standard' else Decimal('0.00')
            vat_amount = (subtotal * vat_rate / Decimal('100')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            order = PurchaseOrder(
                po_number=f"PO-{datetime.now().strftime('%Y%m%d')}-{uuid4().hex[:6].upper()}",
                supplier=supplier,
                currency=currency,
                vat_mode=vat_mode,
                vat_rate=vat_rate,
                subtotal=subtotal,
                vat_amount=vat_amount,
                total=subtotal + vat_amount,
                supplier_emails=','.join(supplier_emails) or None,
                approval_token=secrets.token_urlsafe(32)
            )
            db.session.add(order)
            db.session.flush()
            po_log_event(order, 'pending', 'staff', 'Purchase order created')
            for product, quantity, unit_cost, line_total in line_items:
                db.session.add(PurchaseOrderItem(
                    purchase_order_id=order.id,
                    product_id=product.id,
                    product_sku=product.sku,
                    product_name=product.name or 'Unnamed product',
                    quantity=quantity,
                    unit=product.unit_of_measure or '',
                    unit_cost=unit_cost,
                    line_total=line_total
                ))
            db.session.commit()
            flash(f'Purchase order {order.po_number} created. Inventory balances were not changed.', 'success')
            if json_request:
                return jsonify({
                    'success': True,
                    'purchase_order': {
                        'id': order.id,
                        'po_number': order.po_number,
                        'supplier': order.supplier,
                        'currency': order.currency,
                        'subtotal': format(order.subtotal, 'f'),
                        'vat_amount': format(order.vat_amount, 'f'),
                        'total': format(order.total, 'f')
                    },
                    'url': url_for('staff_purchase_order_detail', order_id=order.id)
                }), 201
            return redirect(url_for('staff_purchase_order_detail', order_id=order.id))
        except Exception as exc:
            db.session.rollback()
            app.logger.exception('Unable to create staff purchase order')
            detail = str(getattr(exc, 'orig', exc)).strip().splitlines()[0][:300]
            message = f'Unable to save the purchase order: {detail}'
            if json_request:
                return jsonify({'success': False, 'error': message}), 500
            flash(message, 'error')
            return redirect(url_for('staff_purchase_orders', supplier=supplier, currency=currency, vat_mode=vat_mode))

    suppliers = [row[0] for row in db.session.query(Product.supplier).filter(
        Product.supplier.isnot(None), Product.supplier != ''
    ).distinct().order_by(Product.supplier).all()]
    supplier = request.args.get('supplier', '').strip()
    currency = request.args.get('currency', 'KES').upper()
    if currency not in ('KES', 'USD'):
        currency = 'KES'
    vat_mode = request.args.get('vat_mode', 'standard')
    if vat_mode not in ('standard', 'exempt'):
        vat_mode = 'standard'

    supplier_products = Product.query.filter(
        db.func.lower(Product.supplier) == supplier.casefold()
    ).order_by(Product.name).all() if supplier else []
    low_stock_products = []
    other_products = []
    for product in supplier_products:
        total_available = Decimal(product.current_stock or 0) + Decimal(product.parent_stock or 0)
        minimum = Decimal(product.min_stock_level or 0)
        if total_available < minimum:
            low_stock_products.append((product, minimum - total_available))
        else:
            other_products.append(product)

    orders = PurchaseOrder.query.order_by(PurchaseOrder.created_at.desc()).limit(50).all()
    last_emails = []
    if supplier:
        previous = PurchaseOrder.query.filter(
            db.func.lower(PurchaseOrder.supplier) == supplier.casefold(), PurchaseOrder.supplier_emails.isnot(None)
        ).order_by(PurchaseOrder.created_at.desc()).first()
        last_emails = po_email_list(previous) if previous else []
    return render_template(
        'staff_purchase_orders.html',
        suppliers=suppliers,
        supplier=supplier,
        currency=currency,
        vat_mode=vat_mode,
        low_stock_products=low_stock_products,
        other_products=other_products,
        orders=orders,
        last_emails=last_emails
    )

@tenant_route('/staff/purchase-orders/<int:order_id>')
def staff_purchase_order_detail(order_id):
    ensure_tint_recipe_tables()
    order = PurchaseOrder.query.get_or_404(order_id)
    po_sync_status(order)
    items = PurchaseOrderItem.query.filter_by(purchase_order_id=order.id).order_by(PurchaseOrderItem.product_name).all()
    events = PurchaseOrderEvent.query.filter_by(purchase_order_id=order.id).order_by(PurchaseOrderEvent.created_at, PurchaseOrderEvent.id).all()
    link = po_public_link(order) if order.approval_token else None
    return render_template(
        'staff_purchase_order_detail.html', order=order, items=items, events=events,
        emails=po_email_list(order), supplier_link=link, track_order=PO_TRACK_ORDER
    )

@tenant_route('/staff/purchase-orders/<int:order_id>/send', methods=['POST'])
def staff_purchase_order_send(order_id):
    ensure_tint_recipe_tables()
    order = PurchaseOrder.query.get_or_404(order_id)
    if order.status not in ('pending', 'sent', 'revision_requested'):
        flash('This purchase order can no longer be sent for approval.', 'error')
        return redirect(url_for('staff_purchase_order_detail', order_id=order.id))
    try:
        emails = parse_supplier_emails(request.form.getlist('supplier_email'))
    except ValueError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('staff_purchase_order_detail', order_id=order.id))
    if not emails:
        flash('Add at least one supplier email address.', 'error')
        return redirect(url_for('staff_purchase_order_detail', order_id=order.id))
    items = PurchaseOrderItem.query.filter_by(purchase_order_id=order.id).order_by(PurchaseOrderItem.product_name).all()
    try:
        order.supplier_emails = ','.join(emails)
        if not order.approval_token:
            order.approval_token = secrets.token_urlsafe(32)
        link = po_public_link(order)
        sent, error = send_po_email(order, items, link, emails)
        if order.status != 'sent':
            po_log_event(order, 'sent', 'staff', 'Sent to ' + ', '.join(emails) if sent else 'Link generated (email not delivered)')
        else:
            db.session.add(PurchaseOrderEvent(purchase_order_id=order.id, status='sent', actor='staff', note='Re-sent to ' + ', '.join(emails)))
        db.session.commit()
        if sent:
            flash('Purchase order emailed to ' + ', '.join(emails) + '.', 'success')
        else:
            flash(f'Email not sent: {error} Share the supplier link below manually.', 'error')
    except Exception as exc:
        db.session.rollback()
        app.logger.exception('Unable to send purchase order')
        flash(f'Unable to send the purchase order: {str(getattr(exc, "orig", exc))[:200]}', 'error')
    return redirect(url_for('staff_purchase_order_detail', order_id=order.id))

@tenant_route('/staff/purchase-orders/<int:order_id>/review', methods=['POST'])
def staff_purchase_order_review(order_id):
    ensure_tint_recipe_tables()
    order = PurchaseOrder.query.get_or_404(order_id)
    if order.status != 'revision_requested':
        flash('No supplier changes are waiting for review.', 'error')
        return redirect(url_for('staff_purchase_order_detail', order_id=order.id))
    items = PurchaseOrderItem.query.filter_by(purchase_order_id=order.id).all()
    try:
        if request.form.get('decision') == 'accept':
            kept = []
            for item in items:
                if item.supplier_included is False:
                    db.session.delete(item)
                    continue
                if item.supplier_quantity is not None:
                    item.quantity = item.supplier_quantity
                if item.supplier_unit_cost is not None:
                    item.unit_cost = item.supplier_unit_cost
                item.line_total = (item.quantity * item.unit_cost).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                kept.append(item)
            po_recalculate(order, kept)
            po_log_event(order, 'approved', 'staff', 'Supplier changes accepted')
            flash('Supplier changes accepted. The order is approved.', 'success')
        else:
            po_log_event(order, 'sent', 'staff', 'Supplier changes rejected; original order stands')
            flash('Changes rejected. The order is back with the supplier for approval.', 'success')
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        app.logger.exception('Unable to review purchase order changes')
        flash(f'Unable to update the purchase order: {str(getattr(exc, "orig", exc))[:200]}', 'error')
    return redirect(url_for('staff_purchase_order_detail', order_id=order.id))

@tenant_route('/po/respond/<token>', methods=['GET', 'POST'])
def supplier_po_response(token):
    if not re.fullmatch(r'[A-Za-z0-9_-]{20,64}', token or ''):
        return render_template('supplier_po_response.html', order=None), 404
    order = PurchaseOrder.query.filter_by(approval_token=token).first()
    if not order:
        return render_template('supplier_po_response.html', order=None), 404
    po_sync_status(order)
    items = PurchaseOrderItem.query.filter_by(purchase_order_id=order.id).order_by(PurchaseOrderItem.product_name).all()
    error = None
    if request.method == 'POST':
        action = request.form.get('action', '')
        comment = ' '.join(request.form.get('comment', '').split())[:1000]
        try:
            if action in ('submit', 'decline') and order.status == 'sent':
                if action == 'decline':
                    order.supplier_comment = comment or None
                    po_log_event(order, 'declined', 'supplier', comment or 'Declined by supplier')
                else:
                    changed = False
                    for item in items:
                        included = request.form.get(f'include_{item.id}') == 'on'
                        quantity = Decimal(request.form.get(f'quantity_{item.id}', '').strip()).quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)
                        unit_cost = Decimal(request.form.get(f'unit_cost_{item.id}', '').strip()).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                        if not quantity.is_finite() or quantity <= 0 or not unit_cost.is_finite() or unit_cost < 0:
                            raise ValueError('Quantities must be above zero and prices cannot be negative.')
                        item.supplier_included = included
                        item.supplier_quantity = quantity
                        item.supplier_unit_cost = unit_cost
                        if not included or quantity != item.quantity or unit_cost != item.unit_cost:
                            changed = True
                    if not any(i.supplier_included for i in items):
                        raise ValueError('Tick at least one item, or decline the order.')
                    order.supplier_comment = comment or None
                    if changed:
                        po_log_event(order, 'revision_requested', 'supplier', comment or 'Supplier proposed changes to quantity/price/items')
                    else:
                        po_log_event(order, 'approved', 'supplier', comment or 'Approved as ordered')
            elif action == 'advance' and order.status in PO_NEXT_STEPS:
                target = request.form.get('next_status', '')
                if target not in PO_NEXT_STEPS[order.status]:
                    raise ValueError('That step is not available.')
                note = None
                if target == 'out_for_delivery':
                    invoice = ' '.join(request.form.get('invoice_number', '').split())[:120]
                    waybill = ' '.join(request.form.get('waybill_number', '').split())[:120]
                    phone = ' '.join(request.form.get('driver_phone', '').split())[:60]
                    if not (invoice or waybill or phone):
                        raise ValueError('Enter an invoice number, waybill number or delivery person phone.')
                    order.invoice_number = invoice or order.invoice_number
                    order.waybill_number = waybill or order.waybill_number
                    order.driver_phone = phone or order.driver_phone
                    note = ' | '.join(p for p in (f'Invoice {invoice}' if invoice else '', f'Waybill {waybill}' if waybill else '', f'Driver {phone}' if phone else '') if p)
                po_log_event(order, target, 'supplier', note)
            else:
                raise ValueError('This action is not available for the current order status.')
            db.session.commit()
            return redirect(url_for('supplier_po_response', token=token))
        except (ValueError, ArithmeticError) as exc:
            db.session.rollback()
            known = ('Quantities must', 'Tick at least', 'Enter an invoice', 'That step')
            error = str(exc) if str(exc).startswith(known) else 'Enter a valid quantity and price for every item.'
        except Exception as exc:
            db.session.rollback()
            app.logger.exception('Supplier PO response failed')
            error = 'Something went wrong. Please try again.'
        items = PurchaseOrderItem.query.filter_by(purchase_order_id=order.id).order_by(PurchaseOrderItem.product_name).all()
    events = PurchaseOrderEvent.query.filter_by(purchase_order_id=order.id).order_by(PurchaseOrderEvent.created_at, PurchaseOrderEvent.id).all()
    return render_template(
        'supplier_po_response.html', order=order, items=items, events=events, error=error,
        next_steps=PO_NEXT_STEPS.get(order.status, []), track_order=PO_TRACK_ORDER
    )

@tenant_route('/admin/add-product', methods=['POST'])
def admin_add_product():
    ensure_tint_recipe_tables()
    name = request.form['name'].strip()
    sku = request.form['sku'].strip()
    supplier = request.form.get('supplier', '').strip() or None
    invoice_number = request.form.get('invoice_number', '').strip() or None
    unit_of_measure = get_submitted_unit()
    
    if not name or not sku or not unit_of_measure or len(unit_of_measure) > 20:
        flash('Please enter a name, SKU, and a unit no longer than 20 characters.', 'error')
        return redirect(url_for('admin_dashboard', view='inventory'))

    category = resolve_product_category()
    if not category:
        flash('Please choose a valid category or enter a new category name.', 'error')
        return redirect(url_for('admin_dashboard', view='inventory'))
    
    current_stock = Decimal(request.form.get('current_stock', '0') or '0')
    parent_stock = Decimal(request.form.get('parent_stock', '0') or '0')
    min_stock_level = Decimal(request.form.get('min_stock_level', '0') or '0')
    
    new_product = Product(
        sku=sku,
        qr_code=generate_product_qr_code(),
        name=name,
        supplier=supplier,
        invoice_number=invoice_number,
        unit_of_measure=unit_of_measure,
        category_id=category.id,
        current_stock=current_stock,
        parent_stock=parent_stock,
        min_stock_level=min_stock_level
    )
    
    try:
        db.session.add(new_product)
        db.session.commit()
        flash('Product added successfully!', 'success')
    except IntegrityError:
        db.session.rollback()
        flash('This SKU is already in use. Please choose a unique identifier.', 'error')
    
    return redirect(url_for('admin_dashboard'))

@tenant_route('/issue-item', methods=['POST'])
def issue_item():
    try:
        product_id = normalize_product_uuid(request.form['product_id'])
        quantity_used = Decimal(request.form['quantity_used'])
        technician_name = request.form['technician_name']
        project_ref = request.form.get('project_ref', '').strip()
        is_tinting = request.form.get('is_tinting') == 'on'

        if len(project_ref) > 100 or (is_tinting and not project_ref):
            flash('Tinting recipes require a project reference of no more than 100 characters.', 'error')
            return redirect(url_for('staff_inventory'))
        
        product = Product.query.get(product_id)
        if not product:
            flash('Product not found!', 'error')
            return redirect(url_for('staff_inventory'))
        
        if quantity_used <= 0:
            flash('Quantity must be greater than 0.', 'error')
            return redirect(url_for('staff_inventory'))
        
        if quantity_used > product.current_stock:
            flash(f'Insufficient stock! Required: {quantity_used}, Available: {product.current_stock}', 'error')
            return redirect(url_for('staff_inventory'))
        
        product.current_stock = Decimal(product.current_stock or 0) - quantity_used
        
        sku_to_save = product.sku
        
        usage_log = UsageLog(
            product_id=product_id,
            quantity_used=-abs(float(quantity_used)),
            technician_name=technician_name,
            project_ref=project_ref,
            product_sku=sku_to_save
        )
        db.session.add(usage_log)

        if is_tinting:
            ensure_tint_recipe_tables()
            recipe = TintRecipe.query.filter(
                db.func.lower(TintRecipe.project_ref) == project_ref.lower()
            ).first()
            if not recipe:
                recipe = TintRecipe(recipe_name=project_ref, project_ref=project_ref)
                db.session.add(recipe)
                db.session.flush()

            ingredient = TintRecipeItem.query.filter_by(
                recipe_id=recipe.id,
                product_name=product.name or 'Unnamed product',
                unit=product.unit_of_measure or ''
            ).first()
            if ingredient:
                ingredient.quantity += Decimal(str(quantity_used))
            else:
                db.session.add(TintRecipeItem(
                    recipe_id=recipe.id,
                    product_name=product.name or 'Unnamed product',
                    quantity=Decimal(str(quantity_used)),
                    unit=product.unit_of_measure or '',
                    product_id=None
                ))
            recipe.updated_at = datetime.now(timezone.utc)

        db.session.commit()
        flash('Item issued and added to the saved tint recipe.' if is_tinting else 'Successfully issued item', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Database error occurred. Please try again. ({str(e)})', 'error')
    
    return redirect(url_for('staff_inventory'))

@tenant_route('/delete-product/<product_id>', methods=['POST'])
def delete_product(product_id):
    try:
        product = Product.query.filter_by(id=normalize_product_uuid(product_id)).first_or_404()
        # Delete related logs first to avoid FK constraint
        UsageLog.query.filter_by(product_id=product.id).delete()
        db.session.delete(product)
        db.session.commit()
        flash('Product and related logs deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Delete failed: {str(e)}', 'error')
    return redirect(url_for('admin_dashboard'))

@tenant_route('/admin/transfer-stock', methods=['POST'])
def admin_transfer_stock():
    try:
        product_id = normalize_product_uuid(request.form['product_id'])
        quantity = Decimal(request.form['quantity'])
        
        product = Product.query.get_or_404(product_id)
        
        if quantity <= 0:
            flash('Quantity must be greater than 0.', 'error')
            return redirect(url_for('admin_dashboard'))
        
        if product.parent_stock < quantity:
            flash(f'Insufficient parent stock! Available: {product.parent_stock:.3f}', 'error')
            return redirect(url_for('admin_dashboard'))
        
        # Perform the transfer
        product.parent_stock = Decimal(product.parent_stock or 0) - quantity
        product.current_stock = Decimal(product.current_stock or 0) + quantity
        
        # Log the action in your existing UsageLog table
        usage_log = UsageLog(
            product_id=product_id,
            product_sku=product.sku,
            quantity_used=quantity,
            technician_name='TRANSFER_TO_STAFF',
            project_ref=f'Transfer to Staff: {product.name}'
        )
        db.session.add(usage_log)
        db.session.commit()
        
        flash(f'Transferred {quantity:.3f} successfully!', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Transfer failed: {str(e)}', 'error')
    
    return redirect(url_for('admin_dashboard'))

@tenant_route('/edit-product/<string:product_id>', methods=['GET', 'POST'])
def edit_product(product_id):
    ensure_tint_recipe_tables()
    try:
        product_id = normalize_product_uuid(product_id)
    except (ValueError, TypeError):
        abort(404)
    product = Product.query.get_or_404(product_id)
    
    if request.method == 'POST':
        unit_of_measure = get_submitted_unit()
        if not unit_of_measure or len(unit_of_measure) > 20:
            flash('Enter a unit of measure no longer than 20 characters.', 'error')
            return render_template('edit_product.html', product=product, unit_options=get_product_units(), product_categories=ProductCategory.query.order_by(ProductCategory.name).all(), category_name_by_id=get_product_category_name_map())
        category = resolve_product_category()
        if not category:
            flash('Choose a valid product category.', 'error')
            return render_template('edit_product.html', product=product, unit_options=get_product_units(), product_categories=ProductCategory.query.order_by(ProductCategory.name).all(), category_name_by_id=get_product_category_name_map())
        product.sku = request.form['sku'].strip()
        product.name = request.form['name'].strip()
        product.supplier = request.form.get('supplier', '').strip() or None
        product.invoice_number = request.form.get('invoice_number', '').strip() or None
        product.unit_of_measure = unit_of_measure
        product.category_id = category.id
        product.current_stock = Decimal(product.current_stock or 0) + Decimal(request.form.get('current_stock') or '0')
        product.parent_stock = Decimal(product.parent_stock or 0) + Decimal(request.form.get('parent_stock') or '0')
        product.min_stock_level = Decimal(request.form.get('min_stock_level', str(product.min_stock_level or 0)) or '0')
        
        try:
            db.session.commit()
            flash('Product updated successfully!', 'success')
            return redirect(url_for('admin_dashboard'))
        except IntegrityError:
            db.session.rollback()
            flash('SKU already exists. Please choose a unique SKU.', 'error')
    
    return render_template('edit_product.html', product=product, unit_options=get_product_units(), product_categories=ProductCategory.query.order_by(ProductCategory.name).all(), category_name_by_id=get_product_category_name_map())

def bootstrap_initial_admin():
    password = os.getenv('INITIAL_ADMIN_PASSWORD')
    if not password:
        app.logger.warning('Skipping initial admin creation: INITIAL_ADMIN_PASSWORD is not set')
        return

    with app.app_context():
        lock_user_provisioning()
        if TenantUser.query.count() != 0:
            db.session.commit()
            return

        email = os.getenv('INITIAL_ADMIN_EMAIL', 'admin@whitetap.com').strip().lower()
        if len(email) > 255 or not EMAIL_PATTERN.fullmatch(email):
            raise RuntimeError('INITIAL_ADMIN_EMAIL must be a valid email address')
        if len(password) < 12:
            raise RuntimeError('INITIAL_ADMIN_PASSWORD must contain at least 12 characters')
        tenant = db.session.get(Tenant, 1)
        if tenant is None or tenant.slug != 'whitetap':
            raise RuntimeError('Initial admin requires the whitetap tenant to have ID 1')

        db.session.add(TenantUser(
            tenant_id=1,
            email=email,
            password_hash=generate_password_hash(password),
            role='admin'
        ))
        db.session.commit()
        app.logger.warning('Initial Whitetap admin account created from environment variables')


bootstrap_initial_admin()

port = int(os.environ.get('PORT', 10000))


if __name__ == '__main__':
    with app.app_context():
        try:
            db.session.execute(text('SELECT 1'))
            print('✅ SUCCESS: Connected to SUPABASE POSTGRES (Not SQLite!)')
        except Exception as e:
            print(f'❌ Startup FAILED: {e}')
    
    print(f'🚀 Aviation ERP running on port {port}')
    app.run(host='0.0.0.0', debug=True, port=port)
