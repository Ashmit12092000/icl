from datetime import datetime
from decimal import Decimal
from enum import Enum
from flask_login import UserMixin
from sqlalchemy import func, CheckConstraint
from database import db

class UserRole(Enum):
    SUPERADMIN = 'superadmin'
    MANAGER = 'manager'
    HOD = 'hod'
    EMPLOYEE = 'employee'

class RequestStatus(Enum):
    DRAFT = 'Draft'
    PENDING = 'Pending'
    APPROVED = 'Approved'
    REJECTED = 'Rejected'
    ISSUED = 'Issued'

# Association table for User-Warehouse many-to-many relationship
user_warehouse_assignments = db.Table('user_warehouse_assignments',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id'), primary_key=True),
    db.Column('location_id', db.Integer, db.ForeignKey('locations.id'), primary_key=True),
    db.Column('assigned_at', db.DateTime, default=datetime.utcnow),
    db.Column('assigned_by', db.Integer, db.ForeignKey('users.id'))
)

class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    full_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    role = db.Column(db.Enum(UserRole), nullable=False, default=UserRole.EMPLOYEE)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)

    # Relationships
    department = db.relationship('Department', foreign_keys=[department_id], back_populates='users')
    managed_department = db.relationship('Department', foreign_keys='Department.hod_id', back_populates='hod', uselist=False)
    employee = db.relationship('Employee', back_populates='user', uselist=False)
    assigned_warehouses = db.relationship(
        'Location', 
        secondary=user_warehouse_assignments, 
        primaryjoin=id == user_warehouse_assignments.c.user_id,
        back_populates='assigned_users'
    )

    def has_role(self, role):
        if isinstance(role, str):
            return self.role.value == role
        return self.role == role

    def can_approve_for_department(self, department_id):
        return (self.role == UserRole.HOD and 
                self.managed_department and 
                self.managed_department.id == department_id)

    def get_accessible_warehouses(self):
        """Get all warehouses user can access"""
        if self.role in [UserRole.SUPERADMIN, UserRole.MANAGER]:
            return Location.query.all()
        return self.assigned_warehouses

    def can_access_warehouse(self, location_id):
        """Check if user can access specific warehouse"""
        if self.role in [UserRole.SUPERADMIN, UserRole.MANAGER]:
            return True
        return any(w.id == location_id for w in self.assigned_warehouses)

    def __repr__(self):
        return f'<User {self.username}>'

class Department(db.Model):
    __tablename__ = 'departments'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    hod_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    hod = db.relationship('User', foreign_keys=[hod_id], back_populates='managed_department')
    users = db.relationship('User', foreign_keys='User.department_id', back_populates='department')
    employees = db.relationship('Employee', back_populates='department')

    def __repr__(self):
        return f'<Department {self.code}>'

class Location(db.Model):
    __tablename__ = 'locations'

    id = db.Column(db.Integer, primary_key=True)
    office = db.Column(db.String(100), nullable=False)
    room = db.Column(db.String(50), nullable=False)
    code = db.Column(db.String(20), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    stock_balances = db.relationship('StockBalance', back_populates='location')
    assigned_users = db.relationship(
        'User', 
        secondary=user_warehouse_assignments, 
        primaryjoin=id == user_warehouse_assignments.c.location_id,
        secondaryjoin=user_warehouse_assignments.c.user_id == User.id,
        back_populates='assigned_warehouses'
    )

    def __repr__(self):
        return f'<Location {self.code}>'

class Employee(db.Model):
    __tablename__ = 'employees'

    id = db.Column(db.Integer, primary_key=True)
    emp_id = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    department = db.relationship('Department', back_populates='employees')
    user = db.relationship('User', back_populates='employee')

    def __repr__(self):
        return f'<Employee {self.emp_id}>'

class Item(db.Model):
    __tablename__ = 'items'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    make = db.Column(db.String(50))
    variant = db.Column(db.String(50))
    description = db.Column(db.Text)
    low_stock_threshold = db.Column(db.Numeric(10, 2), nullable=False, default=5)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    stock_balances = db.relationship('StockBalance', back_populates='item')
    stock_entries = db.relationship('StockEntry', back_populates='item')
    issue_lines = db.relationship('StockIssueLine', back_populates='item')

    def is_low_stock_at_location(self, location_id):
        """Check if item is low stock at specific location"""
        balance = StockBalance.query.filter_by(
            item_id=self.id,
            location_id=location_id
        ).first()
        if not balance:
            return True  # No stock at all
        return balance.quantity <= self.low_stock_threshold

    def get_low_stock_locations(self):
        """Get all locations where this item is low stock"""
        balances = StockBalance.query.filter_by(item_id=self.id).all()
        low_stock_locations = []
        for balance in balances:
            if balance.quantity <= self.low_stock_threshold:
                low_stock_locations.append(balance.location)
        return low_stock_locations

    @staticmethod
    def get_low_stock_items():
        """Get all items that are low stock at any location"""
        low_stock_query = db.session.query(Item).join(StockBalance).filter(
            StockBalance.quantity <= Item.low_stock_threshold
        ).distinct()
        return low_stock_query.all()

    def __repr__(self):
        return f'<Item {self.code}>'

class StockBalance(db.Model):
    __tablename__ = 'stock_balances'

    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('items.id'), nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey('locations.id'), nullable=False)
    quantity = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    item = db.relationship('Item', back_populates='stock_balances')
    location = db.relationship('Location', back_populates='stock_balances')

    # Constraints
    __table_args__ = (
        db.UniqueConstraint('item_id', 'location_id'),
        CheckConstraint('quantity >= 0', name='positive_quantity')
    )

    def __repr__(self):
        return f'<StockBalance Item:{self.item_id} Location:{self.location_id} Qty:{self.quantity}>'

class StockEntry(db.Model):
    __tablename__ = 'stock_entries'

    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('items.id'), nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey('locations.id'), nullable=False)
    quantity = db.Column(db.Numeric(10, 2), nullable=False)
    description = db.Column(db.String(200))
    remarks = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    item = db.relationship('Item', back_populates='stock_entries')
    location = db.relationship('Location')
    creator = db.relationship('User')

    def __repr__(self):
        return f'<StockEntry {self.id}>'

class StockIssueRequest(db.Model):
    __tablename__ = 'stock_issue_requests'

    id = db.Column(db.Integer, primary_key=True)
    request_no = db.Column(db.String(20), unique=True, nullable=False)
    requester_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=False)
    hod_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    location_id = db.Column(db.Integer, db.ForeignKey('locations.id'), nullable=False)
    status = db.Column(db.Enum(RequestStatus), nullable=False, default=RequestStatus.DRAFT)
    purpose = db.Column(db.String(200), nullable=False)
    remarks = db.Column(db.Text)
    approved_at = db.Column(db.DateTime)
    approved_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    issued_at = db.Column(db.DateTime)
    issued_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    requester = db.relationship('User', foreign_keys=[requester_id])
    department = db.relationship('Department')
    hod = db.relationship('User', foreign_keys=[hod_id])
    location = db.relationship('Location')
    approver = db.relationship('User', foreign_keys=[approved_by])
    issuer = db.relationship('User', foreign_keys=[issued_by])
    issue_lines = db.relationship('StockIssueLine', back_populates='request', cascade='all, delete-orphan')

    def generate_request_no(self):
        """Generate unique request number"""
        today = datetime.utcnow()
        prefix = f"REQ{today.strftime('%Y%m%d')}"

        # Find the last request number for today
        last_request = db.session.query(StockIssueRequest).filter(
            StockIssueRequest.request_no.like(f"{prefix}%")
        ).order_by(StockIssueRequest.request_no.desc()).first()

        if last_request:
            last_seq = int(last_request.request_no[-3:])
            new_seq = last_seq + 1
        else:
            new_seq = 1

        return f"{prefix}{new_seq:03d}"

    def can_be_approved_by(self, user):
        """Check if user can approve this request"""
        return (user.role == UserRole.HOD and 
                user.managed_department and 
                user.managed_department.id == self.department_id)

    def __repr__(self):
        return f'<StockIssueRequest {self.request_no}>'

class StockIssueLine(db.Model):
    __tablename__ = 'stock_issue_lines'

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey('stock_issue_requests.id'), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey('items.id'), nullable=False)
    quantity_requested = db.Column(db.Numeric(10, 2), nullable=False)
    quantity_issued = db.Column(db.Numeric(10, 2), nullable=True)
    remarks = db.Column(db.String(200))

    # Relationships
    request = db.relationship('StockIssueRequest', back_populates='issue_lines')
    item = db.relationship('Item', back_populates='issue_lines')

    def __repr__(self):
        return f'<StockIssueLine {self.id}>'

class Audit(db.Model):
    __tablename__ = 'audits'

    id = db.Column(db.Integer, primary_key=True)
    entity_type = db.Column(db.String(50), nullable=False)
    entity_id = db.Column(db.Integer, nullable=False)
    action = db.Column(db.String(50), nullable=False)
    performed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    details = db.Column(db.Text)

    # Relationships
    user = db.relationship('User')

    @staticmethod
    def log(entity_type, entity_id, action, user_id, details=None):
        """Helper method to log audit entries"""
        audit = Audit(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            performed_by=user_id,
            details=details
        )
        db.session.add(audit)

    def __repr__(self):
        return f'<Audit {self.entity_type}:{self.entity_id} {self.action}>'