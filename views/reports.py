from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, make_response
from flask_login import login_required, current_user
from models import *
from database import db
from auth import role_required
from sqlalchemy import func, and_, extract, case
from datetime import datetime, timedelta
import json
import csv
from io import StringIO

reports_bp = Blueprint('reports', __name__)

@reports_bp.route('/reports')
@login_required
@role_required('superadmin', 'manager', 'hod')
def dashboard():
    # Get date range from request or default to last 30 days
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)

    # Override with custom dates if provided
    if request.args.get('start_date'):
        start_date = datetime.strptime(request.args.get('start_date'), '%Y-%m-%d')
    if request.args.get('end_date'):
        end_date = datetime.strptime(request.args.get('end_date'), '%Y-%m-%d')

    # Basic statistics
    stats = {
        'total_users': User.query.filter_by(is_active=True).count(),
        'total_departments': Department.query.count(),
        'total_items': Item.query.count(),
        'total_locations': Location.query.count(),
        'total_requests': StockIssueRequest.query.count(),
        'pending_requests': StockIssueRequest.query.filter_by(status=RequestStatus.PENDING).count(),
        'approved_requests': StockIssueRequest.query.filter_by(status=RequestStatus.APPROVED).count(),
        'issued_requests': StockIssueRequest.query.filter_by(status=RequestStatus.ISSUED).count(),
        'rejected_requests': StockIssueRequest.query.filter_by(status=RequestStatus.REJECTED).count(),
    }

    # Monthly request trends (last 12 months)
    monthly_data = []
    for i in range(12):
        month_start = (datetime.now().replace(day=1) - timedelta(days=i*30)).replace(day=1)
        month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)

        count = StockIssueRequest.query.filter(
            StockIssueRequest.created_at >= month_start,
            StockIssueRequest.created_at <= month_end
        ).count()

        monthly_data.append({
            'month': month_start.strftime('%b %Y'),
            'requests': count
        })

    monthly_data.reverse()

    # Department-wise statistics
    department_stats = []
    departments = Department.query.all()
    for dept in departments:
        dept_requests = StockIssueRequest.query.filter_by(department_id=dept.id).count()
        dept_issued = StockIssueRequest.query.filter_by(
            department_id=dept.id, 
            status=RequestStatus.ISSUED
        ).count()

        department_stats.append({
            'name': dept.name,
            'total_requests': dept_requests,
            'issued_requests': dept_issued,
            'efficiency': round((dept_issued / dept_requests * 100) if dept_requests > 0 else 0, 1)
        })

    # Top requested items
    top_items = db.session.query(
        Item.name,
        func.sum(StockIssueLine.quantity_requested).label('total_quantity'),
        func.count(StockIssueLine.id).label('request_count')
    ).join(StockIssueLine).join(StockIssueRequest).filter(
        StockIssueRequest.status == RequestStatus.ISSUED
    ).group_by(Item.id).order_by(
        func.sum(StockIssueLine.quantity_requested).desc()
    ).limit(10).all()

    # Low stock alerts count
    low_stock_count = db.session.query(StockBalance).join(Item).filter(
        StockBalance.quantity <= Item.low_stock_threshold
    ).count()

    # Recent activity (last 7 days)
    recent_activity = StockIssueRequest.query.filter(
        StockIssueRequest.created_at >= datetime.now() - timedelta(days=7)
    ).order_by(StockIssueRequest.created_at.desc()).limit(10).all()

    # Status distribution
    status_distribution = []
    for status in RequestStatus:
        count = StockIssueRequest.query.filter_by(status=status).count()
        status_distribution.append({
            'status': status.value,
            'count': count,
            'percentage': round((count / stats['total_requests'] * 100) if stats['total_requests'] > 0 else 0, 1)
        })

    return render_template('reports/dashboard.html',
                         stats=stats,
                         monthly_data=monthly_data,
                         department_stats=department_stats,
                         top_items=top_items,
                         low_stock_count=low_stock_count,
                         recent_activity=recent_activity,
                         status_distribution=status_distribution,
                         start_date=start_date.strftime('%Y-%m-%d'),
                         end_date=end_date.strftime('%Y-%m-%d'))

@reports_bp.route('/reports/export')
@login_required
@role_required('superadmin', 'manager', 'hod')
def export_data():
    export_type = request.args.get('type', 'requests')
    format_type = request.args.get('format', 'csv')

    if export_type == 'requests':
        return export_requests(format_type)
    elif export_type == 'stock':
        return export_stock_balances(format_type)
    elif export_type == 'departments':
        return export_department_stats(format_type)
    else:
        flash('Invalid export type', 'error')
        return redirect(url_for('reports.dashboard'))

def export_requests(format_type):
    requests = db.session.query(
        StockIssueRequest.request_no,
        StockIssueRequest.created_at,
        User.full_name.label('requester'),
        Department.name.label('department'),
        StockIssueRequest.purpose,
        StockIssueRequest.status,
        StockIssueRequest.approved_at,
        StockIssueRequest.issued_at
    ).join(User, StockIssueRequest.requester_id == User.id)\
     .join(Department, StockIssueRequest.department_id == Department.id)\
     .order_by(StockIssueRequest.created_at.desc()).all()

    if format_type == 'csv':
        output = StringIO()
        writer = csv.writer(output)

        # Headers
        writer.writerow(['Request No', 'Created Date', 'Requester', 'Department', 
                        'Purpose', 'Status', 'Approved Date', 'Issued Date'])

        # Data
        for req in requests:
            writer.writerow([
                req.request_no,
                req.created_at.strftime('%Y-%m-%d %H:%M'),
                req.requester,
                req.department,
                req.purpose,
                req.status.value if hasattr(req.status, 'value') else req.status,
                req.approved_at.strftime('%Y-%m-%d %H:%M') if req.approved_at else '',
                req.issued_at.strftime('%Y-%m-%d %H:%M') if req.issued_at else ''
            ])

        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'text/csv'
        response.headers['Content-Disposition'] = 'attachment; filename=stock_requests.csv'
        return response

def export_stock_balances(format_type):
    # Build query for stock data with filters
    query = db.session.query(
        Item.code.label('item_code'),
        Item.name.label('item_name'),
        Department.name.label('department_name'),
        Location.name.label('location_name'),
        StockBalance.quantity.label('quantity'),
        (StockBalance.quantity * 0).label('value')  # Placeholder for value calculation
    ).join(StockBalance, Item.id == StockBalance.item_id
    ).join(Location, StockBalance.location_id == Location.id
    ).outerjoin(Department, Item.department_id == Department.id)
    
    balances = query.all()

    if format_type == 'csv':
        output = StringIO()
        writer = csv.writer(output)

        # Headers
        writer.writerow(['Item Code', 'Item Name', 'Department', 'Location Office', 'Location Room', 
                        'Current Stock', 'Low Stock Threshold'])

        # Data
        for balance in balances:
            writer.writerow([
                balance.item_code,
                balance.item_name,
                balance.department_name,
                balance.location_name,
                balance.quantity,
                balance.low_stock_threshold
            ])

        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'text/csv'
        response.headers['Content-Disposition'] = 'attachment; filename=stock_balances.csv'
        return response

def export_department_stats(format_type):
    dept_stats = db.session.query(
        Department.name,
        func.count(StockIssueRequest.id).label('total_requests'),
        func.sum(case((StockIssueRequest.status == RequestStatus.PENDING, 1), else_=0)).label('pending'),
        func.sum(case((StockIssueRequest.status == RequestStatus.APPROVED, 1), else_=0)).label('approved'),
        func.sum(case((StockIssueRequest.status == RequestStatus.ISSUED, 1), else_=0)).label('issued'),
        func.sum(case((StockIssueRequest.status == RequestStatus.REJECTED, 1), else_=0)).label('rejected')
    ).outerjoin(StockIssueRequest).group_by(Department.id).all()

    if format_type == 'csv':
        output = StringIO()
        writer = csv.writer(output)

        # Headers
        writer.writerow(['Department', 'Total Requests', 'Pending', 'Approved', 'Issued', 'Rejected'])

        # Data
        for stat in dept_stats:
            writer.writerow([
                stat.name,
                stat.total_requests or 0,
                stat.pending or 0,
                stat.approved or 0,
                stat.issued or 0,
                stat.rejected or 0
            ])

        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'text/csv'
        response.headers['Content-Disposition'] = 'attachment; filename=department_stats.csv'
        return response

@reports_bp.route('/reports/api/chart-data')
@login_required
@role_required('superadmin', 'manager', 'hod')
def chart_data():
    chart_type = request.args.get('type')

    if chart_type == 'monthly_requests':
        # Monthly request trends
        monthly_data = []
        for i in range(12):
            month_start = (datetime.now().replace(day=1) - timedelta(days=i*30)).replace(day=1)
            month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)

            count = StockIssueRequest.query.filter(
                StockIssueRequest.created_at >= month_start,
                StockIssueRequest.created_at <= month_end
            ).count()

            monthly_data.append({
                'month': month_start.strftime('%b'),
                'requests': count
            })

        monthly_data.reverse()
        return jsonify(monthly_data)

    elif chart_type == 'status_distribution':
        status_data = []
        total_requests = StockIssueRequest.query.count()

        for status in RequestStatus:
            count = StockIssueRequest.query.filter_by(status=status).count()
            status_data.append({
                'status': status.value,
                'count': count,
                'percentage': round((count / total_requests * 100) if total_requests > 0 else 0, 1)
            })

        return jsonify(status_data)

    elif chart_type == 'department_efficiency':
        dept_data = []
        departments = Department.query.all()

        for dept in departments:
            total_requests = StockIssueRequest.query.filter_by(department_id=dept.id).count()
            issued_requests = StockIssueRequest.query.filter_by(
                department_id=dept.id, 
                status=RequestStatus.ISSUED
            ).count()

            dept_data.append({
                'department': dept.name,
                'efficiency': round((issued_requests / total_requests * 100) if total_requests > 0 else 0, 1)
            })

        return jsonify(dept_data)

    return jsonify([])
