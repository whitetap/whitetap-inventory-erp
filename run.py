import sys
sys.path.insert(0, 'aviation_erp')
from app_fixed_final import app
if __name__ == '__main__':
    app.run(debug=True, port=5005)

