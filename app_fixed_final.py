import os
from uuid import uuid4
import csv
from io import StringIO
from flask import Flask, render_template, request, redirect, url_for, flash, Response, make_response
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from sqlalchemy.exc import IntegrityError
from sqlalchemy import desc, text
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime

app = Flask(__name__)

# Final hardcoded URI for Supabase pooler port 6543 (Project Ref in username required)
DATABASE_URL = "postgresql://postgres.ujwzbldcbczbuqernzjy:fjeAbMBqJSPcYf3m@aws-1-eu-west-3.pooler.supabase.com:6543/postgres?sslmode=require&prepare_threshold=0"

app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'aviation-admin-secure-2026')
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    "pool_pre_ping": True,
    "connect_args": {
        "prepare_threshold": 0
    }
}

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
    products = Product.query.filter(Product.sku.ilike('%PNT%')).order_by(Product.name).all()
    
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

@app.route('/admin-dashboard')
def admin_dashboard():
    products = Product.query.order_by(Product.name).all()
    return render_template('admin.html', products=products)

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
        
        usage_log = UsageLog(
            product_id=product_id,
            quantity_used=quantity_used,
            technician_name=technician_name,
            project_ref=project_ref
        )
        db.session.add(usage_log)
        db.session.commit()
        flash('Successfully issued item', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Database error occurred. Please try again. ({str(e)})', 'error')
    
    return redirect(url_for('staff_inventory'))

@app.route('/delete_product/<product_id>', methods=['POST'])
def delete_product(product_id):
    product = Product.query.get_or_404(product_id)
    db.session.delete(product)
    db.session.commit()
    flash('Product deleted successfully!', 'success')
    return redirect(url_for('admin_dashboard'))

with app.app_context():
    try:
        db.session.execute(text('SELECT 1'))
        print('✅ DATABASE CONNECTED')
    except Exception as e:
        db.session.rollback()
        print(f'❌ DB Connection FAILED: {e}')

if __name__ == '__main__':
    print(f'Connecting to: {app.config["SQLALCHEMY_DATABASE_URI"][:50]}...')
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', debug=True, port=port)

