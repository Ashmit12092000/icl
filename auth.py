from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from models import User
from database import db

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        remember = bool(request.form.get('remember'))

        if not username or not password:
            flash('Please provide both username and password.', 'error')
            return render_template('login.html')

        user = User.query.filter_by(username=username, is_active=True).first()

        if user and check_password_hash(user.password_hash, password):
            login_user(user, remember=remember)
            next_page = request.args.get('next')
            if next_page:
                return redirect(next_page)
            return redirect(url_for('main.dashboard'))
        else:
            flash('Invalid username or password.', 'error')

    return render_template('login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out successfully.', 'info')
    return redirect(url_for('auth.login'))

@auth_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        if not current_password or not new_password or not confirm_password:
            flash('All fields are required.', 'error')
            return render_template('change_password.html')

        # Verify current password
        if not check_password_hash(current_user.password_hash, current_password):
            flash('Current password is incorrect.', 'error')
            return render_template('change_password.html')

        # Validate new password
        if len(new_password) < 6:
            flash('New password must be at least 6 characters long.', 'error')
            return render_template('change_password.html')

        # Check if new password matches confirmation
        if new_password != confirm_password:
            flash('New password and confirmation do not match.', 'error')
            return render_template('change_password.html')

        # Check if new password is different from current
        if check_password_hash(current_user.password_hash, new_password):
            flash('New password must be different from current password.', 'error')
            return render_template('change_password.html')

        try:
            # Update password
            current_user.password_hash = generate_password_hash(new_password)
            
            # Log audit
            from models import Audit
            Audit.log(
                entity_type='User',
                entity_id=current_user.id,
                action='PASSWORD_CHANGE',
                user_id=current_user.id,
                details=f'User {current_user.username} changed their password'
            )
            
            from database import db
            db.session.commit()
            flash('Password changed successfully.', 'success')
            return redirect(url_for('main.dashboard'))

        except Exception as e:
            from database import db
            db.session.rollback()
            flash('Error changing password. Please try again.', 'error')
            return render_template('change_password.html')

    return render_template('change_password.html')

def role_required(*roles):
    """Decorator to require specific roles"""
    def decorator(f):
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('auth.login'))

            user_role = current_user.role.value if hasattr(current_user.role, 'value') else current_user.role
            if user_role not in roles:
                flash('You do not have permission to access this page.', 'error')
                return redirect(url_for('main.dashboard'))

            return f(*args, **kwargs)
        decorated_function.__name__ = f.__name__
        return decorated_function
    return decorator