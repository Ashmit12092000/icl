import os
import logging
from flask import Flask, render_template, redirect, url_for
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix
from database import db

# Configure logging
logging.basicConfig(level=logging.DEBUG)

migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()

def create_app():
    app = Flask(__name__)

    # Configuration
    app.config.from_object('config.Config')
    app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-key")
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'
    csrf.init_app(app)

    # Import models to ensure they're registered
    from models import User, UserRole, Department, Location, Employee, Item, StockBalance, StockEntry, StockIssueRequest, StockIssueLine, Audit

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Add template filters
    from utils import format_ist_datetime
    
    @app.template_filter('ist_datetime')
    def ist_datetime_filter(dt):
        return format_ist_datetime(dt)
    
    # Register blueprints
    from auth import auth_bp
    from views.main import main_bp
    from views.masters import masters_bp
    from views.stock_entry import stock_entry_bp
    from views.stock_issue import stock_issue_bp
    from views.approvals import approvals_bp
    from views.user_management import user_management_bp
    from views.warehouse_management import warehouse_management_bp
    from views.low_stock import low_stock_bp
    from views.location_inventory import location_inventory_bp
    from views.reports import reports_bp

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(main_bp)
    app.register_blueprint(masters_bp, url_prefix='/masters')
    app.register_blueprint(stock_entry_bp, url_prefix='/stock')
    app.register_blueprint(stock_issue_bp, url_prefix='/requests')
    app.register_blueprint(approvals_bp, url_prefix='/approvals')
    app.register_blueprint(user_management_bp, url_prefix='/admin')
    app.register_blueprint(warehouse_management_bp, url_prefix='/warehouse')
    app.register_blueprint(low_stock_bp, url_prefix='/low-stock')
    app.register_blueprint(location_inventory_bp, url_prefix='/location-inventory')
    app.register_blueprint(reports_bp, url_prefix='/reports')

    # Create tables and create single superadmin demo account
    with app.app_context():
        db.create_all()

        # Create single superadmin demo account if no users exist
        if User.query.count() == 0:
            from werkzeug.security import generate_password_hash
            admin_user = User(
                username='admin',
                password_hash=generate_password_hash('admin123'),
                full_name='System Administrator',
                email='admin@company.com',
                role=UserRole.SUPERADMIN,
                is_active=True
            )
            db.session.add(admin_user)
            db.session.commit()

    @app.errorhandler(404)
    def not_found(error):
        return render_template('404.html'), 404

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        return render_template('500.html'), 500

    return app

# Create the app instance
app = create_app()
