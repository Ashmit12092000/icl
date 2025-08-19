import os
from datetime import timezone, timedelta

class Config:
    SECRET_KEY = os.environ.get('SESSION_SECRET', 'dev-secret-key')
    SQLALCHEMY_DATABASE_URI = 'sqlite:///stock_management.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # IST timezone (UTC+5:30)
    IST_TIMEZONE = timezone(timedelta(hours=5, minutes=30))
