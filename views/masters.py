from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from models import User, Department, Location, Item, Employee, UserRole, StockBalance, StockEntry, StockIssueLine
from auth import role_required
from database import db
from forms import ItemForm # Assuming ItemForm is defined in forms.py

# Mock Audit class for demonstration if not imported
class Audit:
    @staticmethod
    def log(entity_type, entity_id, action, user_id, details):
        print(f"Audit Log: Type={entity_type}, ID={entity_id}, Action={action}, User={user_id}, Details={details}")

masters_bp = Blueprint('masters', __name__)

@masters_bp.route('/departments')
@login_required
@role_required('superadmin', 'manager', 'hod')
def departments():
    try:
        departments = Department.query.all()
        return render_template('masters/departments.html', departments=departments)
    except Exception as e:
        flash('Error loading departments.', 'error')
        return redirect(url_for('main.dashboard'))

@masters_bp.route('/departments/create', methods=['POST'])
@login_required
@role_required('superadmin')
def create_department():
    code = request.form.get('code', '').strip().upper()
    name = request.form.get('name', '').strip()
    hod_id = request.form.get('hod_id')

    if not code or not name:
        flash('Department code and name are required.', 'error')
        return redirect(url_for('masters.departments'))

    # Check if code already exists
    if Department.query.filter_by(code=code).first():
        flash('Department code already exists.', 'error')
        return redirect(url_for('masters.departments'))

    # Validate HOD if provided
    hod_user = None
    if hod_id and int(hod_id) != 0:
        hod_user = User.query.filter_by(id=int(hod_id), role=UserRole.HOD).first()
        if not hod_user:
            flash('Selected HOD user is invalid or not found.', 'error')
            return redirect(url_for('masters.departments'))

        # Check if HOD is already assigned to another department
        if hod_user.managed_department:
            flash(f'Selected HOD is already managing {hod_user.managed_department.name} department.', 'error')
            return redirect(url_for('masters.departments'))

    try:
        department = Department(
            code=code,
            name=name,
            hod_id=int(hod_id) if hod_id and int(hod_id) != 0 else None
        )

        db.session.add(department)
        db.session.flush()  # Get the department ID

        # Update HOD's department_id if HOD is assigned
        if department.hod_id and hod_user:
            hod_user.department_id = department.id

        # Log audit
        Audit.log(
            entity_type='Department',
            entity_id=department.id,
            action='CREATE',
            user_id=current_user.id,
            details=f'Created department {code} - {name}'
        )

        db.session.commit()
        flash('Department created successfully. You can assign an HOD later if needed.', 'success')

    except Exception as e:
        db.session.rollback()
        flash('Error creating department.', 'error')

    return redirect(url_for('masters.departments'))

@masters_bp.route('/departments/<int:dept_id>/update', methods=['POST'])
@login_required
@role_required('superadmin')
def update_department(dept_id):
    department = Department.query.get_or_404(dept_id)

    code = request.form.get('code', '').strip().upper()
    name = request.form.get('name', '').strip()
    hod_id = request.form.get('hod_id')

    if not code or not name:
        flash('Department code and name are required.', 'error')
        return redirect(url_for('masters.departments'))

    # Check if code already exists (excluding current department)
    existing = Department.query.filter(
        Department.code == code, Department.id != dept_id
    ).first()
    if existing:
        flash('Department code already exists.', 'error')
        return redirect(url_for('masters.departments'))

    # Validate HOD assignment
    hod_user = None
    if hod_id and int(hod_id) != 0:
        hod_user = User.query.filter_by(id=int(hod_id), role=UserRole.HOD).first()
        if not hod_user:
            flash('Selected HOD user is invalid or not found.', 'error')
            return redirect(url_for('masters.departments'))

        # Check if HOD is already assigned to another department
        if hod_user.managed_department and hod_user.managed_department.id != dept_id:
            flash(f'Selected HOD is already managing {hod_user.managed_department.name} department.', 'error')
            return redirect(url_for('masters.departments'))

    # Remove old HOD's department_id if HOD is changing
    if department.hod_id and (not hod_id or int(hod_id) == 0 or department.hod_id != int(hod_id)):
        old_hod = User.query.get(department.hod_id)
        if old_hod:
            old_hod.department_id = None

    department.code = code
    department.name = name
    department.hod_id = int(hod_id) if hod_id and int(hod_id) != 0 else None

    # Assign new HOD's department_id if HOD is assigned
    if department.hod_id and hod_user:
        hod_user.department_id = department.id

    try:
        db.session.commit()
        flash('Department updated successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error updating department.', 'error')

    return redirect(url_for('masters.departments'))

@masters_bp.route('/departments/<int:dept_id>/assign_hod', methods=['POST'])
@login_required
@role_required('superadmin')
def assign_hod_to_department(dept_id):
    department = Department.query.get_or_404(dept_id)
    hod_id = request.form.get('hod_id')

    if not hod_id or int(hod_id) == 0:
        # Remove existing HOD
        if department.hod_id:
            old_hod = User.query.get(department.hod_id)
            if old_hod:
                old_hod.department_id = None
        department.hod_id = None
        flash('HOD removed from department.', 'success')
    else:
        hod_user = User.query.filter_by(id=int(hod_id), role=UserRole.HOD).first()
        if not hod_user:
            flash('Selected HOD user is invalid.', 'error')
            return redirect(url_for('masters.departments'))

        # Check if HOD is already assigned to another department
        if hod_user.managed_department and hod_user.managed_department.id != dept_id:
            flash(f'Selected HOD is already managing {hod_user.managed_department.name} department.', 'error')
            return redirect(url_for('masters.departments'))

        # Remove old HOD's department_id if exists
        if department.hod_id:
            old_hod = User.query.get(department.hod_id)
            if old_hod:
                old_hod.department_id = None

        # Assign new HOD
        department.hod_id = hod_user.id
        hod_user.department_id = department.id
        flash(f'{hod_user.full_name} assigned as HOD of {department.name}.', 'success')

    try:
        # Log audit
        Audit.log(
            entity_type='Department',
            entity_id=department.id,
            action='UPDATE',
            user_id=current_user.id,
            details=f'Updated HOD assignment for department {department.code}'
        )

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        flash('Error updating HOD assignment.', 'error')

    return redirect(url_for('masters.departments'))


@masters_bp.route('/locations')
@login_required
@role_required('superadmin', 'manager', 'hod')
def locations():
    try:
        locations = Location.query.all()
        return render_template('masters/locations.html', locations=locations)
    except Exception as e:
        flash('Error loading locations.', 'error')
        return redirect(url_for('main.dashboard'))

@masters_bp.route('/locations/create', methods=['POST'])
@login_required
@role_required('superadmin')
def create_location():
    office = request.form.get('office', '').strip()
    room = request.form.get('room', '').strip()
    code = request.form.get('code', '').strip()

    if not office or not room or not code:
        flash('Office, room, and code are required.', 'error')
        return redirect(url_for('masters.locations'))

    # Check if code already exists
    if Location.query.filter_by(code=code).first():
        flash('Location code already exists.', 'error')
        return redirect(url_for('masters.locations'))

    location = Location(office=office, room=room, code=code)

    try:
        db.session.add(location)
        db.session.flush()  # Get the location ID

        # Auto-assign all superadmins and managers to this new warehouse
        superadmins_and_managers = User.query.filter(
            User.role.in_([UserRole.SUPERADMIN]),
            User.is_active == True
        ).all()

        for user in superadmins_and_managers:
            user.assigned_warehouses.append(location)

        # Log audit
        Audit.log(
            entity_type='Location',
            entity_id=location.id,
            action='CREATE',
            user_id=current_user.id,
            details=f'Created location {code} and auto-assigned to {len(superadmins_and_managers)} superadmin'
        )

        db.session.commit()
        flash('Location created successfully and auto-assigned to superadmins.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error creating location.', 'error')

    return redirect(url_for('masters.locations'))

@masters_bp.route('/locations/<int:location_id>/update', methods=['POST'])
@login_required
@role_required('superadmin')
def update_location(location_id):
    location = Location.query.get_or_404(location_id)

    office = request.form.get('office', '').strip()
    room = request.form.get('room', '').strip()
    code = request.form.get('code', '').strip()

    if not office or not room or not code:
        flash('Office, room, and code are required.', 'error')
        return redirect(url_for('masters.locations'))

    # Check if code already exists (excluding current location)
    existing = Location.query.filter(
        Location.code == code, Location.id != location_id
    ).first()
    if existing:
        flash('Location code already exists.', 'error')
        return redirect(url_for('masters.locations'))

    location.office = office
    location.room = room
    location.code = code

    try:
        # Log audit
        Audit.log(
            entity_type='Location',
            entity_id=location.id,
            action='UPDATE',
            user_id=current_user.id,
            details=f'Updated location {code}'
        )

        db.session.commit()
        flash('Location updated successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error updating location.', 'error')

    return redirect(url_for('masters.locations'))

@masters_bp.route('/locations/<int:location_id>/delete', methods=['POST'])
@login_required
@role_required('superadmin')
def delete_location(location_id):
    location = Location.query.get_or_404(location_id)

    try:
        # Log audit
        Audit.log(
            entity_type='Location',
            entity_id=location.id,
            action='DELETE',
            user_id=current_user.id,
            details=f'Deleted location {location.code} - {location.office}, {location.room}'
        )

        db.session.delete(location)
        db.session.commit()
        flash('Location deleted successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error deleting location. Location may have associated stock records.', 'error')

    return redirect(url_for('masters.locations'))

@masters_bp.route('/employees')
@login_required
@role_required('superadmin', 'manager', 'hod')
def employees():
    try:
        if current_user.role == UserRole.HOD:
            # HOD can only see employees in their department
            if current_user.managed_department:
                employees = Employee.query.filter_by(
                    department_id=current_user.managed_department.id
                ).all()
            else:
                employees = []
        else:
            # Superadmin and Manager can see all employees
            employees = Employee.query.all()

        departments = Department.query.all()
        return render_template('masters/employees.html', employees=employees, departments=departments)
    except Exception as e:
        flash('Error loading employees.', 'error')
        return redirect(url_for('main.dashboard'))

@masters_bp.route('/employees/create', methods=['POST'])
@login_required
@role_required('superadmin', 'hod')
def create_employee():
    emp_id = request.form.get('emp_id', '').strip()
    name = request.form.get('name', '').strip()
    department_id = request.form.get('department_id')
    user_id = request.form.get('user_id')

    if not emp_id or not name or not department_id:
        flash('Employee ID, name, and department are required.', 'error')
        return redirect(url_for('masters.employees'))

    # Check if emp_id already exists
    if Employee.query.filter_by(emp_id=emp_id).first():
        flash('Employee ID already exists.', 'error')
        return redirect(url_for('masters.employees'))

    # HOD can only create employees in their department
    if current_user.role == UserRole.HOD:
        if (not current_user.managed_department or 
            int(department_id) != current_user.managed_department.id):
            flash('You can only create employees in your department.', 'error')
            return redirect(url_for('masters.employees'))

    employee = Employee(
        emp_id=emp_id,
        name=name,
        department_id=int(department_id),
        user_id=int(user_id) if user_id else None
    )

    try:
        db.session.add(employee)
        db.session.commit()
        flash('Employee created successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error creating employee.', 'error')

    return redirect(url_for('masters.employees'))

@masters_bp.route('/employees/<int:employee_id>/update', methods=['POST'])
@login_required
@role_required('superadmin', 'hod')
def update_employee(employee_id):
    employee = Employee.query.get_or_404(employee_id)

    # HOD can only update employees in their department
    if current_user.role == UserRole.HOD:
        if (not current_user.managed_department or 
            employee.department_id != current_user.managed_department.id):
            flash('You can only update employees in your department.', 'error')
            return redirect(url_for('masters.employees'))

    emp_id = request.form.get('emp_id', '').strip()
    name = request.form.get('name', '').strip()
    department_id = request.form.get('department_id')
    user_id = request.form.get('user_id')

    if not emp_id or not name or not department_id:
        flash('Employee ID, name, and department are required.', 'error')
        return redirect(url_for('masters.employees'))

    # Check if emp_id already exists (excluding current employee)
    existing = Employee.query.filter(
        Employee.emp_id == emp_id, Employee.id != employee_id
    ).first()
    if existing:
        flash('Employee ID already exists.', 'error')
        return redirect(url_for('masters.employees'))

    # HOD can only assign to their department
    if current_user.role == UserRole.HOD:
        if (not current_user.managed_department or 
            int(department_id) != current_user.managed_department.id):
            flash('You can only assign employees to your department.', 'error')
            return redirect(url_for('masters.employees'))

    employee.emp_id = emp_id
    employee.name = name
    employee.department_id = int(department_id)
    employee.user_id = int(user_id) if user_id else None

    try:
        # Log audit
        Audit.log(
            entity_type='Employee',
            entity_id=employee.id,
            action='UPDATE',
            user_id=current_user.id,
            details=f'Updated employee {emp_id}'
        )

        db.session.commit()
        flash('Employee updated successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error updating employee.', 'error')

    return redirect(url_for('masters.employees'))

@masters_bp.route('/employees/<int:employee_id>/delete', methods=['POST'])
@login_required
@role_required('superadmin', 'hod')
def delete_employee(employee_id):
    employee = Employee.query.get_or_404(employee_id)

    # HOD can only delete employees in their department
    if current_user.role == UserRole.HOD:
        if (not current_user.managed_department or 
            employee.department_id != current_user.managed_department.id):
            flash('You can only delete employees in your department.', 'error')
            return redirect(url_for('masters.employees'))

    try:
        # Log audit
        Audit.log(
            entity_type='Employee',
            entity_id=employee.id,
            action='DELETE',
            user_id=current_user.id,
            details=f'Deleted employee {employee.emp_id} - {employee.name}'
        )

        db.session.delete(employee)
        db.session.commit()
        flash('Employee deleted successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error deleting employee. Employee may have associated records.', 'error')

    return redirect(url_for('masters.employees'))

@masters_bp.route('/items')
@login_required
@role_required('superadmin', 'manager', 'hod')
def items():
    try:
        items = Item.query.all()
        departments = Department.query.all()
        return render_template('masters/items.html', items=items, departments=departments)
    except Exception as e:
        flash('Error loading items.', 'error')
        return redirect(url_for('main.dashboard'))

@masters_bp.route('/items/create', methods=['POST'])
@login_required
@role_required('superadmin' )
def create_item():
    code = request.form.get('code', '').strip()
    name = request.form.get('name', '').strip()
    make = request.form.get('make', '').strip()
    variant = request.form.get('variant', '').strip()
    description = request.form.get('description', '').strip()
    department_id = request.form.get('department_id')
    threshold_option = request.form.get('threshold_option')
    low_stock_threshold = request.form.get('low_stock_threshold')

    if not code or not name:
        flash('Item code and name are required.', 'error')
        return redirect(url_for('masters.items'))

    # Check if code already exists
    existing_item = Item.query.filter_by(code=code).first()
    if existing_item:
        flash('Item code already exists.', 'error')
        return redirect(url_for('masters.items'))

    # Handle threshold logic
    if threshold_option == 'enable' and low_stock_threshold:
        try:
            threshold_value = float(low_stock_threshold)
            if threshold_value < 0:
                flash('Threshold must be a positive number.', 'error')
                return redirect(url_for('masters.items'))
        except ValueError:
            flash('Invalid threshold value.', 'error')
            return redirect(url_for('masters.items'))
    else:
        threshold_value = 0

    # Create new item
    item = Item(
        code=code,
        name=name,
        make=make if make else None,
        variant=variant if variant else None,
        description=description if description else None,
        department_id=int(department_id) if department_id and int(department_id) != 0 else None,
        low_stock_threshold=threshold_value
    )

    try:
        db.session.add(item)
        db.session.flush()  # Get the item ID

        # Log audit
        Audit.log(
            entity_type='Item',
            entity_id=item.id,
            action='CREATE',
            user_id=current_user.id,
            details=f'Created item {code} - {name} with threshold {threshold_value}'
        )

        db.session.commit()
        flash('Item created successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error creating item.', 'error')

    return redirect(url_for('masters.items'))

@masters_bp.route('/items/<int:item_id>')
@login_required
@role_required('superadmin', 'manager', 'hod')
def item_detail(item_id):
    try:
        item = Item.query.get_or_404(item_id)
        return render_template('masters/item_detail.html', item=item)
    except Exception as e:
        flash('Error loading item details.', 'error')
        return redirect(url_for('masters.items'))

@masters_bp.route('/items/edit/<int:item_id>', methods=['POST'])
@login_required
@role_required('superadmin')
def edit_item(item_id):
    item = Item.query.get_or_404(item_id)

    try:
        code = request.form.get('code', '').strip()
        name = request.form.get('name', '').strip()
        make = request.form.get('make', '').strip()
        variant = request.form.get('variant', '').strip()
        description = request.form.get('description', '').strip()
        department_id = request.form.get('department_id')
        low_stock_threshold = request.form.get('low_stock_threshold')

        if not code or not name:
            flash('Item code and name are required.', 'error')
            return redirect(url_for('masters.items'))

        # Check if code already exists (excluding current item)
        existing = Item.query.filter(
            Item.code == code, Item.id != item_id
        ).first()
        if existing:
            flash('Item code already exists.', 'error')
            return redirect(url_for('masters.items'))

        item.code = code
        item.name = name
        item.make = make if make else None
        item.variant = variant if variant else None
        item.description = description if description else None
        item.department_id = int(department_id) if department_id and int(department_id) != 0 else None
        item.low_stock_threshold = float(low_stock_threshold) if low_stock_threshold else 0

        # Log audit
        Audit.log(
            entity_type='Item',
            entity_id=item.id,
            action='UPDATE',
            user_id=current_user.id,
            details=f'Updated item {code} - {name}'
        )

        db.session.commit()
        flash('Item updated successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error updating item.', 'error')

    return redirect(url_for('masters.items'))

@masters_bp.route('/items/<int:item_id>/delete', methods=['POST'])
@login_required
@role_required('superadmin')
def delete_item(item_id):
    try:
        item = Item.query.get_or_404(item_id)

        # Log audit before deletion
        Audit.log(
            entity_type='Item',
            entity_id=item.id,
            action='DELETE',
            user_id=current_user.id,
            details=f'Deleted item {item.code} - {item.name}'
        )

        # Soft delete - mark as inactive
        item.is_active = False
        db.session.commit()

        flash('Item deleted successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error deleting item. Item may have associated records.', 'error')

    return redirect(url_for('masters.items'))