from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from init_db import get_db
import pymysql

assessment_scopes_bp = Blueprint('assessment_scopes', __name__)

@assessment_scopes_bp.route('/courses', methods=['GET'])
@jwt_required()
def get_resources_for_assessment():
    try:
        db = get_db()
        with db.cursor() as cursor:
            search = request.args.get('search', '').strip()
            where_clause = ""
            params = []
            if search:
                where_clause = "WHERE c.course_code LIKE %s OR c.course_title LIKE %s"
                params.extend([f"%{search}%", f"%{search}%"])
            
            query = """
                SELECT 
                    c.course_id,
                    c.course_code,
                    c.course_title,
                    c.description,
                    COUNT(DISTINCT a.exam_type_id) as assessment_count
                FROM courses c
                LEFT JOIN assessment_scopes a ON c.course_id = a.course_id
                {where_clause}
                GROUP BY c.course_id, c.course_code, c.course_title, c.description
                ORDER BY c.course_code
            """.format(where_clause=where_clause)
            
            cursor.execute(query, params)
            courses = cursor.fetchall()
            return jsonify({'success': True, 'courses': courses}), 200
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@assessment_scopes_bp.route('/exam_types', methods=['GET'])
@jwt_required()
def get_exam_types():
    try:
        course_id = request.args.get('course_id')
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("""
                SELECT exam_type_id, exam_name, description
                FROM exam_types
                ORDER BY exam_name
            """)
            exam_types = cursor.fetchall()

            if course_id:
                cursor.execute("""
                    SELECT DISTINCT exam_type_id
                    FROM assessment_scopes
                    WHERE course_id = %s
                """, (course_id,))
                existing_assessments = {row['exam_type_id'] for row in cursor.fetchall()}
                
                for exam_type in exam_types:
                    exam_type['has_scope'] = exam_type['exam_type_id'] in existing_assessments
            else:
                for exam_type in exam_types:
                    exam_type['has_scope'] = False
                    
            return jsonify({'success': True, 'exam_types': exam_types}), 200
    
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@assessment_scopes_bp.route('/modules', methods=['GET'])
@jwt_required()
def get_course_modules():
    try:
        course_id = request.args.get('course_id')
        exam_type_id = request.args.get('exam_type_id')
        
        if not course_id:
            return jsonify({'success': False, 'message': 'course_id is required'}), 400
        
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("""
                SELECT module_id, position, content_html
                FROM modules_master
                WHERE course_id = %s
                ORDER BY position
            """, (course_id,))
            modules = cursor.fetchall()
            
            selected_modules = []
            if exam_type_id:
                cursor.execute("""
                    SELECT module_id
                    FROM assessment_scopes 
                    WHERE course_id = %s AND exam_type_id = %s
                """, (course_id, exam_type_id))
                selected_modules = [row['module_id'] for row in cursor.fetchall()]
                
            return jsonify({'success': True, 'modules': modules, 'selected_modules': selected_modules}), 200
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@assessment_scopes_bp.route('/count/<int:course_id>', methods=['GET'])
@jwt_required()
def get_assessment_count(course_id):
    try:
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("""
                SELECT COUNT(DISTINCT exam_type_id) as assessment_count
                FROM assessment_scopes
                WHERE course_id = %s
            """, (course_id,))
            result = cursor.fetchone()
            assessment_count = result['assessment_count'] if result else 0
            return jsonify({'success': True, 'assessment_count': assessment_count}), 200
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@assessment_scopes_bp.route('/save', methods=['POST'])  
@jwt_required()
def save_assessment_scope():
    try:
        data = request.get_json()
        course_id = data.get('course_id')
        exam_type_id = data.get('exam_type_id')
        module_ids = data.get('module_ids', [])
        
        if not course_id or not exam_type_id:
            return jsonify({'success': False, 'message': 'Course ID and Exam Type ID are required'}), 400
        
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("""
                DELETE FROM assessment_scopes
                WHERE course_id = %s AND exam_type_id = %s
            """, (course_id, exam_type_id)) 
            
            if module_ids:
                values = [(course_id, exam_type_id, module_id) for module_id in module_ids]
                cursor.executemany("""
                    INSERT INTO assessment_scopes (course_id, exam_type_id, module_id)
                    VALUES (%s, %s, %s)
                """, values)
            
            db.commit()
            return jsonify({'success': True, 'message': 'Assessment scope saved successfully'}), 200
    except Exception as e:
        db.rollback()  # Added rollback on error
        return jsonify({'success': False, 'message': str(e)}), 500