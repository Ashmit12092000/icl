from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from models import (StockIssueRequest, StockIssueLine, Item, Location,
                   StockBalance, RequestStatus, UserRole, Audit)
from auth import role_required
from database import db
from decimal import Decimal
from datetime import datetime
from utils import get_ist_now
stock_issue_bp = Blueprint('stock_issue', __name__)

@stock_issue_bp.route('/create')
@login_required
def create_request():
    if not current_user.department_id and current_user.role not in [UserRole.SUPERADMIN, UserRole.MANAGER]:
        flash('You must be assigned to a department to create requests.', 'error')
        return redirect(url_for('main.dashboard'))

    from forms import StockIssueRequestForm
    form = StockIssueRequestForm(user=current_user)
    items = Item.query.all()
    # Filter locations based on user's warehouse access
    locations = current_user.get_accessible_warehouses()
    return render_template('stock/request_form.html', form=form, items=items, locations=locations)

@stock_issue_bp.route('/create', methods=['POST'])
@login_required
def submit_request():
    if not current_user.department_id and current_user.role not in [UserRole.SUPERADMIN, UserRole.MANAGER]:
        flash('You must be assigned to a department to create requests.', 'error')
        return redirect(url_for('main.dashboard'))

    location_id = request.form.get('location_id')
    purpose = request.form.get('purpose', '').strip()
    remarks = request.form.get('remarks', '').strip()

    # Validate warehouse access
    if location_id:
        if not current_user.can_access_warehouse(int(location_id)):
            flash('You do not have permission to access this warehouse.', 'error')
            return redirect(url_for('stock_issue.create_request'))

    # Get item data
    item_ids = request.form.getlist('item_id[]')
    quantities = request.form.getlist('quantity[]')
    item_remarks = request.form.getlist('item_remarks[]')

    if not location_id or not purpose:
        flash('Location and purpose are required.', 'error')
        return redirect(url_for('stock_issue.create_request'))

    if not item_ids or not quantities:
        flash('At least one item must be requested.', 'error')
        return redirect(url_for('stock_issue.create_request'))

    # Validate quantities
    valid_items = []
    for i, (item_id, qty) in enumerate(zip(item_ids, quantities)):
        if not item_id or not qty:
            continue
        try:
            qty_decimal = Decimal(qty)
            if qty_decimal <= 0:
                flash(f'Invalid quantity for item {i+1}.', 'error')
                return redirect(url_for('stock_issue.create_request'))
            valid_items.append((int(item_id), qty_decimal, item_remarks[i] if i < len(item_remarks) else ''))
        except (ValueError, TypeError):
            flash(f'Invalid quantity for item {i+1}.', 'error')
            return redirect(url_for('stock_issue.create_request'))

    if not valid_items:
        flash('No valid items found in the request.', 'error')
        return redirect(url_for('stock_issue.create_request'))

    # Validate stock availability for each item
    stock_validation_errors = []
    for item_id, quantity, _ in valid_items:
        stock_balance = StockBalance.query.filter_by(
            item_id=item_id,
            location_id=int(location_id)
        ).first()

        available_qty = stock_balance.quantity if stock_balance else Decimal('0')
        item = Item.query.get(item_id)

        if available_qty <= 0:
            stock_validation_errors.append(f"{item.name} ({item.code}) is out of stock at the selected location.")
        elif available_qty < quantity:
            stock_validation_errors.append(f"{item.name} ({item.code}) has insufficient stock. Available: {available_qty}, Requested: {quantity}")

    if stock_validation_errors:
        for error in stock_validation_errors:
            flash(error, 'error')
        return redirect(url_for('stock_issue.create_request'))

    try:
        # Generate request number first
        today = datetime.utcnow()
        prefix = f"REQ{today.strftime('%Y%m%d')}"

        # Find the last request number for today
        last_request = db.session.query(StockIssueRequest).filter(
            StockIssueRequest.request_no.like(f"{prefix}%")
        ).order_by(StockIssueRequest.request_no.desc()).first()

        if last_request:
            last_seq = int(last_request.request_no[-3:])
            new_seq = last_seq + 1
        else:
            new_seq = 1

        request_no = f"{prefix}{new_seq:03d}"

        # Create the request
        request_obj = StockIssueRequest(
            request_no=request_no,
            requester_id=current_user.id,
            department_id=current_user.department_id or 1,  # Default to first department for admin
            location_id=int(location_id),
            purpose=purpose,
            remarks=remarks if remarks else None
        )

        # Set HOD if department has one
        if request_obj.department and request_obj.department.hod_id:
            request_obj.hod_id = request_obj.department.hod_id

        db.session.add(request_obj)
        db.session.flush()  # Get the ID

        # Add request lines
        for item_id, quantity, item_remark in valid_items:
            line = StockIssueLine(
                request_id=request_obj.id,
                item_id=item_id,
                quantity_requested=quantity,
                remarks=item_remark if item_remark else None
            )
            db.session.add(line)

        # Auto-approve if requester is Manager/Executive or Superadmin
        if current_user.role in [UserRole.MANAGER, UserRole.SUPERADMIN]:
            request_obj.status = RequestStatus.APPROVED
            request_obj.approved_by = current_user.id
            request_obj.approved_at = datetime.utcnow()
        # Original HOD auto-approval logic remains for context, though the new rule overrides it for Managers
        elif (current_user.role == UserRole.HOD and
            current_user.managed_department and
            current_user.managed_department.id == request_obj.department_id):
            request_obj.status = RequestStatus.APPROVED
            request_obj.approved_by = current_user.id
            request_obj.approved_at = datetime.utcnow()

        # Log audit
        Audit.log(
            entity_type='StockIssueRequest',
            entity_id=request_obj.id,
            action='CREATE',
            user_id=current_user.id,
            details=f'Created request {request_obj.request_no}'
        )

        db.session.commit()

        if request_obj.status == RequestStatus.APPROVED:
            flash(f'Request {request_obj.request_no} created and auto-approved.', 'success')
        else:
            flash(f'Request {request_obj.request_no} created successfully.', 'success')

        return redirect(url_for('stock_issue.view_request', request_id=request_obj.id))

    except Exception as e:
        db.session.rollback()
        flash('Error creating request.', 'error')
        return redirect(url_for('stock_issue.create_request'))

@stock_issue_bp.route('/<int:request_id>')
@login_required
def view_request(request_id):
    request_obj = StockIssueRequest.query.get_or_404(request_id)

    # Check access permissions
    if (current_user.role == UserRole.EMPLOYEE and
        request_obj.requester_id != current_user.id):
        flash('You can only view your own requests.', 'error')
        return redirect(url_for('main.dashboard'))

    if (current_user.role == UserRole.HOD and
        request_obj.department_id != current_user.managed_department.id and
        request_obj.requester_id != current_user.id):
        flash('You can only view requests from your department.', 'error')
        return redirect(url_for('main.dashboard'))

    return render_template('stock/request_detail.html', request=request_obj)

@stock_issue_bp.route('/<int:request_id>/submit', methods=['POST'])
@login_required
def submit_for_approval(request_id):
    request_obj = StockIssueRequest.query.get_or_404(request_id)

    # Check permissions
    if request_obj.requester_id != current_user.id:
        flash('You can only submit your own requests.', 'error')
        return redirect(url_for('stock_issue.view_request', request_id=request_id))

    if request_obj.status != RequestStatus.DRAFT:
        flash('Only draft requests can be submitted.', 'error')
        return redirect(url_for('stock_issue.view_request', request_id=request_id))

    request_obj.status = RequestStatus.PENDING

    # Log audit
    Audit.log(
        entity_type='StockIssueRequest',
        entity_id=request_obj.id,
        action='SUBMIT',
        user_id=current_user.id,
        details=f'Submitted request {request_obj.request_no} for approval'
    )

    try:
        db.session.commit()
        flash('Request submitted for approval.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error submitting request.', 'error')

    return redirect(url_for('stock_issue.view_request', request_id=request_id))

@stock_issue_bp.route('/<int:request_id>/issue')
@login_required
@role_required('superadmin', 'manager')
def issue_form(request_id):
    request_obj = StockIssueRequest.query.get_or_404(request_id)

    if request_obj.status != RequestStatus.APPROVED:
        flash('Only approved requests can be issued.', 'error')
        return redirect(url_for('stock_issue.view_request', request_id=request_id))

    # Get stock balances for validation
    stock_balances = {}
    for line in request_obj.issue_lines:
        balance = StockBalance.query.filter_by(
            item_id=line.item_id,
            location_id=request_obj.location_id
        ).first()
        stock_balances[line.item_id] = balance.quantity if balance else 0

    return render_template('stock/issue_form.html',
                         request=request_obj,
                         stock_balances=stock_balances)

@stock_issue_bp.route('/<int:request_id>/issue', methods=['POST'])
@login_required
@role_required('superadmin', 'manager')
def process_issue(request_id):
    request_obj = StockIssueRequest.query.get_or_404(request_id)

    if request_obj.status != RequestStatus.APPROVED:
        flash('Only approved requests can be issued.', 'error')
        return redirect(url_for('stock_issue.view_request', request_id=request_id))

    # Get issued quantities
    line_ids = request.form.getlist('line_id[]')
    issued_quantities = request.form.getlist('quantity_issued[]')

    if not line_ids or not issued_quantities:
        flash('Invalid issue data.', 'error')
        return redirect(url_for('stock_issue.issue_form', request_id=request_id))

    try:
        # Validate and process each line
        for line_id, issued_qty in zip(line_ids, issued_quantities):
            if not line_id or not issued_qty:
                continue

            line = StockIssueLine.query.get(int(line_id))
            if not line or line.request_id != request_id:
                continue

            issued_decimal = Decimal(issued_qty)
            if issued_decimal < 0:
                flash(f'Invalid issued quantity for item {line.item.name}.', 'error')
                return redirect(url_for('stock_issue.issue_form', request_id=request_id))

            if issued_decimal > line.quantity_requested:
                flash(f'Issued quantity cannot exceed requested quantity for {line.item.name}.', 'error')
                return redirect(url_for('stock_issue.issue_form', request_id=request_id))

            # Check stock availability
            stock_balance = StockBalance.query.filter_by(
                item_id=line.item_id,
                location_id=request_obj.location_id
            ).first()

            available_qty = stock_balance.quantity if stock_balance else Decimal('0')
            
            # Prevent issuing if no stock or insufficient stock
            if available_qty <= 0:
                flash(f'{line.item.name} ({line.item.code}) is out of stock at the selected location.', 'error')
                return redirect(url_for('stock_issue.issue_form', request_id=request_id))
            
            if available_qty < issued_decimal:
                flash(f'Insufficient stock for {line.item.name} ({line.item.code}). Available: {available_qty}, Requested: {issued_decimal}', 'error')
                return redirect(url_for('stock_issue.issue_form', request_id=request_id))

            # Only proceed if we have sufficient stock
            if issued_decimal > 0:
                # Update line with issued quantity
                line.quantity_issued = issued_decimal

                # Deduct from stock balance
                stock_balance.quantity -= issued_decimal

        # Final validation: ensure no negative stock balances before committing
        negative_stock_items = []
        for line in request_obj.issue_lines:
            if line.quantity_issued and line.quantity_issued > 0:
                stock_balance = StockBalance.query.filter_by(
                    item_id=line.item_id,
                    location_id=request_obj.location_id
                ).first()
                
                if stock_balance and stock_balance.quantity < 0:
                    negative_stock_items.append(line.item.name)
        
        if negative_stock_items:
            db.session.rollback()
            flash(f'Cannot complete issue: would result in negative stock for {", ".join(negative_stock_items)}', 'error')
            return redirect(url_for('stock_issue.issue_form', request_id=request_id))

        # Update request status
        request_obj.status = RequestStatus.ISSUED
        request_obj.issued_by = current_user.id
        request_obj.issued_at = datetime.utcnow()

        # Log audit
        Audit.log(
            entity_type='StockIssueRequest',
            entity_id=request_obj.id,
            action='ISSUE',
            user_id=current_user.id,
            details=f'Issued stock for request {request_obj.request_no}'
        )

        db.session.commit()
        flash('Stock issued successfully.', 'success')
        return redirect(url_for('stock_issue.view_request', request_id=request_id))

    except Exception as e:
        db.session.rollback()
        flash('Error processing stock issue.', 'error')
        return redirect(url_for('stock_issue.issue_form', request_id=request_id))

@stock_issue_bp.route('/tracker')
@login_required
def request_tracker():
    return render_template('stock/request_tracker.html')

@stock_issue_bp.route('/tracker/search', methods=['POST'])
@login_required
def search_request():
    request_id = request.form.get('request_id', '').strip()

    if not request_id:
        flash('Please enter a request ID.', 'error')
        return redirect(url_for('stock_issue.request_tracker'))

    # Try to find by request number first, then by ID
    request_obj = None

    # Search by request number (REQ20240811001 format)
    if request_id.startswith('REQ'):
        request_obj = StockIssueRequest.query.filter_by(request_no=request_id).first()
    else:
        # Search by numeric ID
        try:
            request_obj = StockIssueRequest.query.get(int(request_id))
        except ValueError:
            pass

    if not request_obj:
        flash(f'Request "{request_id}" not found.', 'error')
        return redirect(url_for('stock_issue.request_tracker'))

    # Check access permissions
    if (current_user.role == UserRole.EMPLOYEE and
        request_obj.requester_id != current_user.id):
        flash('You can only view your own requests.', 'error')
        return redirect(url_for('stock_issue.request_tracker'))

    if (current_user.role == UserRole.HOD and
        request_obj.department_id != current_user.managed_department.id and
        request_obj.requester_id != current_user.id):
        flash('You can only view requests from your department.', 'error')
        return redirect(url_for('stock_issue.request_tracker'))

    return redirect(url_for('stock_issue.view_request', request_id=request_obj.id))

@stock_issue_bp.route('/<int:request_id>/edit')
@login_required
def edit_request(request_id):
    request_obj = StockIssueRequest.query.get_or_404(request_id)

    # Check permissions
    if request_obj.requester_id != current_user.id:
        flash('You can only edit your own requests.', 'error')
        return redirect(url_for('stock_issue.view_request', request_id=request_id))

    if request_obj.status != RequestStatus.DRAFT:
        flash('Only draft requests can be edited.', 'error')
        return redirect(url_for('stock_issue.view_request', request_id=request_id))

    items = Item.query.all()
    locations = current_user.get_accessible_warehouses()
    return render_template('stock/edit_request.html',
                         request=request_obj,
                         items=items,
                         locations=locations)

@stock_issue_bp.route('/<int:request_id>/edit', methods=['POST'])
@login_required
def update_request(request_id):
    request_obj = StockIssueRequest.query.get_or_404(request_id)

    # Check permissions
    if request_obj.requester_id != current_user.id:
        flash('You can only edit your own requests.', 'error')
        return redirect(url_for('stock_issue.view_request', request_id=request_id))

    if request_obj.status != RequestStatus.DRAFT:
        flash('Only draft requests can be edited.', 'error')
        return redirect(url_for('stock_issue.view_request', request_id=request_id))

    location_id = request.form.get('location_id')
    purpose = request.form.get('purpose', '').strip()
    remarks = request.form.get('remarks', '').strip()

    # Validate warehouse access
    if location_id:
        if not current_user.can_access_warehouse(int(location_id)):
            flash('You do not have permission to access this warehouse.', 'error')
            return redirect(url_for('stock_issue.edit_request', request_id=request_id))

    # Get item data
    item_ids = request.form.getlist('item_id[]')
    quantities = request.form.getlist('quantity[]')
    item_remarks = request.form.getlist('item_remarks[]')

    if not location_id or not purpose:
        flash('Location and purpose are required.', 'error')
        return redirect(url_for('stock_issue.edit_request', request_id=request_id))

    if not item_ids or not quantities:
        flash('At least one item must be requested.', 'error')
        return redirect(url_for('stock_issue.edit_request', request_id=request_id))

    # Validate quantities
    valid_items = []
    for i, (item_id, qty) in enumerate(zip(item_ids, quantities)):
        if not item_id or not qty:
            continue
        try:
            qty_decimal = Decimal(qty)
            if qty_decimal <= 0:
                flash(f'Invalid quantity for item {i+1}.', 'error')
                return redirect(url_for('stock_issue.edit_request', request_id=request_id))
            valid_items.append((int(item_id), qty_decimal, item_remarks[i] if i < len(item_remarks) else ''))
        except (ValueError, TypeError):
            flash(f'Invalid quantity for item {i+1}.', 'error')
            return redirect(url_for('stock_issue.edit_request', request_id=request_id))

    if not valid_items:
        flash('No valid items found in the request.', 'error')
        return redirect(url_for('stock_issue.edit_request', request_id=request_id))

    # Validate stock availability for each item
    stock_validation_errors = []
    for item_id, quantity, _ in valid_items:
        stock_balance = StockBalance.query.filter_by(
            item_id=item_id,
            location_id=int(location_id)
        ).first()

        available_qty = stock_balance.quantity if stock_balance else Decimal('0')
        item = Item.query.get(item_id)

        if available_qty <= 0:
            stock_validation_errors.append(f"{item.name} ({item.code}) is out of stock at the selected location.")
        elif available_qty < quantity:
            stock_validation_errors.append(f"{item.name} ({item.code}) has insufficient stock. Available: {available_qty}, Requested: {quantity}")

    if stock_validation_errors:
        for error in stock_validation_errors:
            flash(error, 'error')
        return redirect(url_for('stock_issue.edit_request', request_id=request_id))

    try:
        # Update request details
        request_obj.location_id = int(location_id)
        request_obj.purpose = purpose
        request_obj.remarks = remarks if remarks else None

        # Delete existing lines
        for line in request_obj.issue_lines:
            db.session.delete(line)

        # Add new request lines
        for item_id, quantity, item_remark in valid_items:
            line = StockIssueLine(
                request_id=request_obj.id,
                item_id=item_id,
                quantity_requested=quantity,
                remarks=item_remark if item_remark else None
            )
            db.session.add(line)

        # Log audit
        Audit.log(
            entity_type='StockIssueRequest',
            entity_id=request_obj.id,
            action='UPDATE',
            user_id=current_user.id,
            details=f'Updated request {request_obj.request_no}'
        )

        db.session.commit()
        flash(f'Request {request_obj.request_no} updated successfully.', 'success')
        return redirect(url_for('stock_issue.view_request', request_id=request_obj.id))

    except Exception as e:
        db.session.rollback()
        flash('Error updating request.', 'error')
        return redirect(url_for('stock_issue.edit_request', request_id=request_id))

@stock_issue_bp.route('/<int:request_id>/reject', methods=['POST'])
@login_required
@role_required('superadmin', 'manager')
def reject_approved_request(request_id):
    request_obj = StockIssueRequest.query.get_or_404(request_id)

    if request_obj.status != RequestStatus.APPROVED:
        flash('Only approved requests can be rejected.', 'error')
        return redirect(url_for('main.dashboard'))

    remarks = request.form.get('remarks', '').strip()

    if not remarks:
        flash('Rejection reason is required.', 'error')
        return redirect(url_for('main.dashboard'))

    try:
        request_obj.status = RequestStatus.REJECTED

        if request_obj.remarks:
            request_obj.remarks += f"\n\nRejection by {current_user.full_name}: {remarks}"
        else:
            request_obj.remarks = f"Rejection by {current_user.full_name}: {remarks}"

        # Log audit
        Audit.log(
            entity_type='StockIssueRequest',
            entity_id=request_obj.id,
            action='REJECT',
            user_id=current_user.id,
            details=f'Rejected approved request {request_obj.request_no}: {remarks}'
        )

        db.session.commit()
        flash(f'Request {request_obj.request_no} rejected successfully.', 'success')

    except Exception as e:
        db.session.rollback()
        flash('Error rejecting request.', 'error')

    return redirect(url_for('main.dashboard'))

@stock_issue_bp.route('/<int:request_id>/delete', methods=['POST'])
@login_required
def delete_request(request_id):
    request_obj = StockIssueRequest.query.get_or_404(request_id)

    # Check permissions
    if request_obj.requester_id != current_user.id:
        flash('You can only delete your own requests.', 'error')
        return redirect(url_for('stock_issue.view_request', request_id=request_id))

    if request_obj.status != RequestStatus.DRAFT:
        flash('Only draft requests can be deleted.', 'error')
        return redirect(url_for('stock_issue.view_request', request_id=request_id))

    try:
        request_no = request_obj.request_no

        # Log audit before deleting
        Audit.log(
            entity_type='StockIssueRequest',
            entity_id=request_obj.id,
            action='DELETE',
            user_id=current_user.id,
            details=f'Deleted request {request_no}'
        )

        db.session.delete(request_obj)
        db.session.commit()
        flash(f'Request {request_no} deleted successfully.', 'success')
        return redirect(url_for('stock_issue.my_requests'))

    except Exception as e:
        db.session.rollback()
        flash('Error deleting request.', 'error')
        return redirect(url_for('stock_issue.view_request', request_id=request_id))

@stock_issue_bp.route('/my-requests')
@login_required
def my_requests():
    page = request.args.get('page', 1, type=int)
    requests = StockIssueRequest.query.filter_by(
        requester_id=current_user.id
    ).order_by(StockIssueRequest.created_at.desc()).paginate(
        page=page, per_page=20, error_out=False
    )
    return render_template('stock/my_requests.html', requests=requests)

@stock_issue_bp.route('/<int:request_id>/print')
@login_required
def print_approved_request(request_id):
    request_obj = StockIssueRequest.query.get_or_404(request_id)

    # Check if the request is approved or issued
    if request_obj.status not in [RequestStatus.APPROVED, RequestStatus.ISSUED]:
        flash('Only approved or issued requests can be printed.', 'error')
        return redirect(url_for('stock_issue.view_request', request_id=request_id))

    # Check access permissions (e.g., only requester or manager can print)
    if (current_user.role == UserRole.EMPLOYEE and
        request_obj.requester_id != current_user.id):
        flash('You are not authorized to print this request.', 'error')
        return redirect(url_for('stock_issue.view_request', request_id=request_id))

    if (current_user.role == UserRole.HOD and
        request_obj.department_id != current_user.managed_department.id and
        request_obj.requester_id != current_user.id):
        flash('You are not authorized to print this request.', 'error')
        return redirect(url_for('stock_issue.view_request', request_id=request_id))

    # Render a separate template for printing
    from datetime import datetime
    return render_template('stock/request_print.html', request=request_obj, current_time=datetime.utcnow())
