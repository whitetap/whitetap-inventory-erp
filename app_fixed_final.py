import os
import psycopg2
from dotenv import load_dotenv
from uuid import uuid4
import csv
from io import StringIO
from flask import Flask, render_template, request, redirect, url_for, flash, session, Response, make_response
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from sqlalchemy.exc import IntegrityError
from sqlalchemy import desc, text
from sqlalchemy.engine import make_url
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime, timedelta, timezone
from decimal import Decimal

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

class Product(db.Model):
    __tablename__ = 'products'

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    sku = db.Column(db.String(50))
    name = db.Column(db.String(100))
    unit_of_measure = db.Column(db.String(20))
    category_id = db.Column(UUID(as_uuid=True))
    current_stock = db.Column(db.Float, default=0.0)
    parent_stock = db.Column(db.Float, default=0.0)
    min_stock_level = db.Column(db.Float, default=0.0)

    def __repr__(self):
        return f'<Product {self.name} ({self.sku})>'

class UsageLog(db.Model):
    __tablename__ = 'usage_logs'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(UUID(as_uuid=True), db.ForeignKey('products.id'), nullable=False)
    product_sku = db.Column(db.String(50))
    quantity_used = db.Column(db.Float, nullable=False)
    technician_name = db.Column(db.String(100), nullable=False)
    project_ref = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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

_tint_recipe_schema_ready = False

def ensure_tint_recipe_tables():
    global _tint_recipe_schema_ready
    if not _tint_recipe_schema_ready:
        db.metadata.create_all(
            bind=db.engine,
            tables=[TintRecipe.__table__, TintRecipeItem.__table__],
            checkfirst=True
        )
        _tint_recipe_schema_ready = True

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

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/staff-inventory')
def staff_inventory():
    ensure_tint_recipe_tables()
    search_query = request.args.get('search', '')
    activity_filter = request.args.get('activity_filter', '')
    
    all_products = Product.query.all()
    
    # Split products
    paints = [p for p in all_products if 'PNT' in (p.sku or '').upper()]
    carpets = [p for p in all_products if 'CRP' in (p.sku or '').upper()]
    others = [p for p in all_products if 'PNT' not in (p.sku or '').upper() and 'CRP' not in (p.sku or '').upper()]
    
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
    
    return render_template('staff_dashboard.html', paints=paints, carpets=carpets, others=others, recent_logs=recent_logs, search_query=search_query, activity_filter=activity_filter, low_stock_products=low_stock_products, low_stock_count=low_stock_count, tint_projects=tint_projects)

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

@app.route('/export-logs')
def export_logs():
    period = request.args.get('period', 'all')
    if period not in USAGE_PERIOD_LABELS:
        period = 'all'
    start = get_usage_period_start(period)
    logs_query = db.session.query(UsageLog, Product.name).outerjoin(Product, Product.id == UsageLog.product_id)
    if start:
        logs_query = logs_query.filter(UsageLog.created_at >= start)
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
    if period not in USAGE_PERIOD_LABELS:
        period = 'daily'
    start = get_usage_period_start(period)
    logs_query = db.session.query(UsageLog, Product.name).outerjoin(Product, Product.id == UsageLog.product_id)
    if start:
        logs_query = logs_query.filter(UsageLog.created_at >= start)
    rows = logs_query.order_by(desc(UsageLog.created_at)).all()
    logs = [{
        'created_at': log.created_at,
        'product_name': product_name or 'Deleted product',
        'product_sku': log.product_sku or '-',
        'quantity_used': log.quantity_used,
        'technician_name': log.technician_name,
        'project_ref': log.project_ref or '-'
    } for log, product_name in rows]

    return render_template(
        'usage_logs.html',
        logs=logs,
        period=period,
        period_label=USAGE_PERIOD_LABELS[period],
        period_options=USAGE_PERIOD_LABELS
    )

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
    
    return render_template('admin.html', view=view, display_products=display_products, all_products=all_products, total_items=total_items, low_stock_count=low_stock_count, total_inventory_value=total_inventory_value, today_logs=today_logs, unit_options=get_product_units())

@app.route('/admin/add-product', methods=['POST'])
def admin_add_product():
    name = request.form['name'].strip()
    sku = request.form['sku'].strip()
    unit_of_measure = get_submitted_unit()
    
    if not name or not sku or not unit_of_measure or len(unit_of_measure) > 20:
        flash('Please fill in all required fields: Name, SKU, Unit of Measure.', 'error')
        return redirect(url_for('admin_dashboard'))
    
    current_stock = float(request.form.get('current_stock', 0))
    parent_stock = float(request.form.get('parent_stock', 0))
    min_stock_level = float(request.form.get('min_stock_level', 0))
    
    new_product = Product(
        sku=sku,
        name=name,
        unit_of_measure=unit_of_measure,
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
        quantity_used = float(request.form['quantity_used'])
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
        
        product.current_stock -= quantity_used
        
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
        quantity = float(request.form['quantity'])
        
        product = Product.query.get_or_404(product_id)
        
        if quantity <= 0:
            flash('Quantity must be greater than 0.', 'error')
            return redirect(url_for('admin_dashboard'))
        
        if product.parent_stock < quantity:
            flash(f'Insufficient parent stock! Available: {product.parent_stock:.3f}', 'error')
            return redirect(url_for('admin_dashboard'))
        
        # Perform the transfer
        product.parent_stock -= quantity
        product.current_stock += quantity
        
        # Log the action in your existing UsageLog table
        usage_log = UsageLog(
            product_id=product_id,
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
    product = Product.query.get_or_404(product_id)
    
    if request.method == 'POST':
        unit_of_measure = get_submitted_unit()
        if not unit_of_measure or len(unit_of_measure) > 20:
            flash('Enter a unit of measure no longer than 20 characters.', 'error')
            return render_template('edit_product.html', product=product, unit_options=get_product_units())
        product.sku = request.form['sku'].strip()
        product.name = request.form['name'].strip()
        product.unit_of_measure = unit_of_measure
        product.current_stock += float(request.form.get('current_stock') or 0)
        product.parent_stock += float(request.form.get('parent_stock') or 0)
        product.min_stock_level = float(request.form.get('min_stock_level', product.min_stock_level))
        
        try:
            db.session.commit()
            flash('Product updated successfully!', 'success')
            return redirect(url_for('admin_dashboard'))
        except IntegrityError:
            db.session.rollback()
            flash('SKU already exists. Please choose a unique SKU.', 'error')
    
    return render_template('edit_product.html', product=product, unit_options=get_product_units())

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


