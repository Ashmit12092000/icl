#!/usr/bin/env python3
"""
Database initialization script
This script will create all tables and default data
"""

from app import app, db
from models import User, Customer, Transaction, InterestRate, TDSRate
from werkzeug.security import generate_password_hash
from datetime import datetime, date
from decimal import Decimal

def init_database():
    """Initialize database with tables and default data"""
    
    with app.app_context():
        # Drop all tables and recreate (use with caution in production)
        db.drop_all()
        db.create_all()
        
        # Create default users
        users_data = [
            {
                'username': 'admin',
                'email': 'admin@example.com',
                'password': 'admin123',
                'role': 'admin'
            },
            {
                'username': 'dataentry',
                'email': 'dataentry@example.com',
                'password': 'dataentry123',
                'role': 'data_entry'
            },
            {
                'username': 'user',
                'email': 'user@example.com',
                'password': 'user123',
                'role': 'normal_user'
            }
        ]
        
        for user_data in users_data:
            user = User(
                username=user_data['username'],
                email=user_data['email'],
                password_hash=generate_password_hash(user_data['password']),
                role=user_data['role']
            )
            db.session.add(user)
        
        # Create default interest rate
        interest_rate = InterestRate(
            rate=Decimal('12.00'),
            effective_date=date.today(),
            description='Default Interest Rate',
            created_by=1,
            is_active=True
        )
        db.session.add(interest_rate)
        
        # Create default TDS rate
        tds_rate = TDSRate(
            rate=Decimal('10.00'),
            effective_date=date.today(),
            description='Default TDS Rate',
            created_by=1,
            is_active=True
        )
        db.session.add(tds_rate)
        
        try:
            db.session.commit()
            print("✅ Database initialized successfully!")
            print("Default users created:")
            print("  Admin: admin/admin123")
            print("  Data Entry: dataentry/dataentry123")
            print("  User: user/user123")
            print("Default rates created:")
            print("  Interest Rate: 12.00%")
            print("  TDS Rate: 10.00%")
            
        except Exception as e:
            db.session.rollback()
            print(f"❌ Error initializing database: {e}")

if __name__ == '__main__':
    init_database()
