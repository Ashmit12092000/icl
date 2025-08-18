"""
Test configuration and fixtures for IT Stock Management System
"""

import pytest
import tempfile
import os
from decimal import Decimal
from werkzeug.security import generate_password_hash

from app import create_app, db as _db
from models import (User, UserRole, Department, Location, Item, Employee,
                   StockBalance, StockEntry, StockIssueRequest, StockIssueLine,
                   RequestStatus, Audit)

@pytest.fixture(scope='session')
def app():
    """Create and configure a new app instance for each test session."""
    # Create a temporary file to serve as the database
    db_fd, db_path = tempfile.mkstemp()
    
    # Create app with testing configuration
    app = create_app()
    app.config.update({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_path}',
        'SQLALCHEMY_TRACK_MODIFICATIONS': False,
        'WTF_CSRF_ENABLED': False,  # Disable CSRF for testing
        'SECRET_KEY': 'test-secret-key',
        'SESSION_SECRET': 'test-session-secret'
    })
    
    # Establish an application context
    with app.app_context():
        _db.create_all()
        yield app
        
    # Clean up
    os.close(db_fd)
    os.unlink(db_path)

@pytest.fixture(scope='function')
def db(app):
    """Create a fresh database for each test."""
    with app.app_context():
        _db.create_all()
        yield _db
        _db.session.rollback()
        _db.drop_all()

@pytest.fixture
def client(app):
    """Create a test client for the app."""
    return app.test_client()

@pytest.fixture
def runner(app):
    """Create a test runner for the app's Click commands."""
    return app.test_cli_runner()

# Model fixtures

@pytest.fixture
def sample_user(db):
    """Create a sample user for testing."""
    user = User(
        username='testuser',
        password_hash=generate_password_hash('password123'),
        full_name='Test User',
        email='test@example.com',
        role=UserRole.EMPLOYEE
    )
    db.session.add(user)
    db.session.commit()
    return user

@pytest.fixture
def sample_user_with_role(db):
    """Factory fixture for creating users with specific roles."""
    def _create_user(role, username=None, department_id=None):
        username = username or f'user_{role.value}'
        user = User(
            username=username,
            password_hash=generate_password_hash('password123'),
            full_name=f'Test {role.value.title()}',
            email=f'{username}@example.com',
            role=role,
            department_id=department_id
        )
        db.session.add(user)
        db.session.commit()
        return user
    return _create_user

@pytest.fixture
def sample_department(db):
    """Create a sample department for testing."""
    department = Department(
        code='TEST',
        name='Test Department'
    )
    db.session.add(department)
    db.session.commit()
    return department

@pytest.fixture
def sample_location(db):
    """Create a sample location for testing."""
    location = Location(
        office='Test Office',
        room='Test Room',
        code='TEST-001'
    )
    db.session.add(location)
    db.session.commit()
    return location

@pytest.fixture
def sample_item(db):
    """Create a sample item for testing."""
    item = Item(
        code='TEST-ITEM',
        name='Test Item',
        make='Test Make',
        variant='Test Variant',
        description='Test Description'
    )
    db.session.add(item)
    db.session.commit()
    return item

@pytest.fixture
def sample_employee(db, sample_department, sample_user):
    """Create a sample employee for testing."""
    employee = Employee(
        emp_id='EMP001',
        name='Test Employee',
        department_id=sample_department.id,
        user_id=sample_user.id
    )
    db.session.add(employee)
    db.session.commit()
    return employee

@pytest.fixture
def sample_stock_balance(db, sample_item, sample_location):
    """Create a sample stock balance for testing."""
    balance = StockBalance(
        item_id=sample_item.id,
        location_id=sample_location.id,
        quantity=Decimal('10.00')
    )
    db.session.add(balance)
    db.session.commit()
    return balance

@pytest.fixture
def sample_stock_entry(db, sample_item, sample_location, sample_user):
    """Create a sample stock entry for testing."""
    entry = StockEntry(
        item_id=sample_item.id,
        location_id=sample_location.id,
        quantity=Decimal('5.00'),
        description='Test entry',
        created_by=sample_user.id
    )
    db.session.add(entry)
    db.session.commit()
    return entry

@pytest.fixture
def sample_stock_request(db, sample_user, sample_department, sample_location):
    """Create a sample stock issue request for testing."""
    request = StockIssueRequest(
        request_no='TEST-REQ-001',
        requester_id=sample_user.id,
        department_id=sample_department.id,
        location_id=sample_location.id,
        purpose='Test request',
        status=RequestStatus.DRAFT
    )
    db.session.add(request)
    db.session.commit()
    return request

@pytest.fixture
def sample_stock_request_line(db, sample_stock_request, sample_item):
    """Create a sample stock issue line for testing."""
    line = StockIssueLine(
        request_id=sample_stock_request.id,
        item_id=sample_item.id,
        quantity_requested=Decimal('2.00')
    )
    db.session.add(line)
    db.session.commit()
    return line

# Authentication fixtures

@pytest.fixture
def logged_in_user(client, sample_user):
    """Log in a user and return the client."""
    client.post('/auth/login', data={
        'username': 'testuser',
        'password': 'password123'
    })
    return client

@pytest.fixture
def logged_in_admin(client, db):
    """Log in as admin and return the client."""
    admin = User(
        username='admin',
        password_hash=generate_password_hash('admin123'),
        full_name='Administrator',
        email='admin@example.com',
        role=UserRole.SUPERADMIN
    )
    db.session.add(admin)
    db.session.commit()
    
    client.post('/auth/login', data={
        'username': 'admin',
        'password': 'admin123'
    })
    return client

@pytest.fixture
def logged_in_hod(client, db, sample_department):
    """Log in as HOD and return the client."""
    hod = User(
        username='hod',
        password_hash=generate_password_hash('hod123'),
        full_name='Head of Department',
        email='hod@example.com',
        role=UserRole.HOD,
        department_id=sample_department.id
    )
    db.session.add(hod)
    db.session.flush()
    
    # Assign as HOD
    sample_department.hod_id = hod.id
    db.session.commit()
    
    client.post('/auth/login', data={
        'username': 'hod',
        'password': 'hod123'
    })
    return client

@pytest.fixture
def logged_in_network_admin(client, db):
    """Log in as network admin and return the client."""
    netadmin = User(
        username='netadmin',
        password_hash=generate_password_hash('netadmin123'),
        full_name='Network Administrator',
        email='netadmin@example.com',
        role=UserRole.NETWORK_ADMIN
    )
    db.session.add(netadmin)
    db.session.commit()
    
    client.post('/auth/login', data={
        'username': 'netadmin',
        'password': 'netadmin123'
    })
    return client

# Complex fixtures for integration testing

@pytest.fixture
def complete_stock_scenario(db, sample_user, sample_department, sample_location, sample_item):
    """Create a complete stock scenario with entries, balances, and requests."""
    # Create stock entry
    stock_entry = StockEntry(
        item_id=sample_item.id,
        location_id=sample_location.id,
        quantity=Decimal('20.00'),
        description='Initial stock',
        created_by=sample_user.id
    )
    db.session.add(stock_entry)
    
    # Create stock balance
    stock_balance = StockBalance(
        item_id=sample_item.id,
        location_id=sample_location.id,
        quantity=Decimal('20.00')
    )
    db.session.add(stock_balance)
    
    # Create stock request
    stock_request = StockIssueRequest(
        request_no='COMPLETE-REQ-001',
        requester_id=sample_user.id,
        department_id=sample_department.id,
        location_id=sample_location.id,
        purpose='Complete test scenario',
        status=RequestStatus.PENDING
    )
    db.session.add(stock_request)
    db.session.flush()
    
    # Create request line
    request_line = StockIssueLine(
        request_id=stock_request.id,
        item_id=sample_item.id,
        quantity_requested=Decimal('5.00')
    )
    db.session.add(request_line)
    
    db.session.commit()
    
    return {
        'user': sample_user,
        'department': sample_department,
        'location': sample_location,
        'item': sample_item,
        'stock_entry': stock_entry,
        'stock_balance': stock_balance,
        'stock_request': stock_request,
        'request_line': request_line
    }

@pytest.fixture
def hod_with_department_setup(db):
    """Create a complete HOD setup with department and users."""
    # Create department
    department = Department(
        code='HODDEPT',
        name='HOD Test Department'
    )
    db.session.add(department)
    db.session.flush()
    
    # Create HOD user
    hod_user = User(
        username='test_hod',
        password_hash=generate_password_hash('hod123'),
        full_name='Test HOD',
        email='test_hod@example.com',
        role=UserRole.HOD,
        department_id=department.id
    )
    db.session.add(hod_user)
    db.session.flush()
    
    # Assign HOD to department
    department.hod_id = hod_user.id
    
    # Create employee in same department
    employee_user = User(
        username='test_employee',
        password_hash=generate_password_hash('emp123'),
        full_name='Test Employee',
        email='test_employee@example.com',
        role=UserRole.EMPLOYEE,
        department_id=department.id
    )
    db.session.add(employee_user)
    
    db.session.commit()
    
    return {
        'department': department,
        'hod_user': hod_user,
        'employee_user': employee_user
    }

# Test data generators

@pytest.fixture
def item_factory(db):
    """Factory for creating multiple items."""
    def _create_items(count=5):
        items = []
        for i in range(count):
            item = Item(
                code=f'ITEM-{i:03d}',
                name=f'Test Item {i}',
                make=f'Make {i}',
                variant=f'Variant {i}',
                description=f'Description for item {i}'
            )
            db.session.add(item)
            items.append(item)
        db.session.commit()
        return items
    return _create_items

@pytest.fixture
def location_factory(db):
    """Factory for creating multiple locations."""
    def _create_locations(count=3):
        locations = []
        for i in range(count):
            location = Location(
                office=f'Office {i}',
                room=f'Room {i}',
                code=f'LOC-{i:03d}'
            )
            db.session.add(location)
            locations.append(location)
        db.session.commit()
        return locations
    return _create_locations

# Utility fixtures

@pytest.fixture
def clean_db(db):
    """Ensure clean database state."""
    # Clear all tables
    for table in reversed(db.metadata.sorted_tables):
        db.session.execute(table.delete())
    db.session.commit()
    yield db
    # Clean up after test
    for table in reversed(db.metadata.sorted_tables):
        db.session.execute(table.delete())
    db.session.commit()

# Mock fixtures for external dependencies (if any)

@pytest.fixture
def mock_email_service(monkeypatch):
    """Mock email service for notification testing."""
    emails_sent = []
    
    def mock_send_email(to, subject, body):
        emails_sent.append({
            'to': to,
            'subject': subject,
            'body': body
        })
        return True
    
    # If you have an email service, mock it here
    # monkeypatch.setattr('app.email_service.send_email', mock_send_email)
    
    return emails_sent

# Performance testing fixtures

@pytest.fixture
def performance_data(db, sample_user):
    """Create a large dataset for performance testing."""
    from datetime import datetime, timedelta
    
    # Create multiple departments
    departments = []
    for i in range(5):
        dept = Department(code=f'PERF{i}', name=f'Performance Dept {i}')
        db.session.add(dept)
        departments.append(dept)
    
    # Create multiple items
    items = []
    for i in range(50):
        item = Item(
            code=f'PERF-ITEM-{i:03d}',
            name=f'Performance Item {i}',
            make='Performance Make',
            description=f'Performance test item {i}'
        )
        db.session.add(item)
        items.append(item)
    
    # Create multiple locations
    locations = []
    for i in range(10):
        location = Location(
            office=f'Performance Office {i}',
            room=f'Room {i}',
            code=f'PERF-LOC-{i:03d}'
        )
        db.session.add(location)
        locations.append(location)
    
    db.session.commit()
    
    return {
        'departments': departments,
        'items': items,
        'locations': locations,
        'user': sample_user
    }
