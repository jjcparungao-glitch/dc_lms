from flask import Blueprint, request, jsonify, make_response
import csv
import io
from init_db import get_db
from utils import logger, api_key_required

courses_bp = Blueprint('courses', __name__)

@courses_bp.route('/', methods=['GET'])
@api_key_required
def get_courses():
    try:
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 10))
        search = request.args.get('search', '').strip()
        sort_by = request.args.get('sort_by', 'created_at')
        sort_order = request.args.get('sort_order', 'desc').lower()

        offset = (page - 1) * per_page

        db = get_db()
        with db.cursor() as cursor:
            where_conditions = []
            params = []
            if search:
                where_conditions.append("(course_code LIKE %s OR course_title LIKE %s)")
                search_param = f"%{search}%"
                params.extend([search_param, search_param])

            where_clause = " WHERE " + " AND ".join(where_conditions) if where_conditions else ""


            count_query = f"SELECT COUNT(*) as total FROM courses_master {where_clause}"
            cursor.execute(count_query, params)
            total = cursor.fetchone()['total']

            valid_sort_columns = ['course_code', 'course_title', 'created_at']
            if sort_by not in valid_sort_columns:
                sort_by = 'created_at'
            if sort_order not in ['asc', 'desc']:
                sort_order = 'desc'


            query = f"""
                SELECT course_id, course_code, course_title, description, created_at
                FROM courses_master
                {where_clause}
                ORDER BY {sort_by} {sort_order}
                LIMIT %s OFFSET %s
            """
            params.extend([per_page, offset])
            cursor.execute(query, params)
            courses = cursor.fetchall()

            return jsonify({
                'success': True,
                'courses': courses,
                'total': total,
                'page': page,
                'per_page': per_page,
                'pages': (total + per_page - 1) // per_page
            }), 200
    except Exception as e:
        logger.error(f"Error fetching courses: {e}")
        return jsonify({'success': False, 'message': 'Error fetching courses', 'error': str(e)}), 500

@courses_bp.route('/<int:course_id>', methods=['PUT'])
@api_key_required
def update_course(course_id):
    try:
        data = request.get_json()
        course_code = data.get('course_code', '').strip()
        course_title = data.get('course_title', '').strip()
        description = data.get('description', '').strip()

        print(f"Updating course {course_id} with code '{course_code}', title '{course_title}'")

        if not course_code or not course_title:
            return jsonify({'success': False, 'message': 'Course code and title are required', 'error': 'Course code and title are required'}), 400

        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("""
                SELECT * FROM courses_master WHERE course_id = %s
            """, (course_id,))
            existing_course = cursor.fetchone()
            if not existing_course:
                return jsonify({'success': False, 'message': 'Course not found', 'error': 'Course not found'}), 404

            updates = []
            params = []

            if course_code and course_code != existing_course['course_code']:
                updates.append("course_code = %s")
                params.append(course_code)
            if course_title and course_title != existing_course['course_title']:
                updates.append("course_title = %s")
                params.append(course_title)
            if description is not None and description != existing_course.get('description'):
                updates.append("description = %s")
                params.append(description)

            if not updates:
                print("No changes detected.")
                return jsonify({'success': True, 'message': 'No changes made'}), 200

            params.append(course_id)
            query = f"""
                UPDATE courses_master
                SET {', '.join(updates)}
                WHERE course_id = %s
            """
            cursor.execute(query, params)
            db.commit()
            return jsonify({'success': True, 'message': 'Course updated successfully'}), 200

    except Exception as e:
        logger.error(f"Error updating course: {e}")
        return jsonify({'success': False, 'message': 'Error updating course', 'error': str(e)}), 500

@courses_bp.route('/<int:course_id>', methods=['DELETE'])
@api_key_required
def delete_course(course_id):
    try:
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("""
                SELECT * FROM courses_master WHERE course_id = %s
            """, (course_id,))
            existing_course = cursor.fetchone()
            if not existing_course:
                return jsonify({'success': False, 'message': 'Course not found', 'error': 'Course not found'}), 404

            cursor.execute("""
                DELETE FROM courses_master WHERE course_id = %s
            """, (course_id,))
            db.commit()

            return jsonify({'success': True, 'message': 'Course deleted successfully'}), 200
    except Exception as e:
        logger.error(f"Error deleting course: {e}")
        return jsonify({'success': False, 'message': 'Error deleting course', 'error': str(e)}), 500

@courses_bp.route('/upload-csv', methods=['POST'])
@api_key_required
def upload_csv():
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'message': 'No file uploaded'}), 400

        file = request.files['file']
        if file.filename == '' or not file.filename.endswith('.csv'):
            return jsonify({'success': False, 'message': 'Please select a valid CSV file'}), 400

        stream = io.StringIO(file.stream.read().decode("utf-8", errors="ignore"), newline=None)
        csv_input = csv.DictReader(stream)

        db = get_db()
        created_count = 0
        errors = []

        with db.cursor() as cursor:
            for row_num, row in enumerate(csv_input, start=2):
                try:
                    course_code = row.get('course_code', '').strip()
                    course_title = row.get('course_title', '').strip()
                    description = row.get('description', '').strip()

                    if not course_code or not course_title:
                        errors.append(f"Row {row_num}: Missing course_code or course_title")
                        continue

                    # Check for duplicates
                    cursor.execute("SELECT course_id FROM courses_master WHERE course_code = %s", (course_code,))
                    if cursor.fetchone():
                        errors.append(f"Row {row_num}: Course code '{course_code}' already exists")
                        continue

                    cursor.execute(
                        "INSERT INTO courses_master (course_code, course_title, description) VALUES (%s, %s, %s)",
                        (course_code, course_title, description)
                    )
                    created_count += 1

                except Exception as e:
                    logger.error(f"Error processing row {row_num}: {e}")
                    errors.append(f"Row {row_num}: {str(e)}")

            db.commit()

        return jsonify({
            'success': True,
            'message': f'CSV processed successfully. {created_count} courses created.',
            'created': created_count,
            'errors': errors,
            'has_errors': len(errors) > 0
        }), 200

    except Exception as e:
        logger.error(f"Error uploading CSV: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@courses_bp.route('/export-csv', methods=['GET'])
@api_key_required
def export_csv():
    try:
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("""
                SELECT course_code, course_title, description
                FROM courses_master
                ORDER BY course_code
            """)
            courses = cursor.fetchall()

            output = io.StringIO()
            writer = csv.writer(output)

            # Write UTF-8 BOM for Excel compatibility
            output.write('\ufeff')

            # Write header with better column names
            writer.writerow(['Course Code', 'Course Title', 'Description'])

            # Write data
            for course in courses:
                writer.writerow([
                    course['course_code'],
                    course['course_title'],
                    course['description'] or ''
                ])

            response = make_response(output.getvalue())
            response.headers['Content-Type'] = 'text/csv; charset=utf-8'
            response.headers['Content-Disposition'] = 'attachment; filename="courses_export.csv"'
            return response

    except Exception as e:
        logger.error(f"Error exporting CSV: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500