
from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from models import (StockIssueRequest, StockIssueLine, StockReturn, Item, Location, 
                   User, Department, UserRole, ReturnStatus, RequestStatus, Audit)
from auth import role_required
from database import db
from datetime import datetime, timedelta
from sqlalchemy import desc, func, and_, or_

audit_bp = Blueprint('audit', __name__)

@audit_bp.route('/issue-return-tracker')
@login_required
@role_required('superadmin', 'hod')
def issue_return_tracker():
    """Comprehensive audit page for tracking issued items and returns"""
    
    # Get filter parameters
    page = request.args.get('page', 1, type=int)
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    status_filter = request.args.get('status')
    department_id = request.args.get('department_id', type=int)
    item_id = request.args.get('item_id', type=int)
    user_id = request.args.get('user_id', type=int)
    
    # Base query for audit records
    audit_records = []
    
    # Get issued items with their return details
    issues_query = db.session.query(
        StockIssueRequest.id.label('request_id'),
        StockIssueRequest.request_no,
        StockIssueRequest.issued_at,
        StockIssueRequest.status.label('request_status'),
        StockIssueLine.id.label('line_id'),
        StockIssueLine.quantity_issued,
        Item.code.label('item_code'),
        Item.name.label('item_name'),
        Location.office.label('location_office'),
        Location.room.label('location_room'),
        User.full_name.label('requester_name'),
        User.username.label('requester_username'),
        Department.name.label('department_name'),
        Department.code.label('department_code'),
        func.coalesce(func.sum(StockReturn.quantity_returned), 0).label('total_returned'),
        func.count(StockReturn.id).label('return_count'),
        func.max(StockReturn.created_at).label('last_return_date')
    ).select_from(StockIssueRequest).join(
        StockIssueLine, StockIssueRequest.id == StockIssueLine.request_id
    ).join(
        Item, StockIssueLine.item_id == Item.id
    ).join(
        Location, StockIssueRequest.location_id == Location.id
    ).join(
        User, StockIssueRequest.requester_id == User.id
    ).join(
        Department, StockIssueRequest.department_id == Department.id
    ).outerjoin(
        StockReturn, and_(
            StockIssueLine.id == StockReturn.issue_line_id,
            StockReturn.status == ReturnStatus.COMPLETED
        )
    ).filter(
        StockIssueRequest.status == RequestStatus.ISSUED,
        StockIssueLine.quantity_issued.isnot(None),
        StockIssueLine.quantity_issued > 0
    )
    
    # Apply department filter based on user role
    if current_user.role == UserRole.HOD:
        if current_user.managed_department:
            issues_query = issues_query.filter(
                StockIssueRequest.department_id == current_user.managed_department.id
            )
        else:
            # HOD with no managed department sees nothing
            issues_query = issues_query.filter(False)
    
    # Apply filters
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
    
    if department_id and current_user.role == UserRole.SUPERADMIN:
        issues_query = issues_query.filter(StockIssueRequest.department_id == department_id)
    
    if item_id:
        issues_query = issues_query.filter(StockIssueLine.item_id == item_id)
    
    if user_id:
        issues_query = issues_query.filter(StockIssueRequest.requester_id == user_id)
    
    # Group by relevant fields
    issues_query = issues_query.group_by(
        StockIssueRequest.id,
        StockIssueRequest.request_no,
        StockIssueRequest.issued_at,
        StockIssueRequest.status,
        StockIssueLine.id,
        StockIssueLine.quantity_issued,
        Item.code,
        Item.name,
        Location.office,
        Location.room,
        User.full_name,
        User.username,
        Department.name,
        Department.code
    ).order_by(desc(StockIssueRequest.issued_at))
    
    # Apply status filter
    if status_filter:
        if status_filter == 'fully_returned':
            issues_query = issues_query.having(
                func.coalesce(func.sum(StockReturn.quantity_returned), 0) >= StockIssueLine.quantity_issued
            )
        elif status_filter == 'partially_returned':
            issues_query = issues_query.having(
                and_(
                    func.coalesce(func.sum(StockReturn.quantity_returned), 0) > 0,
                    func.coalesce(func.sum(StockReturn.quantity_returned), 0) < StockIssueLine.quantity_issued
                )
            )
        elif status_filter == 'not_returned':
            issues_query = issues_query.having(
                func.coalesce(func.sum(StockReturn.quantity_returned), 0) == 0
            )
        elif status_filter == 'overdue':
            # Items issued more than 30 days ago and not fully returned
            overdue_date = datetime.utcnow() - timedelta(days=30)
            issues_query = issues_query.filter(
                StockIssueRequest.issued_at < overdue_date
            ).having(
                func.coalesce(func.sum(StockReturn.quantity_returned), 0) < StockIssueLine.quantity_issued
            )
    
    # Execute query with pagination
    per_page = 25
    total_query = issues_query.statement.compile(compile_kwargs={"literal_binds": True})
    total = len(list(issues_query.all()))
    
    # Apply pagination
    start = (page - 1) * per_page
    paginated_issues = issues_query.offset(start).limit(per_page).all()
    
    # Process results to add calculated fields
    audit_data = []
    for issue in paginated_issues:
        # Calculate return status
        quantity_remaining = float(issue.quantity_issued) - float(issue.total_returned)
        
        if issue.total_returned == 0:
            return_status = 'Not Returned'
            return_status_class = 'bg-red-900 text-red-200'
        elif quantity_remaining <= 0:
            return_status = 'Fully Returned'
            return_status_class = 'bg-green-900 text-green-200'
        else:
            return_status = 'Partially Returned'
            return_status_class = 'bg-yellow-900 text-yellow-200'
        
        # Check if overdue (more than 30 days and not fully returned)
        days_since_issue = (datetime.utcnow() - issue.issued_at).days if issue.issued_at else 0
        is_overdue = days_since_issue > 30 and quantity_remaining > 0
        
        audit_data.append({
            'request_id': issue.request_id,
            'request_no': issue.request_no,
            'line_id': issue.line_id,
            'issued_at': issue.issued_at,
            'item_code': issue.item_code,
            'item_name': issue.item_name,
            'location': f"{issue.location_office} - {issue.location_room}",
            'requester_name': issue.requester_name,
            'requester_username': issue.requester_username,
            'department_name': issue.department_name,
            'department_code': issue.department_code,
            'quantity_issued': float(issue.quantity_issued),
            'total_returned': float(issue.total_returned),
            'quantity_remaining': quantity_remaining,
            'return_count': issue.return_count,
            'last_return_date': issue.last_return_date,
            'return_status': return_status,
            'return_status_class': return_status_class,
            'days_since_issue': days_since_issue,
            'is_overdue': is_overdue
        })
    
    # Calculate pagination info
    has_prev = page > 1
    has_next = start + per_page < total
    prev_num = page - 1 if has_prev else None
    next_num = page + 1 if has_next else None
    pages = (total + per_page - 1) // per_page
    
    # Get filter options
    if current_user.role == UserRole.SUPERADMIN:
        departments = Department.query.all()
        users = User.query.filter_by(is_active=True).all()
        items = Item.query.all()
    else:
        # HOD sees only their department data
        departments = [current_user.managed_department] if current_user.managed_department else []
        users = User.query.filter_by(
            department_id=current_user.managed_department.id if current_user.managed_department else None,
            is_active=True
        ).all()
        items = Item.query.filter_by(
            department_id=current_user.managed_department.id if current_user.managed_department else None
        ).all()
    
    # Create pagination object
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
    
    pagination = PaginationInfo(
        page, per_page, total, pages, has_prev, has_next, prev_num, next_num, audit_data
    )
    
    # Calculate summary statistics
    summary_stats = calculate_audit_summary(current_user, date_from, date_to, department_id)
    
    return render_template('audit/issue_return_tracker.html',
                         audit_data=pagination,
                         departments=departments,
                         users=users,
                         items=items,
                         summary_stats=summary_stats,
                         filters={
                             'date_from': date_from,
                             'date_to': date_to,
                             'status': status_filter,
                             'department_id': department_id,
                             'item_id': item_id,
                             'user_id': user_id
                         })

def calculate_audit_summary(user, date_from=None, date_to=None, department_id=None):
    """Calculate summary statistics for the audit dashboard"""
    
    # Base query for issued items
    base_query = db.session.query(StockIssueLine).join(
        StockIssueRequest
    ).filter(
        StockIssueRequest.status == RequestStatus.ISSUED,
        StockIssueLine.quantity_issued.isnot(None),
        StockIssueLine.quantity_issued > 0
    )
    
    # Apply user role filter
    if user.role == UserRole.HOD and user.managed_department:
        base_query = base_query.filter(
            StockIssueRequest.department_id == user.managed_department.id
        )
    
    # Apply date filters
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d')
            base_query = base_query.filter(StockIssueRequest.issued_at >= date_from_obj)
        except ValueError:
            pass
    
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)
            base_query = base_query.filter(StockIssueRequest.issued_at < date_to_obj)
        except ValueError:
            pass
    
    if department_id and user.role == UserRole.SUPERADMIN:
        base_query = base_query.filter(StockIssueRequest.department_id == department_id)
    
    # Calculate statistics
    total_items_issued = base_query.count()
    total_quantity_issued = base_query.with_entities(
        func.sum(StockIssueLine.quantity_issued)
    ).scalar() or 0
    
    # Items with returns
    items_with_returns = base_query.join(
        StockReturn, StockIssueLine.id == StockReturn.issue_line_id
    ).filter(
        StockReturn.status == ReturnStatus.COMPLETED
    ).with_entities(StockIssueLine.id).distinct().count()
    
    # Total returned quantity
    total_returned = db.session.query(
        func.sum(StockReturn.quantity_returned)
    ).join(
        StockIssueLine, StockReturn.issue_line_id == StockIssueLine.id
    ).join(
        StockIssueRequest, StockIssueLine.request_id == StockIssueRequest.id
    ).filter(
        StockReturn.status == ReturnStatus.COMPLETED,
        StockIssueRequest.status == RequestStatus.ISSUED
    )
    
    # Apply same filters to return query
    if user.role == UserRole.HOD and user.managed_department:
        total_returned = total_returned.filter(
            StockIssueRequest.department_id == user.managed_department.id
        )
    
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d')
            total_returned = total_returned.filter(StockIssueRequest.issued_at >= date_from_obj)
        except ValueError:
            pass
    
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)
            total_returned = total_returned.filter(StockIssueRequest.issued_at < date_to_obj)
        except ValueError:
            pass
    
    if department_id and user.role == UserRole.SUPERADMIN:
        total_returned = total_returned.filter(StockIssueRequest.department_id == department_id)
    
    total_returned = total_returned.scalar() or 0
    
    # Overdue items (issued more than 30 days ago and not fully returned)
    overdue_date = datetime.utcnow() - timedelta(days=30)
    overdue_items = base_query.filter(
        StockIssueRequest.issued_at < overdue_date
    ).count()
    
    # Calculate percentages
    return_rate = round((items_with_returns / total_items_issued * 100) if total_items_issued > 0 else 0, 1)
    quantity_return_rate = round((float(total_returned) / float(total_quantity_issued) * 100) if total_quantity_issued > 0 else 0, 1)
    
    return {
        'total_items_issued': total_items_issued,
        'total_quantity_issued': float(total_quantity_issued),
        'items_with_returns': items_with_returns,
        'total_returned': float(total_returned),
        'overdue_items': overdue_items,
        'return_rate': return_rate,
        'quantity_return_rate': quantity_return_rate,
        'outstanding_quantity': float(total_quantity_issued) - float(total_returned)
    }

@audit_bp.route('/return-details/<int:line_id>')
@login_required
@role_required('superadmin', 'hod')
def return_details(line_id):
    """Get detailed return information for a specific issue line"""
    
    issue_line = StockIssueLine.query.get_or_404(line_id)
    
    # Check access permissions
    if (current_user.role == UserRole.HOD and 
        current_user.managed_department and
        issue_line.request.department_id != current_user.managed_department.id):
        return jsonify({'error': 'Access denied'}), 403
    
    returns = StockReturn.query.filter_by(
        issue_line_id=line_id
    ).order_by(desc(StockReturn.created_at)).all()
    
    return_data = []
    for ret in returns:
        return_data.append({
            'return_no': ret.return_no,
            'quantity_returned': float(ret.quantity_returned),
            'return_reason': ret.return_reason,
            'status': ret.status.value,
            'created_at': ret.created_at.strftime('%Y-%m-%d %H:%M'),
            'returner_name': ret.returner.full_name if ret.returner else '',
            'processor_name': ret.processor.full_name if ret.processor else '',
            'processed_at': ret.processed_at.strftime('%Y-%m-%d %H:%M') if ret.processed_at else '',
            'remarks': ret.remarks or ''
        })
    
    return jsonify({
        'returns': return_data,
        'total_returned': sum(float(r.quantity_returned) for r in returns if r.status == ReturnStatus.COMPLETED),
        'quantity_issued': float(issue_line.quantity_issued) if issue_line.quantity_issued else 0
    })
