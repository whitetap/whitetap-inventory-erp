from app_fixed import app, db
from models import Product, FormulaIngredient
from datetime import datetime

def seed_data():
    with app.app_context():
        # Clear existing (for re-runs)
        db.drop_all()
        db.create_all()
        
        print('🌱 Seeding Aviation ERP data...')
        
        # 1. BASE PAINTS
        bases = [
            Product(name='White Base Paint', category='base_paint', unit_type='volume_ml', current_stock=50000, min_stock_level=5000), # type: ignore
            Product(name='Clear Base', category='base_paint', unit_type='volume_ml', current_stock=30000, min_stock_level=3000), # type: ignore
        ]
        
        # 2. PIGMENTS (12+ for test)
        pigments = [
            Product(name='Red Oxide Pigment', category='pigment', unit_type='volume_ml', current_stock=8000, min_stock_level=1000), # type: ignore
            Product(name='Yellow Ochre Pigment', category='pigment', unit_type='volume_ml', current_stock=7500, min_stock_level=1000), # type: ignore
            Product(name='Black Carbon Pigment', category='pigment', unit_type='volume_ml', current_stock=6000, min_stock_level=500), # type: ignore
            Product(name='Titanium White Pigment', category='pigment', unit_type='volume_ml', current_stock=12000, min_stock_level=2000), # type: ignore
            Product(name='Phthalo Blue Pigment', category='pigment', unit_type='volume_ml', current_stock=4500, min_stock_level=500), # type: ignore
            Product(name='Isoindolinone Yellow', category='pigment', unit_type='volume_ml', current_stock=3800, min_stock_level=400), # type: ignore
            Product(name='Quinacridone Magenta', category='pigment', unit_type='volume_ml', current_stock=3200, min_stock_level=300),
            Product(name='Hansa Yellow Pigment', category='pigment', unit_type='volume_ml', current_stock=4100, min_stock_level=400), # type: ignore
            Product(name='Ultramarine Blue', category='pigment', unit_type='volume_ml', current_stock=2900, min_stock_level=300),
            Product(name='Chrome Oxide Green', category='pigment', unit_type='volume_ml', current_stock=2700, min_stock_level=200),
            Product(name='Burnt Umber Pigment', category='pigment', unit_type='volume_ml', current_stock=3500, min_stock_level=350),
            Product(name='Transparent Iron Oxide Red', category='pigment', unit_type='volume_ml', current_stock=2200, min_stock_level=200),
        ]
        
        # 3. ADDITIVES
        additives = [
            Product(name='Fast Hardener', category='hardener', unit_type='volume_ml', current_stock=15000, min_stock_level=1500),
            Product(name='Slow Hardener', category='hardener', unit_type='volume_ml', current_stock=12000, min_stock_level=1000),
            Product(name='Paint Thinner', category='thinner', unit_type='volume_ml', current_stock=25000, min_stock_level=2000),
            Product(name='Surface Cleaner', category='surface_cleaner', unit_type='volume_ml', current_stock=8000, min_stock_level=800),
        ]
        
        # 4. CARPETS
        carpets = [
            Product(name='Black Carpet Roll A', category='carpet', unit_type='area_sqft', current_stock=12000, min_stock_level=1000),
            Product(name='Grey Carpet Roll B', category='carpet', unit_type='area_sqft', current_stock=8500, min_stock_level=800),
        ]
        
        all_products = bases + pigments + additives + carpets
        for p in all_products:
            db.session.add(p)
        db.session.commit()
        print(f'✅ Added {len(all_products)} products')
        
        # FORMULAS
        # Simple Red Carpet
        red_carpet = Product(name='Red Aviation Carpet', category='carpet_formula', unit_type='area_sqft', current_stock=0, min_stock_level=0)
        db.session.add(red_carpet)
        db.session.commit()
        db.session.add(FormulaIngredient(result_color_id=red_carpet.id, pigment_id=bases[0].id, quantity=100.0))  # Base
        db.session.add(FormulaIngredient(result_color_id=red_carpet.id, pigment_id=pigments[0].id, quantity=15.0))  # Red
        print('✅ Red Carpet formula')
        
        # SPECIALTY AVIATION PAINT (13 ingredients test)
        specialty = Product(name='Specialty Aviation Paint', category='final_color', unit_type='volume_ml', current_stock=0, min_stock_level=0)
        db.session.add(specialty)
        db.session.commit()
        
        specialty_formula = [
            (bases[0].id, 65.5),  # White base 65.5%
            (pigments[0].id, 8.2),  # Red 8.2%
            (pigments[1].id, 6.1),  # Yellow 6.1%
            (pigments[2].id, 4.3),  # Black 4.3%
            (pigments[3].id, 5.0),  # White pigment 5%
            (pigments[4].id, 2.8),  # Blue 2.8%
            (pigments[5].id, 1.9),  # Iso yellow 1.9%
            (pigments[6].id, 1.2),  # Magenta 1.2%
            (pigments[7].id, 1.5),  # Hansa 1.5%
            (pigments[8].id, 1.1),  # Ultramarine 1.1%
            (pigments[9].id, 0.9),  # Green 0.9%
            (pigments[10].id, 1.0), # Umber 1.0%
            (additives[0].id, 0.5), # Hardener 0.5%
        ]
        for pigment_id, qty in specialty_formula:
            db.session.add(FormulaIngredient(result_color_id=specialty.id, pigment_id=pigment_id, quantity=qty))
        print('✅ Specialty Aviation Paint formula (13 ingredients)')
        
        db.session.commit()
        print('🎉 Seed complete! Visit http://localhost:5005/staff-dashboard')

if __name__ == '__main__':
    seed_data()

