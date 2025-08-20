
from datetime import datetime, timezone
from config import Config

def get_ist_now():
    """Get current datetime in IST"""
    return datetime.now(Config.IST_TIMEZONE)

def convert_to_ist(dt):
    """Convert UTC datetime to IST"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        # Assume UTC if no timezone info
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(Config.IST_TIMEZONE)

def format_ist_datetime(dt):
    """Format datetime in IST for display"""
    if dt is None:
        return ''
    
    # If datetime is naive (no timezone info), assume it's already in IST
    if dt.tzinfo is None:
        # Assume the naive datetime is already in IST
        ist_dt = dt.replace(tzinfo=Config.IST_TIMEZONE)
    else:
        # Convert timezone-aware datetime to IST
        ist_dt = dt.astimezone(Config.IST_TIMEZONE)
    
    return ist_dt.strftime('%Y-%m-%d %H:%M IST')

def datetime_now_ist():
    """Get current datetime in IST - alias for get_ist_now()"""
    return get_ist_now()


from functools import wraps
from flask import abort
from flask_login import current_user

def role_required(*roles):
    """Decorator to require specific roles"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated or current_user.role not in roles:
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def can_edit_master_data():
    """Check if current user can edit master data"""
    return current_user.is_authenticated and current_user.role in ['admin']

def can_approve_requests():
    """Check if current user can approve requests"""
    return current_user.is_authenticated and current_user.role in ['hod', 'approver']

def can_issue_stock():
    """Check if current user can issue stock"""
    return current_user.is_authenticated and current_user.role in ['admin']

def format_currency(amount):
    """Format amount as currency"""
    return f"${amount:,.2f}"

def format_datetime(dt):
    """Format datetime for display in IST"""
    return format_ist_datetime(dt)

def get_status_badge_class(status):
    """Get Bootstrap badge class for status"""
    status_classes = {
        'draft': 'bg-secondary',
        'pending': 'bg-warning',
        'approved': 'bg-success',
        'rejected': 'bg-danger',
        'issued': 'bg-info',
        'conditional_approved': 'bg-primary'
    }
    return status_classes.get(status, 'bg-secondary')
