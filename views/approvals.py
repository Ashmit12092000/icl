from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from models import StockIssueRequest, RequestStatus, UserRole, Audit
from auth import role_required
from database import db

approvals_bp = Blueprint('approvals', __name__)

@approvals_bp.route('/pending')
@login_required
@role_required('hod')
def pending():
    if not current_user.managed_department:
        flash('You are not assigned as HOD of any department.', 'error')
        return redirect(url_for('main.dashboard'))

    # Get pending requests for HOD's department
    requests = StockIssueRequest.query.filter_by(
        department_id=current_user.managed_department.id,
        status=RequestStatus.PENDING
    ).order_by(StockIssueRequest.created_at.desc()).all()

    return render_template('approvals/pending.html', requests=requests)

@approvals_bp.route('/<int:request_id>/approve', methods=['POST'])
@login_required
@role_required('hod')
def approve_request(request_id):
    request_obj = StockIssueRequest.query.get_or_404(request_id)

    # Check if user can approve this request
    if not request_obj.can_be_approved_by(current_user):
        flash('You do not have permission to approve this request.', 'error')
        return redirect(url_for('approvals.pending'))

    if request_obj.status != RequestStatus.PENDING:
        flash('Only pending requests can be approved.', 'error')
        return redirect(url_for('approvals.pending'))

    remarks = request.form.get('remarks', '').strip()

    try:
        request_obj.status = RequestStatus.APPROVED
        request_obj.approved_by = current_user.id
        request_obj.approved_at = datetime.utcnow()

        if remarks:
            if request_obj.remarks:
                request_obj.remarks += f"\n\nApproval remarks: {remarks}"
            else:
                request_obj.remarks = f"Approval remarks: {remarks}"

        # Log audit
        Audit.log(
            entity_type='StockIssueRequest',
            entity_id=request_obj.id,
            action='APPROVE',
            user_id=current_user.id,
            details=f'Approved request {request_obj.request_no}'
        )

        db.session.commit()
        flash(f'Request {request_obj.request_no} approved successfully.', 'success')

    except Exception as e:
        db.session.rollback()
        flash('Error approving request.', 'error')

    return redirect(url_for('approvals.pending'))

@approvals_bp.route('/<int:request_id>/reject', methods=['POST'])
@login_required
@role_required('hod')
def reject_request(request_id):
    request_obj = StockIssueRequest.query.get_or_404(request_id)

    # Check if user can reject this request
    if not request_obj.can_be_approved_by(current_user):
        flash('You do not have permission to reject this request.', 'error')
        return redirect(url_for('approvals.pending'))

    if request_obj.status != RequestStatus.PENDING:
        flash('Only pending requests can be rejected.', 'error')
        return redirect(url_for('approvals.pending'))

    remarks = request.form.get('remarks', '').strip()

    if not remarks:
        flash('Rejection reason is required.', 'error')
        return redirect(url_for('approvals.pending'))

    try:
        request_obj.status = RequestStatus.REJECTED

        if request_obj.remarks:
            request_obj.remarks += f"\n\nRejection reason: {remarks}"
        else:
            request_obj.remarks = f"Rejection reason: {remarks}"

        # Log audit
        Audit.log(
            entity_type='StockIssueRequest',
            entity_id=request_obj.id,
            action='REJECT',
            user_id=current_user.id,
            details=f'Rejected request {request_obj.request_no}: {remarks}'
        )

        db.session.commit()
        flash(f'Request {request_obj.request_no} rejected.', 'success')

    except Exception as e:
        db.session.rollback()
        flash('Error rejecting request.', 'error')

    return redirect(url_for('approvals.pending'))

@approvals_bp.route('/history')
@login_required
@role_required('hod')
def approval_history():
    if not current_user.managed_department:
        flash('You are not assigned as HOD of any department.', 'error')
        return redirect(url_for('main.dashboard'))

    page = request.args.get('page', 1, type=int)

    # Get all requests for HOD's department (approved/rejected)
    requests = StockIssueRequest.query.filter(
        StockIssueRequest.department_id == current_user.managed_department.id,
        StockIssueRequest.status.in_([RequestStatus.APPROVED, RequestStatus.REJECTED, RequestStatus.ISSUED])
    ).order_by(StockIssueRequest.updated_at.desc()).paginate(
        page=page, per_page=20, error_out=False
    )

    return render_template('approvals/history.html', requests=requests)