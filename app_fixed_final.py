import os
import psycopg2
from dotenv import load_dotenv
from uuid import uuid4, UUID as PythonUUID
import csv
from io import StringIO
from flask import Flask, render_template, request, redirect, url_for, flash, session, Response, make_response, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from sqlalchemy.exc import IntegrityError
from sqlalchemy import desc, text
from sqlalchemy.engine import make_url
from sqlalchemy.dialects.postgresql import UUID
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

# Force Environment Overwrite (Render priority)
load_dotenv(override=True)

app = Flask(__name__)
app.secret_key = 'RAV4Adventure2020-secure-session-key'

app.config['SQLALCHEMY_DATABASE_URI'] = get_database_url('postgresql+psycopg2')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'Aviation-ERP-Secret-2026-Secure')
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'creator': get_conn}

db = SQLAlchemy(app)

def generate_product_qr_code():
    return f'WTI-{uuid4().hex.upper()}'

class Product(db.Model):
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

class ProductCategory(db.Model):
    __tablename__ = 'product_categories'

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = db.Column(db.String(100), nullable=False, unique=True, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

class UsageLog(db.Model):
    __tablename__ = 'usage_logs'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(UUID(as_uuid=True), db.ForeignKey('products.id'), nullable=False)
    product_sku = db.Column(db.String(50))
    quantity_used = db.Column(db.Float, nullable=False)
    technician_name = db.Column(db.String(100), nullable=False)
    project_ref = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    product = db.relationship('Product', lazy='joined')

class TintRecipe(db.Model):
    __tablename__ = 'tint_recipes'

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    recipe_name = db.Column(db.Text, nullable=False)
    project_ref = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

class TintRecipeItem(db.Model):
    __tablename__ = 'tint_recipe_items'

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    recipe_id = db.Column(db.BigInteger, db.ForeignKey('tint_recipes.id'), nullable=False, index=True)
    product_name = db.Column(db.Text, nullable=False)
    quantity = db.Column(db.Numeric, nullable=False)
    unit = db.Column(db.Text, nullable=True)
    product_id = db.Column(db.BigInteger, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

class Client(db.Model):
    __tablename__ = 'clients'

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    name = db.Column(db.Text, nullable=False)
    normalized_name = db.Column(db.Text, nullable=False, unique=True, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

class ProformaInvoice(db.Model):
    __tablename__ = 'proforma_invoices'

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    invoice_number = db.Column(db.String(40), nullable=False, unique=True, index=True)
    client_id = db.Column(db.BigInteger, db.ForeignKey('clients.id'), nullable=False, index=True)
    project_ref = db.Column(db.Text, nullable=False)
    currency = db.Column(db.String(3), nullable=False)
    tax_mode = db.Column(db.String(10), nullable=False)
    tax_rate = db.Column(db.Numeric(5, 2), nullable=False)
    subtotal = db.Column(db.Numeric(14, 2), nullable=False)
    tax_amount = db.Column(db.Numeric(14, 2), nullable=False)
    total = db.Column(db.Numeric(14, 2), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

class ProformaInvoiceItem(db.Model):
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

class PurchaseOrder(db.Model):
    __tablename__ = 'purchase_orders'

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    po_number = db.Column(db.String(40), nullable=False, unique=True, index=True)
    supplier = db.Column(db.Text, nullable=False, index=True)
    currency = db.Column(db.String(3), nullable=False)
    vat_mode = db.Column(db.String(10), nullable=False)
    vat_rate = db.Column(db.Numeric(5, 2), nullable=False)
    subtotal = db.Column(db.Numeric(14, 2), nullable=False)
    vat_amount = db.Column(db.Numeric(14, 2), nullable=False)
    total = db.Column(db.Numeric(14, 2), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='pending')
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

class PurchaseOrderItem(db.Model):
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
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

_tint_recipe_schema_ready = False

def ensure_tint_recipe_tables():
    global _tint_recipe_schema_ready
    if not _tint_recipe_schema_ready:
        db.metadata.create_all(
            bind=db.engine,
            tables=[
                TintRecipe.__table__, TintRecipeItem.__table__, ProductCategory.__table__,
                Client.__table__, ProformaInvoice.__table__, ProformaInvoiceItem.__table__,
                PurchaseOrder.__table__, PurchaseOrderItem.__table__
            ],
            checkfirst=True
        )
        _tint_recipe_schema_ready = True
    for category_name in ('Aviation paints & pigments', 'Carpet & textile', 'Other supplies'):
        category = ProductCategory.query.filter(db.func.lower(ProductCategory.name) == category_name.lower()).first()
        if not category:
            db.session.add(ProductCategory(name=category_name))
    db.session.commit()

def get_product_category_name_map():
    return {str(category.id): category.name for category in ProductCategory.query.order_by(ProductCategory.name).all()}

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

CORS(app)

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

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/staff-inventory')
def staff_inventory():
    ensure_tint_recipe_tables()
    category_names = get_product_category_name_map()
    search_query = request.args.get('search', '')
    activity_filter = request.args.get('activity_filter', '')
    
    all_products = Product.query.all()
    
    # Split products
    def belongs_to_category(product, category_name, sku_marker):
        saved_category = category_names.get(str(product.category_id), '')
        if saved_category:
            return saved_category.casefold() == category_name.casefold()
        return sku_marker in (product.sku or '').upper()

    paints = [p for p in all_products if belongs_to_category(p, 'Aviation paints & pigments', 'PNT')]
    carpets = [p for p in all_products if belongs_to_category(p, 'Carpet & textile', 'CRP')]
    others = [p for p in all_products if p not in paints and p not in carpets]
    
    # Apply search filter
    if search_query:
        def matches_search(p):
            return search_query.lower() in (p.name or '').lower() or search_query.lower() in (p.sku or '').lower()
        paints = [p for p in paints if matches_search(p)]
        carpets = [p for p in carpets if matches_search(p)]
        others = [p for p in others if matches_search(p)]
    
    # Recent activity
    logs_query = UsageLog.query.order_by(desc(UsageLog.created_at))
    if activity_filter:
        logs_query = logs_query.filter(UsageLog.project_ref.ilike(f'%{activity_filter}%'))
    recent_logs = logs_query.limit(10).all()
    
    all_items = paints + carpets + others
    low_stock_products = [p for p in all_products if (p.current_stock or 0) < (p.min_stock_level or 0)]
    low_stock_count = len(low_stock_products)
    tint_projects = [row[0] for row in db.session.query(TintRecipe.project_ref).filter(TintRecipe.project_ref.isnot(None)).order_by(TintRecipe.project_ref).all()]
    
    return render_template('staff_dashboard.html', paints=paints, carpets=carpets, others=others, recent_logs=recent_logs, search_query=search_query, activity_filter=activity_filter, low_stock_products=low_stock_products, low_stock_count=low_stock_count, tint_projects=tint_projects, category_name_by_id=category_names)

@app.route('/api/products/lookup')
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

@app.route('/api/tint-recipes')
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

@app.route('/api/tint-recipes/<int:recipe_id>', methods=['DELETE'])
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

@app.route('/export-logs')
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

@app.route('/admin/usage-logs')
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

@app.route('/admin/proforma-invoices', methods=['GET', 'POST'])
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

@app.route('/admin/proforma-invoices/<int:invoice_id>')
def proforma_invoice_detail(invoice_id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    ensure_tint_recipe_tables()
    invoice = ProformaInvoice.query.get_or_404(invoice_id)
    client = Client.query.get_or_404(invoice.client_id)
    items = ProformaInvoiceItem.query.filter_by(invoice_id=invoice.id).order_by(ProformaInvoiceItem.product_name).all()
    return render_template('proforma_invoice_detail.html', invoice=invoice, client=client, items=items)

@app.route('/export-products')
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

@app.route('/export-paints')
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

@app.route('/export-carpets')
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

@app.route('/export-inventory')
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

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.form.get('password')
        if password == 'RAV4Adventure2020':
            session['logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Incorrect password', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully', 'success')
    return redirect(url_for('login'))

@app.route('/admin-dashboard')
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
    today_logs = UsageLog.query.filter(db.func.date(UsageLog.created_at) == datetime.now().date()).count()
    
    return render_template('admin.html', view=view, display_products=display_products, all_products=all_products, total_items=total_items, low_stock_count=low_stock_count, total_inventory_value=total_inventory_value, today_logs=today_logs, unit_options=get_product_units(), product_categories=ProductCategory.query.order_by(ProductCategory.name).all(), category_name_by_id=get_product_category_name_map())

@app.route('/admin/added-products')
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

@app.route('/staff/purchase-orders', methods=['GET', 'POST'])
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
                total=subtotal + vat_amount
            )
            db.session.add(order)
            db.session.flush()
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
    return render_template(
        'staff_purchase_orders.html',
        suppliers=suppliers,
        supplier=supplier,
        currency=currency,
        vat_mode=vat_mode,
        low_stock_products=low_stock_products,
        other_products=other_products,
        orders=orders
    )

@app.route('/staff/purchase-orders/<int:order_id>')
def staff_purchase_order_detail(order_id):
    ensure_tint_recipe_tables()
    order = PurchaseOrder.query.get_or_404(order_id)
    items = PurchaseOrderItem.query.filter_by(purchase_order_id=order.id).order_by(PurchaseOrderItem.product_name).all()
    return render_template('staff_purchase_order_detail.html', order=order, items=items)

@app.route('/admin/add-product', methods=['POST'])
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

@app.route('/issue-item', methods=['POST'])
def issue_item():
    try:
        product_id = request.form['product_id']
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

@app.route('/delete-product/<product_id>', methods=['POST'])
def delete_product(product_id):
    try:
        product = Product.query.filter_by(id=product_id).first_or_404()
        # Delete related logs first to avoid FK constraint
        UsageLog.query.filter_by(product_id=product.id).delete()
        db.session.delete(product)
        db.session.commit()
        flash('Product and related logs deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Delete failed: {str(e)}', 'error')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/transfer-stock', methods=['POST'])
def admin_transfer_stock():
    try:
        product_id = request.form['product_id']
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

@app.route('/edit-product/<string:product_id>', methods=['GET', 'POST'])
def edit_product(product_id):
    ensure_tint_recipe_tables()
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


