from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
from models import User, UserRole, Department, Employee, Location, Audit
from forms import UserForm
from database import db
from auth import role_required

user_management_bp = Blueprint('user_management', __name__)

@user_management_bp.route('/users')
@login_required
@role_required('superadmin')
def users():
    users = User.query.order_by(User.created_at.desc()).all()
    departments = Department.query.all()
    locations = Location.query.all()
    # Get employees that don't have user accounts assigned
    unassigned_employees = Employee.query.filter_by(user_id=None).all()
    return render_template('user_management/users.html', users=users, departments=departments, locations=locations, unassigned_employees=unassigned_employees)

@user_management_bp.route('/users/create', methods=['POST'])
@login_required
@role_required('superadmin')
def create_user():
    username = request.form.get('username', '').strip()
    email = request.form.get('email', '').strip()
    password = request.form.get('password', '').strip()
    role = request.form.get('role')
    department_id = request.form.get('department_id')
    employee_id = request.form.get('employee_id')

    # Derive full_name from linked employee or use username
    full_name = username  # Default fallback
    if employee_id:
        employee = Employee.query.get(int(employee_id))
        if employee:
            full_name = employee.name

    if not username or not email or not password or not role:
        flash('Username, email, password, and role are required.', 'error')
        return redirect(url_for('user_management.users'))

    # Check if username already exists
    if User.query.filter_by(username=username).first():
        flash('Username already exists.', 'error')
        return redirect(url_for('user_management.users'))

    # Check if email already exists
    if User.query.filter_by(email=email).first():
        flash('Email already exists.', 'error')
        return redirect(url_for('user_management.users'))

    # Validate role
    try:
        user_role = UserRole(role)
    except ValueError:
        flash('Invalid role selected.', 'error')
        return redirect(url_for('user_management.users'))

    # Get department from employee if employee is selected
    final_department_id = None
    if employee_id:
        employee = Employee.query.get(int(employee_id))
        if employee:
            final_department_id = employee.department_id
    elif department_id:
        final_department_id = int(department_id)

    # Managers should not have department assignments
    if user_role == UserRole.MANAGER:
        final_department_id = None

    # Department validation
    if user_role in [UserRole.HOD, UserRole.EMPLOYEE]:
        if not final_department_id:
            flash('Department is required for HOD and Employee roles.', 'error')
            return redirect(url_for('user_management.users'))

        # Check if department already has an HOD
        if user_role == UserRole.HOD:
            existing_hod = Department.query.filter(
                Department.id == final_department_id,
                Department.hod_id.isnot(None)
            ).first()
            if existing_hod:
                flash('Department already has an HOD assigned.', 'error')
                return redirect(url_for('user_management.users'))

    try:
        user = User(
            username=username,
            password_hash=generate_password_hash(password),
            full_name=full_name,
            email=email,
            role=user_role,
            department_id=final_department_id
        )

        db.session.add(user)
        db.session.flush()  # Get the user ID

        # Link employee to user if employee was selected
        if employee_id:
            employee = Employee.query.get(int(employee_id))
            if employee:
                employee.user_id = user.id

        # If HOD, update department
        if user_role == UserRole.HOD and final_department_id:
            department = Department.query.get(final_department_id)
            if department:
                department.hod_id = user.id

        # Handle warehouse assignments
        warehouse_ids = request.form.getlist('warehouse_ids')
        
        # If user is a superadmin or manager, assign all warehouses automatically
        if user_role in [UserRole.SUPERADMIN, UserRole.MANAGER]:
            all_warehouses = Location.query.all()
            for warehouse in all_warehouses:
                user.assigned_warehouses.append(warehouse)
        elif warehouse_ids:
            warehouses = Location.query.filter(Location.id.in_(warehouse_ids)).all()
            for warehouse in warehouses:
                user.assigned_warehouses.append(warehouse)

        # Log audit
        Audit.log(
            entity_type='User',
            entity_id=user.id,
            action='CREATE',
            user_id=current_user.id,
            details=f'Created user {username} with role {role}'
        )

        db.session.commit()
        flash('User created successfully.', 'success')

    except Exception as e:
        db.session.rollback()
        flash('Error creating user.', 'error')

    return redirect(url_for('user_management.users'))

@user_management_bp.route('/users/<int:user_id>/update', methods=['POST'])
@login_required
@role_required('superadmin')
def update_user(user_id):
    user = User.query.get_or_404(user_id)

    # Prevent updating superadmin user
    if user.role == UserRole.SUPERADMIN and user.id != current_user.id:
        flash('Cannot modify other superadmin users.', 'error')
        return redirect(url_for('user_management.users'))

    email = request.form.get('email', '').strip()
    role = request.form.get('role')
    department_id = request.form.get('department_id')
    is_active = bool(request.form.get('is_active'))

    if not email or not role:
        flash('Email and role are required.', 'error')
        return redirect(url_for('user_management.users'))

    # Check if email already exists (excluding current user)
    existing_email = User.query.filter(
        User.email == email, User.id != user_id
    ).first()
    if existing_email:
        flash('Email already exists.', 'error')
        return redirect(url_for('user_management.users'))

    # Validate role
    try:
        user_role = UserRole(role)
    except ValueError:
        flash('Invalid role selected.', 'error')
        return redirect(url_for('user_management.users'))

    # Remove user as HOD if role is changing from HOD
    if user.role == UserRole.HOD and user_role != UserRole.HOD:
        if user.managed_department:
            user.managed_department.hod_id = None

    # Department validation
    if user_role in [UserRole.HOD, UserRole.EMPLOYEE]:
        if not department_id:
            flash('Department is required for HOD and Employee roles.', 'error')
            return redirect(url_for('user_management.users'))

        # Check if department already has an HOD (excluding current user)
        if user_role == UserRole.HOD:
            existing_hod = Department.query.filter(
                Department.id == int(department_id),
                Department.hod_id.isnot(None),
                Department.hod_id != user_id
            ).first()
            if existing_hod:
                flash('Department already has an HOD assigned.', 'error')
                return redirect(url_for('user_management.users'))

    try:
        # Update user
        user.email = email
        user.role = user_role
        user.department_id = int(department_id) if department_id else None
        user.is_active = is_active

        # Update department HOD if needed
        if user_role == UserRole.HOD and department_id:
            department = Department.query.get(int(department_id))
            if department:
                department.hod_id = user.id

        # Handle warehouse assignments
        user.assigned_warehouses.clear()  # Remove existing assignments
        warehouse_ids = request.form.getlist('warehouse_ids')
        
        # If user is a superadmin or manager, assign all warehouses automatically
        if user_role in [UserRole.SUPERADMIN, UserRole.MANAGER]:
            all_warehouses = Location.query.all()
            for warehouse in all_warehouses:
                user.assigned_warehouses.append(warehouse)
        elif warehouse_ids:
            warehouses = Location.query.filter(Location.id.in_(warehouse_ids)).all()
            for warehouse in warehouses:
                user.assigned_warehouses.append(warehouse)

        # Log audit
        Audit.log(
            entity_type='User',
            entity_id=user.id,
            action='UPDATE',
            user_id=current_user.id,
            details=f'Updated user {user.username}'
        )

        db.session.commit()
        flash('User updated successfully.', 'success')

    except Exception as e:
        db.session.rollback()
        flash('Error updating user.', 'error')

    return redirect(url_for('user_management.users'))

@user_management_bp.route('/users/<int:user_id>/reset-password', methods=['POST'])
@login_required
@role_required('superadmin')
def reset_password(user_id):
    user = User.query.get_or_404(user_id)

    # Prevent resetting superadmin password
    if user.role == UserRole.SUPERADMIN and user.id != current_user.id:
        flash('Cannot reset other superadmin passwords.', 'error')
        return redirect(url_for('user_management.users'))

    new_password = request.form.get('new_password', '').strip()

    if not new_password or len(new_password) < 6:
        flash('Password must be at least 6 characters long.', 'error')
        return redirect(url_for('user_management.users'))

    try:
        user.password_hash = generate_password_hash(new_password)

        # Log audit
        Audit.log(
            entity_type='User',
            entity_id=user.id,
            action='PASSWORD_RESET',
            user_id=current_user.id,
            details=f'Reset password for user {user.username}'
        )

        db.session.commit()
        flash('Password reset successfully.', 'success')

    except Exception as e:
        db.session.rollback()
        flash('Error resetting password.', 'error')

    return redirect(url_for('user_management.users'))

@user_management_bp.route('/users/<int:user_id>/assign_department', methods=['POST'])
@login_required
@role_required('superadmin', 'manager')
def assign_department(user_id):
    user = User.query.get_or_404(user_id)
    department_id = request.form.get('department_id')

    if not department_id:
        flash('Please select a department.', 'error')
        return redirect(url_for('user_management.users'))

    department = Department.query.get(int(department_id))
    if not department:
        flash('Invalid department selected.', 'error')
        return redirect(url_for('user_management.users'))

    # If assigning HOD role, check if department already has HOD
    if user.role == UserRole.HOD:
        existing_hod_dept = Department.query.filter_by(hod_id=user.id).first()
        if existing_hod_dept and existing_hod_dept.id != int(department_id):
            flash(f'User is already HOD of {existing_hod_dept.name}. Remove them first.', 'error')
            return redirect(url_for('user_management.users'))

        # Check if target department already has HOD
        if department.hod_id and department.hod_id != user.id:
            flash(f'Department {department.name} already has an HOD assigned.', 'error')
            return redirect(url_for('user_management.users'))

    user.department_id = int(department_id)

    # If user is HOD, also assign them as department HOD
    if user.role == UserRole.HOD:
        department.hod_id = user.id

    try:
        db.session.commit()
        flash(f'Department assigned to {user.full_name} successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error assigning department.', 'error')

    return redirect(url_for('user_management.users'))