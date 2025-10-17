from flask import request
from flask_restx import Namespace, Resource, fields
from init_db import get_db
from utils import logger,api_key_required
from bs4 import BeautifulSoup
import random
import traceback

assessment_preview_ns = Namespace('assessment_preview', description='Assessment Preview Operations')

assessment_preview_courses_response = assessment_preview_ns.model('AssessmentPreviewCoursesResponse', {
    'success': fields.Boolean(required=True, description='Indicates if the request was successful'),
    'courses': fields.List(fields.Raw, description='List of courses available for assessment preview')
})

assessment_preview_assessments_response = assessment_preview_ns.model('AssessmentPreviewAssessmentsResponse', {
    'success': fields.Boolean(required=True, description='Indicates if the request was successful'),
    'assessments': fields.List(fields.Raw, description='List of assessments for the specified course')
})

assessment_preview_generate_response = assessment_preview_ns.model('AssessmentPreviewGenerateResponse', {
    'success': fields.Boolean(required=True, description='Indicates if the request was successful'),
    'assessment_info': fields.Raw(description='Information about the generated assessment'),
    'questions': fields.List(fields.Raw, description='List of selected questions'),
    'statistics': fields.Raw(description='Statistics about the generated assessment'),
    'message': fields.String(description='Error or status message', required=False),
    'error': fields.String(description='Error details', required=False),
})
@assessment_preview_ns.route('/courses')
class AssessmentPreviewCourses(Resource):
    @assessment_preview_ns.doc(
        description="Fetch list of courses available for assessment preview",
        params={'search': 'Optional search term to filter courses by code or title'}
    )
    @api_key_required
    @assessment_preview_ns.marshal_with(assessment_preview_courses_response, code=200)
    def get(self):
        search = request.args.get('search', '').strip()
        try:
            db = get_db()
            with db.cursor() as cursor:
                if search:
                    cursor.execute("""
                        SELECT course_id, course_code, course_title
                        FROM courses_master
                        WHERE course_code LIKE %s OR course_title LIKE %s
                        ORDER BY course_code
                    """, (f"%{search}%", f"%{search}%"))
                else:
                    cursor.execute("""
                        SELECT course_id, course_code, course_title
                        FROM courses_master
                        ORDER BY course_code
                    """)
                courses = cursor.fetchall()
            return {'success': True, 'courses': courses}, 200
        except Exception as e:
            logger.error(f"Error fetching courses for assessment preview: {str(e)}")
            return {'success': False, 'courses': [], 'message': str(e)}, 500


@assessment_preview_ns.route('/assessments/<int:course_id>')
class AssessmentPreviewAssessments(Resource):
    @assessment_preview_ns.doc(
        description="Fetch list of assessments for a given course available for preview",
        params={'course_id': 'ID of the course to fetch assessments for'}
    )
    @api_key_required
    @assessment_preview_ns.marshal_with(assessment_preview_assessments_response, code=200)
    def get(self, course_id):

        try:
            db = get_db()
            with db.cursor() as cursor:
                cursor.execute ("""
                            SELECT DISTINCT et.exam_type_id, et.exam_name, et.total_items,
                            COUNT(ascope.module_id) as module_count
                            FROM exam_types et
                            JOIN assessment_scopes ascope ON et.exam_type_id = ascope.exam_type_id
                            WHERE ascope.course_id = %s
                            GROUP BY et.exam_type_id, et.exam_name, et.total_items
                            ORDER BY et.exam_name
                            """, (course_id,))
            assessments = cursor.fetchall()
            result = []
            for assessment in assessments:
                result.append({
                    'exam_type_id': assessment['exam_type_id'],
                    'exam_name': assessment['exam_name'],
                    'total_items': assessment['total_items'],
                    'module_count': assessment['module_count']
                })
            return {'success': True, 'assessments': result}, 200
        except Exception as e:
            logger.error(f"Error fetching assessments for course {course_id}: {str(e)}")
            traceback.print_exc()
            return {'success': False, 'message': str(e)}, 500

@assessment_preview_ns.route('/generate-preview')
class GenerateAssessmentPreview(Resource):
    @assessment_preview_ns.doc(
        description="Generate a preview of an assessment for a given course and exam type",
        params={'course_id': 'ID of the course', 'exam_type_id': 'ID of the exam type'}
    )
    @api_key_required
    @assessment_preview_ns.marshal_with(assessment_preview_generate_response, code=200)
    def post(self):
        try:
            data = request.get_json()
            course_id = data.get('course_id')
            exam_type_id = data.get('exam_type_id')

            if not course_id or not exam_type_id:
                return {'success': False, 'message': 'course_id and exam_type_id are required'}, 400
            db = get_db()
            with db.cursor() as cursor:
                cursor.execute('''
                    SELECT exam_name, total_items
                    FROM exam_types
                    WHERE exam_type_id = %s
                ''', (exam_type_id,))
                assessment_info = cursor.fetchone()
                if not assessment_info:
                    return {'success': False, 'message': 'Invalid exam_type_id'}, 400
                total_items_needed = assessment_info['total_items']

                cursor.execute('''
                    SELECT
                        m.module_id,
                        m.position as module_position,
                        m.content_html,
                        ms.section_id,
                        ms_title as section_title,
                        ms.position as section_position,
                        ei.item_id,
                        ei.question,
                        ei.option_a,
                        ei.option_b,
                        ei.option_c,
                        ei.option_d,
                        ei.correct_answer
                    FROM assessment_scopes ascope
                    JOIN modules_master m ON ascope.module_id = m.module_id
                    JOIN module_sections ms ON m.module_id = ms.module_id
                    JOIN exam_items ei ON ms.section_id = ei.section_id
                    WHERE ascope.course_id = %s AND ascope.exam_type_id = %s
                    ORDER BY m.position, ms.position
                ''', (course_id, exam_type_id))
                all_questions = cursor.fetchall()
                if not all_questions:
                    return {'success': False, 'message': 'No questions found for the selected course and assessment type'}, 404
                questions_by_module = {}
                for q in all_questions:
                    module_id = q['module_id']
                    section_id = q['section_id']

                    if module_id not in questions_by_module:
                        content_text = BeautifulSoup(q['content_html'], 'html.parser').get_text() if q['content_html'] else ''
                        module_title = content_text.split('\n')[0].strip() if content_text else f"Module {q['module_position']}"

                        questions_by_module[module_id] = {
                            'module_position': q['module_position'],
                            'module_title': module_title,
                            'sections': {}
                        }
                    if section_id not in questions_by_module[module_id]['sections']:
                        questions_by_module[module_id]['sections'][section_id] = {
                            'section_position': q['section_position'],
                            'section_title': q['section_title'],
                            'questions': []
                        }

                    questions_by_module[module_id]['sections'][section_id]['questions'].append({
                        'item_id': q['item_id'],
                        'question': q['question'],
                        'option_a': q['option_a'],
                        'option_b': q['option_b'],
                        'option_c': q['option_c'],
                        'option_d': q['option_d'],
                        'correct_answer': q['correct_answer']
                    })
                selected_questions = []
                all_available_questions = []

                for module_id, module_data in questions_by_module.items():
                    for section_id, section_data in module_data['sections'].items():
                        for question in section_data['questions']:
                            all_available_questions.append({
                                'module_id': module_id,
                                'module_position': module_data['module_position'],
                                'module_title': module_data['module_title'],
                                'section_id': section_id,
                                'section_title': section_data['section_title'],
                                'section_position': section_data['section_position'],
                                **question
                            })
                if len(all_available_questions) < total_items_needed:
                    return {'success': False,
                            'error': 'Not enough questions available',
                            'message': f'Not enough questions available ({len(all_available_questions)}) to generate the requested number of items ({total_items_needed})'}, 400
                selected_questions = random.sample(all_available_questions, total_items_needed)

                selected_questions.sort(key=lambda x: (x['module_position'], x['section_position']))

                module_stats = {}
                section_stats = {}

                for q in selected_questions:
                    module_key = f"{q['module_position']}: {q['module_title']}"
                    section_key = f"{q['section_title']}"

                    module_stats[module_key] = module_stats.get(module_key, 0) + 1
                    section_stats[section_key] = section_stats.get(section_key, 0) + 1

                return {
                    'success': True,
                    'assessment_info':{
                        'exam_name': assessment_info['exam_name'],
                        'total_items': total_items_needed,
                        'selected_count':len(selected_questions)
                    },
                    'questions': selected_questions,
                    'statistics':{
                        'module_distribution': module_stats,
                        'section_distribution': section_stats,
                        'total_available': len(all_available_questions)
                    }
                }, 200
        except Exception as e:
            logger.error(f"Error generating assessment preview: {str(e)}")
            traceback.print_exc()
            return {'success': False, 'message': str(e)}, 500