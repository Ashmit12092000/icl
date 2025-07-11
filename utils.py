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

def safe_decimal_conversion(value, default=Decimal('0')):
    """Safely convert values to Decimal, handling None and invalid inputs"""
    if value is None or value == '':
        return default
    try:
        return Decimal(str(value))
    except (ValueError, TypeError, InvalidOperation):
        logging.warning(f"Failed to convert '{value}' to Decimal. Using default '{default}'.")
        return default

def calculate_interest(principal, annual_rate, days):
    """Calculate simple interest for given principal, rate and days - Fixed NaN issues"""
    try:
        # Convert inputs to Decimal safely
        principal = safe_decimal_conversion(principal)
        annual_rate = safe_decimal_conversion(annual_rate)
        days = safe_decimal_conversion(days)
        
        if principal <= 0 or annual_rate <= 0 or days <= 0:
            return Decimal('0')
        
        # Simple interest formula: (P * R * T) / 100
        # Where T is in years (days/365)
        interest = (principal * annual_rate * days) / (Decimal('100') * Decimal('365'))
        return interest.quantize(Decimal('0.01'))
        
    except Exception as e:
        logging.error(f"Error calculating simple interest: {e}")
        return Decimal('0')

def calculate_compound_interest(principal, annual_rate, days, frequency):
    """Calculate compound interest for given principal, rate, days and frequency - Fixed NaN issues"""
    try:
        # Convert inputs to Decimal safely
        principal = safe_decimal_conversion(principal)
        annual_rate = safe_decimal_conversion(annual_rate)
        days = safe_decimal_conversion(days)
        
        if principal <= 0 or annual_rate <= 0 or days <= 0 or not frequency:
            return Decimal('0')
        
        # Convert frequency to compounding periods per year
        frequency_map = {
            'monthly': 12,
            'quarterly': 4,
            'yearly': 1
        }
        
        n = frequency_map.get(frequency.lower(), 1)
        
        # Convert days to years
        t = days / Decimal('365')
        
        # Compound interest formula: P * (1 + r/n)^(nt) - P
        r = annual_rate / Decimal('100')
        n_decimal = Decimal(str(n))
        
        # Calculate compound amount using power function
        base = Decimal('1') + (r / n_decimal)
        exponent = float(n_decimal * t)  # Convert to float for power calculation
        
        # Handle very small exponents
        if exponent == 0:
            return Decimal('0')
        
        try:
            amount = principal * (Decimal(str(float(base) ** exponent)))
            compound_interest = amount - principal
            return compound_interest.quantize(Decimal('0.01'))
        except (OverflowError, ValueError):
            # Fallback to simple interest for extreme values
            logging.warning(f"Overflow/ValueError in compound interest for principal={principal}, rate={annual_rate}, days={days}, freq={frequency}. Falling back to simple interest.")
            return calculate_interest(principal, annual_rate, days)
            
    except Exception as e:
        logging.error(f"Error calculating compound interest: {e}")
        return Decimal('0')

def export_to_excel(customer, transactions):
    """Export customer data and transactions to Excel - Fixed NaN display issues"""
    output = io.BytesIO()
    
    try:
        logging.debug(f"Starting Excel export for customer: {customer.name} (ID: {customer.id})")
        logging.debug(f"Number of transactions to export: {len(transactions)}")
        if not transactions:
            logging.info(f"No transactions found for customer {customer.id}. The transaction section will be empty.")

        # Create workbook and worksheet
        wb = Workbook()
        ws = wb.active
        ws.title = f"Customer Report - {customer.icl_no}"
        
        # Define styles
        header_font = Font(bold=True, size=12)
        title_font = Font(bold=True, size=14)
        border = Border(left=Side(style='thin'), right=Side(style='thin'),
                        top=Side(style='thin'), bottom=Side(style='thin'))
        
        # Currency and Percentage formats for openpyxl
        currency_format = '₹#,##0.00'
        percentage_format = '0.00%'
        date_format = 'DD-MM-YYYY' # For display in Excel

        # Customer Information Header
        ws['A1'] = 'Customer Master Report'
        ws['A1'].font = title_font
        ws.merge_cells('A1:K1')
        
        # Customer Details
        row = 3
        # Store raw values for cells that need number formatting
        customer_details_data = [
            ('ICL No:', customer.icl_no),
            ('Customer Name:', customer.name),
            ('Address:', customer.address or ''),
            ('Contact Details:', customer.contact_details or ''),
            ('Annual Rate:', customer.get_safe_annual_rate()/ 100), # Pass raw Decimal
            ('Interest Type:', customer.interest_type.title()),
            ('TDS Applicable:', 'Yes' if customer.tds_applicable else 'No'),
            ('TDS Percentage:', customer.get_safe_tds_percentage()/100),
            ('Current Balance:', customer.get_current_balance()) # Pass raw Decimal
        ]
        
        for label, value in customer_details_data:
            ws[f'A{row}'] = label
            cell_b = ws[f'B{row}']
            cell_b.value = value
            ws[f'A{row}'].font = header_font
            
            if label == 'Annual Rate:':
                cell_b.number_format = percentage_format
            elif label == 'Current Balance:':
                cell_b.number_format = currency_format
            elif label == 'TDS Percentage:': # NEW
                cell_b.number_format = percentage_format
            row += 1
        
        # Transaction Headers
        row += 2
        headers = ['Date', 'Amount Paid', 'Amount Repaid', 'Balance', 'Period From', 'Period To',
                   'No of Days', 'Int Rate', 'Int Amount', 'TDS', 'Net Amount']
        
        for col, header in enumerate(headers, 1):
            cell = ws.cell(row=row, column=col, value=header)
            cell.font = header_font
            cell.border = border
            cell.alignment = Alignment(horizontal='center')
        
        # Transaction Data
        total_int_amount = Decimal('0')
        total_tds = Decimal('0')
        total_net = Decimal('0')
        total_days = 0
        
        for transaction in transactions:
            row += 1
            
            # Prepare raw data for cells, let openpyxl handle formatting
            data = [
                transaction.date.strftime('%Y-%m-%d') if transaction.date else '', # Date as string for direct display
                transaction.get_safe_amount_paid(),
                transaction.get_safe_amount_repaid(),
                transaction.get_safe_balance(),
                transaction.period_from.strftime('%Y-%m-%d') if transaction.period_from else '',
                transaction.period_to.strftime('%Y-%m-%d') if transaction.period_to else '',
                transaction.get_safe_no_of_days(),
                transaction.get_safe_int_rate()/100,
                transaction.get_safe_int_amount() ,
                transaction.get_safe_tds_amount(),
                transaction.get_safe_net_amount()
            ]
            
            for col, value in enumerate(data, 1):
                cell = ws.cell(row=row, column=col, value=value)
                cell.border = border
                
                # Apply number formats to numeric columns
                if col in [2, 3, 4, 9, 10, 11]: # Amount Paid, Amount Repaid, Balance, Int Amount, TDS, Net Amount
                    cell.number_format = currency_format
                elif col == 8: # Interest Rate
                    cell.number_format = percentage_format
                # Date columns (1, 5, 6) are already strings formatted for display

                # Align numbers to right (if they are numbers)
                if isinstance(value, (Decimal, int, float)):
                    cell.alignment = Alignment(horizontal='right')
                elif col in [1,5,6] and value: # Dates which are strings
                    cell.alignment = Alignment(horizontal='center')
                else: # Default alignment for other text
                    cell.alignment = Alignment(horizontal='left')
            
            # Add to totals (with safe decimal handling)
            total_int_amount += safe_decimal_conversion(transaction.int_amount)

            total_tds += safe_decimal_conversion(transaction.tds_amount)
            total_net += safe_decimal_conversion(transaction.net_amount)
            total_days += transaction.get_safe_no_of_days()
        
        # Totals row
        row += 1
        ws[f'A{row}'] = 'Total'
        ws[f'A{row}'].font = header_font
        ws[f'G{row}'] = total_days # No of Days total
        ws[f'I{row}'] = total_int_amount
        ws[f'J{row}'] = total_tds
        ws[f'K{row}'] = total_net
        
        # Apply borders and formatting to totals
        for col_idx in range(1, 12): # Iterate through relevant columns for totals
            cell = ws.cell(row=row, column=col_idx)
            cell.border = border
            cell.font = header_font
            if col_idx in [9, 10, 11]: # Int Amount, TDS, Net Amount
                cell.number_format = currency_format
                cell.alignment = Alignment(horizontal='right')
            elif col_idx == 7: # No of Days total
                cell.alignment = Alignment(horizontal='right')
            elif col_idx == 1: # 'Total' label
                cell.alignment = Alignment(horizontal='left')


        # Auto-adjust column widths
        for col_idx in range(1, ws.max_column + 1):
            max_length = 0
            column_letter = get_column_letter(col_idx)
            for cell in ws[column_letter]:
                try:
                    # Use the formatted value if number_format is set, otherwise string value
                    if cell.number_format and isinstance(cell.value, (Decimal, float, int)):
                        # Estimate length based on common formats
                        if cell.number_format == currency_format:
                            length = len(f"₹{cell.value:,.2f}")
                        elif cell.number_format == percentage_format:
                            length = len(f"{cell.value:.2f}%")
                        else:
                            length = len(str(cell.value))
                    elif isinstance(cell.value, datetime) or isinstance(cell.value, date):
                        length = len(cell.value.strftime(date_format))
                    else:
                        length = len(str(cell.value))
                    max_length = max(max_length, length)
                except Exception as e:
                    logging.warning(f"Error calculating column width for cell {cell.coordinate}: {e}")
                    pass # Continue if there's an error with a specific cell
            adjusted_width = min(max_length + 2, 40) # Max width to prevent overly wide columns
            ws.column_dimensions[column_letter].width = adjusted_width
        
        wb.save(output)
        output.seek(0)
        logging.debug("Excel report generated and saved to BytesIO successfully.")
        return output
        
    except Exception as e:
        logging.error(f"Critical Error exporting to Excel: {e}", exc_info=True) # Log full traceback
        # Return empty workbook if error
        wb = Workbook()
        wb.save(output)
        output.seek(0)
        return output
def get_period_report(start_date, end_date):
    """Generate period-based report for all customers - Fixed SQLAlchemy import"""
    output = io.BytesIO()
    
    try:
        # Import here to avoid circular imports
        from models import Transaction, Customer
        
        logging.debug(f"get_period_report called with start_date: {start_date} (type: {type(start_date)}) and end_date: {end_date} (type: {type(end_date)})")
        
        # Get all transactions in the period
        # Using and_() for explicit clarity in filter conditions
        transactions = Transaction.query.filter(
            and_(Transaction.date >= start_date,
                 Transaction.date <= end_date)
        ).order_by(Transaction.date).all()
        
        logging.debug(f"Number of transactions fetched for period report: {len(transactions)}")
        if transactions:
            for txn in transactions:
                logging.debug(f"  Fetched transaction ID: {txn.id}, Date: {txn.date}, Customer ID: {txn.customer_id}")
        else:
            logging.info(f"No transactions found for period {start_date} to {end_date}.")

        if not transactions:
            logging.info(f"No transactions found for period {start_date} to {end_date}. Generating an empty report with headers.")
            # If no transactions, still create a basic workbook with headers
            wb = Workbook()
            ws = wb.active
            ws.title = f"Period Report {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"
            ws['A1'] = f'Period Report: {start_date.strftime("%d-%m-%Y")} to {end_date.strftime("%d-%m-%Y")}'
            ws['A1'].font = Font(bold=True, size=14)
            ws.merge_cells('A1:M1')
            ws.append([]) # Blank row
            headers = ['Customer ICL', 'Customer Name', 'Date', 'Amount Paid', 'Amount Repaid',
                       'Balance', 'Period From', 'Period To', 'No of Days', 'Int Rate', 'Int Amount', 'TDS', 'Net Amount']
            for col, header in enumerate(headers, 1):
                cell = ws.cell(row=ws.max_row + 1, column=col, value=header)
                cell.font = Font(bold=True, size=12)
                cell.border = Border(left=Side(style='thin'), right=Side(style='thin'),
                                    top=Side(style='thin'), bottom=Side(style='thin'))
                cell.alignment = Alignment(horizontal='center')
            
            wb.save(output)
            output.seek(0)
            return output

        # Create workbook
        wb = Workbook()
        ws = wb.active
        ws.title = f"Period Report {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"
        
        # Define styles
        header_font = Font(bold=True, size=12)
        title_font = Font(bold=True, size=14)
        border = Border(left=Side(style='thin'), right=Side(style='thin'),
                        top=Side(style='thin'), bottom=Side(style='thin'))
        currency_format = '₹#,##0.00'
        percentage_format = '0.00%'
        date_format = 'DD-MM-YYYY'
        
        # Title
        ws['A1'] = f'Period Report: {start_date.strftime("%d-%m-%Y")} to {end_date.strftime("%d-%m-%Y")}'
        ws['A1'].font = title_font
        ws.merge_cells('A1:M1') # Adjusted merge range for new headers
        
        # Headers
        row = 3
        headers = ['Customer ICL', 'Customer Name', 'Date', 'Amount Paid', 'Amount Repaid',
                   'Balance', 'Period From', 'Period To', 'No of Days', 'Int Rate', 'Int Amount', 'TDS', 'Net Amount']
        
        for col, header in enumerate(headers, 1):
            cell = ws.cell(row=row, column=col, value=header)
            cell.font = header_font
            cell.border = border
            cell.alignment = Alignment(horizontal='center')
        
        # Data
        total_int_amount = Decimal('0')
        total_tds = Decimal('0')
        total_net = Decimal('0')
        
        for transaction in transactions:
            row += 1
            
            # Customer details
            ws.cell(row=row, column=1, value=transaction.customer.icl_no)
            ws.cell(row=row, column=2, value=transaction.customer.name)
            
            # Transaction date
            date_cell = ws.cell(row=row, column=3, value=transaction.date)
            date_cell.number_format = date_format
            
            # Amount paid
            amount_paid_cell = ws.cell(row=row, column=4, value=transaction.get_safe_amount_paid())
            amount_paid_cell.number_format = currency_format
            
            # Amount repaid
            amount_repaid_cell = ws.cell(row=row, column=5, value=transaction.get_safe_amount_repaid())
            amount_repaid_cell.number_format = currency_format
            
            # Balance
            balance_cell = ws.cell(row=row, column=6, value=transaction.get_safe_balance())
            balance_cell.number_format = currency_format
            
            # Period From
            if transaction.period_from:
                period_from_cell = ws.cell(row=row, column=7, value=transaction.period_from)
                period_from_cell.number_format = date_format
            
            # Period To
            if transaction.period_to:
                period_to_cell = ws.cell(row=row, column=8, value=transaction.period_to)
                period_to_cell.number_format = date_format
            
            # No of Days
            ws.cell(row=row, column=9, value=transaction.get_safe_no_of_days())
            
            # Interest Rate
            rate_cell = ws.cell(row=row, column=10, value=transaction.get_safe_int_rate() / 100)
            rate_cell.number_format = percentage_format
            
            # Interest Amount
            int_amount_cell = ws.cell(row=row, column=11, value=transaction.get_safe_int_amount())
            int_amount_cell.number_format = currency_format
            
            # TDS Amount
            tds_amount_cell = ws.cell(row=row, column=12, value=transaction.get_safe_tds_amount())
            tds_amount_cell.number_format = currency_format
            
            # Net Amount
            net_amount_cell = ws.cell(row=row, column=13, value=transaction.get_safe_net_amount())
            net_amount_cell.number_format = currency_format
            
            # Add to totals
            total_int_amount += transaction.get_safe_int_amount()
            total_tds += transaction.get_safe_tds_amount()
            total_net += transaction.get_safe_net_amount()
            
            # Apply border to all cells
            for col in range(1, 14):
                ws.cell(row=row, column=col).border = border
        
        # Add totals row
        row += 2
        ws.cell(row=row, column=10, value="TOTALS:").font = header_font
        
        total_int_cell = ws.cell(row=row, column=11, value=total_int_amount)
        total_int_cell.number_format = currency_format
        total_int_cell.font = header_font
        
        total_tds_cell = ws.cell(row=row, column=12, value=total_tds)
        total_tds_cell.number_format = currency_format
        total_tds_cell.font = header_font
        
        total_net_cell = ws.cell(row=row, column=13, value=total_net)
        total_net_cell.number_format = currency_format
        total_net_cell.font = header_font
        
        # Apply border to totals row
        for col in range(10, 14):
            ws.cell(row=row, column=col).border = border
        
        # Auto-adjust column widths - simplified to avoid merged cell issues
        from openpyxl.utils import get_column_letter
        column_widths = [15, 20, 12, 15, 15, 15, 12, 12, 10, 12, 15, 15, 15]  # Predefined widths
        
        for col_idx in range(1, min(len(column_widths) + 1, ws.max_column + 1)):
            column_letter = get_column_letter(col_idx)
            ws.column_dimensions[column_letter].width = column_widths[col_idx - 1]
        
        wb.save(output)
        output.seek(0)
        logging.debug("Period report Excel generated successfully.")
        return output
        
    except Exception as e:
        logging.error(f"Critical Error in get_period_report: {e}", exc_info=True)
        # Return empty workbook if error
        wb = Workbook()
        wb.save(output)
        output.seek(0)
        return output
