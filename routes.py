from flask import render_template, request, redirect, url_for, flash, jsonify, make_response
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from app import app, db
from models import User, Customer, Transaction, InterestRate, TDSRate
from utils import calculate_interest, calculate_compound_interest, export_to_excel, get_period_report, safe_decimal_conversion, compute_cumulative_principal
from datetime import datetime, date, timedelta
from decimal import Decimal, InvalidOperation
import io
import logging
from flask import render_template, request, redirect, url_for, flash, jsonify, make_response
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from app import app, db
from models import User, Customer, Transaction, InterestRate, TDSRate
from utils import calculate_interest, calculate_compound_interest, export_to_excel, get_period_report, safe_decimal_conversion,compute_cumulative_principal
from datetime import datetime, date, timedelta
from decimal import Decimal, InvalidOperation
import io
import logging

def admin_required(f):
    """Decorator to require admin role"""
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            flash('Admin access required.', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

def data_entry_required(f):
    """Decorator to require data entry or admin role"""
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role not in ['data_entry', 'admin']:
            flash('Data entry access required.', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

def safe_decimal_conversion(value, default=Decimal('0')):
    """Safely convert values to Decimal, handling None and invalid inputs"""
    if value is None or value == '':
        return default
    try:
        return Decimal(str(value))
    except (ValueError, TypeError, InvalidOperation):
        return default
@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password.', 'error')

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    customers = Customer.query.filter_by(is_active=True).all()
    total_customers = len(customers)
    total_outstanding = 0
    active_loans = 0
    for customer in customers:
        balance = customer.get_current_balance()
        total_outstanding += balance
        if balance > 0:
            active_loans += 1

    # Calculate total outstanding balance - Fixed NaN issue
    total_balance = Decimal('0')
    for customer in customers:
        try:
            balance = customer.get_current_balance()
            total_balance += balance
        except Exception as e:
            logging.warning(f"Error calculating balance for customer {customer.id}: {e}")

    # Recent transactions
    recent_transactions = Transaction.query.order_by(Transaction.created_at.desc()).limit(5).all()

    return render_template('dashboard.html',
                           customers=customers,
                           total_customers=total_customers,
                           total_balance=total_balance,
                           recent_transactions=recent_transactions,active_loans=active_loans)

@app.route('/customer_master', methods=['GET', 'POST'])
@data_entry_required
def customer_master():
    if request.method == 'POST':
        try:
            # Get form data with safe conversion
            icl_no = request.form['icl_no']
            name = request.form['name']
            address = request.form['address']
            contact_details = request.form['contact_details']
            annual_rate = safe_decimal_conversion(request.form.get('annual_rate', '0'))
            icl_start_date = datetime.strptime(request.form['icl_start_date'], '%Y-%m-%d').date()
            icl_end_date = datetime.strptime(request.form['icl_end_date'], '%Y-%m-%d').date() if request.form.get('icl_end_date') else None
            icl_extension = request.form.get('icl_extension', '')
            tds_applicable = 'tds_applicable' in request.form
            interest_type = request.form.get('interest_type', 'simple')
            compound_frequency = request.form.get('compound_frequency', '')
            first_compounding_date = datetime.strptime(request.form['first_compounding_date'], '%Y-%m-%d').date() if request.form.get('first_compounding_date') else None
            tds_percentage = safe_decimal_conversion(request.form.get('tds_percentage', '0.00'))
            if not tds_applicable: # If TDS is not applicable, set percentage to 0
                tds_percentage = Decimal('0.00')

            # Create new customer
            customer = Customer(
                icl_no=icl_no,
                name=name,
                address=address,
                contact_details=contact_details,
                annual_rate=annual_rate,
                icl_start_date=icl_start_date,
                icl_end_date=icl_end_date,
                icl_extension=icl_extension,
                tds_applicable=tds_applicable,
                tds_percentage=tds_percentage,
                interest_type=interest_type,
                compound_frequency=compound_frequency,
                first_compounding_date=first_compounding_date,
                created_by=current_user.id
            )

            db.session.add(customer)
            db.session.commit()
            flash('Customer created successfully!', 'success')
            return redirect(url_for('customer_master'))

        except Exception as e:
            db.session.rollback()
            flash(f'Error creating customer: {str(e)}', 'error')

    # Check if edit mode is requested
    edit_id = request.args.get('edit')
    edit_mode = False
    customer = None

    if edit_id:
        customer = Customer.query.get_or_404(edit_id)
        edit_mode = True

    customers = Customer.query.filter_by(is_active=True).all()
    return render_template('customer_master.html', customers=customers, edit_mode=edit_mode, customer=customer)

@app.route('/customer_profile/<int:customer_id>')
@login_required
def customer_profile(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    transactions = Transaction.query.filter_by(customer_id=customer_id).order_by(Transaction.date.desc()).all()
    current_balance = customer.get_current_balance()

    # Generate period summaries
    quarterly_summary = _group_transactions_by_period(customer, transactions, 'quarterly')
    half_yearly_summary = _group_transactions_by_period(customer, transactions, 'half_yearly')
    yearly_summary = _group_transactions_by_period(customer, transactions, 'yearly')
    today = date.today()

    return render_template('customer_profile.html',
                           customer=customer,
                           transactions=transactions,
                           current_balance=current_balance,
                           quarterly_summary=quarterly_summary,
                           half_yearly_summary=half_yearly_summary,
                           yearly_summary=yearly_summary,
                           today=today)

@app.route('/edit_customer/<int:customer_id>', methods=['GET', 'POST'])
@data_entry_required
def edit_customer(customer_id):
    customer = Customer.query.get_or_404(customer_id)

    if request.method == 'POST':
        try:
            # Update customer data
            customer.icl_no = request.form['icl_no']
            customer.name = request.form['name']
            customer.address = request.form['address']
            customer.contact_details = request.form['contact_details']

            # Only admin can modify interest rates
            if current_user.role == 'admin':
                customer.annual_rate = safe_decimal_conversion(request.form.get('annual_rate', '0'))
                customer.icl_start_date = datetime.strptime(request.form['icl_start_date'], '%Y-%m-%d').date()
                customer.icl_end_date = datetime.strptime(request.form['icl_end_date'], '%Y-%m-%d').date() if request.form.get('icl_end_date') else None
                customer.icl_extension = request.form.get('icl_extension', '')
                customer.tds_applicable = 'tds_applicable' in request.form
                customer.tds_percentage = safe_decimal_conversion(request.form.get('tds_percentage', '0.00'))
                if not customer.tds_applicable: # If TDS is not applicable, set percentage to 0
                    customer.tds_percentage = Decimal('0.00')
                customer.interest_type = request.form.get('interest_type', 'simple')
                customer.compound_frequency = request.form.get('compound_frequency', '')
                customer.first_compounding_date = datetime.strptime(request.form['first_compounding_date'], '%Y-%m-%d').date() if request.form.get('first_compounding_date') else None

            db.session.commit()
            flash('Customer updated successfully!', 'success')
            return redirect(url_for('customer_profile', customer_id=customer_id))

        except Exception as e:
            db.session.rollback()
            flash(f'Error updating customer: {str(e)}', 'error')

    return render_template('customer_master.html', customer=customer, edit_mode=True)

@app.route('/customer/<int:customer_id>/close_loan', methods=['POST'])
@admin_required
def close_loan(customer_id):
    """Close a customer's loan manually (for admin)"""
    customer = Customer.query.get_or_404(customer_id)

    try:
        # Check if loan is already closed
        if customer.loan_closed:
            flash(f'Loan for customer "{customer.name}" is already closed!', 'warning')
            return redirect(url_for('customer_profile', customer_id=customer_id))

        # Get current balance to check if loan can be closed
        current_balance = customer.get_current_balance()

        # Only allow closure if balance is approximately zero or negative (overpaid)
        if current_balance > Decimal('10.00'):
            flash(f'Cannot close loan with outstanding balance of {current_balance}. Balance must be ≤ ₹10.00 to close manually.', 'error')
            return redirect(url_for('customer_profile', customer_id=customer_id))

        # Create loan closure transaction
        closure_transaction = Transaction(
            customer_id=customer_id,
            date=date.today(),
            amount_paid=None,
            amount_repaid=None,
            balance=Decimal('0'),  # Set balance to zero on closure
            period_from=None,
            period_to=None,
            no_of_days=None,
            int_rate=None,
            int_amount=None,
            tds_amount=None,
            net_amount=None,
            transaction_type='loan_closure',
            created_by=current_user.id
        )

        db.session.add(closure_transaction)

        # Mark loan as closed and clear overdue status
        customer.loan_closed = True
        customer.loan_closed_date = date.today()
        customer.loan_overdue = False
        customer.loan_overdue_date = None
        db.session.commit()

        flash(f'Loan for customer "{customer.name}" has been manually closed successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error closing loan for customer "{customer.name}": {e}', 'error')
        app.logger.error(f"Error closing loan for customer {customer_id}: {e}")

    return redirect(url_for('customer_profile', customer_id=customer_id))

@app.route('/customer/<int:customer_id>/extend_loan', methods=['POST'])
@admin_required
def extend_loan(customer_id):
    """Extend a customer's loan with comprehensive validation and logging"""
    customer = Customer.query.get_or_404(customer_id)

    try:
        # Comprehensive validation checks
        if customer.loan_closed:
            flash(f'Cannot extend a closed loan for customer "{customer.name}". Loan was closed on {customer.loan_closed_date.strftime("%d-%m-%Y") if customer.loan_closed_date else "unknown date"}.', 'error')
            return redirect(url_for('overdue_loans'))

        # Check if customer has outstanding balance
        current_balance = customer.get_current_balance()
        if current_balance <= Decimal('0'):
            flash(f'Cannot extend loan for customer "{customer.name}" with zero or negative balance (₹{current_balance}).', 'error')
            return redirect(url_for('overdue_loans'))

        new_end_date = datetime.strptime(request.form['new_end_date'], '%Y-%m-%d').date()
        extension_reason = request.form.get('extension_reason', '').strip()

        # Enhanced validation
        if not extension_reason:
            flash('Extension reason is required and cannot be empty.', 'error')
            return redirect(url_for('overdue_loans'))

        if len(extension_reason) < 10:
            flash('Extension reason must be at least 10 characters long for proper documentation.', 'error')
            return redirect(url_for('overdue_loans'))

        # Date validation with edge cases
        today = date.today()
        if customer.icl_end_date:
            if new_end_date <= customer.icl_end_date:
                flash(f'New end date ({new_end_date.strftime("%d-%m-%Y")}) must be after the current ICL end date ({customer.icl_end_date.strftime("%d-%m-%Y")}).', 'error')
                return redirect(url_for('overdue_loans'))
        
        if new_end_date <= today:
            flash(f'New end date ({new_end_date.strftime("%d-%m-%Y")}) must be in the future (after {today.strftime("%d-%m-%Y")}).', 'error')
            return redirect(url_for('overdue_loans'))

        # Check for reasonable extension period (not more than 5 years)
        max_extension_date = today + timedelta(days=5*365)  # 5 years
        if new_end_date > max_extension_date:
            flash(f'Extension period too long. Maximum allowed extension date is {max_extension_date.strftime("%d-%m-%Y")}.', 'warning')
            return redirect(url_for('overdue_loans'))

        # Store original ICL end date if this is the first extension
        if not customer.loan_extended and customer.icl_end_date:
            customer.original_icl_end_date = customer.icl_end_date

        # Calculate extension period for logging
        old_end_date = customer.icl_end_date or customer.icl_start_date
        extension_days = (new_end_date - old_end_date).days

        # Update loan details
        customer.icl_end_date = new_end_date
        customer.loan_extended = True
        customer.loan_overdue = False
        customer.loan_overdue_date = None

        # Update extension reason with timestamp and user info
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        user_info = f"Extended by {current_user.username} on {timestamp}"
        full_reason = f"{extension_reason}\n\n[{user_info}]"
        
        customer.icl_extension = full_reason

        # Create audit log entry (you might want to add an audit table)
        logging.info(f"Loan extension: Customer {customer.name} (ID: {customer_id}) extended by {extension_days} days. New end date: {new_end_date}. Reason: {extension_reason}")

        db.session.commit()

        # Success message with details
        flash(f'✅ Loan successfully extended for "{customer.name}"!\n'
              f'📅 New end date: {new_end_date.strftime("%d-%m-%Y")}\n'
              f'⏱️ Extension period: {extension_days} days\n'
              f'💰 Outstanding balance: ₹{current_balance:,.2f}', 'success')

    except ValueError as ve:
        db.session.rollback()
        flash(f'Invalid date format provided. Please use a valid date.', 'error')
        app.logger.error(f"Date validation error for customer {customer_id}: {ve}")
    except Exception as e:
        db.session.rollback()
        flash(f'Unexpected error extending loan for customer "{customer.name}": {str(e)}', 'error')
        app.logger.error(f"Error extending loan for customer {customer_id}: {e}", exc_info=True)

    return redirect(url_for('overdue_loans'))

@app.route('/customer/<int:customer_id>/mark_overdue', methods=['POST'])
@admin_required
def mark_overdue(customer_id):
    """Mark a customer's loan as overdue with comprehensive validation and audit trail"""
    customer = Customer.query.get_or_404(customer_id)
    today = date.today()

    try:
        # Comprehensive validation checks
        if customer.loan_closed:
            flash(f'❌ Cannot mark a closed loan as overdue for customer "{customer.name}". '
                  f'Loan was closed on {customer.loan_closed_date.strftime("%d-%m-%Y") if customer.loan_closed_date else "unknown date"}.', 'error')
            return redirect(url_for('overdue_loans'))

        if customer.loan_overdue:
            days_already_overdue = (today - customer.loan_overdue_date).days if customer.loan_overdue_date else 0
            flash(f'⚠️ Loan for customer "{customer.name}" is already marked as overdue '
                  f'({days_already_overdue} days since {customer.loan_overdue_date.strftime("%d-%m-%Y") if customer.loan_overdue_date else "unknown date"}).', 'warning')
            return redirect(url_for('overdue_loans'))

        # Check outstanding balance
        current_balance = customer.get_current_balance()
        if current_balance <= Decimal('0'):
            flash(f'❌ Cannot mark loan as overdue for customer "{customer.name}" with balance of ₹{current_balance}. '
                  f'Only loans with positive outstanding balance can be marked overdue.', 'error')
            return redirect(url_for('overdue_loans'))

        # Check if loan is actually past due date
        if not customer.icl_end_date:
            flash(f'⚠️ Warning: Customer "{customer.name}" has no ICL end date set. '
                  f'Please verify loan terms before marking as overdue.', 'warning')
        elif customer.icl_end_date >= today:
            days_until_due = (customer.icl_end_date - today).days
            flash(f'⚠️ Warning: Loan for customer "{customer.name}" is not yet due. '
                  f'ICL end date is {customer.icl_end_date.strftime("%d-%m-%Y")} ({days_until_due} days from now). '
                  f'Are you sure you want to mark it as overdue?', 'warning')

        # Calculate days past due for audit log
        days_past_due = 0
        if customer.icl_end_date and today > customer.icl_end_date:
            days_past_due = (today - customer.icl_end_date).days

        # Mark loan as overdue with proper audit trail
        customer.loan_overdue = True
        customer.loan_overdue_date = today

        # Create detailed audit log
        audit_info = {
            'customer_id': customer_id,
            'customer_name': customer.name,
            'icl_no': customer.icl_no,
            'outstanding_balance': float(current_balance),
            'icl_end_date': customer.icl_end_date.strftime('%Y-%m-%d') if customer.icl_end_date else None,
            'days_past_due': days_past_due,
            'marked_overdue_date': today.strftime('%Y-%m-%d'),
            'marked_by_user': current_user.username,
            'marked_by_user_id': current_user.id
        }

        logging.warning(f"LOAN MARKED OVERDUE: {audit_info}")

        # Calculate penalty implications
        daily_interest = _calculate_daily_interest(current_balance, customer.annual_rate)
        monthly_penalty = daily_interest * 30

        db.session.commit()

        # Comprehensive success message
        flash(f'🚨 Loan marked as overdue for customer "{customer.name}"!\n'
              f'📋 ICL No: {customer.icl_no}\n'
              f'💰 Outstanding: ₹{current_balance:,.2f}\n'
              f'📅 Days Past Due: {days_past_due} days\n'
              f'💸 Daily Interest: ₹{daily_interest:,.2f}\n'
              f'⚠️ Monthly Penalty: ≈₹{monthly_penalty:,.2f}\n'
              f'👤 Marked by: {current_user.username}', 'warning')

        # Log successful operation
        logging.info(f"Loan successfully marked overdue for customer {customer_id} by user {current_user.username}")

    except Exception as e:
        db.session.rollback()
        error_msg = f'Unexpected error marking loan as overdue for customer "{customer.name}": {str(e)}'
        flash(f'❌ {error_msg}', 'error')
        app.logger.error(f"Error marking loan as overdue for customer {customer_id}: {e}", exc_info=True)

    return redirect(url_for('overdue_loans'))

@app.route('/overdue_loans')
@admin_required
def overdue_loans():
    """View all overdue loans with comprehensive analysis"""
    today = date.today()
    
    # Get all active customers with loans
    all_customers = Customer.query.filter(
        Customer.is_active == True,
        Customer.loan_closed == False
    ).all()

    # Categorize customers based on their loan status
    overdue_customers = []
    past_due_customers_list = []
    
    for customer in all_customers:
        balance = customer.get_current_balance()
        
        # Only process customers with outstanding balance
        if balance > Decimal('0'):
            # Check if loan is already marked as overdue
            if customer.loan_overdue:
                days_overdue = (today - customer.loan_overdue_date).days if customer.loan_overdue_date else 0
                # Ensure minimum 1 day overdue for display consistency
                days_overdue = max(1, days_overdue)
                
                overdue_customers.append({
                    'customer': customer,
                    'balance': balance,
                    'days_overdue': days_overdue,
                    'priority': _calculate_priority(days_overdue, balance),
                    'daily_interest': _calculate_daily_interest(balance, customer.annual_rate),
                    'accrued_penalty': _calculate_accrued_penalty(balance, customer.annual_rate, days_overdue)
                })
            
            # Check if loan is past ICL end date but not marked overdue
            elif customer.icl_end_date and today > customer.icl_end_date:
                days_past_due = (today - customer.icl_end_date).days
                
                # Handle edge case where ICL end date is today (same day)
                if days_past_due == 0:
                    days_past_due = 1
                
                past_due_customers_list.append({
                    'customer': customer,
                    'balance': balance,
                    'days_past_due': days_past_due,
                    'risk_level': _calculate_risk_level(days_past_due, balance),
                    'daily_interest': _calculate_daily_interest(balance, customer.annual_rate),
                    'potential_loss': _calculate_potential_loss(balance, customer.annual_rate, days_past_due)
                })
            
            # Edge case: ICL end date is null but customer has balance (data integrity issue)
            elif not customer.icl_end_date and balance > Decimal('0'):
                # Calculate based on last transaction date or ICL start date
                reference_date = customer.get_last_transaction_date() or customer.icl_start_date
                if reference_date and (today - reference_date).days > 365:  # Assume 1 year default term
                    days_past_due = (today - reference_date).days - 365
                    
                    past_due_customers_list.append({
                        'customer': customer,
                        'balance': balance,
                        'days_past_due': days_past_due,
                        'risk_level': 'data_issue',
                        'daily_interest': _calculate_daily_interest(balance, customer.annual_rate),
                        'potential_loss': _calculate_potential_loss(balance, customer.annual_rate, days_past_due),
                        'data_issue': True
                    })

    # Sort by priority/risk level
    overdue_customers.sort(key=lambda x: (x['priority'], x['days_overdue']), reverse=True)
    past_due_customers_list.sort(key=lambda x: (x.get('risk_level') == 'critical', x['days_past_due']), reverse=True)

    # Calculate summary statistics
    total_overdue_amount = sum(item['balance'] for item in overdue_customers)
    total_past_due_amount = sum(item['balance'] for item in past_due_customers_list)
    critical_cases = sum(1 for item in overdue_customers if item['days_overdue'] > 90)
    high_risk_cases = sum(1 for item in past_due_customers_list if item['days_past_due'] > 30)

    return render_template('overdue_loans.html', 
                         overdue_customers=overdue_customers,
                         past_due_customers=past_due_customers_list,
                         timedelta=timedelta,
                         summary_stats={
                             'total_overdue_amount': total_overdue_amount,
                             'total_past_due_amount': total_past_due_amount,
                             'critical_cases': critical_cases,
                             'high_risk_cases': high_risk_cases,
                             'total_cases': len(overdue_customers) + len(past_due_customers_list)
                         })

@app.route('/customer/<int:customer_id>/delete', methods=['POST'])
@admin_required
def delete_customer(customer_id):
    logging.debug(f"Attempting to delete customer {customer_id} with method {request.method}") # Debug log added
    customer = Customer.query.get_or_404(customer_id)
    print("Customer ID: "+str(customer_id))
    try:
        customer.is_active = False
        db.session.delete(customer)
        db.session.commit()
        flash('Customer deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting customer "{customer.name}": {e}', 'danger')
        app.logger.error(f"Error deleting customer {customer_id}: {e}")
    return redirect(url_for('customer_master',deleted=1))

@app.route('/transactions/<int:customer_id>', methods=['GET', 'POST'])
@data_entry_required
def transactions(customer_id):
    customer = Customer.query.get_or_404(customer_id)

    # --- START MODIFICATION ---
    default_period_from = None
    # Fetch the last transaction for the customer to get its period_to date
    last_transaction = Transaction.query.filter_by(customer_id=customer_id) \
                                      .order_by(Transaction.date.desc(), Transaction.created_at.desc()) \
                                      .first()
    if last_transaction and last_transaction.period_to:
        # If there's a last transaction with a period_to, set it as default_period_from
        new_period_from_date = last_transaction.period_to + timedelta(days=1)
        default_period_from = new_period_from_date.strftime('%Y-%m-%d')
        logging.debug(f"Found last transaction period_to: {default_period_from} for customer {customer_id}")
    else:
        # If no transactions or no period_to, use customer's start date as default
        # or just leave it None to allow client-side to use current date
        if customer.icl_start_date:
            default_period_from = customer.icl_start_date.strftime('%Y-%m-%d')
            logging.debug(f"No last transaction period_to, using customer icl_start_date: {default_period_from}")
        else:
            # Fallback for entirely new customers without a defined start date
            default_period_from = date.today().strftime('%Y-%m-%d')
            logging.debug(f"No customer icl_start_date, defaulting period_from to today: {default_period_from}")
    # --- END MODIFICATION ---

    if request.method == 'POST':
        try:
            transaction_date = datetime.strptime(request.form['date'], '%Y-%m-%d').date()
            amount_paid = safe_decimal_conversion(request.form.get('amount_paid'))
            amount_repaid = safe_decimal_conversion(request.form.get('amount_repaid'))

            # Check if loan is closed
            if customer.loan_closed:
                flash('Cannot add transactions to a closed loan.', 'error')
                transactions = Transaction.query.filter_by(customer_id=customer_id).order_by(Transaction.date.desc()).all()
                return render_template('transactions.html', customer=customer, transactions=transactions, default_period_from=default_period_from)

            # Validate transaction date against ICL end date for manual passive transactions
            is_manual_passive = (amount_paid == Decimal('0') and amount_repaid == Decimal('0'))
            if is_manual_passive and customer.icl_end_date and transaction_date > customer.icl_end_date:
                flash(f'Manual passive transaction date cannot be beyond ICL end date ({customer.icl_end_date.strftime("%d-%m-%Y")}). Please select a date on or before the ICL end date.', 'error')
                transactions = Transaction.query.filter_by(customer_id=customer_id).order_by(Transaction.date.desc()).all()
                return render_template('transactions.html', customer=customer, transactions=transactions, default_period_from=default_period_from)

            # For overdue loans, allow transactions but show warning
            if customer.loan_overdue and transaction_date > customer.icl_end_date:
                flash(f'Adding transaction to overdue loan. Loan was due on {customer.icl_end_date.strftime("%d-%m-%Y")}.', 'warning')

            # For active loans, check if transaction date is beyond ICL end date
            elif not customer.loan_overdue and customer.icl_end_date and transaction_date > customer.icl_end_date:
                # Allow transactions beyond ICL end date but show warning
                flash(f'Transaction date is beyond ICL end date ({customer.icl_end_date.strftime("%d-%m-%Y")}). Interest will continue to accrue.', 'warning')

            # Only include transactions before this one to calculate correct principal
            previous_txns = Transaction.query.filter(
                Transaction.customer_id == customer_id,
                Transaction.date < transaction_date
            ).all()

            # Include same-date earlier transactions if any
            same_day_txns = Transaction.query.filter(
                Transaction.customer_id == customer_id,
                Transaction.date == transaction_date
            ).order_by(Transaction.id.asc()).all()

            net_outstanding_balance = Decimal('0')
            for txn in previous_txns + same_day_txns:
                net_outstanding_balance += txn.get_safe_amount_paid() - txn.get_safe_amount_repaid()

            current_balance_before_this_txn = net_outstanding_balance

            # New balance after this transaction
            new_balance = current_balance_before_this_txn + amount_paid - amount_repaid

            # Auto-calculate period dates
            period_from = None
            period_to = None
            create_post_payment_period = False

            # Get manual period dates if provided
            manual_period_from = datetime.strptime(request.form['period_from'], '%Y-%m-%d').date() if request.form.get('period_from') else None
            manual_period_to = datetime.strptime(request.form['period_to'], '%Y-%m-%d').date() if request.form.get('period_to') else None

            # Auto-calculate periods for both simple and compound interest
            if manual_period_from and manual_period_to:
                # Use manual dates if provided
                period_from = manual_period_from
                period_to = manual_period_to
            else:
                # DYNAMIC MISSING PERIOD DETECTION AND CREATION
                missing_periods = _get_all_missing_periods_until_transaction(customer_id, customer, transaction_date)

                # Create passive period transactions for ALL missing quarters
                for missing_start, missing_end in missing_periods:
                    _create_passive_period_transaction(customer_id, customer, missing_start, missing_end, current_user.id)
                    logging.debug(f"Created passive period transaction for {missing_start} to {missing_end}")

                # If passive periods were created, recalculate the balance before this transaction
                if missing_periods:
                    db.session.flush()  # Ensure passive periods are saved before continuing

                    # Recalculate balance including new passive periods
                    previous_txns = Transaction.query.filter(
                        Transaction.customer_id == customer_id,
                        Transaction.date < transaction_date
                    ).all()

                    same_day_txns = Transaction.query.filter(
                        Transaction.customer_id == customer_id,
                        Transaction.date == transaction_date
                    ).order_by(Transaction.id.asc()).all()

                    net_outstanding_balance = Decimal('0')
                    for txn in previous_txns + same_day_txns:
                        net_outstanding_balance += txn.get_safe_amount_paid() - txn.get_safe_amount_repaid()
                        # For compound interest, add accumulated interest at quarter ends
                        if (customer.interest_type == 'compound' and 
                            customer.first_compounding_date and 
                            txn.date >= customer.first_compounding_date and 
                            txn.period_to and 
                            _is_quarter_end(txn.period_to, customer.icl_start_date) and 
                            txn.get_safe_net_amount()):
                            net_outstanding_balance += txn.get_safe_net_amount()

                    current_balance_before_this_txn = net_outstanding_balance
                # Handle repayments - split periods for both simple and compound interest users
                if amount_repaid > Decimal('0'):
                    # For repayments (both simple and compound), create two periods:
                    # Period 1: Period start to repayment date 
                    # Period 2: Day after repayment to period end (interest calculated on reduced principal)

                    frequency_to_use = customer.compound_frequency if customer.interest_type == 'compound' and customer.compound_frequency else 'quarterly'
                    period_start_for_repayment = _get_period_start_date(transaction_date, customer.icl_start_date, frequency_to_use)
                    period_end_for_repayment = _get_period_end_date(transaction_date, customer.icl_start_date, frequency_to_use)

                    # Check if there's an existing transaction in this period that needs splitting
                    existing_period_txn = Transaction.query.filter(
                        Transaction.customer_id == customer_id,
                        Transaction.period_from == period_start_for_repayment,
                        Transaction.period_to == period_end_for_repayment,
                        Transaction.date < transaction_date
                    ).order_by(Transaction.date.desc()).first()

                    if existing_period_txn:
                        # Split the existing period transaction
                        existing_period_txn.period_to = transaction_date - timedelta(days=1)
                        existing_period_txn.no_of_days = (existing_period_txn.period_to - existing_period_txn.period_from).days + 1

                        # Recalculate interest for the split period (but don't add to principal for mid-period)
                        if existing_period_txn.no_of_days > 0:
                            prev_balance = Decimal('0')
                            prev_txns = Transaction.query.filter(
                                Transaction.customer_id == customer_id,
                                Transaction.date < existing_period_txn.date
                            ).all()

                            for prev_txn in prev_txns:
                                prev_balance += prev_txn.get_safe_amount_paid() - prev_txn.get_safe_amount_repaid()

                            # For compound interest, include accumulated net interest from PREVIOUS PERIODS only
                            if (customer.first_compounding_date and 
                                existing_period_txn.date >= customer.first_compounding_date):
                                # Get accumulated net interest only from transactions before this period starts
                                previous_period_transactions = Transaction.query.filter(
                                    Transaction.customer_id == customer_id,
                                    Transaction.date < period_start_for_repayment
                                ).order_by(Transaction.date.asc(), Transaction.id.asc()).all()

                                accumulated_net_interest_from_previous_periods = Decimal('0')
                                for prev_txn in previous_period_transactions:
                                    accumulated_net_interest_from_previous_periods += prev_txn.get_safe_net_amount()

                                if existing_period_txn.get_safe_amount_paid() > Decimal('0'):
                                    principal_for_existing = prev_balance + accumulated_net_interest_from_previous_periods + existing_period_txn.get_safe_amount_paid()
                                else:
                                    principal_for_existing = prev_balance + accumulated_net_interest_from_previous_periods
                            else:
                                if existing_period_txn.get_safe_amount_paid() > Decimal('0'):
                                    principal_for_existing = prev_balance + existing_period_txn.get_safe_amount_paid()
                                else:
                                    principal_for_existing = prev_balance

                            existing_period_txn.int_amount = calculate_interest(principal_for_existing, customer.annual_rate, existing_period_txn.no_of_days)

                            # Recalculate TDS
                            if customer.tds_applicable and existing_period_txn.int_amount:
                                tds_rate_to_use = customer.tds_percentage or Decimal('10.00')
                                existing_period_txn.tds_amount = existing_period_txn.int_amount * (tds_rate_to_use / Decimal('100'))
                                existing_period_txn.net_amount = existing_period_txn.int_amount - existing_period_txn.tds_amount
                            else:
                                existing_period_txn.tds_amount = Decimal('0')
                                existing_period_txn.net_amount = existing_period_txn.int_amount

                        db.session.add(existing_period_txn)
                        logging.debug(f"Split existing period transaction {existing_period_txn.id}: period updated to {existing_period_txn.period_from} - {existing_period_txn.period_to}")

                    # Current repayment transaction (Period 1): Period start to repayment date
                    period_from = period_start_for_repayment
                    # Use transaction date, but don't exceed ICL end date
                    period_to = min(transaction_date, customer.icl_end_date) if customer.icl_end_date else transaction_date

                    # For repayments (both simple and compound), schedule creation of post-payment period after this transaction is saved
                    create_post_payment_period = True
                    post_payment_start = transaction_date + timedelta(days=1)
                    post_payment_end = min(period_end_for_repayment, customer.icl_end_date) if customer.icl_end_date else period_end_for_repayment

                else:
                    # Initialize post-payment period variables for non-repayment cases
                    create_post_payment_period = False

                    # Special handling for yearly compounding
                    if customer.interest_type == 'compound' and customer.compound_frequency == 'yearly':
                        # Handle yearly compounding with FY period splitting and passive period updates
                        period_from, period_to, should_create_post_fy_period, post_fy_start, post_fy_end = _calculate_yearly_compounding_periods(
                            customer_id, customer, transaction_date, amount_paid, amount_repaid, current_balance_before_this_txn, current_user.id
                        )

                        # Check for existing transactions that need splitting
                        existing_period_txn = Transaction.query.filter(
                            Transaction.customer_id == customer_id,
                            Transaction.period_from <= transaction_date,
                            Transaction.period_to >= transaction_date,
                            Transaction.date < transaction_date,
                            Transaction.transaction_type != 'passive'  # Don't split passive periods as they're being recalculated
                        ).order_by(Transaction.date.desc()).first()

                        if existing_period_txn:
                            # Split the existing transaction at the new transaction date
                            existing_period_txn.period_to = transaction_date - timedelta(days=1)
                            existing_period_txn.no_of_days = (existing_period_txn.period_to - existing_period_txn.period_from).days + 1

                            # Recalculate interest for the split period
                            if existing_period_txn.no_of_days > 0:
                                prev_balance = Decimal('0')
                                prev_txns = Transaction.query.filter(
                                    Transaction.customer_id == customer_id,
                                    Transaction.date < existing_period_txn.date
                                ).all()

                                for prev_txn in prev_txns:
                                    prev_balance += prev_txn.get_safe_amount_paid() - prev_txn.get_safe_amount_repaid()
                                    # Add accumulated FY interest for yearly compounding
                                    if (prev_txn.period_to and 
                                        _is_yearly_period_end(prev_txn.period_to) and 
                                        prev_txn.get_safe_net_amount()):
                                        prev_balance += prev_txn.get_safe_net_amount()

                                if existing_period_txn.get_safe_amount_paid() > Decimal('0'):
                                    principal_for_existing = prev_balance + existing_period_txn.get_safe_amount_paid()
                                else:
                                    principal_for_existing = prev_balance

                                existing_period_txn.int_amount = calculate_interest(principal_for_existing, customer.annual_rate, existing_period_txn.no_of_days)

                                # Recalculate TDS
                                if customer.tds_applicable and existing_period_txn.int_amount:
                                    tds_rate_to_use = customer.tds_percentage or Decimal('10.00')
                                    existing_period_txn.tds_amount = existing_period_txn.int_amount * (tds_rate_to_use / Decimal('100'))
                                    existing_period_txn.net_amount = existing_period_txn.int_amount - existing_period_txn.tds_amount
                                else:
                                    existing_period_txn.tds_amount = Decimal('0')
                                    existing_period_txn.net_amount = existing_period_txn.int_amount

                            db.session.add(existing_period_txn)
                            logging.debug(f"Split existing yearly transaction {existing_period_txn.id}: period updated to {existing_period_txn.period_from} - {existing_period_txn.period_to}")

                        # Set current transaction period (up to March 31 or transaction date)
                        if amount_paid > Decimal('0'):
                            # For deposits, period starts from transaction date
                            period_from = transaction_date
                        if customer.icl_end_date and period_to > customer.icl_end_date:
                            period_to = customer.icl_end_date
                            # If period is capped by ICL end date, no need for post-FY period
                            should_create_post_fy_period = False
                            logging.debug(f"Yearly period capped by ICL end date: {period_to}")
                        # Mark for post-FY period creation if needed
                        if should_create_post_fy_period:
                            create_post_payment_period = True
                            post_payment_start = post_fy_start
                            post_payment_end = post_fy_end
                    else:
                        # Original logic for non-yearly compounding
                        # Check if there's an ongoing period that needs to be split
                        ongoing_txn = Transaction.query.filter(
                            Transaction.customer_id == customer_id,
                            Transaction.period_from <= transaction_date,
                            Transaction.period_to >= transaction_date
                        ).order_by(Transaction.date.desc(), Transaction.created_at.desc()).first()

                        if ongoing_txn and ongoing_txn.date != transaction_date:
                            # Split the ongoing period
                            if amount_repaid > Decimal('0'):
                                # Repayment: transaction belongs to period ending on repayment date
                                period_from = ongoing_txn.period_from
                                period_to = transaction_date

                                # Update the ongoing transaction's period_to to day before current transaction
                                ongoing_txn.period_to = transaction_date - timedelta(days=1)
                            else:
                                # Deposit: transaction starts new period from transaction date
                                period_from = transaction_date
                                period_to = ongoing_txn.period_to

                                # Update the ongoing transaction's period_to to day before current transaction
                                ongoing_txn.period_to = transaction_date - timedelta(days=1)

                            # Recalculate the ongoing transaction's no_of_days and interest
                            if ongoing_txn.period_from and ongoing_txn.period_to:
                                ongoing_txn.no_of_days = (ongoing_txn.period_to - ongoing_txn.period_from).days + 1

                                # Recalculate interest for the ongoing transaction with new period
                                principal_for_ongoing = Decimal('0')
                                previous_balance = Decimal('0')

                                # Get balance before ongoing transaction
                                prev_txns = Transaction.query.filter(
                                    Transaction.customer_id == customer_id,
                                    Transaction.date < ongoing_txn.date
                                ).all()

                                for prev_txn in prev_txns:
                                    previous_balance += prev_txn.get_safe_amount_paid() - prev_txn.get_safe_amount_repaid()

                                if ongoing_txn.get_safe_amount_paid() > Decimal('0'):
                                    principal_for_ongoing = previous_balance + ongoing_txn.get_safe_amount_paid()
                                elif ongoing_txn.get_safe_amount_repaid() > Decimal('0'):
                                    principal_for_ongoing = previous_balance - ongoing_txn.get_safe_amount_repaid()
                                else:
                                    principal_for_ongoing = previous_balance

                                # Recalculate interest
                                if ongoing_txn.no_of_days > 0:
                                    ongoing_txn.int_amount = calculate_interest(principal_for_ongoing, customer.annual_rate, ongoing_txn.no_of_days)

                                    # Recalculate TDS
                                    if customer.tds_applicable and ongoing_txn.int_amount:
                                        tds_rate_to_use = customer.tds_percentage or Decimal('10.00')
                                        ongoing_txn.tds_amount = ongoing_txn.int_amount * (tds_rate_to_use / Decimal('100'))
                                        ongoing_txn.net_amount = ongoing_txn.int_amount - ongoing_txn.tds_amount
                                    else:
                                        ongoing_txn.tds_amount = Decimal('0')
                                        ongoing_txn.net_amount = ongoing_txn.int_amount

                                db.session.add(ongoing_txn)
                                logging.debug(f"Split ongoing transaction {ongoing_txn.id}: period updated to {ongoing_txn.period_from} - {ongoing_txn.period_to}")

                        else:
                            # No ongoing period to split, calculate normally
                            last_txn = Transaction.query.filter(
                                Transaction.customer_id == customer_id,
                                Transaction.date < transaction_date
                            ).order_by(Transaction.date.desc(), Transaction.created_at.desc()).first()

                            if last_txn and last_txn.period_to:
                                # Period starts from day after last transaction's period_to
                                period_from = last_txn.period_to + timedelta(days=1)
                            else:
                                # First transaction - start from transaction date or customer's ICL start date
                                if customer.icl_start_date and transaction_date >= customer.icl_start_date:
                                    period_from = transaction_date
                                else:
                                    period_from = customer.icl_start_date or transaction_date

                            # Calculate period_to based on interest type and frequency, but respect ICL end date
                            if customer.interest_type == 'compound' and customer.compound_frequency:
                                # For compound interest, use the customer's specified frequency
                                calculated_period_end = _get_period_end_date(transaction_date, customer.icl_start_date, customer.compound_frequency)
                                # Use the earlier of period end or ICL end date
                                period_to = min(calculated_period_end, customer.icl_end_date) if customer.icl_end_date else calculated_period_end
                            elif customer.interest_type == 'simple':
                                # For simple interest, use quarterly periods as default
                                calculated_quarter_end = _get_quarter_end_date(transaction_date, customer.icl_start_date)
                                # Use the earlier of quarter end or ICL end date
                                period_to = min(calculated_quarter_end, customer.icl_end_date) if customer.icl_end_date else calculated_quarter_end
                            else:
                                # For compound interest without specified frequency, use quarterly as default
                                calculated_period_end = _get_quarter_end_date(transaction_date, customer.icl_start_date)
                                # Use the earlier of calculated period end or ICL end date
                                period_to = min(calculated_period_end, customer.icl_end_date) if customer.icl_end_date else calculated_period_end

            int_amount = tds_amount = net_amount = None
            no_of_days = None

            if period_from and period_to:
                no_of_days = (period_to - period_from).days + 1
                principal_for_interest_calculation = Decimal('0')

                # Determine if we're before first compounding date
                is_before_first_compounding = True
                if customer.interest_type == 'compound' and customer.first_compounding_date:
                    if transaction_date >= customer.first_compounding_date:
                        is_before_first_compounding = False

                # Always use simple interest formula for interest calculation
                # The difference is only in principal calculation and when to add to balance
                if amount_paid > Decimal('0'):
                    # Deposit — interest on previous balance + current paid
                    principal_for_interest_calculation = current_balance_before_this_txn + amount_paid
                elif amount_repaid > Decimal('0'):
                    # Repayment — interest on the reduced principal
                    principal_for_interest_calculation = current_balance_before_this_txn - amount_repaid
                else:
                    # Passive period — interest on previous balance
                    principal_for_interest_calculation = current_balance_before_this_txn

                # For compound interest, include accumulated net interest only from previous quarters (not current quarter)
                if not is_before_first_compounding:
                    # Get the quarter start date for this transaction
                    quarter_start = _get_quarter_start_date(transaction_date, customer.icl_start_date)

                    # Get accumulated net interest only from transactions before this quarter starts
                    previous_quarter_transactions = Transaction.query.filter(
                        Transaction.customer_id == customer_id,
                        Transaction.date < quarter_start
                    ).order_by(Transaction.date.asc(), Transaction.id.asc()).all()

                    # Calculate accumulated net interest only from previous quarters
                    accumulated_net_interest_from_previous_quarters = Decimal('0')
                    for prev_txn in previous_quarter_transactions:
                        accumulated_net_interest_from_previous_quarters += prev_txn.get_safe_net_amount()

                    # For transactions after first compounding date, principal = previous principal + accumulated interest from previous quarters
                    if amount_paid > Decimal('0'):
                        # Deposit — interest on (previous balance + accumulated interest from previous quarters) + current paid
                        principal_for_interest_calculation = current_balance_before_this_txn + accumulated_net_interest_from_previous_quarters + amount_paid
                    elif amount_repaid > Decimal('0'):
                        # Repayment — interest on (previous balance + accumulated interest from previous quarters) - current repaid
                        principal_for_interest_calculation = current_balance_before_this_txn + accumulated_net_interest_from_previous_quarters - amount_repaid
                    else:
                        # Passive period — interest on previous balance + accumulated interest from previous quarters
                        principal_for_interest_calculation = current_balance_before_this_txn + accumulated_net_interest_from_previous_quarters

                # Calculate interest using simple interest formula
                int_amount = calculate_interest(principal_for_interest_calculation, customer.annual_rate, no_of_days)
                logging.debug(f"Calculated interest amount: {int_amount} for principal: {principal_for_interest_calculation}")

                # TDS calculation
                if customer.tds_applicable and int_amount:
                    tds_rate_to_use = customer.tds_percentage or Decimal('10.00')  # Default 10% TDS
                    tds_amount = int_amount * (tds_rate_to_use / Decimal('100'))
                    net_amount = int_amount - tds_amount
                else:
                    tds_amount = Decimal('0')
                    net_amount = int_amount

            # Balance calculation
            new_balance = current_balance_before_this_txn + amount_paid - amount_repaid

            # For compound interest, add net interest to balance only at period end (based on frequency)
            # For simple interest, interest is typically not added to principal until maturity or repayment
            if (customer.interest_type == 'compound' and 
                customer.first_compounding_date and 
                transaction_date >= customer.first_compounding_date and 
                period_to and 
                net_amount):
                
                # Check if this is a period end based on frequency
                is_period_end_for_compounding = False
                
                if customer.compound_frequency == 'yearly':
                    # For yearly compounding, add interest only at FY ends (March 31)
                    is_period_end_for_compounding = _is_yearly_period_end(period_to)
                else:
                    # For other frequencies, use the general period end check
                    is_period_end_for_compounding = _is_period_end(period_to, customer.icl_start_date, customer.compound_frequency or 'quarterly')
                
                if is_period_end_for_compounding:
                    new_balance += net_amount
                    logging.debug(f"Period end ({customer.compound_frequency or 'quarterly'}): adding net interest {net_amount} to balance")
                else:
                    logging.debug(f"Mid-period transaction: interest {net_amount} calculated but NOT added to principal balance")
            else:
                if customer.interest_type == 'compound' and net_amount:
                    logging.debug(f"Before first compounding date or simple interest: interest {net_amount} calculated but NOT added to principal balance")

            # Determine transaction type
            transaction_type = 'passive'  # Default
            if amount_paid > Decimal('0'):
                transaction_type = 'deposit'
            elif amount_repaid > Decimal('0'):
                transaction_type = 'repayment'

            # Save transaction
            transaction = Transaction(
                customer_id=customer_id,
                date=transaction_date,
                amount_paid=amount_paid if amount_paid != Decimal('0') else None,
                amount_repaid=amount_repaid if amount_repaid != Decimal('0') else None,
                balance=new_balance,
                period_from=period_from,
                period_to=period_to,
                no_of_days=no_of_days,
                int_rate=customer.annual_rate,
                int_amount=int_amount,
                tds_amount=tds_amount,
                net_amount=net_amount,
                transaction_type=transaction_type,
                created_by=current_user.id
            )

            db.session.add(transaction)
            db.session.flush()  # Make transaction available for queries without full commit

            # Create post-payment period for compound interest repayments or post-FY periods for yearly compounding
            if create_post_payment_period and post_payment_start <= post_payment_end:
                # Calculate balance after repayment for post-payment period
                balance_after_repayment = current_balance_before_this_txn - amount_repaid

                # For compound interest, include accumulated net interest from previous periods only
                if (customer.interest_type == 'compound' and 
                    customer.first_compounding_date and 
                    post_payment_start >= customer.first_compounding_date):

                    # Get the period start date for this transaction using customer's frequency
                    frequency_for_post_payment = customer.compound_frequency if customer.compound_frequency else 'quarterly'
                    period_start_for_post_payment = _get_period_start_date(post_payment_start, customer.icl_start_date, frequency_for_post_payment)

                    # Get accumulated net interest from transactions before this period starts
                    previous_period_transactions = Transaction.query.filter(
                        Transaction.customer_id == customer_id,
                        Transaction.date < period_start_for_post_payment
                    ).order_by(Transaction.date.asc(), Transaction.id.asc()).all()

                    accumulated_net_interest_from_previous_periods = Decimal('0')
                    for prev_txn in previous_period_transactions:
                        accumulated_net_interest_from_previous_periods += prev_txn.get_safe_net_amount()

                    principal_for_post_payment = balance_after_repayment + accumulated_net_interest_from_previous_periods
                else:
                    principal_for_post_payment = balance_after_repayment

                # Calculate days for post-payment period
                post_payment_days = (post_payment_end - post_payment_start).days + 1

                if post_payment_days > 0 and principal_for_post_payment > Decimal('0'):
                    # Calculate interest for post-payment period
                    post_payment_int_amount = calculate_interest(principal_for_post_payment, customer.annual_rate, post_payment_days)

                    # Calculate TDS for post-payment period
                    post_payment_tds_amount = Decimal('0')
                    if customer.tds_applicable and post_payment_int_amount:
                        tds_rate_to_use = customer.tds_percentage or Decimal('10.00')
                        post_payment_tds_amount = post_payment_int_amount * (tds_rate_to_use / Decimal('100'))

                    post_payment_net_amount = post_payment_int_amount - post_payment_tds_amount

                    # Calculate balance for post-payment period
                    post_payment_balance = balance_after_repayment

                    # For compound interest, add net interest to balance at period end
                    if (customer.interest_type == 'compound' and 
                        customer.first_compounding_date and 
                        post_payment_start >= customer.first_compounding_date and 
                        _is_period_end(post_payment_end, customer.icl_start_date, customer.compound_frequency or 'quarterly') and 
                        post_payment_net_amount):
                        post_payment_balance += post_payment_net_amount
                        logging.debug(f"Post-payment period end ({customer.compound_frequency or 'quarterly'}): adding net interest {post_payment_net_amount} to balance")

                    # Create post-payment period transaction
                    # Use a date slightly after the repayment date for chronological ordering
                    post_payment_date = post_payment_start + timedelta(days=(post_payment_end - post_payment_start).days // 2)

                    post_payment_transaction = Transaction(
                        customer_id=customer_id,
                        date=post_payment_date,
                        amount_paid=None,  # No amount paid in post-payment period
                        amount_repaid=None,  # No amount repaid in post-payment period
                        balance=post_payment_balance,
                        period_from=post_payment_start,
                        period_to=post_payment_end,
                        no_of_days=post_payment_days,
                        int_rate=customer.annual_rate,
                        int_amount=post_payment_int_amount,
                        tds_amount=post_payment_tds_amount,
                        net_amount=post_payment_net_amount,
                        transaction_type='passive',
                        created_by=current_user.id
                    )

                    db.session.add(post_payment_transaction)
                    logging.debug(f"Created post-payment period transaction: {post_payment_start} to {post_payment_end}, interest: {post_payment_int_amount}")

            # For yearly compounding, recalculate passive periods after FY end if needed
            if (customer.interest_type == 'compound' and 
                customer.compound_frequency == 'yearly'):
                
                # Recalculate passive periods for remaining time after FY end with updated principal
                _recalculate_yearly_passive_periods_after_transaction(customer_id, customer, transaction_date, current_user.id)
                logging.debug(f"Recalculated yearly passive periods after transaction on: {transaction_date}")

            # Special handling for ICL end date repayments
            if (customer.icl_end_date and 
                transaction_date == customer.icl_end_date and 
                amount_repaid > Decimal('0')):

                # Check if there's already a passive period transaction that ends on ICL end date
                existing_icl_end_transaction = Transaction.query.filter(
                    Transaction.customer_id == customer_id,
                    Transaction.period_to == customer.icl_end_date,
                    Transaction.transaction_type == 'passive'
                ).first()

                if existing_icl_end_transaction:
                    # Update the existing passive period transaction to include the repayment
                    logging.debug(f"Found existing passive period transaction {existing_icl_end_transaction.id} ending on ICL end date")

                    # Update the existing transaction with repayment details
                    existing_icl_end_transaction.amount_repaid = amount_repaid
                    existing_icl_end_transaction.transaction_type = 'repayment'
                    existing_icl_end_transaction.balance = new_balance  # Use calculated balance

                    # Don't create a new transaction, use the existing one
                    db.session.delete(transaction)  # Remove the new transaction we were about to create
                    transaction = existing_icl_end_transaction  # Use the existing one instead

                    logging.debug(f"Updated existing transaction {transaction.id} with repayment amount {amount_repaid}")
                else:
                    # No existing passive period transaction, proceed with normal ICL end date logic
                    # For ICL end date repayments, ensure the repayment transaction includes proper period and interest calculation
                    if period_from and period_to and no_of_days and no_of_days > 0:
                        # Calculate the final interest on the period including the final period before repayment
                        principal_for_final_interest = current_balance_before_this_txn

                        # Handle accumulated interest calculation based on interest type
                        if customer.interest_type == 'compound' and customer.first_compounding_date:
                            frequency_for_final = customer.compound_frequency if customer.compound_frequency else 'quarterly'
                            final_period_start = _get_period_start_date(customer.icl_end_date, customer.icl_start_date, frequency_for_final)

                            # Get accumulated net interest from transactions before this period starts
                            previous_period_transactions = Transaction.query.filter(
                                Transaction.customer_id == customer_id,
                                Transaction.date < final_period_start
                            ).order_by(Transaction.date.asc(), Transaction.id.asc()).all()

                            accumulated_net_interest = Decimal('0')
                            for prev_txn in previous_period_transactions:
                                accumulated_net_interest += prev_txn.get_safe_net_amount()

                            principal_for_final_interest = current_balance_before_this_txn + accumulated_net_interest
                        else:
                            # For simple interest, only use the current balance before repayment
                            principal_for_final_interest = current_balance_before_this_txn

                        # Calculate interest and TDS for the final period
                        int_amount = calculate_interest(principal_for_final_interest, customer.annual_rate, no_of_days)

                        # Calculate TDS
                        if customer.tds_applicable and int_amount:
                            tds_rate_to_use = customer.tds_percentage or Decimal('10.00')
                            tds_amount = int_amount * (tds_rate_to_use / Decimal('100'))
                            net_amount = int_amount - tds_amount
                        else:
                            tds_amount = Decimal('0')
                            net_amount = int_amount

                        # Update the transaction with calculated values
                        transaction.int_amount = int_amount
                        transaction.tds_amount = tds_amount
                        transaction.net_amount = net_amount

                        logging.debug(f"ICL end date repayment: Calculated interest {int_amount}, TDS {tds_amount}, net {net_amount} using principal {principal_for_final_interest}")

                    # Update balance to calculated value
                    transaction.balance = new_balance

                # Check if balance is approximately zero (-10 to +10) for automatic closure
                if abs(new_balance) <= Decimal('10.00'):
                    # Create loan closure entry for ICL end date
                    final_entry = Transaction(
                        customer_id=customer_id,
                        date=customer.icl_end_date,
                        amount_paid=None,
                        amount_repaid=None,  # The repayment is already recorded in the main transaction
                        balance=Decimal('0'),  # Set balance to zero on closure
                        period_from=None,
                        period_to=None,
                        no_of_days=None,
                        int_rate=None,
                        int_amount=None,
                        tds_amount=None,
                        net_amount=None,
                        transaction_type='loan_closure',
                        created_by=current_user.id
                    )

                    db.session.add(final_entry)

                    # Mark loan as closed
                    customer.loan_closed = True
                    customer.loan_closed_date = customer.icl_end_date
                    db.session.add(customer)

                    flash('Loan automatically closed due to near-zero balance on ICL end date!', 'success')
                else:
                    flash(f'ICL end date repayment processed. Remaining balance: {new_balance}', 'info')
            else:
                # Check for early full repayment (before ICL end date)
                if (amount_repaid > Decimal('0') and 
                    customer.icl_end_date and 
                    transaction_date < customer.icl_end_date and 
                    abs(new_balance) <= Decimal('10.00')):

                    flash(f'Early full repayment detected! Balance is now {new_balance}. '
                          f'Admin can manually close this loan from the customer profile page.', 'info')

                # Auto-update ICL end date to last transaction date if it's later
                last_txn_date = customer.get_last_transaction_date()
                if last_txn_date and (not customer.icl_end_date or last_txn_date > customer.icl_end_date):
                    customer.icl_end_date = max(transaction_date, last_txn_date)
                    db.session.add(customer)

            # Note: No longer automatically filling missing periods to ICL end date
            # Passive periods are only created for gaps between actual transactions

            db.session.commit()
            flash('Transaction added successfully!', 'success')
            return redirect(url_for('transactions', customer_id=customer_id))

        except Exception as e:
            db.session.rollback()
            flash(f'Error adding transaction: {str(e)}', 'error')
            logging.error(f"Transaction error: {e}")

    transactions = Transaction.query.filter_by(customer_id=customer_id).order_by(Transaction.date.desc()).all()
    # Pass the default_period_from to the template
    return render_template('transactions.html', customer=customer, transactions=transactions, default_period_from=default_period_from)


@app.route('/reports')
@login_required
def reports():
    customers = Customer.query.filter_by(is_active=True).all()

    # Calculate statistics in backend for reliability
    total_outstanding = 0
    active_loans = 0
    for customer in customers:
        balance = customer.get_current_balance()
        total_outstanding += balance
        if balance > 0:
            active_loans += 1

    avg_balance = (total_outstanding / len(customers)) if customers else 0

    stats = {
        'total_customers': len(customers),
        'total_outstanding': total_outstanding,
        'active_loans': active_loans,
        'avg_balance': avg_balance
    }

    return render_template('reports.html', customers=customers, stats=stats)

@app.route('/export_customer_report/<int:customer_id>')
@login_required
def export_customer_report(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    transactions = Transaction.query.filter_by(customer_id=customer_id).order_by(Transaction.date).all()

    output = export_to_excel(customer, transactions)
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    response.headers['Content-Disposition'] = f'attachment; filename=customer_report_{customer.icl_no}.xlsx'

    return response



@app.route('/print_customer_profile/<int:customer_id>')
@login_required
def print_customer_profile(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    transactions = Transaction.query.filter_by(customer_id=customer_id).order_by(Transaction.date.desc()).all()
    current_balance = customer.get_current_balance()

    # Generate period summaries
    quarterly_summary = _group_transactions_by_period(customer, transactions, 'quarterly')
    half_yearly_summary = _group_transactions_by_period(customer, transactions, 'half_yearly')
    yearly_summary = _group_transactions_by_period(customer, transactions, 'yearly')

    # Calculate metrics for display
    total_deposits = sum(t.get_safe_amount_paid() for t in transactions)
    total_withdrawals = sum(t.get_safe_amount_repaid() for t in transactions)
    total_interest = sum(t.get_safe_int_amount() for t in transactions)
    total_tds = sum(t.get_safe_tds_amount() for t in transactions)

    metrics = {
        'total_deposits': total_deposits,
        'total_withdrawals': total_withdrawals,
        'total_interest': total_interest,
        'total_tds': total_tds,
        'transaction_count': len(transactions)
    }

    return render_template('customer_profile_print.html',
                           customer=customer,
                           transactions=transactions,
                           current_balance=current_balance,
                           quarterly_summary=quarterly_summary,
                           half_yearly_summary=half_yearly_summary,
                           yearly_summary=yearly_summary,
                           metrics=metrics,
                           current_date=datetime.now())

@app.route('/calculate_realtime_balance/<int:customer_id>', methods=['POST'])
@login_required
def calculate_realtime_balance(customer_id):
    """Calculate balance as of a specific date including accrued interest using same logic as transaction creation"""
    try:
        customer = Customer.query.get_or_404(customer_id)
        as_of_date = datetime.strptime(request.form['as_of_date'], '%Y-%m-%d').date()

        # Check if as_of_date is beyond ICL end date
        if customer.icl_end_date and as_of_date > customer.icl_end_date:
            return jsonify({
                'success': False,
                'error': f'Cannot calculate balance beyond ICL end date ({customer.icl_end_date.strftime("%d-%m-%Y")})'
            }), 400

        # Get all transactions up to the specified date
        transactions = Transaction.query.filter(
            Transaction.customer_id == customer_id,
            Transaction.date <= as_of_date
        ).order_by(Transaction.date.asc(), Transaction.created_at.asc()).all()

        if not transactions:
            return jsonify({
                'success': True,
                'balance': '0.00',
                'principal': '0.00',
                'accrued_interest': '0.00',
                'as_of_date': as_of_date.strftime('%d-%m-%Y')
            })

        # Use the same logic as transaction creation - process transactions chronologically
        current_running_balance = Decimal('0')
        total_principal_movements = Decimal('0')
        total_recorded_interest = Decimal('0')

        for txn in transactions:
            # Add principal movements to running balance
            principal_movement = txn.get_safe_amount_paid() - txn.get_safe_amount_repaid()
            current_running_balance += principal_movement
            total_principal_movements += principal_movement

            # Track all interest for reporting purposes
            total_recorded_interest += txn.get_safe_net_amount()

            # For compound interest, add net interest to balance only at quarter end
            # CRITICAL: Do NOT add interest to balance during mid-quarter periods
            if (customer.interest_type == 'compound' and 
                customer.first_compounding_date and 
                txn.date >= customer.first_compounding_date and 
                txn.period_to and 
                _is_quarter_end(txn.period_to, customer.icl_start_date) and 
                txn.get_safe_net_amount()):

                net_amount = txn.get_safe_net_amount()
                current_running_balance += net_amount
                logging.debug(f"Quarter end: added net interest {net_amount} to balance")
            else:
                if customer.interest_type == 'compound' and txn.get_safe_net_amount():
                    logging.debug(f"Mid-quarter: interest {txn.get_safe_net_amount()} recorded but NOT added to balance")

        current_balance = current_running_balance

        # Find the last transaction to calculate additional interest from
        last_transaction = max(transactions, key=lambda t: (t.date, t.created_at))
        last_transaction_date = last_transaction.period_to or last_transaction.date

        # Calculate additional interest from last transaction period end to as_of_date
        additional_interest = Decimal('0')
        if as_of_date > last_transaction_date:
            days_since_last_transaction = (as_of_date - last_transaction_date).days

            if days_since_last_transaction > 0:
                # Use the same principal calculation logic as transaction creation
                principal_for_calculation = Decimal('0')

                # Check if we're before first compounding date
                is_before_first_compounding = True
                if customer.interest_type == 'compound' and customer.first_compounding_date:
                    if as_of_date >= customer.first_compounding_date:
                        is_before_first_compounding = False

                # For compound interest, include accumulated net interest only from previous periods
        if not is_before_first_compounding:
            # Get the period start date based on customer's compound frequency
            frequency_to_use = customer.compound_frequency if customer.compound_frequency else 'quarterly'
            period_start = _get_period_start_date(as_of_date, customer.icl_start_date, frequency_to_use)

            # Get accumulated net interest only from transactions before this period starts
            previous_period_transactions = Transaction.query.filter(
                Transaction.customer_id == customer_id,
                Transaction.date < period_start
            ).order_by(Transaction.date.asc(), Transaction.id.asc()).all()

            accumulated_net_interest_from_previous_periods = Decimal('0')
            for prev_txn in previous_period_transactions:
                accumulated_net_interest_from_previous_periods += prev_txn.get_safe_net_amount()

            principal_for_calculation = total_principal_movements + accumulated_net_interest_from_previous_periods
        else:
            # For simple interest or before first compounding date, only use principal movements
            principal_for_calculation = total_principal_movements

        # Calculate additional interest using simple interest formula
        additional_interest = calculate_interest(
            principal_for_calculation, 
            customer.annual_rate, 
            days_since_last_transaction
        )

        # Apply TDS if applicable
        if customer.tds_applicable and additional_interest > Decimal('0'):
            tds_rate = customer.tds_percentage or Decimal('10.00')
            tds_amount = additional_interest * (tds_rate / Decimal('100'))
            additional_interest = additional_interest - tds_amount

        # Calculate final balance based on interest type
        if customer.interest_type == 'compound':
            # For compound interest, current_balance already includes:
            # - Principal movements
            # - Quarter-end interest compounding
            # - Repayment adjustments
            # Just add any additional accrued interest since last transaction
            total_balance = current_balance + additional_interest
        else:
            # For simple interest, balance is principal + all accrued interest (not compounded)
            total_balance = total_principal_movements + total_recorded_interest + additional_interest

        return jsonify({
            'success': True,
            'balance': str(total_balance.quantize(Decimal('0.01'))),
            'principal': str(total_principal_movements.quantize(Decimal('0.01'))),
            'recorded_interest': str(total_recorded_interest.quantize(Decimal('0.01'))),
            'accrued_interest': str(additional_interest.quantize(Decimal('0.01'))),
            'as_of_date': as_of_date.strftime('%d-%m-%Y'),
            'days_calculated': (as_of_date - last_transaction_date).days if as_of_date > last_transaction_date else 0,
            'interest_type': customer.interest_type
        })

    except Exception as e:
        logging.error(f"Error calculating real-time balance: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400

@app.route('/export_period_report', methods=['POST'])
@login_required
def export_period_report():
    start_date = datetime.strptime(request.form['start_date'], '%Y-%m-%d').date()
    end_date = datetime.strptime(request.form['end_date'], '%Y-%m-%d').date()

    output = get_period_report(start_date, end_date)
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    response.headers['Content-Disposition'] = f'attachment; filename=period_report_{start_date}_{end_date}.xlsx'

    return response

@app.route('/admin_panel')
@admin_required
def admin_panel():
    users = User.query.all()
    interest_rates = InterestRate.query.order_by(InterestRate.effective_date.desc()).all()
    tds_rates = TDSRate.query.order_by(TDSRate.effective_date.desc()).all()

    return render_template('admin_panel.html', users=users, interest_rates=interest_rates, tds_rates=tds_rates)

@app.route('/create_user', methods=['POST'])
@admin_required
def create_user():
    try:
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        role = request.form['role']

        # Check if user exists
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash('Username already exists!', 'error')
            return redirect(url_for('admin_panel'))

        user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password),
            role=role
        )

        db.session.add(user)
        db.session.commit()
        flash('User created successfully!', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'Error creating user: {str(e)}', 'error')

    return redirect(url_for('admin_panel'))

@app.route('/update_interest_rate', methods=['POST'])
@admin_required
def update_interest_rate():
    try:
        rate = safe_decimal_conversion(request.form['rate'])
        effective_date = datetime.strptime(request.form['effective_date'], '%Y-%m-%d').date()
        description = request.form['description']

        # Deactivate current rates
        InterestRate.query.filter_by(is_active=True).update({'is_active': False})

        # Create new rate
        interest_rate = InterestRate(
            rate=rate,
            effective_date=effective_date,
            description=description,
            created_by=current_user.id
        )

        db.session.add(interest_rate)
        db.session.commit()
        flash('Interest rate updated successfully!', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'Error updating interest rate: {str(e)}', 'error')

    return redirect(url_for('admin_panel'))

@app.route('/update_tds_rate', methods=['POST'])
@admin_required
def update_tds_rate():
    try:
        rate = safe_decimal_conversion(request.form['rate'])
        effective_date = datetime.strptime(request.form['effective_date'], '%Y-%m-%d').date()
        description = request.form['description']

        # Deactivate current rates
        TDSRate.query.filter_by(is_active=True).update({'is_active': False})

        # Create new rate
        tds_rate = TDSRate(
            rate=rate,
            effective_date=effective_date,
            description=description,
            created_by=current_user.id
        )

        db.session.add(tds_rate)
        db.session.commit()
        flash('TDS rate updated successfully!', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'Error updating TDS rate: {str(e)}', 'error')

    return redirect(url_for('admin_panel'))

@app.route('/edit_transaction/<int:transaction_id>', methods=['POST'])
@login_required # Ensure user is logged in
@admin_required # Only admin can edit transactions
def edit_transaction(transaction_id):
    """
    Handles editing a specific transaction and recalculates subsequent transactions.
    """
    transaction = Transaction.query.get_or_404(transaction_id)
    customer_id = transaction.customer_id

    try:
        # Update transaction fields from form data
        transaction.date = datetime.strptime(request.form['date'], '%Y-%m-%d').date()
        amount_paid = safe_decimal_conversion(request.form.get('amount_paid'))
        amount_repaid = safe_decimal_conversion(request.form.get('amount_repaid'))

        transaction.amount_paid = amount_paid if amount_paid != Decimal('0') else None
        transaction.amount_repaid = amount_repaid if amount_repaid != Decimal('0') else None

        # Update transaction type based on amounts
        if amount_paid > Decimal('0'):
            transaction.transaction_type = 'deposit'
        elif amount_repaid > Decimal('0'):
            transaction.transaction_type = 'repayment'
        else:
            transaction.transaction_type = 'passive'

        transaction.period_from = datetime.strptime(request.form['period_from'], '%Y-%m-%d').date() if request.form.get('period_from') else None
        transaction.period_to = datetime.strptime(request.form['period_to'], '%Y-%m-%d').date() if request.form.get('period_to') else None

        # Recalculate no_of_days for this specific transaction
        if transaction.period_from and transaction.period_to:
            transaction.no_of_days = (transaction.period_to - transaction.period_from).days + 1
        else:transaction.no_of_days = 0

        # Don't recalculate int_amount, tds_amount, net_amount, balance here directly.
        # These will be handled by the full recalculation function.
        db.session.add(transaction) # Mark the transaction as modified

        # Recalculate all transactions from this transaction's date onwards
        # This is CRITICAL for maintaining data integrity.
        if recalculate_customer_transactions(customer_id, start_date=transaction.date):
            db.session.commit() # Commit all changes from recalculation
            flash('Transaction updated and subsequent transactions recalculated successfully!', 'success')
        else:
            db.session.rollback() # Rollback if recalculation failed
            flash('Error during transaction update or recalculation.', 'danger')

    except Exception as e:
        db.session.rollback()
        flash(f'Error editing transaction: {str(e)}', 'danger')
        logging.error(f"Error editing transaction {transaction_id}: {e}", exc_info=True)

    return redirect(url_for('transactions', customer_id=customer_id))


@app.route('/delete_transaction/<int:transaction_id>', methods=['POST'])
@login_required # Ensure user is logged in
@admin_required # Only admin can delete transactions
def delete_transaction(transaction_id):
    """
    Handles deleting a specific transaction and recalculates subsequent transactions.
    """
    transaction = Transaction.query.get_or_404(transaction_id)
    customer_id = transaction.customer_id
    transaction_date = transaction.date # Get date before deleting

    try:
        db.session.delete(transaction) # Mark for deletion
        db.session.commit() # Commit deletion first

        # After deletion,# recalculate all transactions from the deleted transaction's date onwards.
        # This is CRITICAL for maintaining data integrity.
        if recalculate_customer_transactions(customer_id, start_date=transaction_date):
            db.session.commit() # Commit changes from recalculation
            flash('Transaction deleted and subsequent transactions recalculated successfully!', 'success')
        else:
            db.session.rollback() # Rollback if recalculation failed
            flash('Error during transaction deletion or recalculation.', 'danger')

    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting transaction: {str(e)}', 'danger')
        logging.error(f"Error deleting transaction {transaction_id}: {e}", exc_info=True)

    return redirect(url_for('transactions', customer_id=customer_id))

def recalculate_customer_transactions(customer_id, start_date=None):
    """
    Recalculates balances, interest, TDS, and net amounts for a customer's transactions
    from a given start_date onwards. This is crucial after an edit or delete.

    Args:
        customer_id (int): The ID of the customer whose transactions need recalculation.
        start_date (datetime.date, optional): The date from which to start recalculating.
                                               If None, all transactions for the customer are recalculated.
    """
    logging.debug(f"Starting recalculation for customer {customer_id} from date {start_date}")

    customer = Customer.query.get(customer_id)
    if not customer:
        logging.error(f"Recalculation failed: Customer with ID {customer_id} not found.")
        return False

    # Fetch all transactions for the customer, ordered by date
    # If a start_date is provided, only fetch transactions from that date onwards.
    transactions_query = Transaction.query.filter_by(customer_id=customer_id).order_by(Transaction.date, Transaction.created_at)

    if start_date:
        transactions_to_recalculate = transactions_query.filter(Transaction.date >= start_date).all()
        # To get the balance *before* the start_date, we need transactions prior to it.
        # Get the balance from the last transaction *before* the start_date.
        previous_transactions = Transaction.query.filter(
            Transaction.customer_id == customer_id,
            Transaction.date < start_date
        ).order_by(Transaction.date.desc(), Transaction.created_at.desc()).first()

        current_running_balance = previous_transactions.get_safe_balance() if previous_transactions else Decimal('0')
        logging.debug(f"Starting recalculation with initial running balance: {current_running_balance} (from last transaction before {start_date})")
    else:
        transactions_to_recalculate = transactions_query.all()
        current_running_balance = Decimal('0') # Start from zero if recalculating all

    if not transactions_to_recalculate:
        logging.info(f"No transactions to recalculate for customer {customer_id} from {start_date}.")
        return True # Nothing to do, considered successful

    try:
        for transaction in transactions_to_recalculate:
            logging.debug(f"Recalculating transaction {transaction.id} (Date: {transaction.date})")

            # Determine principal for interest calculation for *this specific transaction's period*
            # Different logic for simple vs compound interest
            principal_for_interest_calculation = Decimal('0')

            # Check if transaction period is before first compounding date
            should_use_simple_interest = True
            if customer.interest_type == 'compound' and customer.first_compounding_date:
                # Use compound interest only if period_from is on or after first_compounding_date
                if transaction.period_from and transaction.period_from >= customer.first_compounding_date:
                    should_use_simple_interest = False

            # Always use simple interest formula for calculation
            # The difference is only in principal calculation and when to add to balance
            if transaction.get_safe_amount_paid() > Decimal('0'):
                # Deposit — interest on previous balance + current paid amount
                principal_for_interest_calculation = current_running_balance + transaction.get_safe_amount_paid()
                logging.debug(f"  Deposit - Principal for interest (previous balance + deposit): {principal_for_interest_calculation}")
            elif transaction.get_safe_amount_repaid() > Decimal('0'):
                # Repayment — interest on the reduced principal
                principal_for_interest_calculation = current_running_balance - transaction.get_safe_amount_repaid()
                logging.debug(f"  Repayment - Principal for interest (reduced principal): {principal_for_interest_calculation}")
            else:
                # Passive period — interest on previous balance
                principal_for_interest_calculation = current_running_balance
                logging.debug(f"  Passive - Principal for interest (previous balance): {principal_for_interest_calculation}")

            # For compound interest, include accumulated net interest only from previous quarters (not current quarter)
            if not should_use_simple_interest:
                # Get the quarter start date for this transaction
                quarter_start = _get_quarter_start_date(transaction.date, customer.icl_start_date)

                # Get accumulated net interest only from transactions before this quarter starts
                previous_quarter_transactions = Transaction.query.filter(
                    Transaction.customer_id == customer_id,
                    Transaction.date < quarter_start
                ).order_by(Transaction.date.asc(), Transaction.id.asc()).all()

                # Calculate accumulated net interest only from previous quarters
                accumulated_net_interest_from_previous_quarters = Decimal('0')
                for prev_txn in previous_quarter_transactions:
                    accumulated_net_interest_from_previous_quarters += prev_txn.get_safe_net_amount()

                # Add accumulated interest from previous quarters
                if transaction.get_safe_amount_paid() > Decimal('0'):
                    principal_for_interest_calculation = current_running_balance + accumulated_net_interest_from_previous_quarters + transaction.get_safe_amount_paid()
                elif transaction.get_safe_amount_repaid() > Decimal('0'):
                    # For repayment transactions, use principal BEFORE repayment
                    principal_for_interest_calculation = current_running_balance + accumulated_net_interest_from_previous_quarters
                    logging.debug(f"  Repayment transaction - Using principal BEFORE repayment: {principal_for_interest_calculation}")
                else:
                    principal_for_interest_calculation = current_running_balance + accumulated_net_interest_from_previous_quarters

                logging.debug(f"  Compound Interest - Added accumulated net interest from previous quarters {accumulated_net_interest_from_previous_quarters}, final principal: {principal_for_interest_calculation}")

            # Recalculate no_of_days (if period dates are present)
            if transaction.period_from and transaction.period_to:
                transaction.no_of_days = (transaction.period_to - transaction.period_from).days + 1
                logging.debug(f"  Recalculated no_of_days: {transaction.no_of_days}")
            else:
                transaction.no_of_days = 0 # Ensure it's 0 if no period dates
                logging.debug("  No period dates, no_of_days set to 0.")

            # Recalculate Interest Amount
            int_amount = Decimal('0')
            if transaction.period_from and transaction.period_to and transaction.no_of_days > 0 and principal_for_interest_calculation > Decimal('0'):
                if should_use_simple_interest:
                    int_amount = calculate_interest(principal_for_interest_calculation, customer.annual_rate, transaction.no_of_days)
                else:
                    # For compound interest, still use simple interest formula but on compounded principal
                    int_amount = calculate_interest(principal_for_interest_calculation, customer.annual_rate, transaction.no_of_days)
            transaction.int_amount = int_amount
            logging.debug(f"  Recalculated int_amount: {transaction.int_amount}")

            # Recalculate TDS Amount
            tds_amount = Decimal('0')
            if customer.tds_applicable and transaction.int_amount > Decimal('0'):
                tds_rate_to_use = customer.tds_percentage
                if tds_rate_to_use is not None and tds_rate_to_use > Decimal('0'):
                    tds_amount = transaction.int_amount * (tds_rate_to_use / Decimal('100'))
            transaction.tds_amount = tds_amount
            logging.debug(f"  Recalculated tds_amount: {transaction.tds_amount}")

            # Recalculate Net Amount
            transaction.net_amount = transaction.int_amount - transaction.tds_amount
            logging.debug(f"  Recalculated net_amount: {transaction.net_amount}")

            # Update the running balance and transaction balance
            current_running_balance += transaction.get_safe_amount_paid() - transaction.get_safe_amount_repaid()

            # Update balance - always start with principal movements
            new_transaction_balance = current_running_balance

            # For compound interest customers, we need to show accumulated balance including compounded interest
            if customer.interest_type == 'compound' and customer.first_compounding_date:
                # For compound interest, calculate accumulated balance including all previous quarter-end interest
                accumulated_interest_balance = Decimal('0')

                # Get all previous transactions to calculate accumulated interest
                previous_txns_for_balance = Transaction.query.filter(
                    Transaction.customer_id == customer_id,
                    Transaction.date < transaction.date
                ).order_by(Transaction.date.asc(), Transaction.created_at.asc()).all()

                # Add net interest from all previous quarter-end transactions
                for prev_txn in previous_txns_for_balance:
                    if (prev_txn.date >= customer.first_compounding_date and 
                        prev_txn.period_to and 
                        _is_quarter_end(prev_txn.period_to, customer.icl_start_date) and 
                        prev_txn.net_amount):
                        accumulated_interest_balance += prev_txn.net_amount
                        logging.debug(f"Added previous quarter-end interest {prev_txn.net_amount} to accumulated balance")

                # For current transaction, add interest if it's a quarter-end
                if (transaction.date >= customer.first_compounding_date and 
                    transaction.period_to and 
                    _is_quarter_end(transaction.period_to, customer.icl_start_date) and 
                    transaction.net_amount):
                    accumulated_interest_balance += transaction.net_amount
                    # Update running balance to include interest for next transaction
                    current_running_balance += transaction.net_amount
                    logging.debug(f"Quarter end: added current transaction interest {transaction.net_amount} to balance")

                # Final accumulated balance for compound interest
                new_transaction_balance = current_running_balance + accumulated_interest_balance
                logging.debug(f"Compound interest - Final balance: {current_running_balance} + {accumulated_interest_balance} = {new_transaction_balance}")
            else:
                # For simple interest or before first compounding date, just use principal balance
                logging.debug(f"Simple interest or before compounding - Balance: {new_transaction_balance}")

            transaction.balance = new_transaction_balance.quantize(Decimal('0.01'))

            logging.debug(f"  Updated transaction.balance to: {transaction.balance}. Running balance for next txn: {current_running_balance}")

            db.session.add(transaction) # Mark for update

        db.session.commit()
        logging.debug(f"Recalculation for customer {customer_id} completed successfully.")
        return True

    except Exception as e:
        db.session.rollback()
        logging.error(f"Error during recalculation for customer {customer_id}: {e}", exc_info=True)
        return False

def _get_yearly_period_start_date(transaction_date, icl_start_date):
    """
    Calculate the period start date for yearly compounding based on Financial Year (April to March).
    """
    if not transaction_date or not icl_start_date:
        return transaction_date

    # Determine which financial year the transaction falls into
    if transaction_date.month >= 4:  # April to December
        fy_start_year = transaction_date.year
    else:  # January to March
        fy_start_year = transaction_date.year - 1

    # Standard Financial year starts on April 1st
    fy_start = date(fy_start_year, 4, 1)

    # Special case: if ICL start date is after April 1st of the first FY,
    # use ICL start date for the first partial period
    if icl_start_date > fy_start and transaction_date < date(fy_start_year + 1, 4, 1):
        # First partial financial year - use ICL start date
        return icl_start_date
    elif transaction_date < fy_start:
        # Transaction is before current FY start, use previous FY start
        return date(fy_start_year - 1, 4, 1)
    else:
        # Use current financial year start
        return fy_start

def _get_yearly_period_end_date(transaction_date, icl_start_date):
    """
    Calculate the period end date for yearly compounding (always March 31st).
    """
    if not transaction_date or not icl_start_date:
        return transaction_date

    # For yearly compounding, periods always end on March 31st of the financial year
    if transaction_date.month >= 4:  # April to December
        fy_end_year = transaction_date.year + 1
    else:  # January to March
        fy_end_year = transaction_date.year

    return date(fy_end_year, 3, 31)

def _create_yearly_passive_period_for_remaining_time(customer_id, customer, fy_end_date, created_by_user_id):
    """
    Create passive period transaction for time remaining after FY end until ICL end date.
    This handles the case where ICL end date goes beyond March 31.
    """
    if not customer.icl_end_date or customer.icl_end_date <= fy_end_date:
        return None

    # Check if there are any existing transactions in the next FY period
    next_fy_start = fy_end_date + timedelta(days=1)  # April 1st
    
    existing_next_fy_txn = Transaction.query.filter(
        Transaction.customer_id == customer_id,
        Transaction.date >= next_fy_start,
        Transaction.date <= customer.icl_end_date
    ).first()

    if existing_next_fy_txn:
        logging.debug(f"Existing transaction found in next FY period, skipping passive period creation")
        return None

    # Create passive period from April 1st to ICL end date
    period_start = next_fy_start
    period_end = customer.icl_end_date
    
    # Calculate middle date for the transaction
    period_middle = period_start + timedelta(days=(period_end - period_start).days // 2)

    # Get balance before this passive period (including accumulated interest up to FY end)
    previous_txns = Transaction.query.filter(
        Transaction.customer_id == customer_id,
        Transaction.date <= fy_end_date
    ).order_by(Transaction.date.asc(), Transaction.created_at.asc()).all()

    current_balance_before_passive = Decimal('0')
    accumulated_fy_interest = Decimal('0')

    for txn in previous_txns:
        current_balance_before_passive += txn.get_safe_amount_paid() - txn.get_safe_amount_repaid()
        # For yearly compounding, add net interest at FY ends
        if (txn.period_to and 
            txn.period_to.month == 3 and 
            txn.period_to.day == 31 and 
            txn.get_safe_net_amount()):
            accumulated_fy_interest += txn.get_safe_net_amount()

    # Principal for interest calculation includes accumulated FY interest
    principal_for_calculation = current_balance_before_passive + accumulated_fy_interest

    # Calculate days for this passive period
    no_of_days = (period_end - period_start).days + 1

    # Calculate interest for this passive period
    int_amount = calculate_interest(principal_for_calculation, customer.annual_rate, no_of_days)

    # Calculate TDS
    tds_amount = Decimal('0')
    if customer.tds_applicable and int_amount:
        tds_rate_to_use = customer.tds_percentage or Decimal('10.00')
        tds_amount = int_amount * (tds_rate_to_use / Decimal('100'))

    net_amount = int_amount - tds_amount

    # Balance calculation - principal + accumulated interest (no compounding mid-period)
    new_balance = current_balance_before_passive + accumulated_fy_interest

    # Create the passive period transaction
    passive_transaction = Transaction(
        customer_id=customer_id,
        date=period_middle,
        amount_paid=None,
        amount_repaid=None,
        balance=new_balance,
        period_from=period_start,
        period_to=period_end,
        no_of_days=no_of_days,
        int_rate=customer.annual_rate,
        int_amount=int_amount,
        tds_amount=tds_amount,
        net_amount=net_amount,
        transaction_type='passive',
        created_by=created_by_user_id
    )

    db.session.add(passive_transaction)
    logging.debug(f"Created yearly passive period transaction for remaining time: {period_start} to {period_end}, interest: {int_amount}")

    return passive_transaction

def _handle_yearly_compounding_transaction(customer_id, customer, transaction_date, amount_paid, amount_repaid, current_balance_before_txn, created_by_user_id):
    """
    Separate method to handle yearly compounding transactions with proper FY period management.
    This ensures accurate calculation and automatic passive period generation.
    """
    # Get FY period boundaries for this transaction
    fy_start = _get_yearly_period_start_date(transaction_date, customer.icl_start_date)
    fy_end = _get_yearly_period_end_date(transaction_date, customer.icl_start_date)

    # Clean up existing passive periods that need recalculation
    _cleanup_future_passive_periods(customer_id, transaction_date)

    # Determine transaction period boundaries
    if transaction_date <= fy_end:
        # Transaction is within current FY
        period_from = transaction_date if amount_paid > Decimal('0') else fy_start
        period_to = fy_end
        should_create_post_fy_period = customer.icl_end_date and customer.icl_end_date > fy_end
        post_fy_start = fy_end + timedelta(days=1) if should_create_post_fy_period else None
        post_fy_end = customer.icl_end_date if should_create_post_fy_period else None
    else:
        # Transaction spans beyond FY end
        period_from = fy_start
        period_to = fy_end
        should_create_post_fy_period = True
        post_fy_start = fy_end + timedelta(days=1)
        post_fy_end = min(transaction_date, customer.icl_end_date) if customer.icl_end_date else transaction_date

    return period_from, period_to, should_create_post_fy_period, post_fy_start, post_fy_end

def _cleanup_future_passive_periods(customer_id, from_date):
    """
    Clean up passive periods that need recalculation after a new transaction.
    """
    future_passive_periods = Transaction.query.filter(
        Transaction.customer_id == customer_id,
        Transaction.date >= from_date,
        Transaction.transaction_type == 'passive'
    ).all()

    for passive_txn in future_passive_periods:
        logging.debug(f"Deleting outdated passive period transaction {passive_txn.id} for recalculation")
        db.session.delete(passive_txn)

def _calculate_yearly_fy_end_principal(customer_id, fy_end_date):
    """
    Calculate the principal at FY end including all transactions and accumulated interest up to March 31.
    For yearly compounding, ALL net interest within the FY should be compounded.
    """
    # Get the FY start date (April 1st of the financial year)
    if fy_end_date.month == 3:  # March 31st
        fy_start_year = fy_end_date.year - 1
    else:
        fy_start_year = fy_end_date.year
    
    fy_start_date = date(fy_start_year, 4, 1)
    
    # Get all transactions up to FY end (March 31)
    fy_transactions = Transaction.query.filter(
        Transaction.customer_id == customer_id,
        Transaction.date <= fy_end_date
    ).order_by(Transaction.date.asc(), Transaction.created_at.asc()).all()

    # Calculate cumulative principal movements
    cumulative_principal = Decimal('0')
    
    for txn in fy_transactions:
        cumulative_principal += txn.get_safe_amount_paid() - txn.get_safe_amount_repaid()

    # For yearly compounding, add ALL net interest from ALL transactions within the current FY
    # This includes both transactions that end on March 31st AND transactions within the FY period
    accumulated_fy_interest = Decimal('0')
    
    for txn in fy_transactions:
        # Include net interest from transactions that fall within the current FY
        if (txn.period_from and txn.period_from >= fy_start_date and 
            txn.period_to and txn.period_to <= fy_end_date and 
            txn.get_safe_net_amount()):
            accumulated_fy_interest += txn.get_safe_net_amount()
            logging.debug(f"Added FY interest {txn.get_safe_net_amount()} from transaction {txn.id} (period: {txn.period_from} to {txn.period_to})")
        # Also include transactions that end exactly on March 31st (FY end)
        elif (txn.period_to and 
              txn.period_to.month == 3 and 
              txn.period_to.day == 31 and 
              txn.get_safe_net_amount()):
            accumulated_fy_interest += txn.get_safe_net_amount()
            logging.debug(f"Added FY end interest {txn.get_safe_net_amount()} from transaction {txn.id}")

    total_principal_at_fy_end = cumulative_principal + accumulated_fy_interest
    
    logging.debug(f"FY end principal calculation (FY {fy_start_year}-{fy_start_year + 1}): cumulative_principal={cumulative_principal}, accumulated_fy_interest={accumulated_fy_interest}, total={total_principal_at_fy_end}")
    
    return total_principal_at_fy_end

def _calculate_yearly_compounding_periods(customer_id, customer, transaction_date, amount_paid, amount_repaid, current_balance_before_txn, created_by_user_id):
    """
    Handle yearly compounding calculation with automatic FY period splitting and passive period updates.
    For manual passive transactions, calculate only till the user-selected date.
    """
    # Check if this is a manual passive transaction (both amounts are zero)
    is_manual_passive = (amount_paid == Decimal('0') and amount_repaid == Decimal('0'))
    
    if is_manual_passive:
        # For manual passive transactions, calculate period till the selected date only
        # Validate transaction date against ICL end date
        effective_transaction_date = transaction_date
        if customer.icl_end_date and transaction_date > customer.icl_end_date:
            effective_transaction_date = customer.icl_end_date
            logging.debug(f"Manual passive transaction date {transaction_date} beyond ICL end date, adjusted to {effective_transaction_date}")
        
        # Get FY start for the transaction date
        fy_start = _get_yearly_period_start_date(effective_transaction_date, customer.icl_start_date)
        
        # For manual passive transactions, period ends on the selected date (or ICL end date if earlier)
        period_from = fy_start
        period_to = effective_transaction_date
        
        # No post-FY period creation for manual passive transactions
        should_create_post_fy_period = False
        post_fy_start = None
        post_fy_end = None
        
        logging.debug(f"Manual passive transaction: period from {period_from} to {period_to}")
        
        return period_from, period_to, should_create_post_fy_period, post_fy_start, post_fy_end
    else:
        # For regular transactions, use the existing logic
        return _handle_yearly_compounding_transaction(customer_id, customer, transaction_date, amount_paid, amount_repaid, current_balance_before_txn, created_by_user_id)

def _recalculate_yearly_passive_periods_after_transaction(customer_id, customer, transaction_date, created_by_user_id):
    """
    Recalculate all passive periods after a transaction for yearly compounding.
    Uses the new separate calculation method for accuracy.
    """
    if not customer.icl_end_date:
        return

    # Check if we need to create passive periods after this transaction
    current_fy_end = _get_yearly_period_end_date(transaction_date, customer.icl_start_date)
    
    # Only create passive periods if ICL end date goes beyond current FY end
    if customer.icl_end_date <= current_fy_end:
        return

    # Check if there are any existing transactions in the next FY period
    next_fy_start = current_fy_end + timedelta(days=1)  # April 1st
    
    existing_next_fy_txn = Transaction.query.filter(
        Transaction.customer_id == customer_id,
        Transaction.date >= next_fy_start,
        Transaction.date <= customer.icl_end_date,
        Transaction.transaction_type != 'passive'
    ).first()

    if existing_next_fy_txn:
        logging.debug(f"Existing non-passive transaction found in next FY period, skipping passive period creation")
        return

    # Use the new separate method to calculate FY end principal correctly
    principal_for_calculation = _calculate_yearly_fy_end_principal(customer_id, current_fy_end)

    # Create passive period from April 1st to ICL end date with updated principal
    period_start = next_fy_start
    period_end = customer.icl_end_date
    
    # Calculate middle date for the transaction
    period_middle = period_start + timedelta(days=(period_end - period_start).days // 2)

    # Calculate days for this passive period
    no_of_days = (period_end - period_start).days + 1

    if no_of_days > 0 and principal_for_calculation > Decimal('0'):
        # Check if there's already a passive period with these exact dates
        existing_passive_period = Transaction.query.filter(
            Transaction.customer_id == customer_id,
            Transaction.period_from == period_start,
            Transaction.period_to == period_end,
            Transaction.transaction_type == 'passive'
        ).first()

        # Calculate interest for this passive period
        int_amount = calculate_interest(principal_for_calculation, customer.annual_rate, no_of_days)

        # Calculate TDS
        tds_amount = Decimal('0')
        if customer.tds_applicable and int_amount:
            tds_rate_to_use = customer.tds_percentage or Decimal('10.00')
            tds_amount = int_amount * (tds_rate_to_use / Decimal('100'))

        net_amount = int_amount - tds_amount

        # Balance calculation for yearly compounding - includes the principal that will earn interest next period
        new_balance = principal_for_calculation

        if existing_passive_period:
            # Update the existing passive period transaction
            existing_passive_period.int_amount = int_amount
            existing_passive_period.tds_amount = tds_amount
            existing_passive_period.net_amount = net_amount
            existing_passive_period.balance = new_balance
            existing_passive_period.no_of_days = no_of_days
            existing_passive_period.int_rate = customer.annual_rate
            
            db.session.add(existing_passive_period)
            logging.debug(f"Updated existing yearly passive period transaction {existing_passive_period.id}: {period_start} to {period_end}, principal: {principal_for_calculation}, interest: {int_amount}")
        else:
            # Create the updated passive period transaction
            passive_transaction = Transaction(
                customer_id=customer_id,
                date=period_middle,
                amount_paid=None,
                amount_repaid=None,
                balance=new_balance,
                period_from=period_start,
                period_to=period_end,
                no_of_days=no_of_days,
                int_rate=customer.annual_rate,
                int_amount=int_amount,
                tds_amount=tds_amount,
                net_amount=net_amount,
                transaction_type='passive',
                created_by=created_by_user_id
            )

            db.session.add(passive_transaction)
            logging.debug(f"Created new yearly passive period transaction: {period_start} to {period_end}, principal: {principal_for_calculation}, interest: {int_amount}")

def _split_yearly_transaction_at_fy_end(customer_id, customer, transaction_date, amount_paid, amount_repaid, current_balance_before_txn, created_by_user_id):
    """
    Split yearly compounding transaction at FY end (March 31) if transaction spans across FY boundary.
    Returns tuple: (period_from, period_to, should_create_post_fy_period, post_fy_start, post_fy_end)
    """
    return _calculate_yearly_compounding_periods(customer_id, customer, transaction_date, amount_paid, amount_repaid, current_balance_before_txn, created_by_user_id)

def _get_period_start_date(transaction_date, icl_start_date, frequency='quarterly'):
    """
    Calculate the period start date based on transaction date, ICL start date, and frequency.
    """
    if not transaction_date or not icl_start_date:
        return transaction_date

    if frequency == 'yearly':
        return _get_yearly_period_start_date(transaction_date, icl_start_date)
    elif frequency == 'monthly':
        # Calculate total months from ICL start to transaction date
        months_from_start = (transaction_date.year - icl_start_date.year) * 12 + (transaction_date.month - icl_start_date.month)

        # Calculate year and month for period start
        target_year = icl_start_date.year
        target_month = icl_start_date.month + months_from_start

        # Handle year overflow
        while target_month > 12:
            target_month -= 12
            target_year += 1

        target_day = min(icl_start_date.day, _get_last_day_of_month(target_year, target_month))
        return date(target_year, target_month, target_day)

    else:  # quarterly (default)
        # Calculate total days from ICL start to transaction date
        days_from_start = (transaction_date - icl_start_date).days

        # Calculate which quarter this transaction falls into (0-based)
        quarter_number = days_from_start // 90  # 90 days per quarter (approximately)

        # Calculate the exact quarter start date
        # Each quarter is exactly 3 months from the ICL start date
        months_to_add = quarter_number * 3

        # Calculate year and month for quarter start
        target_year = icl_start_date.year
        target_month = icl_start_date.month + months_to_add

        # Handle year overflow
        while target_month > 12:
            target_month -= 12
            target_year += 1

        target_day = icl_start_date.day

        # Create the quarter start date
        try:
            quarter_start = date(target_year, target_month, target_day)
        except ValueError:
            # Handle edge case where day doesn't exist in target month (e.g., Feb 30)
            target_day = min(target_day, _get_last_day_of_month(target_year, target_month))
            quarter_start = date(target_year, target_month, target_day)

        return quarter_start

def _get_last_day_of_month(year, month):
    """Get the last day of a given month and year."""
    if month in [1, 3, 5, 7, 8, 10, 12]:
        return 31
    elif month in [4, 6, 9, 11]:
        return 30
    else:  # February
        if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0):
            return 29
        else:
            return 28

def _get_quarter_start_date(transaction_date, icl_start_date):
    """
    Backward compatibility function - calls _get_period_start_date with quarterly frequency.
    """
    return _get_period_start_date(transaction_date, icl_start_date, 'quarterly')

def _get_period_end_date(transaction_date, icl_start_date, frequency='quarterly'):
    """
    Calculate the period end date based on transaction date, ICL start date, and frequency.
    """
    if not transaction_date or not icl_start_date:
        return transaction_date

    if frequency == 'yearly':
        return _get_yearly_period_end_date(transaction_date, icl_start_date)
    elif frequency == 'monthly':
        # Get the period start
        period_start = _get_period_start_date(transaction_date, icl_start_date, 'monthly')

        # Calculate next month
        if period_start.month == 12:
            next_month_start = date(period_start.year + 1, 1, period_start.day)
        else:
            next_month_day = min(period_start.day, _get_last_day_of_month(period_start.year, period_start.month + 1))
            next_month_start = date(period_start.year, period_start.month + 1, next_month_day)

        return next_month_start - timedelta(days=1)

    else:  # quarterly (default)
        # Calculate total days from ICL start to transaction date
        days_from_start = (transaction_date - icl_start_date).days

        # Calculate which quarter this transaction falls into (0-based)
        quarter_number = days_from_start // 90  # 90 days per quarter (approximately)

        # Calculate the exact quarter end date
        # Each quarter is exactly 3 months from the ICL start date
        months_to_add = (quarter_number + 1) * 3

        # Calculate year and month for quarter end
        target_year = icl_start_date.year
        target_month = icl_start_date.month + months_to_add

        # Handle year overflow
        while target_month > 12:
            target_month -= 12
            target_year += 1

        # Get the day before the start of next quarter (which is the quarter end)
        # Start with ICL start day, then subtract 1 day
        target_day = icl_start_date.day

        # Create the start of next quarter first
        try:
            next_quarter_start = date(target_year, target_month, target_day)
        except ValueError:
            # Handle edge case where day doesn't exist in target month (e.g., Feb 30)
            target_day = min(target_day, _get_last_day_of_month(target_year, target_month))
            next_quarter_start = date(target_year, target_month, target_day)

        # Quarter end is one day before the next quarter starts
        quarter_end = next_quarter_start - timedelta(days=1)

        return quarter_end

def _get_quarter_end_date(transaction_date, icl_start_date):
    """
    Backward compatibility function - calls _get_period_end_date with quarterly frequency.
    """
    return _get_period_end_date(transaction_date, icl_start_date, 'quarterly')

def _is_yearly_period_end(date_to_check):
    """
    Check if a given date is March 31st (Financial Year end).
    """
    return date_to_check.month == 3 and date_to_check.day == 31

def _is_period_end(date_to_check, icl_start_date, frequency='quarterly'):
    """
    Check if a given date falls at the end of a financial period, based on the customer's ICL start date and frequency.
    """
    if not date_to_check or not icl_start_date:
        return False

    if frequency == 'yearly':
        return _is_yearly_period_end(date_to_check)

    # Calculate expected period end for this date
    expected_period_end = _get_period_end_date(date_to_check, icl_start_date, frequency)

    return date_to_check == expected_period_end

def _is_quarter_end(date_to_check, icl_start_date):
    """
    Backward compatibility function - calls _is_period_end with quarterly frequency.
    """
    return _is_period_end(date_to_check, icl_start_date, 'quarterly')

def _get_all_missing_periods_until_transaction(customer_id, customer, transaction_date):
    """
    Function to identify missing periods only between existing transactions.
    This ensures no gaps exist between actual transactions, but does not extend beyond the last transaction.
    Returns a list of (start_date, end_date) tuples for missing periods.
    """
    missing_periods = []

    if not customer.icl_start_date or not transaction_date:
        return missing_periods

    # Get all existing transactions for this customer, sorted by date
    existing_transactions = Transaction.query.filter_by(customer_id=customer_id).order_by(Transaction.date.asc(), Transaction.created_at.asc()).all()

    # Determine frequency to use
    frequency_to_use = 'quarterly'
    if customer.interest_type == 'compound' and customer.compound_frequency:
        frequency_to_use = customer.compound_frequency

    # Create a set of all periods that should have transactions
    covered_periods = set()

    # Add periods covered by existing transactions
    for txn in existing_transactions:
        if txn.period_from and txn.period_to:
            period_start = _get_period_start_date(txn.date, customer.icl_start_date, frequency_to_use)
            covered_periods.add(period_start)

    # Add the period for the current transaction being added
    current_period_start = _get_period_start_date(transaction_date, customer.icl_start_date, frequency_to_use)
    covered_periods.add(current_period_start)

    # Only generate periods between ICL start and current transaction date
    # Do NOT extend to ICL end date
    expected_periods = []
    current_period_start = customer.icl_start_date

    # Use only the transaction date as the end boundary, not ICL end date
    end_boundary = transaction_date

    while current_period_start <= end_boundary:
        period_start = _get_period_start_date(current_period_start, customer.icl_start_date, frequency_to_use)
        period_end = _get_period_end_date(current_period_start, customer.icl_start_date, frequency_to_use)

        # Only add if period start is not beyond the transaction date
        if period_start <= end_boundary:
            expected_periods.append((period_start, period_end))

        # Move to next period based on frequency
        if frequency_to_use == 'yearly':
            # Move to next financial year (April 1st)
            if current_period_start.month >= 4:
                current_period_start = date(current_period_start.year + 1, 4, 1)
            else:
                current_period_start = date(current_period_start.year, 4, 1)
        elif frequency_to_use == 'monthly':
            # Move to next month
            if current_period_start.month == 12:
                current_period_start = current_period_start.replace(year=current_period_start.year + 1, month=1)
            else:
                current_period_start = current_period_start.replace(month=current_period_start.month + 1)
        else:  # quarterly
            # Move to next quarter (add 3 months)
            if current_period_start.month <= 9:
                current_period_start = current_period_start.replace(month=current_period_start.month + 3)
            else:
                # Handle year transition
                new_month = current_period_start.month + 3 - 12
                current_period_start = current_period_start.replace(year=current_period_start.year + 1, month=new_month)

    # Find missing periods only between actual transactions
    for period_start, period_end in expected_periods:
        if period_start not in covered_periods:
            # Verify this period doesn't already have a transaction
            existing_in_period = Transaction.query.filter(
                Transaction.customer_id == customer_id,
                Transaction.period_from == period_start,
                Transaction.period_to == period_end
            ).first()

            if not existing_in_period:
                # Double-check by also looking for any transaction that covers this period
                overlapping_txn = Transaction.query.filter(
                    Transaction.customer_id == customer_id,
                    Transaction.period_from <= period_end,
                    Transaction.period_to >= period_start
                ).first()

                if not overlapping_txn:
                    missing_periods.append((period_start, period_end))
                    logging.debug(f"Found missing {frequency_to_use} period: {period_start} to {period_end}")
                else:
                    logging.debug(f"Found overlapping transaction for period {period_start} to {period_end}, skipping")

    # Sort missing periods by start date
    missing_periods.sort(key=lambda x: x[0])

    logging.debug(f"Total missing periods found: {len(missing_periods)}")
    return missing_periods

def _create_passive_period_transaction(customer_id, customer, period_start, period_end, created_by_user_id):
    """
    Create a passive period transaction (no amount paid/repaid, only accumulated interest).
    """
    from models import Transaction

    # Check if a transaction already exists for this period
    existing_period_txn = Transaction.query.filter(
        Transaction.customer_id == customer_id,
        Transaction.period_from == period_start,
        Transaction.period_to == period_end
    ).first()
    
    if existing_period_txn:
        logging.debug(f"Transaction already exists for period {period_start} to {period_end}, skipping passive period creation")
        return existing_period_txn

    # Calculate the period in the middle for the transaction date
    period_middle = period_start + timedelta(days=(period_end - period_start).days // 2)

    # Calculate balance before this passive period
    previous_txns = Transaction.query.filter(
        Transaction.customer_id == customer_id,
        Transaction.date < period_middle
    ).order_by(Transaction.date.asc(), Transaction.created_at.asc()).all()

    current_balance_before_passive = Decimal('0')
    frequency_to_use = customer.compound_frequency if customer.compound_frequency else 'quarterly'

    for txn in previous_txns:
        current_balance_before_passive += txn.get_safe_amount_paid() - txn.get_safe_amount_repaid()
        # For compound interest, add net interest at period ends
        if (customer.interest_type == 'compound' and 
            customer.first_compounding_date and 
            txn.date >= customer.first_compounding_date and 
            txn.period_to and 
            _is_period_end(txn.period_to, customer.icl_start_date, frequency_to_use) and 
            txn.get_safe_net_amount()):
            current_balance_before_passive += txn.get_safe_net_amount()

    # Calculate days for this passive period
    no_of_days = (period_end - period_start).days + 1

    # Calculate interest for this passive period
    principal_for_calculation = current_balance_before_passive

    # For compound interest, include accumulated net interest from previous periods only
    if (customer.interest_type == 'compound' and 
        customer.first_compounding_date and 
        period_middle >= customer.first_compounding_date):

        # Get accumulated net interest from transactions before this period starts
        previous_period_transactions = Transaction.query.filter(
            Transaction.customer_id == customer_id,
            Transaction.date < period_start
        ).order_by(Transaction.date.asc(), Transaction.id.asc()).all()

        accumulated_net_interest_from_previous_periods = Decimal('0')
        for prev_txn in previous_period_transactions:
            accumulated_net_interest_from_previous_periods += prev_txn.get_safe_net_amount()

        principal_for_calculation = current_balance_before_passive + accumulated_net_interest_from_previous_periods

    # Calculate interest
    int_amount = calculate_interest(principal_for_calculation, customer.annual_rate, no_of_days)

    # Calculate TDS
    tds_amount = Decimal('0')
    if customer.tds_applicable and int_amount:
        tds_rate_to_use = customer.tds_percentage or Decimal('10.00')
        tds_amount = int_amount * (tds_rate_to_use / Decimal('100'))

    net_amount = int_amount - tds_amount

    # Balance calculation
    new_balance = current_balance_before_passive

    # For compound interest, add net interest to balance at period end
    if (customer.interest_type == 'compound' and 
        customer.first_compounding_date and 
        period_middle >= customer.first_compounding_date and 
        _is_period_end(period_end, customer.icl_start_date, frequency_to_use) and 
        net_amount):
        new_balance += net_amount
        logging.debug(f"Passive {frequency_to_use} period end: adding net interest {net_amount} to balance")

    # Create the passive period transaction
    passive_transaction = Transaction(
        customer_id=customer_id,
        date=period_middle,
        amount_paid=None,  # No amount paid
        amount_repaid=None,  # No amount repaid
        balance=new_balance,
        period_from=period_start,
        period_to=period_end,
        no_of_days=no_of_days,
        int_rate=customer.annual_rate,
        int_amount=int_amount,
        tds_amount=tds_amount,
        net_amount=net_amount,
        transaction_type='passive',
        created_by=created_by_user_id
    )

    db.session.add(passive_transaction)
    logging.debug(f"Created passive period transaction: {period_start} to {period_end}, interest: {int_amount}")

    return passive_transaction

def _calculate_priority(days_overdue, balance):
    """Calculate priority level for overdue loans"""
    if days_overdue > 90:
        return 'critical'
    elif days_overdue > 30:
        return 'high'
    elif days_overdue > 7:
        return 'medium'
    else:
        return 'low'

def _calculate_risk_level(days_past_due, balance):
    """Calculate risk level for past due loans"""
    if days_past_due > 90:
        return 'critical'
    elif days_past_due > 30:
        return 'high'
    elif days_past_due > 7:
        return 'medium'
    else:
        return 'low'

def _calculate_daily_interest(balance, annual_rate):
    """Calculate daily interest amount"""
    if not balance or not annual_rate:
        return Decimal('0')
    return (balance * annual_rate / Decimal('100') / Decimal('365')).quantize(Decimal('0.01'))

def _calculate_accrued_penalty(balance, annual_rate, days_overdue):
    """Calculate accrued penalty interest for overdue loans"""
    if not balance or not annual_rate or not days_overdue:
        return Decimal('0')
    daily_interest = _calculate_daily_interest(balance, annual_rate)
    # Apply penalty rate (e.g., 2% additional penalty)
    penalty_rate = Decimal('1.02')  # 2% penalty
    return (daily_interest * penalty_rate * days_overdue).quantize(Decimal('0.01'))

def _calculate_potential_loss(balance, annual_rate, days_past_due):
    """Calculate potential loss for past due loans"""
    if not balance or not annual_rate or not days_past_due:
        return Decimal('0')
    daily_interest = _calculate_daily_interest(balance, annual_rate)
    return (daily_interest * days_past_due).quantize(Decimal('0.01'))

def _group_transactions_by_period(customer, transactions, period_type):
    """
    Aggregates transactions into quarterly, half_yearly, or yearly periods
    starting from the customer's ICL start date.
    """
    logging.debug(f"Starting _group_transactions_by_period for customer {customer.id}, type: {period_type}")
    summary_data = []
    if not customer or not customer.icl_start_date:
        logging.debug("Customer or ICL start date missing, returning empty summary.")
        return summary_data

    start_date_of_customer = customer.icl_start_date

    # Sort transactions by date and creation_at to ensure correct chronological processing
    sorted_transactions = sorted(transactions, key=lambda t: (t.date, t.created_at))
    logging.debug(f"Sorted transactions count: {len(sorted_transactions)}")

    # Initialize running balance before the first period
    current_running_balance_for_summary = Decimal('0')

    # Calculate initial balance from transactions *before* the ICL start date
    # This ensures the first period's opening balance is correct if there are historical transactions
    pre_icl_transactions = [t for t in sorted_transactions if t.date < start_date_of_customer]
    for t in pre_icl_transactions:
        current_running_balance_for_summary += t.get_safe_amount_paid() - t.get_safe_amount_repaid()
        current_running_balance_for_summary += t.get_safe_net_amount()
    logging.debug(f"Initial running balance before ICL start date ({start_date_of_customer}): {current_running_balance_for_summary}")


    current_period_start = start_date_of_customer

    # Determine the overall end date for the summary (latest transaction date or today)
    if sorted_transactions:
        max_transaction_date = sorted_transactions[-1].date
    else:
        max_transaction_date = date.today() # If no transactions, summarize up to today

    overall_end_date = max(max_transaction_date, date.today()) # Ensure we go up to today if no future transactions
    logging.debug(f"Overall summary end date: {overall_end_date}")

    # Keep track of the index for sorted_transactions to avoid re-iterating
    transaction_idx = 0

    while current_period_start <= overall_end_date:
        period_name = ""
        period_end = None

        if period_type == 'quarterly':
            # Calculate end of quarter
            year = current_period_start.year
            month = current_period_start.month

            if month >= 1 and month <= 3:
                period_end = date(year, 3, 31)
                period_name = f"Q1 {year}"
            elif month >= 4 and month <= 6:
                period_end = date(year, 6, 30)
                period_name = f"Q2 {year}"
            elif month >= 7 and month <= 9:
                period_end = date(year, 9, 30)
                period_name = f"Q3 {year}"
            else: # month >= 10 and month <= 12:
                period_end = date(year, 12, 31)
                period_name = f"Q4 {year}"
        elif period_type == 'half_yearly':
            # Calculate end of half-year
            year = current_period_start.year
            if current_period_start.month <= 6:
                period_end = date(year, 6, 30)
                period_name = f"H1 {year}"
            else:
                period_end = date(year, 12, 31)
                period_name = f"H2 {year}"
        elif period_type == 'yearly':
            # Calculate end of year
            year = current_period_start.year
            period_end = date(year, 12, 31)
            period_name = f"Year {year}"

        # Adjust period_end if it goes beyond overall_end_date (e.g., current period)
        if period_end > overall_end_date:
            period_end = overall_end_date

        # Ensure actual_period_start is not before customer's ICL start date for the very first period
        actual_period_start = max(current_period_start, start_date_of_customer)

        logging.debug(f"Processing period: {period_name} from {actual_period_start} to {period_end}")

        total_paid_in_period = Decimal('0')
        total_repaid_in_period = Decimal('0')
        total_interest_in_period = Decimal('0')
        total_tds_in_period = Decimal('0')
        total_net_amount_in_period = Decimal('0')

        # Capture opening balance for the current period
        opening_balance_for_period = current_running_balance_for_summary

        # Iterate through transactions from the last processed point
        transactions_in_period = []
        while transaction_idx < len(sorted_transactions) and \
              sorted_transactions[transaction_idx].date <= period_end:

            t = sorted_transactions[transaction_idx]
            if t.date >= actual_period_start: # Only include if within the current period's bounds
                transactions_in_period.append(t)
                total_paid_in_period += t.get_safe_amount_paid()
                total_repaid_in_period += t.get_safe_amount_repaid()
                total_interest_in_period += t.get_safe_int_amount()
                total_tds_in_period += t.get_safe_tds_amount()
                total_net_amount_in_period += t.get_safe_net_amount()

                # Update running balance for the next period's opening balance
                current_running_balance_for_summary += t.get_safe_amount_paid() - t.get_safe_amount_repaid()
                current_running_balance_for_summary += t.get_safe_net_amount()
            transaction_idx += 1 # Move to the next transaction

        # Capture closing balance for the current period
        closing_balance_for_period = current_running_balance_for_summary

        # Use the natural closing balance without any adjustments
        adjusted_closing_balance = closing_balance_for_period

        logging.debug(f"  Period totals: Paid={total_paid_in_period}, Repaid={total_repaid_in_period}, Interest={total_interest_in_period}, Closing Balance={closing_balance_for_period}, Adjusted Closing Balance={adjusted_closing_balance}")

        # Only add period if it contains transactions or if it's the current/last period
        # and has a non-zero balance or if it's the first period.
        # Also, ensure period_end is not before actual_period_start (can happen with single-day periods or edge cases)
        if actual_period_start <= period_end and \
           (transactions_in_period or \
           (actual_period_start <= date.today() <= period_end) or \
           (actual_period_start == start_date_of_customer) or \
           (opening_balance_for_period != Decimal('0') or closing_balance_for_period != Decimal('0'))):

            summary_data.append({
                'period_name': period_name,
                'start_date': actual_period_start,
                'end_date': period_end,
                'opening_balance': opening_balance_for_period.quantize(Decimal('0.01')),
                'total_paid': total_paid_in_period.quantize(Decimal('0.01')),
                'total_repaid': total_repaid_in_period.quantize(Decimal('0.01')),
                'total_interest': total_interest_in_period.quantize(Decimal('0.01')),
                'total_tds': total_tds_in_period.quantize(Decimal('0.01')),
                'total_net_amount': total_net_amount_in_period.quantize(Decimal('0.01')),
                'closing_balance': closing_balance_for_period.quantize(Decimal('0.01')),
                'adjusted_closing_balance': closing_balance_for_period.quantize(Decimal('0.01')),
                'is_fy_summary': False
            })

            # Check if this period ends on March 31st (FY end) and add FY summary row
            if period_type == 'quarterly' and period_end.month == 3 and period_end.day == 31:
                # Calculate FY summary from April 1st to March 31st
                fy_start_year = period_end.year - 1 if period_end.month <= 3 else period_end.year
                fy_start = date(fy_start_year, 4, 1)
                fy_end = period_end

                # Calculate cumulative totals for the entire FY
                fy_total_paid = Decimal('0')
                fy_total_repaid = Decimal('0')
                fy_total_interest = Decimal('0')
                fy_total_tds = Decimal('0')
                fy_total_net_amount = Decimal('0')

                # Get all transactions in this FY period
                fy_transactions = Transaction.query.filter(
                    Transaction.customer_id == customer.id,
                    Transaction.date >= fy_start,
                    Transaction.date <= fy_end
                ).all()

                for txn in fy_transactions:
                    fy_total_paid += txn.get_safe_amount_paid()
                    fy_total_repaid += txn.get_safe_amount_repaid()
                    fy_total_interest += txn.get_safe_int_amount()
                    fy_total_tds += txn.get_safe_tds_amount()
                    fy_total_net_amount += txn.get_safe_net_amount()

                # Get opening balance at FY start
                fy_opening_balance = Decimal('0')
                pre_fy_transactions = Transaction.query.filter(
                    Transaction.customer_id == customer.id,
                    Transaction.date < fy_start
                ).order_by(Transaction.date.asc(), Transaction.created_at.asc()).all()

                for txn in pre_fy_transactions:
                    fy_opening_balance += txn.get_safe_amount_paid() - txn.get_safe_amount_repaid()
                    fy_opening_balance += txn.get_safe_net_amount()

                # FY closing balance is the same as current period's closing balance
                fy_closing_balance = adjusted_closing_balance

                summary_data.append({
                    'period_name': f'FY {fy_start_year}-{fy_start_year + 1} Summary',
                    'start_date': fy_start,
                    'end_date': fy_end,
                    'opening_balance': fy_opening_balance.quantize(Decimal('0.01')),
                    'total_paid': fy_total_paid.quantize(Decimal('0.01')),
                    'total_repaid': fy_total_repaid.quantize(Decimal('0.01')),
                    'total_interest': fy_total_interest.quantize(Decimal('0.01')),
                    'total_tds': fy_total_tds.quantize(Decimal('0.01')),
                    'total_net_amount': fy_total_net_amount.quantize(Decimal('0.01')),
                    'closing_balance': fy_closing_balance.quantize(Decimal('0.01')),
                    'adjusted_closing_balance': fy_closing_balance.quantize(Decimal('0.01')),
                    'is_fy_summary': True
                })

        # Move to the next period
        if period_type == 'quarterly':
            # Advance to the first day of the next quarter
            if period_end.month == 12: # If current quarter ends in Dec, next is Jan of next year
                current_period_start = date(period_end.year + 1, 1, 1)
            else: # Otherwise, next quarter starts 3 months from current quarter's start month
                next_month = ((period_end.month - 1) // 3 + 1) * 3 + 1  # Always an integer
                if next_month > 12:
                    # Roll over to next year, correct month
                    month = next_month - 12
                    year = period_end.year + 1
                else:
                    month = next_month
                    year = period_end.year

                current_period_start = date(year, month, 1)
        elif period_type == 'half_yearly':
            # Advance to the first day of the next half-year
            if period_end.month == 6: # If current half-year ends in June, next starts in July
                current_period_start = date(period_end.year, 7, 1)
            else: # If current half-year ends in December, next starts in January of next year
                current_period_start = date(period_end.year + 1, 1, 1)
        elif period_type == 'yearly':
            current_period_start = date(current_period_start.year + 1, 1, 1)

        # Break condition to prevent infinite loops if logic goes awry
        if current_period_start > date.today() + timedelta(days=365 * 2): # Stop if more than 2 years into future
            logging.warning("Breaking period summary loop: current_period_start too far in future.")
            break

    logging.debug(f"Finished _group_transactions_by_period. Total periods: {len(summary_data)}")
    return summary_data

# Function removed - no longer automatically filling periods to ICL end date
# Passive periods are only created for gaps between actual transactions
