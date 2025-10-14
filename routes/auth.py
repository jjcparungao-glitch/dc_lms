
from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token, decode_token, jwt_required, get_jwt_identity
import bcrypt

from init_db import get_db
from utils import store_token

auth_bp = Blueprint('auth', __name__)



@auth_bp.route('/login', methods=['POST'])
def login():
    print("Login endpoint triggered")
    try: 
        data = request.get_json()
        print(f"Received data: {data}")
        
        external_id = data.get('external_id')
        password = data.get('password')
        
        if not external_id or not password:
            return jsonify({'success': False, 'message': 'External ID and password are required'}), 400
        
        db = get_db()
        try:
            with db.cursor() as cur:
                cur.execute("SELECT user_id, password_hash, full_name, role FROM users WHERE external_id = %s", (external_id,))
                user = cur.fetchone()
                print(f"Database query result: {user}")
                
                if user:
                    password_match = bcrypt.checkpw(password.encode('utf-8'), user['password_hash'].encode('utf-8'))
                    print(f"Password match: {password_match}")
                    
                    if password_match:
                        token = create_access_token(identity=str(user['user_id']), additional_claims={'role': user['role']})
                        store_token(token, user['user_id'], db)
                        cur.execute(
                        '''SELECT count(*) AS token_count FROM access_tokens WHERE user_id = %s''',
                        (user['user_id'],)
                        )
                        token_count = cur.fetchone()['token_count']
                        print(f"User {user['user_id']} has {token_count} active tokens.")
                        
                        db.commit()
                        print ("Login successful, token created")
                        return jsonify({
                            'success': True,
                            'token': token,
                            'user': {
                                'user_id': user['user_id'],
                                'external_id': external_id,
                                'full_name': user['full_name'],
                                'role': user['role']
                            }
                        }), 200
                    else:
                        print("Invalid password")
                        return jsonify({'success': False, 'message': 'Invalid credentials'}), 401
                else:
                    print("User not found")
                    return jsonify({'success': False, 'message': 'Invalid credentials'}), 401
        finally:
            db.close()
    except Exception as e:
        print(f"Error during login: {str(e)}")
        return jsonify({'success': False, 'message': 'An error occurred during login'}), 500
    
@auth_bp.route('/logout', methods=['POST'])
@jwt_required()
def Logout():
    return jsonify({'success': True, 'message': 'Logout successful'}), 200

@auth_bp.route('/verify', methods=['GET'])
@jwt_required()
def verify():
    try:
        user_id = int(get_jwt_identity())
        db = get_db()
        try:
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
        finally:
            db.close()
    except Exception as e:
        print(f"Error during token verification: {str(e)}")
        return jsonify({'success': False, 'message': 'An error occurred during token verification'}), 500
    
    