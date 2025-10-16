from flask import Blueprint, request, jsonify
import bcrypt
import csv
import io

from init_db import get_db
from utils import logger, api_key_required

users_bp = Blueprint('users', __name__)

@users_bp.route('/', methods=['GET'])
@api_key_required
def get_users():
    try:
        logger.info("Getting users...")
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT user_id, external_id, full_name, role, created_at FROM users ORDER BY created_at DESC")
            users = cursor.fetchall()
            logger.info(f"Found {len(users)} users")
            return jsonify({'users': users}), 200
    except Exception as e:
        logger.error(f"Error getting users: {e}")
        return jsonify({'error': str(e)}), 500

@users_bp.route('/', methods=['POST'])
@api_key_required
def create_user():
    try:
        print("Creating user...")
        data = request.get_json()
        print(f"Request data: {data}")

        external_id = data.get('external_id')
        password = data.get('password', '1234')
        full_name = data.get('full_name')
        role = data.get('role', 'student')

        if not external_id or not full_name:
            return jsonify({'error': 'External ID and full name required'}), 400

        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

        db = get_db()
        with db.cursor() as cursor:
            cursor.execute(
                "INSERT INTO users (external_id, password_hash, full_name, role) VALUES (%s, %s, %s, %s)",
                (external_id, password_hash, full_name, role)
            )
            db.commit()
            logger.info("User created successfully")
            return jsonify({'message': 'User created successfully'}), 201
    except Exception as e:
        logger.error(f"Error creating user: {e}")
        return jsonify({'error': str(e)}), 500
    except Exception as e:
        print(f"Error creating user: {e}")
        return jsonify({'error': str(e)}), 500

@users_bp.route('/<int:user_id>', methods=['PUT'])
@api_key_required
def update_user(user_id):
    try:
        print(f"Updating user ID: {user_id}")
        data = request.get_json()
        print(f"Update data: {data}")

        external_id = data.get('external_id')
        full_name = data.get('full_name')
        role = data.get('role')
        password = data.get('password')

        db = get_db()
        with db.cursor() as cursor:
            # Check if user exists first
            cursor.execute("SELECT user_id, external_id, full_name, role FROM users WHERE user_id = %s", (user_id,))
            existing_user = cursor.fetchone()
            logger.info(f"Existing user: {existing_user}")

            if not existing_user:
                return jsonify({'error': 'User not found'}), 404

                # Build dynamic update query only for changed fields
            updates = []
            params = []

            if external_id and external_id != existing_user['external_id']:
                updates.append("external_id = %s")
                params.append(external_id)
            if full_name and full_name != existing_user['full_name']:
                updates.append("full_name = %s")
                params.append(full_name)
            if role and role != existing_user['role']:
                updates.append("role = %s")
                params.append(role)
            if password:
                password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                updates.append("password_hash = %s")
                params.append(password_hash)

            if not updates:
                # No changes needed, but still return success
                return jsonify({'message': 'User updated successfully (no changes)'})

            params.append(user_id)
            query = f"UPDATE users SET {', '.join(updates)} WHERE user_id = %s"
            logger.info(f"Update query: {query}")
            logger.info(f"Update params: {params}")

            cursor.execute(query, params)
            db.commit()

            logger.info(f"Rows affected: {cursor.rowcount}")
            return jsonify({'message': 'User updated successfully'})

    except Exception as e:
        logger.error(f"Update user error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@users_bp.route('/<int:user_id>', methods=['DELETE'])
@api_key_required
def delete_user(user_id):
    try:
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("DELETE FROM users WHERE user_id = %s", (user_id,))
            db.commit()

            if cursor.rowcount == 0:
                return jsonify({'error': 'User not found'}), 404

            return jsonify({'message': 'User deleted successfully'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@users_bp.route('/upload-csv', methods=['POST'])
@api_key_required
def upload_csv():
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400

        if not file.filename.endswith('.csv'):
            return jsonify({'error': 'File must be CSV format'}), 400

        # Read CSV content
        stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
        csv_input = csv.DictReader(stream)

        db = get_db()
        created_count = 0
        errors = []

        with db.cursor() as cursor:
                for row_num, row in enumerate(csv_input, start=2):
                    try:
                        external_id = row.get('external_id', '').strip()
                        full_name = row.get('full_name', '').strip()
                        role = row.get('role', 'student').strip()
                        password = row.get('password', '1234').strip()

                        if not external_id or not full_name:
                            errors.append(f"Row {row_num}: Missing external_id or full_name")
                            continue

                        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

                        cursor.execute(
                            "INSERT INTO users (external_id, password_hash, full_name, role) VALUES (%s, %s, %s, %s)",
                            (external_id, password_hash, full_name, role)
                        )
                        created_count += 1

                    except Exception as e:
                        errors.append(f"Row {row_num}: {str(e)}")

                db.commit()


        return jsonify({
            'success': True,
            'message': f'CSV processed successfully',
            'created': created_count,
            'errors': errors
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500
