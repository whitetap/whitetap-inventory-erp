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
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime

def get_conn():
    return psycopg2.connect(os.getenv('DATABASE_URL'))

# Force Environment Overwrite (Render priority)
load_dotenv(override=True)

app = Flask(__name__)
app.secret_key = 'RAV4Adventure2020-secure-session-key'

app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
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
    min_stock_level = db.Column(db.Float, default=0.0)

    def __repr__(self):
        return f'<Product {self.name} ({self.sku})>'

class UsageLog(db.Model):
    __tablename__ = 'usage_logs'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(UUID(as_uuid=True), db.ForeignKey('products.id'), nullable=False)
    quantity_used = db.Column(db.Float, nullable=False)
    technician_name = db.Column(db.String(100), nullable=False)
    project_ref = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

CORS(app)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/staff-inventory')
def staff_inventory():
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
    
    return render_template('staff_dashboard.html', paints=paints, carpets=carpets, others=others, recent_logs=recent_logs, search_query=search_query, activity_filter=activity_filter)

@app.route('/export-logs')
def export_logs():
    logs = UsageLog.query.order_by(desc(UsageLog.created_at)).all()
    
    output = StringIO()
    writer = csv.writer(output)
    
    writer.writerow(['Date', 'Product Name', 'Quantity', 'Technician', 'Project Reference'])
    
    for log in logs:
        product = Product.query.get(log.product_id)
        product_name = product.name if product else 'Unknown Product'
        writer.writerow([
            log.created_at.strftime('%Y-%m-%d %H:%M:%S') if log.created_at else '',
            product_name,
            log.quantity_used,
            log.technician_name,
            log.project_ref or ''
        ])
    
    output.seek(0)
    
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=usage_report.csv'}
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
    
    return render_template('admin.html', view=view, display_products=display_products, all_products=all_products, total_items=total_items, low_stock_count=low_stock_count, total_inventory_value=total_inventory_value, today_logs=today_logs)

@app.route('/admin/add-product', methods=['POST'])
def admin_add_product():
    name = request.form['name'].strip()
    sku = request.form['sku'].strip()
    unit_of_measure = request.form['unit_of_measure'].strip()
    
    if not name or not sku or not unit_of_measure:
        flash('Please fill in all required fields: Name, SKU, Unit of Measure.', 'error')
        return redirect(url_for('admin_dashboard'))
    
    current_stock = float(request.form.get('current_stock', 0))
    min_stock_level = float(request.form.get('min_stock_level', 0))
    
    new_product = Product(
        sku=sku,
        name=name,
        unit_of_measure=unit_of_measure,
        current_stock=current_stock,
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

@app.route('/restock-item', methods=['POST'])
def restock_item():
    product_id = request.form['product_id']
    amount_to_add = float(request.form['amount_to_add'])
    
    product = Product.query.get(product_id)
    if not product:
        flash('Product not found!', 'error')
        return redirect(url_for('admin_dashboard'))
    
    if amount_to_add <= 0:
        flash('Restock amount must be positive.', 'error')
        return redirect(url_for('admin_dashboard'))
    
    product.current_stock += amount_to_add
    
    usage_log = UsageLog(
        product_id=product_id,
        quantity_used=amount_to_add,
        technician_name='RESTOCK',
        project_ref=f'Restock +{amount_to_add}'
    )
    db.session.add(usage_log)
    db.session.commit()
    
    flash(f'Restocked +{amount_to_add} to {product.name}. New stock: {product.current_stock}', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/issue-item', methods=['POST'])
def issue_item():
    try:
        product_id = request.form['product_id']
        quantity_used = float(request.form['quantity_used'])
        technician_name = request.form['technician_name']
        project_ref = request.form.get('project_ref', '')
        
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
        
        product_name = product.name  # Snapshot for display
        usage_log = UsageLog(
            product_id=product_id,
            quantity_used=-quantity_used,
            technician_name=technician_name,
            project_ref=project_ref
        )
        usage_log.product_name = product_name  # Assign after init if model supports
        db.session.add(usage_log)
        db.session.commit()
        flash('Successfully issued item', 'success')
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

@app.route('/edit-product/<string:product_id>', methods=['GET', 'POST'])
def edit_product(product_id):
    product = Product.query.get_or_404(product_id)
    
    if request.method == 'POST':
        product.sku = request.form['sku'].strip()
        product.name = request.form['name'].strip()
        product.unit_of_measure = request.form['unit_of_measure'].strip()
        product.current_stock = float(request.form.get('current_stock', product.current_stock))
        product.min_stock_level = float(request.form.get('min_stock_level', product.min_stock_level))
        
        try:
            db.session.commit()
            flash('Product updated successfully!', 'success')
            return redirect(url_for('admin_dashboard'))
        except IntegrityError:
            db.session.rollback()
            flash('SKU already exists. Please choose a unique SKU.', 'error')
    
    return render_template('edit_product.html', product=product)

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


