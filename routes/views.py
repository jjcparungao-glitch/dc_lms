from flask import Blueprint, render_template, redirect, url_for
from flask_jwt_extended import get_jwt_identity, get_jwt, unset_jwt_cookies, verify_jwt_in_request

from init_db import get_db

views = Blueprint('views', __name__)

def current_user():
    try:
        # Will verify if a token is present; will not require one
        verify_jwt_in_request(optional=True)
        return get_jwt_identity(), get_jwt()
    except Exception:
        # Expired/invalid/missing token -> treat as anonymous
        return None, {}




@views.route('/')
def root():
    return redirect('/docs')


@views.route('/login')
def login():
    ident, claims = current_user()
    role = claims.get('role')
    if ident and role:
        if role == 'admin':
            return redirect(url_for('views.dashboard'))
        else:
            return render_template('login.html')
    return render_template('login.html')


@views.route('/dashboard')
def dashboard():
    ident, claims = current_user()
    role = claims.get('role')

    if ident and role:
        if role == 'admin':
            return render_template('dashboard.html', user=claims)
        else:
            resp = redirect(url_for('views.login'))
            return unset_jwt_cookies(resp)

    # not authenticated -> redirect to login page
    return redirect(url_for('views.login'))
