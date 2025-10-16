from flask import Blueprint, request, jsonify

from init_db import get_db
from utils import api_key_required, logger


database_bp = Blueprint('database', __name__)


@database_bp.route('/tables', methods=['GET'])
@api_key_required
def list_tables():
    try:
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SHOW TABLES")
            tables = [row[f'Tables_in_{db.db.decode()}'] for row in cursor.fetchall()]
            return jsonify({'tables': tables}), 200
    except Exception as e:
        logger.error(f"Error listing tables: {e}")
        return jsonify({'error': str(e)}), 500


@database_bp.route('/table-data', methods=['GET'])
@api_key_required
def get_table_data():
    table_name = request.args.get('table')
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 50))
    offset = (page - 1) * per_page

    if not table_name:
        return jsonify({'error': 'Table name is required'}), 400
    try:
        db = get_db()
        with db.cursor as cursor:
            cursor.execute(f"SELECT COUNT(*) as total FROM `{table_name}`")
            total = cursor.fetchone()['total']

            cursor.execute(f"DESCRIBE `{table_name}`")
            columns = cursor.fetchall()

            cursor.execute(f"SELECT * FROM `{table_name}` LIMIT %s OFFSET %s", (per_page, offset))
            data = cursor.fetchall()

            return jsonify({
                'columns': columns,
                'data': data,
                'total': total,
                'page': page,
                'per_page': per_page,
                'total_pages': (total + per_page - 1) // per_page
            }), 200
    except Exception as e:
        logger.error(f"Error fetching table data: {e}")
        return jsonify({'error': str(e)}), 500


@database_bp.route('/execute-query', methods=['POST'])
@api_key_required
def execute_custom_query():
    try:
        data = request.get_json()
        query = data.get('query', '').strip()
        confirmed = data.get('confirmed', False)
        if not query:
            return jsonify({'error': 'Query is required'}), 400

        query_upper = query.upper().strip()
        is_select = query_upper.startswith('SELECT') or query_upper.startswith('SHOW') or query_upper.startswith('DESCRIBE')

        if not is_select and not confirmed:
            return jsonify({
                'success': False,
                'requires_confirmation': True,
                'message': 'This query will modify the database. Please confirm to proceed.',
                'error': 'This query will modify the database. Please confirm to proceed.'
            }), 200

        db = get_db()
        with db.cursor() as cursor:
            cursor.execute(query)

            if is_select:
                results = cursor.fetchall()
                columns = list(results[0].keys()) if results else []
                return jsonify({'success': True,
                                'columns': columns,
                                'results': results,
                                'row_count': len(results)}), 200
            else:
                db.commit()
                return jsonify({'success': True,
                                'message': 'Query executed successfully',
                                'affected_rows': cursor.rowcount
                                }), 200
    except Exception as e:
        logger.error(f"Error executing query: {e}")
        return jsonify({'error': str(e)}), 500
