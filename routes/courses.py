from flask import Blueprint, request, jsonify, make_response
from flask_jwt_extended import jwt_required
import csv
import io
import requests
import os
import boto3
import json
from init_db import get_db
from utils import logger

courses_bp = Blueprint('courses', __name__)
# AWS Bedrock configuration
model_id = "meta.llama3-70b-instruct-v1:0"

def get_bedrock_client():
    """"Initialize and return a boto3 Bedrock client."""
    return boto3.client(
        'bedrock-runtime',
        region_name=os.getenv('AWS_REGION', 'us-west-2'),
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
    )
def generate_with_bedrock(prompt, temperature=0.7):
    try:
        bedrock = get_bedrock_client()
        response = bedrock.invoke_model(
            modelId=model_id,
            body=json.dumps({
                "prompt": prompt,
                "max_gen_len":4096,
                "temperature": temperature,
                "top_p": 0.9,
            }),
        )
        result = json.loads(response['body'].read())
        return result['generation']
    except Exception as e:
        logger.error(f"Bedrock generation error: {str(e)}")
        print(f"Bedrock generation error: {str(e)}")
        return None

@courses_bp.route('/', methods=['GET'])
@jwt_required()
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
            params= []
            if search: 
                where_conditions.append("(course_code LIKE %s OR course_title LIKE %s)")
                search_param = f"%{search}%"
                params.extend([search_param, search_param])
            
            where_clause = " WHERE " + " AND ".join(where_conditions) if where_conditions else ""
            
            count_query = f"SELECT COUNT(*) as total FROM courses {where_clause}"
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
        return jsonify({'success': False, 'message': str(e)}), 500
    
@courses_bp.route('/<int:course_id>', methods=['PUT'])
@jwt_required()
def update_course(course_id):
    try:
        data = request.get_json()
        course_code = data.get('course_code', '').strip()
        course_title = data.get('course_title', '').strip()
        description = data.get('description', '').strip()
        
        print(f"Updating course {course_id} with code '{course_code}', title '{course_title}'")
        
        if not course_code or not course_title:
            return jsonify({'success': False, 'message': 'Course code and title are required'}), 400
        
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("""
                SELECT * FROM courses_master WHERE course_id = %s
            """, (course_id,))
            existing_course = cursor.fetchone()
            if not existing_course:
                return jsonify({'success': False, 'message': 'Course not found'}), 404

            updates = []
            params = []
            
            if course_code and course_code != existing_course['course_code']:
                updates.append("course_code = %s")
                params.append(course_code)
            if course_title and course_title != existing_course['course_title']:
                updates.append("course_title = %s")
                params.append(course_title)
            if description is not None and description!= existing_course.get('description'):
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
        return jsonify({'success': False, 'message': str(e)}), 500

@courses_bp.route('/<int:course_id>', methods=['DELETE'])
@jwt_required()
def delete_course(course_id):
    try:
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("""
                SELECT * FROM courses_master WHERE course_id = %s
            """, (course_id,))
            existing_course = cursor.fetchone()
            if not existing_course:
                return jsonify({'success': False, 'message': 'Course not found'}), 404
            
            cursor.execute("""
                DELETE FROM courses_master WHERE course_id = %s
            """, (course_id,))
            db.commit()
            
            if cursor.rowcount == 0:
                return jsonify({'success': False, 'message': 'Course not found or already deleted'}), 404
            
            return jsonify({'success': True, 'message': 'Course deleted successfully'}), 200
    except Exception as e:
        logger.error(f"Error deleting course: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@courses_bp.route('/upload-csv', methods=['POST'])
@jwt_required()
def upload_csv():
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'message': 'No file part'}), 400

        file = request.files['file']
        if file.filename == '' or not file.filename.endswith('.csv'):
            return jsonify({'success': False, 'message': 'No selected file or invalid file type'}), 400
        
        # Use more robust decoding
        stream = io.StringIO(file.stream.read().decode("utf-8", errors="ignore"), newline=None)
        csv_input = csv.DictReader(stream)

        db = get_db()
        created_count = 0
        errors = []
        
        try:
            with db.cursor() as cursor:
                for row_num, row in enumerate(csv_input, start=2): 
                    try:
                        course_code = row.get('course_code', '').strip()
                        course_title = row.get('course_title', '').strip()
                        description = row.get('description', '').strip()
                    
                        if not course_code or not course_title:
                            errors.append(f"Row {row_num}: Missing required fields.")
                            continue
                        
                        cursor.execute("""
                            INSERT INTO courses_master (course_code, course_title, description)
                            VALUES (%s, %s, %s)
                        """, (course_code, course_title, description))
                        created_count += 1
                        
                    except Exception as e:
                        logger.error(f"Error processing CSV row {row_num}: {e}")
                        errors.append(f"Row {row_num}: {str(e)}")
                        continue
                
                db.commit()
                
            return jsonify({
                'success': True, 
                'created': created_count, 
                'errors': errors,
                'message': f'Successfully processed {created_count} courses'
            }), 200
            
        except Exception as e:
           
            db.rollback()
            logger.error(f"Database error during CSV upload: {e}")
            return jsonify({
                'success': False, 
                'message': f'Database error: {str(e)}'
            }), 500

    except Exception as e:
        logger.error(f"Error uploading CSV: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
    
@courses_bp.route('/generate-description', methods=['POST'])
@jwt_required()
def generate_description():
    try:
        data = request.get_json()
        course_code = data.get('course_code', '').strip()
        course_title = data.get('course_title', '').strip()
        
        if not course_code or not course_title:
            return jsonify({'success': False, 'message': 'Course code and title are required'}), 400
        
        # Strict prompt for course description only
        prompt = f"""Generate ONLY a course description for: {course_code} - {course_title}

Requirements:
- Write ONLY the course description paragraph
- Do NOT include course objectives, learning outcomes, prerequisites, or target audience
- Do NOT include any headers, titles, or formatting
- Keep it to exactly one paragraph (3-4 sentences)
- Focus on what the course covers and teaches
- Use academic language suitable for a course catalog

Course: {course_code} - {course_title}

Description:"""

        print(f"Generating description with prompt: {prompt}")
        
        raw_description = generate_with_bedrock(prompt, temperature=0.7)
        
        if raw_description:
            lines = raw_description.split('\n')
            description = ''
            for line in lines:
                line - line.strip()
                if line and not line.startswith(('Course:', 'Description:', '**', '#', '-','•')):
                    if not description:
                        description = line 
                    elif len(description.split('.'))<4:
                        description += ' ' + line
                    else:
                        break
            
            description = description.replace('Description:','').strip()
            print(f"Generated description: {description}")
            
            return jsonify({
                'success': True,
                'description': description,
                'generated': True,
            })
        else:
            return jsonify({'success': False, 'message': 'Failed to generate description'}), 500
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error during description generation: {e}")
        return jsonify({'success': False, 'message': 'Error communicating with AI service'}), 500
    except Exception as e:
        logger.error(f"Error generating description: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@courses_bp.route('/export-csv', methods=['GET'])
@jwt_required()
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
            
            # Write header
            writer.writerow(['course_code', 'course_title', 'description'])
            
            # Write data
            for course in courses:
                writer.writerow([
                    course['course_code'],
                    course['course_title'], 
                    course['description'] or ''  # Handle None values
                ])
            
            response = make_response(output.getvalue())
            response.headers['Content-Type'] = 'text/csv'
            response.headers['Content-Disposition'] = 'attachment; filename=courses.csv'
            return response
            
    except Exception as e:
        logger.error(f"Error exporting CSV: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500