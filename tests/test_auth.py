"""
Unit tests for authentication functionality
"""

import pytest
from flask import url_for
from werkzeug.security import generate_password_hash
from models import User, UserRole, Department
from auth import role_required

class TestAuth:
    """Test authentication views and functions"""
    
    def test_login_page_get(self, client):
        """Test GET request to login page"""
        response = client.get('/auth/login')
        assert response.status_code == 200
        assert b'Sign in to your account' in response.data
        assert b'Username' in response.data
        assert b'Password' in response.data
    
    def test_login_successful(self, client, sample_user):
        """Test successful login"""
        response = client.post('/auth/login', data={
            'username': 'testuser',
            'password': 'password123'
        }, follow_redirects=True)
        
        assert response.status_code == 200
        # Should redirect to dashboard after successful login
        assert b'Dashboard' in response.data
    
    def test_login_invalid_username(self, client, sample_user):
        """Test login with invalid username"""
        response = client.post('/auth/login', data={
            'username': 'nonexistent',
            'password': 'password123'
        }, follow_redirects=True)
        
        assert response.status_code == 200
        assert b'Invalid username or password' in response.data
    
    def test_login_invalid_password(self, client, sample_user):
        """Test login with invalid password"""
        response = client.post('/auth/login', data={
            'username': 'testuser',
            'password': 'wrongpassword'
        }, follow_redirects=True)
        
        assert response.status_code == 200
        assert b'Invalid username or password' in response.data
    
    def test_login_missing_credentials(self, client):
        """Test login with missing credentials"""
        # Missing password
        response = client.post('/auth/login', data={
            'username': 'testuser'
        }, follow_redirects=True)
        
        assert response.status_code == 200
        assert b'Please provide both username and password' in response.data
        
        # Missing username
        response = client.post('/auth/login', data={
            'password': 'password123'
        }, follow_redirects=True)
        
        assert response.status_code == 200
        assert b'Please provide both username and password' in response.data
    
    def test_login_inactive_user(self, client, db):
        """Test login with inactive user"""
        user = User(
            username='inactive',
            password_hash=generate_password_hash('password123'),
            full_name='Inactive User',
            email='inactive@example.com',
            role=UserRole.EMPLOYEE,
            is_active=False
        )
        db.session.add(user)
        db.session.commit()
        
        response = client.post('/auth/login', data={
            'username': 'inactive',
            'password': 'password123'
        }, follow_redirects=True)
        
        assert response.status_code == 200
        assert b'Invalid username or password' in response.data
    
    def test_login_remember_me(self, client, sample_user):
        """Test login with remember me option"""
        response = client.post('/auth/login', data={
            'username': 'testuser',
            'password': 'password123',
            'remember': 'on'
        }, follow_redirects=True)
        
        assert response.status_code == 200
        # Should set remember me cookie (implementation specific)
    
    def test_login_redirect_to_next(self, client, sample_user):
        """Test login redirect to next parameter"""
        # Try to access protected page without login
        response = client.get('/masters/departments')
        assert response.status_code == 302
        
        # Login with next parameter
        response = client.post('/auth/login?next=/masters/departments', data={
            'username': 'testuser',
            'password': 'password123'
        }, follow_redirects=True)
        
        assert response.status_code == 200
        # Should redirect to the requested page after login
    
    def test_logout(self, client, logged_in_user):
        """Test logout functionality"""
        response = client.get('/auth/logout', follow_redirects=True)
        
        assert response.status_code == 200
        assert b'You have been logged out successfully' in response.data
        assert b'Sign in to your account' in response.data
    
    def test_logout_requires_login(self, client):
        """Test logout requires login"""
        response = client.get('/auth/logout')
        assert response.status_code == 302
        # Should redirect to login page
    
    def test_authenticated_user_redirected_from_login(self, client, logged_in_user):
        """Test authenticated user is redirected from login page"""
        response = client.get('/auth/login', follow_redirects=True)
        
        assert response.status_code == 200
        # Should redirect to dashboard
        assert b'Dashboard' in response.data

class TestRoleRequired:
    """Test role-based access control decorator"""
    
    def test_role_required_superadmin_access(self, client, db):
        """Test superadmin can access all role-restricted pages"""
        user = User(
            username='superadmin',
            password_hash=generate_password_hash('password123'),
            full_name='Super Admin',
            email='superadmin@example.com',
            role=UserRole.SUPERADMIN
        )
        db.session.add(user)
        db.session.commit()
        
        # Login as superadmin
        client.post('/auth/login', data={
            'username': 'superadmin',
            'password': 'password123'
        })
        
        # Should have access to admin pages
        response = client.get('/admin/users')
        assert response.status_code == 200
        
        # Should have access to network admin pages
        response = client.get('/masters/departments')
        assert response.status_code == 200
    
    def test_role_required_network_admin_access(self, client, db):
        """Test network admin access to appropriate pages"""
        user = User(
            username='netadmin',
            password_hash=generate_password_hash('password123'),
            full_name='Network Admin',
            email='netadmin@example.com',
            role=UserRole.NETWORK_ADMIN
        )
        db.session.add(user)
        db.session.commit()
        
        # Login as network admin
        client.post('/auth/login', data={
            'username': 'netadmin',
            'password': 'password123'
        })
        
        # Should have access to masters
        response = client.get('/masters/departments')
        assert response.status_code == 200
        
        # Should NOT have access to user management
        response = client.get('/admin/users', follow_redirects=True)
        assert response.status_code == 200
        assert b'You do not have permission' in response.data
    
    def test_role_required_hod_access(self, client, db, sample_department):
        """Test HOD access to appropriate pages"""
        user = User(
            username='hod',
            password_hash=generate_password_hash('password123'),
            full_name='HOD User',
            email='hod@example.com',
            role=UserRole.HOD,
            department_id=sample_department.id
        )
        db.session.add(user)
        db.session.flush()
        
        # Assign as HOD
        sample_department.hod_id = user.id
        db.session.commit()
        
        # Login as HOD
        client.post('/auth/login', data={
            'username': 'hod',
            'password': 'password123'
        })
        
        # Should have access to employee management
        response = client.get('/masters/employees')
        assert response.status_code == 200
        
        # Should have access to approvals
        response = client.get('/approvals/pending')
        assert response.status_code == 200
        
        # Should NOT have access to departments
        response = client.get('/masters/departments', follow_redirects=True)
        assert response.status_code == 200
        assert b'You do not have permission' in response.data
    
    def test_role_required_employee_access(self, client, db, sample_department):
        """Test employee access restrictions"""
        user = User(
            username='employee',
            password_hash=generate_password_hash('password123'),
            full_name='Employee User',
            email='employee@example.com',
            role=UserRole.EMPLOYEE,
            department_id=sample_department.id
        )
        db.session.add(user)
        db.session.commit()
        
        # Login as employee
        client.post('/auth/login', data={
            'username': 'employee',
            'password': 'password123'
        })
        
        # Should have access to dashboard
        response = client.get('/')
        assert response.status_code == 200 or response.status_code == 302
        
        # Should have access to own requests
        response = client.get('/requests/my-requests')
        assert response.status_code == 200
        
        # Should NOT have access to masters
        response = client.get('/masters/departments', follow_redirects=True)
        assert response.status_code == 200
        assert b'You do not have permission' in response.data
        
        # Should NOT have access to approvals
        response = client.get('/approvals/pending', follow_redirects=True)
        assert response.status_code == 200
        assert b'You do not have permission' in response.data
    
    def test_role_required_unauthenticated_user(self, client):
        """Test unauthenticated user is redirected to login"""
        response = client.get('/masters/departments')
        assert response.status_code == 302
        # Should redirect to login
        
        response = client.get('/admin/users')
        assert response.status_code == 302
        # Should redirect to login
    
    def test_role_required_multiple_roles(self, client, db):
        """Test decorator with multiple allowed roles"""
        # Create network admin
        user = User(
            username='netadmin',
            password_hash=generate_password_hash('password123'),
            full_name='Network Admin',
            email='netadmin@example.com',
            role=UserRole.NETWORK_ADMIN
        )
        db.session.add(user)
        db.session.commit()
        
        # Login
        client.post('/auth/login', data={
            'username': 'netadmin',
            'password': 'password123'
        })
        
        # Should have access to pages that allow network_admin
        response = client.get('/masters/departments')
        assert response.status_code == 200
    
    def test_role_required_with_string_role(self, client, sample_user_with_role):
        """Test role checking with string role values"""
        user = sample_user_with_role(UserRole.HOD)
        
        # Login
        client.post('/auth/login', data={
            'username': user.username,
            'password': 'password123'
        })
        
        # Test that role checking works with string values
        assert user.has_role('hod') is True
        assert user.has_role('employee') is False

class TestUserRoleHelpers:
    """Test user role helper methods"""
    
    def test_has_role_with_enum(self, sample_user):
        """Test has_role method with enum value"""
        sample_user.role = UserRole.HOD
        
        assert sample_user.has_role(UserRole.HOD) is True
        assert sample_user.has_role(UserRole.EMPLOYEE) is False
        assert sample_user.has_role(UserRole.SUPERADMIN) is False
    
    def test_has_role_with_string(self, sample_user):
        """Test has_role method with string value"""
        sample_user.role = UserRole.NETWORK_ADMIN
        
        assert sample_user.has_role('network_admin') is True
        assert sample_user.has_role('hod') is False
        assert sample_user.has_role('employee') is False
    
    def test_can_approve_for_department_non_hod(self, sample_user, sample_department):
        """Test non-HOD cannot approve for any department"""
        sample_user.role = UserRole.EMPLOYEE
        
        assert sample_user.can_approve_for_department(sample_department.id) is False
    
    def test_can_approve_for_department_hod_no_assignment(self, sample_user, sample_department):
        """Test HOD without department assignment cannot approve"""
        sample_user.role = UserRole.HOD
        # No managed_department relationship
        
        assert sample_user.can_approve_for_department(sample_department.id) is False
    
    def test_can_approve_for_department_hod_with_assignment(self, db, sample_department):
        """Test HOD with proper assignment can approve for their department"""
        user = User(
            username='hod_test',
            password_hash=generate_password_hash('password123'),
            full_name='HOD Test',
            email='hod@example.com',
            role=UserRole.HOD
        )
        db.session.add(user)
        db.session.flush()
        
        # Assign user as HOD
        sample_department.hod_id = user.id
        db.session.commit()
        
        assert user.can_approve_for_department(sample_department.id) is True
        assert user.can_approve_for_department(999) is False  # Wrong department
