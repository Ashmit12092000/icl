import os
import logging
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from sqlalchemy.orm import DeclarativeBase
from werkzeug.middleware.proxy_fix import ProxyFix

# Set up logging
logging.basicConfig(level=logging.DEBUG)

class Base(DeclarativeBase):
    pass

db = SQLAlchemy(model_class=Base)
login_manager = LoginManager()

# create the app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-key-change-in-production")
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)  # needed for url_for to generate with https

# configure the database - SQLite only
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///loan_management.db"
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 300,
    "pool_pre_ping": True,
}

# initialize the app with the extension, flask-sqlalchemy >= 3.0.x
db.init_app(app)

# Initialize Flask-Login
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'

@login_manager.user_loader
def load_user(user_id):
    from models import User
    return User.query.get(int(user_id))

# Template filters for handling NaN issues
@app.template_filter('safe_decimal')
def safe_decimal_filter(value):
    """Convert Decimal/None values to safe JavaScript numbers"""
    if value is None:
        return 0.0
    try:
        from decimal import Decimal
        if isinstance(value, Decimal):
            return float(value)
        return float(value) if value else 0.0
    except (ValueError, TypeError):
        return 0.0

@app.template_filter('safe_currency')
def safe_currency_filter(value):
    """Format currency values safely"""
    if value is None:
        return "₹0.00"
    try:
        from decimal import Decimal
        if isinstance(value, Decimal):
            return f"₹{float(value):,.2f}"
        return f"₹{float(value):,.2f}" if value else "₹0.00"
    except (ValueError, TypeError):
        return "₹0.00"

@app.template_filter('safe_percentage')
def safe_percentage_filter(value):
    """Format percentage values safely"""
    if value is None:
        return "0.00%"
    try:
        from decimal import Decimal
        if isinstance(value, Decimal):
            return f"{float(value):.2f}%"
        return f"{float(value):.2f}%" if value else "0.00%"
    except (ValueError, TypeError):
        return "0.00%"

@app.template_filter('safe_number')
def safe_number_filter(value):
    """Format numbers safely for display"""
    if value is None:
        return "0"
    try:
        from decimal import Decimal
        if isinstance(value, Decimal):
            return f"{float(value):,.2f}"
        return f"{float(value):,.2f}" if value else "0"
    except (ValueError, TypeError):
        return "0"

with app.app_context():
    # Make sure to import the models here or their tables won't be created
    import models  # noqa: F401
    import routes  # noqa: F401
    
    db.create_all()
    
    # Create default users if they don't exist
    from models import User
    from werkzeug.security import generate_password_hash
    
    # Create admin user
    admin_user = User.query.filter_by(username='admin').first()
    if not admin_user:
        admin_user = User(
            username='admin',
            email='admin@example.com',
            password_hash=generate_password_hash('admin123'),
            role='admin'
        )
        db.session.add(admin_user)
    
    # Create data entry user
    data_entry_user = User.query.filter_by(username='dataentry').first()
    if not data_entry_user:
        data_entry_user = User(
            username='dataentry',
            email='dataentry@example.com',
            password_hash=generate_password_hash('dataentry123'),
            role='data_entry'
        )
        db.session.add(data_entry_user)
    
    # Create normal user
    normal_user = User.query.filter_by(username='user').first()
    if not normal_user:
        normal_user = User(
            username='user',
            email='user@example.com',
            password_hash=generate_password_hash('user123'),
            role='normal_user'
        )
        db.session.add(normal_user)
    
    try:
        db.session.commit()
        print("Default users created/verified successfully")
    except Exception as e:
        db.session.rollback()
        print(f"Error creating default users: {e}")
