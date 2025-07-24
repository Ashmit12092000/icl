from app import db
from flask_login import UserMixin
from datetime import datetime, date # Import date as it's used in db.Column(db.Date)
from decimal import Decimal, InvalidOperation
import logging

# Configure logging for models
logging.basicConfig(level=logging.DEBUG)

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256))
    role = db.Column(db.String(20), default='normal_user')  # normal_user, data_entry, admin
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)

    def __repr__(self):
        return f'<User {self.username}>'

class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    icl_no = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    address = db.Column(db.Text)
    contact_details = db.Column(db.String(200))
    annual_rate = db.Column(db.Numeric(5, 2), nullable=False)  # e.g., 15.50
    icl_start_date = db.Column(db.Date, nullable=False)
    icl_end_date = db.Column(db.Date)
    icl_extension = db.Column(db.String(100))
    tds_applicable = db.Column(db.Boolean, default=False)
    tds_percentage = db.Column(db.Numeric(5, 2), default=Decimal('0.00'))
    interest_type = db.Column(db.String(20), default='simple')  # simple, compound
    compound_frequency = db.Column(db.String(20))  # monthly, quarterly, yearly
    first_compounding_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    is_active = db.Column(db.Boolean, default=True)
    loan_closed = db.Column(db.Boolean, default=False)
    loan_closed_date = db.Column(db.Date)
    loan_overdue = db.Column(db.Boolean, default=False)
    loan_overdue_date = db.Column(db.Date)
    loan_extended = db.Column(db.Boolean, default=False)
    original_icl_end_date = db.Column(db.Date)

    # Relationships
    transactions = db.relationship('Transaction', backref='customer', lazy=True, cascade='all, delete-orphan')

    # Removed the redundant 'current_balance' @property to avoid confusion,
    # as get_current_balance() is performing the same role.
    # @property
    # def current_balance(self):
    #     """Calculate current balance based on transactions - Fixed for NaN issues"""
    #     # ... (removed this block)


    def get_current_balance(self):
        """Calculates the current balance for the customer, including accrued net interest."""
        total_principal_paid = Decimal('0')
        total_principal_repaid = Decimal('0')
        total_net_interest_accrued = Decimal('0')

        logging.debug(f"Starting get_current_balance for customer {self.id}. Number of transactions: {len(self.transactions)}")

        for t in self.transactions:
            logging.debug(f"Processing transaction {t.id} for customer {self.id}")

            # Skip loan closure transactions from balance calculation as they represent final state
            if t.transaction_type == 'loan_closure':
                logging.debug(f"  Skipping loan closure transaction {t.id}")
                continue

            safe_paid = t.get_safe_amount_paid()
            logging.debug(f"  get_safe_amount_paid() returned: {safe_paid} (type: {type(safe_paid)})")
            total_principal_paid += safe_paid

            safe_repaid = t.get_safe_amount_repaid()
            logging.debug(f"  get_safe_amount_repaid() returned: {safe_repaid} (type: {type(safe_repaid)})")
            total_principal_repaid += safe_repaid

            # Only add interest/TDS if they were calculated for this transaction
            # Ensure int_amount and tds_amount are not None before attempting subtraction
            if t.int_amount is not None or t.tds_amount is not None:
                safe_int_amount = t.get_safe_int_amount()
                safe_tds_amount = t.get_safe_tds_amount()
                net_interest_for_txn = safe_int_amount - safe_tds_amount
                logging.debug(f"  Net interest for txn {t.id}: {net_interest_for_txn} (type: {type(net_interest_for_txn)})")
                total_net_interest_accrued += net_interest_for_txn

        calculated_balance = (total_principal_paid - total_principal_repaid + total_net_interest_accrued).quantize(Decimal('0.01'))

        # For compound interest customers only, subtract net amounts from repayment transactions after repayment quarters
        # BUT exclude ICL end date quarter from adjustment
        total_repayment_net_amount = Decimal('0')
        if self.interest_type == 'compound':
            # Find periods that contain repayment transactions (based on customer's frequency)
            frequency_to_use = self.compound_frequency if self.compound_frequency else 'quarterly'
            repayment_periods = set()
            icl_end_period_start = None
            
            # Identify ICL end date period if ICL end date exists
            if self.icl_end_date and self.icl_start_date:
                try:
                    from routes import _get_period_start_date
                    icl_end_period_start = _get_period_start_date(self.icl_end_date, self.icl_start_date, frequency_to_use)
                    logging.debug(f"  ICL end date period starts: {icl_end_period_start}")
                except ImportError:
                    icl_end_period_start = None
            
            for t in self.transactions:
                if t.transaction_type == 'repayment' and t.period_to:
                    # Get the period start for this repayment transaction
                    period_start = None
                    if self.icl_start_date:
                        try:
                            from routes import _get_period_start_date
                            period_start = _get_period_start_date(t.date, self.icl_start_date, frequency_to_use)
                            
                            # Only add to repayment periods if it's NOT the ICL end date period
                            if icl_end_period_start is None or period_start != icl_end_period_start:
                                repayment_periods.add(period_start)
                                logging.debug(f"  Added repayment period: {period_start} (not ICL end period)")
                            else:
                                logging.debug(f"  Skipping repayment adjustment for ICL end date period: {period_start}")
                        except ImportError:
                            pass

            # Only apply adjustment for transactions after repayment periods (excluding ICL end period)
            for t in self.transactions:
                if t.transaction_type == 'repayment':
                    # Check if this transaction's period has been identified as a repayment period
                    if self.icl_start_date:
                        try:
                            from routes import _get_period_start_date
                            txn_period_start = _get_period_start_date(t.date, self.icl_start_date, frequency_to_use)
                            if txn_period_start in repayment_periods:
                                repayment_net_amount = t.get_safe_net_amount()
                                total_repayment_net_amount += repayment_net_amount
                                logging.debug(f"  Found repayment transaction {t.id} with net amount: {repayment_net_amount} in repayment {frequency_to_use} period")
                        except ImportError:
                            pass

            # Subtract repayment net amounts from calculated balance for compound interest customers only
            if total_repayment_net_amount > Decimal('0'):
                adjusted_balance = calculated_balance - total_repayment_net_amount
                logging.debug(f"  Compound interest - Adjusted balance: {calculated_balance} - {total_repayment_net_amount} = {adjusted_balance}")
                calculated_balance = adjusted_balance

        logging.debug(f"get_current_balance for customer {self.id}: total_principal_paid={total_principal_paid}, total_principal_repaid={total_principal_repaid}, total_net_interest_accrued={total_net_interest_accrued}, repayment_adjustment={total_repayment_net_amount if self.interest_type == 'compound' else 'N/A'}, final_calculated_balance={calculated_balance}")
        logging.debug(f"FINAL BALANCE RETURNED: {calculated_balance}")
        return calculated_balance



    def _is_quarter_end(self, date_to_check):
        """Check if a given date falls at the end of a financial quarter, based on the customer's ICL start date."""
        if not date_to_check or not self.icl_start_date:
            return False

        # Import here to avoid circular imports
        from routes import _get_quarter_end_date

        # Calculate expected quarter end for this date
        expected_quarter_end = _get_quarter_end_date(date_to_check, self.icl_start_date)

        return date_to_check == expected_quarter_end

    def get_safe_annual_rate(self):
        """Get annual rate as a safe float for display purposes (if needed as float)."""
        if self.annual_rate is None:
            return 0.0
        try:
            return float(self.annual_rate)
        except (ValueError, TypeError, InvalidOperation):
            return 0.0

    def get_safe_tds_percentage(self):
        """Returns tds_percentage safely as a float for display purposes (if needed as float)."""
        if self.tds_percentage is None:
            return 0.0
        try:
            return float(self.tds_percentage)
        except (ValueError, TypeError, InvalidOperation):
            return 0.0

    def get_effective_end_date(self):
        """Get the effective end date (latest of ICL end date or last transaction date)."""
        last_transaction_date = self.get_last_transaction_date()
        if self.icl_end_date and last_transaction_date:
            return max(self.icl_end_date, last_transaction_date)
        elif self.icl_end_date:
            return self.icl_end_date
        elif last_transaction_date:
            return last_transaction_date
        else:
            return None

    def get_last_transaction_date(self):
        """Get the date of the last transaction for this customer."""
        if self.transactions:
            return max(t.date for t in self.transactions)
        return None

    def get_loan_status(self):
        """Get the current loan status"""
        if self.loan_closed:
            return 'closed'
        elif self.loan_overdue:
            return 'overdue'
        elif self.icl_end_date and date.today() > self.icl_end_date and self.get_current_balance() > Decimal('0'):
            return 'past_due'
        else:
            return 'active'

    def is_past_icl_end_date(self):
        """Check if current date is past ICL end date"""
        return self.icl_end_date and date.today() > self.icl_end_date

    def __repr__(self):
        return f'<Customer {self.name}>'

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    amount_paid = db.Column(db.Numeric(15, 2))
    amount_repaid = db.Column(db.Numeric(15, 2))
    balance = db.Column(db.Numeric(15, 2))
    period_from = db.Column(db.Date)
    period_to = db.Column(db.Date)
    no_of_days = db.Column(db.Integer)
    int_rate = db.Column(db.Numeric(5, 2))
    int_amount = db.Column(db.Numeric(15, 2))
    tds_amount = db.Column(db.Numeric(15, 2))
    net_amount = db.Column(db.Numeric(15, 2))
    transaction_type = db.Column(db.String(20), default='passive')  # 'deposit', 'repayment', 'passive'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))

    def __repr__(self):
        return f'<Transaction {self.date} - {self.customer.name if self.customer else "Unknown"}>'

    def _to_decimal(self, value, attribute_name):
        """Helper to convert a value to Decimal, with robust error logging."""
        if value is None:
            logging.debug(f"  _to_decimal: {attribute_name} is None, returning Decimal('0')")
            return Decimal('0')
        try:
            # Convert to string first to handle potential float representation robustly
            decimal_value = Decimal(str(value))
            logging.debug(f"  _to_decimal: {attribute_name} converted {value} (type {type(value)}) to {decimal_value} (type {type(decimal_value)})")
            return decimal_value
        except (ValueError, TypeError, InvalidOperation) as e:
            logging.error(f"  _to_decimal: Error converting {attribute_name} value {value} (type {type(value)}) to Decimal: {e}", exc_info=True)
            return Decimal('0')

    # --- START OF FIX: Ensure all get_safe_ methods return Decimal ---
    def get_safe_amount_paid(self):
        return self._to_decimal(self.amount_paid, 'amount_paid')

    def get_safe_amount_repaid(self):
        return self._to_decimal(self.amount_repaid, 'amount_repaid')

    def get_safe_balance(self):
        return self._to_decimal(self.balance, 'balance')

    def get_safe_no_of_days(self):
        # This one is an integer, so no Decimal conversion needed
        return self.no_of_days if self.no_of_days is not None else 0

    def get_safe_int_rate(self):
        return self._to_decimal(self.int_rate, 'int_rate')

    def get_safe_int_amount(self):
        return self._to_decimal(self.int_amount, 'int_amount')

    def get_safe_tds_amount(self):
        return self._to_decimal(self.tds_amount, 'tds_amount')

    def get_safe_net_amount(self):
        return self._to_decimal(self.net_amount, 'net_amount')
    # --- END OF FIX ---

    def get_transaction_type_display(self):
        """Get formatted transaction type for display"""
        type_mapping = {
            'deposit': 'Deposit',
            'repayment': 'Repayment', 
            'passive': 'Passive Period',
            'loan_closure': 'Loan Closed'
        }
        return type_mapping.get(self.transaction_type, 'Unknown')


class InterestRate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    rate = db.Column(db.Numeric(5, 2), nullable=False)
    effective_date = db.Column(db.Date, nullable=False)
    description = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    is_active = db.Column(db.Boolean, default=True)

    def get_safe_rate(self):
        """Get rate as safe float"""
        try:
            if self.rate is not None:
                return float(self.rate)
            return 0.0
        except (ValueError, TypeError):
            return 0.0

    def __repr__(self):
        return f'<InterestRate {self.rate}% from {self.effective_date}>'

class TDSRate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    rate = db.Column(db.Numeric(5, 2), nullable=False, default=10.0)  # Default 10% TDS
    effective_date = db.Column(db.Date, nullable=False)
    description = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    is_active = db.Column(db.Boolean, default=True)

    def get_safe_rate(self):
        """Get rate as safe float"""
        try:
            if self.rate is not None:
                return float(self.rate)
            return 10.0  # Default TDS rate
        except (ValueError, TypeError):
            return 10.0

    def __repr__(self):
        return f'<TDSRate {self.rate}% from {self.effective_date}>'
