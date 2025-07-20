import io
import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from openpyxl import Workbook
from openpyxl.styles import Font, Border, Side, Alignment, PatternFill
from openpyxl.utils import get_column_letter # <--- Added this import
from sqlalchemy import and_
# Configure logging for utils.py
logging.basicConfig(level=logging.DEBUG)

def compute_cumulative_principal(transactions, new_paid=Decimal('0'), new_repaid=Decimal('0')):
    """
    Calculates cumulative principal for the next compounding period, including all prior net interest.
    - transactions: list of Transaction objects, sorted by date, each must have .get_safe_amount_paid(), .get_safe_amount_repaid(), and .get_safe_net_amount()
    - new_paid: Decimal, amount_paid for the new transaction (if any, else 0)
    - new_repaid: Decimal, amount_repaid for the new transaction (if any, else 0)
    Returns: Decimal, principal to use for interest calculation
    """
    cumulative = Decimal('0')
    for txn in transactions:
        cumulative += txn.get_safe_amount_paid()
        cumulative -= txn.get_safe_amount_repaid()
        cumulative += txn.get_safe_net_amount()  # Net interest is compounded
    cumulative += new_paid
    cumulative -= new_repaid
    return cumulative
def safe_decimal_conversion(value, default=Decimal('0')):
    """Safely convert values to Decimal, handling None and invalid inputs"""
    if value is None or value == '':
