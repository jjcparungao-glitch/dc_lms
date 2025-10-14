from datetime import timedelta
from flask import Flask, jsonify, render_template
from flask_jwt_extended import JWTManager
from dotenv import load_dotenv
import os

from init_db import init_app


def create_app():
    app = Flask(__name__)
    init_app(app)
    # Load environment variables
    load_dotenv()
    
    # JWT Configuration
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'devsecret')
    app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET', 'devsecret')
    app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(days=int(os.getenv('ACCESS_TOKEN_EXPIRES_DAYS', 1)))
    app.config['JWT_TOKEN_LOCATION'] = ['localstorage']
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

