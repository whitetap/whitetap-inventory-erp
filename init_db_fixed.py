from app_fixed import app, db

with app.app_context():
    db.create_all()
    print("✅ Supabase/PostgreSQL/SQLite tables created!")
    print("Run seed_fixed.py next.")

