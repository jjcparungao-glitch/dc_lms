from flask import Blueprint, request, jsonify
from init_db import get_db
from utils import logger, api_key_required

course_instructors_bp = Blueprint('course_instructors', __name__)

@course_instructors_bp.route('/instructors', methods=['GET'])
@api_key_required
def get_course_instructors():
    try:
        db = get_db()
        with db.cursor() as cursor:
            search_term = request.args.get('search', '').strip()
            instance_filter = request.args.get('instance_id', '').strip()
            role_filter = request.args.get('role', '').strip().lower()

            where_clauses = []
            params = []

            if search_term:
                where_clauses.append("(u.full_name LIKE %s OR cm.course_code LIKE %s OR cm.course_title LIKE %s)")
                search_param = f"%{search_term}%"
                params.extend([search_param, search_param, search_param])
            if instance_filter:
                where_clauses.append("ci_inst.instance_id = %s")
                params.append(instance_filter)
            if role_filter:
                where_clauses.append("ci_inst.role = %s")
                params.append(role_filter)

            where_clause = " AND ".join(where_clauses)
            if where_clause:
                where_clause = "WHERE " + where_clause

            # Use parameterized query instead of f-string for security
            query = """
                SELECT
                    ci_inst.course_instructor_id,
                    ci_inst.instance_id,
                    ci_inst.user_id,
                    ci_inst.role,
                    ci_inst.created_at,
                    u.full_name as instructor_name,
                    u.external_id as instructor_external_id,
                    cm.course_code,
                    cm.course_title,
                    ci.term_code,
                    ci.start_date,
                    ci.end_date
                FROM course_instructors ci_inst
                JOIN users u ON ci_inst.user_id = u.user_id
                JOIN course_instances ci ON ci_inst.instance_id = ci.instance_id
                JOIN courses_master cm ON ci.course_id = cm.course_id
                {where_clause}
                ORDER BY cm.course_code, ci.term_code, ci_inst.role, u.full_name
            """.format(where_clause=where_clause)

            cursor.execute(query, params)
            instructors = cursor.fetchall()

            return jsonify({'success': True, 'instructors': instructors, 'total': len(instructors)}), 200
    except Exception as e:
        logger.error(f"Error fetching course instructors: {e}")
        return jsonify({"success": False, "error": "Internal server error"}), 500

@course_instructors_bp.route('/instructors', methods=['POST'])
@api_key_required
def create_course_instructor_assignment():
    try:
        data = request.get_json()

        required_fields = ['instance_id', 'user_id']
        for field in required_fields:
            if field not in data:
                return jsonify({'success': False, 'message': f'Missing required field: {field}', 'error': f'Missing required field: {field}'}), 400

        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("""
                SELECT role FROM users WHERE user_id = %s
            """, (data['user_id'],))
            user = cursor.fetchone()
            if not user or user['role'] != 'instructor':
                return jsonify({'success': False, 'message': 'User must have instructor role', 'error': 'User must have instructor role'}), 400

            cursor.execute("""
                SELECT course_instructor_id FROM course_instructors
                WHERE instance_id = %s AND user_id = %s
            """, (data['instance_id'], data['user_id']))
            existing = cursor.fetchone()
            if existing:
                return jsonify({'success': False, 'message': 'Instructor already assigned to this course instance', 'error': 'Instructor already assigned to this course instance'}), 400

            cursor.execute("""
                INSERT INTO course_instructors (instance_id, user_id, role)
                VALUES (%s, %s, %s)
            """, (data['instance_id'], data['user_id'], user['role']))
            db.commit()
            return jsonify({
                'success': True,
                'message': 'Instructor assigned successfully',
                'course_instructor_id': cursor.lastrowid
            }), 201
    except Exception as e:
        logger.error(f"Error creating course instructor assignment: {e}")
        return jsonify({"success": False, 'message': 'Error creating course instructor assignment', "error": str(e)}), 500

@course_instructors_bp.route('/instructors/<int:course_instructor_id>', methods=['PUT'])
@api_key_required
def update_course_instructor_assignment(course_instructor_id):
    try:
        data = request.get_json()
        role = data.get('role', '').strip().lower()

        if 'role' not in data:
            return jsonify({'success': False, 'message': 'Missing required field: role', 'error': 'Missing required field: role'}), 400

        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("""
                SELECT * FROM course_instructors
                WHERE course_instructor_id = %s
            """, (course_instructor_id,))
            existing = cursor.fetchone()
            if not existing:
                return jsonify({'success': False, 'message': 'Course instructor assignment not found', 'error': 'Course instructor assignment not found'}), 404

            cursor.execute("""
                UPDATE course_instructors
                SET role = %s
                WHERE course_instructor_id = %s
            """, (role, course_instructor_id))
            db.commit()
            return jsonify({'success': True, 'message': 'Course instructor assignment updated successfully'}), 200
    except Exception as e:
        logger.error(f"Error updating course instructor assignment: {e}")
        return jsonify({"success": False, "message": 'Error updating course instructor assignment', "error": str(e)}), 500

@course_instructors_bp.route('/instructors/<int:course_instructor_id>', methods=['DELETE'])
@api_key_required
def delete_course_instructor_assignment(course_instructor_id):
    try:
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("""
                SELECT * FROM course_instructors
                WHERE course_instructor_id = %s
            """, (course_instructor_id,))
            existing = cursor.fetchone()
            if not existing:
                return jsonify({'success': False, 'message': 'Course instructor assignment not found', 'error': 'Course instructor assignment not found'}), 404

            cursor.execute("""
                DELETE FROM course_instructors
                WHERE course_instructor_id = %s
            """, (course_instructor_id,))
            db.commit()
            return jsonify({'success': True, 'message': 'Course instructor assignment deleted successfully'}), 200
    except Exception as e:
        logger.error(f"Error deleting course instructor assignment: {e}")
        return jsonify({"success": False, "message": 'Error deleting course instructor assignment', "error": str(e)}), 500

@course_instructors_bp.route('/available-teachers', methods=['GET'])
@api_key_required
def get_available_teachers():
    try:
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("""
                           SELECT user_id, full_name, external_id
                            FROM users
                            WHERE role = 'teacher'
                            ORDER BY full_name
                           """)
            teachers = cursor.fetchall()
            return jsonify({'success': True, 'teachers': teachers}), 200
    except Exception as e:
        logger.error(f"Error fetching available teachers: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@course_instructors_bp.route('/available-instances', methods=['GET'])
@api_key_required
def get_available_course_instances():
    try:
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("""
                            SELECT
                            ci.instance_id,
                            ci.term_code,
                            ci.start_date,
                            ci.end_date,
                            cm.course_code,
                            cm.course_title
                            FROM course_instances ci
                            JOIN courses_master cm ON ci.course_id = cm.course_id
                            ORDER BY cm.course_code, ci.term_code
                           """)
            instances = cursor.fetchall()
            return jsonify({'success': True, 'instances': instances}), 200
    except Exception as e:
        logger.error(f"Error fetching available course instances: {e}")
        return jsonify({"success": False, "error": str(e)}), 500