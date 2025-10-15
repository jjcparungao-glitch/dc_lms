from datetime import timedelta
from flask import Flask, jsonify, render_template
from flask_jwt_extended import JWTManager
from dotenv import load_dotenv
import os

from init_db import get_db, init_app


def create_app():
    app = Flask(__name__)
    init_app(app)
    # Load environment variables
    load_dotenv()

    # JWT Configuration
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'devsecret')
    app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET', 'devsecret')
    app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(minutes=int(os.getenv('JWT_EXP_MINUTES', 15)))
    app.config['JWT_REFRESH_TOKEN_EXPIRES'] = timedelta(days=int(os.getenv('REFRESH_EXP_DAYS', 7)))
    app.config['JWT_TOKEN_LOCATION'] = ['cookies']
    app.config['JWT_COOKIE_SECURE'] = False
    app.config['JWT_COOKIE_SAMESITE'] = 'Lax'
    app.config['JWT_COOKIE_CSRF_PROTECT'] = True
    app.config["JWT_ACCESS_COOKIE_NAME"] = "access_token_cookie"
    app.config["JWT_REFRESH_COOKIE_NAME"] = "refresh_token_cookie"
    app.config["JWT_ACCESS_CSRF_COOKIE_NAME"] = "csrf_access_token"
    app.config["JWT_REFRESH_CSRF_COOKIE_NAME"] = "csrf_refresh_token"
    app.config['JWT_ALGORITHM'] = 'HS256'

    #ROUTES IMPORTS
    from routes.auth import auth_bp
    from routes.views import views
    from routes.courses import courses_bp
    from routes.assessment_scopes import assessment_scopes_bp
    from routes.course_instructors import course_instructors_bp
    from routes.exam_types import exam_types_bp
    from routes.modules import modules_bp
    from routes.assessment_preview import assessment_preview_bp
    from routes.dashboard import dashboard_bp
    from routes.enrollments import enrollments_bp
    from routes.database import database_bp



    #BLUEPRINTS
    app.register_blueprint(views, url_prefix='/')
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(courses_bp, url_prefix='/api/courses')
    app.register_blueprint(assessment_scopes_bp, url_prefix='/api/assessment_scopes')
    app.register_blueprint(course_instructors_bp, url_prefix='/api/course_instructors')
    app.register_blueprint(exam_types_bp, url_prefix='/api/exam_types')
    app.register_blueprint(modules_bp, url_prefix='/api/modules')
    app.register_blueprint(assessment_preview_bp, url_prefix='/api/assessment_preview')
    app.register_blueprint(dashboard_bp, url_prefix='/api/dashboard')
    app.register_blueprint(enrollments_bp, url_prefix='/api/enrollments')
    app.register_blueprint(database_bp, url_prefix='/api/database')


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

# --- Register Blueprints ---
    from routes.auth import auth
    app.register_blueprint(auth, url_prefix='/api/auth')

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

