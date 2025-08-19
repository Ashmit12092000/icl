from flask import Blueprint, render_template, request
from flask_login import login_required, current_user
from models import Location, StockBalance, Item
from database import db
from sqlalchemy import func

location_inventory_bp = Blueprint('location_inventory', __name__)


@location_inventory_bp.route('/location-inventory')
@login_required
def location_inventory():
    """Show inventory details by location"""
    location_filter = request.args.get('location', '')
    item_filter = request.args.get('item', '')

    # Base query to get location inventory data
    query = db.session.query(Location.id.label('location_id'),
                             Location.office, Location.room,
                             Location.code.label('location_code'),
                             Item.id.label('item_id'),
                             Item.code.label('item_code'),
                             Item.name.label('item_name'),
                             StockBalance.quantity, Item.low_stock_threshold,
                             Item.department_id).select_from(Location).join(
                                 StockBalance,
                                 Location.id == StockBalance.location_id).join(
                                     Item, StockBalance.item_id == Item.id)

    # Apply user access restrictions
    if current_user.role.value not in ['superadmin', 'manager']:
        accessible_warehouses = current_user.get_accessible_warehouses()
        if accessible_warehouses:
            warehouse_ids = [w.id for w in accessible_warehouses]
            query = query.filter(Location.id.in_(warehouse_ids))
        else:
            # No warehouse access - show no data
            query = query.filter(Location.id == -1)

    # Apply filters
    if location_filter:
        query = query.filter(Location.office.contains(location_filter))
    if item_filter:
        query = query.filter(Item.name.contains(item_filter))

    # Order by location and item
    inventory_data = query.order_by(Location.office, Location.room,
                                    Item.name).all()

    # Group data by location for better presentation
    locations_inventory = {}
    for record in inventory_data:
        location_key = f"{record.office} - {record.room}"
        if location_key not in locations_inventory:
            locations_inventory[location_key] = {
                'location_id': record.location_id,
                'location_code': record.location_code,
                'office': record.office,
                'room': record.room,
                'item_list': [],
                'total_items': 0,
                'low_stock_items': 0
            }

        # Check if item is low stock
        is_low_stock = record.quantity <= record.low_stock_threshold
        if is_low_stock:
            locations_inventory[location_key]['low_stock_items'] += 1

        # Get department name if department_id exists
        department_name = None
        if record.department_id:
            from models import Department
            department = Department.query.get(record.department_id)
            if department:
                department_name = department.name

        locations_inventory[location_key]['item_list'].append({
            'item_id':
            record.item_id,
            'item_code':
            record.item_code,
            'item_name':
            record.item_name,
            'quantity':
            record.quantity,
            'low_stock_threshold':
            record.low_stock_threshold,
            'is_low_stock':
            is_low_stock,
            'department':
            department_name
        })
        locations_inventory[location_key]['total_items'] += 1

    # Get filter options based on user permissions
    if current_user.role.value in ['superadmin', 'manager']:
        locations = Location.query.all()
    else:
        locations = current_user.get_accessible_warehouses()

    items = Item.query.all()

    return render_template('location_inventory/inventory.html',
                           locations_inventory=locations_inventory,
                           locations=locations,
                           items=items,
                           location_filter=location_filter,
                           item_filter=item_filter)