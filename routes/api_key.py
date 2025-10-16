from datetime import datetime,timezone
import secrets
import bcrypt
from flask import Blueprint, request, jsonify
from init_db import get_db
from utils import logger
from flask_jwt_extended import get_jwt_identity, jwt_required

api_key_bp = Blueprint('api_key', __name__)

@api_key_bp.route('/generate', methods=['POST'])
@jwt_required()
def generate_api_key():
    try:
        data=request.get_json()
        name = data.get('name').strip()

        user_id = int(get_jwt_identity())
        db = get_db()
        with db.cursor() as cur:
            cur.execute("SELECT external_id, full_name, role FROM users WHERE user_id = %s", (user_id,))
            user = cur.fetchone()

            if user:
                secret_key = secrets.token_hex(32)
                prefix="sk_"
                api_key = f"{prefix}{secret_key}"
                hashed = bcrypt.hashpw(api_key.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                cur.execute(
                    "INSERT INTO api_keys (user_id, api_key, name, created_at) VALUES (%s, %s, %s, %s)",
                    (user_id, hashed, name, datetime.now(timezone.utc))
                )
                db.commit()
                return jsonify({'success': True, 'api_key': api_key}), 200
            else:
                return jsonify({'success': False, 'message': 'User not found'}), 404
    except Exception as e:
        logger.error(f"Error during API key generation: {str(e)}")
        return jsonify({'success': False, 'message': 'An error occurred during API key generation', 'error': str(e)}), 500



@api_key_bp.route('/list', methods=['GET'])
@jwt_required()
def list_api_keys():
    try:
        user_id = get_jwt_identity()
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT api_key_id, user_id, name, created_at FROM api_keys WHERE user_id = %s", (user_id,))
            api_keys = cursor.fetchall()

            if not api_keys:
                return jsonify({
                    'success': False,
                    'message': 'No API keys found',
                    'error': 'No API keys found'
                }), 404

            return jsonify({
                'success': True,
                'message': 'API keys fetched successfully',
                'data': api_keys
                }), 200
    except Exception as e:
        logger.error(f"Error listing API keys: {e}")
        return jsonify({
            'success': False,
            'message': 'Error fetching API keys',
            'error': str(e)
        }), 500


@api_key_bp.route('/delete/<int:api_key_id>', methods=['DELETE'])
@jwt_required()
def delete_api_key(api_key_id):
    try:
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT * FROM api_keys WHERE api_key_id = %s", (api_key_id,))
            existing = cursor.fetchone()
            if not existing:
                return jsonify({'success': False, 'message': 'API key not found', 'error': 'API key not found'}), 404

            cursor.execute("DELETE FROM api_keys WHERE api_key_id = %s", (api_key_id,))
            db.commit()
            return jsonify({'success': True, 'message': 'API key deleted successfully'}), 200
    except Exception as e:
        logger.error(f"Error deleting API key: {e}")
        return jsonify({
            'success': False,
            'message': 'Error deleting API key',
            'error': str(e)
        }), 500

@api_key_bp.route('/edit/<int:api_key_id>', methods=['PUT'])
@jwt_required()
def update_api_key(api_key_id):
    try:
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT * FROM api_keys WHERE api_key_id = %s", (api_key_id,))
            existing = cursor.fetchone()
            if not existing:
                return jsonify({'success': False, 'message': 'API key not found', 'error': 'API key not found'}), 404

            data = request.get_json()
            name = data.get('name', existing['name'])

            cursor.execute("UPDATE api_keys SET name = %s WHERE api_key_id = %s", (name, api_key_id))
            db.commit()
            return jsonify({'success': True, 'message': 'API key updated successfully'}), 200
    except Exception as e:
        logger.error(f"Error updating API key: {e}")
        return jsonify({
            'success': False,
            'message': 'Error updating API key',
            'error': str(e)
        }), 500
