from flask import Flask, render_template, request, jsonify
from flask_migrate import Migrate
from datetime import datetime
from config import Config
from models import db, Product, FormulaIngredient, StockLog, UsageReport

app = Flask(__name__, template_folder='templates', static_folder='static', static_url_path='/static')
app.config.from_object(Config)

db.init_app(app)
migrate = Migrate(app, db)

@app.route('/')
def hello():
    return '<h1>Aviation ERP</h1><a href="/staff-dashboard" class="text-blue-500 underline text-2xl">Staff Dashboard</a> | <a href="/api/usage-reports/paints">API Paints</a>'

@app.route('/staff-dashboard')
def staff_dashboard():
    return render_template('staff_dashboard.html')

@app.route('/api/product/<int:product_id>')
def api_product(product_id):
    product = Product.query.get_or_404(product_id)
    return jsonify({
        'id': product.id,
        'name': product.name,
        'category': product.category,
        'current_stock': float(product.current_stock),  # Smallest unit ml/sqft
        'unit_type': product.unit_type,
        'min_stock_level': float(product.min_stock_level)
    })

@app.route('/api/carpet-stock')
def api_carpet_stock():
    carpets = Product.query.filter(Product.category == 'carpet').all()
    return jsonify([{
        'name': c.name,
        'stock_sqft': float(c.current_stock)
    } for c in carpets])

@app.route('/api/usage-reports/<usage_type>')
def api_usage_reports(usage_type):
    if usage_type not in ['paints', 'carpets']:
        return jsonify({'error': 'Invalid type: paints or carpets'}), 400

    query = UsageReport.query.join(Product, Product.id == UsageReport.result_color_id)
    if usage_type == 'carpets':
        query = query.filter(Product.category.ilike('%carpet%'))
    else:
        query = query.filter(~Product.category.ilike('%carpet%'))

    reports = query.order_by(UsageReport.created_at.desc()).limit(20).all()

    return jsonify([{
        'job_id': r.job_id,
        'created_at': r.created_at.isoformat(),
        'total_volume_ml': float(r.total_volume_ml) if r.total_volume_ml else 0,
        'scale_factor': r.scale_factor,
        'category': Product.query.get(r.result_color_id).category
    } for r in reports])

def execute_tinting(result_color_id: int, scale_factor: float = 1.0, job_id: str = None) -> dict:
    if not job_id:
        job_id = f'tint_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}_{result_color_id}'

    ingredients = FormulaIngredient.query.filter_by(result_color_id=result_color_id).all()
    if not ingredients:
        return {'success': False, 'error': 'No formula found for this color'}

    insufficient = []
    deductions = []
    for ing in ingredients:
        product = Product.query.get(ing.pigment_id)
        if not product:
            return {'success': False, 'error': f'Pigment {ing.pigment_id} not found'}
        req_ml = round(ing.quantity * scale_factor, 4)
        if product.current_stock < req_ml:
            insufficient.append({'pigment': product.name, 'required': req_ml, 'available': product.current_stock})
        deductions.append({'pigment_id': ing.pigment_id, 'qty': req_ml})

    if insufficient:
        return {'success': False, 'error': 'Insufficient stock', 'details': insufficient}

    # Transaction-safe execution
    try:
        for ded in deductions:
            product = Product.query.get(ded['pigment_id'])
            product.current_stock -= ded['qty']
            product.updated_at = datetime.utcnow()
            log = StockLog(
                product_id=ded['pigment_id'],
                change_type='deduction',
                quantity_change=-ded['qty'],
                reason=f'tinting_job:{job_id}'
            )
            db.session.add(log)

        total_ml = sum(d['qty'] for d in deductions)
        report = UsageReport(
            job_id=job_id,
            result_color_id=result_color_id,
            scale_factor=scale_factor,
            total_volume_ml=total_ml
        )
        db.session.add(report)
        db.session.flush()  # Test before commit
        db.session.commit()  # All or nothing
        return {
            'success': True,
            'job_id': job_id,
            'scale_factor': scale_factor,
            'ingredients': deductions,
            'total_ml': total_ml
        }
    except Exception as e:
        db.session.rollback()
        return {'success': False, 'error': f'Transaction failed: {str(e)}'}

@app.route('/tinting/execute', methods=['POST'])
def tinting_execute():
    data = request.json
    result_color_id = data.get('result_color_id')
    scale_factor = data.get('scale_factor', 1.0)
    job_id = data.get('job_id')

    if not result_color_id:
        return jsonify({'error': 'result_color_id required'}), 400

    result = execute_tinting(result_color_id, scale_factor, job_id)
    return jsonify(result)

@app.route('/api/products', methods=['GET'])
def api_products():
    products = Product.query.all()
    return jsonify([{
        'id': p.id,
        'name': p.name,
        'category': p.category,
        'current_stock': float(p.current_stock),
        'unit_type': p.unit_type,
        'min_stock_level': float(p.min_stock_level)
    } for p in products])

@app.route('/api/products', methods=['POST'])
def api_create_product():
    data = request.json
    product = Product(
        name=data['name'],
        category=data['category'],
        unit_type=data['unit_type'],
        current_stock=data.get('current_stock', 0.0),
        min_stock_level=data.get('min_stock_level', 0.0)
    )
    db.session.add(product)
    db.session.commit()
    return jsonify({'id': product.id, 'message': 'Product created'}), 201

@app.route('/api/formulas/<int:result_color_id>')
def api_formula(result_color_id):
    ingredients = FormulaIngredient.query.filter_by(result_color_id=result_color_id).all()
    return jsonify([{
        'pigment_id': ing.pigment_id,
        'pigment_name': Product.query.get(ing.pigment_id).name,
        'quantity': float(ing.quantity)
    } for ing in ingredients])

@app.route('/api/stock-adjust', methods=['POST'])
def api_stock_adjust():
    data = request.json
    product_id = data['product_id']
    quantity = data['quantity']
    reason = data.get('reason', 'manual_adjust')
    
    product = Product.query.get_or_404(product_id)
    product.current_stock += quantity
    product.updated_at = datetime.utcnow()
    
    log = StockLog(
        product_id=product_id,
        change_type='addition' if quantity > 0 else 'deduction',
        quantity_change=quantity,
        reason=reason
    )
    db.session.add(log)
    db.session.commit()
    return jsonify({'success': True, 'new_stock': float(product.current_stock)})

@app.route('/api/barcode/<barcode>')
def api_barcode(barcode):
    product = Product.query.filter(Product.name.contains(barcode) | Product.id == int(barcode) if barcode.isdigit() else Product.id == 0).first_or_404()
    return jsonify({
        'id': product.id,
        'name': product.name,
        'stock_ml_sqft': float(product.current_stock),  # Smallest unit
        'unit_type': product.unit_type
    })

@app.route('/api/upload-po', methods=['POST'])
def api_upload_po():
    # Stub for ClientPO - assumes file handling via form/multipart
    data = request.form
    client_name = data.get('client_name')
    po_number = data.get('po_number')
    file_path = request.files.get('file').filename if 'file' in request.files else None
    
    po = ClientPO(
        client_name=client_name,
        po_number=po_number,
        file_path=file_path,
        total_amount=float(data.get('total_amount', 0)),
        status='pending'
    )
    db.session.add(po)
    db.session.commit()
    return jsonify({'id': po.id, 'message': 'PO uploaded'})

if __name__ == '__main__':\n    app.run(debug=True, port=5005)

