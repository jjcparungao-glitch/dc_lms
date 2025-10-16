from flask import Blueprint, g, request, jsonify, make_response
from flask_jwt_extended import get_jwt_identity
from init_db import get_db
from utils import logger, api_key_required
import json

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from bs4 import BeautifulSoup

import requests
import os
import boto3
import re
import traceback
import io
from flask import send_file

modules_bp = Blueprint('modules', __name__)


@modules_bp.route('/courses', methods = ['GET'])
@api_key_required
def get_courses():
    try:
        search = request.args.get('search', '')

        db = get_db()
        with db.cursor() as cursor:
            where_clause = ''
            params = []

            if search:
                where_clause= 'WHERE course_code LIKE  %s OR course_title LIKE %s'
                params = [f'%{search}%', f'%{search}%']
            query = f'''
                    SELECT course_id, course_code, course_title
                    FROM courses_master
                    {where_clause}
                    ORDER BY course_code
                    '''

            cursor.execute(query, params)
            courses = cursor.fetchall()
            return jsonify({'success': True, 'courses': courses}), 200
    except Exception as e:
        logger.error(f"Error fetching courses: {str(e)}")
        return jsonify({'success': False, 'message': 'Error fetching courses', 'error': str(e)}), 500

@modules_bp.route('/course-details/<int:course_id>', methods = ['GET'])
@api_key_required
def get_course_details(course_id):
    try:
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute('''
                        SELECT
                        course_id,
                        course_code,
                        course_title,
                        description
                        FROM courses_master
                        WHERE course_id = %s
                        ''', (course_id,))
            course = cursor.fetchone()

            if not course:
                logger.warning(f"Course with ID {course_id} not found.")
                return jsonify({'success': False, 'message': 'Course not found'}), 404

            return jsonify({'success': True, 'course': course}), 200
    except Exception as e:
        logger.error(f"Error fetching course details: {str(e)}")
        return jsonify({'success': False, 'message': 'Error fetching course details', 'error': str(e)}), 500

@modules_bp.route('/save-description', methods = ['POST'])
@api_key_required
def save_description():
    try:
        data = request.get_json()
        course_id = data.get('course_id')
        description = data.get('description', '')

        if not course_id:
            return jsonify({'success': False, 'message': 'Missing course_id'}), 400
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute('SELECT course_id, description FROM courses_master WHERE course_id = %s', (course_id,))
            course = cursor.fetchone()

            if not course:
                return jsonify({'success': False, 'message': 'Course not found'}), 404

            if description and description.strip():
                cursor.execute('''
                               UPDATE courses_master SET description = %s WHERE course_id = %s
                               ''', (description, course_id))
                db.commit()
            return jsonify({'success': True, 'message': 'Course description updated successfully'}), 200
    except Exception as e:
        logger.error(f"Error saving course description: {str(e)}")
        return jsonify({'success': False, 'message': 'Error saving course description', 'error': str(e)}), 500

@modules_bp.route('/', methods=['GET'])
@api_key_required
def get_modules():
    try:
        course_id = request.args.get('course_id')
        if not course_id:
            return jsonify({'success': False, 'message': 'course_id is required'}), 400
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute(
                'SELECT course_code, course_title, description FROM courses_master WHERE course_id = %s', (course_id,)
                )
            modules = cursor.fetchall()

            for module in modules:
                cursor.execute ('''
                                SELECT section_id, position, title, content
                                FROM module_sections
                                WHERE module_id = %s
                                ORDER BY position
                                ''', (module['module_id'],))
                module['sections'] = cursor.fetchall()

            return jsonify({'success': True, 'modules': modules}), 200
    except Exception as e:
        logger.error(f"Error fetching modules: {str(e)}")
        return jsonify({'success': False, 'message':'Error fetching modules', 'error':str(e)}), 500

@modules_bp.route('/update', methods=['POST'])
@api_key_required
def update_module():
    try:
        data = request.get_json()
        module_id = data.get('module_id')
        title = data.get('title')
        description = data.get('description')

        if not module_id:
            return jsonify({'success': False, 'message': 'module_id is required'}), 400

        db = get_db()
        with db.cursor() as cursor:
            cursor.execute ('SELECT content_html FROM modules_master WHERE module_id = %s', (module_id,))
            module = cursor.fetchone()

            if not module:
                return jsonify({'success': False, 'message': 'Module not found'}), 404

            current_html = module['content_html']

            if title:
                current_html = re.sub(r'<h2>.*?</h2>', f'<h2>{title}</h2>', current_html)
            if description:
                if '<div class="module-description">' in current_html:
                    # Replace existing description
                    current_html = re.sub(
                        r'<div class="module-description">.*?</div>',
                        f'<div class="module-description"><p>{description}</p></div>',
                        current_html,
                        flags=re.DOTALL
                    )
                else:
                    # Add description after title if it doesn't exist
                    current_html = re.sub(
                        r'(<h2>.*?</h2>)',
                        r'\1\n<div class="module-description"><p>' + description + '</p></div>',
                        current_html
                    )
            cursor.execute('''
                           UPDATE modules_master SET content_html = %s WHERE module_id = %s
                           ''', (current_html, module_id))
            db.commit()
            return jsonify({'success': True, 'message': 'Module updated successfully'}), 200
    except Exception as e:
        logger.error(f"Error updating module: {str(e)}")
        return jsonify({'success': False, 'message': 'Error updating module', 'error': str(e)}), 500

@modules_bp.route('/delete/<int:module_id>', methods=['DELETE'])
@api_key_required
def delete_module(module_id):
    try:
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute (' DELETE FROM modules_master WHERE module_id = %s', (module_id,))
            db.commit()

            if cursor.rowcount == 0:
                return jsonify({'success': False, 'message': 'Module not found'}), 404
            return jsonify({'success': True, 'message': 'Module deleted successfully'}), 200
    except Exception as e:
        logger.error(f"Error deleting module: {str(e)}")
        return jsonify({'success': False, 'message': 'Error deleting module', 'error': str(e)}), 500

@modules_bp.route('/reorder', methods=['POST'])
@api_key_required
def reorder_module():
    try:
        data = request.get_json()
        module_id = data.get('module_id')
        direction = data.get('direction')

        print (f"Reorder request - module_id: {module_id}, direction: {direction}")
        logger.info(f"Reorder request - module_id: {module_id}, direction: {direction}")

        db = get_db()
        with db.cursor() as cursor:
            cursor.execute('''
                           SELECT
                           position,
                           course_id
                           FROM modules_master
                           WHERE module_id = %s
                           ''', (module_id,))
            current_module = cursor.fetchone()
            if not current_module:
                return jsonify({'success': False, 'message': 'Module not found'}), 404
            current_position = current_module['position']
            course_id = current_module['course_id']

            if direction == 'up':
                target_position = current_position - 1
            else:
                target_position = current_position + 1

            print(f"Current position: {current_position}, Target position: {target_position}")
            logger.info(f"Current position: {current_position}, Target position: {target_position}")
            #check if target position exists
            cursor.execute ('''
                            SELECT module_id FROM modules_master
                            WHERE course_id = %s AND position = %s
                            ''', (course_id, target_position))
            target_module = cursor.fetchone()

            print(f"Target module: {target_module}")
            logger.info(f"Target module: {target_module}")

            if not target_module:
                return jsonify({'success': False, 'message': 'Cannot move module further in this direction'}), 400

            target_module_id = target_module['module_id']

            temp_position = 9999

            #move current to temp
            cursor.execute('''
                           UPDATE modules_master
                           SET position = %s
                           WHERE module_id = %s
                           ''', (temp_position, module_id))
            #move target to current
            cursor.execute('''
                           UPDATE modules_master
                           SET position = %s
                           WHERE module_id = %s
                           ''', (current_position, target_module_id))
            #move current (temp) to target
            cursor.execute('''
                           UPDATE modules_master
                           SET position = %s
                           WHERE module_id = %s
                           ''', (target_position, module_id))
            db.commit()
            print(f"Module {module_id} moved {direction} successfully.")
            logger.info(f"Module {module_id} moved {direction} successfully.")
            return jsonify({'success': True, 'message': f'Module moved {direction} successfully'}), 200
    except Exception as e:
        logger.error(f"Error reordering module: {str(e)}")
        return jsonify({'success': False, 'message': 'Error reordering module', 'error': str(e)}), 500


@modules_bp.route('/update-section-full', methods=['POST'])
@api_key_required
def update_section_full():
    try:
        data = request.get_json()
        section_id = data.get('section_id')
        title = data.get('title')
        content = data.get('content')

        if not section_id or not title:
            return jsonify({
                'success': False,
                'message': 'Section ID and title required',
                'error': 'Section ID and title required'
                }), 400

        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("""
                UPDATE module_sections
                SET title = %s, content = %s, updated_at = CURRENT_TIMESTAMP
                WHERE section_id = %s
            """, (title, content or '', section_id))
            db.commit()
            if cursor.rowcount == 0:
                return jsonify({'error': 'Section not found'}), 404

            return jsonify({'message': 'Section updated successfully'})
    except Exception as e:
        print(f"Update section full error: {e}")
        traceback.print_exc()
        return jsonify({
            'error': str(e),
            'success': False,
            'message': 'Error updating section'
        }), 500

@modules_bp.route('/update-section', methods=['POST'])
@api_key_required
def update_section():
    try:
        data = request.get_json()
        section_id = data.get('section_id')
        content = data.get('content')

        print(f"=== UPDATE SECTION DEBUG ===")
        print(f"Received section_id: {section_id}")
        print(f"Content length: {len(content) if content else 0}")
        print(f"Content preview: {content[:200] if content else 'None'}...")

        if not section_id or content is None:
            return jsonify({
                'error': 'Section ID and content required'
            }), 400

        db = get_db()
        with db.cursor() as cursor:
            # Check if section exists first
            cursor.execute("SELECT section_id, title FROM module_sections WHERE section_id = %s", (section_id,))
            existing = cursor.fetchone()

            if not existing:
                print(f"❌ Section {section_id} not found")
                return jsonify({
                    'success': False,
                    'message': 'Section not found',
                    'error': 'Section not found'
                }), 404

            print(f"✅ Found section: {existing['title']}")

            cursor.execute("""
                UPDATE module_sections
                SET content = %s, updated_at = CURRENT_TIMESTAMP
                WHERE section_id = %s
            """, (content, section_id))
            db.commit()
            print(f"✅ Updated {cursor.rowcount} row(s)")

            # Verify the update
            cursor.execute("SELECT content FROM module_sections WHERE section_id = %s", (section_id,))
            updated = cursor.fetchone()
            print(f"✅ Verified content length: {len(updated['content']) if updated['content'] else 0}")

            return jsonify({
                'success': True,
                'message': 'Section updated successfully'
            })
    except Exception as e:
        print(f"❌ Update section error: {e}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': 'Error updating section',
            'error': str(e)
        }), 500

@modules_bp.route('/insert-module', methods=['POST'])
@api_key_required
def insert_module():
    try:
        data = request.get_json()
        course_id = data.get('course_id')
        after_position = data.get('after_position', 0)

        if not course_id:
            return jsonify({
                'success': False,
                'message': 'Course ID required',
                'error': 'Course ID required'
            }), 400

        db = get_db()
        with db.cursor() as cursor:
            # Verify course exists
            cursor.execute("SELECT course_id FROM courses_master WHERE course_id = %s", (course_id,))
            if not cursor.fetchone():
                return jsonify({
                    'error': 'Course not found'
                }), 404

            # Update positions of existing modules that come after the insertion point
            cursor.execute("""
                UPDATE modules_master
                SET position = position + 1
                WHERE course_id = %s AND position > %s
            """, (course_id, after_position))

            # Insert new module
            new_position = after_position + 1
            default_title = f"New Module {new_position}"
            default_description = "Module description..."

            # Create HTML content for the new module
            content_html = f"""<h2>{default_title}</h2>
<div class="module-description">
    <p>{default_description}</p>
</div>"""
            cursor.execute("""
                INSERT INTO modules_master (course_id, position, content_html)
                VALUES (%s, %s, %s)
            """, (course_id, new_position, content_html))
            db.commit()
            new_module_id = cursor.lastrowid

            return jsonify({
                'success': True,
                'message': 'Module inserted successfully',
                'module_id': new_module_id,
                'position': new_position
            })
    except Exception as e:
        print(f"Insert module error: {e}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': 'Error inserting module',
            'error': str(e)
        }), 500

@modules_bp.route('/insert-section', methods=['POST'])
@api_key_required
def insert_section():
    try:
        data = request.get_json()
        module_id = data.get('module_id')
        after_position = data.get('after_position', 0)

        if not module_id:
            return jsonify({
                'success': False,
                'message': 'Module ID required',
                'error': 'Module ID required'
            }), 400

        db = get_db()
        with db.cursor() as cursor:
            # Verify module exists
            cursor.execute("SELECT module_id FROM modules_master WHERE module_id = %s", (module_id,))
            if not cursor.fetchone():
                return jsonify({
                    'success': False,
                    'message': 'Module not found',
                    'error': 'Module not found'
                }), 404

            # Update positions of existing sections that come after the insertion point
            cursor.execute("""
                UPDATE module_sections
                SET position = position + 1
                WHERE module_id = %s AND position > %s
            """, (module_id, after_position))

            # Insert new section
            new_position = after_position + 1
            default_title = f"New Section {new_position}"

            cursor.execute("""
                INSERT INTO module_sections (module_id, position, title, content)
                VALUES (%s, %s, %s, %s)
            """, (module_id, new_position, default_title, ""))
            db.commit()
            new_section_id = cursor.lastrowid

            return jsonify({
                'success': True,
                'message': 'Section inserted successfully',
                'section_id': new_section_id,
                'position': new_position
            })
    except Exception as e:
        print(f"Insert section error: {e}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': 'Error inserting section',
            'error': str(e)
        }), 500


@modules_bp.route('/sections', methods=['GET'])
@api_key_required
def get_module_sections():
    try:
        module_id = request.args.get('module_id')

        if not module_id:
            return jsonify({
                'success': False,
                'message': 'Module ID required',
                'error': 'Module ID required'
            }), 400

        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("""
                SELECT section_id, position, title, content
                FROM module_sections
                WHERE module_id = %s
                ORDER BY position
            """, (module_id,))
            sections = cursor.fetchall()

            return jsonify({
                'success': True,
                'message': f'Retrieved {len(sections)} sections',
                'sections': sections
            })
    except Exception as e:
        print(f"Get sections error: {e}")
        return jsonify({
            'success': False,
            'message': 'Error retrieving sections',
            'error': str(e)
        }), 500

@modules_bp.route('/delete-section/<int:section_id>', methods=['DELETE'])
@api_key_required
def delete_section(section_id):
    try:
        db = get_db()
        with db.cursor() as cursor:
            # Get section info before deletion
            cursor.execute("SELECT module_id, position FROM module_sections WHERE section_id = %s", (section_id,))
            section_info = cursor.fetchone()

            if not section_info:
                return jsonify({
                    'success': False,
                    'message': 'Section not found',
                    'error': 'Section not found'
                }), 404

            module_id = section_info['module_id']
            deleted_position = section_info['position']

            # Delete the section
            cursor.execute("DELETE FROM module_sections WHERE section_id = %s", (section_id,))

            if cursor.rowcount == 0:
                return jsonify({
                    'success': False,
                    'message': 'Section not found',
                    'error': 'Section not found'
                }), 404

            # Update positions of sections that come after the deleted one
            cursor.execute("""
                UPDATE module_sections
                SET position = position - 1
                WHERE module_id = %s AND position > %s
            """, (module_id, deleted_position))
            db.commit()
            return jsonify({
                'success': True,
                'message': 'Section deleted successfully'
            })
    except Exception as e:
        print(f"Delete section error: {e}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': 'Error deleting section',
            'error': str(e)
        }), 500


@modules_bp.route('/export-single-module-pdf/<int:module_id>', methods=['GET'])
@api_key_required
def export_single_module_enhanced_pdf(module_id):
    try:
        db = get_db()
        with db.cursor() as cursor:
            # Get module and course information
            cursor.execute("""
                SELECT m.content_html, c.course_code, c.course_title, c.description, m.position, m.learning_outcomes
                FROM modules_master m
                JOIN courses_master c ON m.course_id = c.course_id
                WHERE m.module_id = %s
            """, (module_id,))
            module_info = cursor.fetchone()

            if not module_info:
                return jsonify({'error': 'Module not found'}), 404

            # Get module sections
            cursor.execute("""
                SELECT section_id, title, content, position
                FROM module_sections
                WHERE module_id = %s
                ORDER BY position
            """, (module_id,))
            sections = cursor.fetchall()

            # Get module activities
            cursor.execute("""
                SELECT title, instructions, activity_type, position
                FROM module_activities
                WHERE module_id = %s
                ORDER BY position
            """, (module_id,))
            activities = cursor.fetchall()

            # Create enhanced PDF
            buffer = io.BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=18)

            # Enhanced styles
            styles = getSampleStyleSheet()

            # Custom enhanced styles
            title_style = ParagraphStyle(
                'EnhancedTitleStyle',
                parent=styles['Title'],
                fontSize=24,
                spaceAfter=30,
                alignment=1,  # Center alignment
                textColor=colors.HexColor('#1a365d'),
                fontName='Helvetica-Bold'
            )

            course_style = ParagraphStyle(
                'EnhancedCourseStyle',
                parent=styles['Heading1'],
                fontSize=18,
                spaceAfter=20,
                alignment=1,
                textColor=colors.HexColor('#2d3748'),
                fontName='Helvetica-Bold'
            )

            module_header_style = ParagraphStyle(
                'EnhancedModuleHeaderStyle',
                parent=styles['Heading1'],
                fontSize=20,
                spaceAfter=25,
                spaceBefore=15,
                textColor=colors.HexColor('#2b6cb0'),
                fontName='Helvetica-Bold',
                borderWidth=2,
                borderColor=colors.HexColor('#2b6cb0'),
                borderPadding=10,
                backColor=colors.HexColor('#ebf8ff')
            )

            section_header_style = ParagraphStyle(
                'EnhancedSectionHeaderStyle',
                parent=styles['Heading2'],
                fontSize=16,
                spaceAfter=15,
                spaceBefore=20,
                textColor=colors.HexColor('#2d3748'),
                fontName='Helvetica-Bold',
                leftIndent=20,
                borderWidth=1,
                borderColor=colors.HexColor('#e2e8f0'),
                borderPadding=8,
                backColor=colors.HexColor('#f7fafc')
            )

            content_style = ParagraphStyle(
                'EnhancedContentStyle',
                parent=styles['Normal'],
                fontSize=11,
                spaceAfter=12,
                leftIndent=30,
                rightIndent=20,
                textColor=colors.HexColor('#2d3748'),
                fontName='Helvetica'
            )

            activity_style = ParagraphStyle(
                'EnhancedActivityStyle',
                parent=styles['Normal'],
                fontSize=11,
                spaceAfter=12,
                leftIndent=30,
                rightIndent=20,
                textColor=colors.HexColor('#2d3748'),
                fontName='Helvetica',
                backColor=colors.HexColor('#fffbeb'),
                borderWidth=1,
                borderColor=colors.HexColor('#f59e0b'),
                borderPadding=10
            )

            story = []

            # Enhanced title page
            story.append(Paragraph("Learning Module", title_style))
            story.append(Spacer(1, 20))
            story.append(Paragraph(f"{module_info['course_code']} - {module_info['course_title']}", course_style))
            story.append(Spacer(1, 30))

            # Extract module title from HTML
            soup = BeautifulSoup(module_info['content_html'], 'html.parser')
            module_title_elem = soup.find('h2')
            module_title = module_title_elem.get_text() if module_title_elem else f"Module {module_info['position']}"

            story.append(Paragraph(module_title, module_header_style))
            story.append(Spacer(1, 20))

            # Module description
            desc_elem = soup.find('div', class_='module-description')
            if desc_elem:
                desc_text = desc_elem.get_text().strip()
                if desc_text:
                    story.append(Paragraph(f"<b>Module Overview:</b><br/>{desc_text}", content_style))
                    story.append(Spacer(1, 15))

            # Learning outcomes with enhanced styling
            if module_info['learning_outcomes']:
                try:
                    outcomes = json.loads(module_info['learning_outcomes'])
                    if outcomes:
                        story.append(Paragraph("<b>Learning Outcomes:</b>", section_header_style))
                        for outcome in outcomes:
                            story.append(Paragraph(f"• {outcome}", content_style))
                        story.append(Spacer(1, 20))
                except:
                    pass

            story.append(PageBreak())

            # Enhanced sections with page breaks
            for section in sections:
                story.append(Paragraph(f"Section {section['position']}: {section['title']}", section_header_style))
                story.append(Spacer(1, 15))

                if section['content']:
                    # Use BeautifulSoup to clean HTML but preserve line breaks and paragraphs
                    section_soup = BeautifulSoup(section['content'], 'html.parser')

                    # Replace HTML elements with text equivalents while preserving structure
                    for br in section_soup.find_all('br'):
                        br.replace_with('\n')

                    for p in section_soup.find_all('p'):
                        p.insert_after('\n\n')

                    for div in section_soup.find_all('div'):
                        div.insert_after('\n')

                    # Convert formatting tags
                    for tag in section_soup.find_all(['strong', 'b']):
                        if tag.get_text():
                            tag.replace_with(f"<b>{tag.get_text()}</b>")

                    for tag in section_soup.find_all(['em', 'i']):
                        if tag.get_text():
                            tag.replace_with(f"<i>{tag.get_text()}</i>")

                    for tag in section_soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
                        if tag.get_text():
                            tag.replace_with(f"<b>{tag.get_text()}</b>\n\n")

                    # Get text with preserved line breaks
                    clean_content = section_soup.get_text()

                    # Split by single newlines to preserve line structure
                    lines = clean_content.split('\n')
                    current_paragraph = []

                    for line in lines:
                        line = line.strip()
                        if line:
                            current_paragraph.append(line)
                        else:
                            # Empty line indicates paragraph break
                            if current_paragraph:
                                para_text = ' '.join(current_paragraph)
                                if para_text:
                                    story.append(Paragraph(para_text, content_style))
                                    story.append(Spacer(1, 8))
                                current_paragraph = []

                    # Handle any remaining content
                    if current_paragraph:
                        para_text = ' '.join(current_paragraph)
                        if para_text:
                            story.append(Paragraph(para_text, content_style))
                            story.append(Spacer(1, 8))

                story.append(PageBreak())  # Each section starts on new page

            # Enhanced activities section
            if activities:
                story.append(Paragraph("Module Activities", section_header_style))
                story.append(Spacer(1, 15))

                for activity in activities:
                    activity_title = f"Activity {activity['position']}: {activity['title']}"
                    story.append(Paragraph(activity_title, section_header_style))
                    story.append(Spacer(1, 10))

                    story.append(Paragraph(f"<b>Type:</b> {activity['activity_type'].replace('_', ' ').title()}", activity_style))
                    story.append(Spacer(1, 8))

                    if activity['instructions']:
                        instructions_soup = BeautifulSoup(activity['instructions'], 'html.parser')
                        clean_instructions = instructions_soup.get_text().strip()
                        story.append(Paragraph(f"<b>Instructions:</b><br/>{clean_instructions}", activity_style))

                    story.append(Spacer(1, 15))

            # Build PDF
            doc.build(story)
            buffer.seek(0)

            # Generate filename with course code, module number, and module name
            safe_module_title = re.sub(r'[^\w\s-]', '', module_title).strip()
            safe_module_title = re.sub(r'[-\s]+', ' ', safe_module_title)
            filename = f"{module_info['course_code']}_Module {module_info['position']}_{safe_module_title}.pdf"

            return send_file(
                    buffer,
                    as_attachment=True,
                    download_name=filename,
                    mimetype='application/pdf'
                )

    except Exception as e:
        print(f"Error generating enhanced module PDF: {str(e)}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': 'Error generating module PDF',
            'error': str(e)
        }), 500

@modules_bp.route('/export-pdf/<int:course_id>', methods=['GET'])
@api_key_required
def export_course_pdf(course_id):
    try:
        db = get_db()
        with db.cursor() as cursor:
                # Get course info
                cursor.execute("SELECT course_title, description FROM courses_master WHERE course_id = %s", (course_id,))
                course = cursor.fetchone()

                if not course:
                    return jsonify({'error': 'Course not found'}), 404

                # Get modules
                cursor.execute("""
                    SELECT module_id, position, content_html, learning_outcomes
                    FROM modules_master
                    WHERE course_id = %s
                    ORDER BY position
                """, (course_id,))
                modules = cursor.fetchall()

                # Create PDF
                buffer = io.BytesIO()
                doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=18)

                # Styles
                styles = getSampleStyleSheet()
                title_style = ParagraphStyle('CustomTitle', parent=styles['Heading1'], fontSize=24, spaceAfter=30)
                heading_style = ParagraphStyle('CustomHeading', parent=styles['Heading2'], fontSize=18, spaceAfter=20)
                subheading_style = ParagraphStyle('CustomSubHeading', parent=styles['Heading3'], fontSize=14, spaceAfter=12)
                code_style = ParagraphStyle('CodeBlock', parent=styles['Code'], fontName='Courier', fontSize=9, leftIndent=20, spaceAfter=2)

                story = []

                # Course title page
                story.append(Paragraph(course['course_title'], title_style))
                story.append(Spacer(1, 20))
                if course['description']:
                    story.append(Paragraph(course['description'], styles['Normal']))
                story.append(PageBreak())

                # Process each module
                for i, module in enumerate(modules):
                    # Extract module title and description
                    title_match = re.search(r'<h2>(.*?)</h2>', module['content_html'])
                    desc_match = re.search(r'<div class="module-description">\s*<p>(.*?)</p>', module['content_html'], re.DOTALL)

                    module_title = title_match.group(1) if title_match else f"Module {module['position']}"
                    module_description = desc_match.group(1).strip() if desc_match else ""

                    # Module header
                    story.append(Paragraph(module_title, heading_style))
                    if module_description:
                        story.append(Paragraph(module_description, styles['Normal']))
                        story.append(Spacer(1, 12))

                    # Learning outcomes
                    if module['learning_outcomes']:
                        outcomes = json.loads(module['learning_outcomes'])
                        story.append(Paragraph("Learning Outcomes:", subheading_style))
                        for outcome in outcomes:
                            story.append(Paragraph(f"• {outcome}", styles['Normal']))
                        story.append(Spacer(1, 12))

                    # Get sections for this module
                    cursor.execute("""
                        SELECT title, content
                        FROM module_sections
                        WHERE module_id = %s
                        ORDER BY position
                    """, (module['module_id'],))
                    sections = cursor.fetchall()

                    # Add sections
                    for section in sections:
                        if section['title'] and section['content']:
                            story.append(Paragraph(section['title'], subheading_style))

                            # Parse HTML content
                            soup = BeautifulSoup(section['content'], 'html.parser')
                            for element in soup.find_all(['p', 'h4', 'ul', 'li', 'pre']):
                                if element.name == 'h4':
                                    story.append(Paragraph(element.get_text(), subheading_style))
                                elif element.name == 'p':
                                    story.append(Paragraph(element.get_text(), styles['Normal']))
                                elif element.name == 'ul':
                                    for li in element.find_all('li'):
                                        story.append(Paragraph(f"• {li.get_text()}", styles['Normal']))
                                elif element.name == 'pre':
                                    code_text = element.get_text()
                                    # Add space before code block
                                    story.append(Spacer(1, 8))
                                    # Split code into lines and create separate paragraphs for each line
                                    code_lines = code_text.split('\n')
                                    for line in code_lines:
                                        if line.strip():  # Only add non-empty lines
                                            story.append(Paragraph(line, code_style))
                                    # Add space after code block
                                    story.append(Spacer(1, 8))

                            story.append(Spacer(1, 12))

                    # Get activities for this module
                    cursor.execute("""
                        SELECT title, instructions, activity_type
                        FROM module_activities
                        WHERE module_id = %s
                        ORDER BY position
                    """, (module['module_id'],))
                    activities = cursor.fetchall()

                    # Add activities after sections
                    if activities:
                        story.append(Paragraph("Module Activities", subheading_style))
                        for activity in activities:
                            # Activity title with type badge
                            activity_title = f"{activity['title']} ({activity['activity_type'].title()})"
                            story.append(Paragraph(activity_title, styles['Heading4']))

                            # Clean activity instructions for PDF
                            clean_instructions = activity['instructions'].replace('<br><br>', '\n\n').replace('<br>', '\n')
                            story.append(Paragraph(clean_instructions, styles['Normal']))
                            story.append(Spacer(1, 12))

                    # Add page break after each module (except the last one)
                    if i < len(modules) - 1:
                        story.append(PageBreak())

                doc.build(story)
                buffer.seek(0)

                return send_file(
                    buffer,
                    as_attachment=True,
                    download_name=f"{course['course_title']}.pdf",
                    mimetype='application/pdf'
                )

    except ImportError:
        return jsonify({
            'success': False,
            'message': 'PDF generation requires reportlab and beautifulsoup4. Install with: pip install reportlab beautifulsoup4',
            'error': 'PDF generation requires reportlab and beautifulsoup4. Install with: pip install reportlab beautifulsoup4'
        }), 500
    except Exception as e:
        print(f"PDF export error: {e}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': 'Error generating course PDF',
            'error': str(e)
        }), 500






def clean_json_string(s):
    # Remove BOM if present
    s = s.lstrip('\ufeff')

    # Fix common escape issues
    s = s.replace('\\*', '*')  # Fix the \* issue
    s = s.replace('\\"', '"')  # Fix quotes if needed

    # Remove trailing commas
    s = re.sub(r',(\s*[}\]])', r'\1', s)

    return s.strip()

@modules_bp.route('/activities', methods=['GET'])
@api_key_required
def get_activities():
    try:
        module_id = request.args.get('module_id')
        if not module_id:
            return jsonify({
                'success': False,
                'message': 'Module ID is required',
                'error': 'Module ID is required'
            }), 400

        db = get_db()
        with db.cursor() as cursor:
                cursor.execute("""
                    SELECT activity_id, position, title, instructions, activity_type
                    FROM module_activities
                    WHERE module_id = %s
                    ORDER BY position
                """, (module_id,))
                activities = cursor.fetchall()
                return jsonify({
                    'success': True,
                    'message': f'Retrieved {len(activities)} activities',
                    'activities': activities
                })

    except Exception as e:
        print(f"Get activities error: {e}")
        return jsonify({
            'success': False,
            'message': 'Error retrieving activities',
            'error': str(e)
        }), 500

@modules_bp.route('/delete-activity/<int:activity_id>', methods=['DELETE'])
@api_key_required
def delete_activity(activity_id):
    try:
        db = get_db()
        with db.cursor() as cursor:
                cursor.execute("DELETE FROM module_activities WHERE activity_id = %s", (activity_id,))
                db.commit()
                if cursor.rowcount == 0:
                    return jsonify({
                        'success': False,
                        'message': 'Activity not found',
                        'error': 'Activity not found'
                    }), 404

                return jsonify({
                    'success': True,
                    'message': 'Activity deleted successfully'
                })

    except Exception as e:
        print(f"Delete activity error: {e}")
        return jsonify({
            'success': False,
            'message': 'Error deleting activity',
            'error': str(e)
        }), 500

@modules_bp.route('/update-activity', methods=['POST'])
@api_key_required
def update_activity():
    try:
        data = request.get_json()
        activity_id = data.get('activity_id')
        title = data.get('title')
        instructions = data.get('instructions')

        if not all([activity_id, title, instructions]):
            return jsonify({
                'success': False,
                'message': 'Activity ID, title, and instructions are required',
                'error': 'Activity ID, title, and instructions are required'
            }), 400

        db = get_db()
        with db.cursor() as cursor:
                cursor.execute("""
                    UPDATE module_activities
                    SET title = %s, instructions = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE activity_id = %s
                """, (title, instructions, activity_id))
                db.commit()
                return jsonify({
                    'success': True,
                    'message': 'Activity updated successfully'
                })

    except Exception as e:
        print(f"Update activity error: {e}")
        return jsonify({
            'success': False,
            'message': 'Error updating activity',
            'error': str(e)
        }), 500


@modules_bp.route('/exam-items/manual-create', methods=['POST'])
@api_key_required
def create_manual_exam_item():
    try:
        data = request.get_json()
        section_id = data.get('section_id')
        question = data.get('question')
        option_a = data.get('option_a')
        option_b = data.get('option_b')
        option_c = data.get('option_c')
        option_d = data.get('option_d')
        correct_answer = data.get('correct_answer')

        if not all([section_id, question, option_a,
                    option_b, option_c, option_d, correct_answer]):
            return jsonify({
                'success': False,
                'message': 'All fields are required',
                'error': 'All fields are required'
            }), 400

        db = get_db()
        with db.cursor() as cursor:
            # Insert the new exam item (without difficulty column)
            cursor.execute("""
                    INSERT INTO exam_items
                    (section_id, question, option_a,
                    option_b, option_c, option_d, correct_answer)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (section_id, question, option_a,
                      option_b, option_c, option_d, correct_answer))
            db.commit()
            item_id = cursor.lastrowid

            return jsonify({
                    'success': True,
                    'message': 'Exam item created successfully',
                    'item_id': item_id
                })

    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error creating exam item',
            'error': str(e)
        }), 500


@modules_bp.route('/activity-grading/submission/<int:submission_id>', methods=['GET'])
@api_key_required
def get_single_submission_for_grading(submission_id):
    """Get a single submission for grading modal"""
    try:
        db = get_db()
        with db.cursor() as cursor:
                cursor.execute("""
                    SELECT
                        asub.submission_id,
                        asub.submission_content,
                        asub.grade,
                        asub.feedback,
                        asub.status,
                        asub.submitted_at,
                        u.full_name
                    FROM activity_submissions asub
                    JOIN users u ON asub.user_id = u.user_id
                    WHERE asub.submission_id = %s
                """, (submission_id,))

                result = cursor.fetchone()

                if result:
                    if isinstance(result, dict):
                        submission_data = {
                            'submission_id': result['submission_id'],
                            'submission_content': result['submission_content'],
                            'grade': result['grade'],
                            'feedback': result['feedback'],
                            'status': result['status'],
                            'submitted_at': result['submitted_at'].isoformat() if result['submitted_at'] else None,
                            'full_name': result['full_name']
                        }
                    else:
                        submission_data = {
                            'submission_id': result[0],
                            'submission_content': result[1],
                            'grade': result[2],
                            'feedback': result[3],
                            'status': result[4],
                            'submitted_at': result[5].isoformat() if result[5] else None,
                            'full_name': result[6]
                        }

                    return jsonify(submission_data)
                else:
                    return jsonify({'error': 'Submission not found'}), 404

    except Exception as e:
        print(f"Error fetching submission: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'Error fetching submission',
            'error': str(e)
        }), 500


@modules_bp.route('/submission-tracking', methods=['GET'])
@api_key_required
def get_submission_tracking():
    """Get submission tracking data for all course instances"""
    try:
        search_term = request.args.get('search', '')

        db = get_db()
        with db.cursor() as cursor:
                # Get course instances with basic info
                query = """
                SELECT ci.instance_id, ci.course_id, cm.course_code, cm.course_title, ci.term_code
                FROM course_instances ci
                JOIN courses_master cm ON ci.course_id = cm.course_id
                WHERE 1=1
                """

                params = []
                if search_term:
                    query += " AND (cm.course_code LIKE %s OR cm.course_title LIKE %s)"
                    search_pattern = f"%{search_term}%"
                    params.extend([search_pattern, search_pattern])

                query += " ORDER BY cm.course_code, ci.term_code"

                cursor.execute(query, params)
                results = cursor.fetchall()

                courses = []
                for result in results:
                    # Handle both tuple and dict results
                    if isinstance(result, dict):
                        instance_id = result['instance_id']
                        course_id = result['course_id']
                        course_code = result['course_code']
                        course_title = result['course_title']
                        term_code = result['term_code']
                    else:
                        instance_id = result[0]
                        course_id = result[1]
                        course_code = result[2]
                        course_title = result[3]
                        term_code = result[4]

                    # Get enrolled students count
                    cursor.execute("SELECT COUNT(*) FROM enrollments WHERE instance_id = %s", (instance_id,))
                    enrolled_result = cursor.fetchone()
                    enrolled_students = enrolled_result[0] if isinstance(enrolled_result, tuple) else enrolled_result['COUNT(*)']

                    # Get total activities for this course
                    cursor.execute("""
                        SELECT COUNT(*) FROM module_activities ma
                        JOIN modules_master mm ON ma.module_id = mm.module_id
                        WHERE mm.course_id = %s
                    """, (course_id,))
                    activities_result = cursor.fetchone()
                    total_activities = activities_result[0] if isinstance(activities_result, tuple) else activities_result['COUNT(*)']

                    # Get submitted count for this instance
                    cursor.execute("""
                        SELECT COUNT(*) FROM activity_submissions asub
                        JOIN enrollments e ON asub.user_id = e.user_id
                        JOIN module_activities ma ON asub.activity_id = ma.activity_id
                        JOIN modules_master mm ON ma.module_id = mm.module_id
                        WHERE e.instance_id = %s AND mm.course_id = %s
                    """, (instance_id, course_id))
                    submitted_result = cursor.fetchone()
                    submitted_count = submitted_result[0] if isinstance(submitted_result, tuple) else submitted_result['COUNT(*)']

                    # Get total quizzes for this course
                    cursor.execute("""
                        SELECT COUNT(DISTINCT et.exam_type_id) FROM assessment_scopes a_scope
                        JOIN exam_types et ON a_scope.exam_type_id = et.exam_type_id
                        WHERE a_scope.course_id = %s AND et.category = 'quiz'
                    """, (course_id,))
                    quiz_result = cursor.fetchone()
                    total_quizzes = quiz_result[0] if isinstance(quiz_result, tuple) else quiz_result['COUNT(DISTINCT et.exam_type_id)']

                    # Get total exams for this course
                    cursor.execute("""
                        SELECT COUNT(DISTINCT et.exam_type_id) FROM assessment_scopes a_scope
                        JOIN exam_types et ON a_scope.exam_type_id = et.exam_type_id
                        WHERE a_scope.course_id = %s AND et.category = 'exam'
                    """, (course_id,))
                    exam_result = cursor.fetchone()
                    total_exams = exam_result[0] if isinstance(exam_result, tuple) else exam_result['COUNT(DISTINCT et.exam_type_id)']

                    # Get completed counts (placeholder until exam submission tracking is implemented)
                    completed_quizzes = 0
                    completed_exams = 0

                    total_required = enrolled_students * total_activities
                    total_quizzes_required = enrolled_students * total_quizzes
                    total_exams_required = enrolled_students * total_exams

                    courses.append({
                        'instance_id': instance_id,
                        'course_code': course_code,
                        'course_title': course_title,
                        'term_code': term_code,
                        'enrolled_students': enrolled_students,
                        'total_activities': total_activities,
                        'total_required': total_required,
                        'submitted_count': submitted_count,
                        'total_quizzes': total_quizzes,
                        'total_quizzes_required': total_quizzes_required,
                        'completed_quizzes': completed_quizzes,
                        'total_exams': total_exams,
                        'total_exams_required': total_exams_required,
                        'completed_exams': completed_exams
                    })

                return jsonify({'courses': courses})

    except Exception as e:
        print(f"Error in submission tracking: {str(e)}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': 'Error in submission tracking',
            'error': str(e)
        }), 500

@modules_bp.route('/activity-grading/courses-with-pending', methods=['GET'])
@api_key_required
def get_courses_with_pending_counts():
    try:
        db = get_db()
        with db.cursor() as cursor:
                search = request.args.get('search', '')

                # Query to get course instances with pending submissions
                if search:
                    query = """
                        SELECT
                            ci.instance_id,
                            ci.course_id,
                            c.course_code,
                            c.course_title,
                            ci.term_code,
                            COUNT(CASE WHEN asub.status = 'submitted' THEN 1 END) as pending_count,
                            COUNT(DISTINCT ma.activity_id) as total_activities
                        FROM course_instances ci
                        INNER JOIN courses_master c ON ci.course_id = c.course_id
                        INNER JOIN enrollments e ON ci.instance_id = e.instance_id
                        INNER JOIN modules_master mm ON c.course_id = mm.course_id
                        INNER JOIN module_activities ma ON mm.module_id = ma.module_id
                        LEFT JOIN activity_submissions asub ON ma.activity_id = asub.activity_id AND asub.user_id = e.user_id
                        WHERE ci.end_date >= CURDATE()
                        AND (c.course_code LIKE %s OR c.course_title LIKE %s)
                        GROUP BY ci.instance_id, ci.course_id, c.course_code, c.course_title, ci.term_code
                        HAVING pending_count > 0
                        ORDER BY c.course_code, ci.term_code
                    """
                    params = [f'%{search}%', f'%{search}%']
                else:
                    query = """
                        SELECT
                            ci.instance_id,
                            ci.course_id,
                            c.course_code,
                            c.course_title,
                            ci.term_code,
                            COUNT(CASE WHEN asub.status = 'submitted' THEN 1 END) as pending_count,
                            COUNT(DISTINCT ma.activity_id) as total_activities
                        FROM course_instances ci
                        INNER JOIN courses_master c ON ci.course_id = c.course_id
                        INNER JOIN enrollments e ON ci.instance_id = e.instance_id
                        INNER JOIN modules_master mm ON c.course_id = mm.course_id
                        INNER JOIN module_activities ma ON mm.module_id = ma.module_id
                        LEFT JOIN activity_submissions asub ON ma.activity_id = asub.activity_id AND asub.user_id = e.user_id
                        WHERE ci.end_date >= CURDATE()
                        GROUP BY ci.instance_id, ci.course_id, c.course_code, c.course_title, ci.term_code
                        HAVING pending_count > 0
                        ORDER BY c.course_code, ci.term_code
                    """
                    params = []

                cursor.execute(query, params)
                courses = cursor.fetchall()

                return jsonify({'courses': courses})

    except Exception as e:
        print(f"Error in get_courses_with_pending_counts: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'Error getting courses with pending counts',
            'error': str(e)
        }), 500

@modules_bp.route('/activity-grading/pending-count/<int:course_id>', methods=['GET'])
@api_key_required
def get_pending_submissions_count(course_id):
    try:
        db = get_db()
        with db.cursor() as cursor:
                cursor.execute("""
                    SELECT COUNT(*) as count
                    FROM activity_submissions asub
                    JOIN module_activities ma ON asub.activity_id = ma.activity_id
                    JOIN modules_master mm ON ma.module_id = mm.module_id
                    WHERE mm.course_id = %s AND asub.status = 'submitted'
                """, (course_id,))

                result = cursor.fetchone()
                return jsonify({'count': result['count'] if result else 0})

    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error getting pending submissions count',
            'error': str(e)
        }), 500

@modules_bp.route('/activity-grading/activities/<int:instance_id>', methods=['GET'])
@api_key_required
def get_course_activities_for_grading(instance_id):
    try:
        db = get_db()
        with db.cursor() as cursor:
                cursor.execute("""
                    SELECT
                        ma.activity_id,
                        ma.title,
                        ma.instructions,
                        ma.position,
                        mm.module_id,
                        mm.content_html,
                        COUNT(asub.submission_id) as pending_count
                    FROM module_activities ma
                    JOIN modules_master mm ON ma.module_id = mm.module_id
                    JOIN course_instances ci ON mm.course_id = ci.course_id
                    JOIN (
                        SELECT asub.activity_id, asub.submission_id
                        FROM activity_submissions asub
                        JOIN enrollments e ON asub.user_id = e.user_id
                        WHERE e.instance_id = %s AND asub.status = 'submitted'
                    ) asub ON ma.activity_id = asub.activity_id
                    WHERE ci.instance_id = %s
                    GROUP BY ma.activity_id, ma.title, ma.instructions, ma.position, mm.module_id, mm.content_html
                    HAVING COUNT(asub.submission_id) > 0
                    ORDER BY mm.position, ma.position
                """, (instance_id, instance_id))

                activities = cursor.fetchall()

                # Extract module titles from content_html
                for activity in activities:
                    title_match = activity['content_html'].find('<h2>')
                    if title_match != -1:
                        end_match = activity['content_html'].find('</h2>', title_match)
                        if end_match != -1:
                            activity['module_title'] = activity['content_html'][title_match+4:end_match]
                        else:
                            activity['module_title'] = f"Module {activity['module_id']}"
                    else:
                        activity['module_title'] = f"Module {activity['module_id']}"

                return jsonify({'activities': activities})

    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error getting course activities for grading',
            'error': str(e)
        }), 500

@modules_bp.route('/activity-grading/submissions/<int:activity_id>', methods=['GET'])
@api_key_required
def get_activity_submissions_for_grading(activity_id):
    try:
        db = get_db()
        with db.cursor() as cursor:
                cursor.execute("""
                    SELECT
                        asub.submission_id,
                        asub.submission_content,
                        asub.submitted_at,
                        asub.status,
                        asub.grade,
                        asub.feedback,
                        u.full_name,
                        u.external_id
                    FROM activity_submissions asub
                    JOIN users u ON asub.user_id = u.user_id
                    WHERE asub.activity_id = %s
                    ORDER BY asub.submitted_at DESC
                """, (activity_id,))

                submissions = cursor.fetchall()
                return jsonify(submissions)

    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error getting activity submissions for grading',
            'error': str(e)
        }), 500

@modules_bp.route('/activity-grading/grade', methods=['POST'])
@api_key_required
def save_activity_grade():
    try:
        data = request.get_json()
        submission_id = data.get('submission_id')
        grade = data.get('grade')
        feedback = data.get('feedback', '')

        if not all([submission_id, grade is not None]):
            return jsonify({'error': 'Submission ID and grade are required'}), 400

        if grade < 0 or grade > 100:
            return jsonify({'error': 'Grade must be between 0 and 100'}), 400

        db = get_db()
        with db.cursor() as cursor:
                cursor.execute("""
                    UPDATE activity_submissions
                    SET grade = %s, feedback = %s, status = 'graded', updated_at = CURRENT_TIMESTAMP
                    WHERE submission_id = %s
                """, (grade, feedback, submission_id))
                db.commit()
                return jsonify({
                    'success': True,
                    'message': 'Grade saved successfully'
                })

    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error saving grade',
            'error': str(e)
            }), 500

@modules_bp.route('/exam-items', methods=['GET'])
@api_key_required
def get_exam_items():
    try:
        section_id = request.args.get('section_id')
        if not section_id:
            return jsonify({'error': 'Section ID required'}), 400

        db = get_db()
        with db.cursor() as cursor:
                cursor.execute("""
                    SELECT item_id, question, option_a, option_b, option_c, option_d, correct_answer
                    FROM exam_items
                    WHERE section_id = %s
                    ORDER BY created_at
                """, (section_id,))
                items = cursor.fetchall()
                return jsonify({'items': items})

    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error fetching exam items',
            'error': str(e)
            }), 500

@modules_bp.route('/update-exam-item', methods=['POST'])
@api_key_required
def update_exam_item():
    try:
        data = request.get_json()
        item_id = data.get('item_id')
        question = data.get('question')
        option_a = data.get('option_a')
        option_b = data.get('option_b')
        option_c = data.get('option_c')
        option_d = data.get('option_d')
        correct_answer = data.get('correct_answer')

        if not all([item_id, question, option_a, option_b, option_c, option_d, correct_answer]):
            return jsonify({'error': 'All fields required'}), 400

        db = get_db()
        with db.cursor() as cursor:
                cursor.execute("""
                    UPDATE exam_items
                    SET question = %s, option_a = %s, option_b = %s, option_c = %s, option_d = %s, correct_answer = %s
                    WHERE item_id = %s
                """, (question, option_a, option_b, option_c, option_d, correct_answer, item_id))
                db.commit()
                return jsonify({'success': True})

    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error updating exam item',
            'error': str(e)
            }), 500

@modules_bp.route('/delete-exam-item/<int:item_id>', methods=['DELETE'])
@api_key_required
def delete_exam_item(item_id):
    try:
        db = get_db()
        with db.cursor() as cursor:
                cursor.execute("DELETE FROM exam_items WHERE item_id = %s", (item_id,))

                return jsonify({'success': True})

    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error deleting exam item',
            'error': str(e)
            }), 500

@modules_bp.route('/export-exam-items-pdf/<int:module_id>', methods=['GET'])
@api_key_required
def export_exam_items_pdf(module_id):
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER
        import io
        from flask import make_response

        db = get_db()
        with db.cursor() as cursor:
                # Get module and course information
                cursor.execute("""
                    SELECT m.content_html, c.course_code, c.course_title, m.position
                    FROM modules_master m
                    JOIN courses_master c ON m.course_id = c.course_id
                    WHERE m.module_id = %s
                """, (module_id,))
                module_info = cursor.fetchone()

                if not module_info:
                    return jsonify({'error': 'Module not found'}), 404

                # Extract module title from HTML content
                from html import unescape
                content_text = re.sub('<[^<]+?>', '', module_info['content_html'])
                content_text = unescape(content_text)
                module_title = content_text.split('\n')[0].strip() if content_text else f"Module {module_info['position']}"

                # Get sections and their exam items
                cursor.execute("""
                    SELECT s.section_id, s.title, s.position,
                           e.item_id, e.question, e.option_a, e.option_b, e.option_c, e.option_d, e.correct_answer
                    FROM module_sections s
                    LEFT JOIN exam_items e ON s.section_id = e.section_id
                    WHERE s.module_id = %s
                    ORDER BY s.position, e.item_id
                """, (module_id,))
                results = cursor.fetchall()

                # Organize data by sections
                sections_data = {}
                for row in results:
                    section_id = row['section_id']
                    if section_id not in sections_data:
                        sections_data[section_id] = {
                            'title': row['title'],
                            'position': row['position'],
                            'items': []
                        }

                    if row['item_id']:  # Only add if there's an exam item
                        sections_data[section_id]['items'].append({
                            'question': row['question'],
                            'option_a': row['option_a'],
                            'option_b': row['option_b'],
                            'option_c': row['option_c'],
                            'option_d': row['option_d'],
                            'correct_answer': row['correct_answer']
                        })

                # Create PDF
                buffer = io.BytesIO()
                doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=18)

                # Styles
                styles = getSampleStyleSheet()
                title_style = ParagraphStyle(
                    'CustomTitle',
                    parent=styles['Heading1'],
                    fontSize=18,
                    spaceAfter=30,
                    alignment=TA_CENTER,
                    textColor=colors.HexColor('#2c3e50')
                )

                course_style = ParagraphStyle(
                    'CourseStyle',
                    parent=styles['Heading2'],
                    fontSize=14,
                    spaceAfter=20,
                    alignment=TA_CENTER,
                    textColor=colors.HexColor('#34495e')
                )

                section_style = ParagraphStyle(
                    'SectionStyle',
                    parent=styles['Heading2'],
                    fontSize=14,
                    spaceAfter=12,
                    textColor=colors.HexColor('#2980b9')
                )

                question_style = ParagraphStyle(
                    'QuestionStyle',
                    parent=styles['Normal'],
                    fontSize=11,
                    spaceAfter=8,
                    leftIndent=20,
                    fontName='Helvetica-Bold'
                )

                option_style = ParagraphStyle(
                    'OptionStyle',
                    parent=styles['Normal'],
                    fontSize=10,
                    spaceAfter=4,
                    leftIndent=40
                )

                answer_style = ParagraphStyle(
                    'AnswerStyle',
                    parent=styles['Normal'],
                    fontSize=10,
                    spaceAfter=15,
                    leftIndent=40,
                    textColor=colors.HexColor('#27ae60'),
                    fontName='Helvetica-Bold'
                )

                # Build PDF content
                story = []

                # Title page
                story.append(Paragraph("EXAM ITEMS", title_style))
                story.append(Paragraph(f"{module_info['course_code']} - {module_info['course_title']}", course_style))
                story.append(Paragraph(f"{module_title}", course_style))
                story.append(Spacer(1, 30))

                # Add sections and questions
                question_number = 1
                for section_id in sorted(sections_data.keys(), key=lambda x: sections_data[x]['position']):
                    section = sections_data[section_id]

                    if section['items']:  # Only show sections with exam items
                        story.append(Paragraph(f"Section {section['position']}: {section['title']}", section_style))
                        story.append(Spacer(1, 12))

                        for item in section['items']:
                            # Question
                            story.append(Paragraph(f"{question_number}. {item['question']}", question_style))

                            # Options
                            story.append(Paragraph(f"A. {item['option_a']}", option_style))
                            story.append(Paragraph(f"B. {item['option_b']}", option_style))
                            story.append(Paragraph(f"C. {item['option_c']}", option_style))
                            story.append(Paragraph(f"D. {item['option_d']}", option_style))

                            # Correct answer
                            story.append(Paragraph(f"Correct Answer: {item['correct_answer']}", answer_style))

                            question_number += 1

                        story.append(Spacer(1, 20))

                if question_number == 1:  # No questions found
                    story.append(Paragraph("No exam items found for this module.", styles['Normal']))

                # Build PDF
                doc.build(story)

                # Prepare response
                buffer.seek(0)
                response = make_response(buffer.getvalue())
                response.headers['Content-Type'] = 'application/pdf'
                response.headers['Content-Disposition'] = f'attachment; filename="{module_info["course_code"]}_Module_{module_info["position"]}_Exam_Items.pdf"'

                return response

    except ImportError:
        return jsonify({'error': 'PDF generation library not available. Please install reportlab.'}), 500
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error exporting exam items to PDF',
            'error': str(e)
            }), 500

@modules_bp.route('/export-all-exam-items-pdf/<int:course_id>', methods=['GET'])
@api_key_required
def export_all_exam_items_pdf(course_id):
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER
        import io
        from flask import make_response

        db = get_db()
        with db.cursor() as cursor:
                # Get course information
                cursor.execute("""
                    SELECT course_code, course_title, description
                    FROM courses_master
                    WHERE course_id = %s
                """, (course_id,))
                course_info = cursor.fetchone()

                if not course_info:
                    return jsonify({'error': 'Course not found'}), 404

                # Get all modules with their sections and exam items
                cursor.execute("""
                    SELECT m.module_id, m.content_html, m.position as module_position,
                           s.section_id, s.title as section_title, s.position as section_position,
                           e.item_id, e.question, e.option_a, e.option_b, e.option_c, e.option_d, e.correct_answer
                    FROM modules_master m
                    LEFT JOIN module_sections s ON m.module_id = s.module_id
                    LEFT JOIN exam_items e ON s.section_id = e.section_id
                    WHERE m.course_id = %s
                    ORDER BY m.position, s.position, e.item_id
                """, (course_id,))
                results = cursor.fetchall()

                # Organize data by modules and sections
                modules_data = {}
                for row in results:
                    module_id = row['module_id']
                    if module_id not in modules_data:
                        # Extract module title from HTML content
                        from html import unescape
                        content_text = re.sub('<[^<]+?>', '', row['content_html'] or '')
                        content_text = unescape(content_text)
                        module_title = content_text.split('\n')[0].strip() if content_text else f"Module {row['module_position']}"

                        modules_data[module_id] = {
                            'title': module_title,
                            'position': row['module_position'],
                            'sections': {}
                        }

                    section_id = row['section_id']
                    if section_id and section_id not in modules_data[module_id]['sections']:
                        modules_data[module_id]['sections'][section_id] = {
                            'title': row['section_title'],
                            'position': row['section_position'],
                            'items': []
                        }

                    if row['item_id'] and section_id:  # Only add if there's an exam item
                        modules_data[module_id]['sections'][section_id]['items'].append({
                            'question': row['question'],
                            'option_a': row['option_a'],
                            'option_b': row['option_b'],
                            'option_c': row['option_c'],
                            'option_d': row['option_d'],
                            'correct_answer': row['correct_answer']
                        })

                # Create PDF
                buffer = io.BytesIO()
                doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=18)

                # Styles
                styles = getSampleStyleSheet()
                title_style = ParagraphStyle(
                    'CustomTitle',
                    parent=styles['Heading1'],
                    fontSize=20,
                    spaceAfter=30,
                    alignment=TA_CENTER,
                    textColor=colors.HexColor('#2c3e50')
                )

                course_style = ParagraphStyle(
                    'CourseStyle',
                    parent=styles['Heading2'],
                    fontSize=16,
                    spaceAfter=20,
                    alignment=TA_CENTER,
                    textColor=colors.HexColor('#34495e')
                )

                module_style = ParagraphStyle(
                    'ModuleStyle',
                    parent=styles['Heading1'],
                    fontSize=16,
                    spaceAfter=15,
                    textColor=colors.HexColor('#e74c3c'),
                    borderWidth=2,
                    borderColor=colors.HexColor('#e74c3c'),
                    borderPadding=10,
                    backColor=colors.HexColor('#fdf2f2')
                )

                section_style = ParagraphStyle(
                    'SectionStyle',
                    parent=styles['Heading2'],
                    fontSize=14,
                    spaceAfter=12,
                    textColor=colors.HexColor('#2980b9')
                )

                question_style = ParagraphStyle(
                    'QuestionStyle',
                    parent=styles['Normal'],
                    fontSize=11,
                    spaceAfter=8,
                    leftIndent=20,
                    fontName='Helvetica-Bold'
                )

                option_style = ParagraphStyle(
                    'OptionStyle',
                    parent=styles['Normal'],
                    fontSize=10,
                    spaceAfter=4,
                    leftIndent=40
                )

                answer_style = ParagraphStyle(
                    'AnswerStyle',
                    parent=styles['Normal'],
                    fontSize=10,
                    spaceAfter=15,
                    leftIndent=40,
                    textColor=colors.HexColor('#27ae60'),
                    fontName='Helvetica-Bold'
                )

                # Build PDF content
                story = []

                # Title page
                story.append(Paragraph("EXAM ITEMS - ALL MODULES", title_style))
                story.append(Paragraph(f"{course_info['course_code']} - {course_info['course_title']}", course_style))
                story.append(Spacer(1, 30))

                # Add modules, sections and questions
                question_number = 1
                for module_id in sorted(modules_data.keys(), key=lambda x: modules_data[x]['position']):
                    module = modules_data[module_id]

                    # Check if module has any exam items
                    has_items = any(section['items'] for section in module['sections'].values())

                    if has_items:
                        # Add page break before each module (except first)
                        if question_number > 1:
                            story.append(PageBreak())

                        story.append(Paragraph(f"Module {module['position']}: {module['title']}", module_style))
                        story.append(Spacer(1, 20))

                        for section_id in sorted(module['sections'].keys(), key=lambda x: module['sections'][x]['position']):
                            section = module['sections'][section_id]

                            if section['items']:  # Only show sections with exam items
                                story.append(Paragraph(f"Section {section['position']}: {section['title']}", section_style))
                                story.append(Spacer(1, 12))

                                for item in section['items']:
                                    # Question
                                    story.append(Paragraph(f"{question_number}. {item['question']}", question_style))

                                    # Options
                                    story.append(Paragraph(f"A. {item['option_a']}", option_style))
                                    story.append(Paragraph(f"B. {item['option_b']}", option_style))
                                    story.append(Paragraph(f"C. {item['option_c']}", option_style))
                                    story.append(Paragraph(f"D. {item['option_d']}", option_style))

                                    # Correct answer
                                    story.append(Paragraph(f"Correct Answer: {item['correct_answer']}", answer_style))

                                    question_number += 1

                                story.append(Spacer(1, 20))

                if question_number == 1:  # No questions found
                    story.append(Paragraph("No exam items found for this course.", styles['Normal']))

                # Build PDF
                doc.build(story)

                # Prepare response
                buffer.seek(0)
                response = make_response(buffer.getvalue())
                response.headers['Content-Type'] = 'application/pdf'
                response.headers['Content-Disposition'] = f'attachment; filename="{course_info["course_code"]}_All_Modules_Exam_Items.pdf"'

                return response

    except ImportError:
        return jsonify({'error': 'PDF generation library not available. Please install reportlab.'}), 500
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error exporting all exam items to PDF',
            'error': str(e)
            }), 500

# Aiken Format TXT Export Routes
@modules_bp.route('/export-aiken-txt-single-module/<int:module_id>', methods=['GET'])
@api_key_required
def export_aiken_txt_single_module(module_id):
    try:
        db = get_db()
        with db.cursor() as cursor:
                # Get module and course info
                cursor.execute("""
                    SELECT m.content_html, m.position, c.course_code, c.course_title
                    FROM modules_master m
                    JOIN courses_master c ON m.course_id = c.course_id
                    WHERE m.module_id = %s
                """, (module_id,))

                module_info = cursor.fetchone()
                if not module_info:
                    return jsonify({'error': 'Module not found'}), 404

                # Extract module title from content_html
                content_text = BeautifulSoup(module_info['content_html'], 'html.parser').get_text() if module_info['content_html'] else ""
                module_title = content_text.split('\n')[0].strip() if content_text else f"Module {module_info['position']}"

                # Get sections and their exam items
                cursor.execute("""
                    SELECT s.section_id, s.title, s.position,
                           e.question, e.option_a, e.option_b, e.option_c, e.option_d, e.correct_answer
                    FROM module_sections s
                    LEFT JOIN exam_items e ON s.section_id = e.section_id
                    WHERE s.module_id = %s AND e.item_id IS NOT NULL
                    ORDER BY s.position, e.item_id
                """, (module_id,))

                exam_data = cursor.fetchall()

                # Generate Aiken format content
                aiken_content_lines = []

                for row in exam_data:
                    question_text = row['question'].strip()
                    option_a = row['option_a'].strip()
                    option_b = row['option_b'].strip()
                    option_c = row['option_c'].strip()
                    option_d = row['option_d'].strip()
                    correct_answer = row['correct_answer'].strip()

                    # Add question
                    aiken_content_lines.append(question_text)

                    # Add options
                    aiken_content_lines.append(f"A. {option_a}")
                    aiken_content_lines.append(f"B. {option_b}")
                    aiken_content_lines.append(f"C. {option_c}")
                    aiken_content_lines.append(f"D. {option_d}")

                    # Add correct answer
                    aiken_content_lines.append(f"ANSWER: {correct_answer}")

                    # Add blank line between questions
                    aiken_content_lines.append("")

                if not aiken_content_lines:
                    aiken_content_lines = ["No exam items found for this module."]

                # Create response
                aiken_text_content = '\n'.join(aiken_content_lines)

                response = make_response(aiken_text_content)
                response.headers['Content-Type'] = 'text/plain; charset=utf-8'
                response.headers['Content-Disposition'] = f'attachment; filename="{module_info["course_code"]}_Module_{module_info["position"]}_Aiken_Format.txt"'

                return response

    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error exporting exam items to Aiken format',
            'error': str(e)
            }), 500

@modules_bp.route('/export-aiken-txt-all-modules/<int:course_id>', methods=['GET'])
@api_key_required
def export_aiken_txt_all_modules(course_id):
    try:
        db = get_db()
        with db.cursor() as cursor:
                # Get course info
                cursor.execute("""
                    SELECT course_code, course_title
                    FROM courses_master
                    WHERE course_id = %s
                """, (course_id,))

                course_info = cursor.fetchone()
                if not course_info:
                    return jsonify({'error': 'Course not found'}), 404

                # Get all modules with their sections and exam items
                cursor.execute("""
                    SELECT m.module_id, m.content_html, m.position as module_position,
                           s.section_id, s.title as section_title, s.position as section_position,
                           e.question, e.option_a, e.option_b, e.option_c, e.option_d, e.correct_answer
                    FROM modules_master m
                    LEFT JOIN module_sections s ON m.module_id = s.module_id
                    LEFT JOIN exam_items e ON s.section_id = e.section_id
                    WHERE m.course_id = %s AND e.item_id IS NOT NULL
                    ORDER BY m.position, s.position, e.item_id
                """, (course_id,))

                exam_data = cursor.fetchall()

                # Generate Aiken format content
                aiken_content_lines = []
                current_module_id = None

                for row in exam_data:
                    # Add module header when we encounter a new module
                    if current_module_id != row['module_id']:
                        current_module_id = row['module_id']

                        # Extract module title from content_html
                        content_text = BeautifulSoup(row['content_html'], 'html.parser').get_text() if row['content_html'] else ""
                        module_title = content_text.split('\n')[0].strip() if content_text else f"Module {row['module_position']}"

                        # Add module separator (but not for the first module)
                        if len(aiken_content_lines) > 0:
                            aiken_content_lines.append("")
                            aiken_content_lines.append("=" * 50)

                        aiken_content_lines.append(f"MODULE {row['module_position']}: {module_title}")
                        aiken_content_lines.append("=" * 50)
                        aiken_content_lines.append("")

                    question_text = row['question'].strip()
                    option_a = row['option_a'].strip()
                    option_b = row['option_b'].strip()
                    option_c = row['option_c'].strip()
                    option_d = row['option_d'].strip()
                    correct_answer = row['correct_answer'].strip()

                    # Add question
                    aiken_content_lines.append(question_text)

                    # Add options
                    aiken_content_lines.append(f"A. {option_a}")
                    aiken_content_lines.append(f"B. {option_b}")
                    aiken_content_lines.append(f"C. {option_c}")
                    aiken_content_lines.append(f"D. {option_d}")

                    # Add correct answer
                    aiken_content_lines.append(f"ANSWER: {correct_answer}")

                    # Add blank line between questions
                    aiken_content_lines.append("")

                if not aiken_content_lines:
                    aiken_content_lines = ["No exam items found for this course."]

                # Create response
                aiken_text_content = '\n'.join(aiken_content_lines)

                response = make_response(aiken_text_content)
                response.headers['Content-Type'] = 'text/plain; charset=utf-8'
                response.headers['Content-Disposition'] = f'attachment; filename="{course_info["course_code"]}_All_Modules_Aiken_Format.txt"'

                return response

    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error exporting exam items to Aiken format',
            'error': str(e)
            }), 500
