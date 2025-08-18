from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from database import db
from models import (Item, User, Department, Employee, Location, StockEntry,
                   StockIssueRequest, StockIssueItem, StockBalance, AuditLog,
                   get_stock_balance, update_stock_balance)
from forms import (ItemForm, DepartmentForm, EmployeeForm, LocationForm,
                  StockEntryForm, StockIssueRequestForm, StockIssueItemForm, ApprovalForm)
from datetime import datetime
import json
from sqlalchemy import or_, and_
from sqlalchemy import func

main_bp = Blueprint('main', __name__)

def log_audit(table_name, record_id, action, old_values=None, new_values=None):
    """Helper function to log audit trail"""
    if current_user.is_authenticated:
        audit = AuditLog(
            table_name=table_name,
            record_id=record_id,
            action=action,
            old_values=json.dumps(old_values) if old_values else None,
            new_values=json.dumps(new_values) if new_values else None,
            user_id=current_user.id
        )
        db.session.add(audit)

@main_bp.route('/')
@login_required
def dashboard():
    # Get current user's department context
    user_employee = Employee.query.filter_by(user_id=current_user.id).first()
    user_department = user_employee.department if user_employee else None

    # Get summary statistics based on department access
    total_items = Item.query.filter_by(is_active=True).count()
    total_locations = Location.query.filter_by(is_active=True).count()

    if current_user.role == 'admin':
        # Admin sees all pending requests
        pending_requests = StockIssueRequest.query.filter_by(status='pending').count()
        recent_entries = StockEntry.query.order_by(StockEntry.created_at.desc()).limit(5).all()
        recent_requests = StockIssueRequest.query.order_by(StockIssueRequest.created_at.desc()).limit(5).all()
    elif current_user.role == 'hod' and user_department:
        # HOD sees pending requests from their department
        pending_requests = StockIssueRequest.query.filter_by(
            department_id=user_department.id,
            status='pending'
        ).count()
        recent_entries = StockEntry.query.order_by(StockEntry.created_at.desc()).limit(5).all()
        recent_requests = StockIssueRequest.query.filter_by(
            department_id=user_department.id
        ).order_by(StockIssueRequest.created_at.desc()).limit(5).all()
    else:
        # Regular employees see only their requests
        pending_requests = StockIssueRequest.query.filter_by(
            created_by=current_user.id,
            status='pending'
        ).count()
        recent_entries = StockEntry.query.order_by(StockEntry.created_at.desc()).limit(5).all()
        recent_requests = StockIssueRequest.query.filter_by(
            created_by=current_user.id
        ).order_by(StockIssueRequest.created_at.desc()).limit(5).all()

    # Get low stock items (items with balance <= 5)
    low_stock = db.session.query(StockBalance, Item, Location).join(Item).join(Location).filter(StockBalance.balance <= 5).all()

    # Calculate additional metrics for progress bars
    total_stock_value = db.session.query(func.sum(StockBalance.balance)).scalar() or 0
    active_departments = Department.query.filter_by(is_active=True).count()
    total_users = User.query.filter_by(is_active=True).count()

    # Calculate progress percentages
    items_progress = min((total_items / 100) * 100, 100) if total_items > 0 else 2
    locations_progress = min((total_locations / 50) * 100, 100) if total_locations > 0 else 2
    pending_progress = min((pending_requests / 20) * 100, 100) if pending_requests > 0 else 2
    low_stock_progress = min((len(low_stock) / 15) * 100, 100) if low_stock else 1

    return render_template('dashboard.html',
                         total_items=total_items,
                         total_locations=total_locations,
                         pending_requests=pending_requests,
                         recent_entries=recent_entries,
                         recent_requests=recent_requests,
                         low_stock=low_stock,
                         user_department=user_department,
                         items_progress=items_progress,
                         locations_progress=locations_progress,
                         pending_progress=pending_progress,
                         low_stock_progress=low_stock_progress,
                         total_stock_value=total_stock_value,
                         active_departments=active_departments,
                         total_users=total_users)

# Item Master Routes
@main_bp.route('/masters/items')
@login_required
def items():
    if current_user.role not in ['admin']:
        flash('You do not have permission to view items master.', 'error')
        return redirect(url_for('main.dashboard'))

    search = request.args.get('search', '')
    items = Item.query.filter_by(is_active=True)
    if search:
        items = items.filter(or_(Item.code.contains(search), Item.name.contains(search)))
    items = items.all()
    return render_template('masters/items.html', items=items, search=search)

@main_bp.route('/masters/items/add', methods=['GET', 'POST'])
@login_required
def add_item():
    if current_user.role not in ['admin']:
        flash('You do not have permission to add items.', 'error')
        return redirect(url_for('main.items'))

    form = ItemForm()
    if form.validate_on_submit():
        # Check for duplicate code
        existing = Item.query.filter_by(code=form.code.data).first()
        if existing:
            flash('Item code already exists.', 'error')
        else:
            item = Item(
                code=form.code.data,
                name=form.name.data,
                make=form.make.data,
                variant=form.variant.data,
                description=form.description.data
            )
            db.session.add(item)
            db.session.commit()
            log_audit('item', item.id, 'CREATE', new_values=form.data)
            flash('Item added successfully.', 'success')
            return redirect(url_for('main.items'))

    return render_template('masters/items.html', form=form, mode='add')

@main_bp.route('/masters/items/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_item(id):
    if current_user.role not in ['admin']:
        flash('You do not have permission to edit items.', 'error')
        return redirect(url_for('main.items'))

    item = Item.query.get_or_404(id)
    form = ItemForm(obj=item)

    if form.validate_on_submit():
        # Check for duplicate code (excluding current item)
        existing = Item.query.filter(Item.code == form.code.data, Item.id != id).first()
        if existing:
            flash('Item code already exists.', 'error')
        else:
            old_values = {
                'code': item.code,
                'name': item.name,
                'make': item.make,
                'variant': item.variant,
                'description': item.description
            }

            item.code = form.code.data
            item.name = form.name.data
            item.make = form.make.data
            item.variant = form.variant.data
            item.description = form.description.data

            db.session.commit()
            log_audit('item', item.id, 'UPDATE', old_values=old_values, new_values=form.data)
            flash('Item updated successfully.', 'success')
            return redirect(url_for('main.items'))

    return render_template('masters/items.html', form=form, item=item, mode='edit')

@main_bp.route('/masters/items/delete/<int:id>')
@login_required
def delete_item(id):
    if current_user.role not in ['admin']:
        flash('You do not have permission to delete items.', 'error')
        return redirect(url_for('main.items'))

    item = Item.query.get_or_404(id)

    # Check if item has stock entries or issues
    has_entries = StockEntry.query.filter_by(item_id=id).first()
    has_issues = StockIssueItem.query.filter_by(item_id=id).first()

    if has_entries or has_issues:
        flash('Cannot delete item - it has stock entries or issues.', 'error')
    else:
        old_values = {
            'code': item.code,
            'name': item.name,
            'make': item.make,
            'variant': item.variant,
            'description': item.description
        }
        item.is_active = False
        db.session.commit()
        log_audit('item', item.id, 'DELETE', old_values=old_values)
        flash('Item deleted successfully.', 'success')

    return redirect(url_for('main.items'))

# Department Master Routes
@main_bp.route('/masters/departments')
@login_required
def departments():
    if current_user.role not in ['admin']:
        flash('You do not have permission to view departments master.', 'error')
        return redirect(url_for('main.dashboard'))

    search = request.args.get('search', '')
    departments = Department.query.filter_by(is_active=True)
    if search:
        departments = departments.filter(or_(Department.code.contains(search), Department.name.contains(search)))
    departments = departments.all()
    return render_template('masters/departments.html', departments=departments, search=search)

@main_bp.route('/masters/departments/add', methods=['GET', 'POST'])
@login_required
def add_department():
    if current_user.role not in ['admin']:
        flash('You do not have permission to add departments.', 'error')
        return redirect(url_for('main.departments'))

    form = DepartmentForm()
    if form.validate_on_submit():
        existing = Department.query.filter_by(code=form.code.data).first()
        if existing:
            flash('Department code already exists.', 'error')
        else:
            department = Department(
                code=form.code.data,
                name=form.name.data,
                hod_id=form.hod_id.data if form.hod_id.data != 0 else None
            )
            db.session.add(department)
            db.session.commit()
            log_audit('department', department.id, 'CREATE', new_values=form.data)
            flash('Department added successfully.', 'success')
            return redirect(url_for('main.departments'))

    return render_template('masters/departments.html', form=form, mode='add')

@main_bp.route('/masters/departments/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_department(id):
    if current_user.role not in ['admin']:
        flash('You do not have permission to edit departments.', 'error')
        return redirect(url_for('main.departments'))

    department = Department.query.get_or_404(id)
    form = DepartmentForm(obj=department)

    if form.validate_on_submit():
        existing = Department.query.filter(Department.code == form.code.data, Department.id != id).first()
        if existing:
            flash('Department code already exists.', 'error')
        else:
            old_values = {
                'code': department.code,
                'name': department.name,
                'hod_id': department.hod_id
            }

            department.code = form.code.data
            department.name = form.name.data
            department.hod_id = form.hod_id.data if form.hod_id.data != 0 else None

            db.session.commit()
            log_audit('department', department.id, 'UPDATE', old_values=old_values, new_values=form.data)
            flash('Department updated successfully.', 'success')
            return redirect(url_for('main.departments'))

    # Get all departments for the list view
    search = request.args.get('search', '')
    departments = Department.query.filter_by(is_active=True)
    if search:
        departments = departments.filter(or_(Department.code.contains(search), Department.name.contains(search)))
    departments = departments.all()

    return render_template('masters/departments.html', form=form, department=department, departments=departments, mode='edit', search=search)

@main_bp.route('/masters/departments/delete/<int:id>')
@login_required
def delete_department(id):
    if current_user.role not in ['admin']:
        flash('You do not have permission to delete departments.', 'error')
        return redirect(url_for('main.departments'))

    department = Department.query.get_or_404(id)

    # Check if department has employees
    has_employees = Employee.query.filter_by(department_id=id).first()

    if has_employees:
        flash('Cannot delete department - it has employees assigned.', 'error')
    else:
        old_values = {
            'code': department.code,
            'name': department.name,
            'hod_id': department.hod_id
        }
        department.is_active = False
        db.session.commit()
        log_audit('department', department.id, 'DELETE', old_values=old_values)
        flash('Department deleted successfully.', 'success')

    return redirect(url_for('main.departments'))

# Employee Master Routes
@main_bp.route('/masters/employees')
@login_required
def employees():
    if current_user.role not in ['admin']:
        flash('You do not have permission to view employees master.', 'error')
        return redirect(url_for('main.dashboard'))

    search = request.args.get('search', '')
    employees = Employee.query.filter_by(is_active=True)
    if search:
        employees = employees.filter(or_(Employee.emp_id.contains(search), Employee.name.contains(search)))
    employees = employees.all()
    return render_template('masters/employees.html', employees=employees, search=search)

@main_bp.route('/masters/employees/add', methods=['GET', 'POST'])
@login_required
def add_employee():
    if current_user.role not in ['admin']:
        flash('You do not have permission to add employees.', 'error')
        return redirect(url_for('main.employees'))

    form = EmployeeForm()
    if form.validate_on_submit():
        existing = Employee.query.filter_by(emp_id=form.emp_id.data).first()
        if existing:
            flash('Employee ID already exists.', 'error')
        else:
            employee = Employee(
                emp_id=form.emp_id.data,
                name=form.name.data,
                department_id=form.department_id.data,
                user_id=form.user_id.data if form.user_id.data != 0 else None
            )
            db.session.add(employee)
            db.session.commit()
            log_audit('employee', employee.id, 'CREATE', new_values=form.data)
            flash('Employee added successfully.', 'success')
            return redirect(url_for('main.employees'))

    return render_template('masters/employees.html', form=form, mode='add')

@main_bp.route('/masters/employees/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_employee(id):
    if current_user.role not in ['admin']:
        flash('You do not have permission to edit employees.', 'error')
        return redirect(url_for('main.employees'))

    employee = Employee.query.get_or_404(id)
    form = EmployeeForm(obj=employee)

    if form.validate_on_submit():
        existing = Employee.query.filter(Employee.emp_id == form.emp_id.data, Employee.id != id).first()
        if existing:
            flash('Employee ID already exists.', 'error')
        else:
            old_values = {
                'emp_id': employee.emp_id,
                'name': employee.name,
                'department_id': employee.department_id,
                'user_id': employee.user_id
            }

            employee.emp_id = form.emp_id.data
            employee.name = form.name.data
            employee.department_id = form.department_id.data
            employee.user_id = form.user_id.data if form.user_id.data != 0 else None

            db.session.commit()
            log_audit('employee', employee.id, 'UPDATE', old_values=old_values, new_values=form.data)
            flash('Employee updated successfully.', 'success')
            return redirect(url_for('main.employees'))

    # Get all employees for the list view
    search = request.args.get('search', '')
    employees = Employee.query.filter_by(is_active=True)
    if search:
        employees = employees.filter(or_(Employee.emp_id.contains(search), Employee.name.contains(search)))
    employees = employees.all()

    return render_template('masters/employees.html', form=form, employee=employee, employees=employees, mode='edit', search=search)

@main_bp.route('/masters/employees/delete/<int:id>')
@login_required
def delete_employee(id):
    if current_user.role not in ['admin']:
        flash('You do not have permission to delete employees.', 'error')
        return redirect(url_for('main.employees'))

    employee = Employee.query.get_or_404(id)

    # Check if employee has stock requests
    has_requests = StockIssueRequest.query.filter_by(requester_id=id).first()

    if has_requests:
        flash('Cannot delete employee - they have stock requests.', 'error')
    else:
        old_values = {
            'emp_id': employee.emp_id,
            'name': employee.name,
            'department_id': employee.department_id,
            'user_id': employee.user_id
        }
        employee.is_active = False
        db.session.commit()
        log_audit('employee', employee.id, 'DELETE', old_values=old_values)
        flash('Employee deleted successfully.', 'success')

    return redirect(url_for('main.employees'))

# Location Master Routes
@main_bp.route('/masters/locations')
@login_required
def locations():
    if current_user.role not in ['admin']:
        flash('You do not have permission to view locations master.', 'error')
        return redirect(url_for('main.dashboard'))

    search = request.args.get('search', '')
    locations = Location.query.filter_by(is_active=True)
    if search:
        locations = locations.filter(or_(Location.office.contains(search), Location.room_store.contains(search)))
    locations = locations.all()
    return render_template('masters/locations.html', locations=locations, search=search)

@main_bp.route('/masters/locations/add', methods=['GET', 'POST'])
@login_required
def add_location():
    if current_user.role not in ['admin']:
        flash('You do not have permission to add locations.', 'error')
        return redirect(url_for('main.locations'))

    form = LocationForm()
    if form.validate_on_submit():
        location = Location(
            office=form.office.data,
            room_store=form.room_store.data
        )
        db.session.add(location)
        db.session.commit()
        log_audit('location', location.id, 'CREATE', new_values=form.data)
        flash('Location added successfully.', 'success')
        return redirect(url_for('main.locations'))

    return render_template('masters/locations.html', form=form, mode='add')

@main_bp.route('/masters/locations/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_location(id):
    if current_user.role not in ['admin']:
        flash('You do not have permission to edit locations.', 'error')
        return redirect(url_for('main.locations'))

    location = Location.query.get_or_404(id)
    form = LocationForm(obj=location)

    if form.validate_on_submit():
        old_values = {
            'office': location.office,
            'room_store': location.room_store
        }

        location.office = form.office.data
        location.room_store = form.room_store.data

        db.session.commit()
        log_audit('location', location.id, 'UPDATE', old_values=old_values, new_values=form.data)
        flash('Location updated successfully.', 'success')
        return redirect(url_for('main.locations'))

    return render_template('masters/locations.html', form=form, location=location, mode='edit')

@main_bp.route('/masters/locations/delete/<int:id>')
@login_required
def delete_location(id):
    if current_user.role not in ['admin']:
        flash('You do not have permission to delete locations.', 'error')
        return redirect(url_for('main.locations'))

    location = Location.query.get_or_404(id)

    # Check if location has stock entries or balances
    has_entries = StockEntry.query.filter_by(location_id=id).first()
    has_balances = StockBalance.query.filter_by(location_id=id).first()

    if has_entries or has_balances:
        flash('Cannot delete location - it has stock entries or balances.', 'error')
    else:
        old_values = {
            'office': location.office,
            'room_store': location.room_store
        }
        location.is_active = False
        db.session.commit()
        log_audit('location', location.id, 'DELETE', old_values=old_values)
        flash('Location deleted successfully.', 'success')

    return redirect(url_for('main.locations'))

# Stock Entry Routes
@main_bp.route('/stock/entries')
@login_required
def stock_entries():
    if current_user.role not in ['admin', 'hod']:
        flash('You do not have permission to view stock entries.', 'error')
        return redirect(url_for('main.dashboard'))

    entries = StockEntry.query.order_by(StockEntry.created_at.desc()).all()
    return render_template('stock/entry.html', entries=entries)

@main_bp.route('/stock/entries/add', methods=['GET', 'POST'])
@login_required
def add_stock_entry():
    if current_user.role not in ['admin', 'hod']:
        flash('You do not have permission to add stock entries.', 'error')
        return redirect(url_for('main.dashboard'))

    form = StockEntryForm()
    if form.validate_on_submit():
        entry = StockEntry(
            item_id=form.item_id.data,
            location_id=form.location_id.data,
            quantity_procured=form.quantity_procured.data,
            description=form.description.data,
            remarks=form.remarks.data,
            created_by=current_user.id
        )
        db.session.add(entry)
        db.session.commit()

        # Update stock balance
        update_stock_balance(form.item_id.data, form.location_id.data, form.quantity_procured.data)

        log_audit('stock_entry', entry.id, 'CREATE', new_values=form.data)
        flash('Stock entry added successfully.', 'success')
        return redirect(url_for('main.stock_entries'))

    return render_template('stock/entry.html', form=form, mode='add')

# Stock Issue Routes
@main_bp.route('/stock/issues')
@login_required
def stock_issues():
    if current_user.role == 'admin':
        requests = StockIssueRequest.query.order_by(StockIssueRequest.created_at.desc()).all()
    elif current_user.role == 'hod':
        # HODs see requests from their departments
        hod_departments = Department.query.filter_by(hod_id=current_user.id).all()
        dept_ids = [d.id for d in hod_departments]
        if dept_ids:
            requests = StockIssueRequest.query.filter(StockIssueRequest.department_id.in_(dept_ids)).order_by(StockIssueRequest.created_at.desc()).all()
        else:
            requests = []
    else:
        # Regular users see only their requests
        requests = StockIssueRequest.query.filter_by(created_by=current_user.id).order_by(StockIssueRequest.created_at.desc()).all()

    return render_template('stock/issue.html', requests=requests)

@main_bp.route('/stock/issues/add', methods=['GET', 'POST'])
@login_required
def add_stock_issue():
    form = StockIssueRequestForm(user=current_user)

    # Get current user's employee record to auto-select department
    user_employee = Employee.query.filter_by(user_id=current_user.id).first()

    # Auto-select user's department if they have an employee record
    if user_employee and request.method == 'GET':
        form.department_id.data = user_employee.department_id
        form.requester_id.data = user_employee.id

    if form.validate_on_submit():
        # Ensure the request is for the user's own department (security check)
        if user_employee and form.department_id.data != user_employee.department_id:
            flash('You can only create requests for your own department.', 'error')
            return render_template('stock/issue.html', form=form, mode='add')
        # Generate request number
        import uuid
        request_number = f"REQ-{datetime.now().strftime('%Y%m%d')}-{str(uuid.uuid4())[:8].upper()}"

        request_obj = StockIssueRequest(
            request_number=request_number,
            requester_id=form.requester_id.data,
            department_id=form.department_id.data,
            purpose=form.purpose.data,
            approval_flow=form.approval_flow.data,
            approver_id=form.approver_id.data if form.approver_id.data != 0 else None,
            created_by=current_user.id
        )
        db.session.add(request_obj)
        db.session.commit()

        log_audit('stock_issue_request', request_obj.id, 'CREATE', new_values=form.data)
        flash('Stock issue request created successfully.', 'success')
        return redirect(url_for('main.stock_issue_detail', id=request_obj.id))

    return render_template('stock/issue.html', form=form, mode='add')

@main_bp.route('/stock/issues/<int:id>')
@login_required
def stock_issue_detail(id):
    request_obj = StockIssueRequest.query.get_or_404(id)

    # Check permissions
    if current_user.role not in ['admin'] and request_obj.created_by != current_user.id:
        if current_user.role == 'hod':
            # Check if HOD manages this department
            hod_departments = Department.query.filter_by(hod_id=current_user.id).all()
            if request_obj.department_id not in [d.id for d in hod_departments]:
                flash('You do not have permission to view this request.', 'error')
                return redirect(url_for('main.stock_issues'))
        else:
            flash('You do not have permission to view this request.', 'error')
            return redirect(url_for('main.stock_issues'))

    item_form = StockIssueItemForm(user=current_user)
    approval_form = ApprovalForm()

    return render_template('stock/issue_detail.html',
                         request=request_obj,
                         item_form=item_form,
                         approval_form=approval_form)

@main_bp.route('/stock/issues/<int:id>/add_item', methods=['POST'])
@login_required
def add_issue_item(id):
    request_obj = StockIssueRequest.query.get_or_404(id)

    if request_obj.status not in ['draft']:
        flash('Cannot add items to this request.', 'error')
        return redirect(url_for('main.stock_issue_detail', id=id))

    form = StockIssueItemForm(user=current_user)
    if form.validate_on_submit():
        # Check available stock
        available = get_stock_balance(form.item_id.data, form.location_id.data)
        if available < form.quantity_requested.data:
            flash(f'Insufficient stock. Available: {available}', 'error')
        else:
            issue_item = StockIssueItem(
                request_id=id,
                item_id=form.item_id.data,
                location_id=form.location_id.data,
                quantity_requested=form.quantity_requested.data,
                description=form.description.data
            )
            db.session.add(issue_item)
            db.session.commit()
            flash('Item added to request.', 'success')

    return redirect(url_for('main.stock_issue_detail', id=id))

@main_bp.route('/stock/issues/<int:id>/approve', methods=['POST'])
@login_required
def approve_issue_request(id):
    request_obj = StockIssueRequest.query.get_or_404(id)
    form = ApprovalForm()

    if form.validate_on_submit():
        action = form.action.data

        if action == 'approve':
            # Check if current user is HOD of the requesting department
            requesting_department = request_obj.department
            is_department_hod = (current_user.role == 'hod' and
                               requesting_department.hod_id == current_user.id)

            if is_department_hod:
                # Final approval
                request_obj.hod_approved_by = current_user.id
                request_obj.hod_approved_at = datetime.utcnow()
                request_obj.status = 'approved'
                flash('Request approved successfully.', 'success')

                db.session.commit()
                log_audit('stock_issue_request', request_obj.id, 'APPROVE')
            else:
                flash('You do not have permission to approve this request.', 'error')

        elif action == 'reject':
            request_obj.status = 'rejected'
            request_obj.rejection_reason = form.rejection_reason.data
            db.session.commit()
            log_audit('stock_issue_request', request_obj.id, 'REJECT')
            flash('Request rejected.', 'success')

    return redirect(url_for('main.stock_issue_detail', id=id))

@main_bp.route('/stock/issues/<int:id>/issue')
@login_required
def issue_stock(id):
    if current_user.role != 'admin':
        flash('You do not have permission to issue stock.', 'error')
        return redirect(url_for('main.stock_issue_detail', id=id))

    request_obj = StockIssueRequest.query.get_or_404(id)

    if request_obj.status != 'approved':
        flash('Request must be approved before issuing stock.', 'error')
        return redirect(url_for('main.stock_issue_detail', id=id))

    # Check and update stock for each item
    for item in request_obj.items:
        available = get_stock_balance(item.item_id, item.location_id)
        if available < item.quantity_requested:
            flash(f'Insufficient stock for {item.item.name}. Available: {available}', 'error')
            return redirect(url_for('main.stock_issue_detail', id=id))

    # Issue all items
    for item in request_obj.items:
        update_stock_balance(item.item_id, item.location_id, -item.quantity_requested)
        item.quantity_issued = item.quantity_requested

    request_obj.status = 'issued'
    request_obj.issued_by= current_user.id
    request_obj.issued_at = datetime.utcnow()

    db.session.commit()
    log_audit('stock_issue_request', request_obj.id, 'ISSUE')

    flash('Stock issued successfully.', 'success')
    return redirect(url_for('main.stock_issue_detail', id=id))

# Approval Routes
@main_bp.route('/approvals/pending')
@login_required
def pending_approvals():
    if current_user.role == 'hod':
        # HOD sees requests from their departments that are pending approval
        hod_departments = Department.query.filter_by(hod_id=current_user.id).all()
        dept_ids = [d.id for d in hod_departments]
        if dept_ids:
            requests = StockIssueRequest.query.filter(
                and_(
                    StockIssueRequest.department_id.in_(dept_ids),
                    StockIssueRequest.status == 'pending'
                )
            ).order_by(StockIssueRequest.created_at.desc()).all()
        else:
            requests = []
    elif current_user.role == 'approver':
        # Approvers see requests assigned to them for conditional approval
        requests = StockIssueRequest.query.filter(
            and_(
                StockIssueRequest.approver_id == current_user.id,
                StockIssueRequest.status == 'pending'
            )
        ).order_by(StockIssueRequest.created_at.desc()).all()
    else:
        requests = []

    return render_template('approval/pending.html', requests=requests)

@main_bp.route('/stock/issues/<int:id>/submit')
@login_required
def submit_issue_request(id):
    request_obj = StockIssueRequest.query.get_or_404(id)

    if request_obj.created_by != current_user.id:
        flash('You can only submit your own requests.', 'error')
        return redirect(url_for('main.stock_issue_detail', id=id))

    if request_obj.status != 'draft':
        flash('Request can only be submitted from draft status.', 'error')
        return redirect(url_for('main.stock_issue_detail', id=id))

    if not request_obj.items:
        flash('Cannot submit request without items.', 'error')
        return redirect(url_for('main.stock_issue_detail', id=id))

    request_obj.status = 'pending'
    request_obj.updated_at = datetime.utcnow()
    db.session.commit()
    log_audit('stock_issue_request', request_obj.id, 'SUBMIT')

    flash('Request submitted successfully for approval.', 'success')
    return redirect(url_for('main.stock_issue_detail', id=id))

# Reports Routes
@main_bp.route('/reports/stock')
@login_required
def stock_report():
    item_filter = request.args.get('item', '')
    location_filter = request.args.get('location', '')
    department_filter = request.args.get('department', '')

    query = db.session.query(StockBalance, Item, Location).join(Item).join(Location)

    # Filter based on user's assigned warehouses
    if current_user.role.value not in ['superadmin', 'manager']:
        # Non-admin users only see stock from their assigned warehouses
        accessible_warehouses = current_user.get_accessible_warehouses()
        if accessible_warehouses:
            warehouse_ids = [w.id for w in accessible_warehouses]
            query = query.filter(Location.id.in_(warehouse_ids))
        else:
            # No warehouse access - show no data
            query = query.filter(Location.id == -1)

    if item_filter:
        query = query.filter(Item.name.contains(item_filter))
    if location_filter:
        query = query.filter(Location.office.contains(location_filter))

    stock_data = query.all()

    # Get filter options based on user permissions
    items = Item.query.filter_by(is_active=True).all()

    # Department-specific filtering for stock requests analysis
    if current_user.role == 'admin':
        departments = Department.query.filter_by(is_active=True).all()
        stock_requests_summary = []
        for dept in departments:
            pending_count = StockIssueRequest.query.filter_by(
                department_id=dept.id,
                status='pending'
            ).count()
            approved_count = StockIssueRequest.query.filter_by(
                department_id=dept.id,
                status='approved'
            ).count()
            stock_requests_summary.append({
                'department': dept,
                'pending': pending_count,
                'approved': approved_count
            })
    else:
        departments = []
        stock_requests_summary = []

    if current_user.role in ['admin', 'superadmin']:
        locations = Location.query.all()
    else:
        # Get user's assigned warehouses
        locations = current_user.get_accessible_warehouses()

    return render_template('reports/stock_report.html',
                         stock_data=stock_data,
                         items=items,
                         locations=locations,
                         departments=departments,
                         stock_requests_summary=stock_requests_summary,
                         item_filter=item_filter,
                         location_filter=location_filter,
                         department_filter=department_filter)

@main_bp.route('/reports/department_usage')
@login_required
def department_usage_report():
    """Department-wise stock usage and request statistics"""
    if current_user.role not in ['admin', 'hod']:
        flash('You do not have permission to view this report.', 'error')
        return redirect(url_for('main.dashboard'))

    # Get department statistics
    if current_user.role == 'admin':
        departments = Department.query.filter_by(is_active=True).all()
    else:
        # HOD sees only their department
        user_employee = Employee.query.filter_by(user_id=current_user.id).first()
        if user_employee:
            departments = [user_employee.department]
        else:
            departments = []

    department_stats = []
    for dept in departments:
        total_requests = StockIssueRequest.query.filter_by(department_id=dept.id).count()
        pending_requests = StockIssueRequest.query.filter_by(
            department_id=dept.id,
            status='pending'
        ).count()
        approved_requests = StockIssueRequest.query.filter_by(
            department_id=dept.id,
            status='approved'
        ).count()
        issued_requests = StockIssueRequest.query.filter_by(
            department_id=dept.id,
            status='issued'
        ).count()

        # Calculate total items issued
        total_items_issued = db.session.query(func.sum(StockIssueItem.quantity_issued)).join(
            StockIssueRequest
        ).filter(
            StockIssueRequest.department_id == dept.id,
            StockIssueRequest.status == 'issued'
        ).scalar() or 0

        department_stats.append({
            'department': dept,
            'total_requests': total_requests,
            'pending_requests': pending_requests,
            'approved_requests': approved_requests,
            'issued_requests': issued_requests,
            'total_items_issued': total_items_issued,
            'approval_rate': round((approved_requests + issued_requests) / total_requests * 100, 1) if total_requests > 0 else 0
        })

    return render_template('reports/department_usage.html', department_stats=department_stats)

# User Management Routes
@main_bp.route('/admin/users')
@login_required
def user_management():
    if current_user.role != 'admin':
        flash('You do not have permission to manage users.', 'error')
        return redirect(url_for('main.dashboard'))

    search = request.args.get('search', '')
    users = User.query.filter_by(is_active=True)
    if search:
        users = users.filter(or_(User.username.contains(search), User.email.contains(search)))
    users = users.all()

    return render_template('admin/user_management.html', users=users, search=search)

@main_bp.route('/admin/users/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_user(id):
    if current_user.role != 'admin':
        flash('You do not have permission to edit users.', 'error')
        return redirect(url_for('main.dashboard'))

    from werkzeug.security import generate_password_hash
    user = User.query.get_or_404(id)

    # Get departments and locations for dropdowns
    departments = Department.query.filter_by(is_active=True).all()
    locations = Location.query.filter_by(is_active=True).all()

    # Get employee record if exists
    employee = Employee.query.filter_by(user_id=id).first()

    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        role = request.form.get('role')
        emp_id = request.form.get('emp_id')
        employee_name = request.form.get('employee_name')
        department_id = request.form.get('department_id')
        warehouse_id = request.form.get('warehouse_id')

        # Check for duplicates (excluding current user)
        existing_user = User.query.filter(User.username == username, User.id != id).first()
        existing_email = User.query.filter(User.email == email,  User.id == id).first()
        existing_emp = Employee.query.filter(Employee.emp_id == emp_id, Employee.user_id != id).first()

        if existing_user:
            flash('Username already exists.', 'error')
        elif existing_email:
            flash('Email already exists.', 'error')
        elif existing_emp:
            flash('Employee ID already exists.', 'error')
        else:
            # Update user
            old_values = {
                'username': user.username,
                'email': user.email,
                'role': user.role
            }

            user.username = username
            user.email = email
            user.role = role
            if password:
                user.password_hash = generate_password_hash(password)

            # Update or create employee record
            if employee:
                employee.emp_id = emp_id
                employee.name = employee_name
                employee.department_id = int(department_id)
                employee.warehouse_id = int(warehouse_id) if warehouse_id else None
            else:
                employee = Employee(
                    emp_id=emp_id,
                    name=employee_name,
                    department_id=int(department_id),
                    warehouse_id=int(warehouse_id) if warehouse_id else None,
                    user_id=user.id
                )
                db.session.add(employee)

            db.session.commit()
            log_audit('user', user.id, 'UPDATE', old_values=old_values, new_values={
                'username': username, 'email': email, 'role': role
            })
            flash('User updated successfully.', 'success')
            return redirect(url_for('main.user_management'))

    return render_template('admin/edit_user.html',
                         user=user,
                         employee=employee,
                         departments=departments,
                         locations=locations)

@main_bp.route('/admin/users/delete/<int:id>')
@login_required
def delete_user(id):
    if current_user.role != 'admin':
        flash('You do not have permission to delete users.', 'error')
        return redirect(url_for('main.dashboard'))

    if id == current_user.id:
        flash('You cannot delete your own account.', 'error')
        return redirect(url_for('main.user_management'))

    user = User.query.get_or_404(id)

    # Check if user has stock requests or other dependencies
    has_requests = StockIssueRequest.query.filter_by(created_by=id).first()

    if has_requests:
        # Soft delete - deactivate user
        user.is_active = False
        log_audit('user', user.id, 'DEACTIVATE')
        flash('User deactivated successfully.', 'success')
    else:
        # Hard delete if no dependencies
        employee = Employee.query.filter_by(user_id=id).first()
        if employee:
            db.session.delete(employee)

        old_values = {
            'username': user.username,
            'email': user.email,
            'role': user.role
        }

        db.session.delete(user)
        log_audit('user', user.id, 'DELETE', old_values=old_values)
        flash('User deleted successfully.', 'success')

    db.session.commit()
    return redirect(url_for('main.user_management'))

# API Endpoints for AJAX
@main_bp.route('/api/stock_balance/<int:item_id>/<int:location_id>')
@login_required
def api_stock_balance(item_id, location_id):
    # Check if user has access to this warehouse
    if not current_user.can_access_warehouse(location_id):
        return jsonify({'error': 'Access denied'}), 403
    
    balance = get_stock_balance(item_id, location_id)
    return jsonify({'balance': balance})

@main_bp.route('/api/employee/<int:employee_id>')
@login_required
def api_employee_details(employee_id):
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403

    employee = Employee.query.get_or_404(employee_id)
    return jsonify({
        'id': employee.id,
        'emp_id': employee.emp_id,
        'name': employee.name,
        'department': {
            'id': employee.department.id,
            'code': employee.department.code,
            'name': employee.department.name
        }
    })

@main_bp.route('/api/items_by_location/<int:location_id>')
@login_required
def api_items_by_location(location_id):
    # Check if user has access to this warehouse
    if not current_user.can_access_warehouse(location_id):
        return jsonify([])  # Return empty if no access

    # Get items that have stock in this location
    balances = StockBalance.query.filter(
        StockBalance.location_id == location_id,
        StockBalance.balance > 0
    ).all()

    items = []
    for balance in balances:
        items.append({
            'id': balance.item.id,
            'code': balance.item.code,
            'name': balance.item.name,
            'balance': balance.balance
        })

    return jsonify(items)