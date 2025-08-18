from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SelectField, IntegerField, PasswordField, BooleanField, HiddenField
from wtforms.validators import DataRequired, Length, Optional, NumberRange, Email
from wtforms.widgets import TextArea
from models import Department, Employee, Location, Item, User
from database import db

class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=64)])
    password = PasswordField('Password', validators=[DataRequired()])

class ItemForm(FlaskForm):
    code = StringField('Item Code', validators=[DataRequired(), Length(max=50)])
    name = StringField('Item Name', validators=[DataRequired(), Length(max=200)])
    make = StringField('Make', validators=[Optional(), Length(max=100)])
    variant = StringField('Variant', validators=[Optional(), Length(max=100)])
    description = TextAreaField('Description', validators=[Optional()])
    low_stock_threshold = IntegerField('Low Stock Threshold', validators=[DataRequired(), NumberRange(min=0)], default=5)

class DepartmentForm(FlaskForm):
    code = StringField('Department Code', validators=[DataRequired(), Length(max=20)])
    name = StringField('Department Name', validators=[DataRequired(), Length(max=100)])
    hod_id = SelectField('Head of Department (Optional)', coerce=int, validators=[Optional()])

    def __init__(self, *args, **kwargs):
        super(DepartmentForm, self).__init__(*args, **kwargs)
        hod_users = User.query.filter_by(role='hod').all()
        if hod_users:
            self.hod_id.choices = [(0, 'No HOD Assigned')] + [(u.id, f"{u.username} ({u.email})") for u in hod_users]
        else:
            self.hod_id.choices = [(0, 'No HOD users available - Create HOD users first')]

class EmployeeForm(FlaskForm):
    emp_id = StringField('Employee ID', validators=[DataRequired(), Length(max=20)])
    name = StringField('Employee Name', validators=[DataRequired(), Length(max=100)])
    department_id = SelectField('Department', coerce=int, validators=[DataRequired()])
    user_id = SelectField('User Account', coerce=int, validators=[Optional()])

    def __init__(self, *args, **kwargs):
        super(EmployeeForm, self).__init__(*args, **kwargs)
        self.department_id.choices = [(d.id, f"{d.code} - {d.name}") for d in Department.query.filter_by(is_active=True).all()]
        self.user_id.choices = [(0, 'No User Account')] + [(u.id, f"{u.username} ({u.email})") for u in User.query.filter_by(is_active=True).all()]

class LocationForm(FlaskForm):
    office = StringField('Office', validators=[DataRequired(), Length(max=100)])
    room_store = StringField('Room/Store', validators=[DataRequired(), Length(max=100)])

class StockEntryForm(FlaskForm):
    item_id = SelectField('Item', coerce=int, validators=[DataRequired()])
    location_id = SelectField('Location', coerce=int, validators=[DataRequired()])
    quantity_procured = IntegerField('Quantity Procured', validators=[DataRequired(), NumberRange(min=1)])
    description = TextAreaField('Description', validators=[Optional()])
    remarks = TextAreaField('Remarks', validators=[Optional()])

    def __init__(self, *args, **kwargs):
        super(StockEntryForm, self).__init__(*args, **kwargs)
        self.item_id.choices = [(i.id, f"{i.code} - {i.name}") for i in Item.query.filter_by(is_active=True).all()]
        self.location_id.choices = [(l.id, str(l)) for l in Location.query.filter_by(is_active=True).all()]

class StockIssueRequestForm(FlaskForm):
    requester_id = SelectField('Requester', coerce=int, validators=[DataRequired()])
    department_id = SelectField('Department', coerce=int, validators=[DataRequired()])
    purpose = TextAreaField('Purpose', validators=[DataRequired()])
    approval_flow = SelectField('Approval Flow', choices=[('regular', 'Regular'), ('alternate', 'Alternate')], default='regular')
    approver_id = SelectField('Approver (for Alternate Flow)', coerce=int, validators=[Optional()])


    def __init__(self, user=None, *args, **kwargs):
        super(StockIssueRequestForm, self).__init__(*args, **kwargs)

        # Filter requesters and departments based on user role and department
        if user and user.is_authenticated:
            user_employee = Employee.query.filter_by(user_id=user.id).first()

            if user.role == 'admin':
                # Admin can select any requester and department
                self.requester_id.choices = [(e.id, f"{e.emp_id} - {e.name}") for e in Employee.query.filter_by(is_active=True).all()]
                self.department_id.choices = [(d.id, f"{d.code} - {d.name}") for d in Department.query.filter_by(is_active=True).all()]
            elif user_employee:
                # Regular employees can only create requests for themselves and their department
                self.requester_id.choices = [(user_employee.id, f"{user_employee.emp_id} - {user_employee.name}")]
                self.department_id.choices = [(user_employee.department.id, f"{user_employee.department.code} - {user_employee.department.name}")]
            else:
                # No employee record - no options
                self.requester_id.choices = []
                self.department_id.choices = []
        else:
            # Default - all options
            self.requester_id.choices = [(e.id, f"{e.emp_id} - {e.name}") for e in Employee.query.filter_by(is_active=True).all()]
            self.department_id.choices = [(d.id, f"{d.code} - {d.name}") for d in Department.query.filter_by(is_active=True).all()]

        # Set approver choices (users with hod or admin role)
        approver_users = User.query.filter(User.role.in_(['hod', 'admin']), User.is_active == True).all()
        self.approver_id.choices = [(0, 'Select Approver')] + [(u.id, f"{u.username} ({u.email})") for u in approver_users]



class StockIssueItemForm(FlaskForm):
    item_id = SelectField('Item', coerce=int, validators=[DataRequired()])
    location_id = SelectField('Location', coerce=int, validators=[DataRequired()])
    quantity_requested = IntegerField('Quantity', validators=[DataRequired(), NumberRange(min=1)])
    description = TextAreaField('Description', validators=[Optional()])

    def __init__(self, user=None, *args, **kwargs):
        super(StockIssueItemForm, self).__init__(*args, **kwargs)
        self.item_id.choices = [(i.id, f"{i.code} - {i.name}") for i in Item.query.filter_by(is_active=True).all()]

        # Filter locations based on user's assigned warehouses
        if user and user.is_authenticated:
            if user.role in ['admin', 'superadmin']:
                # Admin can see all locations
                allowed_locations = Location.query.all()
            else:
                # Users can only see their assigned warehouses
                allowed_locations = user.get_accessible_warehouses()
        else:
            allowed_locations = Location.query.all()

        self.location_id.choices = [(l.id, f"{l.office} - {l.room_store}") for l in allowed_locations]

class UserForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=80)])
    full_name = StringField('Full Name', validators=[DataRequired(), Length(max=100)])
    email = StringField('Email', validators=[DataRequired(), Email(), Length(max=120)])
    role = SelectField('Role', choices=[
        ('employee', 'Employee'),
        ('hod', 'Head of Department'),
        ('manager', 'Manager'),
        ('superadmin', 'Super Administrator')
    ], validators=[DataRequired()])
    department_id = SelectField('Department', coerce=int, validators=[Optional()])
    employee_id = SelectField('Link to Employee', coerce=int, validators=[Optional()])
    is_active = BooleanField('Active', default=True)
    password = PasswordField('Password', validators=[Optional(), Length(min=6)])

    def __init__(self, *args, **kwargs):
        super(UserForm, self).__init__(*args, **kwargs)
        # Load departments for selection
        self.department_id.choices = [(0, 'No Department')] + [(d.id, f"{d.code} - {d.name}") for d in Department.query.filter_by(is_active=True).all()]
        # Load employees that don't have user accounts
        unassigned_employees = Employee.query.filter_by(user_id=None).all()
        self.employee_id.choices = [(0, 'No Employee Link')] + [(e.id, f"{e.emp_id} - {e.name}") for e in unassigned_employees]

class ApprovalForm(FlaskForm):
    action = HiddenField('Action')
    rejection_reason = TextAreaField('Rejection Reason', validators=[Optional()])