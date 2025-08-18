
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from models import User, Location, user_warehouse_assignments, Audit
from database import db
from auth import role_required

warehouse_management_bp = Blueprint('warehouse_management', __name__)

@warehouse_management_bp.route('/warehouse-assignments')
@login_required
@role_required('superadmin', 'manager')
def warehouse_assignments():
    """View and manage warehouse assignments"""
    users = User.query.filter_by(is_active=True).all()
    warehouses = Location.query.all()
    
    # Get current assignments
    assignments = {}
    for user in users:
        assignments[user.id] = [w.id for w in user.assigned_warehouses]
    
    return render_template('warehouse_management/assignments.html', 
                         users=users, 
                         warehouses=warehouses, 
                         assignments=assignments)

@warehouse_management_bp.route('/users/<int:user_id>/assign-warehouses', methods=['POST'])
@login_required
@role_required('superadmin', 'manager')
def assign_warehouses(user_id):
    """Assign multiple warehouses to a user"""
    user = User.query.get_or_404(user_id)
    warehouse_ids = request.form.getlist('warehouse_ids')
    
    # Clear existing assignments
    user.assigned_warehouses.clear()
    
    # Add new assignments
    for warehouse_id in warehouse_ids:
        warehouse = Location.query.get(int(warehouse_id))
        if warehouse:
            user.assigned_warehouses.append(warehouse)
    
    # Log audit
    Audit.log(
        entity_type='User',
        entity_id=user.id,
        action='WAREHOUSE_ASSIGN',
        user_id=current_user.id,
        details=f'Assigned warehouses: {warehouse_ids}'
    )
    
    try:
        db.session.commit()
        flash(f'Warehouse assignments updated for {user.full_name}', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error updating warehouse assignments', 'error')
    
    return redirect(url_for('warehouse_management.warehouse_assignments'))

@warehouse_management_bp.route('/api/user-warehouses/<int:user_id>')
@login_required
def get_user_warehouses(user_id):
    """API endpoint to get user's assigned warehouses"""
    user = User.query.get_or_404(user_id)
    warehouses = [{'id': w.id, 'name': f"{w.office} - {w.room}", 'code': w.code} 
                 for w in user.assigned_warehouses]
    return jsonify(warehouses)
