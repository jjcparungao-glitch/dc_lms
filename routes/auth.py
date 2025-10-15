
from asyncio.log import logger
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token, create_refresh_token, decode_token, get_jwt, jwt_required, get_jwt_identity, set_access_cookies, set_refresh_cookies, unset_jwt_cookies
import bcrypt

from init_db import get_db

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        external_id = data.get('external_id')
        password = data.get('password')

        if not external_id or not password:
            return jsonify({'success': False, 'message': 'External ID and password are required'}), 400

        db = get_db()
        with db.cursor() as cur:
            cur.execute("SELECT user_id, password_hash, full_name, role FROM users WHERE external_id = %s", (external_id,))
            user = cur.fetchone()

            if user and bcrypt.checkpw(password.encode('utf-8'), user['password_hash'].encode('utf-8')):
                # Create new token
                access_token = create_access_token(
                    identity=str(user['user_id']),
                    additional_claims={
                        'role': user['role'],
                        'external_id': external_id,
                        'full_name': user['full_name']}
                )
                refresh_token = create_refresh_token(
                    identity=str(user['user_id']),
                    additional_claims={
                        'role': user['role'],
                        'external_id': external_id,
                        'full_name': user['full_name']
                    }
                )
                resp = jsonify({'success': True, 'message': 'Login successful'})
                set_access_cookies(resp, access_token)
                set_refresh_cookies(resp, refresh_token)
                return resp, 200
            else:
                return jsonify({'success': False, 'message': 'Invalid credentials', 'error': 'Invalid credentials'}), 401
    except Exception as e:
        logger.error(f"Error during login: {str(e)}")
        return jsonify({'success': False, 'message': 'An error occurred during login', 'error': str(e)}), 500


@auth_bp.route('/refresh', methods=['POST'])
@jwt_required(refresh=True)
def refresh():
    try:
        ident = str(get_jwt_identity())
        claims = get_jwt()
        role = claims.get('role')
        external_id = claims.get('external_id')
        full_name = claims.get('full_name')

        logger.info(f"Refreshing token for user {ident} with role {role}")
        new_access = create_access_token(identity=ident, additional_claims={'role': role, 'external_id': external_id, 'full_name': full_name})
        resp = jsonify({'success': True, 'message': 'Token refreshed'})
        set_access_cookies(resp, new_access)

        return resp, 200
    except Exception as e:
        logger.error(f"Token refresh failed: {str(e)}")
        return jsonify({'success': False, 'message': 'Token refresh failed', 'error': str(e)}), 500

@auth_bp.route('/logout', methods=['POST'])
@jwt_required()
def logout():
    try:
        j = get_jwt()
        db = get_db()
        with db.cursor() as cur:
                cur.execute(
                    "INSERT IGNORE INTO token_blocklist (jti, type, expires_at) VALUES (%s, %s, %s)",
                    (j['jti'], j['type'], datetime.fromtimestamp(j['exp'], tz=timezone.utc))
                )
                db.commit()
        resp = jsonify({'success': True, 'message': 'Logout successful'})
        unset_jwt_cookies(resp)
        return resp, 200
    except Exception as e:
        logger.error(f"Error during logout: {str(e)}")
        return jsonify({'success': False, 'message': 'An error occurred during logout', 'error': str(e)}), 500


@auth_bp.route('/verify', methods=['GET'])
@jwt_required()
def verify():
    try:
        user_id = int(get_jwt_identity())
        db = get_db()
        with db.cursor() as cur:
                cur.execute("SELECT user_id, external_id, full_name, role FROM users WHERE user_id = %s", (user_id,))
                user = cur.fetchone()

                if user:
                    return jsonify({
                        'success': True,
                        'user': {
                            'user_id': user['user_id'],
                            'external_id': user['external_id'],
                            'full_name': user['full_name'],
                            'role': user['role']
                        }
                    }), 200
                else:
                    return jsonify({'success': False, 'message': 'User not found'}), 404
    except Exception as e:
        logger.error(f"Error during token verification: {str(e)}")
        return jsonify({'success': False, 'message': 'An error occurred during token verification', 'error': str(e)}), 500

