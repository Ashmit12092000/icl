#!/usr/bin/env python3

from app import app
from database import db
from flask_migrate import upgrade

def create_migration():
    """Create database tables"""