
import datetime
import re, logging
from bcrypt import hashpw, gensalt, checkpw
from functools import wraps
from flask import g, jsonify, request
from flask_jwt_extended import decode_token, get_jwt, verify_jwt_in_request







logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def validate_email(email: str):
    if not email or not isinstance(email, str):
        return False, "Email is required"
    email = email.strip().lower()
    email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if re.match(email_regex, email):
        return True, None
    return False, "Invalid email"

def validate_password(password: str):
    if not isinstance(password, str) or len(password) < 8:
        return False, "Password must be at least 8 characters"
    if not re.search(r'[A-Z]', password): return False, "Password needs an uppercase letter"
    if not re.search(r'[a-z]', password): return False, "Password needs a lowercase letter"
    if not re.search(r'[0-9]', password): return False, "Password needs a digit"
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password): return False, "Password needs a special character"
    return True, None

def validate_status(status: str):
    if not status or not isinstance(status, str):
        return False, "Status is required"
    status = status.lower().strip()
    if status not in ['active', 'inactive']:
        return False, "Invalid status"
    return True, None

def hash_password(password: str) -> str:
    return hashpw(password.encode('utf-8'), gensalt()).decode('utf-8')

def verify_password(password: str, hashed_password: str) -> bool:
    try:
        return checkpw(password.encode('utf-8'), hashed_password.encode('utf-8'))
    except Exception as e:
        logger.error(f"Error verifying password: {e}")
        return False

def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            verify_jwt_in_request()
            claims = get_jwt()
            if claims.get("role") != "admin":
                return jsonify({
                    "success": False,
                    "message": "Admins only. Access denied."
                }), 403
        except Exception as e:
            return jsonify({
                "success": False,
                "message": f"Unauthorized: {str(e)}"
            }), 401

        return fn(*args, **kwargs)
    return wrapper


def sanitize_full_name(name):
    # Remove HTML tags
    name = re.sub(r'<.*?>', '', name)
    # Remove any script tags or suspicious input
    name = re.sub(r'(script|on\w+)', '', name, flags=re.IGNORECASE)
    # Limit to 100 characters
    name = name[:100]
    # Optionally, allow only letters, spaces, hyphens, apostrophes, and periods
    name = re.sub(r"[^a-zA-Z\s\-'.]", '', name)
    return name

# def store_token(token, user_id, db):
#     decoded = decode_token(token)
#     jti = decoded['jti']
#     # Ensure we store as timezone-aware datetime
#     expires = datetime.fromtimestamp(decoded['exp'], tz=datetime.timezone.utc)
#     with db.cursor() as cur:
#         cur.execute(
#             "INSERT INTO access_tokens (jti, user_id, token, expires_at) VALUES (%s, %s, %s, %s)",
#             (jti, user_id, token, expires)
#         )
#         db.commit()

# def is_token_valid(jti, db):
#     with db.cursor() as cur:
#         cur.execute(
#             "SELECT expires_at FROM access_tokens WHERE jti = %s", (jti,)
#         )
#         result = cur.fetchone()
#         if result:
#             expires_at = result['expires_at']
#             # Ensure both are timezone-aware for proper comparison
#             if expires_at.tzinfo is None:
#                 expires_at = expires_at.replace(tzinfo=datetime.timezone.utc)
#             return expires_at > datetime.now(datetime.timezone.utc)
#         return False

def api_key_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-KEY')
        if not api_key:
            return {'success': False, 'message': 'API key is missing'}, 401

        from init_db import get_db
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute('''
                SELECT ak.api_key AS hashed_api_key, ak.user_id, u.role, u.external_id, u.full_name
                FROM api_keys ak
                JOIN users u ON ak.user_id = u.user_id
            ''')
            rows = cursor.fetchall()

            matched = None
            for row in rows:
                stored = row.get('hashed_api_key') or row.get('api_key')
                try:
                    if stored and checkpw(api_key.encode('utf-8'), stored.encode('utf-8')):
                        matched = row
                        break
                except Exception:
                    continue

            if not matched:
                return {'success': False, 'message': 'Invalid API key'}, 403

            g.user_id = matched['user_id']
            g.role = matched['role']
            g.external_id = matched['external_id']
            g.full_name = matched['full_name']
            return f(*args, **kwargs)
    return decorated_function