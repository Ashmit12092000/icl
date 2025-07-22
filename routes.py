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
                           recent_transactions=recent_transactions)

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
    """Close a customer's loan"""
    customer = Customer.query.get_or_404(customer_id)

    try:
        customer.loan_closed = True
        customer.loan_closed_date = date.today()
        db.session.commit()
        flash(f'Loan for customer "{customer.name}" has been closed successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error closing loan for customer "{customer.name}": {e}', 'error')
        app.logger.error(f"Error closing loan for customer {customer_id}: {e}")

    return redirect(url_for('customer_profile', customer_id=customer_id))

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

            # Check if transaction date is beyond ICL end date
            if customer.icl_end_date and transaction_date > customer.icl_end_date:
                flash(f'Transaction date cannot be beyond ICL end date ({customer.icl_end_date.strftime("%d-%m-%Y")})', 'error')
                transactions = Transaction.query.filter_by(customer_id=customer_id).order_by(Transaction.date.desc()).all()
                return render_template('transactions.html', customer=customer, transactions=transactions, default_period_from=default_period_from)

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

                    # For other cases (deposits or compound interest), use existing logic
                    # Check if there's an ongoing period that needs to be split
                    ongoing_txn = Transaction.query.filter(
                        Transaction.customer_id == customer_id,
                        Transaction.period_from <= transaction_date,
                        Transaction.period_to >= transaction_date
                    ).order_by(Transaction.date.desc(), Transaction.created_at.desc()).first()

                    if ongoing_txn and ongoing_txn.date != transaction_date:
                        # Split the ongoing period
                        # For repayments: current transaction should be in the period ending on repayment date
                        # For deposits: current transaction starts a new period from transaction date

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

                    # Calculate adjustment for repayment transactions in previous quarters
                    # For compound interest users, subtract net amounts from repayment transactions
                    repayment_adjustment = Decimal('0')
                    if customer.interest_type == 'compound':
                        for prev_txn in previous_quarter_transactions:
                            if prev_txn.transaction_type == 'repayment':
                                repayment_adjustment += prev_txn.get_safe_net_amount()

                    # For transactions after first compounding date, principal = previous principal + accumulated interest from previous quarters - repayment adjustments
                    if amount_paid > Decimal('0'):
                        # Deposit — interest on (previous balance + accumulated interest from previous quarters - repayment adjustments) + current paid
                        principal_for_interest_calculation = current_balance_before_this_txn + accumulated_net_interest_from_previous_quarters - repayment_adjustment + amount_paid
                    elif amount_repaid > Decimal('0'):
                        # Repayment — interest on (previous balance + accumulated interest from previous quarters - repayment adjustments) - current repaid
                        principal_for_interest_calculation = current_balance_before_this_txn + accumulated_net_interest_from_previous_quarters - repayment_adjustment - amount_repaid
                    else:
                        # Passive period — interest on (previous balance + accumulated```python

                        principal_for_interest_calculation = current_balance_before_this_txn + accumulated_net_interest_from_previous_quarters - repayment_adjustment

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
                _is_period_end(period_to, customer.icl_start_date, customer.compound_frequency or 'quarterly') and 
                net_amount):
                new_balance += net_amount
                logging.debug(f"Period end ({customer.compound_frequency or 'quarterly'}): adding net interest {net_amount} to balance")
            else:
                if customer.interest_type == 'compound' and net_amount:
                    logging.debug(f"Mid-period transaction: interest {net_amount} calculated but NOT added to principal balance")

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

            # Create post-payment period for compound interest repayments if needed
            if create_post_payment_period and post_payment_start <= post_payment_end:
                # Calculate balance after repayment for post-payment period
                balance_after_repayment = current_balance_before_this_txn - amount_repaid

                # For compound interest, include accumulated net interest from previous quarters only
                if (customer.interest_type == 'compound' and 
                    customer.first_compounding_date and 
                    post_payment_start >= customer.first_compounding_date):

                    # Get accumulated net interest from transactions before this quarter starts
                    previous_quarter_transactions = Transaction.query.filter(
                        Transaction.customer_id == customer_id,
                        Transaction.date < quarter_start
                    ).order_by(Transaction.date.asc(), Transaction.id.asc()).all()

                    accumulated_net_interest_from_previous_quarters = Decimal('0')
                    repayment_adjustment = Decimal('0')
                    for prev_txn in previous_quarter_transactions:
                        accumulated_net_interest_from_previous_quarters += prev_txn.get_safe_net_amount()
                        if prev_txn.transaction_type == 'repayment':
                            repayment_adjustment += prev_txn.get_safe_net_amount()

                    principal_for_post_payment = balance_after_repayment + accumulated_net_interest_from_previous_quarters - repayment_adjustment
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

            # Special handling for ICL end date repayments
            if (customer.icl_end_date and 
                transaction_date == customer.icl_end_date and 
                amount_repaid > Decimal('0')):
                
                # For both simple and compound interest customers, ensure final period interest is calculated
                # before creating the loan closure transaction
                if customer.interest_type in ['compound', 'simple']:
                    # Determine the appropriate frequency for final period calculation
                    if customer.interest_type == 'compound' and customer.compound_frequency:
                        frequency_to_use = customer.compound_frequency
                    else:
                        frequency_to_use = 'quarterly'  # Default to quarterly for simple interest
                    
                    # Check if there's already a transaction for the final period
                    final_period_start = _get_period_start_date(customer.icl_end_date, customer.icl_start_date, frequency_to_use)
                    
                    # Look for existing transactions that cover this final period
                    # Check both exact match and overlapping periods
                    existing_final_period_txn = Transaction.query.filter(
                        Transaction.customer_id == customer_id,
                        Transaction.period_from == final_period_start,
                        Transaction.period_to == customer.icl_end_date,
                        Transaction.date < transaction_date,
                        Transaction.transaction_type == 'passive'  # Only look for passive period transactions
                    ).first()
                    
                    # Also check if there's any transaction that overlaps with this period
                    overlapping_txn = Transaction.query.filter(
                        Transaction.customer_id == customer_id,
                        Transaction.period_from <= customer.icl_end_date,
                        Transaction.period_to >= final_period_start,
                        Transaction.date < transaction_date,
                        Transaction.transaction_type == 'passive'
                    ).first()
                    
                    # If no passive transaction exists for the final period, create one
                    if not existing_final_period_txn and not overlapping_txn and final_period_start < customer.icl_end_date:
                        # Calculate balance before the final period
                        final_period_txns = Transaction.query.filter(
                            Transaction.customer_id == customer_id,
                            Transaction.date < final_period_start
                        ).order_by(Transaction.date.asc(), Transaction.created_at.asc()).all()
                        
                        balance_before_final_period = Decimal('0')
                        for txn in final_period_txns:
                            balance_before_final_period += txn.get_safe_amount_paid() - txn.get_safe_amount_repaid()
                            # For compound interest, add net interest at period ends
                            if (customer.interest_type == 'compound' and 
                                txn.period_to and 
                                _is_period_end(txn.period_to, customer.icl_start_date, frequency_to_use) and 
                                txn.get_safe_net_amount()):
                                balance_before_final_period += txn.get_safe_net_amount()
                        
                        # Calculate accumulated net interest from previous periods
                        accumulated_net_interest = Decimal('0')
                        repayment_adjustment = Decimal('0')
                        previous_period_transactions = Transaction.query.filter(
                            Transaction.customer_id == customer_id,
                            Transaction.date < final_period_start
                        ).order_by(Transaction.date.asc(), Transaction.id.asc()).all()
                        
                        for prev_txn in previous_period_transactions:
                            accumulated_net_interest += prev_txn.get_safe_net_amount()
                            if customer.interest_type == 'compound' and prev_txn.transaction_type == 'repayment':
                                repayment_adjustment += prev_txn.get_safe_net_amount()
                        
                        # For simple interest, only use principal movements for final period calculation
                        if customer.interest_type == 'simple':
                            principal_for_final_period = balance_before_final_period
                        else:
                            # For compound interest, include accumulated interest and adjustments
                            principal_for_final_period = balance_before_final_period + accumulated_net_interest - repayment_adjustment
                        
                        # Calculate days for final period (from period start to ICL end date)
                        final_period_days = (customer.icl_end_date - final_period_start).days + 1
                        
                        if final_period_days > 0 and principal_for_final_period > Decimal('0'):
                            # Double-check that no passive transaction exists for this final period
                            existing_final_period_txn_check = Transaction.query.filter(
                                Transaction.customer_id == customer_id,
                                Transaction.period_from == final_period_start,
                                Transaction.period_to == customer.icl_end_date,
                                Transaction.transaction_type == 'passive'
                            ).first()
                            
                            if not existing_final_period_txn_check:
                                # Calculate interest for final period
                                final_period_int_amount = calculate_interest(principal_for_final_period, customer.annual_rate, final_period_days)
                                
                                # Calculate TDS for final period
                                final_period_tds_amount = Decimal('0')
                                if customer.tds_applicable and final_period_int_amount:
                                    tds_rate_to_use = customer.tds_percentage or Decimal('10.00')
                                    final_period_tds_amount = final_period_int_amount * (tds_rate_to_use / Decimal('100'))
                                
                                final_period_net_amount = final_period_int_amount - final_period_tds_amount
                                
                                # Calculate balance for final period (before repayment)
                                if customer.interest_type == 'simple':
                                    # For simple interest, don't add interest to balance
                                    final_period_balance = balance_before_final_period
                                else:
                                    # For compound interest, add net interest to balance
                                    final_period_balance = balance_before_final_period + final_period_net_amount
                                
                                # Create final period transaction (before the repayment)
                                final_period_date = final_period_start + timedelta(days=final_period_days // 2)
                                
                                final_period_transaction = Transaction(
                                    customer_id=customer_id,
                                    date=final_period_date,
                                    amount_paid=None,
                                    amount_repaid=None,
                                    balance=final_period_balance,
                                    period_from=final_period_start,
                                    period_to=customer.icl_end_date,
                                    no_of_days=final_period_days,
                                    int_rate=customer.annual_rate,
                                    int_amount=final_period_int_amount,
                                    tds_amount=final_period_tds_amount,
                                    net_amount=final_period_net_amount,
                                    transaction_type='passive',
                                    created_by=current_user.id
                                )
                                
                                db.session.add(final_period_transaction)
                                db.session.flush()  # Ensure the transaction is available
                                
                                logging.debug(f"Created final period transaction for {customer.interest_type} interest customer: {final_period_start} to {customer.icl_end_date}, interest: {final_period_int_amount}")
                            else:
                                logging.debug(f"Final period passive transaction already exists for period {final_period_start} to {customer.icl_end_date}, skipping creation")
                        else:
                            logging.debug(f"Final period conditions not met: days={final_period_days}, principal={principal_for_final_period}")
                    else:
                        logging.debug(f"Final period already covered by existing transactions: existing={existing_final_period_txn is not None}, overlapping={overlapping_txn is not None}")
                
                            # NOW RECALCULATE THE CURRENT BALANCE INCLUDING THE FINAL QUARTER TRANSACTION
                # This is crucial for the repayment transaction's interest calculation
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
                            
                            # Apply repayment adjustment for compound interest customers only (excluding ICL end date period)
                if customer.interest_type == 'compound':
                    repayment_periods = set()
                    frequency_for_adjustment = customer.compound_frequency if customer.compound_frequency else 'quarterly'
                    icl_end_period_start = _get_period_start_date(customer.icl_end_date, customer.icl_start_date, frequency_for_adjustment)
                    
                    for t in previous_txns + same_day_txns:
                        if t.transaction_type == 'repayment' and t.period_to:
                            period_start = _get_period_start_date(t.date, customer.icl_start_date, frequency_for_adjustment)
                            if period_start != icl_end_period_start:
                                repayment_periods.add(period_start)
                    
                    # Subtract net amounts from repayment transactions in repayment periods
                    total_repayment_net_amount = Decimal('0')
                    for t in previous_txns + same_day_txns:
                        if t.transaction_type == 'repayment':
                            txn_period_start = _get_period_start_date(t.date, customer.icl_start_date, frequency_for_adjustment)
                            if txn_period_start in repayment_periods:
                                total_repayment_net_amount += t.get_safe_net_amount()
                    
                    if total_repayment_net_amount > Decimal('0'):
                        current_balance_before_this_txn -= total_repayment_net_amount
                
                # Update the balance for interest calculation - this is the correct balance before repayment
                new_balance = current_balance_before_this_txn - amount_repaid
                            
                            # CRITICAL FIX: For ICL end date repayments, recalculate interest using correct principal
                # The interest should be calculated on the principal BEFORE repayment, not after
                if amount_repaid > Decimal('0'):
                    # Recalculate interest for the final period using principal before repayment
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
                        repayment_adjustment = Decimal('0')
                        for prev_txn in previous_period_transactions:
                            accumulated_net_interest += prev_txn.get_safe_net_amount()
                            if prev_txn.transaction_type == 'repayment':
                                repayment_adjustment += prev_txn.get_safe_net_amount()
                        
                        principal_for_final_interest = current_balance_before_this_txn + accumulated_net_interest - repayment_adjustment
                    else:
                        # For simple interest, only use the current balance before repayment
                        principal_for_final_interest = current_balance_before_this_txn
                    
                    # Recalculate interest and TDS for the current transaction using correct principal
                    if period_from and period_to and no_of_days and no_of_days > 0:
                        int_amount = calculate_interest(principal_for_final_interest, customer.annual_rate, no_of_days)
                        
                        # Recalculate TDS
                        if customer.tds_applicable and int_amount:
                            tds_rate_to_use = customer.tds_percentage or Decimal('10.00')
                            tds_amount = int_amount * (tds_rate_to_use / Decimal('100'))
                            net_amount = int_amount - tds_amount
                        else:
                            tds_amount = Decimal('0')
                            net_amount = int_amount
                        
                        # Update the transaction with recalculated values
                        transaction.int_amount = int_amount
                        transaction.tds_amount = tds_amount
                        transaction.net_amount = net_amount
                        
                        logging.debug(f"ICL end date repayment: Recalculated interest {int_amount}, TDS {tds_amount}, net {net_amount} using principal {principal_for_final_interest}")
                
                # Set the final balance after repayment to zero (loan closure)
                transaction.balance = Decimal('0')
                
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

                flash('Loan fully repaid and closed successfully!', 'success')
            else:
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

        # For compound interest customers only, apply repayment adjustments
        # BUT exclude ICL end date quarter from adjustment
        if customer.interest_type == 'compound':
            # Find quarters that contain repayment transactions
            repayment_quarters = set()
            icl_end_quarter_start = None

            # Identify ICL end date quarter if ICL end date exists
            if customer.icl_end_date:
                icl_end_quarter_start = _get_quarter_start_date(customer.icl_end_date, customer.icl_start_date)
                logging.debug(f"  ICL end date quarter starts: {icl_end_quarter_start}")

            for t in transactions:
                if t.transaction_type == 'repayment' and t.period_to:
                    # Get the quarter start for this repayment transaction
                    quarter_start = _get_quarter_start_date(t.date, customer.icl_start_date)

                    # Only add to repayment quarters if it's NOT the ICL end date quarter
                    if icl_end_quarter_start is None or quarter_start != icl_end_quarter_start:
                        repayment_quarters.add(quarter_start)
                        logging.debug(f"  Added repayment quarter: {quarter_start} (not ICL end quarter)")
                    else:
                        logging.debug(f"  Skipping repayment adjustment for ICL end date quarter: {quarter_start}")

            # Apply adjustment for repayment transactions in repayment quarters (excluding ICL end quarter)
            total_repayment_net_amount = Decimal('0')
            for t in transactions:
                if t.transaction_type == 'repayment':
                    # Check if this transaction's quarter has been identified as a repayment quarter
                    txn_quarter_start = _get_quarter_start_date(t.date, customer.icl_start_date)
                    if txn_quarter_start in repayment_quarters:
                        repayment_net_amount = t.get_safe_net_amount()
                        total_repayment_net_amount += repayment_net_amount
                        logging.debug(f"  Found repayment transaction {t.id} with net amount: {repayment_net_amount} in repayment quarter")

            # Subtract repayment net amounts from balance for compound interest customers
            if total_repayment_net_amount > Decimal('0'):
                current_running_balance -= total_repayment_net_amount
                logging.debug(f"  Compound interest - Adjusted balance after repayment adjustment: {current_running_balance}")

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
            repayment_adjustment = Decimal('0')
            for prev_txn in previous_period_transactions:
                accumulated_net_interest_from_previous_periods += prev_txn.get_safe_net_amount()
                if prev_txn.transaction_type == 'repayment':
                    repayment_adjustment += prev_txn.get_safe_net_amount()

            principal_for_calculation = total_principal_movements + accumulated_net_interest_from_previous_periods - repayment_adjustment
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

        # After deletion, recalculate all transactions from the deleted transaction's date onwards.
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

                # Calculate adjustment for repayment transactions in previous quarters
                # IMPORTANT: For ICL end date transactions, do NOT exclude the ICL end quarter from repayment adjustments
                repayment_adjustment = Decimal('0')
                icl_end_quarter_start = None
                if customer.icl_end_date:
                    icl_end_quarter_start = _get_quarter_start_date(customer.icl_end_date, customer.icl_start_date)

                for prev_txn in previous_quarter_transactions:
                    if prev_txn.transaction_type == 'repayment':
                        # For recalculation, apply standard repayment adjustment logic
                        # The exclusion of ICL end quarter is handled in balance calculation, not here
                        repayment_adjustment += prev_txn.get_safe_net_amount()

                # Add accumulated interest from previous quarters and subtract repayment adjustments
                if transaction.get_safe_amount_paid() > Decimal('0'):
                    principal_for_interest_calculation = current_running_balance + accumulated_net_interest_from_previous_quarters - repayment_adjustment + transaction.get_safe_amount_paid()
                elif transaction.get_safe_amount_repaid() > Decimal('0'):
                    # For repayment transactions, especially ICL end date, use principal BEFORE repayment
                    principal_for_interest_calculation = current_running_balance + accumulated_net_interest_from_previous_quarters - repayment_adjustment
                    logging.debug(f"  Repayment transaction - Using principal BEFORE repayment: {principal_for_interest_calculation}")
                else:
                    principal_for_interest_calculation = current_running_balance + accumulated_net_interest_from_previous_quarters - repayment_adjustment

                logging.debug(f"  Compound Interest - Added accumulated net interest from previous quarters {accumulated_net_interest_from_previous_quarters}, repayment adjustment: {repayment_adjustment}, final principal: {principal_for_interest_calculation}")

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

            # For compound interest, add net interest to balance only at quarter end
            # CRITICAL: Do NOT add interest to balance during mid-quarter periods
            if (customer.interest_type == 'compound' and 
                customer.first_compounding_date and 
                transaction.date >= customer.first_compounding_date and 
                transaction.period_to and 
                _is_quarter_end(transaction.period_to, customer.icl_start_date) and 
                transaction.net_amount):
                new_transaction_balance += transaction.net_amount
                # Update running balance to include interest for next transaction
                current_running_balance += transaction.net_amount
                logging.debug(f"Quarter end: added net interest {transaction.net_amount} to balance")
            else:
                logging.debug(f"Mid-quarter recalc: interest {transaction.net_amount} calculated but NOT added to principal balance")

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

def _get_period_start_date(transaction_date, icl_start_date, frequency='quarterly'):
    """
    Calculate the period start date based on transaction date, ICL start date, and frequency.
    """
    if not transaction_date or not icl_start_date:
        return transaction_date

    if frequency == 'monthly':
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

    elif frequency == 'yearly':
        # Calculate years from ICL start to transaction date
        years_from_start = transaction_date.year - icl_start_date.year
        if transaction_date.month < icl_start_date.month or (transaction_date.month == icl_start_date.month and transaction_date.day < icl_start_date.day):
            years_from_start -= 1

        target_year = icl_start_date.year + years_from_start
        target_month = icl_start_date.month
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

    if frequency == 'monthly':
        # Get the period start
        period_start = _get_period_start_date(transaction_date, icl_start_date, 'monthly')

        # Calculate next month
        if period_start.month == 12:
            next_month_start = date(period_start.year + 1, 1, period_start.day)
        else:
            next_month_day = min(period_start.day, _get_last_day_of_month(period_start.year, period_start.month + 1))
            next_month_start = date(period_start.year, period_start.month + 1, next_month_day)

        return next_month_start - timedelta(days=1)

    elif frequency == 'yearly':
        # Get the period start
        period_start = _get_period_start_date(transaction_date, icl_start_date, 'yearly')

        # Calculate next year
        next_year_day = min(period_start.day, _get_last_day_of_month(period_start.year + 1, period_start.month))
        next_year_start = date(period_start.year + 1, period_start.month, next_year_day)

        return next_year_start - timedelta(days=1)

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

def _is_period_end(date_to_check, icl_start_date, frequency='quarterly'):
    """
    Check if a given date falls at the end of a financial period, based on the customer's ICL start date and frequency.
    """
    if not date_to_check or not icl_start_date:
        return False

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
    Function to identify missing quarters only between existing transactions.
    This ensures no gaps exist between actual transactions, but does not extend beyond the last transaction.
    Returns a list of (start_date, end_date) tuples for missing periods.
    """
    missing_periods = []

    if not customer.icl_start_date or not transaction_date:
        return missing_periods

    # Get all existing transactions for this customer, sorted by date
    existing_transactions = Transaction.query.filter_by(customer_id=customer_id).order_by(Transaction.date.asc(), Transaction.created_at.asc()).all()

    # Create a set of all quarters that should have transactions
    covered_quarters = set()

    # Add quarters covered by existing transactions
    for txn in existing_transactions:
        if txn.period_from and txn.period_to:
            quarter_start = _get_quarter_start_date(txn.date, customer.icl_start_date)
            covered_quarters.add(quarter_start)

    # Add the quarter for the current transaction being added
    current_quarter_start = _get_quarter_start_date(transaction_date, customer.icl_start_date)
    covered_quarters.add(current_quarter_start)

    # Only generate quarters between ICL start and current transaction date
    # Do NOT extend to ICL end date
    expected_quarters = []
    current_period_start = customer.icl_start_date

    # Use only the transaction date as the end boundary, not ICL end date
    end_boundary = transaction_date

    while current_period_start <= end_boundary:
        quarter_start = _get_quarter_start_date(current_period_start, customer.icl_start_date)
        quarter_end = _get_quarter_end_date(current_period_start, customer.icl_start_date)

        # Only add if quarter start is not beyond the transaction date
        if quarter_start <= end_boundary:
            expected_quarters.append((quarter_start, quarter_end))

        # Move to next quarter (add 3 months)
        if current_period_start.month <= 9:
            current_period_start = current_period_start.replace(month=current_period_start.month + 3)
        else:
            # Handle year transition
            new_month = current_period_start.month + 3 - 12
            current_period_start = current_period_start.replace(year=current_period_start.year + 1, month=new_month)

    # Find missing quarters only between actual transactions
    for quarter_start, quarter_end in expected_quarters:
        if quarter_start not in covered_quarters:
            # Verify this quarter doesn't already have a transaction
            existing_in_quarter = Transaction.query.filter(
                Transaction.customer_id == customer_id,
                Transaction.period_from == quarter_start,
                Transaction.period_to == quarter_end
            ).first()

            if not existing_in_quarter:
                # Double-check by also looking for any transaction that covers this period
                overlapping_txn = Transaction.query.filter(
                    Transaction.customer_id == customer_id,
                    Transaction.period_from <= quarter_end,
                    Transaction.period_to >= quarter_start
                ).first()
                
                if not overlapping_txn:
                    missing_periods.append((quarter_start, quarter_end))
                    logging.debug(f"Found missing quarter: {quarter_start} to {quarter_end}")
                else:
                    logging.debug(f"Found overlapping transaction for period {quarter_start} to {quarter_end}, skipping")

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

    # Calculate the period in the middle of the quarter for the transaction date
    period_middle = period_start + timedelta(days=(period_end - period_start).days // 2)

    # Calculate balance before this passive period
    previous_txns = Transaction.query.filter(
        Transaction.customer_id == customer_id,
        Transaction.date < period_middle
    ).order_by(Transaction.date.asc(), Transaction.created_at.asc()).all()

    current_balance_before_passive = Decimal('0')
    for txn in previous_txns:
        current_balance_before_passive += txn.get_safe_amount_paid() - txn.get_safe_amount_repaid()
        # For compound interest, add net interest at quarter ends
        if (customer.interest_type == 'compound' and 
            customer.first_compounding_date and 
            txn.date >= customer.first_compounding_date and 
            txn.period_to and 
            _is_quarter_end(txn.period_to, customer.icl_start_date) and 
            txn.get_safe_net_amount()):
            current_balance_before_passive += txn.get_safe_net_amount()

    # Calculate days for this passive period
    no_of_days = (period_end - period_start).days + 1

    # Calculate interest for this passive period
    principal_for_calculation = current_balance_before_passive

    # For compound interest, include accumulated net interest from previous quarters only
    if (customer.interest_type == 'compound' and 
        customer.first_compounding_date and 
        period_middle >= customer.first_compounding_date):

        # Get accumulated net interest from transactions before this quarter starts
        previous_quarter_transactions = Transaction.query.filter(
            Transaction.customer_id == customer_id,
            Transaction.date < period_start
        ).order_by(Transaction.date.asc(), Transaction.id.asc()).all()

        accumulated_net_interest_from_previous_quarters = Decimal('0')
        repayment_adjustment = Decimal('0')
        for prev_txn in previous_quarter_transactions:
            accumulated_net_interest_from_previous_quarters += prev_txn.get_safe_net_amount()
            if prev_txn.transaction_type == 'repayment':
                repayment_adjustment += prev_txn.get_safe_net_amount()

        principal_for_calculation = current_balance_before_passive + accumulated_net_interest_from_previous_quarters - repayment_adjustment

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

    # For compound interest, add net interest to balance at quarter end
    if (customer.interest_type == 'compound' and 
        customer.first_compounding_date and 
        period_middle >= customer.first_compounding_date and 
        _is_quarter_end(period_end, customer.icl_start_date) and 
        net_amount):
        new_balance += net_amount
        logging.debug(f"Passive quarter end: adding net interest {net_amount} to balance")

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

        # For quarterly periods and compound interest customers only, subtract net amounts from repayment transactions within the quarter
        adjusted_closing_balance = closing_balance_for_period
        if period_type == 'quarterly' and customer.interest_type == 'compound':
            # Search database for repayment transactions in this quarter period
            repayment_transactions_in_quarter = Transaction.query.filter(
                Transaction.customer_id == customer.id,
                Transaction.transaction_type == 'repayment',
                Transaction.date >= actual_period_start,
                Transaction.date <= period_end
            ).all()

            # Only apply adjustment if there are repayment transactions in this quarter
            if repayment_transactions_in_quarter:
                # Subtract net amounts of repayment transactions from closing balance
                total_repayment_net_amount = Decimal('0')
                for repayment_txn in repayment_transactions_in_quarter:
                    repayment_net_amount = repayment_txn.get_safe_net_amount()
                    total_repayment_net_amount += repayment_net_amount
                    logging.debug(f"  Database search found repayment transaction {repayment_txn.id} on {repayment_txn.date} with net amount: {repayment_net_amount}")

                if total_repayment_net_amount > Decimal('0'):
                    adjusted_closing_balance = closing_balance_for_period - total_repayment_net_amount
                    logging.debug(f"  Compound interest customer - Adjusted closing balance: {closing_balance_for_period} - {total_repayment_net_amount} = {adjusted_closing_balance}")
                else:
                    logging.debug(f"  Compound interest customer - No repayment net amounts to subtract in quarter {period_name}")
            else:
                logging.debug(f"  Compound interest customer - No repayment transactions found in quarter {period_name}, no adjustment needed")
        elif period_type == 'quarterly' and customer.interest_type != 'compound':
            logging.debug(f"  Simple interest customer - No repayment adjustment applied for quarter {period_name}")

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
                'adjusted_closing_balance': adjusted_closing_balance.quantize(Decimal('0.01')) if (period_type == 'quarterly' and customer.interest_type == 'compound') else closing_balance_for_period.quantize(Decimal('0.01'))
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
