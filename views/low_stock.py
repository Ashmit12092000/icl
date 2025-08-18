
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from models import Item, StockBalance, Location, Audit
from auth import role_required
from database import db
from sqlalchemy import and_

low_stock_bp = Blueprint('low_stock', __name__)

@low_stock_bp.route('/alerts')
@login_required
def alerts():
    """Show low stock alerts"""
    location_id = request.args.get('location_id')
    
    # Base query for low stock items
    query = db.session.query(
        Item, StockBalance, Location
    ).select_from(Item).join(
        StockBalance, Item.id == StockBalance.item_id
    ).join(
        Location, StockBalance.location_id == Location.id
    ).filter(
        StockBalance.quantity <= Item.low_stock_threshold
    )
    
    # Filter by location if specified
    if location_id:
        query = query.filter(StockBalance.location_id == location_id)
    
    # Filter by user's accessible warehouses
    if current_user.role != 'superadmin':
        accessible_location_ids = [loc.id for loc in current_user.get_accessible_warehouses()]
        if accessible_location_ids:
            query = query.filter(StockBalance.location_id.in_(accessible_location_ids))
    
    low_stock_items = query.order_by(StockBalance.quantity.asc()).all()
    
    # Get locations for filter
    if current_user.role == 'superadmin':
        locations = Location.query.all()
    else:
        locations = current_user.get_accessible_warehouses()
    
    return render_template('stock/low_stock_alerts.html',
                         low_stock_items=low_stock_items,
                         locations=locations,
                         selected_location=location_id)

@low_stock_bp.route('/summary')
@login_required
def summary():
    """Get low stock summary for dashboard"""
    # Count low stock items by location
    query = db.session.query(
        Location.id,
        Location.office,
        Location.room,
        db.func.count(StockBalance.id).label('low_stock_count')
    ).join(StockBalance).join(Item).filter(
        StockBalance.quantity <= Item.low_stock_threshold
    )
    
    # Filter by user's accessible warehouses
    if current_user.role != 'superadmin':
        accessible_location_ids = [loc.id for loc in current_user.get_accessible_warehouses()]
        if accessible_location_ids:
            query = query.filter(Location.id.in_(accessible_location_ids))
    
    summary_data = query.group_by(Location.id).all()
    
    return jsonify([{
        'location_id': item.id,
        'location_name': f"{item.office} - {item.room}",
        'low_stock_count': item.low_stock_count
    } for item in summary_data])

@low_stock_bp.route('/update-threshold/<int:item_id>', methods=['POST'])
@login_required
@role_required('superadmin', 'manager')
def update_threshold(item_id):
    """Update low stock threshold for an item"""
    item = Item.query.get_or_404(item_id)
    new_threshold = request.form.get('threshold')
    
    if not new_threshold:
        flash('Threshold value is required.', 'error')
        return redirect(url_for('low_stock.alerts'))
    
    try:
        threshold_value = float(new_threshold)
        if threshold_value < 0:
            flash('Threshold must be a positive number.', 'error')
            return redirect(url_for('low_stock.alerts'))
        
        old_threshold = item.low_stock_threshold
        item.low_stock_threshold = threshold_value
        
        # Log audit
        Audit.log(
            entity_type='Item',
            entity_id=item.id,
            action='UPDATE_THRESHOLD',
            user_id=current_user.id,
            details=f'Changed low stock threshold from {old_threshold} to {threshold_value}'
        )
        
        db.session.commit()
        flash(f'Low stock threshold updated for {item.name}.', 'success')
        
    except ValueError:
        flash('Invalid threshold value.', 'error')
    
    return redirect(url_for('low_stock.alerts'))
