from datetime import timedelta
from flask import Flask, jsonify, render_template
from flask_restx import Api
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from dotenv import load_dotenv
import os

from init_db import get_db, init_app


authorizations ={
    'XApiKeyAuth': {
        'type': 'apiKey',
        'in': 'header',
        'name': 'X-API-KEY'
    },
    'accessTokenAuth': {
        'type':'apiKey',
        'in':'header',
        'name': 'X-CSRF-TOKEN'
    }
}

def create_app():
    app = Flask(__name__)

    app.config["RESTX_MASK_SWAGGER"] = False
    init_app(app)
    api = Api(app,
              doc='/docs' ,
              authorizations=authorizations,
              security=['XApiKeyAuth', 'accessTokenAuth'],
              title="LMS API Documentation",
              version="1.0.0",
              description="""
The **LMS API** provides endpoints for managing **courses**, **users**, **enrollments**, and **assessments** in the AMA Learning Management System (LMS).

---

## 🔐 Authentication

### 2️⃣ API Key Authentication

The API key is for **server-side requests only** — do **not** expose it on the client side.

Each key is tied to an LMS user account.

- [Sign in](http://10.10.2.197:8080/login) with an LMS admin account.
- [Generate an API Key](http://10.10.2.197:8080/dashboard/) after logging in.
- Save it securely (it’s only shown once).
- You can delete or regenerate keys anytime from your account.

#### ✅ Use via Header
Include the API key in the `X-API-KEY` header of your requests:
```
    X-API-KEY: sk_your_generated_api_key_here
```

#### 2️⃣ Cookie-Based JWT Authentication
For the API key generation and other endpoints, they uses cookie-based JWT authentication instead of X-API-KEY header.

- Log in via the `/api/auth/login` endpoint to receive JWT tokens set as secure cookies.
- Include the access token cookie in subsequent requests to authenticate.
- X-CSRF-TOKEN = access_token_cookie headers are use for jwt_required endpoints to protect against CSRF attacks.

### Structure

#### Every response is contained in a JSON object with the following structure:
```json
{
    "success": true,
    "message": "Descriptive message",
    "data_name": { ... } // Varies by endpoint
},200
```

#### error responses:
```json
{
    "success": false,
    "message": "Error description",
    "error": str(e)
},500
```

              """
              )


    # Load environment variables
    load_dotenv()
    CORS(app,
        supports_credentials=True,
        resources={r"/api/*": {"origins": os.getenv("CORS_ORIGIN")}},
    )
    # JWT Configuration
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'devsecret')
    app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET', 'devsecret')
    app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(minutes=int(os.getenv('JWT_EXP_MINUTES', 15)))
    app.config['JWT_REFRESH_TOKEN_EXPIRES'] = timedelta(days=int(os.getenv('REFRESH_EXP_DAYS', 7)))
    app.config['JWT_TOKEN_LOCATION'] = ['cookies']
    app.config['JWT_COOKIE_SECURE'] = True
    app.config['JWT_COOKIE_SAMESITE'] = 'None'  # Adjust as needed: 'Lax', 'Strict', or 'None'
    app.config['JWT_COOKIE_CSRF_PROTECT'] = True
    app.config["JWT_ACCESS_COOKIE_NAME"] = "access_token_cookie"
    app.config["JWT_REFRESH_COOKIE_NAME"] = "refresh_token_cookie"
    app.config["JWT_ACCESS_CSRF_COOKIE_NAME"] = "csrf_access_token"
    app.config["JWT_REFRESH_CSRF_COOKIE_NAME"] = "csrf_refresh_token"
    app.config['JWT_ALGORITHM'] = 'HS256'

    #ROUTES IMPORTS
    from routes.auth import auth_bp
    from routes.views import views
    from routes.courses import courses_ns
    from routes.assessment_scopes import assessment_scopes_ns
    from routes.course_instructors import course_instructors_ns
    from routes.exam_types import exam_types_ns
    from routes.modules import modules_ns
    from routes.assessment_preview import assessment_preview_ns
    from routes.dashboard import dashboard_ns
    from routes.enrollments import enrollments_ns
    from routes.database import database_ns
    from routes.users import users_ns
    from routes.api_key import api_key_ns

    #BLUEPRINTS & NAMESPACES
    app.register_blueprint(views)
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    api.add_namespace(courses_ns, path='/api/courses')
    api.add_namespace(assessment_scopes_ns, path='/api/assessment_scopes')
    api.add_namespace(course_instructors_ns, path='/api/course_instructors')
    api.add_namespace(exam_types_ns, path='/api/exam_types')
    api.add_namespace(modules_ns, path='/api/modules')
    api.add_namespace(assessment_preview_ns, path='/api/assessment_preview')
    api.add_namespace(dashboard_ns, path='/api/dashboard')
    api.add_namespace(enrollments_ns, path='/api/enrollments')
    api.add_namespace(database_ns, path='/api/database')
    api.add_namespace(users_ns, path='/api/users')
    api.add_namespace(api_key_ns, path='/api/api_key')

    # Initialize JWT Manager
    jwt = JWTManager(app)
    @jwt.token_in_blocklist_loader
    def check_if_token_revoked(jwt_header, jwt_payload):
        jti = jwt_payload.get("jti")
        try:
            db = get_db()
            with db.cursor() as cur:
                cur.execute("SELECT 1 FROM token_blocklist WHERE jti = %s", (jti,))
            return cur.fetchone() is not None
        except:
            return True  # fail-safe: block token if DB fails

    # --- Error Handlers ---
    @app.errorhandler(404)
    def not_found(e):
        return render_template('404.html'), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        return jsonify({'success': False, 'message': 'Method not allowed'}), 405

    @app.errorhandler(500)
    def internal_error(e):
        return jsonify({'success': False, 'message': 'Internal server error'}), 500

    # Production-specific error handler
    if os.getenv('FLASK_ENV') == 'production':
        @app.errorhandler(Exception)
        def handle_exception(e):
            app.logger.error(f"Unhandled exception: {str(e)}")
            return jsonify({"success": False, "message": "Internal server error"}), 500

    return app

