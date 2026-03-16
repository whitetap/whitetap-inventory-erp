from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import UniqueConstraint

db = SQLAlchemy()

class Product(db.Model):
    __tablename__ = 'product'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, index=True, nullable=False)
    category = db.Column(db.String(50), index=True)
    unit_type = db.Column(db.String(20), nullable=False)
    min_stock_level = db.Column(db.Float, default=0.0)
    current_stock = db.Column(db.Float, default=0.0)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    formula_results = db.relationship('FormulaIngredient', foreign_keys='FormulaIngredient.result_color_id', backref='result_color', lazy='dynamic')
    formula_ingredients = db.relationship('FormulaIngredient', foreign_keys='FormulaIngredient.pigment_id', backref='pigment', lazy='dynamic')
    stock_logs = db.relationship('StockLog', backref='product', lazy='dynamic')

class FormulaIngredient(db.Model):
    __tablename__ = 'formula_ingredient'

    id = db.Column(db.Integer, primary_key=True)
    result_color_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False, index=True)
    pigment_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False, index=True)
    quantity = db.Column(db.Float, nullable=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (UniqueConstraint('result_color_id', 'pigment_id', name='unique_formula_ing'),)

class StockLog(db.Model):
    __tablename__ = 'stock_log'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False, index=True)
    change_type = db.Column(db.String(10), index=True, nullable=False)
    quantity_change = db.Column(db.Float, nullable=False)
    reason = db.Column(db.String(200))
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)

class ClientPO(db.Model):
    __tablename__ = 'client_po'

    id = db.Column(db.Integer, primary_key=True)
    client_name = db.Column(db.String(100), index=True, nullable=False)
    po_number = db.Column(db.String(50), unique=True, index=True, nullable=False)
    file_path = db.Column(db.String(500))
    total_amount = db.Column(db.Float)
    status = db.Column(db.String(50), default='pending', index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    po_details = db.Column(JSONB)

class UsageReport(db.Model):
    __tablename__ = 'usage_report'

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.String(100), unique=True, index=True, nullable=False)
    result_color_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False, index=True)
    scale_factor = db.Column(db.Float, default=1.0)
    status = db.Column(db.String(20), default='completed', index=True)
    total_volume_ml = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

