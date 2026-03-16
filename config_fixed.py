import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-me'
    db_path = os.path.join(os.getcwd(), 'aviation_erp.db')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or f'sqlite:///{db_path.replace('\\\\', '/').replace(chr(92), '/')}'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

