from datetime import datetime,timezone
import secrets
import bcrypt
from flask import request
from flask_restx import Namespace, Resource, fields
from init_db import get_db
from utils import logger
from flask_jwt_extended import get_jwt_identity, jwt_required

api_key_ns = Namespace('api_key', description='API Key operations')

api_key_response = api_key_ns.model('ApiKeyResponse', {

    'success': fields.Boolean,
    'api_key': fields.String,
    'message': fields.String,
    'error': fields.String
})

api_key_list_response = api_key_ns.model('ApiKeyListResponse', {
    'success': fields.Boolean,
    'message': fields.String,
    'data': fields.List(fields.Raw),
    'error': fields.String
})

api_key_simple_response = api_key_ns.model('ApiKeySimpleResponse', {
    'success': fields.Boolean,
    'message': fields.String,
    'error': fields.String
})


@api_key_ns.route('/generate')
class GenerateApiKey(Resource):
    @api_key_ns.doc(description="Generate a new API key for the authenticated user.",
                    params={'name': 'API key name'}
                    )
    @jwt_required()
    @api_key_ns.marshal_with(api_key_response, code=200)
    def post(self):
        try:
            data = request.get_json()
            name = data.get('name').strip()
            user_id = int(get_jwt_identity())
            db = get_db()
            with db.cursor() as cur:
                cur.execute("SELECT external_id, full_name, role FROM users WHERE user_id = %s", (user_id,))
                user = cur.fetchone()
                if user:
                    secret_key = secrets.token_hex(32)
                    prefix = "sk_"
                    api_key = f"{prefix}{secret_key}"
                    hashed = bcrypt.hashpw(api_key.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                    cur.execute(
                        "INSERT INTO api_keys (user_id, api_key, name, created_at) VALUES (%s, %s, %s, %s)",
                        (user_id, hashed, name, datetime.now(timezone.utc))
                    )
                    db.commit()
                    return {'success': True, 'api_key': api_key, 'message': 'API key generated successfully'}, 200
                else:
                    return {'success': False, 'message': 'User not found'}, 404
        except Exception as e:
            logger.error(f"Error during API key generation: {str(e)}")
            return {'success': False, 'message': 'An error occurred during API key generation', 'error': str(e)}, 500


@api_key_ns.route('/list')
class ApiKeyList(Resource):
    @jwt_required()
    @api_key_ns.marshal_with(api_key_list_response, code=200)
    def get(self):
        try:
            user_id = get_jwt_identity()
            db = get_db()
            with db.cursor() as cursor:
                cursor.execute("SELECT api_key_id, user_id, name, created_at FROM api_keys WHERE user_id = %s", (user_id,))
                api_keys = cursor.fetchall()
                # Convert datetime fields to ISO format
                for key in api_keys:
                    if 'created_at' in key and isinstance(key['created_at'], datetime):
                        key['created_at'] = key['created_at'].isoformat()
                if not api_keys:
                    return {
                        'success': False,
                        'message': 'No API keys found',
                        'error': 'No API keys found',
                        'data': []
                    }, 404
                return {
                    'success': True,
                    'message': 'API keys fetched successfully',
                    'data': api_keys,
                    'error': None
                }, 200
        except Exception as e:
            logger.error(f"Error listing API keys: {e}")
            return {
                'success': False,
                'message': 'Error fetching API keys',
                'error': str(e),
                'data': []
            }, 500


@api_key_ns.route('/delete/<int:api_key_id>')
class ApiKeyDelete(Resource):
    @jwt_required()
    @api_key_ns.marshal_with(api_key_simple_response, code=200)
    def delete(self, api_key_id):
        try:
            db = get_db()
            with db.cursor() as cursor:
                cursor.execute("SELECT * FROM api_keys WHERE api_key_id = %s", (api_key_id,))
                existing = cursor.fetchone()
                if not existing:
                    return {'success': False, 'message': 'API key not found', 'error': 'API key not found'}, 404
                cursor.execute("DELETE FROM api_keys WHERE api_key_id = %s", (api_key_id,))
                db.commit()
                return {'success': True, 'message': 'API key deleted successfully', 'error': None}, 200
        except Exception as e:
            logger.error(f"Error deleting API key: {e}")
            return {'success': False, 'message': 'Error deleting API key', 'error': str(e)}, 500

@api_key_ns.route('/edit/<int:api_key_id>')
class ApiKeyEdit(Resource):
    @api_key_ns.doc(description="Edit the name of an existing API key.",
                    params={'name': 'New API key name'})
    @jwt_required()
    @api_key_ns.marshal_with(api_key_simple_response, code=200)
    def put(self, api_key_id):
        try:
            db = get_db()
            with db.cursor() as cursor:
                cursor.execute("SELECT * FROM api_keys WHERE api_key_id = %s", (api_key_id,))
                existing = cursor.fetchone()
                if not existing:
                    return {'success': False, 'message': 'API key not found', 'error': 'API key not found'}, 404
                data = request.get_json()
                name = data.get('name', existing['name'])
                cursor.execute("UPDATE api_keys SET name = %s WHERE api_key_id = %s", (name, api_key_id))
                db.commit()
                return {'success': True, 'message': 'API key updated successfully', 'error': None}, 200
        except Exception as e:
            logger.error(f"Error updating API key: {e}")
            return {'success': False, 'message': 'Error updating API key', 'error': str(e)}, 500
