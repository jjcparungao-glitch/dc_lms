from flask import Blueprint, jsonify
from init_db import get_db
from utils import logger,api_key_required
dashboard_bp = Blueprint('dashboard', __name__)


@dashboard_bp.route('/stats', methods=['GET'])
@api_key_required
def get_dashboard_stats():
    try:
        db = get_db()
        with db.cursor() as cursor:

            cursor.execute("SELECT COUNT(*) as count FROM users")
            user_count = cursor.fetchone()['count']

            cursor.execute("SELECT COUNT(*) as count FROM courses_master")
            course_count = cursor.fetchone()['count']

            cursor.execute("SELECT COUNT(*) as count FROM course_instances")
            instance_count = cursor.fetchone()['count']

            cursor.execute("SELECT COUNT(*) as count FROM enrollments")
            enrollment_count = cursor.fetchone()['count']

        return jsonify({
            'success': True,
            'message': 'Dashboard stats fetched successfully',
            'user_count': user_count,
            'course_count': course_count,
            'instance_count': instance_count,
            'enrollment_count': enrollment_count
        })
    except Exception as e:
        logger.error(f"Error fetching dashboard stats: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'Error fetching dashboard stats',
            'error': str(e)
        }), 500
