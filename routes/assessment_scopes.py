from flask import Blueprint, request
from flask_restx import Resource, Namespace, fields
from init_db import get_db
from utils import logger, api_key_required

assessment_scopes_ns = Namespace('assessment_scopes', description='Assessment Scopes Operations')


assessment_scopes_courses_response = assessment_scopes_ns.model('AssessmentScopesCoursesResponse', {
    'success': fields.Boolean,
    'courses': fields.List(fields.Raw, description='List of courses with assessment counts'),
    'message': fields.String(description='Error or status message', required=False)
})

assessment_scopes_exam_types_response = assessment_scopes_ns.model('AssessmentScopesExamTypesResponse', {
    'success': fields.Boolean,
    'exam_types': fields.List(fields.Raw, description='List of exam types with assessment scope status'),
    'message': fields.String(description='Error or status message', required=False)
})

assessment_scopes_modules_response = assessment_scopes_ns.model('AssessmentScopesModulesResponse', {
    'success': fields.Boolean,
    'modules': fields.List(fields.Raw, description='List of modules for the course'),
    'selected_modules': fields.List(fields.Integer, description='List of selected module IDs for the exam type'),
    'message': fields.String(description='Error or status message', required=False)
})

assessment_scopes_count_response = assessment_scopes_ns.model('AssessmentScopesCountResponse', {
    'success': fields.Boolean,
    'assessment_count': fields.Integer,
    'message': fields.String(description='Error or status message', required=False)
})

assessment_scopes_save_response = assessment_scopes_ns.model('AssessmentScopesSaveResponse', {
    'success': fields.Boolean,
    'message': fields.String(description='Status message'),
    'error': fields.String(description='Error message', required=False)
})

@assessment_scopes_ns.route('/courses')
class AssessmentScopesCourses(Resource):
    @assessment_scopes_ns.doc(description="Get list of courses with their assessment scopes.",
                             params={'search': 'Search term to filter courses by code or title'})
    @api_key_required
    @assessment_scopes_ns.marshal_with(assessment_scopes_courses_response, code=200)
    def get(self):
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
                return {'success': True, 'courses': courses}, 200
        except Exception as e:
            return {'success': False, 'message': str(e)}, 500

@assessment_scopes_ns.route('/exam_types')
class ExamTypes(Resource):
    @assessment_scopes_ns.doc(
        description="Get list of exam types with assessment scope status for a given course.",
        params={'course_id': 'ID of the course (optional)'})
    @api_key_required
    @assessment_scopes_ns.marshal_with(assessment_scopes_exam_types_response, code=200)
    def get(self):
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

                return {'success': True, 'exam_types': exam_types}, 200

        except Exception as e:
            return {'success': False, 'message': str(e)}, 500

@assessment_scopes_ns.route('/modules')
class CourseModules(Resource):
    @assessment_scopes_ns.doc(
        description="Get list of modules for a specific course and highlight selected modules for an exam type.",
        params={'course_id': 'ID of the course', 'exam_type_id': 'ID of the exam type (optional)'}
    )
    @api_key_required
    @assessment_scopes_ns.marshal_with(assessment_scopes_modules_response, code=200)
    def get(self):
        try:
            course_id = request.args.get('course_id')
            exam_type_id = request.args.get('exam_type_id')

            if not course_id:
                return {'success': False, 'message': 'course_id is required'}, 400

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

                return {'success': True, 'modules': modules, 'selected_modules': selected_modules}, 200
        except Exception as e:
            return {'success': False, 'message': str(e)}, 500


# Add a new response model for count endpoint
assessment_scopes_count_response = assessment_scopes_ns.model('AssessmentScopesCountResponse', {
    'success': fields.Boolean,
    'assessment_count': fields.Integer,
    'message': fields.String(description='Error or status message', required=False)
})

@assessment_scopes_ns.route('/count/<int:course_id>')
class AssessmentCount(Resource):
    @assessment_scopes_ns.doc(
        description="Get count of distinct assessment types for a given course.",
        params={'course_id': 'ID of the course'}
    )
    @api_key_required
    @assessment_scopes_ns.marshal_with(assessment_scopes_count_response, code=200)
    def get(self, course_id):
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
                return {'success': True, 'assessment_count': assessment_count}, 200
        except Exception as e:
            return {'success': False, 'assessment_count': 0, 'message': str(e)}, 500

@assessment_scopes_ns.route('/save')
class SaveAssessmentScope(Resource):
    @assessment_scopes_ns.doc(
        description="Save assessment scope for a course and exam type.",
        params={'course_id': 'ID of the course', 'exam_type_id': 'ID of the exam type', 'module_ids': 'List of module IDs to include in the assessment scope'}
    )
    @api_key_required
    @assessment_scopes_ns.marshal_with(assessment_scopes_save_response, code=200)
    def post(self):
        try:
            data = request.get_json()
            course_id = data.get('course_id')
            exam_type_id = data.get('exam_type_id')
            module_ids = data.get('module_ids', [])

            if not course_id or not exam_type_id:
                return {'success': False, 'message': 'Course ID and Exam Type ID are required', 'error': 'Course ID and Exam Type ID are required'}, 400

            if not isinstance(module_ids, list):
                return {'success': False, 'message': 'module_ids must be a list', 'error': 'module_ids must be a list'}, 400

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
                return {'success': True, 'message': 'Assessment scope saved successfully', 'error': None}, 200
        except Exception as e:
            return {'success': False, 'message': str(e), 'error': str(e)}, 500