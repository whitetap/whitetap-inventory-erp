from app_fixed import app, db, Product
with app.app_context():
    # Delete existing
    Product.query.delete()
    db.session.commit()
    
    # 13 Aviation Pigments
    pigments = [
        Product(name='Titanium White', sku='TIT-WHT-001', unit_of_measure='ml'),
        Product(name='Carbon Black', sku='CAR-BLK-001', unit_of_measure='ml'),
        Product(name='Phthalo Blue', sku='PHT-BLU-001', unit_of_measure='ml'),
        Product(name='Phthalo Green', sku='PHT-GRN-001', unit_of_measure='ml'),
        Product(name='Quinacridone Red', sku='QUI-RED-001', unit_of_measure='ml'),
        Product(name='Hans Yellow Medium', sku='HAN-YEL-001', unit_of_measure='ml'),
        Product(name='Transparent Red Iron Oxide', sku='TRI-OX-001', unit_of_measure='ml'),
        Product(name='Raw Umber', sku='RAW-UMB-001', unit_of_measure='ml'),
        Product(name='Burnt Sienna', sku='BRN-SIE-001', unit_of_measure='ml'),
        Product(name='Ultramarine Blue', sku='ULT-BLU-001', unit_of_measure='ml'),
        Product(name='Cadmium Yellow Light', sku='CAD-YEL-001', unit_of_measure='ml'),
        Product(name='Alizarin Crimson', sku='ALI-CRM-001', unit_of_measure='ml'),
        Product(name='Viridian', sku='VIR-GRN-001', unit_of_measure='ml'),
    ]
    
    # 2 Aviation Carpets
    carpets = [
        Product(name='Red Cabin Carpet', sku='RCC-001', unit_of_measure='sq_ft'),
        Product(name='Navy Bulkhead Carpet', sku='NBC-001', unit_of_measure='sq_ft'),
    ]
    
    all_products = pigments + carpets
    db.session.add_all(all_products)
    db.session.commit()
    print(f'Successfully seeded {len(all_products)} products to Supabase!')
