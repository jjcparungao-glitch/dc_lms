from flask import Blueprint, request, jsonify, make_response
import csv
import io
from datetime import datetime
from init_db import get_db
from utils import logger, api_key_required

instances_bp = Blueprint('instances', __name__)

@instances_bp.route('/', methods=['GET'])
@api_key_required
def get_instances():
    try:
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 10))
        search = request.args.get('search', '')
        term_filter = request.args.get('term', '')
        sort_by = request.args.get('sort_by', 'created_at')
        sort_order = request.args.get('sort_order', 'desc')

        offset = (page - 1) * per_page

        db = get_db()
        with db.cursor() as cursor:
            # Build WHERE clause
            where_conditions = []
            params = []

            if search:
                    where_conditions.append("(cm.course_code LIKE %s OR cm.course_title LIKE %s OR ci.term_code LIKE %s)")
                    params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])

            if term_filter:
                where_conditions.append("ci.term_code = %s")
                params.append(term_filter)

                where_clause = " WHERE " + " AND ".join(where_conditions) if where_conditions else ""

                # Get total count
                count_query = f"""
                    SELECT COUNT(*) as total
                    FROM course_instances ci
                    JOIN courses_master cm ON ci.course_id = cm.course_id
                    {where_clause}
                """
                cursor.execute(count_query, params)
                total = cursor.fetchone()['total']

                # Get instances with pagination
                valid_sort_columns = ['course_code', 'course_title', 'term_code', 'start_date', 'end_date', 'created_at']
                if sort_by not in valid_sort_columns:
                    sort_by = 'created_at'
                if sort_order not in ['asc', 'desc']:
                    sort_order = 'desc'

                # Map sort columns to actual table columns
                sort_column_map = {
                    'course_code': 'cm.course_code',
                    'course_title': 'cm.course_title',
                    'term_code': 'ci.term_code',
                    'start_date': 'ci.start_date',
                    'end_date': 'ci.end_date',
                    'created_at': 'ci.created_at'
                }

                query = f"""
                    SELECT ci.instance_id, ci.course_id, ci.term_code, ci.start_date, ci.end_date, ci.created_at,
                           cm.course_code, cm.course_title
                    FROM course_instances ci
                    JOIN courses_master cm ON ci.course_id = cm.course_id
                    {where_clause}
                    ORDER BY {sort_column_map[sort_by]} {sort_order}
                    LIMIT %s OFFSET %s
                """
                params.extend([per_page, offset])

                cursor.execute(query, params)
                instances = cursor.fetchall()

                return jsonify({
                    'instances': instances,
                    'pagination': {
                        'page': page,
                        'per_page': per_page,
                        'total': total,
                        'pages': (total + per_page - 1) // per_page
                    }
                })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@instances_bp.route('/terms', methods=['GET'])
@api_key_required
def get_terms():
    try:
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT DISTINCT term_code FROM course_instances ORDER BY term_code DESC")
            terms = [row['term_code'] for row in cursor.fetchall()]
            return jsonify({'terms': terms})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@instances_bp.route('/courses', methods=['GET'])
@api_key_required
def get_available_courses():
    try:
        search = request.args.get('search', '')

        db = get_db()
        with db.cursor() as cursor:
            where_clause = ""
            params = []

            if search:
                    where_clause = "WHERE course_code LIKE %s OR course_title LIKE %s"
                    params = [f"%{search}%", f"%{search}%"]

            query = f"""
                    SELECT course_id, course_code, course_title
                    FROM courses_master
                    {where_clause}
                    ORDER BY course_code
                """

            cursor.execute(query, params)
            courses = cursor.fetchall()
            return jsonify({'courses': courses})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@instances_bp.route('/bulk-create', methods=['POST'])
@api_key_required
def bulk_create_instances():
    try:
        data = request.get_json()
        term_code = data.get('term_code')
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        course_ids = data.get('course_ids', [])

        if not term_code or not start_date or not end_date or not course_ids:
            return jsonify({'error': 'Term code, dates, and course selection required'}), 400

        db = get_db()
        created_count = 0
        errors = []

        with db.cursor() as cursor:
            for course_id in course_ids:
                try:
                    cursor.execute(
                        "INSERT INTO course_instances (course_id, term_code, start_date, end_date) VALUES (%s, %s, %s, %s)",
                            (course_id, term_code, start_date, end_date)
                        )
                    created_count += 1
                except Exception as e:
                        # Get course info for error message
                        cursor.execute("SELECT course_code FROM courses_master WHERE course_id = %s", (course_id,))
                        course = cursor.fetchone()
                        course_code = course['course_code'] if course else f"ID:{course_id}"
                        errors.append(f"{course_code}: {str(e)}")

            db.commit()


        return jsonify({
            'message': f'Course instances created successfully',
            'created': created_count,
            'errors': errors
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@instances_bp.route('/<int:instance_id>', methods=['PUT'])
@api_key_required
def update_instance(instance_id):
    try:
        data = request.get_json()
        term_code = data.get('term_code')
        start_date = data.get('start_date')
        end_date = data.get('end_date')

        db = get_db()
        with db.cursor() as cursor:
            # Check if instance exists
            cursor.execute("SELECT * FROM course_instances WHERE instance_id = %s", (instance_id,))
            existing_instance = cursor.fetchone()

            if not existing_instance:
                    return jsonify({'error': 'Course instance not found'}), 404

                # Build update query for changed fields only
            updates = []
            params = []

            if term_code and term_code != existing_instance['term_code']:
                updates.append("term_code = %s")
                params.append(term_code)
            if start_date and start_date != str(existing_instance['start_date']):
                updates.append("start_date = %s")
                params.append(start_date)
            if end_date and end_date != str(existing_instance['end_date']):
                updates.append("end_date = %s")
                params.append(end_date)

            if not updates:
                return jsonify({'message': 'Course instance updated successfully (no changes)'})

            params.append(instance_id)
            query = f"UPDATE course_instances SET {', '.join(updates)} WHERE instance_id = %s"
            cursor.execute(query, params)
            db.commit()

            return jsonify({'message': 'Course instance updated successfully'})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@instances_bp.route('/<int:instance_id>', methods=['DELETE'])
@api_key_required
def delete_instance(instance_id):
    try:
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("DELETE FROM course_instances WHERE instance_id = %s", (instance_id,))
            db.commit()

            if cursor.rowcount == 0:
                return jsonify({'error': 'Course instance not found'}), 404

            return jsonify({'message': 'Course instance deleted successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@instances_bp.route('/export-csv', methods=['GET'])
@api_key_required
def export_csv():
    try:
        db = get_db()
        with db.cursor() as cursor:
                cursor.execute("""
                    SELECT cm.course_code, cm.course_title, ci.term_code, ci.start_date, ci.end_date
                    FROM course_instances ci
                    JOIN courses_master cm ON ci.course_id = cm.course_id
                    ORDER BY ci.term_code DESC, cm.course_code
                """)
                instances = cursor.fetchall()

                output = io.StringIO()
                writer = csv.writer(output)

                # Write header
                writer.writerow(['course_code', 'course_title', 'term_code', 'start_date', 'end_date'])

                # Write data
                for instance in instances:
                    writer.writerow([
                        instance['course_code'],
                        instance['course_title'],
                        instance['term_code'],
                        instance['start_date'],
                        instance['end_date']
                    ])

                response = make_response(output.getvalue())
                response.headers['Content-Type'] = 'text/csv'
                response.headers['Content-Disposition'] = 'attachment; filename=course_instances.csv'
                return response
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@instances_bp.route('/<int:instance_id>', methods=['GET'])
@api_key_required
def get_single_instance_unique(instance_id):
    """Get a single course instance by ID"""
    try:
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("""
                SELECT ci.instance_id, ci.course_id, ci.term_code, ci.start_date, ci.end_date,
                       cm.course_code, cm.course_title, cm.description
                    FROM course_instances ci
                    JOIN courses_master cm ON ci.course_id = cm.course_id
                    WHERE ci.instance_id = %s
                """, (instance_id,))

            instance = cursor.fetchone()
            if not instance:
                return jsonify({'error': 'Course instance not found'}), 404

            return jsonify(instance)

            conn.close()

    except Exception as e:
        return jsonify({'error': str(e)}), 500
