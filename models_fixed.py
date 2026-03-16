from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid

db = SQLAlchemy()

class Product(db.Model):
    __tablename__ = 'products'

    id = db.Column(UUID(as_uuid=True), primary_key=True)
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
