"""
Unit tests for database models
"""

import pytest
from decimal import Decimal
from datetime import datetime
from models import (User, UserRole, Department, Location, Item, Employee,
                   StockBalance, StockEntry, StockIssueRequest, StockIssueLine,
                   RequestStatus, Audit)
from werkzeug.security import generate_password_hash, check_password_hash

class TestUser:
    """Test User model"""
    
    def test_user_creation(self, db):
        """Test creating a user"""
        user = User(
            username='testuser',
            password_hash=generate_password_hash('password123'),
            full_name='Test User',
            email='test@example.com',
            role=UserRole.EMPLOYEE
        )
        db.session.add(user)
        db.session.commit()
        
        assert user.id is not None
        assert user.username == 'testuser'
        assert user.full_name == 'Test User'
        assert user.email == 'test@example.com'
        assert user.role == UserRole.EMPLOYEE
        assert user.is_active is True
        assert check_password_hash(user.password_hash, 'password123')
    
    def test_user_has_role(self, db):
        """Test user role checking"""
        user = User(
            username='testuser',
            password_hash=generate_password_hash('password123'),
            full_name='Test User',
            email='test@example.com',
            role=UserRole.HOD
        )
        
        assert user.has_role('hod') is True
        assert user.has_role(UserRole.HOD) is True
        assert user.has_role('employee') is False
        assert user.has_role(UserRole.EMPLOYEE) is False
    
    def test_user_can_approve_for_department(self, db, sample_department):
        """Test department approval permission"""
        user = User(
            username='hod_user',
            password_hash=generate_password_hash('password123'),
            full_name='HOD User',
            email='hod@example.com',
            role=UserRole.HOD
        )
        db.session.add(user)
        db.session.flush()
        
        # Assign user as HOD of department
        sample_department.hod_id = user.id
        db.session.commit()
        
        assert user.can_approve_for_department(sample_department.id) is True
        assert user.can_approve_for_department(999) is False  # Non-existent department
    
    def test_user_repr(self, db):
        """Test user string representation"""
        user = User(username='testuser')
        assert str(user) == '<User testuser>'

class TestDepartment:
    """Test Department model"""
    
    def test_department_creation(self, db):
        """Test creating a department"""
        dept = Department(
            code='TEST',
            name='Test Department'
        )
        db.session.add(dept)
        db.session.commit()
        
        assert dept.id is not None
        assert dept.code == 'TEST'
        assert dept.name == 'Test Department'
        assert dept.hod_id is None
        assert dept.created_at is not None
    
    def test_department_with_hod(self, db, sample_user):
        """Test department with HOD assignment"""
        dept = Department(
            code='TEST',
            name='Test Department',
            hod_id=sample_user.id
        )
        db.session.add(dept)
        db.session.commit()
        
        assert dept.hod_id == sample_user.id
        assert dept.hod == sample_user
    
    def test_department_repr(self, db):
        """Test department string representation"""
        dept = Department(code='TEST', name='Test Department')
        assert str(dept) == '<Department TEST>'

class TestLocation:
    """Test Location model"""
    
    def test_location_creation(self, db):
        """Test creating a location"""
        location = Location(
            office='Test Office',
            room='Test Room',
            code='TEST-001'
        )
        db.session.add(location)
        db.session.commit()
        
        assert location.id is not None
        assert location.office == 'Test Office'
        assert location.room == 'Test Room'
        assert location.code == 'TEST-001'
        assert location.created_at is not None
    
    def test_location_repr(self, db):
        """Test location string representation"""
        location = Location(code='TEST-001', office='Test Office', room='Test Room')
        assert str(location) == '<Location TEST-001>'

class TestItem:
    """Test Item model"""
    
    def test_item_creation(self, db):
        """Test creating an item"""
        item = Item(
            code='TEST-001',
            name='Test Item',
            make='Test Make',
            variant='Test Variant',
            description='Test Description'
        )
        db.session.add(item)
        db.session.commit()
        
        assert item.id is not None
        assert item.code == 'TEST-001'
        assert item.name == 'Test Item'
        assert item.make == 'Test Make'
        assert item.variant == 'Test Variant'
        assert item.description == 'Test Description'
        assert item.created_at is not None
    
    def test_item_minimal(self, db):
        """Test creating item with minimal required fields"""
        item = Item(
            code='MIN-001',
            name='Minimal Item'
        )
        db.session.add(item)
        db.session.commit()
        
        assert item.id is not None
        assert item.code == 'MIN-001'
        assert item.name == 'Minimal Item'
        assert item.make is None
        assert item.variant is None
        assert item.description is None
    
    def test_item_repr(self, db):
        """Test item string representation"""
        item = Item(code='TEST-001', name='Test Item')
        assert str(item) == '<Item TEST-001>'

class TestEmployee:
    """Test Employee model"""
    
    def test_employee_creation(self, db, sample_department, sample_user):
        """Test creating an employee"""
        employee = Employee(
            emp_id='EMP001',
            name='Test Employee',
            department_id=sample_department.id,
            user_id=sample_user.id
        )
        db.session.add(employee)
        db.session.commit()
        
        assert employee.id is not None
        assert employee.emp_id == 'EMP001'
        assert employee.name == 'Test Employee'
        assert employee.department_id == sample_department.id
        assert employee.user_id == sample_user.id
        assert employee.department == sample_department
        assert employee.user == sample_user
        assert employee.created_at is not None
    
    def test_employee_without_user(self, db, sample_department):
        """Test creating employee without linked user"""
        employee = Employee(
            emp_id='EMP002',
            name='Test Employee 2',
            department_id=sample_department.id
        )
        db.session.add(employee)
        db.session.commit()
        
        assert employee.user_id is None
        assert employee.user is None
    
    def test_employee_repr(self, db):
        """Test employee string representation"""
        employee = Employee(emp_id='EMP001', name='Test Employee')
        assert str(employee) == '<Employee EMP001>'

class TestStockBalance:
    """Test StockBalance model"""
    
    def test_stock_balance_creation(self, db, sample_item, sample_location):
        """Test creating a stock balance"""
        balance = StockBalance(
            item_id=sample_item.id,
            location_id=sample_location.id,
            quantity=Decimal('10.50')
        )
        db.session.add(balance)
        db.session.commit()
        
        assert balance.id is not None
        assert balance.item_id == sample_item.id
        assert balance.location_id == sample_location.id
        assert balance.quantity == Decimal('10.50')
        assert balance.item == sample_item
        assert balance.location == sample_location
        assert balance.last_updated is not None
    
    def test_stock_balance_unique_constraint(self, db, sample_item, sample_location):
        """Test unique constraint on item_id and location_id"""
        balance1 = StockBalance(
            item_id=sample_item.id,
            location_id=sample_location.id,
            quantity=Decimal('10.00')
        )
        db.session.add(balance1)
        db.session.commit()
        
        # Try to create duplicate
        balance2 = StockBalance(
            item_id=sample_item.id,
            location_id=sample_location.id,
            quantity=Decimal('20.00')
        )
        db.session.add(balance2)
        
        with pytest.raises(Exception):  # Should raise integrity error
            db.session.commit()
    
    def test_stock_balance_repr(self, db, sample_item, sample_location):
        """Test stock balance string representation"""
        balance = StockBalance(
            item_id=sample_item.id,
            location_id=sample_location.id,
            quantity=Decimal('10.50')
        )
        expected = f'<StockBalance Item:{sample_item.id} Location:{sample_location.id} Qty:10.50>'
        assert str(balance) == expected

class TestStockEntry:
    """Test StockEntry model"""
    
    def test_stock_entry_creation(self, db, sample_item, sample_location, sample_user):
        """Test creating a stock entry"""
        entry = StockEntry(
            item_id=sample_item.id,
            location_id=sample_location.id,
            quantity=Decimal('5.00'),
            description='Test entry',
            remarks='Test remarks',
            created_by=sample_user.id
        )
        db.session.add(entry)
        db.session.commit()
        
        assert entry.id is not None
        assert entry.item_id == sample_item.id
        assert entry.location_id == sample_location.id
        assert entry.quantity == Decimal('5.00')
        assert entry.description == 'Test entry'
        assert entry.remarks == 'Test remarks'
        assert entry.created_by == sample_user.id
        assert entry.item == sample_item
        assert entry.creator == sample_user
        assert entry.created_at is not None
    
    def test_stock_entry_repr(self, db):
        """Test stock entry string representation"""
        entry = StockEntry(id=1)
        entry.id = 1  # Simulate saved entry
        assert str(entry) == '<StockEntry 1>'

class TestStockIssueRequest:
    """Test StockIssueRequest model"""
    
    def test_request_creation(self, db, sample_user, sample_department, sample_location):
        """Test creating a stock issue request"""
        request = StockIssueRequest(
            request_no='REQ001',
            requester_id=sample_user.id,
            department_id=sample_department.id,
            location_id=sample_location.id,
            purpose='Test purpose',
            remarks='Test remarks'
        )
        db.session.add(request)
        db.session.commit()
        
        assert request.id is not None
        assert request.request_no == 'REQ001'
        assert request.requester_id == sample_user.id
        assert request.department_id == sample_department.id
        assert request.location_id == sample_location.id
        assert request.purpose == 'Test purpose'
        assert request.remarks == 'Test remarks'
        assert request.status == RequestStatus.DRAFT
        assert request.requester == sample_user
        assert request.department == sample_department
        assert request.location == sample_location
        assert request.created_at is not None
    
    def test_generate_request_no(self, db, sample_user, sample_department, sample_location):
        """Test request number generation"""
        request = StockIssueRequest(
            requester_id=sample_user.id,
            department_id=sample_department.id,
            location_id=sample_location.id,
            purpose='Test purpose'
        )
        
        request_no = request.generate_request_no()
        assert request_no.startswith('REQ')
        assert len(request_no) >= 11  # REQ + 8 digit date + 3 digit sequence
    
    def test_can_be_approved_by(self, db, sample_user, sample_department, sample_location):
        """Test approval permission checking"""
        # Create HOD user
        hod_user = User(
            username='hod_test',
            password_hash=generate_password_hash('password123'),
            full_name='HOD Test',
            email='hod@example.com',
            role=UserRole.HOD
        )
        db.session.add(hod_user)
        db.session.flush()
        
        # Assign HOD to department
        sample_department.hod_id = hod_user.id
        
        request = StockIssueRequest(
            request_no='REQ001',
            requester_id=sample_user.id,
            department_id=sample_department.id,
            location_id=sample_location.id,
            purpose='Test purpose'
        )
        db.session.add(request)
        db.session.commit()
        
        assert request.can_be_approved_by(hod_user) is True
        assert request.can_be_approved_by(sample_user) is False  # Not HOD
    
    def test_request_repr(self, db):
        """Test request string representation"""
        request = StockIssueRequest(request_no='REQ001')
        assert str(request) == '<StockIssueRequest REQ001>'

class TestStockIssueLine:
    """Test StockIssueLine model"""
    
    def test_issue_line_creation(self, db, sample_item, sample_user, sample_department, sample_location):
        """Test creating a stock issue line"""
        request = StockIssueRequest(
            request_no='REQ001',
            requester_id=sample_user.id,
            department_id=sample_department.id,
            location_id=sample_location.id,
            purpose='Test purpose'
        )
        db.session.add(request)
        db.session.flush()
        
        line = StockIssueLine(
            request_id=request.id,
            item_id=sample_item.id,
            quantity_requested=Decimal('5.00'),
            quantity_issued=Decimal('3.00'),
            remarks='Test line remarks'
        )
        db.session.add(line)
        db.session.commit()
        
        assert line.id is not None
        assert line.request_id == request.id
        assert line.item_id == sample_item.id
        assert line.quantity_requested == Decimal('5.00')
        assert line.quantity_issued == Decimal('3.00')
        assert line.remarks == 'Test line remarks'
        assert line.request == request
        assert line.item == sample_item
    
    def test_issue_line_repr(self, db):
        """Test issue line string representation"""
        line = StockIssueLine(id=1)
        line.id = 1  # Simulate saved line
        assert str(line) == '<StockIssueLine 1>'

class TestAudit:
    """Test Audit model"""
    
    def test_audit_creation(self, db, sample_user):
        """Test creating an audit entry"""
        audit = Audit(
            entity_type='User',
            entity_id=sample_user.id,
            action='CREATE',
            performed_by=sample_user.id,
            details='Created user for testing'
        )
        db.session.add(audit)
        db.session.commit()
        
        assert audit.id is not None
        assert audit.entity_type == 'User'
        assert audit.entity_id == sample_user.id
        assert audit.action == 'CREATE'
        assert audit.performed_by == sample_user.id
        assert audit.details == 'Created user for testing'
        assert audit.user == sample_user
        assert audit.timestamp is not None
    
    def test_audit_log_helper(self, db, sample_user):
        """Test audit log helper method"""
        Audit.log(
            entity_type='TestEntity',
            entity_id=123,
            action='TEST_ACTION',
            user_id=sample_user.id,
            details='Test audit log'
        )
        
        # The log method adds to session but doesn't commit
        # We need to commit to verify it was added
        db.session.commit()
        
        audit = Audit.query.filter_by(entity_type='TestEntity').first()
        assert audit is not None
        assert audit.entity_id == 123
        assert audit.action == 'TEST_ACTION'
        assert audit.performed_by == sample_user.id
        assert audit.details == 'Test audit log'
    
    def test_audit_repr(self, db):
        """Test audit string representation"""
        audit = Audit(entity_type='User', entity_id=1, action='CREATE')
        assert str(audit) == '<Audit User:1 CREATE>'
