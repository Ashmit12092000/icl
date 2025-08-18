"""
Seed data for IT Stock Management System
Creates initial users, departments, locations, and items for testing and demo purposes
"""

from werkzeug.security import generate_password_hash
from models import (User, UserRole, Department, Location, Item, Employee, 
                   StockBalance, StockEntry, Audit)
from app import db
import logging

logger = logging.getLogger(__name__)

def seed_initial_data():
    """Create initial data for the application"""
    try:
        logger.info("Starting data seeding process...")

        # Create departments first
        departments = create_departments()

        # Create users
        users = create_users(departments)

        # Update departments with HODs
        update_department_hods(departments, users)

        # Create locations
        locations = create_locations()

        # Create items
        items = create_items()

        # Create employees
        create_employees(departments, users)

        # Create initial stock entries
        create_initial_stock(items, locations, users)

        db.session.commit()
        logger.info("Data seeding completed successfully!")

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error during data seeding: {str(e)}")
        raise

def create_departments():
    """Create initial departments"""
    departments_data = [
        {'code': 'IT', 'name': 'Information Technology'},
        {'code': 'HR', 'name': 'Human Resources'},
        {'code': 'FIN', 'name': 'Finance'},
        {'code': 'OPS', 'name': 'Operations'},
        {'code': 'MKT', 'name': 'Marketing'}
    ]

    departments = {}
    for dept_data in departments_data:
        if not Department.query.filter_by(code=dept_data['code']).first():
            dept = Department(
                code=dept_data['code'],
                name=dept_data['name']
            )
            db.session.add(dept)
            departments[dept_data['code']] = dept
            logger.info(f"Created department: {dept_data['name']}")

    db.session.flush()  # Get IDs
    return departments

def create_users(departments):
    """Create initial users with different roles"""
    users_data = [
        {
            'username': 'admin',
            'password': 'admin123',
            'full_name': 'System Administrator',
            'email': 'admin@company.com',
            'role': UserRole.SUPERADMIN,
            'department': None
        },
        {
            'username': 'netadmin',
            'password': 'netadmin123',
            'full_name': 'Network Administrator',
            'email': 'netadmin@company.com',
            'role': UserRole.NETWORK_ADMIN,
            'department': 'IT'
        },
        {
            'username': 'hod_it',
            'password': 'hod123',
            'full_name': 'John Smith',
            'email': 'john.smith@company.com',
            'role': UserRole.HOD,
            'department': 'IT'
        },
        {
            'username': 'hod_hr',
            'password': 'hod123',
            'full_name': 'Sarah Johnson',
            'email': 'sarah.johnson@company.com',
            'role': UserRole.HOD,
            'department': 'HR'
        },
        {
            'username': 'hod_fin',
            'password': 'hod123',
            'full_name': 'Michael Brown',
            'email': 'michael.brown@company.com',
            'role': UserRole.HOD,
            'department': 'FIN'
        },
        {
            'username': 'emp001',
            'password': 'emp123',
            'full_name': 'Alice Wilson',
            'email': 'alice.wilson@company.com',
            'role': UserRole.EMPLOYEE,
            'department': 'IT'
        },
        {
            'username': 'emp002',
            'password': 'emp123',
            'full_name': 'Bob Davis',
            'email': 'bob.davis@company.com',
            'role': UserRole.EMPLOYEE,
            'department': 'HR'
        },
        {
            'username': 'emp003',
            'password': 'emp123',
            'full_name': 'Carol Miller',
            'email': 'carol.miller@company.com',
            'role': UserRole.EMPLOYEE,
            'department': 'FIN'
        }
    ]

    users = {}
    for user_data in users_data:
        if not User.query.filter_by(username=user_data['username']).first():
            department_id = None
            if user_data['department'] and user_data['department'] in departments:
                department_id = departments[user_data['department']].id

            user = User(
                username=user_data['username'],
                password_hash=generate_password_hash(user_data['password']),
                full_name=user_data['full_name'],
                email=user_data['email'],
                role=user_data['role'],
                department_id=department_id
            )
            db.session.add(user)
            users[user_data['username']] = user
            logger.info(f"Created user: {user_data['username']} ({user_data['role'].value})")

    db.session.flush()  # Get IDs
    return users

def update_department_hods(departments, users):
    """Update departments with their HODs"""
    hod_mappings = {
        'IT': 'hod_it',
        'HR': 'hod_hr',
        'FIN': 'hod_fin'
    }

    for dept_code, username in hod_mappings.items():
        if dept_code in departments and username in users:
            departments[dept_code].hod_id = users[username].id
            logger.info(f"Assigned {users[username].full_name} as HOD of {dept_code}")

def create_locations():
    """Create initial locations"""
    locations_data = [
        {'code': 'HQ-101', 'office': 'Headquarters', 'room': 'IT Server Room'},
        {'code': 'HQ-201', 'office': 'Headquarters', 'room': 'IT Storage'},
        {'code': 'HQ-301', 'office': 'Headquarters', 'room': 'General Storage'},
        {'code': 'BR1-101', 'office': 'Branch Office 1', 'room': 'Storage Room'},
        {'code': 'BR2-101', 'office': 'Branch Office 2', 'room': 'Storage Room'},
        {'code': 'WH-001', 'office': 'Main Warehouse', 'room': 'Section A'},
        {'code': 'WH-002', 'office': 'Main Warehouse', 'room': 'Section B'}
    ]

    locations = {}
    for loc_data in locations_data:
        if not Location.query.filter_by(code=loc_data['code']).first():
            location = Location(
                code=loc_data['code'],
                office=loc_data['office'],
                room=loc_data['room']
            )
            db.session.add(location)
            locations[loc_data['code']] = location
            logger.info(f"Created location: {loc_data['code']}")

    db.session.flush()  # Get IDs
    return locations

def create_items():
    """Create initial items"""
    items_data = [
        {
            'code': 'LAP-001',
            'name': 'Laptop Computer',
            'make': 'Dell',
            'variant': 'Latitude 5520',
            'description': 'Business laptop with Intel i5 processor, 8GB RAM, 256GB SSD'
        },
        {
            'code': 'MON-001',
            'name': 'Monitor',
            'make': 'LG',
            'variant': '24inch LED',
            'description': '24-inch LED monitor with Full HD resolution'
        },
        {
            'code': 'KEY-001',
            'name': 'Keyboard',
            'make': 'Logitech',
            'variant': 'K120',
            'description': 'Standard USB keyboard'
        },
        {
            'code': 'MOU-001',
            'name': 'Mouse',
            'make': 'Logitech',
            'variant': 'M100',
            'description': 'Standard optical mouse'
        },
        {
            'code': 'CAB-001',
            'name': 'Network Cable',
            'make': 'Generic',
            'variant': 'Cat6 Ethernet',
            'description': 'Category 6 Ethernet cable, 5 meters'
        },
        {
            'code': 'HD-001',
            'name': 'External Hard Drive',
            'make': 'Seagate',
            'variant': '1TB USB 3.0',
            'description': '1TB external hard drive with USB 3.0 interface'
        },
        {
            'code': 'PWR-001',
            'name': 'Power Adapter',
            'make': 'Dell',
            'variant': '90W',
            'description': '90W laptop power adapter'
        },
        {
            'code': 'PEN-001',
            'name': 'USB Pen Drive',
            'make': 'SanDisk',
            'variant': '32GB',
            'description': '32GB USB 3.0 pen drive'
        },
        {
            'code': 'PRT-001',
            'name': 'Printer',
            'make': 'HP',
            'variant': 'LaserJet Pro',
            'description': 'Monochrome laser printer'
        },
        {
            'code': 'SWI-001',
            'name': 'Network Switch',
            'make': 'Cisco',
            'variant': '24-port',
            'description': '24-port gigabit network switch'
        }
    ]

    items = {}
    for item_data in items_data:
        if not Item.query.filter_by(code=item_data['code']).first():
            item = Item(
                code=item_data['code'],
                name=item_data['name'],
                make=item_data['make'],
                variant=item_data['variant'],
                description=item_data['description']
            )
            db.session.add(item)
            items[item_data['code']] = item
            logger.info(f"Created item: {item_data['code']} - {item_data['name']}")

    db.session.flush()  # Get IDs
    return items

def create_employees(departments, users):
    """Create employee records"""
    employees_data = [
        {
            'emp_id': 'EMP001',
            'name': 'Alice Wilson',
            'department': 'IT',
            'username': 'emp001'
        },
        {
            'emp_id': 'EMP002',
            'name': 'Bob Davis',
            'department': 'HR',
            'username': 'emp002'
        },
        {
            'emp_id': 'EMP003',
            'name': 'Carol Miller',
            'department': 'FIN',
            'username': 'emp003'
        },
        {
            'emp_id': 'HOD001',
            'name': 'John Smith',
            'department': 'IT',
            'username': 'hod_it'
        },
        {
            'emp_id': 'HOD002',
            'name': 'Sarah Johnson',
            'department': 'HR',
            'username': 'hod_hr'
        },
        {
            'emp_id': 'HOD003',
            'name': 'Michael Brown',
            'department': 'FIN',
            'username': 'hod_fin'
        }
    ]

    for emp_data in employees_data:
        if not Employee.query.filter_by(emp_id=emp_data['emp_id']).first():
            department_id = None
            user_id = None

            if emp_data['department'] in departments:
                department_id = departments[emp_data['department']].id

            if emp_data['username'] in users:
                user_id = users[emp_data['username']].id

            employee = Employee(
                emp_id=emp_data['emp_id'],
                name=emp_data['name'],
                department_id=department_id,
                user_id=user_id
            )
            db.session.add(employee)
            logger.info(f"Created employee: {emp_data['emp_id']} - {emp_data['name']}")

    db.session.flush()

def create_initial_stock(items, locations, users):
    """Create initial stock entries and balances"""
    # Sample stock data
    stock_data = [
        {'item': 'LAP-001', 'location': 'HQ-201', 'quantity': 25},
        {'item': 'MON-001', 'location': 'HQ-201', 'quantity': 30},
        {'item': 'KEY-001', 'location': 'HQ-201', 'quantity': 50},
        {'item': 'MOU-001', 'location': 'HQ-201', 'quantity': 50},
        {'item': 'CAB-001', 'location': 'HQ-201', 'quantity': 100},
        {'item': 'HD-001', 'location': 'HQ-301', 'quantity': 15},
        {'item': 'PWR-001', 'location': 'HQ-201', 'quantity': 20},
        {'item': 'PEN-001', 'location': 'HQ-301', 'quantity': 75},
        {'item': 'PRT-001', 'location': 'WH-001', 'quantity': 5},
        {'item': 'SWI-001', 'location': 'HQ-101', 'quantity': 3},
        # Add stock to other locations
        {'item': 'LAP-001', 'location': 'BR1-101', 'quantity': 10},
        {'item': 'MON-001', 'location': 'BR1-101', 'quantity': 12},
        {'item': 'KEY-001', 'location': 'WH-002', 'quantity': 25},
        {'item': 'MOU-001', 'location': 'WH-002', 'quantity': 25},
        {'item': 'CAB-001', 'location': 'WH-001', 'quantity': 50}
    ]

    admin_user = users.get('admin')
    if not admin_user:
        logger.warning("Admin user not found, skipping stock creation")
        return

    for stock in stock_data:
        item_code = stock['item']
        location_code = stock['location']
        quantity = stock['quantity']

        if item_code in items and location_code in locations:
            item = items[item_code]
            location = locations[location_code]

            # Check if stock balance already exists
            existing_balance = StockBalance.query.filter_by(
                item_id=item.id,
                location_id=location.id
            ).first()

            if not existing_balance:
                # Create stock entry
                stock_entry = StockEntry(
                    item_id=item.id,
                    location_id=location.id,
                    quantity=quantity,
                    description=f"Initial stock for {item.name}",
                    remarks="System seeded data",
                    created_by=admin_user.id
                )
                db.session.add(stock_entry)
                db.session.flush()  # Flush to get the ID

                # Create stock balance
                stock_balance = StockBalance(
                    item_id=item.id,
                    location_id=location.id,
                    quantity=quantity
                )
                db.session.add(stock_balance)

                # Create audit log after flush so we have the ID
                Audit.log(
                    entity_type='StockEntry',
                    entity_id=stock_entry.id,
                    action='CREATE',
                    user_id=admin_user.id,
                    details=f'Initial stock entry: {quantity} units of {item.code} at {location.code}'
                )

                logger.info(f"Created initial stock: {quantity} units of {item_code} at {location_code}")

    db.session.flush()

if __name__ == '__main__':
    # This allows running the seed script independently for testing
    from app import create_app

    app = create_app()
    with app.app_context():
        seed_initial_data()
        print("Seed data created successfully!")