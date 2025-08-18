from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from models import *
from database import db
from sqlalchemy import func

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return redirect(url_for('auth.login'))

@main_bp.route('/dashboard')
@login_required
def dashboard():
    # Get dashboard statistics based on user role
    stats = {}
    low_stock = [] # Initialize low_stock for all roles

    if current_user.role in [UserRole.SUPERADMIN, UserRole.MANAGER]:
        # Admin users see all requests
        stats = {
            'total_users': User.query.filter_by(is_active=True).count(),
            'total_departments': Department.query.count(),
            'total_items': Item.query.count(),
            'total_locations': Location.query.count(),
            'pending_requests': StockIssueRequest.query.filter_by(status=RequestStatus.PENDING).count(),
            'approved_requests': StockIssueRequest.query.filter_by(status=RequestStatus.APPROVED).count(),
            'total_stock_value': db.session.query(func.sum(StockBalance.quantity)).scalar() or 0,
        }

        # Recent requests (all requests for admin/manager)
        recent_requests = StockIssueRequest.query.order_by(
            StockIssueRequest.created_at.desc()
        ).limit(10).all()

        # Approved requests ready for issue
        approved_requests = StockIssueRequest.query.filter_by(
            status=RequestStatus.APPROVED
        ).order_by(StockIssueRequest.approved_at.desc()).limit(5).all()

        # Get low stock items (items below their threshold)
        low_stock = db.session.query(StockBalance, Item, Location).join(Item).join(Location).filter(
            StockBalance.quantity <= Item.low_stock_threshold
        ).limit(10).all()

    elif current_user.role == UserRole.HOD:
        # HOD dashboard - show department statistics
        dept_id = current_user.managed_department.id if current_user.managed_department else None

        if dept_id:
            stats = {
                'department_users': User.query.filter_by(
                    department_id=dept_id, is_active=True
                ).count(),
                'pending_approvals': StockIssueRequest.query.filter_by(
                    department_id=dept_id, status=RequestStatus.PENDING
                ).count(),
                'approved_requests': StockIssueRequest.query.filter_by(
                    department_id=dept_id, status=RequestStatus.APPROVED
                ).count(),
                'my_requests': StockIssueRequest.query.filter_by(
                    requester_id=current_user.id
                ).count(),
            }

            # Recent requests for this department
            recent_requests = StockIssueRequest.query.filter_by(
                department_id=dept_id
            ).order_by(StockIssueRequest.created_at.desc()).limit(10).all()
        else:
            stats = {}
            recent_requests = []

    else:
        # Employee dashboard - show personal statistics
        stats = {
            'my_requests': StockIssueRequest.query.filter_by(
                requester_id=current_user.id
            ).count(),
            'pending_requests': StockIssueRequest.query.filter_by(
                requester_id=current_user.id, status=RequestStatus.PENDING
            ).count(),
            'approved_requests': StockIssueRequest.query.filter_by(
                requester_id=current_user.id, status=RequestStatus.APPROVED
            ).count(),
        }

        # My recent requests
        recent_requests = StockIssueRequest.query.filter_by(
            requester_id=current_user.id
        ).order_by(StockIssueRequest.created_at.desc()).limit(10).all()

    # Prepare template variables based on role
    template_vars = {
        'stats': stats, 
        'recent_requests': recent_requests, 
        'low_stock': low_stock
    }
    
    # Only pass approved_requests for admin/manager roles
    if current_user.role in [UserRole.SUPERADMIN, UserRole.MANAGER]:
        template_vars['approved_requests'] = approved_requests
    
    return render_template('dashboard.html', **template_vars)

@main_bp.route('/stock_requests/new', methods=['GET', 'POST'])
@login_required
def new_stock_request():
    if request.method == 'POST':
        item_id = request.form.get('item_id')
        quantity = request.form.get('quantity')
        department_id = request.form.get('department_id')
        reason = request.form.get('reason')

        item = Item.query.get(item_id)

        if not item:
            # Handle error: item not found
            return redirect(url_for('main.new_stock_request')) # Or render an error message

        # Determine the initial status
        if current_user.role == UserRole.MANAGER: # Changed from NETWORK_ADMIN to MANAGER
            status = RequestStatus.APPROVED # Auto-approve for Manager
        elif current_user.role == UserRole.HOD:
            status = RequestStatus.PENDING # HOD requests are pending for approval
        else:
            status = RequestStatus.PENDING # Default to pending for other roles

        new_request = StockIssueRequest(
            requester_id=current_user.id,
            item_id=item_id,
            quantity=quantity,
            department_id=department_id,
            reason=reason,
            status=status
        )

        db.session.add(new_request)
        db.session.commit()

        return redirect(url_for('main.dashboard')) # Redirect to dashboard after creation

    # For GET requests, render the form
    items = Item.query.all()
    departments = Department.query.all()
    return render_template('new_stock_request.html', items=items, departments=departments)

@main_bp.route('/stock_requests/<int:req_id>/approve', methods=['POST'])
@login_required
def approve_stock_request(req_id):
    request_item = StockIssueRequest.query.get_or_404(req_id)

    # Only HOD or SuperAdmin can approve requests
    if current_user.role not in [UserRole.HOD, UserRole.SUPERADMIN]:
        flash('You do not have permission to approve requests.', 'danger')
        return redirect(url_for('main.dashboard')) # Or show an error message

    # Check if the request is pending
    if request_item.status == RequestStatus.PENDING:
        request_item.status = RequestStatus.APPROVED
        request_item.approved_at = func.now() # Record approval time
        db.session.commit()
        flash('Stock request approved successfully.', 'success')
    else:
        flash('This request is not pending.', 'info')

    return redirect(url_for('main.dashboard'))

@main_bp.route('/stock_requests/<int:req_id>/reject', methods=['POST'])
@login_required
def reject_stock_request(req_id):
    request_item = StockIssueRequest.query.get_or_404(req_id)

    # Only HOD or SuperAdmin can reject requests
    if current_user.role not in [UserRole.HOD, UserRole.SUPERADMIN]:
        flash('You do not have permission to reject requests.', 'danger')
        return redirect(url_for('main.dashboard')) # Or show an error message

    # Check if the request is pending
    if request_item.status == RequestStatus.PENDING:
        request_item.status = RequestStatus.REJECTED
        request_item.rejected_at = func.now() # Record rejection time
        db.session.commit()
        flash('Stock request rejected successfully.', 'success')
    else:
        flash('This request is not pending.', 'info')

    return redirect(url_for('main.dashboard'))

@main_bp.route('/stock_requests/<int:req_id>/issue', methods=['POST'])
@login_required
def issue_stock_request(req_id):
    request_item = StockIssueRequest.query.get_or_404(req_id)

    # Only Manager or SuperAdmin can issue stock
    if current_user.role not in [UserRole.MANAGER, UserRole.SUPERADMIN]:
        flash('You do not have permission to issue stock.', 'danger')
        return redirect(url_for('main.dashboard'))

    # Check if the request is approved and stock is available
    if request_item.status == RequestStatus.APPROVED:
        stock_balance = StockBalance.query.filter_by(item_id=request_item.item_id, location_id=request_item.department.default_location_id).first()

        if stock_balance and stock_balance.quantity >= request_item.quantity:
            stock_balance.quantity -= request_item.quantity
            request_item.status = RequestStatus.ISSUED
            request_item.issued_at = func.now()
            db.session.commit()
            flash('Stock issued successfully.', 'success')
        else:
            flash('Insufficient stock available or no stock balance entry.', 'warning')
    else:
        flash('This request is not approved for issuing.', 'info')

    return redirect(url_for('main.dashboard'))


@main_bp.route('/stock_balances')
@login_required
def stock_balances():
    balances = StockBalance.query.all()
    return render_template('stock_balances.html', balances=balances)

@main_bp.route('/users')
@login_required
def list_users():
    users = User.query.all()
    return render_template('users.html', users=users)

@main_bp.route('/departments')
@login_required
def list_departments():
    departments = Department.query.all()
    return render_template('departments.html', departments=departments)

@main_bp.route('/items')
@login_required
def list_items():
    items = Item.query.all()
    return render_template('items.html', items=items)

@main_bp.route('/locations')
@login_required
def list_locations():
    locations = Location.query.all()
    return render_template('locations.html', locations=locations)

@main_bp.route('/low_stock_alerts')
@login_required
def low_stock_alerts():
    # Get low stock items (items below their threshold)
    low_stock_items = db.session.query(StockBalance, Item, Location).join(Item).join(Location).filter(
        StockBalance.quantity <= Item.low_stock_threshold
    ).all()
    return render_template('low_stock_alerts.html', low_stock_items=low_stock_items)

@main_bp.route('/api/stock_balance/<int:item_id>/<int:location_id>')
@login_required
def get_stock_balance(item_id, location_id):
    # Check if user has access to this location
    if not current_user.can_access_warehouse(location_id):
        return jsonify({'error': 'Access denied'}), 403
    
    stock_balance = StockBalance.query.filter_by(
        item_id=item_id,
        location_id=location_id
    ).first()
    
    balance = stock_balance.quantity if stock_balance else 0
    return jsonify({'balance': float(balance)})

@main_bp.route('/api/items_by_location/<int:location_id>')
@login_required
def api_items_by_location(location_id):
    # Check if user has access to this warehouse
    if not current_user.can_access_warehouse(location_id):
        return jsonify([])  # Return empty if no access

    # Get items that have stock in this location
    balances = StockBalance.query.filter(
        StockBalance.location_id == location_id,
        StockBalance.quantity > 0
    ).join(Item).all()

    items = []
    for balance in balances:
        items.append({
            'id': balance.item.id,
            'code': balance.item.code,
            'name': balance.item.name,
            'balance': float(balance.quantity)
        })

    return jsonify(items)