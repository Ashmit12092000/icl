from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, abort
from flask_login import login_required, current_user
from models import StockReturn, StockIssueLine, StockIssueRequest, Item, Location, StockBalance, ReturnStatus, RequestStatus, Audit, UserRole
from database import db
from decimal import Decimal
from utils import get_ist_now
from auth import role_required
from datetime import datetime, timedelta

stock_return_bp = Blueprint('stock_return', __name__)

@stock_return_bp.route('/create')
@login_required
def create_return():
    """Show form to create a new stock return"""
    # Get issued requests for current user or all if superadmin
    if current_user.role == UserRole.SUPERADMIN:
        issued_requests = StockIssueRequest.query.filter_by(
            status=RequestStatus.ISSUED
        ).order_by(StockIssueRequest.issued_at.desc()).all()
    else:
        issued_requests = StockIssueRequest.query.filter_by(
            requester_id=current_user.id,
            status=RequestStatus.ISSUED
        ).order_by(StockIssueRequest.issued_at.desc()).all()

    # Filter out requests that have returnable items and calculate days since issue
    returnable_requests = []
    current_time = get_ist_now()
    for request in issued_requests:
        returnable_lines = [line for line in request.issue_lines if line.is_returnable]
        if returnable_lines:
            # Calculate days since issue in IST
            if request.issued_at:
                # Convert issued_at to IST and calculate difference
                from utils import convert_to_ist
                issued_at_ist = convert_to_ist(request.issued_at)
                days_diff = (current_time - issued_at_ist).days
                request.days_since_issue = days_diff
            else:
                request.days_since_issue = 0
            returnable_requests.append(request)

    return render_template('stock/return_form.html', issued_requests=returnable_requests)

@stock_return_bp.route('/select-issue', methods=['POST'])
@login_required
def select_issue():
    """Select which issued stock request to return items from"""

    # Handle both GET (from audit links) and POST (from form)
    if request.method == 'GET':
        request_id = request.args.get('request_id', type=int)
    else:
        request_id = request.form.get('request_id', type=int)

    if not request_id:
        flash('Please select a stock issue request.', 'error')
        return redirect(url_for('stock_return.create_return'))

    stock_request = StockIssueRequest.query.get_or_404(request_id)

    # Check if user can return this stock (only original requester or superadmin)
    if (current_user.role != UserRole.SUPERADMIN and
        stock_request.requester_id != current_user.id):
        flash('You can only return stock that was originally requested by you.', 'error')
        return redirect(url_for('stock_return.create_return'))

    # Check if request is issued
    if stock_request.status != RequestStatus.ISSUED:
        flash('Stock can only be returned from issued requests.', 'error')
        return redirect(url_for('stock_return.create_return'))

    # Get returnable items
    returnable_lines = [line for line in stock_request.issue_lines if line.is_returnable]

    if not returnable_lines:
        flash('No items are available for return from this request.', 'warning')
        return redirect(url_for('stock_return.create_return'))

    # Determine if this was accessed directly (GET) or through form (POST)
    from_direct = request.method == 'GET'

    return render_template('stock/return_items.html',
                         request=stock_request,
                         returnable_lines=returnable_lines,
                         from_direct=from_direct)

@stock_return_bp.route('/search-issue', methods=['POST'])
@login_required
def search_issue():
    """Search for stock issue by request number or ID"""
    search_term = request.form.get('search_term', '').strip()

    if not search_term:
        flash('Please enter a request number or ID.', 'error')
        return redirect(url_for('stock_return.create_return'))

    # Search by request number first, then by ID
    stock_request = None
    if search_term.startswith('REQ'):
        stock_request = StockIssueRequest.query.filter_by(request_no=search_term).first()
    else:
        try:
            stock_request = StockIssueRequest.query.get(int(search_term))
        except ValueError:
            pass

    if not stock_request:
        flash(f'Stock issue request "{search_term}" not found.', 'error')
        return redirect(url_for('stock_return.create_return'))

    # Check if user can return this stock (only original requester or superadmin)
    if (current_user.role != UserRole.SUPERADMIN and
        stock_request.requester_id != current_user.id):
        flash('You can only return stock that was originally requested by you.', 'error')
        return redirect(url_for('stock_return.create_return'))

    # Check if request is issued
    if stock_request.status != RequestStatus.ISSUED:
        flash('Stock can only be returned from issued requests.', 'error')
        return redirect(url_for('stock_return.create_return'))

    # Get returnable items
    returnable_lines = [line for line in stock_request.issue_lines if line.is_returnable]

    if not returnable_lines:
        flash('No items are available for return from this request.', 'warning')
        return redirect(url_for('stock_return.create_return'))

    return render_template('stock/return_items.html',
                         request=stock_request,
                         returnable_lines=returnable_lines)

@stock_return_bp.route('/submit', methods=['POST'])
@login_required
def submit_return():
    """Submit stock return request"""
    request_id = request.form.get('request_id')
    line_ids = request.form.getlist('line_id[]')
    quantities = request.form.getlist('quantity[]')
    return_reason = request.form.get('return_reason', '').strip()

    if not request_id or not line_ids or not quantities or not return_reason:
        flash('All fields are required.', 'error')
        return redirect(url_for('stock_return.create_return'))

    stock_request = StockIssueRequest.query.get_or_404(request_id)

    # Check permissions
    if (current_user.role != UserRole.SUPERADMIN and
        stock_request.requester_id != current_user.id):
        flash('You can only return stock that was originally requested by you.', 'error')
        return redirect(url_for('stock_return.create_return'))

    # Validate return items
    valid_returns = []
    for line_id, quantity in zip(line_ids, quantities):
        if not line_id or not quantity:
            continue

        try:
            quantity_decimal = Decimal(quantity)
            if quantity_decimal <= 0:
                continue

            issue_line = StockIssueLine.query.get(int(line_id))
            if not issue_line or issue_line.request_id != int(request_id):
                continue

            if not issue_line.is_returnable:
                flash(f'Item {issue_line.item.name} is not returnable (either overdue or no quantity available).', 'error')
                return redirect(url_for('stock_return.create_return'))

            if quantity_decimal > issue_line.quantity_returnable:
                flash(f'Cannot return {quantity_decimal} of {issue_line.item.name}. Maximum returnable: {issue_line.quantity_returnable}', 'error')
                return redirect(url_for('stock_return.create_return'))

            valid_returns.append((issue_line, quantity_decimal))

        except (ValueError, TypeError):
            continue

    if not valid_returns:
        flash('No valid items found for return.', 'error')
        return redirect(url_for('stock_return.create_return'))

    try:
        # Create return records
        return_records = []
        for issue_line, quantity in valid_returns:
            # Generate return number
            today = datetime.utcnow()
            prefix = f"RET{today.strftime('%Y%m%d')}"

            last_return = db.session.query(StockReturn).filter(
                StockReturn.return_no.like(f"{prefix}%")
            ).order_by(StockReturn.return_no.desc()).first()

            if last_return:
                last_seq = int(last_return.return_no[-3:])
                new_seq = last_seq + 1
            else:
                new_seq = 1

            return_no = f"{prefix}{new_seq:03d}"

            stock_return = StockReturn(
                return_no=return_no,
                issue_line_id=issue_line.id,
                returned_by=current_user.id,
                quantity_returned=quantity,
                return_reason=return_reason,
                status=ReturnStatus.PENDING
            )

            db.session.add(stock_return)
            return_records.append(stock_return)

        db.session.flush()  # Get IDs

        # Auto-process if user is superadmin
        if current_user.role == UserRole.SUPERADMIN:
            for stock_return in return_records:
                stock_return.status = ReturnStatus.COMPLETED
                stock_return.processed_by = current_user.id
                stock_return.processed_at = datetime.utcnow()

                # Update stock balance
                stock_balance = StockBalance.query.filter_by(
                    item_id=stock_return.issue_line.item_id,
                    location_id=stock_return.issue_line.request.location_id
                ).first()

                if stock_balance:
                    stock_balance.quantity += stock_return.quantity_returned
                else:
                    stock_balance = StockBalance(
                        item_id=stock_return.issue_line.item_id,
                        location_id=stock_return.issue_line.request.location_id,
                        quantity=stock_return.quantity_returned
                    )
                    db.session.add(stock_balance)

        # Log audit
        for stock_return in return_records:
            Audit.log(
                entity_type='StockReturn',
                entity_id=stock_return.id,
                action='CREATE',
                user_id=current_user.id,
                details=f'Created return {stock_return.return_no} for {stock_return.quantity_returned} units'
            )

        db.session.commit()

        if current_user.role == UserRole.SUPERADMIN:
            flash(f'{len(return_records)} return(s) created and auto-processed.', 'success')
        else:
            flash(f'{len(return_records)} return(s) created and submitted for processing.', 'success')

        return redirect(url_for('stock_return.my_returns'))

    except Exception as e:
        db.session.rollback()
        flash('Error creating return request.', 'error')
        return redirect(url_for('stock_return.create_return'))

@stock_return_bp.route('/my-returns')
@login_required
def my_returns():
    """Show user's return requests"""
    page = request.args.get('page', 1, type=int)
    returns = StockReturn.query.filter_by(
        returned_by=current_user.id
    ).order_by(StockReturn.created_at.desc()).paginate(
        page=page, per_page=20, error_out=False
    )
    return render_template('stock/my_returns.html', returns=returns)

@stock_return_bp.route('/<int:return_id>')
@login_required
def view_return(return_id):
    """View return details"""
    stock_return = StockReturn.query.get_or_404(return_id)

    # Check access permissions
    if (current_user.role != UserRole.SUPERADMIN and
        stock_return.returned_by != current_user.id):
        flash('You can only view your own returns.', 'error')
        return redirect(url_for('stock_return.my_returns'))

    return render_template('stock/return_detail.html', stock_return=stock_return)

@stock_return_bp.route('/pending')
@login_required
@role_required('superadmin','hod')
def pending_returns():
    """Show pending returns for processing"""
    page = request.args.get('page', 1, type=int)
    returns = StockReturn.query.filter_by(
        status=ReturnStatus.PENDING
    ).order_by(StockReturn.created_at.desc()).paginate(
        page=page, per_page=20, error_out=False
    )
    return render_template('stock/pending_returns.html', returns=returns)

@stock_return_bp.route('/<int:return_id>/process', methods=['POST'])
@login_required
@role_required('superadmin','hod')
def process_return(return_id):
    """Process (approve/reject) a return request"""
    stock_return = StockReturn.query.get_or_404(return_id)

    if stock_return.status != ReturnStatus.PENDING:
        flash('Only pending returns can be processed.', 'error')
        return redirect(url_for('stock_return.pending_returns'))

    action = request.form.get('action')
    remarks = request.form.get('remarks', '').strip()

    try:
        if action == 'approve':
            stock_return.status = ReturnStatus.COMPLETED
            stock_return.processed_by = current_user.id
            stock_return.processed_at = datetime.utcnow()
            stock_return.remarks = remarks

            # Update stock balance
            stock_balance = StockBalance.query.filter_by(
                item_id=stock_return.issue_line.item_id,
                location_id=stock_return.issue_line.request.location_id
            ).first()

            if stock_balance:
                stock_balance.quantity += stock_return.quantity_returned
            else:
                stock_balance = StockBalance(
                    item_id=stock_return.issue_line.item_id,
                    location_id=stock_return.issue_line.request.location_id,
                    quantity=stock_return.quantity_returned
                )
                db.session.add(stock_balance)

            # Log audit
            Audit.log(
                entity_type='StockReturn',
                entity_id=stock_return.id,
                action='APPROVE',
                user_id=current_user.id,
                details=f'Approved return {stock_return.return_no}'
            )

            flash(f'Return {stock_return.return_no} approved successfully.', 'success')

        elif action == 'reject':
            if not remarks:
                flash('Rejection reason is required.', 'error')
                return redirect(url_for('stock_return.pending_returns'))

            stock_return.status = ReturnStatus.REJECTED
            stock_return.processed_by = current_user.id
            stock_return.processed_at = datetime.utcnow()
            stock_return.remarks = remarks

            # Log audit
            Audit.log(
                entity_type='StockReturn',
                entity_id=stock_return.id,
                action='REJECT',
                user_id=current_user.id,
                details=f'Rejected return {stock_return.return_no}: {remarks}'
            )

            flash(f'Return {stock_return.return_no} rejected.', 'success')

        db.session.commit()

    except Exception as e:
        db.session.rollback()
        flash('Error processing return.', 'error')

    return redirect(url_for('stock_return.pending_returns'))

@stock_return_bp.route('/history')
@login_required
@role_required('superadmin','hod')
def return_history():
    """Show all returns history"""
    page = request.args.get('page', 1, type=int)
    status_filter = request.form.get('status')

    query = StockReturn.query
    if status_filter:
        query = query.filter_by(status=status_filter)

    returns = query.order_by(StockReturn.created_at.desc()).paginate(
        page=page, per_page=20, error_out=False
    )

    return render_template('stock/return_history.html', returns=returns)