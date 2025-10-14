import csv
import io
from flask import Blueprint, make_response, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from init_db import get_db
from utils import logger

enrollments_bp = Blueprint('enrollments', __name__)


@enrollments_bp.route('/student/<int:student_id>', methods=['GET'])
@jwt_required()
def get_student_enrollments(student_id):
    try:
        db =get_db()
        with db.cursor() as cursor:
            query = """
            SELECT
                e.enrollment_id,
                e. created_at as enrolled_at,
                cm.course_id,
                cm.course_code,
                cm.course_title,
                cm.description,
                ci.term_code,
                ci.start_date,
                ci.end_date
                ci.instance_id
                FROM enrollments e
                JOIN course_instances ci ON e.instance_id = ci.instance_id
                JOIN courses_master cm ON ci.course_id = cm.course_id
                WHERE e.user_id = %s
                ORDER BY ci.start_date DESC
            """
            cursor.execute(query, (student_id,))
            enrollments = cursor.fetchall()
            return jsonify({'success': True, 'enrollments': enrollments}), 200
    except Exception as e:
        logger.error(f"Error fetching enrollments for student {student_id}: {str(e)}")
        return jsonify({'success': False, 'message': 'An error occurred while fetching enrollments'}), 500

@enrollments_bp.route('/', methods=['GET'])
@jwt_required()
def get_enrollments():
    try:
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 10))
        search = request.args.get('search', '').strip()
        instance_filter = request.args.get('instance_id', '')
        term_filter = request.args.get('term', '').strip()
        sort_by = request.args.get('sort_by', 'created_at')
        sort_order = request.args.get('sort_order', 'desc').lower()
        
        offset = (page - 1) * per_page
        db = get_db() 
        
        with db.cursor() as cursor:
            where_conditions = []
            params = []
            
            if search:
                where_conditions.append("(u.external_id LIKE %s OR u.full_name LIKE %s OR cm.course_code LIKE %s OR cm.course_title LIKE %s)")  
                params.extend([f"%{search}%"] * 4)
            if instance_filter:
                where_conditions.append("ci.instance_id = %s")
                params.append(instance_filter)
            if term_filter:
                where_conditions.append("ci.term_code = %s")
                params.append(term_filter)
            
            where_clause = "WHERE" + "AND".join(where_conditions) if where_conditions else ""
            
                            # Get total count
            count_query = f"""
                SELECT COUNT(*) as total 
                FROM enrollments e
                JOIN course_instances ci ON e.instance_id = ci.instance_id
                JOIN courses_master cm ON ci.course_id = cm.course_id                    
                JOIN users u ON e.user_id = u.user_id
                {where_clause}
                """
            
            cursor.execute(count_query, params)
            total = cursor.fetchone()['total']
            
            valid_sort_columns = ['external_id', 'full_name', 'course_code', 'course_title', 'term_code', 'created_at']   
            if sort_by not in valid_sort_columns:
                sort_by = 'created_at'
            if sort_order not in ['asc', 'desc']:
                sort_order = 'desc'
            
            sort_column_map = {
                'external_id': 'u.external_id',
                'full_name': 'u.full_name',
                'course_code': 'cm.course_code',
                'course_title': 'cm.course_title',
                'term_code': 'ci.term_code',
                'created_at': 'e.created_at'
            }
            query = f"""
            SELECT
            e.enrollment_id,e.instance_id, e.user_id, e.created_at,
            u.external_id, u.full_name,
            cm.course_code,cm.course_title,
            ci.term_code, ci.start_date, ci.end_date
            FROM enrollments e
            JOIN course_instances ci ON e.instance_id = ci.instance_id
            JOIN courses_master cm ON ci.course_id = cm.course_id
            JOIN users u ON e.user_id = u.user_id
            {where_clause}
            ORDER BY {sort_column_map[sort_by]} {sort_order}
            LIMIT %s OFFSET %s
            """
            params.extend([per_page, offset])
            cursor.execute(query, params)
            enrollments = cursor.fetchall()
            return jsonify({
                'success': True,
                'enrollments': enrollments,
                'total': total,
                'page': page,
                'per_page': per_page,
                'pages': (total + per_page - 1) // per_page
            }), 200
    except Exception as e:
        logger.error(f"Error fetching enrollments: {str(e)}")
        return jsonify({'success': False, 'message': 'An error occurred while fetching enrollments'}), 500
    
@enrollments_bp.route('/instances', methods=['GET'])
@jwt_required()
def get_course_instances():
    try:
        search = request.args.get('search', '').strip()
        db = get_db()
        with db.cursor() as cursor:
            where_clause = ""
            params = []
            if search:
                where_clause = "WHERE cm.course_code LIKE %s OR cm.course_title LIKE %s OR ci.term_code LIKE %s"
                params.extend([f"%{search}%"] * 3)
                
            query = f"""
            SELECT 
                ci.instance_id, 
                ci.term_code,
                ci.start_date,
                ci.end_date,
                cm.course_code,
                cm.course_title
            FROM course_instances ci
            JOIN courses_master cm ON ci.course_id = cm.course_id
            {where_clause}
            ORDER BY ci.term_code DESC, cm.course_code
            """
            cursor.execute(query, params)
            instances = cursor.fetchall()
            return jsonify({'success': True, 'instances': instances}), 200
    except Exception as e:
        logger.error(f"Error fetching course instances: {str(e)}")
        return jsonify({'success': False, 'message': 'An error occurred while fetching course instances'}), 500
    
@enrollments_bp.route('/students', methods=['GET'])
@jwt_required()
def get_students():
    try:
        search = request.args.get('search', '')
        db = get_db()
        with db.cursor() as cursor:
            where_clause = "WHERE role = 'student'"
            params = []
            if search:
                where_clause += " AND (external_id LIKE %s OR full_name LIKE %s)"
                params.extend([f"%{search}%", f"%{search}%"])
            
            query = f"""
            SELECT user_id, external_id, full_name
            FROM users
            {where_clause}
            ORDER BY external_id
            """
            cursor.execute(query, params)
            students = cursor.fetchall()
            return jsonify({'success': True, 'students': students}), 200
    except Exception as e:
        logger.error(f"Error fetching students: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500
    
@enrollments_bp.route('/', methods=['POST'])
@jwt_required()
def create_enrollment():
    try:
        data = request.get_json()
        instance_id = data.get('instance_id')
        user_id = data.get('user_id')  
        
        if not instance_id or not user_id:
            return jsonify({'success': False, 'message': 'instance_id and user_id are required'}), 400
        
        db = get_db()
        with db.cursor() as cursor:  # Fixed spacing
            # Check if enrollment already exists
            cursor.execute("""
                SELECT enrollment_id FROM enrollments 
                WHERE instance_id = %s AND user_id = %s
            """, (instance_id, user_id))
            existing = cursor.fetchone()
            
            if existing:
                return jsonify({
                    'success': False, 
                    'message': 'User is already enrolled in this course instance'
                }), 400
            
            # Validate that instance exists
            cursor.execute("""
                SELECT instance_id FROM course_instances 
                WHERE instance_id = %s
            """, (instance_id,))
            instance = cursor.fetchone()
            
            if not instance:
                return jsonify({
                    'success': False, 
                    'message': 'Course instance not found'
                }), 404
            
            # Validate that user exists
            cursor.execute("""
                SELECT user_id FROM users 
                WHERE user_id = %s
            """, (user_id,))
            user = cursor.fetchone()
            
            if not user:
                return jsonify({
                    'success': False, 
                    'message': 'User not found'
                }), 404
            
            # Create enrollment
            cursor.execute("""
                INSERT INTO enrollments (instance_id, user_id) 
                VALUES (%s, %s)
            """, (instance_id, user_id))
            
            db.commit()
            
            return jsonify({
                'success': True, 
                'message': 'Enrollment created successfully',
                'enrollment_id': cursor.lastrowid  # Return the new ID
            }), 201
            
    except Exception as e:
        logger.error(f"Error creating enrollment: {str(e)}")
        db.rollback()
        return jsonify({
            'success': False, 
            'message': f'An error occurred while creating enrollment: {str(e)}'
        }), 500
        
@enrollments_bp.route('/bulk-enroll', methods=['POST'])
@jwt_required()
def bulk_enroll_students():
    try:
        data = request.get_json()
        instance_id = data.get('instance_id')
        user_ids = data.get('user_ids', [])
        
        if not instance_id:
            return jsonify({'success': False, 'message': 'instance_id is required'}), 400
        if not user_ids or not isinstance(user_ids, list):
            return jsonify({'success': False, 'message': 'user_ids must be a non-empty list'}), 400
        
        db = get_db()
        created_count = 0
        errors = []
        
        with db.cursor() as cursor:
            # Validate course instance exists
            cursor.execute("SELECT instance_id FROM course_instances WHERE instance_id = %s", (instance_id,))
            if not cursor.fetchone():
                return jsonify({'success': False, 'message': 'Course instance not found'}), 404
            
            # Process each user
            for user_id in user_ids:
                try:
                    # Validate user exists and get external_id for error messages
                    cursor.execute("SELECT user_id, external_id FROM users WHERE user_id = %s", (user_id,))
                    user = cursor.fetchone()
                    
                    if not user:
                        errors.append(f"User ID {user_id}: User not found")
                        continue
                    
                    # Check for existing enrollment
                    cursor.execute("""
                        SELECT enrollment_id FROM enrollments 
                        WHERE instance_id = %s AND user_id = %s
                    """, (instance_id, user_id))
                    
                    if cursor.fetchone():
                        errors.append(f"User {user['external_id']}: Already enrolled in this course")
                        continue
                    
                    # Create enrollment
                    cursor.execute("""
                        INSERT INTO enrollments (instance_id, user_id) 
                        VALUES (%s, %s)
                    """, (instance_id, user_id))
                    
                    created_count += 1
                    
                except Exception as inner_e:
                    # Handle individual user errors without stopping the entire process
                    external_id = user['external_id'] if user else str(user_id)
                    error_msg = str(inner_e)
                    
                    # Make error message more user-friendly
                    if 'duplicate' in error_msg.lower():
                        errors.append(f"User {external_id}: Already enrolled in this course")
                    elif 'foreign key constraint' in error_msg.lower():
                        errors.append(f"User {external_id}: Invalid user or course instance")
                    else:
                        errors.append(f"User {external_id}: {error_msg}")
                    
                    continue
            
            
            db.commit()
            
            return jsonify({
                'success': True,
                'message': f'Bulk enrollment completed. {created_count} users enrolled successfully.',
                'created': created_count,
                'errors': errors,
                'has_errors': len(errors) > 0
            }), 200
            
    except Exception as e:
        logger.error(f"Error during bulk enrollment: {str(e)}")
        db.rollback()
        return jsonify({
            'success': False, 
            'message': f'An error occurred during bulk enrollment: {str(e)}'
        }), 500

# @enrollments_bp.route('/upload-csv', methods=['POST'])
# @jwt_required()
# def upload_csv():
#     try:
#         if 'file' not in request.files:
#             return jsonify({'error': 'No file uploaded'}), 400
        
#         file = request.files['file']
#         instance_id = request.form.get('instance_id')
        
#         if not instance_id:
#             return jsonify({'error': 'Course instance required'}), 400
        
#         if file.filename == '' or not file.filename.endswith('.csv'):
#             return jsonify({'error': 'Please select a valid CSV file'}), 400
        
#         stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
#         csv_input = csv.DictReader(stream)
        
#         db = get_db()
#         created_count = 0
#         errors = []
        
#         try:
#             with db.cursor() as cursor:
#                 for row_num, row in enumerate(csv_input, start=2):
#                     try:
#                         external_id = row.get('external_id', '').strip()
                        
#                         if not external_id:
#                             errors.append(f"Row {row_num}: Missing external_id (USN)")
#                             continue
                        
#                         # Find user by external_id
#                         cursor.execute("SELECT user_id FROM users WHERE external_id = %s AND role = 'student'", (external_id,))
#                         user = cursor.fetchone()
                        
#                         if not user:
#                             errors.append(f"Row {row_num}: Student with USN '{external_id}' not found")
#                             continue
                        
#                         cursor.execute(
#                             "INSERT INTO enrollments (instance_id, user_id) VALUES (%s, %s)",
#                             (instance_id, user['user_id'])
#                         )
#                         created_count += 1
                        
#                     except Exception as e:
#                         errors.append(f"Row {row_num}: {str(e)}")
                
#                 db.commit()
#         finally:
#             db.close()

#         return jsonify({
#             'success': True,
#             'message': 'CSV processed successfully',
#             'created': created_count,
#             'errors': errors
#         })
        
#     except Exception as e:
#         return jsonify({'error': str(e)}), 500
    
# @enrollments_bp.route('/export-csv', methods=['GET'])
# @jwt_required()
# def export_csv():
#     try:
#         instance_id = request.args.get('instance_id')

#         db = get_db()
#         try:
#             with db.cursor() as cursor:
#                 where_clause = ""
#                 params = []
                
#                 if instance_id:
#                     where_clause = "WHERE e.instance_id = %s"
#                     params = [instance_id]
                
#                 query = f"""
#                     SELECT u.external_id, u.full_name, cm.course_code, cm.course_title, ci.term_code
#                     FROM enrollments e
#                     JOIN course_instances ci ON e.instance_id = ci.instance_id
#                     JOIN courses_master cm ON ci.course_id = cm.course_id
#                     JOIN users u ON e.user_id = u.user_id
#                     {where_clause}
#                     ORDER BY ci.term_code DESC, cm.course_code, u.external_id
#                 """
                
#                 cursor.execute(query, params)
#                 enrollments = cursor.fetchall()
                
#                 output = io.StringIO()
#                 writer = csv.writer(output)
                
#                 # Write header
#                 writer.writerow(['external_id', 'full_name', 'course_code', 'course_title', 'term_code'])
                
#                 # Write data
#                 for enrollment in enrollments:
#                     writer.writerow([
#                         enrollment['external_id'],
#                         enrollment['full_name'],
#                         enrollment['course_code'],
#                         enrollment['course_title'],
#                         enrollment['term_code']
#                     ])
                
#                 response = make_response(output.getvalue())
#                 response.headers['Content-Type'] = 'text/csv'
#                 response.headers['Content-Disposition'] = 'attachment; filename=enrollments.csv'
#                 return response
#         finally:
#             db.close()
#     except Exception as e:
#         return jsonify({'error': str(e)}), 500

@enrollments_bp.route('/upload-csv', methods=['POST'])
@jwt_required()
def upload_csv():
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'message': 'No file uploaded'}), 400
        
        file = request.files['file']
        instance_id = request.form.get('instance_id')
        
        if not instance_id:
            return jsonify({'success': False, 'message': 'Course instance ID is required'}), 400
        
        # Validate file
        if file.filename == '':
            return jsonify({'success': False, 'message': 'No file selected'}), 400
        
        if not file.filename.lower().endswith('.csv'):
            return jsonify({'success': False, 'message': 'Please select a CSV file'}), 400
        
        # Check file size (e.g., 5MB limit)
        file.seek(0, 2)  # Seek to end
        file_size = file.tell()
        file.seek(0)  # Reset to beginning
        
        if file_size > 5 * 1024 * 1024:  # 5MB
            return jsonify({'success': False, 'message': 'File too large (max 5MB)'}), 400
        
        # Process CSV
        stream = io.StringIO(file.stream.read().decode("utf-8", errors="ignore"), newline=None)
        csv_input = csv.DictReader(stream)
        
        db = get_db()
        created_count = 0
        errors = []
        
        with db.cursor() as cursor:
            # Validate course instance
            cursor.execute("""
                SELECT ci.instance_id, cm.course_code, cm.course_title 
                FROM course_instances ci 
                JOIN courses_master cm ON ci.course_id = cm.course_id 
                WHERE ci.instance_id = %s
            """, (instance_id,))
            instance = cursor.fetchone()
            
            if not instance:
                return jsonify({'success': False, 'message': 'Course instance not found'}), 404
            
            course_info = f"{instance['course_code']} - {instance['course_title']}"
            
            # Process each row
            for row_num, row in enumerate(csv_input, start=2):
                try:
                    external_id = row.get('external_id', '').strip()
                    
                    if not external_id:
                        errors.append(f"Row {row_num}: Missing student USN")
                        continue
                    
                    # Find student
                    cursor.execute(
                        "SELECT user_id, external_id, full_name FROM users WHERE external_id = %s AND role = 'student'", 
                        (external_id,)
                    )
                    student = cursor.fetchone()
                    
                    if not student:
                        errors.append(f"Row {row_num}: Student with USN '{external_id}' not found")
                        continue
                    
                    # Check existing enrollment
                    cursor.execute(
                        "SELECT enrollment_id FROM enrollments WHERE instance_id = %s AND user_id = %s",
                        (instance_id, student['user_id'])
                    )
                    if cursor.fetchone():
                        errors.append(f"Row {row_num}: {student['full_name']} ({external_id}) already enrolled")
                        continue
                    
                    # Create enrollment
                    cursor.execute(
                        "INSERT INTO enrollments (instance_id, user_id) VALUES (%s, %s)",
                        (instance_id, student['user_id'])
                    )
                    created_count += 1
                    
                except Exception as e:
                    external_id = row.get('external_id', 'Unknown')
                    errors.append(f"Row {row_num}: Error processing student '{external_id}' - {str(e)}")
            
            db.commit()
        
        return jsonify({
            'success': True,
            'message': f'Enrollment CSV processed for {course_info}',
            'created': created_count,
            'errors': errors,
            'has_errors': len(errors) > 0,
            'course_info': course_info
        }), 200
        
    except Exception as e:
        logger.error(f"Error uploading enrollment CSV: {str(e)}")
        db.rollback()
        return jsonify({'success': False, 'message': f'Error processing CSV file: {str(e)}'}), 500
    
@enrollments_bp.route('/export-csv', methods=['GET'])
@jwt_required()
def export_csv():
    try:
        instance_id = request.args.get('instance_id')
        
        db = get_db()  # Use your existing get_db() function
        with db.cursor() as cursor:
            where_clause = ""
            params = []
            
            if instance_id:
                where_clause = "WHERE e.instance_id = %s"
                params = [instance_id]
            
            # Use .format() instead of f-string for security
            query = """
                SELECT 
                    u.external_id, 
                    u.full_name, 
                    cm.course_code, 
                    cm.course_title, 
                    ci.term_code
                FROM enrollments e
                JOIN course_instances ci ON e.instance_id = ci.instance_id
                JOIN courses_master cm ON ci.course_id = cm.course_id
                JOIN users u ON e.user_id = u.user_id
                {where_clause}
                ORDER BY ci.term_code DESC, cm.course_code, u.external_id
            """.format(where_clause=where_clause)
            
            cursor.execute(query, params)
            enrollments = cursor.fetchall()
            
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write UTF-8 BOM for Excel compatibility
            output.write('\ufeff')
            
            # Write header
            writer.writerow(['USN', 'Student Name', 'Course Code', 'Course Title', 'Term'])
            
            # Write data
            for enrollment in enrollments:
                writer.writerow([
                    enrollment['external_id'] or '',
                    enrollment['full_name'] or '',
                    enrollment['course_code'] or '',
                    enrollment['course_title'] or '',
                    enrollment['term_code'] or ''
                ])
            
            # Create response
            csv_data = output.getvalue()
            output.close()
            
            # Determine filename
            if instance_id:
                filename = f"enrollments_instance_{instance_id}.csv"
            else:
                filename = "all_enrollments.csv"
            
            response = make_response(csv_data)
            response.headers['Content-Type'] = 'text/csv; charset=utf-8'
            response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
            return response
            
    except Exception as e:
        logger.error(f"Error exporting enrollments CSV: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500