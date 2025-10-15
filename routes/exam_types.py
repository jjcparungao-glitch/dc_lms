from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from init_db import get_db
from utils import logger
import pymysql

exam_types_bp = Blueprint('exam_types', __name__)

@exam_types_bp.route('/', methods=['GET'])
@jwt_required()
def get_exam_types():
    search = request.args.get('search', '').strip()
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 50))
    sort_by = request.args.get('sort_by', 'exam_name')
    sort_order = request.args.get('sort_order', 'asc').lower()
    offset = (page - 1) * per_page

    try:
        db = get_db()
        with db.cursor() as cursor:

            valid_sort_columns = [
                'exam_type_id', 'category', 'exam_name',
                'description', 'total_items', 'created_at', 'updated_at'
            ]
            sort_column_map = {col: col for col in valid_sort_columns}
            sort_column = sort_column_map.get(sort_by, 'exam_name')

            if sort_order.lower() not in ['asc', 'desc']:
                sort_order = 'asc'


            where_clause = ""
            params = []
            if search:
                where_clause = "WHERE exam_name LIKE %s OR description LIKE %s"
                params.extend([f"%{search}%", f"%{search}%"])

            count_query = f"SELECT COUNT(*) AS total FROM exam_types {where_clause}"
            cursor.execute(count_query, params)
            total = cursor.fetchone()['total']


            query = f"""
                SELECT
                    exam_type_id,
                    exam_name,
                    category,
                    exam_period,
                    description,
                    total_items,
                    created_at,
                    updated_at
                FROM exam_types
                {where_clause}
                ORDER BY {sort_column} {sort_order.upper()}
                LIMIT %s OFFSET %s
            """

            params.extend([per_page, offset])
            cursor.execute(query, params)
            exam_types = cursor.fetchall()

            return jsonify({
                'success': True,
                'exam_types': exam_types,
                'total': total,
                'page': page,
                'per_page': per_page,
                'total_pages': (total + per_page - 1) // per_page
            }), 200

    except Exception as e:
        logger.error(f"Error fetching exam types: {e}")
        return jsonify({"error": "Internal server error"}), 500

@exam_types_bp.route('/', methods=['POST'])
@jwt_required()
def create_exam_type():
    try:
        data =request.get_json()
        exam_name = data.get('exam_name', '').strip()
        category = data.get('category', '').strip()
        exam_period = data.get('exam_period', '').strip()
        description = data.get('description', '').strip()
        total_items = data.get('total_items', 1)

        if not exam_name:
            return jsonify({'success': False, 'message': 'Exam name is required'}), 400
        if category not in ['quiz', 'exam']:
            return jsonify({'success': False, 'message': 'Category must be either "quiz" or "exam"'}), 400
        if exam_period not in ['Prelim', 'Midterm', 'Pre-Final', 'Final']:
            return jsonify({'success': False, 'message': 'Invalid exam period'}), 400

        total_items = int(total_items)
        if total_items < 1 or total_items > 100:
            return jsonify({'success': False, 'message': 'Total items must be between 1 and 100'}), 400

        db = get_db()
        with db.cursor() as cursor:
            cursor.execute('''
                           INSERT INTO exam_types (exam_name, category, exam_period, description, total_items)
                           VALUES (%s, %s, %s, %s, %s)
                           ''', (exam_name, category, exam_period, description, total_items))
            db.commit()
            return jsonify({
                'success': True,
                'message': 'Exam type created successfully',
                'exam_type_id': cursor.lastrowid
            }), 201
    except pymysql.MySQLError as e:
        logger.error(f"MySQL error creating exam type: {e}")
        return jsonify({'success': False, 'message': 'Database error occurred'}), 500
    except Exception as e:
        logger.error(f"Error creating exam type: {e}")
        return jsonify({'success': False, 'message': 'Error creating exam type', 'error': str(e)}), 500

@exam_types_bp.route('/<int:exam_type_id>', methods=['PUT'])
@jwt_required()
def update_exam_type(exam_type_id):
    try:
        data = request.get_json()
        exam_name = data.get('exam_name', '').strip()
        category = data.get('category', '').strip()
        exam_period = data.get('exam_period', '').strip()
        description = data.get('description', '').strip()
        total_items = data.get('total_items', 1)

        if not exam_name:
            return jsonify({'success': False, 'message': 'Exam name is required'}), 400
        if category not in ['quiz', 'exam']:
            return jsonify({'success': False, 'message': 'Category must be either "quiz" or "exam"'}), 400
        if exam_period not in ['Prelim', 'Midterm', 'Pre-Final', 'Final']:
            return jsonify({'success': False, 'message': 'Invalid exam period'}), 400

        total_items = int(total_items)
        if total_items < 1 or total_items > 100:
            return jsonify({'success': False, 'message': 'Total items must be between 1 and 100'}), 400
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute('''
                           UPDATE exam_types
                           SET exam_name = %s,
                               category = %s,
                               exam_period = %s,
                               description = %s,
                               total_items = %s,
                               updated_at = NOW()
                           WHERE exam_type_id = %s
                           ''', (exam_name, category, exam_period, description, total_items, exam_type_id))
            if cursor.rowcount == 0:
                return jsonify({'success': False, 'message': 'Exam type not found'}), 404
            db.commit()
            return jsonify({'success': True, 'message': 'Exam type updated successfully'}), 200
    except pymysql.MySQLError as e:
        logger.error(f"MySQL error updating exam type: {e}")
        return jsonify({'success': False, 'message': 'Database error occurred'}), 500
    except Exception as e:
        logger.error(f"Error updating exam type: {e}")
        return jsonify({'success': False, 'message': 'Error updating exam type', 'error': str(e)}), 500

@exam_types_bp.route('/<int:exam_type_id>', methods=['DELETE'])
@jwt_required()
def delete_exam_type(exam_type_id):
    try:
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute('''
                           DELETE FROM exam_types
                           WHERE exam_type_id = %s
                           ''', (exam_type_id,))
            if cursor.rowcount == 0:
                return jsonify({'success': False, 'message': 'Exam type not found'}), 404
            db.commit()
            return jsonify({'success': True, 'message': 'Exam type deleted successfully'}), 200
    except pymysql.MySQLError as e:
        logger.error(f"MySQL error deleting exam type: {e}")
        return jsonify({'success': False, 'message': 'Database error occurred'}), 500
    except Exception as e:
        logger.error(f"Error deleting exam type: {e}")
        return jsonify({'success': False, 'message': 'Error deleting exam type', 'error': str(e)}), 500
