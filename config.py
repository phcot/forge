import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-change-me')
    APP_PIN = os.environ.get('APP_PIN', '1234')
    ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    DATABASE_URL = os.environ.get('DATABASE_URL', 'sqlite:///forge.db')
    # Railway gives postgres:// but SQLAlchemy needs postgresql://
    if DATABASE_URL.startswith('postgres://'):
        DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
    SQLALCHEMY_DATABASE_URI = DATABASE_URL
