
from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from models import (StockEntry, StockIssueRequest, StockIssueLine, Item, Location, 
                   User, Department, UserRole)
from auth import role_required
from database import db
from datetime import datetime, timedelta
from sqlalchemy import desc, func

admin_transactions_bp = Blueprint('admin_transactions', __name__)

@admin_transactions_bp.route('/transaction-history')
@login_required
@role_required('superadmin')
def transaction_history():
    """Admin view for all transaction history"""
    
    # Get filter parameters
    page = request.args.get('page', 1, type=int)
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    transaction_type = request.args.get('transaction_type', 'all')
    location_id = request.args.get('location_id', type=int)
    item_id = request.args.get('item_id', type=int)
    
    # Build the unified transaction list
    transactions = []
    
    # Get stock entries (IN transactions)
    entries_query = db.session.query(
        StockEntry.id.label('transaction_id'),
        StockEntry.created_at.label('transaction_date'),
        StockEntry.quantity_procured.label('quantity'),
        StockEntry.description.label('description'),
        StockEntry.remarks.label('remarks'),
        Item.code.label('item_code'),
        Item.name.label('item_name'),
        Location.office.label('location_office'),
        Location.room.label('location_room'),
        User.full_name.label('user_name'),
        Department.name.label('department_name')
    ).select_from(StockEntry).join(
        Item, StockEntry.item_id == Item.id
    ).join(
        Location, StockEntry.location_id == Location.id
    ).join(
        User, StockEntry.created_by == User.id
    ).outerjoin(
        Department, Item.department_id == Department.id
    )
    
    # Apply filters to entries
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d')
            entries_query = entries_query.filter(StockEntry.created_at >= date_from_obj)
        except ValueError:
            pass
    
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)
            entries_query = entries_query.filter(StockEntry.created_at < date_to_obj)
        except ValueError:
            pass
    
    if location_id:
        entries_query = entries_query.filter(StockEntry.location_id == location_id)
    
    if item_id:
        entries_query = entries_query.filter(StockEntry.item_id == item_id)
    
    # Get stock issues (OUT transactions)
    issues_query = db.session.query(
        StockIssueRequest.id.label('transaction_id'),
        StockIssueRequest.issued_at.label('transaction_date'),
        StockIssueLine.quantity_issued.label('quantity'),
        StockIssueRequest.purpose.label('description'),
        StockIssueLine.remarks.label('remarks'),
        Item.code.label('item_code'),
        Item.name.label('item_name'),
        Location.office.label('location_office'),
        Location.room.label('location_room'),
        User.full_name.label('user_name'),
        Department.name.label('department_name'),
        StockIssueRequest.request_no.label('request_no')
    ).select_from(StockIssueRequest).join(
        StockIssueLine, StockIssueRequest.id == StockIssueLine.request_id
    ).join(
        Item, StockIssueLine.item_id == Item.id
    ).join(
        Location, StockIssueRequest.location_id == Location.id
    ).join(
        User, StockIssueRequest.issued_by == User.id
    ).join(
        Department, StockIssueRequest.department_id == Department.id
    ).filter(
        StockIssueRequest.issued_at.isnot(None),
        StockIssueLine.quantity_issued.isnot(None),
        StockIssueLine.quantity_issued > 0
    )
    
    # Apply filters to issues
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d')
            issues_query = issues_query.filter(StockIssueRequest.issued_at >= date_from_obj)
        except ValueError:
            pass
    
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)
            issues_query = issues_query.filter(StockIssueRequest.issued_at < date_to_obj)
        except ValueError:
            pass
    
    if location_id:
        issues_query = issues_query.filter(StockIssueRequest.location_id == location_id)
    
    if item_id:
        issues_query = issues_query.filter(StockIssueLine.item_id == item_id)
    
    # Execute queries and combine results
    if transaction_type == 'all' or transaction_type == 'entries':
        entries = entries_query.all()
        for entry in entries:
            transactions.append({
                'type': 'entry',
                'id': entry.transaction_id,
                'date': entry.transaction_date,
                'quantity': float(entry.quantity) if entry.quantity else 0,
                'description': entry.description or '',
                'remarks': entry.remarks or '',
                'item_code': entry.item_code or '',
                'item_name': entry.item_name or '',
                'location': f"{entry.location_office or ''} - {entry.location_room or ''}",
                'user': entry.user_name or '',
                'department': entry.department_name or '',
                'reference': f"Stock Entry #{entry.transaction_id}"
            })
    
    if transaction_type == 'all' or transaction_type == 'issues':
        issues = issues_query.all()
        for issue in issues:
            transactions.append({
                'type': 'issue',
                'id': issue.transaction_id,
                'date': issue.transaction_date,
                'quantity': float(issue.quantity) if issue.quantity else 0,
                'description': issue.description or '',
                'remarks': issue.remarks or '',
                'item_code': issue.item_code or '',
                'item_name': issue.item_name or '',
                'location': f"{issue.location_office or ''} - {issue.location_room or ''}",
                'user': issue.user_name or '',
                'department': issue.department_name or '',
                'reference': getattr(issue, 'request_no', None) or f"Issue #{issue.transaction_id}"
            })
    
    # Sort transactions by date (newest first)
    transactions.sort(key=lambda x: x['date'], reverse=True)
    
    # Pagination
    per_page = 50
    total = len(transactions)
    start = (page - 1) * per_page
    end = start + per_page
    paginated_transactions = transactions[start:end]
    
    # Get filter options
    locations = Location.query.all()
    items = Item.query.all()
    
    # Calculate pagination info
    has_prev = page > 1
    has_next = end < total
    prev_num = page - 1 if has_prev else None
    next_num = page + 1 if has_next else None
    pages = (total + per_page - 1) // per_page
    
    # Create a simple object to hold pagination info
    class PaginationInfo:
        def __init__(self, page, per_page, total, pages, has_prev, has_next, prev_num, next_num, items):
            self.page = page
            self.per_page = per_page
            self.total = total
            self.pages = pages
            self.has_prev = has_prev
            self.has_next = has_next
            self.prev_num = prev_num
            self.next_num = next_num
            self.items = items
    
    pagination_info = PaginationInfo(
        page, per_page, total, pages, has_prev, has_next, prev_num, next_num, paginated_transactions
    )
    
    return render_template('admin/transaction_history.html',
                         transactions=pagination_info,
                         locations=locations,
                         items=items,
                         filters={
                             'date_from': date_from,
                             'date_to': date_to,
                             'transaction_type': transaction_type,
                             'location_id': location_id,
                             'item_id': item_id
                         })

@admin_transactions_bp.route('/transaction-summary')
@login_required
@role_required('superadmin')
def transaction_summary():
    """API endpoint for transaction summary statistics"""
    
    # Get date range (default to last 30 days)
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    
    if not date_from:
        date_from = (datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%d')
    if not date_to:
        date_to = datetime.utcnow().strftime('%Y-%m-%d')
    
    try:
        date_from_obj = datetime.strptime(date_from, '%Y-%m-%d')
        date_to_obj = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)
    except ValueError:
        return jsonify({'error': 'Invalid date format'}), 400
    
    # Count stock entries
    entries_count = StockEntry.query.filter(
        StockEntry.created_at >= date_from_obj,
        StockEntry.created_at < date_to_obj
    ).count()
    
    # Sum total quantity in
    total_quantity_in = db.session.query(
        func.sum(StockEntry.quantity_procured)
    ).filter(
        StockEntry.created_at >= date_from_obj,
        StockEntry.created_at < date_to_obj
    ).scalar() or 0
    
    # Count stock issues
    issues_count = StockIssueRequest.query.filter(
        StockIssueRequest.issued_at >= date_from_obj,
        StockIssueRequest.issued_at < date_to_obj,
        StockIssueRequest.issued_at.isnot(None)
    ).count()
    
    # Sum total quantity out
    total_quantity_out = db.session.query(
        func.sum(StockIssueLine.quantity_issued)
    ).join(
        StockIssueRequest, StockIssueLine.request_id == StockIssueRequest.id
    ).filter(
        StockIssueRequest.issued_at >= date_from_obj,
        StockIssueRequest.issued_at < date_to_obj,
        StockIssueRequest.issued_at.isnot(None),
        StockIssueLine.quantity_issued.isnot(None)
    ).scalar() or 0
    
    return jsonify({
        'entries_count': entries_count,
        'issues_count': issues_count,
        'total_quantity_in': float(total_quantity_in),
        'total_quantity_out': float(total_quantity_out),
        'net_movement': float(total_quantity_in - total_quantity_out),
        'date_range': {
            'from': date_from,
            'to': date_to
        }
    })
