from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from models import Item, Location, StockEntry, StockBalance, Audit, StockIssueLine, StockIssueRequest
from forms import StockEntryForm
from database import db
from auth import role_required
from decimal import Decimal
from datetime import datetime
from utils import get_ist_now

stock_entry_bp = Blueprint('stock_entry', __name__)

@stock_entry_bp.route('/entry')
@login_required
def entry_form():
    # Check if user has permission
    if current_user.role.value not in ['superadmin', 'manager','hod'] and not (current_user.role.value == 'hod' and current_user.managed_department):
        flash('You do not have permission to create stock entries.', 'error')
        return redirect(url_for('main.dashboard'))

    # Filter items based on user's department for HODs
    if current_user.role.value == 'hod' and current_user.managed_department:
        items = Item.query.filter(
            db.or_(Item.department_id == current_user.managed_department.id, Item.department_id.is_(None))
        ).all()
    else:
        items = Item.query.all()

    locations = Location.query.all()

    # Get pre-selected values from URL parameters
    selected_item_id = request.args.get('item_id')
    selected_location_id = request.args.get('location_id')

    return render_template('stock/entry.html',
                         items=items,
                         locations=locations,
                         selected_item_id=selected_item_id,
                         selected_location_id=selected_location_id)

@stock_entry_bp.route('/entry/create', methods=['POST'])
@login_required
def create_entry():
    # Check if user has permission
    if current_user.role.value not in ['superadmin', 'manager','hod'] and not (current_user.role.value == 'hod' and current_user.managed_department):
        flash('You do not have permission to create stock entries.', 'error')
        return redirect(url_for('main.dashboard'))
    item_id = request.form.get('item_id')
    location_id = request.form.get('location_id')
    quantity = request.form.get('quantity')
    description = request.form.get('description', '').strip()
    remarks = request.form.get('remarks', '').strip()

    if not item_id or not location_id or not quantity:
        flash('Item, location, and quantity are required.', 'error')
        return redirect(url_for('stock_entry.entry_form'))

    try:
        quantity = Decimal(quantity)
        if quantity <= 0:
            flash('Quantity must be greater than zero.', 'error')
            return redirect(url_for('stock_entry.entry_form'))
    except (ValueError, TypeError):
        flash('Invalid quantity value.', 'error')
        return redirect(url_for('stock_entry.entry_form'))

    # Create stock entry
    stock_entry = StockEntry(
        item_id=int(item_id),
        location_id=int(location_id),
        quantity_procured=quantity,
        description=description if description else None,
        remarks=remarks if remarks else None,
        created_by=current_user.id,
        created_at=get_ist_now()
    )

    try:
        db.session.add(stock_entry)

        # Update or create stock balance
        stock_balance = StockBalance.query.filter_by(
            item_id=int(item_id),
            location_id=int(location_id)
        ).first()

        if stock_balance:
            stock_balance.quantity += quantity
        else:
            stock_balance = StockBalance(
                item_id=int(item_id),
                location_id=int(location_id),
                quantity=quantity
            )
            db.session.add(stock_balance)

        # Log audit
        Audit.log(
            entity_type='StockEntry',
            entity_id=stock_entry.id,
            action='CREATE',
            user_id=current_user.id,
            details=f'Added {quantity} units to stock'
        )

        db.session.commit()
        flash('Stock entry created successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error creating stock entry.', 'error')

    return redirect(url_for('stock_entry.entry_form'))

@stock_entry_bp.route('/balances')
@login_required
def balances():
    location_id = request.args.get('location_id')
    item_id = request.args.get('item_id')

    query = db.session.query(StockBalance).join(Item).join(Location)

    # Filter by user department for HOD and Employee users
    if current_user.role.value == 'hod':
        # HOD can see items from their managed department or items without department
        if current_user.managed_department:
            query = query.filter(
                db.or_(Item.department_id == current_user.managed_department.id, Item.department_id.is_(None))
            )
        else:
            # If HOD has no managed department, show nothing
            query = query.filter(Item.department_id == -1)
    elif current_user.role.value == 'employee':
        # Employee can only see items from their department or items without department
        if current_user.department_id:
            query = query.filter(
                db.or_(Item.department_id == current_user.department_id, Item.department_id.is_(None))
            )
        else:
            # If employee has no department, show nothing
            query = query.filter(Item.department_id == -1)

    if location_id:
        query = query.filter(StockBalance.location_id == location_id)

    if item_id:
        query = query.filter(StockBalance.item_id == item_id)

    # Show all balances including zero quantities
    balances = query.all()

    locations = Location.query.all()

    # Filter items based on user's department for dropdown
    if current_user.role.value == 'hod':
        if current_user.managed_department:
            items = Item.query.filter(
                db.or_(Item.department_id == current_user.managed_department.id, Item.department_id.is_(None))
            ).all()
        else:
            items = []
    elif current_user.role.value == 'employee':
        if current_user.department_id:
            items = Item.query.filter(
                db.or_(Item.department_id == current_user.department_id, Item.department_id.is_(None))
            ).all()
        else:
            items = []
    else:
        # Superadmin and Manager can see all items
        items = Item.query.all()

    return render_template('stock/balances.html',
                         balances=balances,
                         locations=locations,
                         items=items,
                         selected_location=location_id,
                         selected_item=item_id)

@stock_entry_bp.route('/entries')
@login_required
@role_required('superadmin','hod')
def entries():
    page = request.args.get('page', 1, type=int)
    entries = StockEntry.query.order_by(
        StockEntry.created_at.desc()
    ).paginate(
        page=page, per_page=20, error_out=False
    )
    return render_template('stock/entries.html', entries=entries)

@stock_entry_bp.route('/history/<int:item_id>/<int:location_id>')
@login_required
def stock_history(item_id, location_id):
    # Check if user has permission to view this location
    if not current_user.can_access_warehouse(location_id):
        flash('You do not have permission to access this warehouse.', 'error')
        return redirect(url_for('stock_entry.balances'))

    item = Item.query.get_or_404(item_id)
    location = Location.query.get_or_404(location_id)

    # Check department access for HOD and Employee users
    if current_user.role.value == 'hod':
        if current_user.managed_department:
            if item.department_id and item.department_id != current_user.managed_department.id:
                flash('You can only view items from your department.', 'error')
                return redirect(url_for('stock_entry.balances'))
        else:
            flash('You do not have permission to view this item.', 'error')
            return redirect(url_for('stock_entry.balances'))
    elif current_user.role.value == 'employee':
        if current_user.department_id:
            if item.department_id and item.department_id != current_user.department_id:
                flash('You can only view items from your department.', 'error')
                return redirect(url_for('stock_entry.balances'))
        else:
            flash('You do not have permission to view this item.', 'error')
            return redirect(url_for('stock_entry.balances'))

    # Get stock entries (additions)
    stock_entries = StockEntry.query.filter_by(
        item_id=item_id,
        location_id=location_id
    ).order_by(StockEntry.created_at.desc()).all()

    # Get stock issues (deductions) - from StockIssueLine joined with StockIssueRequest
    stock_issues = db.session.query(StockIssueLine, StockIssueRequest).join(
        StockIssueRequest, StockIssueLine.request_id == StockIssueRequest.id
    ).filter(
        StockIssueLine.item_id == item_id,
        StockIssueRequest.location_id == location_id,
        StockIssueRequest.status == 'Issued',
        StockIssueLine.quantity_issued.isnot(None)
    ).order_by(StockIssueRequest.issued_at.desc()).all()

    # Get current stock balance
    current_balance = StockBalance.query.filter_by(
        item_id=item_id,
        location_id=location_id
    ).first()

    return render_template('stock/history.html',
                         item=item,
                         location=location,
                         stock_entries=stock_entries,
                         stock_issues=stock_issues,
                         current_balance=current_balance)

@stock_entry_bp.route('/api/stock-balance/<int:item_id>/<int:location_id>')
@login_required
def get_stock_balance(item_id, location_id):
    """API endpoint to get stock balance for an item at a location"""
    try:
        # Check if user has access to this location
        if not current_user.can_access_warehouse(location_id):
            return jsonify({'error': 'Access denied'}), 403

        stock_balance = StockBalance.query.filter_by(
            item_id=item_id,
            location_id=location_id
        ).first()

        balance = float(stock_balance.quantity) if stock_balance else 0.0

        return jsonify({
            'balance': balance,
            'item_id': item_id,
            'location_id': location_id
        })

    except Exception as e:
        return jsonify({'error': 'Failed to fetch stock balance'}), 500