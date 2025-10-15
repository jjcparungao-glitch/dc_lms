from flask import Blueprint, render_template, redirect, url_for
from flask_jwt_extended import get_jwt_identity, get_jwt, verify_jwt_in_request

from init_db import get_db

views = Blueprint('views', __name__)

def current_user():
    try:
        # Will verify if a token is present; will not require one
        verify_jwt_in_request(optional=True)
        return str(get_jwt_identity()), get_jwt()
    except Exception:
        # Expired/invalid/missing token -> treat as anonymous
        return None, {}

@views.route('/')
@views.route('/login')
def index():
    ident, claims = current_user()
    role = claims.get('role')
    if ident and role:
        if role == 'admin':
            return redirect(url_for('views.admin_dashboard'))
        elif role == 'user':
            return redirect(url_for('views.user_dashboard'))
    return render_template('index.html')

