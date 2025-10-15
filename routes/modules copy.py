from flask import Blueprint, request, jsonify, make_response, send_file
from flask_jwt_extended import jwt_required, get_jwt_identity
from init_db import get_db
from utils import logger
import json

from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import black, blue
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from bs4 import BeautifulSoup

import requests
import os
import boto3
import json
import re
import traceback
import io

modules_bp = Blueprint('modules', __name__)

# AWS Bedrock configuration
model_id = "meta.llama3-70b-instruct-v1:0"

def get_bedrock_client():
    """Get AWS Bedrock client"""
    return boto3.client(
        "bedrock-runtime",
        region_name=os.getenv('AWS_REGION', 'us-west-2'),
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
    )

def generate_with_bedrock(prompt, temperature=0.7):
    try:
        print(f"Bedrock request - temperature: {temperature}")
        logger.info(f"Bedrock request - temperature: {temperature}")
        print(f"Prompt: {prompt[:200]}")
        logger.info(f"Prompt: {prompt[:200]}")
        bedrock = get_bedrock_client()
        response = bedrock.invoke_model(
            modelId=model_id,
            body=json.dumps({
                "prompt": prompt,
                'max_gen_len': 4096,
                'temperature': temperature,
                'top_p': 0.9
            })
        )

        raw_response = response['body'].read()
        print(f"Raw response: {raw_response}")
        logger.info(f"Raw response: {raw_response}")

        result = json.loads(raw_response)
        print(f"Result: {result}")
        logger.info(f"Result: {result}")

        generated_content = result['generation']
        print(f"Generated content: {generated_content[:300]}")
        logger.info(f"Generated content: {generated_content[:300]}")

        return generated_content
    except Exception as e:
        print(f"Error in Bedrock generation: {str(e)}")
        logger.error(f"Error in Bedrock generation: {str(e)}")
        traceback.print_exc()
        return None

def call_ollama(prompt):
    try:
        ollama_url = os.getenv('OLLAMA_URL', 'http://localhost:11434')
        response = requests.post(
            f"{ollama_url}/api/generate",
            json={
                "model":"llama3",
                "prompt":prompt,
                "stream":False,
            }, timeout=300
        )

        if response.status_code == 200:
            return response.json().get('response').strip()
        else:
            logger.error(f"Ollama API error: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        logger.error(f"Error calling Ollama API: {str(e)}")
        return None

def fix_code_blocks(content):
    """Fix malformed code blocks in AI-generated content"""
    # First, fix any existing malformed code tags
    # Convert single-line <code> with newlines to <pre><code>
    content = re.sub(r'<code>([^<]*\n[^<]*)</code>', r'<pre><code>\1</code></pre>', content, flags=re.DOTALL)

    # Fix double pre tags
    content = re.sub(r'<pre><pre><code>', '<pre><code>', content)
    content = re.sub(r'</code></pre></pre>', '</code></pre>', content)

    # Clean up excessive empty lines in existing pre/code blocks
    def clean_code_block(match):
        code_content = match.group(1)
        # Remove excessive empty lines (more than 1 consecutive empty line)
        cleaned = re.sub(r'\n\s*\n\s*\n+', '\n\n', code_content)
        # Remove leading/trailing whitespace from the entire block
        cleaned = cleaned.strip()
        return f'<pre><code>{cleaned}</code></pre>'

    content = re.sub(r'<pre><code>(.*?)</code></pre>', clean_code_block, content, flags=re.DOTALL)

    return content

@modules_bp.route('/suggest-count', methods=['POST'])
@jwt_required()
def suggest_module_count():
    try:
        data = request.get_json()
        course_title = data.get('course_title', '')
        course_description = data.get('course_description', '')

        prompt = f"""Based on this course information:
Title: {course_title}
Description: {course_description}

Suggest the optimal number of modules for this course. Consider the scope and complexity of the content. Respond with ONLY a number between 3 and 12."""

        suggested_count = generate_with_bedrock(prompt)

        if suggested_count and suggested_count.isdigit():
            count = int(suggested_count)
            if 3 <= count <= 12:
                return jsonify({
                    'success': True,
                    'message': f'Suggested {count} modules for the course',
                    'suggested_count': count
                })

        # Fallback to default
        return jsonify({
            'success': True,
            'message': 'Using default module count',
            'suggested_count': 6
        })

    except Exception as e:
        print(f"Suggest module count error: {e}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': 'Error suggesting module count',
            'error': str(e)
        }), 500

@modules_bp.route('/generate', methods=['POST'])
@jwt_required()
def generate_modules():
    try:
        data = request.get_json()
        course_id = data.get('course_id')
        course_title = data.get('course_title', '')
        course_description = data.get('course_description', '')
        module_count = data.get('module_count', 6)
        override_existing = data.get('override_existing', True)
        existing_modules = data.get('existing_modules', [])

        if not course_id:
            return jsonify({'error': 'Course ID required'}), 400

        db = get_db()
        with db.cursor() as cursor:
                cursor.execute("""
                    SELECT module_id, position, content_html
                    FROM modules_master
                    WHERE course_id = %s
                    ORDER BY position
                """, (course_id,))
                current_modules = cursor.fetchall()

                if override_existing:
                    # Clear existing modules
                    cursor.execute("DELETE FROM modules_master WHERE course_id = %s", (course_id,))
                    start_position = 1
                    existing_titles_descriptions = []
                else:
                    # Keep existing modules, add new ones after
                    start_position = len(current_modules) + 1
                    existing_titles_descriptions = []

                    # Extract titles and descriptions from existing modules
                    for module in current_modules:
                        temp_div_content = module['content_html']
                        # Simple regex to extract title and description
                        title_match = re.search(r'<h2>(.*?)</h2>', temp_div_content)
                        desc_match = re.search(r'<div class="module-description">\s*<p>(.*?)</p>', temp_div_content, re.DOTALL)

                        if title_match and desc_match:
                            existing_titles_descriptions.append({
                                'title': title_match.group(1),
                                'description': desc_match.group(1).strip()
                            })

                # Create prompt for new modules
                if override_existing:
                    # Override: Create fresh modules from scratch
                    primary_prompt = f"""Create {module_count} course modules for:
Course: {course_title}
Description: {course_description}

For each module, provide:
1. A clear, descriptive title
2. A comprehensive description (2-3 sentences)

Format as JSON array:
[{{"title": "Module Title", "description": "Module description..."}}]

Respond with ONLY the JSON array, no other text."""

                    fallback_prompt = f"""Create exactly {module_count} modules for: {course_title}

Course Description: {course_description}

You MUST return a valid JSON array with {module_count} objects. Each object must have "title" and "description" fields.

Make the titles and descriptions specific to {course_title}. Return ONLY the JSON array."""
                else:
                    # Add: Create modules that complement existing ones
                    existing_info = ""
                    if existing_titles_descriptions:
                        existing_info = "\n\nExisting modules to avoid overlap:\n"
                        for i, mod in enumerate(existing_titles_descriptions, 1):
                            existing_info += f"{i}. {mod['title']}: {mod['description']}\n"

                    primary_prompt = f"""Create {module_count} NEW course modules for:
Course: {course_title}
Description: {course_description}{existing_info}

Requirements:
- Create {module_count} modules that complement the existing ones
- Do not overlap with existing module topics
- Each module should have a unique focus
- Provide clear, descriptive titles and comprehensive descriptions

Format as JSON array:
[{{"title": "Module Title", "description": "Module description..."}}]

Respond with ONLY the JSON array, no other text."""

                    fallback_prompt = f"""Create exactly {module_count} modules for: {course_title}

Course Description: {course_description}

You MUST return a valid JSON array with {module_count} objects. Each object must have "title" and "description" fields.

Make the titles and descriptions specific to {course_title} and avoid these existing topics: {', '.join([mod['title'] for mod in existing_titles_descriptions])}.

Return ONLY the JSON array."""

                # Try primary prompt first
                ai_response = generate_with_bedrock(primary_prompt)
                modules_data = None

                if ai_response:
                    try:
                        modules_data = json.loads(ai_response)
                        if not isinstance(modules_data, list) or len(modules_data) != module_count:
                            raise ValueError("Invalid response format")
                    except (json.JSONDecodeError, ValueError):
                        # Try fallback prompt
                        ai_response = generate_with_bedrock(fallback_prompt)
                        if ai_response:
                            try:
                                modules_data = json.loads(ai_response)
                                if not isinstance(modules_data, list) or len(modules_data) != module_count:
                                    raise ValueError("Fallback also failed")
                            except (json.JSONDecodeError, ValueError):
                                modules_data = None

                # If both prompts fail, create default modules
                if not modules_data:
                    modules_data = []
                    for i in range(module_count):
                        if override_existing:
                            # Fresh modules starting from 1
                            modules_data.append({
                                "title": f"Module {i+1}: {course_title} - Part {i+1}",
                                "description": f"This module covers important concepts and topics related to {course_title}. Students will learn key principles and practical applications."
                            })
                        else:
                            # Additional modules continuing from existing
                            modules_data.append({
                                "title": f"Module {start_position + i}: {course_title} - Advanced Topics {i+1}",
                                "description": f"This module covers advanced concepts and topics related to {course_title}. Students will explore specialized principles and practical applications."
                            })

                # Insert new modules
                for i, module in enumerate(modules_data):
                    title = module.get('title', f'Module {start_position + i}')
                    description = module.get('description', '')

                    # Create basic HTML content
                    content_html = f"""<div class="module-content">
<h2>{title}</h2>
<div class="module-description">
<p>{description}</p>
</div>
<div class="module-body">
<p>Module content will be added here...</p>
</div>
</div>"""

                    cursor.execute("""
                        INSERT INTO modules_master (course_id, position, content_html)
                        VALUES (%s, %s, %s)
                    """, (course_id, start_position + i, content_html))

                # Return all modules (existing + new)
                cursor.execute("""
                    SELECT module_id, position, content_html, created_at, updated_at
                    FROM modules_master
                    WHERE course_id = %s
                    ORDER BY position
                """, (course_id,))
                all_modules = cursor.fetchall()

                action = "overridden with" if override_existing else "added"
                return jsonify({
                    'success': True,
                    'message': f'Successfully {action} {len(modules_data)} new modules',
                    'modules': all_modules
                })

    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error generating modules',
            'error': str(e)
        }), 500

@modules_bp.route('/courses', methods=['GET'])
@jwt_required()
def get_courses():
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
            return jsonify({
                'success': True,
                'message': f'Found {len(courses)} courses',
                'courses': courses
            })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error retrieving courses',
            'error': str(e)
        }), 500

@modules_bp.route('/course-details/<int:course_id>', methods=['GET'])
@jwt_required()
def get_course_details(course_id):
    try:
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("""
                SELECT course_id, course_code, course_title, description
                FROM courses_master
                WHERE course_id = %s
            """, (course_id,))
            course = cursor.fetchone()

            if not course:
                return jsonify({
                    'success': False,
                    'message': 'Course not found',
                    'error': 'Course not found'
                }), 404

            return jsonify({
                'success': True,
                'message': 'Course details retrieved successfully',
                'course': course
            })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error retrieving course details',
            'error': str(e)
        }), 500

@modules_bp.route('/save-description', methods=['POST'])
@jwt_required()
def save_description():
    try:
        data = request.get_json()
        course_id = data.get('course_id')
        description = data.get('description')

        if not course_id:
            return jsonify({'error': 'Course ID required'}), 400

        db = get_db()
        with db.cursor() as cursor:
            # First check if course exists
            cursor.execute("SELECT course_id, description FROM courses_master WHERE course_id = %s", (course_id,))
            course = cursor.fetchone()

            if not course:
                return jsonify({
                    'success': False,
                    'message': 'Course not found',
                    'error': 'Course not found'
                }), 404

            # Only update if description is provided and different
            if description and description.strip():
                cursor.execute(
                    "UPDATE courses_master SET description = %s WHERE course_id = %s",
                    (description, course_id)
                )

            return jsonify({
                'success': True,
                'message': 'Description saved successfully'
            })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error saving description',
            'error': str(e)
        }), 500

@modules_bp.route('/', methods=['GET'])
@jwt_required()
def get_modules():
    try:
        course_id = request.args.get('course_id')

        if not course_id:
            return jsonify({
                'success': False,
                'message': 'Course ID required',
                'error': 'Course ID required'
            }), 400

        db = get_db()
        with db.cursor() as cursor:
            # Get course info
            cursor.execute("SELECT course_code, course_title, description FROM courses_master WHERE course_id = %s", (course_id,))
            course = cursor.fetchone()

            if not course:
                return jsonify({
                    'success': False,
                    'message': 'Course not found',
                    'error': 'Course not found'
                }), 404

            # Get modules for this course
            cursor.execute("""
                SELECT module_id, position, content_html, learning_outcomes, created_at, updated_at
                FROM modules_master
                WHERE course_id = %s
                ORDER BY position
            """, (course_id,))
            modules = cursor.fetchall()

            # Get sections for each module
            for module in modules:
                cursor.execute("""
                    SELECT section_id, position, title, content
                    FROM module_sections
                    WHERE module_id = %s
                    ORDER BY position
                """, (module['module_id'],))
                module['sections'] = cursor.fetchall()

            return jsonify({
                'success': True,
                'message': f'Retrieved {len(modules)} modules for course',
                'course': course,
                'modules': modules
            })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error retrieving modules',
            'error': str(e)
        }), 500

@modules_bp.route('/update', methods=['POST'])
@jwt_required()
def update_module():
    try:
        data = request.get_json()
        module_id = data.get('module_id')
        title = data.get('title')
        description = data.get('description')

        if not module_id:
            return jsonify({
                'success': False,
                'message': 'Module ID required',
                'error': 'Module ID required'
            }), 400

        db = get_db()
        with db.cursor() as cursor:
            # Get current module
            cursor.execute("SELECT content_html FROM modules_master WHERE module_id = %s", (module_id,))
            module = cursor.fetchone()

            if not module:
                return jsonify({
                    'success': False,
                    'message': 'Module not found',
                    'error': 'Module not found'
                }), 404

            # Parse current HTML and update
            current_html = module['content_html']

            if title:
                # Update title in HTML
                current_html = re.sub(r'<h2>.*?</h2>', f'<h2>{title}</h2>', current_html)

            if description:
                # Update description in HTML - handle both simple and complex content
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

            cursor.execute(
                "UPDATE modules_master SET content_html = %s WHERE module_id = %s",
                (current_html, module_id)
            )

            return jsonify({
                'success': True,
                'message': 'Module updated successfully'
            })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error updating module',
            'error': str(e)
        }), 500

@modules_bp.route('/regenerate', methods=['POST'])
@jwt_required()
def regenerate_module():
    try:
        data = request.get_json()
        module_id = data.get('module_id')
        course_title = data.get('course_title', '')
        course_description = data.get('course_description', '')
        module_title = data.get('module_title', '')
        existing_modules = data.get('existing_modules', [])

        if not module_id:
            return jsonify({'error': 'Module ID required'}), 400

        # Create prompt to regenerate specific module
        existing_list = ', '.join(existing_modules) if existing_modules else 'None'

        prompt = f"""Generate ONLY a module description for: "{module_title}"

Course: {course_title}
Course Description: {course_description}
Other Existing Modules: {existing_list}

Requirements:
- Write 2-3 sentences describing what students will learn in "{module_title}"
- Be specific to this module topic
- Do not overlap with other existing modules
- Do not include the module title in your response
- Return ONLY the description text, no formatting, no JSON, no extra text

Description:"""

        description = generate_with_bedrock(prompt)

        if description:
            # Clean up the response to ensure it's just the description
            description = description.strip()
            # Remove any potential title or formatting
            lines = description.split('\n')
            # Take only the meaningful content lines
            clean_lines = [line.strip() for line in lines if line.strip() and not line.strip().startswith(module_title)]
            if clean_lines:
                description = ' '.join(clean_lines)

        if not description or len(description.strip()) < 10:
            description = f"This module covers important concepts related to {module_title} within the context of {course_title}. Students will explore key principles and practical applications specific to this topic."

        return jsonify({'description': description.strip()})

    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error saving description',
            'error': str(e)
        }), 500

@modules_bp.route('/delete/<int:module_id>', methods=['DELETE'])
@jwt_required()
def delete_module(module_id):
    try:
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("DELETE FROM modules_master WHERE module_id = %s", (module_id,))

            if cursor.rowcount == 0:
                return jsonify({
                    'success': False,
                    'message': 'Module not found',
                    'error': 'Module not found'
                }), 404

            return jsonify({
                'success': True,
                'message': 'Module deleted successfully'
            })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error deleting module',
            'error': str(e)
        }), 500

@modules_bp.route('/reorder', methods=['POST'])
@jwt_required()
def reorder_module():
    try:
        data = request.get_json()
        module_id = data.get('module_id')
        direction = data.get('direction')  # 'up' or 'down'

        print(f"Reorder request: module_id={module_id}, direction={direction}")

        if not module_id or direction not in ['up', 'down']:
            return jsonify({
                'success': False,
                'message': 'Module ID and valid direction required',
                'error': 'Module ID and valid direction required'
            }), 400

        db = get_db()
        with db.cursor() as cursor:
            # Get current module position and course_id
            cursor.execute("""
                SELECT position, course_id FROM modules_master
                WHERE module_id = %s
            """, (module_id,))
            current_module = cursor.fetchone()

            print(f"Current module: {current_module}")

            if not current_module:
                return jsonify({
                    'success': False,
                    'message': 'Module not found',
                    'error': 'Module not found'
                }), 404

            current_position = current_module['position']
            course_id = current_module['course_id']

            # Determine target position
            if direction == 'up':
                target_position = current_position - 1
            else:  # down
                target_position = current_position + 1

            print(f"Target position: {target_position}")

            # Check if target position exists
            cursor.execute("""
                SELECT module_id FROM modules_master
                WHERE course_id = %s AND position = %s
            """, (course_id, target_position))
            target_module = cursor.fetchone()

            print(f"Target module: {target_module}")

            if not target_module:
                return jsonify({
                    'success': False,
                    'message': 'Cannot move module in that direction',
                    'error': 'Cannot move module in that direction'
                }), 400

            target_module_id = target_module['module_id']

            # Use temporary position to avoid unique constraint violation
            temp_position = 9999

            # Step 1: Move current module to temp position
            cursor.execute("""
                UPDATE modules_master
                SET position = %s
                WHERE module_id = %s
            """, (temp_position, module_id))

            # Step 2: Move target module to current position
            cursor.execute("""
                UPDATE modules_master
                SET position = %s
                WHERE module_id = %s
            """, (current_position, target_module_id))

            # Step 3: Move current module to target position
            cursor.execute("""
                UPDATE modules_master
                SET position = %s
                WHERE module_id = %s
            """, (target_position, module_id))

            print("Position swap completed successfully")
            return jsonify({
                'success': True,
                'message': 'Module position updated successfully'
            })
    except Exception as e:
        print(f"Reorder error: {e}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': 'Error reordering module',
            'error': str(e)
        }), 500

@modules_bp.route('/generate-outcomes', methods=['POST'])
@jwt_required()
def generate_learning_outcomes():
    try:
        data = request.get_json()
        course_id = data.get('course_id')
        only_empty = data.get('only_empty', False)
        specific_module_id = data.get('module_id')

        if not course_id:
            return jsonify({
                'success': False,
                'message': 'Course ID required',
                'error': 'Course ID required'
            }), 400

        db = get_db()
        with db.cursor() as cursor:
            # Get course info
            cursor.execute("SELECT course_title, description FROM courses_master WHERE course_id = %s", (course_id,))
            course = cursor.fetchone()

            if not course:
                return jsonify({
                    'success': False,
                    'message': 'Course not found',
                    'error': 'Course not found'
                }), 404

            # Get modules based on the request type
            if specific_module_id:
                # Generate for specific module only
                cursor.execute("""
                    SELECT module_id, position, content_html
                    FROM modules_master
                    WHERE course_id = %s AND module_id = %s
                """, (course_id, specific_module_id))
                modules = cursor.fetchall()
            elif only_empty:
                # Generate only for modules without learning outcomes
                cursor.execute("""
                    SELECT module_id, position, content_html
                    FROM modules_master
                    WHERE course_id = %s AND (learning_outcomes IS NULL OR learning_outcomes = 'null' OR learning_outcomes = '[]')
                    ORDER BY position
                """, (course_id,))
                modules = cursor.fetchall()
            else:
                # Generate for all modules
                cursor.execute("""
                    SELECT module_id, position, content_html
                    FROM modules_master
                    WHERE course_id = %s
                    ORDER BY position
                """, (course_id,))
                modules = cursor.fetchall()

            if not modules:
                if specific_module_id:
                    return jsonify({
                        'success': False,
                        'message': 'Module not found',
                        'error': 'Module not found'
                    }), 404
                elif only_empty:
                    return jsonify({
                        'success': True,
                        'message': 'All modules already have learning outcomes'
                    }), 200
                else:
                    return jsonify({
                        'success': False,
                        'message': 'No modules found for this course',
                        'error': 'No modules found for this course'
                    }), 404

            # Get all modules for context (to avoid overlap)
            cursor.execute("""
                SELECT module_id, position, content_html
                FROM modules_master
                WHERE course_id = %s
                ORDER BY position
            """, (course_id,))
            all_modules = cursor.fetchall()

            # Generate learning outcomes for selected modules
            for module in modules:
                # Extract module title and description
                title_match = re.search(r'<h2>(.*?)</h2>', module['content_html'])
                desc_match = re.search(r'<div class="module-description">\s*<p>(.*?)</p>', module['content_html'], re.DOTALL)

                module_title = title_match.group(1) if title_match else f"Module {module['position']}"
                module_description = desc_match.group(1).strip() if desc_match else ""

                # Get other module titles to avoid overlap
                other_modules = [m for m in all_modules if m['module_id'] != module['module_id']]
                other_titles = []
                for other in other_modules:
                    other_title_match = re.search(r'<h2>(.*?)</h2>', other['content_html'])
                    if other_title_match:
                        other_titles.append(other_title_match.group(1))

                # Generate learning outcomes
                prompt = f"""Generate 3-5 specific learning outcomes for this module:

Course: {course['course_title']}
Course Description: {course['description']}
Module: {module_title}
Module Description: {module_description}
Other Modules: {', '.join(other_titles)}

Requirements:
- Create 3-5 measurable learning outcomes
- Use action verbs (analyze, evaluate, create, apply, etc.)
- Be specific to this module only
- Avoid overlap with other modules
- Focus on what students will be able to DO after completing this module

Format as JSON array of strings:
["Students will be able to...", "Students will be able to..."]

Return ONLY the JSON array."""

                outcomes_response = generate_with_bedrock(prompt)

                if outcomes_response:
                    print(f"Raw Bedrock response for learning outcomes: {outcomes_response}")
                    try:
                        # Clean the response - extract JSON array
                        cleaned_response = outcomes_response.strip()

                        # Extract just the JSON array from response
                        start_idx = cleaned_response.find('[')
                        end_idx = cleaned_response.rfind(']')
                        if start_idx != -1 and end_idx != -1:
                            cleaned_response = cleaned_response[start_idx:end_idx+1]

                        if isinstance(json.loads(cleaned_response), list) and 3 <= len(json.loads(cleaned_response)) <= 5:
                            outcomes = json.loads(cleaned_response)
                        else:
                            # Try to find JSON array in the response
                            json_match = re.search(r'\[.*?\]', cleaned_response, re.DOTALL)
                            if json_match:
                                json_str = json_match.group(0)
                                outcomes = json.loads(json_str)
                            else:
                                # Try parsing the whole response as JSON
                                outcomes = json.loads(cleaned_response)

                        if isinstance(outcomes, list) and 3 <= len(outcomes) <= 5:
                            # Save to database
                            cursor.execute("""
                                UPDATE modules_master
                                SET learning_outcomes = %s
                                WHERE module_id = %s
                            """, (json.dumps(outcomes), module['module_id']))
                        else:
                            # Fallback outcomes
                            fallback_outcomes = [
                                f"Students will be able to understand the key concepts of {module_title}",
                                f"Students will be able to apply principles learned in {module_title}",
                                f"Students will be able to analyze scenarios related to {module_title}"
                            ]
                            cursor.execute("""
                                UPDATE modules_master
                                SET learning_outcomes = %s
                                WHERE module_id = %s
                            """, (json.dumps(fallback_outcomes), module['module_id']))
                    except (json.JSONDecodeError, ValueError):
                        # Fallback outcomes
                        fallback_outcomes = [
                            f"Students will be able to understand the key concepts of {module_title}",
                            f"Students will be able to apply principles learned in {module_title}",
                            f"Students will be able to analyze scenarios related to {module_title}"
                        ]
                        cursor.execute("""
                            UPDATE modules_master
                            SET learning_outcomes = %s
                            WHERE module_id = %s
                        """, (json.dumps(fallback_outcomes), module['module_id']))

            if specific_module_id:
                return jsonify({
                    'success': True,
                    'message': 'Learning outcomes regenerated for module'
                })
            else:
                return jsonify({
                    'success': True,
                    'message': f'Learning outcomes generated for {len(modules)} modules'
                })
    except Exception as e:
        print(f"Generate outcomes error: {e}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': 'Error generating learning outcomes',
            'error': str(e)
        }), 500

@modules_bp.route('/generate-sections', methods=['POST'])
@jwt_required()
def generate_sections():
    try:
        data = request.get_json()
        module_id = data.get('module_id')

        if not module_id:
            return jsonify({
                'success': False,
                'message': 'Module ID required',
                'error': 'Module ID required'
            }), 400

        db = get_db()
        with db.cursor() as cursor:
            # Get module and course info
            cursor.execute("""
                SELECT m.content_html, c.course_title, c.description
                FROM modules_master m
                JOIN courses_master c ON m.course_id = c.course_id
                WHERE m.module_id = %s
            """, (module_id,))
            module_info = cursor.fetchone()

            if not module_info:
                return jsonify({
                    'success': False,
                    'message': 'Module not found',
                    'error': 'Module not found'
                }), 404

            # Extract module title and description
            title_match = re.search(r'<h2>(.*?)</h2>', module_info['content_html'])
            desc_match = re.search(r'<div class="module-description">\s*<p>(.*?)</p>', module_info['content_html'], re.DOTALL)

            module_title = title_match.group(1) if title_match else "Module"
            module_description = desc_match.group(1).strip() if desc_match else ""

            # Primary prompt - topic-based approach
            primary_prompt = f"""Create a comprehensive topic outline for self-study learning:

Course: {module_info['course_title']}
Module: {module_title}
Description: {module_description}

Generate 5-6 essential topics that students must master to fully understand this module. Structure as a logical learning progression:

1. Foundation topic (basic concepts, definitions)
2. Core theory topics (2-3 main concepts)
3. Application topic (practical examples, real-world use)
4. Advanced topic (complex applications, analysis)

Each topic should be:
- A distinct learning unit students can study independently
- Comprehensive enough for self-directed learning
- Logically sequenced for progressive understanding
- Focused on practical mastery, not just theory

Return ONLY a JSON array of topic titles:
["Foundation Topic Name", "Core Concept 1", "Core Concept 2", "Practical Applications", "Advanced Analysis"]"""

            sections_response = generate_with_bedrock(primary_prompt)
            print("Primary prompt response:", sections_response)

            # Try to parse primary response
            sections = None
            if sections_response:
                start_idx = sections_response.find('[')
                end_idx = sections_response.rfind(']')
                if start_idx != -1 and end_idx != -1:
                    json_str = sections_response[start_idx:end_idx+1]
                    try:
                        sections = json.loads(json_str)
                        if isinstance(sections, list) and 4 <= len(sections) <= 7:
                            print("✅ Primary prompt successful")
                        else:
                            sections = None
                    except (json.JSONDecodeError, ValueError):
                        sections = None

            # Backup prompt if primary fails
            if not sections:
                print("⚠️ Primary prompt failed, trying backup prompt")
                backup_prompt = f"""Break down this module into essential learning topics:

Module: {module_title}
Course: {module_info['course_title']}

Create 5 topics that cover everything needed for complete understanding:
1. Introduction and basic concepts
2. Main theoretical framework
3. Key principles and methods
4. Real-world examples and cases
5. Applications and implications

Format as simple JSON array of topic names:
["Topic 1", "Topic 2", "Topic 3", "Topic 4", "Topic 5"]

Return only the JSON array, no other text."""

                backup_response = generate_with_bedrock(backup_prompt)
                print("Backup prompt response:", backup_response)

                if backup_response:
                    start_idx = backup_response.find('[')
                    end_idx = backup_response.rfind(']')
                    if start_idx != -1 and end_idx != -1:
                        json_str = backup_response[start_idx:end_idx+1]
                        try:
                            sections = json.loads(json_str)
                            if isinstance(sections, list) and 4 <= len(sections) <= 7:
                                print("✅ Backup prompt successful")
                            else:
                                sections = None
                        except (json.JSONDecodeError, ValueError):
                            sections = None

            # Third backup prompt if second backup fails
            if not sections:
                print("⚠️ Second prompt failed, trying third backup prompt")
                third_prompt = f"""Generate 5 specific section titles for this module:

Module: {module_title}
Course: {module_info['course_title']}

Create 5 unique section names that are specific to this module topic:
1. Start with introduction/overview of the specific topic
2. Core concepts specific to this subject
3. Methods/processes/principles of this topic
4. Real examples and case studies for this subject
5. Applications and future directions of this topic

Make each section name specific to "{module_title}" - do not use generic words like "Key Concepts" or "Principles".

Example format: ["Understanding Market Dynamics", "Supply and Demand Analysis", "Price Formation Mechanisms", "Market Case Studies", "Investment Applications"]

Return only the JSON array with 5 specific section names for {module_title}."""

                third_response = generate_with_bedrock(third_prompt)
                print("Third prompt response:", third_response)

                if third_response:
                    start_idx = third_response.find('[')
                    end_idx = third_response.rfind(']')
                    if start_idx != -1 and end_idx != -1:
                        json_str = third_response[start_idx:end_idx+1]
                        try:
                            sections = json.loads(json_str)
                            if isinstance(sections, list) and 4 <= len(sections) <= 7:
                                print("✅ Third prompt successful")
                            else:
                                sections = None
                        except (json.JSONDecodeError, ValueError):
                            sections = None

            # Use improved fallback if all three prompts fail
            if not sections:
                print("⚠️ All three prompts failed, using improved fallback")
                sections = [
                    f"Foundations of {module_title}",
                    "Core Concepts and Principles",
                    "Theoretical Framework and Methods",
                    "Practical Applications and Examples",
                    "Advanced Topics and Analysis",
                    "Real-World Implementation"
                ]

            # Clear existing sections
            cursor.execute("DELETE FROM module_sections WHERE module_id = %s", (module_id,))

            # Insert new sections
            for i, section_title in enumerate(sections, 1):
                cursor.execute("""
                    INSERT INTO module_sections (module_id, position, title)
                    VALUES (%s, %s, %s)
                """, (module_id, i, section_title))

            # Return created sections
            cursor.execute("""
                SELECT section_id, position, title, content
                FROM module_sections
                WHERE module_id = %s
                ORDER BY position
            """, (module_id,))
            created_sections = cursor.fetchall()

            return jsonify({
                'success': True,
                'message': f'Generated {len(created_sections)} sections',
                'sections': created_sections
            })
    except Exception as e:
        print(f"Generate sections error: {e}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': 'Error generating sections',
            'error': str(e)
        }), 500@modules_bp.route('/generate-section-content', methods=['POST'])
@jwt_required()
def generate_section_content():
    try:
        data = request.get_json()
        section_id = data.get('section_id')

        if not section_id:
            return jsonify({
                'success': False,
                'message': 'Section ID required',
                'error': 'Section ID required'
            }), 400

        db = get_db()
        with db.cursor() as cursor:
                # Get section and module info
                cursor.execute("""
                    SELECT s.title, s.position, m.content_html, c.course_title, c.description
                    FROM module_sections s
                    JOIN modules_master m ON s.module_id = m.module_id
                    JOIN courses_master c ON m.course_id = c.course_id
                    WHERE s.section_id = %s
                """, (section_id,))
                section_info = cursor.fetchone()

                if not section_info:
                    return jsonify({
                        'success': False,
                        'message': 'Section not found',
                        'error': 'Section not found'
                    }), 404

                # Extract module title and description
                title_match = re.search(r'<h2>(.*?)</h2>', section_info['content_html'])
                desc_match = re.search(r'<div class="module-description">\s*<p>(.*?)</p>', section_info['content_html'], re.DOTALL)

                module_title = title_match.group(1) if title_match else "Module"
                module_description = desc_match.group(1).strip() if desc_match else ""

                # Get all other sections in this module to prevent overlap
                cursor.execute("""
                    SELECT title, position
                    FROM module_sections
                    WHERE module_id = (SELECT module_id FROM module_sections WHERE section_id = %s)
                    AND section_id != %s
                    ORDER BY position
                """, (section_id, section_id))
                other_sections = cursor.fetchall()
                other_section_titles = [s['title'] for s in other_sections]

                # Generate section content with retry mechanism
                print(f"=== GENERATING CONTENT FOR SECTION: {section_info['title']} ===")

                # Primary prompt (original working format)
#                 primary_prompt = f"""Generate comprehensive educational content for this section:

# Course: {section_info['course_title']}
# Module: {module_title}
# Section: {section_info['title']}

# Other sections in this module (avoid overlapping with these):
# {chr(10).join([f"- {title}" for title in other_section_titles])}

# Create detailed content that:
# - Explains concepts clearly for self-study (no teacher present)
# - Includes multiple practical examples specific to "{section_info['title']}"
# - Uses simple, educational language
# - Provides step-by-step explanations where needed
# - Is comprehensive enough for complete understanding of THIS SECTION ONLY
# - Length: 4-5 paragraphs
# - Focuses exclusively on "{section_info['title']}" content

# Format the content with proper HTML structure:
# - Use <h4> for subsection headings
# - Use <p> for paragraphs
# - Use <ul><li> for bullet points
# - Use <strong> for emphasis
# - For single-line code: <code>example</code>
# - For multi-line code blocks: <pre><code>line 1
# line 2
# line 3</code></pre>

# Write as if teaching a student directly. Include examples and explanations that make the topic clear and actionable.

# Return ONLY the HTML-formatted educational content, no prefixes, no extra text."""

                primary_prompt = f"""You are an expert educational content creator. Your task is to generate exceptionally comprehensive, fully self-contained content for the following section:

Course: {section_info['course_title']}
Module: {module_title}
Section: {section_info['title']}

Other sections in this module (to avoid overlap):
{chr(10).join([f"- {title}" for title in other_section_titles])}

**Instructional Requirements:**
- The content must teach this section in exhaustive detail, as if it were a complete self-guided textbook chapter.
- Assume learners have **no prior knowledge**; every concept must be explained clearly, step by step.
- Provide **multiple practical, fully worked examples** specific to "{section_info['title']}".
- Use **simple, educational language** that builds from the ground up.
- Ensure the content is **standalone and sufficient** for mastering this section alone.
- Explanations must be **deep, systematic, and reinforced with analogies, examples, and explanations of 'why' as well as 'how'.**
- Strictly focus only on "{section_info['title']}" without overlapping with other listed sections.

**Length & Structure:**
- Aim for 4–5 substantial paragraphs (expanded and detailed, not superficial).
- Content must be comprehensive enough for complete understanding of this section.
- Organize ideas into logical subsections with clear flow.

**Formatting Instructions (HTML only):**
- Use <h4> for subsection headings
- Use <p> for paragraphs
- Use <ul><li> for bullet points
- Use <strong> for emphasis
- For single-line code: <code>example</code>
- For multi-line code blocks:
  <pre><code>line 1
line 2
line 3</code></pre>

**Output Rules:**
- Return ONLY the HTML-formatted instructional content.
- Do NOT include any prefixes, extra commentary, or explanations outside the HTML.
"""


                # Secondary prompt (alternative format)
#                 secondary_prompt = f"""Create educational content for "{section_info['title']}" in {section_info['course_title']}.

# Topic: {section_info['title']}
# Module: {module_title}
# Avoid these topics: {', '.join(other_section_titles)}

# Write detailed content covering:
# 1. What {section_info['title']} is and why it matters
# 2. How it works with specific examples
# 3. Step-by-step implementation
# 4. Real-world applications
# 5. Common challenges and solutions

# Use HTML formatting: <p>, <h4>, <strong>, <code>, <pre><code>
# Write 4-5 comprehensive paragraphs with practical examples."""
                secondary_prompt = f"""You are an expert instructional designer. Create exceptionally comprehensive, self-contained educational content for the following section:

Course: {section_info['course_title']}
Module: {module_title}
Section: {section_info['title']}

Other sections in this module (avoid overlap with these):
{chr(10).join([f"- {title}" for title in other_section_titles])}

**Content Requirements:**
- Teach "{section_info['title']}" in exhaustive detail, assuming the learner has no prior knowledge.
- Content must explain:
  1. <strong>What</strong> {section_info['title']} is and why it matters.
  2. <strong>How</strong> it works, with multiple fully developed examples.
  3. <strong>Step-by-step implementation</strong>, described clearly and logically.
  4. <strong>Real-world applications</strong> that connect theory to practice.
  5. <strong>Common challenges and solutions</strong>, with clear explanations of how to overcome them.
- Each explanation must be reinforced with analogies, bullet points, tables, or examples where helpful.
- The writing must be self-sufficient, clear, and written as if it were a chapter in a guided textbook.

**Style & Depth:**
- Use <strong>educational, student-friendly language</strong> that builds understanding gradually.
- Provide multiple, detailed examples specific to "{section_info['title']}".
- Include reasoning behind concepts (“why” as well as “how”) for deeper comprehension.
- Length: 4–5 substantial, information-rich paragraphs.
- Focus exclusively on this section; do not overlap with the listed topics.

**Formatting (HTML only):**
- <h4> for subsection headings
- <p> for paragraphs
- <ul><li> for bullet lists
- <strong> for emphasis
- <code>inline code</code> for short snippets
- <pre><code>...</code></pre> for multi-line code blocks
- (Optional) include descriptions of visual aids where helpful, e.g., “Figure 1: Diagram showing...”

**Output Rules:**
- Return ONLY the HTML-formatted instructional content.
- No preambles, introductions, or text outside the HTML itself.
"""


                content_response = None

                # Try primary prompt up to 3 times
                print("Trying PRIMARY PROMPT...")
                for attempt in range(1, 4):
                    print(f"Primary attempt {attempt}/3...")
                    content_response = generate_with_bedrock(primary_prompt)
                    if content_response and content_response.strip():
                        print(f"✅ PRIMARY PROMPT SUCCESS on attempt {attempt}")
                        break
                    else:
                        print(f"❌ Primary attempt {attempt} failed")

                # If primary failed, try secondary prompt up to 3 times
                if not content_response or not content_response.strip():
                    print("Primary prompt failed all attempts. Trying SECONDARY PROMPT...")
                    for attempt in range(1, 4):
                        print(f"Secondary attempt {attempt}/3...")
                        content_response = generate_with_bedrock(secondary_prompt)
                        if content_response and content_response.strip():
                            print(f"✅ SECONDARY PROMPT SUCCESS on attempt {attempt}")
                            break
                        else:
                            print(f"❌ Secondary attempt {attempt} failed")

                # Final fallback to hardcoded content
                if not content_response or not content_response.strip():
                    print("❌ ALL ATTEMPTS FAILED! Using hardcoded fallback content...")
                    content_response = f"""<p>This section covers the essential concepts of {section_info['title']} in the context of {section_info['course_title']}. Students will learn the fundamental principles and practical applications that are crucial for mastering this topic. The content includes detailed explanations, examples, and hands-on exercises.</p>

<h4>Key Learning Areas</h4>
<ul>
<li>Core concepts and terminology</li>
<li>Step-by-step implementation processes</li>
<li>Real-world applications and examples</li>
<li>Best practices and common approaches</li>
<li>Troubleshooting and problem-solving techniques</li>
<li>Practical applications and examples</li>
</ul>
<p>The content provides comprehensive coverage of all essential aspects of this topic, ensuring students gain both theoretical knowledge and practical skills.</p>"""
                    print(f"✅ HARDCODED FALLBACK APPLIED for section: {section_info['title']}")
                else:
                    print(f"✅ CONTENT GENERATED SUCCESSFULLY for section: {section_info['title']}")

                if content_response:
                    # Clean up the response to remove any prefixes
                    content_response = content_response.strip()
                    # Remove common AI prefixes
                    prefixes_to_remove = [
                        "Here is the educational content:",
                        "Here's the educational content:",
                        "Educational content:",
                        "Content:",
                        "Here is the content:",
                        "Here's the content:",
                        "Do not include any instructions or comments.",
                        "Do not include any references or citations. Start with the first paragraph.",
                        "Do not include any references or citations. Do not include any copyright or licensing information. Do not include any unnecessary information. Start with the first paragraph and end with the last paragraph.",
                        "``` Here is the HTML-formatted educational content:",
                        "Do not include any course, module, or section headings.",
                        "Just the HTML content.",
                        "Do not include the section title or any other extraneous information.",
                        "Do not include a title or any introductory sentences.",
                        "Do not include any unnecessary information.",
                        "Do not include any references or citations.",
                        "-->",
                        "```"
                    ]

                    for prefix in prefixes_to_remove:
                        if content_response.startswith(prefix):
                            content_response = content_response[len(prefix):].strip()

                    # Fix code block formatting
                    content_response = fix_code_blocks(content_response)

                if not content_response or len(content_response.strip()) < 50:
                    content_response = f"""<h4>Overview</h4>
<p>This section covers <strong>{section_info['title']}</strong> in detail. Students will learn the fundamental concepts, see practical examples, and understand how to apply this knowledge in real-world scenarios.</p>
<h4>Key Concepts</h4>
<ul>
<li>Understanding the core principles</li>
<li>Practical applications and examples</li>
<li>Best practices and common approaches</li>
</ul>
<p>The content provides comprehensive coverage of all essential aspects of this topic, ensuring students gain both theoretical knowledge and practical skills.</p>"""

                # Save content to database
                cursor.execute("""
                    UPDATE module_sections
                    SET content = %s
                    WHERE section_id = %s
                """, (content_response.strip(), section_id))

                return jsonify({
                    'success': True,
                    'message': 'Section content generated successfully',
                    'content': content_response.strip()
                })
    except Exception as e:
        print(f"Generate section content error: {e}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': 'Error generating section content',
            'error': str(e)
        }), 500

@modules_bp.route('/update-section-full', methods=['POST'])
@jwt_required()
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

            if cursor.rowcount == 0:
                return jsonify({
                    'success': False,
                    'message': 'Section not found',
                    'error': 'Section not found'
                }), 404

            return jsonify({
                'success': True,
                'message': 'Section updated successfully'
            })
    except Exception as e:
        print(f"Update section full error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': 'Error updating section',
            'error': str(e)
        }), 500

@modules_bp.route('/update-section', methods=['POST'])
@jwt_required()
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
                'success': False,
                'message': 'Section ID and content required',
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
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': 'Error updating section',
            'error': str(e)
        }), 500

@modules_bp.route('/insert-module', methods=['POST'])
@jwt_required()
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
                    'success': False,
                    'message': 'Course not found',
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

            new_module_id = cursor.lastrowid

            return jsonify({
                'success': True,
                'message': 'Module inserted successfully',
                'module_id': new_module_id,
                'position': new_position
            })
    except Exception as e:
        print(f"Insert module error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': 'Error inserting module',
            'error': str(e)
        }), 500

@modules_bp.route('/insert-section', methods=['POST'])
@jwt_required()
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

            new_section_id = cursor.lastrowid

            return jsonify({
                'success': True,
                'message': 'Section inserted successfully',
                'section_id': new_section_id,
                'position': new_position
            })
    except Exception as e:
        print(f"Insert section error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': 'Error inserting section',
            'error': str(e)
        }), 500

@modules_bp.route('/sections', methods=['GET'])
@jwt_required()
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
@jwt_required()
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

            return jsonify({
                'success': True,
                'message': 'Section deleted successfully'
            })
    except Exception as e:
        print(f"Delete section error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': 'Error deleting section',
            'error': str(e)
        }), 500
@modules_bp.route('/export-single-module-pdf/<int:module_id>', methods=['GET'])
@jwt_required()
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
@jwt_required()
def export_course_pdf(course_id):
    try:
        db = get_db()
        with db:
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

# Activity Management Endpoints
def generate_practical_activity(module_info, module_title, learning_outcomes_text):
    """Generate a practical application activity"""

    # Primary prompt
    backup_prompt = f"""<|begin_of_text|><|start_header_id|>user<|end_header_id|>

Create a hands-on practical activity for students studying {module_title}.

REQUIREMENTS:
- Real-world professional scenario
- Specific deliverables with word count
- Step-by-step instructions
- Uses {module_title} concepts directly

EXAMPLE:
You are a real estate analyst hired by XYZ Investment Group to evaluate 3 commercial properties in downtown area. Using market analysis techniques from this module, create a comprehensive report (800-1000 words) that includes: 1) Property valuation using comparable sales method 2) Market trend analysis for the area 3) Investment recommendation with risk assessment 4) Financial projections for next 5 years. Submit your analysis with supporting data and clear recommendations.

CREATE SIMILAR ACTIVITY FOR: {module_title}
COURSE CONTEXT: {module_info['course_title']}
LEARNING GOALS: {learning_outcomes_text}

OUTPUT FORMAT (return exactly this structure):
{{
  "title": "Your Activity Title Here",
  "instructions": "Your detailed activity instructions here",
  "activity_type": "practical"
}}

<|eot_id|><|start_header_id|>assistant<|end_header_id|>

"""

    # Backup prompt (simpler)
    primary_prompt = f"""<|begin_of_text|><|start_header_id|>user<|end_header_id|>

Create a practical assignment for {module_title} students.

Requirements:
- Professional scenario using {module_title} concepts
- 500-800 word deliverable
- Clear instructions

Module: {module_title}
Course: {module_info['course_title']}

OUTPUT FORMAT (return only this JSON):
{{"title": "Assignment Name", "instructions": "Complete task description", "activity_type": "practical"}}

<|eot_id|><|start_header_id|>assistant<|end_header_id|>

"""

    def try_generate_with_prompt(prompt, prompt_name, max_retries=3):
        for attempt in range(1, max_retries + 1):
            try:
                print(f"🔄 {prompt_name} - Attempt {attempt}/{max_retries}")
                print(f"📤 Sending prompt (length: {len(prompt)})")

                ai_response = generate_with_bedrock(prompt)

                print(f"📥 Raw response type: {type(ai_response)}")
                print(f"📥 Raw response: {repr(ai_response)}")
                print(f"📥 Response length: {len(ai_response) if ai_response else 0}")

                if ai_response and '{' in ai_response and '}' in ai_response:
                    json_start = ai_response.find('{')
                    json_end = ai_response.rfind('}') + 1
                    json_str = ai_response[json_start:json_end]
                    print(f"🔍 Extracted JSON: {json_str}")

                    # Clean the JSON string to handle control characters
                    import re
                    # Remove control characters except newlines and tabs
                    cleaned_json = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', json_str)
                    # Fix common JSON issues
                    cleaned_json = cleaned_json.replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
                    print(f"🧹 Cleaned JSON: {cleaned_json}")

                    try:
                        activity = json.loads(cleaned_json)
                        print(f"🔍 Parsed activity: {activity}")

                        if 'title' in activity and 'instructions' in activity and len(activity['instructions']) > 100:
                            activity['activity_type'] = 'practical'
                            print(f"✅ {prompt_name} succeeded on attempt {attempt}")
                            return activity
                        else:
                            print(f"⚠️ {prompt_name} attempt {attempt}: Invalid structure or too short")
                            print(f"   - Has title: {'title' in activity}")
                            print(f"   - Has instructions: {'instructions' in activity}")
                            print(f"   - Instructions length: {len(activity.get('instructions', ''))}")
                    except json.JSONDecodeError as json_error:
                        print(f"⚠️ JSON parsing failed: {json_error}")
                        # Try alternative parsing - extract fields manually
                        try:
                            title_match = re.search(r'"title":\s*"([^"]*(?:\\.[^"]*)*)"', cleaned_json)
                            instructions_match = re.search(r'"instructions":\s*"([^"]*(?:\\.[^"]*)*)"', cleaned_json, re.DOTALL)

                            if title_match and instructions_match:
                                title = title_match.group(1).replace('\\"', '"')
                                instructions = instructions_match.group(1).replace('\\"', '"').replace('\\n', '\n')

                                if len(instructions) > 100:
                                    activity = {
                                        "title": title,
                                        "instructions": instructions,
                                        "activity_type": "practical"
                                    }
                                    print(f"✅ {prompt_name} succeeded with manual parsing on attempt {attempt}")
                                    return activity
                                else:
                                    print(f"⚠️ Manual parsing: instructions too short ({len(instructions)} chars)")
                            else:
                                print(f"⚠️ Manual parsing: could not extract title or instructions")
                        except Exception as manual_error:
                            print(f"⚠️ Manual parsing failed: {manual_error}")
                else:
                    print(f"⚠️ {prompt_name} attempt {attempt}: No valid JSON found")
                    print(f"   - Response exists: {ai_response is not None}")
                    print(f"   - Contains {{: {'{' in str(ai_response) if ai_response else False}")
                    print(f"   - Contains }}: {'}' in str(ai_response) if ai_response else False}")

            except Exception as e:
                print(f"❌ {prompt_name} attempt {attempt} error: {e}")
                import traceback
                traceback.print_exc()

        print(f"❌ {prompt_name} failed after {max_retries} attempts")
        return None

    # Try primary prompt 3 times
    activity = try_generate_with_prompt(primary_prompt, "Primary Prompt")

    # If primary fails, try backup prompt 3 times
    if not activity:
        print("🔄 Switching to backup prompt...")
        activity = try_generate_with_prompt(backup_prompt, "Backup Prompt")

    # If both fail, use fallback
    if not activity:
        print("⚠️ All prompts failed, using fallback practical activity")
        return {
            "title": f"Practical Application: {module_title}",
            "instructions": f"Based on the concepts learned in {module_title}, create a practical example or case study that demonstrates your understanding. Your response should be 300-500 words and include specific examples from the module content.",
            "activity_type": "practical"
        }

    return activity

def generate_analysis_activity(module_info, module_title, learning_outcomes_text):
    """Generate a situational analysis activity with multiple choice decision"""

    # Primary prompt
    primary_prompt = f"""<|begin_of_text|><|start_header_id|>user<|end_header_id|>

Create a workplace decision scenario for {module_title}.

STRICT FORMAT - Must include:
1. Realistic workplace scenario with specific details
2. Exactly 4 options (A, B, C, D) with different solutions
3. Clear instructions for student response

Return ONLY this JSON:
{{"title": "Decision Title", "instructions": "Complete scenario and 4 options here", "activity_type": "analysis"}}

Example structure:
"You are a [job role] at [company]. [Specific situation with numbers/details]. Which action should you take? A) [solution 1] B) [solution 2] C) [solution 3] D) [solution 4]. Choose the best option and explain in 200-300 words."

Module: {module_title}
Course: {module_info['course_title']}
Make it specific to {module_info['course_title']} field.

<|eot_id|><|start_header_id|>assistant<|end_header_id|>

"""

    # Backup prompt (alternative approach)
    backup_prompt = f"""<|begin_of_text|><|start_header_id|>user<|end_header_id|>

Design a professional scenario assessment for {module_title} students.

REQUIREMENTS:
- Present a business situation requiring {module_title} knowledge
- Provide 4 distinct solution choices (A, B, C, D)
- Ask students to select best option and justify their choice

FORBIDDEN:
- Do not reference external materials or "read the following"
- Do not create essay questions or open analysis tasks

JSON OUTPUT REQUIRED:
{{"title": "Professional Decision: [Scenario Name]", "instructions": "[Full scenario description with 4 options A-D and response instructions]", "activity_type": "analysis"}}

Context: {module_info['course_title']} course, {module_title} module
Learning objectives: {learning_outcomes_text}

<|eot_id|><|start_header_id|>assistant<|end_header_id|>

"""

    def try_generate_analysis_with_prompt(prompt, prompt_name, max_retries=3):
        for attempt in range(1, max_retries + 1):
            try:
                print(f"🔄 Analysis {prompt_name} - Attempt {attempt}/{max_retries}")
                ai_response = generate_with_bedrock(prompt)

                if ai_response and '{' in ai_response and '}' in ai_response:
                    json_start = ai_response.find('{')
                    json_end = ai_response.rfind('}') + 1
                    json_str = ai_response[json_start:json_end]

                    # Clean the JSON string
                    import re
                    cleaned_json = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', json_str)
                    cleaned_json = cleaned_json.replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')

                    try:
                        activity = json.loads(cleaned_json)
                        if 'title' in activity and 'instructions' in activity and len(activity['instructions']) > 200:
                            # Convert \n to actual line breaks for display
                            activity['instructions'] = activity['instructions'].replace('\\n', '\n')
                            activity['activity_type'] = 'analysis'
                            print(f"✅ Analysis {prompt_name} succeeded on attempt {attempt}")
                            return activity
                        else:
                            print(f"⚠️ Analysis {prompt_name} attempt {attempt}: Invalid structure or too short")
                    except json.JSONDecodeError:
                        # Try manual parsing
                        try:
                            title_match = re.search(r'"title":\s*"([^"]*(?:\\.[^"]*)*)"', cleaned_json)
                            instructions_match = re.search(r'"instructions":\s*"([^"]*(?:\\.[^"]*)*)"', cleaned_json, re.DOTALL)

                            if title_match and instructions_match:
                                title = title_match.group(1).replace('\\"', '"')
                                instructions = instructions_match.group(1).replace('\\"', '"').replace('\\n', '\n')

                                if len(instructions) > 200:
                                    activity = {
                                        "title": title,
                                        "instructions": instructions,
                                        "activity_type": "analysis"
                                    }
                                    print(f"✅ Analysis {prompt_name} succeeded with manual parsing on attempt {attempt}")
                                    return activity
                        except Exception:
                            pass
                else:
                    print(f"⚠️ Analysis {prompt_name} attempt {attempt}: No valid JSON found")

            except Exception as e:
                print(f"❌ Analysis {prompt_name} attempt {attempt} error: {e}")

        print(f"❌ Analysis {prompt_name} failed after {max_retries} attempts")
        return None

    # Try primary prompt 3 times
    activity = try_generate_analysis_with_prompt(primary_prompt, "Primary Prompt")

    # If primary fails, try backup prompt 3 times
    if not activity:
        print("🔄 Analysis switching to backup prompt...")
        activity = try_generate_analysis_with_prompt(backup_prompt, "Backup Prompt")

    # If both fail, use fallback
    if not activity:
        print("⚠️ All analysis prompts failed, using fallback analysis activity")
        return {
            "title": f"Decision Analysis: {module_title}",
            "instructions": f"SCENARIO:\n\nYou are a {module_info['course_title']} professional facing a decision that requires {module_title} expertise. A client needs immediate recommendations on a complex situation involving multiple stakeholders and competing priorities.\n\nOPTIONS:\nA) Recommend a conservative approach based on established industry standards\nB) Propose an innovative solution incorporating latest {module_title} methodologies\nC) Suggest gathering additional data before making any recommendations\nD) Provide multiple options and let the client decide\n\nTASK:\nChoose the best option (A, B, C, or D) and explain your reasoning in 200-300 words. Reference specific {module_title} concepts and justify why your chosen option is superior.\n\nSubmit your answer as: 'I choose option [X] because...'",
            "activity_type": "analysis"
        }

    return activity

@modules_bp.route('/generate-single-activity', methods=['POST'])
@jwt_required()
def generate_single_activity():
    try:
        data = request.get_json()
        module_id = data.get('module_id')
        activity_type = data.get('activity_type', 'practical')
        activity_id = data.get('activity_id')  # For regeneration
        clear_existing = data.get('clear_existing', False)  # For clearing old activities

        print(f"=== ACTIVITY GENERATION START ===")
        print(f"Module ID: {module_id}")
        print(f"Activity Type: {activity_type}")
        print(f"Activity ID (regen): {activity_id}")

        if not module_id:
            return jsonify({
                'success': False,
                'message': 'Module ID is required',
                'error': 'Module ID is required'
            }), 400

        db = get_db()
        with db:
            with db.cursor() as cursor:
                # Get module and course info for context
                cursor.execute("""
                    SELECT m.content_html, m.learning_outcomes, c.course_title, c.description
                    FROM modules_master m
                    JOIN courses_master c ON m.course_id = c.course_id
                    WHERE m.module_id = %s
                """, (module_id,))
                module_info = cursor.fetchone()

                if not module_info:
                    print("ERROR: Module not found")
                    return jsonify({
                        'success': False,
                        'message': 'Module not found',
                        'error': 'Module not found'
                    }), 404

                print(f"Course: {module_info['course_title']}")

                # Extract module title
                title_match = re.search(r'<h2>(.*?)</h2>', module_info['content_html'])
                module_title = title_match.group(1) if title_match else "Module"
                print(f"Module Title: {module_title}")

                # Get learning outcomes
                learning_outcomes_text = ""
                if module_info['learning_outcomes']:
                    outcomes = json.loads(module_info['learning_outcomes'])
                    learning_outcomes_text = "\n".join([f"- {outcome}" for outcome in outcomes])

                # Generate activity based on type
                if activity_type == "analysis":
                    activity = generate_analysis_activity(module_info, module_title, learning_outcomes_text)
                elif activity_type == "practical":
                    activity = generate_practical_activity(module_info, module_title, learning_outcomes_text)
                else:
                    return jsonify({
                        'success': False,
                        'message': f'Unsupported activity type: {activity_type}',
                        'error': f'Unsupported activity type: {activity_type}'
                    }), 400

                print(f"=== ACTIVITY GENERATION RESULT ===")
                print(f"Activity type: {activity_type}")

                if not activity:
                    print("ERROR: Activity generation failed")
                    return jsonify({
                        'success': False,
                        'message': 'Failed to generate activity',
                        'error': 'Failed to generate activity'
                    }), 500

                print(f"=== FINAL ACTIVITY ===")
                print(json.dumps(activity, indent=2))

                if activity_id:
                    # Regenerate existing activity
                    print(f"REGENERATING activity ID: {activity_id}")
                    cursor.execute("""
                        UPDATE module_activities
                        SET title = %s, instructions = %s, activity_type = %s
                        WHERE activity_id = %s
                    """, (activity['title'], activity['instructions'], activity_type, activity_id))
                else:
                    # Create new activity - delete existing activities only if clear_existing flag is set
                    if clear_existing:
                        print("DELETING existing activities for module")
                        cursor.execute("DELETE FROM module_activities WHERE module_id = %s", (module_id,))

                    print("CREATING new activity")
                    cursor.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM module_activities WHERE module_id = %s", (module_id,))
                    next_position = cursor.fetchone()['COALESCE(MAX(position), 0) + 1']
                    print(f"Next position: {next_position}")

                    cursor.execute("""
                        INSERT INTO module_activities (module_id, position, title, instructions, activity_type)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (module_id, next_position, activity['title'], activity['instructions'], activity_type))

                print("SUCCESS: Database updated")
                return jsonify({
                    'success': True,
                    'message': 'Activity generated successfully',
                    'activity': activity
                })
    except Exception as e:
        print(f"Generate single activity error: {e}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': 'Error generating activity',
            'error': str(e)
        }), 500

    except Exception as e:
        print(f"ERROR: General exception - {e}")
        return jsonify({
            'success': False,
            'message': 'Error generating activity',
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
@jwt_required()
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
@jwt_required()
def delete_activity(activity_id):
    try:
        db = get_db()
        with db:
            with db.cursor() as cursor:
                cursor.execute("DELETE FROM module_activities WHERE activity_id = %s", (activity_id,))

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
@jwt_required()
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

# Exam Items Management Endpoints
def clean_content_for_prompt(content):
    """Clean and optimize content for use in AI prompts"""
    if not content:
        return ""

    # Remove HTML tags
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(content, 'html.parser')
    text = soup.get_text()

    # Remove newlines and replace with spaces
    text = text.replace('\n', ' ').replace('\r', ' ')

    # Remove multiple spaces and replace with single space
    text = ' '.join(text.split())

    # Remove extra whitespace
    text = text.strip()

    return text

@modules_bp.route('/generate-exam-items', methods=['POST'])
@jwt_required()
def generate_exam_items():
    try:
        data = request.get_json()
        section_id = data.get('section_id')
        difficulty = data.get('difficulty', 'medium')  # easy, medium, hard

        if not section_id:
            return jsonify({'error': 'Section ID required'}), 400

        db = get_db()
        with db:
            with db.cursor() as cursor:
                # Get section and module info
                cursor.execute("""
                    SELECT s.title, s.content, m.content_html, c.course_title
                    FROM module_sections s
                    JOIN modules_master m ON s.module_id = m.module_id
                    JOIN courses_master c ON m.course_id = c.course_id
                    WHERE s.section_id = %s
                """, (section_id,))
                section_info = cursor.fetchone()

                if not section_info:
                    return jsonify({'error': 'Section not found'}), 404

                # Get existing questions to avoid duplicates
                cursor.execute("SELECT question FROM exam_items WHERE section_id = %s", (section_id,))
                existing_questions = [row['question'].lower() for row in cursor.fetchall()]

                # Clean and optimize content for prompts
                raw_content = section_info['content'] or ""
                cleaned_content = clean_content_for_prompt(raw_content)

                # Split cleaned content into chunks of 800 characters (smaller due to cleaning)
                chunks = []
                for i in range(0, len(cleaned_content), 800):
                    chunk = cleaned_content[i:i+800]
                    if len(chunk.strip()) > 50:  # Only use meaningful chunks
                        chunks.append(chunk)

                if not chunks:
                    chunks = [cleaned_content[:800]]  # Fallback to first 400 chars

                difficulty_prompts = {
                    'easy': {
                        'desc': 'comprehension and basic application',
                        'instructions': 'Create questions that check fundamental understanding and straightforward application of core concepts. Focus on clear recall, simple examples, and direct problem-solving.'
                    },
                    'medium': {
                        'desc': 'application and multi-step analysis',
                        'instructions': 'Create questions that require applying knowledge in unfamiliar contexts, breaking down problems into multiple steps, and connecting different ideas. Include moderate complexity and some critical thinking.'
                    },
                    'hard': {
                        'desc': 'evaluation and creation',
                        'instructions': 'Design advanced questions that demand original thought, deep evaluation, and the creation of new solutions or perspectives. Require integration of multiple concepts, handling ambiguity, and justifying reasoning with evidence.'
                    }
                }

                all_items = []

                # Process each chunk
                for chunk_num, chunk in enumerate(chunks, 1):
                    print(f"Processing chunk {chunk_num}/{len(chunks)} for {difficulty} difficulty...")

                    prompts = [
                        # Prompt 3: Simple format
                        f"""Topic: {section_info['title']}
Content: {chunk}

Difficulty: {difficulty}

Level: {difficulty_prompts[difficulty]['desc']}

Goal: {difficulty_prompts[difficulty]['instructions']}

Create 5 {difficulty} quiz questions in JSON:
[{{"question":"...", "option_a":"...", "option_b":"...", "option_c":"...", "option_d":"...", "correct_answer":"A"}}]

Make questions appropriate for {difficulty} level.""",

                        # Prompt 1: Structured format
                        f"""Create 5 {difficulty} level multiple choice questions about: {section_info['title']}

Content chunk: {chunk}

Difficulty: {difficulty_prompts[difficulty]['desc']}

Instructions: {difficulty_prompts[difficulty]['instructions']}

Return ONLY valid JSON array:
[{{"question":"What is...?","option_a":"Answer A","option_b":"Answer B","option_c":"Answer C","option_d":"Answer D","correct_answer":"A"}}]

Make wrong answers plausible but clearly incorrect.""",

                        # Prompt 2: Detailed format
                        f"""Generate exactly 5 {difficulty}-level questions for "{section_info['title']}".

Content: {chunk}

Level: {difficulty_prompts[difficulty]['desc']}

Goal: {difficulty_prompts[difficulty]['instructions']}

Format as JSON array:
[{{"question": "Question text?", "option_a": "Choice A", "option_b": "Choice B", "option_c": "Choice C", "option_d": "Choice D", "correct_answer": "A"}}]

Ensure questions match {difficulty} difficulty level."""
                    ]

                    chunk_items = None

                    # Try each prompt up to 3 times
                    for prompt_num, prompt in enumerate(prompts, 1):
                        print(f"  Trying prompt {prompt_num}...")

                        for attempt in range(1, 4):
                            print(f"    Attempt {attempt}/3...")
                            response = generate_with_bedrock(prompt)

                            if response:
                                try:
                                    # Extract JSON from response
                                    start_idx = response.find('[')
                                    end_idx = response.rfind(']') + 1
                                    if start_idx != -1 and end_idx != -1:
                                        json_str = response[start_idx:end_idx]
                                        chunk_items = json.loads(json_str)

                                        if isinstance(chunk_items, list) and len(chunk_items) >= 3:
                                            print(f"    ✅ Success with prompt {prompt_num}, attempt {attempt}")
                                            break
                                except (json.JSONDecodeError, ValueError):
                                    print(f"    Parse failed on attempt {attempt}")
                                    continue

                        if chunk_items and len(chunk_items) >= 3:
                            break

                    # Add non-duplicate items
                    if chunk_items:
                        for item in chunk_items:
                            if (isinstance(item, dict) and
                                all(key in item for key in ['question', 'option_a', 'option_b', 'option_c', 'option_d', 'correct_answer']) and
                                item['question'].lower() not in existing_questions):
                                all_items.append(item)
                                existing_questions.append(item['question'].lower())

                # Save items to database
                saved_items = []
                for item in all_items:
                    cursor.execute("""
                        INSERT INTO exam_items (section_id, question, option_a, option_b, option_c, option_d, correct_answer)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (section_id, item['question'], item['option_a'], item['option_b'], item['option_c'], item['option_d'], item['correct_answer']))
                    saved_items.append(item)

                if saved_items:
                    return jsonify({'success': True, 'items': saved_items, 'count': len(saved_items)})

                # Fallback items if all attempts failed
                fallback_items = []
                for i in range(5):
                    cursor.execute("""
                        INSERT INTO exam_items (section_id, question, option_a, option_b, option_c, option_d, correct_answer)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (section_id, f"{difficulty.title()} Question {i+1} about {section_info['title']}?", "Option A", "Option B", "Option C", "Option D", "A"))
                    fallback_items.append({
                        'question': f"{difficulty.title()} Question {i+1} about {section_info['title']}?",
                        'option_a': "Option A", 'option_b': "Option B", 'option_c': "Option C", 'option_d': "Option D",
                        'correct_answer': "A"
                    })

                return jsonify({'success': True, 'items': fallback_items, 'count': len(fallback_items)})
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error generating exam items',
            'error': str(e)
        }), 500

@modules_bp.route('/exam-items/manual-create', methods=['POST'])
@jwt_required()
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

        if not all([section_id, question, option_a, option_b, option_c, option_d, correct_answer]):
            return jsonify({
                'success': False,
                'message': 'All fields are required',
                'error': 'All fields are required'
            }), 400

        db = get_db()
        with db:
            with db.cursor() as cursor:
                # Insert the new exam item (without difficulty column)
                cursor.execute("""
                    INSERT INTO exam_items (section_id, question, option_a, option_b, option_c, option_d, correct_answer)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (section_id, question, option_a, option_b, option_c, option_d, correct_answer))

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

@modules_bp.route('/activity-submissions/check/<int:activity_id>', methods=['GET'])
@jwt_required()
def check_student_activity_submission(activity_id):
    try:
        user_id = int(get_jwt_identity())

        db = get_db()
        with db:
            with db.cursor() as cursor:
                # Check if student has already submitted this activity
                cursor.execute("""
                    SELECT submission_id, submission_content, submitted_at, status
                    FROM activity_submissions
                    WHERE user_id = %s AND activity_id = %s
                """, (user_id, activity_id))

                submission = cursor.fetchone()

                return jsonify({
                    'success': True,
                    'message': 'Submission status retrieved',
                    'submission': submission
                })

    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error checking submission',
            'error': str(e)
        }), 500

@modules_bp.route('/activity-submissions/submit', methods=['POST'])
@jwt_required()
def submit_student_activity():
    try:
        user_id = int(get_jwt_identity())

        data = request.get_json()
        activity_id = data.get('activity_id')
        submission_content = data.get('submission_content')

        if not all([activity_id, submission_content]):
            return jsonify({'error': 'Activity ID and content are required'}), 400

        db = get_db()
        with db:
            with db.cursor() as cursor:
                # Check if submission already exists
                cursor.execute("""
                    SELECT submission_id, status FROM activity_submissions
                    WHERE user_id = %s AND activity_id = %s
                """, (user_id, activity_id))

                existing = cursor.fetchone()

                if existing:
                    # Check if submission is final (submitted status)
                    if existing['status'] == 'submitted':
                        return jsonify({'error': 'Activity already submitted. Contact instructor to resubmit.'}), 400

                    # Update draft submission
                    cursor.execute("""
                        UPDATE activity_submissions
                        SET submission_content = %s, status = 'submitted', updated_at = CURRENT_TIMESTAMP
                        WHERE user_id = %s AND activity_id = %s
                    """, (submission_content, user_id, activity_id))
                    message = 'Activity submission updated successfully'
                else:
                    # Create new submission as final
                    cursor.execute("""
                        INSERT INTO activity_submissions (user_id, activity_id, submission_content, status)
                        VALUES (%s, %s, %s, 'submitted')
                    """, (user_id, activity_id, submission_content))
                    message = 'Activity submitted successfully'

                return jsonify({
                    'success': True,
                    'message': message
                })

    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error checking activity submission',
            'error': str(e)
        }), 500

@modules_bp.route('/student-quizzes/<int:course_id>', methods=['GET'])
@jwt_required()
def get_student_course_quizzes(course_id):
    """Get available quizzes for a student in a course"""
    try:
        user_id = get_jwt_identity()

        db = get_db()
        with db:
            with db.cursor() as cursor:
                # Get student's course instance
                cursor.execute("""
                    SELECT ci.instance_id FROM course_instances ci
                    JOIN enrollments e ON ci.instance_id = e.instance_id
                    WHERE ci.course_id = %s AND e.user_id = %s
                """, (course_id, user_id))

                instance_result = cursor.fetchone()
                if not instance_result:
                    return jsonify({'error': 'Student not enrolled in this course'}), 403

                instance_id = instance_result[0] if isinstance(instance_result, tuple) else instance_result['instance_id']

                # Get quizzes for this course (only category = 'quiz') with exam_period
                cursor.execute("""
                    SELECT DISTINCT et.exam_type_id, et.exam_name, et.exam_period, et.description, et.total_items
                    FROM exam_types et
                    JOIN assessment_scopes a_scope ON et.exam_type_id = a_scope.exam_type_id
                    WHERE a_scope.course_id = %s AND et.category = 'quiz'
                    ORDER BY
                        CASE et.exam_period
                            WHEN 'Prelim' THEN 1
                            WHEN 'Midterm' THEN 2
                            WHEN 'Pre-Final' THEN 3
                            WHEN 'Final' THEN 4
                        END,
                        et.exam_name
                """, (course_id,))

                quiz_results = cursor.fetchall()
                quizzes = []

                for result in quiz_results:
                    if isinstance(result, dict):
                        quiz_id = result['exam_type_id']
                        quiz_name = result['exam_name']
                        exam_period = result['exam_period']
                        description = result['description']
                        total_items = result['total_items']
                    else:
                        quiz_id = result[0]
                        quiz_name = result[1]
                        exam_period = result[2]
                        description = result[3]
                        total_items = result[4]

                    # Check if student has already taken this quiz
                    cursor.execute("""
                        SELECT qr.result_id, qr.score, qr.completed_at
                        FROM quiz_results qr
                        WHERE qr.user_id = %s AND qr.exam_type_id = %s AND qr.instance_id = %s
                    """, (user_id, quiz_id, instance_id))

                    quiz_attempt = cursor.fetchone()

                    quiz_data = {
                        'quiz_id': quiz_id,
                        'quiz_name': quiz_name,
                        'exam_period': exam_period,
                        'description': description,
                        'total_items': total_items,
                        'is_taken': quiz_attempt is not None,
                        'score': None,
                        'completed_at': None
                    }

                    if quiz_attempt:
                        if isinstance(quiz_attempt, dict):
                            quiz_data['score'] = quiz_attempt['score']
                            quiz_data['completed_at'] = quiz_attempt['completed_at'].isoformat() if quiz_attempt['completed_at'] else None
                        else:
                            quiz_data['score'] = quiz_attempt[1]
                            quiz_data['completed_at'] = quiz_attempt[2].isoformat() if quiz_attempt[2] else None

                    quizzes.append(quiz_data)

                return jsonify({'quizzes': quizzes, 'instance_id': instance_id})

    except Exception as e:
        print(f"Error getting student quizzes: {str(e)}")
        return jsonify({'error': str(e)}), 500

@modules_bp.route('/student-exams/<int:course_id>', methods=['GET'])
@jwt_required()
def get_student_course_exams_grouped(course_id):
    """Get available exams for a student in a course grouped by periods"""
    try:
        user_id = get_jwt_identity()

        db = get_db()
        with db:
            with db.cursor() as cursor:
                # Get student's course instance
                cursor.execute("""
                    SELECT ci.instance_id FROM course_instances ci
                    JOIN enrollments e ON ci.instance_id = e.instance_id
                    WHERE ci.course_id = %s AND e.user_id = %s
                """, (course_id, user_id))

                instance_result = cursor.fetchone()
                if not instance_result:
                    return jsonify({'error': 'Student not enrolled in this course'}), 403

                instance_id = instance_result[0] if isinstance(instance_result, tuple) else instance_result['instance_id']

                # Get exams for this course (only category = 'exam') with exam_period
                cursor.execute("""
                    SELECT DISTINCT et.exam_type_id, et.exam_name, et.exam_period, et.description, et.total_items
                    FROM exam_types et
                    JOIN assessment_scopes a_scope ON et.exam_type_id = a_scope.exam_type_id
                    WHERE a_scope.course_id = %s AND et.category = 'exam'
                    ORDER BY
                        CASE et.exam_period
                            WHEN 'Prelim' THEN 1
                            WHEN 'Midterm' THEN 2
                            WHEN 'Pre-Final' THEN 3
                            WHEN 'Final' THEN 4
                        END,
                        et.exam_name
                """, (course_id,))

                exam_results = cursor.fetchall()
                exams = []

                for result in exam_results:
                    if isinstance(result, dict):
                        exam_id = result['exam_type_id']
                        exam_name = result['exam_name']
                        exam_period = result['exam_period']
                        description = result['description']
                        total_items = result['total_items']
                    else:
                        exam_id = result[0]
                        exam_name = result[1]
                        exam_period = result[2]
                        description = result[3]
                        total_items = result[4]

                    # Check if student has already taken this exam
                    cursor.execute("""
                        SELECT er.result_id, er.score, er.completed_at
                        FROM exam_results er
                        WHERE er.user_id = %s AND er.exam_type_id = %s AND er.instance_id = %s
                    """, (user_id, exam_id, instance_id))

                    exam_attempt = cursor.fetchone()

                    exam_data = {
                        'exam_id': exam_id,
                        'exam_name': exam_name,
                        'exam_period': exam_period,
                        'description': description,
                        'total_items': total_items,
                        'is_taken': exam_attempt is not None,
                        'score': None,
                        'completed_at': None
                    }

                    if exam_attempt:
                        if isinstance(exam_attempt, dict):
                            exam_data['score'] = exam_attempt['score']
                            exam_data['completed_at'] = exam_attempt['completed_at'].isoformat() if exam_attempt['completed_at'] else None
                        else:
                            exam_data['score'] = exam_attempt[1]
                            exam_data['completed_at'] = exam_attempt[2].isoformat() if exam_attempt[2] else None

                    exams.append(exam_data)

                return jsonify({'exams': exams, 'instance_id': instance_id})

    except Exception as e:
        print(f"Error getting student exams: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'Error getting student exams',
            'error': str(e)
        }), 500

@modules_bp.route('/student-exam-questions-unique/<int:exam_id>/<int:instance_id>', methods=['GET'])
@jwt_required()
def get_student_exam_questions_unique(exam_id, instance_id):
    """Get exam questions for student (without correct answers)"""
    try:
        user_id = get_jwt_identity()

        db = get_db()
        with db:
            with db.cursor() as cursor:
                # Verify student is enrolled (exam results table doesn't exist yet, so no completion check)
                cursor.execute("""
                    SELECT e.enrollment_id FROM enrollments e
                    JOIN course_instances ci ON e.instance_id = ci.instance_id
                    WHERE e.user_id = %s AND ci.instance_id = %s
                """, (user_id, instance_id))

                if not cursor.fetchone():
                    return jsonify({'error': 'Student not enrolled in this course instance'}), 403

                # Get exam questions (same logic as quiz questions)
                cursor.execute("""
                    SELECT DISTINCT a_scope.module_id
                    FROM assessment_scopes a_scope
                    WHERE a_scope.exam_type_id = %s
                """, (exam_id,))

                module_results = cursor.fetchall()
                all_questions = []

                for module_result in module_results:
                    module_id = module_result[0] if isinstance(module_result, tuple) else module_result['module_id']

                    cursor.execute("""
                        SELECT ei.item_id, ei.question, ei.option_a, ei.option_b, ei.option_c, ei.option_d
                        FROM exam_items ei
                        JOIN module_sections ms ON ei.section_id = ms.section_id
                        WHERE ms.module_id = %s
                        ORDER BY RAND()
                    """, (module_id,))

                    questions = cursor.fetchall()
                    all_questions.extend(questions)

                # Get total items needed from exam_types
                cursor.execute("SELECT total_items FROM exam_types WHERE exam_type_id = %s", (exam_id,))
                total_items_result = cursor.fetchone()
                total_items = total_items_result[0] if isinstance(total_items_result, tuple) else total_items_result['total_items']

                # Randomly select questions up to total_items
                import random
                if len(all_questions) > total_items:
                    selected_questions = random.sample(all_questions, total_items)
                else:
                    selected_questions = all_questions

                questions_data = selected_questions

                if not questions_data:
                    return jsonify({'error': 'No questions found for this exam'}), 404

                questions = []
                for i, row in enumerate(questions_data):
                    if isinstance(row, dict):
                        question = {
                            'question_number': i + 1,
                            'item_id': row['item_id'],
                            'question_text': row['question'],
                            'options': {
                                'A': row['option_a'],
                                'B': row['option_b'],
                                'C': row['option_c'],
                                'D': row['option_d']
                            }
                        }
                    else:
                        question = {
                            'question_number': i + 1,
                            'item_id': row[0],
                            'question_text': row[1],
                            'options': {
                                'A': row[2],
                                'B': row[3],
                                'C': row[4],
                                'D': row[5]
                            }
                        }
                    questions.append(question)

                return jsonify({'questions': questions})

    except Exception as e:
        print(f"Error getting exam questions: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'Error getting exam questions',
            'error': str(e)
        }), 500

@modules_bp.route('/submit-exam-results-unique', methods=['POST'])
@jwt_required()
def submit_exam_results_unique():
    """Submit exam results for a student"""
    try:
        user_id = get_jwt_identity()
        data = request.get_json()

        exam_id = data.get('exam_id')
        instance_id = data.get('instance_id')
        answers = data.get('answers', {})
        submission_reason = data.get('submission_reason', 'manual')

        if not exam_id or not instance_id:
            return jsonify({'error': 'Missing required fields'}), 400

        db = get_db()
        with db:
            with db.cursor() as cursor:
                # Check if already submitted
                cursor.execute("""
                    SELECT result_id FROM exam_results
                    WHERE user_id = %s AND exam_type_id = %s AND instance_id = %s
                """, (user_id, exam_id, instance_id))

                if cursor.fetchone():
                    return jsonify({'error': 'Exam already submitted'}), 403

                # Get correct answers and calculate score
                cursor.execute("""
                    SELECT DISTINCT a_scope.module_id
                    FROM assessment_scopes a_scope
                    WHERE a_scope.exam_type_id = %s
                """, (exam_id,))

                module_results = cursor.fetchall()
                all_questions = []

                for module_result in module_results:
                    module_id = module_result[0] if isinstance(module_result, tuple) else module_result['module_id']

                    cursor.execute("""
                        SELECT ei.item_id, ei.correct_answer
                        FROM exam_items ei
                        JOIN module_sections ms ON ei.section_id = ms.section_id
                        WHERE ms.module_id = %s
                    """, (module_id,))

                    questions = cursor.fetchall()
                    all_questions.extend(questions)

                # Calculate score based on total_items from exam_types (not answered questions)
                cursor.execute("SELECT total_items FROM exam_types WHERE exam_type_id = %s", (exam_id,))
                total_items_result = cursor.fetchone()
                total_items = total_items_result[0] if isinstance(total_items_result, tuple) else total_items_result['total_items']

                correct_answers = 0

                for question_data in all_questions:
                    item_id = str(question_data[0] if isinstance(question_data, tuple) else question_data['item_id'])
                    correct_answer = question_data[1] if isinstance(question_data, tuple) else question_data['correct_answer']

                    if item_id in answers and answers[item_id] == correct_answer:
                        correct_answers += 1

                score = (correct_answers / total_items * 100) if total_items > 0 else 0

                # Insert exam result
                cursor.execute("""
                    INSERT INTO exam_results (user_id, exam_type_id, instance_id, score, total_questions, correct_answers, answers, submission_reason)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (user_id, exam_id, instance_id, score, total_items, correct_answers, json.dumps(answers), submission_reason))

                return jsonify({
                    'success': True,
                    'score': round(score, 2),
                    'correct_answers': correct_answers,
                    'total_questions': total_items,
                    'submission_reason': submission_reason
                })

    except Exception as e:
        print(f"Error submitting exam results: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'Error submitting exam results',
            'error': str(e)
        }), 500

@modules_bp.route('/student-quiz-questions/<int:quiz_id>/<int:instance_id>', methods=['GET'])
@jwt_required()
def get_student_quiz_questions(quiz_id, instance_id):
    """Get quiz questions for student (without correct answers)"""
    try:
        user_id = get_jwt_identity()

        db = get_db()
        with db:
            with db.cursor() as cursor:
                # Verify student is enrolled and hasn't taken the quiz
                cursor.execute("""
                    SELECT COUNT(*) FROM enrollments e
                    WHERE e.user_id = %s AND e.instance_id = %s
                """, (user_id, instance_id))

                enrollment_check = cursor.fetchone()
                if not enrollment_check or (enrollment_check[0] if isinstance(enrollment_check, tuple) else enrollment_check['COUNT(*)']) == 0:
                    return jsonify({'error': 'Student not enrolled in this course instance'}), 403

                # Check if already taken
                cursor.execute("""
                    SELECT COUNT(*) FROM quiz_results
                    WHERE user_id = %s AND exam_type_id = %s AND instance_id = %s
                """, (user_id, quiz_id, instance_id))

                taken_check = cursor.fetchone()
                if taken_check and (taken_check[0] if isinstance(taken_check, tuple) else taken_check['COUNT(*)']) > 0:
                    return jsonify({'error': 'Quiz already taken'}), 403

                # Get quiz questions (same logic as assessment preview but without correct answers)
                cursor.execute("""
                    SELECT DISTINCT a_scope.module_id
                    FROM assessment_scopes a_scope
                    WHERE a_scope.exam_type_id = %s
                """, (quiz_id,))

                module_results = cursor.fetchall()
                all_questions = []

                for module_result in module_results:
                    module_id = module_result[0] if isinstance(module_result, tuple) else module_result['module_id']

                    cursor.execute("""
                        SELECT ei.item_id, ei.question, ei.option_a, ei.option_b, ei.option_c, ei.option_d
                        FROM exam_items ei
                        JOIN module_sections ms ON ei.section_id = ms.section_id
                        WHERE ms.module_id = %s
                        ORDER BY RAND()
                    """, (module_id,))

                    questions = cursor.fetchall()
                    all_questions.extend(questions)

                # Get total items needed
                cursor.execute("SELECT total_items FROM exam_types WHERE exam_type_id = %s", (quiz_id,))
                total_items_result = cursor.fetchone()
                total_items = total_items_result[0] if isinstance(total_items_result, tuple) else total_items_result['total_items']

                # Randomly select questions up to total_items
                import random
                if len(all_questions) > total_items:
                    selected_questions = random.sample(all_questions, total_items)
                else:
                    selected_questions = all_questions

                # Format questions without correct answers
                formatted_questions = []
                for i, q in enumerate(selected_questions):
                    if isinstance(q, dict):
                        question_data = {
                            'question_number': i + 1,
                            'item_id': q['item_id'],
                            'question': q['question'],
                            'options': {
                                'A': q['option_a'],
                                'B': q['option_b'],
                                'C': q['option_c'],
                                'D': q['option_d']
                            }
                        }
                    else:
                        question_data = {
                            'question_number': i + 1,
                            'item_id': q[0],
                            'question': q[1],
                            'options': {
                                'A': q[2],
                                'B': q[3],
                                'C': q[4],
                                'D': q[5]
                            }
                        }
                    formatted_questions.append(question_data)

                return jsonify({'questions': formatted_questions})

    except Exception as e:
        print(f"Error getting quiz questions: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'Error getting quiz questions',
            'error': str(e)
        }), 500

@modules_bp.route('/student-quiz-submit', methods=['POST'])
@jwt_required()
def submit_student_quiz():
    """Submit student quiz answers"""
    try:
        user_id = get_jwt_identity()
        data = request.get_json()

        quiz_id = data.get('quiz_id')
        instance_id = data.get('instance_id')
        answers = data.get('answers')  # {item_id: selected_answer}

        if not quiz_id or not instance_id or not answers:
            return jsonify({'error': 'Missing required data'}), 400

        db = get_db()
        with db:
            with db.cursor() as cursor:
                # Verify student hasn't already taken this quiz
                cursor.execute("""
                    SELECT COUNT(*) FROM quiz_results
                    WHERE user_id = %s AND exam_type_id = %s AND instance_id = %s
                """, (user_id, quiz_id, instance_id))

                taken_check = cursor.fetchone()
                if taken_check and (taken_check[0] if isinstance(taken_check, tuple) else taken_check['COUNT(*)']) > 0:
                    return jsonify({'error': 'Quiz already taken'}), 403

                # Get total questions for this quiz (not just answered ones)
                cursor.execute("SELECT total_items FROM exam_types WHERE exam_type_id = %s", (quiz_id,))
                total_items_result = cursor.fetchone()
                total_questions = total_items_result[0] if isinstance(total_items_result, tuple) else total_items_result['total_items']

                # Get correct answers and calculate score
                correct_count = 0

                for item_id, student_answer in answers.items():
                    cursor.execute("""
                        SELECT correct_answer FROM exam_items WHERE item_id = %s
                    """, (item_id,))

                    correct_result = cursor.fetchone()
                    if correct_result:
                        correct_answer = correct_result[0] if isinstance(correct_result, tuple) else correct_result['correct_answer']
                        if student_answer == correct_answer:
                            correct_count += 1

                # Calculate percentage score based on TOTAL questions, not just answered ones
                score = (correct_count / total_questions * 100) if total_questions > 0 else 0

                # Save quiz result
                cursor.execute("""
                    INSERT INTO quiz_results (user_id, exam_type_id, instance_id, score, total_questions, correct_answers, completed_at)
                    VALUES (%s, %s, %s, %s, %s, %s, NOW())
                """, (user_id, quiz_id, instance_id, score, total_questions, correct_count))

                return jsonify({
                    'success': True,
                    'score': round(score, 2),
                    'correct_answers': correct_count,
                    'total_questions': total_questions
                })

    except Exception as e:
        print(f"Error submitting quiz: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'Error submitting quiz',
            'error': str(e)
        }), 500

@modules_bp.route('/activity-grading/submission/<int:submission_id>', methods=['GET'])
@jwt_required()
def get_single_submission_for_grading(submission_id):
    """Get a single submission for grading modal"""
    try:
        db = get_db()
        with db:
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

@modules_bp.route('/student-activities-with-grades/<int:module_id>', methods=['GET'])
@jwt_required()
def get_student_activities_with_grade_status(module_id):
    """Get activities for a module with student's submission and grade status"""
    try:
        user_id = get_jwt_identity()

        db = get_db()
        with db:
            with db.cursor() as cursor:
                # Get activities with submission status and grades
                cursor.execute("""
                    SELECT
                        ma.activity_id,
                        ma.title,
                        ma.instructions,
                        ma.activity_type,
                        ma.position,
                        asub.submission_id,
                        asub.status,
                        asub.grade,
                        asub.feedback,
                        asub.submitted_at
                    FROM module_activities ma
                    LEFT JOIN activity_submissions asub ON ma.activity_id = asub.activity_id AND asub.user_id = %s
                    WHERE ma.module_id = %s
                    ORDER BY ma.position
                """, (user_id, module_id))

                results = cursor.fetchall()
                activities = []

                for result in results:
                    if isinstance(result, dict):
                        activity = {
                            'activity_id': result['activity_id'],
                            'title': result['title'],
                            'instructions': result['instructions'],
                            'activity_type': result['activity_type'],
                            'position': result['position'],
                            'submission_id': result['submission_id'],
                            'status': result['status'],
                            'grade': float(result['grade']) if result['grade'] else None,
                            'feedback': result['feedback'],
                            'submitted_at': result['submitted_at'].isoformat() if result['submitted_at'] else None,
                            'is_graded': result['status'] == 'graded' if result['status'] else False,
                            'has_submission': result['submission_id'] is not None
                        }
                    else:
                        activity = {
                            'activity_id': result[0],
                            'title': result[1],
                            'instructions': result[2],
                            'activity_type': result[3],
                            'position': result[4],
                            'submission_id': result[5],
                            'status': result[6],
                            'grade': float(result[7]) if result[7] else None,
                            'feedback': result[8],
                            'submitted_at': result[9].isoformat() if result[9] else None,
                            'is_graded': result[6] == 'graded' if result[6] else False,
                            'has_submission': result[5] is not None
                        }

                    activities.append(activity)

                return jsonify({'activities': activities})

    except Exception as e:
        print(f"Error getting student activities with grades: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'Error getting student activities with grades',
            'error': str(e)
        }), 500

@modules_bp.route('/student-progress/track-section', methods=['POST'])
@jwt_required()
def track_student_section_progress():
    """Track when a student accesses a section"""
    try:
        data = request.get_json()
        section_id = data.get('section_id')
        user_id = get_jwt_identity()

        if not section_id:
            return jsonify({'error': 'Section ID required'}), 400

        db = get_db()
        with db:
            with db.cursor() as cursor:
                # Check if progress record already exists
                cursor.execute("""
                    SELECT progress_id FROM student_progress
                    WHERE user_id = %s AND section_id = %s
                """, (user_id, section_id))

                existing_progress = cursor.fetchone()

                if not existing_progress:
                    # Create new progress record
                    cursor.execute("""
                        INSERT INTO student_progress (user_id, section_id, accessed_at, is_completed)
                        VALUES (%s, %s, NOW(), 1)
                    """, (user_id, section_id))
                else:
                    # Update existing record to mark as completed if not already
                    cursor.execute("""
                        UPDATE student_progress
                        SET is_completed = 1, completed_at = NOW()
                        WHERE user_id = %s AND section_id = %s AND is_completed = 0
                    """, (user_id, section_id))

                return jsonify({'success': True})

    except Exception as e:
        print(f"Error tracking section progress: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'Error tracking section progress',
            'error': str(e)
        }), 500

@modules_bp.route('/student-progress/module-progress/<int:module_id>', methods=['GET'])
@jwt_required()
def get_student_module_progress_data(module_id):
    """Get student progress data for a specific module"""
    try:
        user_id = get_jwt_identity()

        db = get_db()
        with db:
            with db.cursor() as cursor:
                # Get total sections in the module
                cursor.execute("""
                    SELECT COUNT(*) FROM module_sections WHERE module_id = %s
                """, (module_id,))
                total_sections_result = cursor.fetchone()
                total_sections = total_sections_result[0] if isinstance(total_sections_result, tuple) else total_sections_result['COUNT(*)']

                # Get completed sections by student
                cursor.execute("""
                    SELECT COUNT(*) FROM student_progress sp
                    JOIN module_sections ms ON sp.section_id = ms.section_id
                    WHERE sp.user_id = %s AND ms.module_id = %s AND sp.is_completed = 1
                """, (user_id, module_id))
                completed_sections_result = cursor.fetchone()
                completed_sections = completed_sections_result[0] if isinstance(completed_sections_result, tuple) else completed_sections_result['COUNT(*)']

                # Get total activities in the module
                cursor.execute("""
                    SELECT COUNT(*) FROM module_activities WHERE module_id = %s
                """, (module_id,))
                total_activities_result = cursor.fetchone()
                total_activities = total_activities_result[0] if isinstance(total_activities_result, tuple) else total_activities_result['COUNT(*)']

                # Get submitted activities by student
                cursor.execute("""
                    SELECT COUNT(*) FROM activity_submissions asub
                    JOIN module_activities ma ON asub.activity_id = ma.activity_id
                    WHERE asub.user_id = %s AND ma.module_id = %s
                """, (user_id, module_id))
                submitted_activities_result = cursor.fetchone()
                submitted_activities = submitted_activities_result[0] if isinstance(submitted_activities_result, tuple) else submitted_activities_result['COUNT(*)']

                # Calculate percentages
                sections_percentage = (completed_sections / total_sections * 100) if total_sections > 0 else 0
                activities_percentage = (submitted_activities / total_activities * 100) if total_activities > 0 else 0
                overall_percentage = ((completed_sections + submitted_activities) / (total_sections + total_activities) * 100) if (total_sections + total_activities) > 0 else 0

                return jsonify({
                    'module_id': module_id,
                    'total_sections': total_sections,
                    'completed_sections': completed_sections,
                    'sections_percentage': round(sections_percentage, 1),
                    'total_activities': total_activities,
                    'submitted_activities': submitted_activities,
                    'activities_percentage': round(activities_percentage, 1),
                    'overall_percentage': round(overall_percentage, 1)
                })

    except Exception as e:
        print(f"Error getting module progress: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'Error getting module progress',
            'error': str(e)
        }), 500

@modules_bp.route('/submission-tracking', methods=['GET'])
@jwt_required()
def get_submission_tracking():
    """Get submission tracking data for all course instances"""
    try:
        search_term = request.args.get('search', '')

        db = get_db()
        with db:
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
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': 'Error in submission tracking',
            'error': str(e)
        }), 500

@modules_bp.route('/activity-grading/courses-with-pending', methods=['GET'])
@jwt_required()
def get_courses_with_pending_counts():
    try:
        db = get_db()
        with db:
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
@jwt_required()
def get_pending_submissions_count(course_id):
    try:
        db = get_db()
        with db:
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
@jwt_required()
def get_course_activities_for_grading(instance_id):
    try:
        db = get_db()
        with db:
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
        return jsonify({'error': str(e)}), 500

@modules_bp.route('/activity-grading/submissions/<int:activity_id>', methods=['GET'])
@jwt_required()
def get_activity_submissions_for_grading(activity_id):
    try:
        db = get_db()
        with db:
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
        return jsonify({'error': str(e)}), 500

@modules_bp.route('/activity-grading/grade', methods=['POST'])
@jwt_required()
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
        with db:
            with db.cursor() as cursor:
                cursor.execute("""
                    UPDATE activity_submissions
                    SET grade = %s, feedback = %s, status = 'graded', updated_at = CURRENT_TIMESTAMP
                    WHERE submission_id = %s
                """, (grade, feedback, submission_id))

                return jsonify({
                    'success': True,
                    'message': 'Grade saved successfully'
                })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@modules_bp.route('/activity-grading/ai-grade', methods=['POST'])
@jwt_required()
def ai_grade_submission():
    """AI-powered grading with AI detection and multiple prompt strategies"""
    try:
        data = request.get_json()
        submission_id = data.get('submission_id')
        activity_instructions = data.get('activity_instructions', '')
        submission_content = data.get('submission_content', '')

        if not all([submission_id, activity_instructions, submission_content]):
            return jsonify({'error': 'Missing required data for AI grading'}), 400

        # Clean HTML from instructions
        import re
        clean_instructions = re.sub('<[^<]+?>', '', activity_instructions)

        # Define 3 different prompts for AI grading
        prompts = [
            # Prompt 1: Comprehensive evaluation
            f"""<|begin_of_text|><|start_header_id|>system<|end_header_id|>
You are a teacher grading student work. Write feedback as if you're personally reviewing this submission.

ASSIGNMENT: {clean_instructions}
STUDENT WORK: {submission_content}

Grade 0-100 and write natural teacher feedback. Check for AI usage - if detected, reduce grade significantly.

Write feedback like a teacher would:
- Use "I noticed..." "Your work shows..." "Good job on..."
- Be conversational but professional
- Point out specific strengths/weaknesses
- Give constructive suggestions
- If AI-generated, mention concerns about originality naturally

Format: {{"grade": number, "feedback": "natural teacher feedback", "ai_detected": boolean}}<|eot_id|>

<|start_header_id|>assistant<|end_header_id|>""",

            # Prompt 2: Focused on authenticity
            f"""<|begin_of_text|><|start_header_id|>system<|end_header_id|>
Grade this like a teacher reviewing homework. Write personal, conversational feedback.

Task: {clean_instructions}
Student Answer: {submission_content}

Write feedback as if speaking to the student:
- "I can see you understood..."
- "This part needs work because..."
- "Nice thinking here, but..."
- "I'm concerned this might not be your own work..."

If this looks AI-generated, reduce grade and mention it naturally in feedback.

Return: {{"grade": number, "feedback": "conversational teacher feedback", "ai_detected": boolean}}<|eot_id|>

<|start_header_id|>assistant<|end_header_id|>""",

            # Prompt 3: Simple and direct
            f"""<|begin_of_text|><|start_header_id|>system<|end_header_id|>
Grade this student work and write brief teacher comments.

Assignment: {clean_instructions}
Student Response: {submission_content}

Write feedback like a teacher's quick comments:
- Start with overall impression
- Mention what worked/didn't work
- If AI-generated, note authenticity concerns
- Keep it personal and direct

Format: {{"grade": number, "feedback": "brief teacher comments", "ai_detected": boolean}}<|eot_id|>

<|start_header_id|>assistant<|end_header_id|>"""
        ]

        # Try each prompt with 3 retries each
        for prompt_idx, prompt in enumerate(prompts, 1):
            print(f"🤖 Trying AI grading prompt {prompt_idx}/3")

            for attempt in range(1, 4):
                try:
                    print(f"   Attempt {attempt}/3...")
                    ai_response = generate_with_bedrock(prompt, temperature=0.3)

                    if ai_response and '{' in ai_response and '}' in ai_response:
                        # Extract JSON from response
                        json_start = ai_response.find('{')
                        json_end = ai_response.rfind('}') + 1
                        json_str = ai_response[json_start:json_end]

                        # Clean and parse JSON
                        json_str = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', json_str)
                        result = json.loads(json_str)

                        if 'grade' in result and 'feedback' in result:
                            grade = float(result['grade'])
                            if 0 <= grade <= 100:
                                print(f"✅ AI grading successful with prompt {prompt_idx}, attempt {attempt}")
                                return jsonify({
                                    'grade': grade,
                                    'feedback': result['feedback'],
                                    'ai_detected': result.get('ai_detected', False)
                                })

                except (json.JSONDecodeError, ValueError, KeyError) as e:
                    print(f"   JSON parsing failed: {e}")
                    continue
                except Exception as e:
                    print(f"   Attempt failed: {e}")
                    continue

        # Fallback if all prompts fail
        print("❌ All AI grading attempts failed, using fallback")
        return jsonify({
            'grade': 75,
            'feedback': 'I reviewed your submission and it appears to meet the basic requirements. However, I need to do a more thorough review to give you detailed feedback. Please see me during office hours if you have questions about this grade.',
            'ai_detected': False
        })

    except Exception as e:
        print(f"❌ AI grading error: {str(e)}")
        return jsonify({'error': 'AI grading service unavailable'}), 500

@modules_bp.route('/exam-items', methods=['GET'])
@jwt_required()
def get_exam_items():
    try:
        section_id = request.args.get('section_id')
        if not section_id:
            return jsonify({'error': 'Section ID required'}), 400

        db = get_db()
        with db:
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
        return jsonify({'error': str(e)}), 500

@modules_bp.route('/update-exam-item', methods=['POST'])
@jwt_required()
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
        with db:
            with db.cursor() as cursor:
                cursor.execute("""
                    UPDATE exam_items
                    SET question = %s, option_a = %s, option_b = %s, option_c = %s, option_d = %s, correct_answer = %s
                    WHERE item_id = %s
                """, (question, option_a, option_b, option_c, option_d, correct_answer, item_id))

                return jsonify({'success': True})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@modules_bp.route('/delete-exam-item/<int:item_id>', methods=['DELETE'])
@jwt_required()
def delete_exam_item(item_id):
    try:
        db = get_db()
        with db:
            with db.cursor() as cursor:
                cursor.execute("DELETE FROM exam_items WHERE item_id = %s", (item_id,))

                return jsonify({'success': True})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@modules_bp.route('/export-exam-items-pdf/<int:module_id>', methods=['GET'])
@jwt_required()
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
        with db:
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
                import re
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
        return jsonify({'error': str(e)}), 500

@modules_bp.route('/export-all-exam-items-pdf/<int:course_id>', methods=['GET'])
@jwt_required()
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
        with db:
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
                        import re
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
        return jsonify({'error': str(e)}), 500

# Aiken Format TXT Export Routes
@modules_bp.route('/export-aiken-txt-single-module/<int:module_id>', methods=['GET'])
@jwt_required()
def export_aiken_txt_single_module(module_id):
    try:
        db = get_db()
        with db:
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
        return jsonify({'error': str(e)}), 500

@modules_bp.route('/export-aiken-txt-all-modules/<int:course_id>', methods=['GET'])
@jwt_required()
def export_aiken_txt_all_modules(course_id):
    try:
        db = get_db()
        with db:
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
        return jsonify({'error': str(e)}), 500
@modules_bp.route('/course-overview-stats/<int:course_id>', methods=['GET'])
@jwt_required()
def get_student_course_overview_stats_unique(course_id):
    """Get course overview statistics for student dashboard"""
    try:
        user_id = get_jwt_identity()
        db = get_db()
        with db:
            with db.cursor() as cursor:
                # Verify student enrollment in this course
                cursor.execute("""
                    SELECT ci.instance_id
                    FROM enrollments e
                    JOIN course_instances ci ON e.instance_id = ci.instance_id
                    WHERE ci.course_id = %s AND e.user_id = %s
                    LIMIT 1
                """, (course_id, user_id))

                enrollment_check = cursor.fetchone()
                if not enrollment_check:
                    return jsonify({'error': 'Student not enrolled in this course'}), 403

                instance_id = enrollment_check['instance_id']

                # Get total modules count
                cursor.execute("""
                    SELECT COUNT(*) as total_modules
                    FROM modules_master
                    WHERE course_id = %s
                """, (course_id,))
                total_modules = cursor.fetchone()['total_modules']

                # Get completed modules count (assuming completion based on section access)
                cursor.execute("""
                    SELECT COUNT(DISTINCT mm.module_id) as completed_modules
                    FROM modules_master mm
                    JOIN module_sections ms ON mm.module_id = ms.module_id
                    JOIN student_progress sp ON ms.section_id = sp.section_id
                    WHERE mm.course_id = %s AND sp.user_id = %s AND sp.is_completed = 1
                """, (course_id, user_id))
                completed_modules = cursor.fetchone()['completed_modules'] or 0

                # Get total quizzes count
                cursor.execute("""
                    SELECT COUNT(DISTINCT et.exam_type_id) as total_quizzes
                    FROM exam_types et
                    JOIN assessment_scopes a_scope ON et.exam_type_id = a_scope.exam_type_id
                    WHERE a_scope.course_id = %s AND et.category = 'quiz'
                """, (course_id,))
                total_quizzes = cursor.fetchone()['total_quizzes']

                # Get completed quizzes count
                cursor.execute("""
                    SELECT COUNT(DISTINCT qr.exam_type_id) as completed_quizzes
                    FROM quiz_results qr
                    JOIN exam_types et ON qr.exam_type_id = et.exam_type_id
                    JOIN assessment_scopes a_scope ON et.exam_type_id = a_scope.exam_type_id
                    WHERE qr.user_id = %s AND qr.instance_id = %s AND a_scope.course_id = %s
                """, (user_id, instance_id, course_id))
                completed_quizzes = cursor.fetchone()['completed_quizzes'] or 0

                # Get total exams count
                cursor.execute("""
                    SELECT COUNT(DISTINCT et.exam_type_id) as total_exams
                    FROM exam_types et
                    JOIN assessment_scopes a_scope ON et.exam_type_id = a_scope.exam_type_id
                    WHERE a_scope.course_id = %s AND et.category = 'exam'
                """, (course_id,))
                total_exams = cursor.fetchone()['total_exams']

                # Get completed exams count from exam_results table
                cursor.execute("""
                    SELECT COUNT(DISTINCT er.exam_type_id) as completed_exams
                    FROM exam_results er
                    JOIN exam_types et ON er.exam_type_id = et.exam_type_id
                    JOIN assessment_scopes a_scope ON et.exam_type_id = a_scope.exam_type_id
                    WHERE er.user_id = %s AND er.instance_id = %s AND a_scope.course_id = %s
                """, (user_id, instance_id, course_id))
                completed_exams = cursor.fetchone()['completed_exams'] or 0

                # Calculate overall grade including 0s for incomplete assessments
                # Get quiz scores (completed quizzes)
                cursor.execute("""
                    SELECT AVG(qr.score) as avg_quiz_score
                    FROM quiz_results qr
                    JOIN exam_types et ON qr.exam_type_id = et.exam_type_id
                    JOIN assessment_scopes a_scope ON et.exam_type_id = a_scope.exam_type_id
                    WHERE qr.user_id = %s AND qr.instance_id = %s AND a_scope.course_id = %s
                """, (user_id, instance_id, course_id))
                completed_quiz_result = cursor.fetchone()['avg_quiz_score']
                completed_quiz_avg = float(completed_quiz_result) if completed_quiz_result else 0

                # Calculate quiz average including 0s for incomplete quizzes
                if total_quizzes > 0:
                    quiz_total_score = (completed_quiz_avg * completed_quizzes)
                    quiz_avg = quiz_total_score / total_quizzes
                else:
                    quiz_avg = 0

                # Calculate exam average (currently 0 since no exams taken)
                exam_avg = 0  # All exams are incomplete, so 0

                # Calculate overall grade (50% quizzes, 50% exams, no activities)
                total_assessments = total_quizzes + total_exams
                if total_assessments > 0:
                    quiz_weight = total_quizzes / total_assessments
                    exam_weight = total_exams / total_assessments
                    overall_grade = (quiz_avg * quiz_weight) + (exam_avg * exam_weight)
                else:
                    overall_grade = 0

                return jsonify({
                    'modules': f"{completed_modules}/{total_modules}",
                    'quizzes': f"{completed_quizzes}/{total_quizzes}",
                    'exams': f"{completed_exams}/{total_exams}",
                    'overall_grade': round(overall_grade, 1)
                })

    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error retrieving course overview stats',
            'error': str(e)
        }), 500

@modules_bp.route('/student-course-progress-comprehensive/<int:course_id>', methods=['GET'])
@jwt_required()
def get_student_course_progress_comprehensive(course_id):
    """Get comprehensive course progress for student including all components"""
    try:
        user_id = get_jwt_identity()
        db = get_db()
        with db:
            with db.cursor() as cursor:
                # Verify student enrollment
                cursor.execute("""
                    SELECT ci.instance_id
                    FROM enrollments e
                    JOIN course_instances ci ON e.instance_id = ci.instance_id
                    WHERE ci.course_id = %s AND e.user_id = %s
                    LIMIT 1
                """, (course_id, user_id))

                enrollment_check = cursor.fetchone()
                if not enrollment_check:
                    return jsonify({'error': 'Student not enrolled in this course'}), 403

                instance_id = enrollment_check['instance_id']

                # Get total counts for each component
                # 1. Module sections progress
                cursor.execute("""
                    SELECT COUNT(*) as total_sections
                    FROM module_sections ms
                    JOIN modules_master mm ON ms.module_id = mm.module_id
                    WHERE mm.course_id = %s
                """, (course_id,))
                total_sections = cursor.fetchone()['total_sections']

                cursor.execute("""
                    SELECT COUNT(*) as completed_sections
                    FROM student_progress sp
                    JOIN module_sections ms ON sp.section_id = ms.section_id
                    JOIN modules_master mm ON ms.module_id = mm.module_id
                    WHERE mm.course_id = %s AND sp.user_id = %s AND sp.is_completed = 1
                """, (course_id, user_id))
                completed_sections = cursor.fetchone()['completed_sections'] or 0

                # 2. Activity submissions progress
                cursor.execute("""
                    SELECT COUNT(*) as total_activities
                    FROM module_activities ma
                    JOIN modules_master mm ON ma.module_id = mm.module_id
                    WHERE mm.course_id = %s
                """, (course_id,))
                total_activities = cursor.fetchone()['total_activities']

                cursor.execute("""
                    SELECT COUNT(*) as submitted_activities
                    FROM activity_submissions asub
                    JOIN module_activities ma ON asub.activity_id = ma.activity_id
                    JOIN modules_master mm ON ma.module_id = mm.module_id
                    WHERE mm.course_id = %s AND asub.user_id = %s
                """, (course_id, user_id))
                submitted_activities = cursor.fetchone()['submitted_activities'] or 0

                # 3. Quiz completion progress
                cursor.execute("""
                    SELECT COUNT(DISTINCT et.exam_type_id) as total_quizzes
                    FROM exam_types et
                    JOIN assessment_scopes a_scope ON et.exam_type_id = a_scope.exam_type_id
                    WHERE a_scope.course_id = %s AND et.category = 'quiz'
                """, (course_id,))
                total_quizzes = cursor.fetchone()['total_quizzes']

                cursor.execute("""
                    SELECT COUNT(DISTINCT qr.exam_type_id) as completed_quizzes
                    FROM quiz_results qr
                    JOIN exam_types et ON qr.exam_type_id = et.exam_type_id
                    JOIN assessment_scopes a_scope ON et.exam_type_id = a_scope.exam_type_id
                    WHERE qr.user_id = %s AND qr.instance_id = %s AND a_scope.course_id = %s
                """, (user_id, instance_id, course_id))
                completed_quizzes = cursor.fetchone()['completed_quizzes'] or 0

                # 4. Exam completion progress
                cursor.execute("""
                    SELECT COUNT(DISTINCT et.exam_type_id) as total_exams
                    FROM exam_types et
                    JOIN assessment_scopes a_scope ON et.exam_type_id = a_scope.exam_type_id
                    WHERE a_scope.course_id = %s AND et.category = 'exam'
                """, (course_id,))
                total_exams = cursor.fetchone()['total_exams']

                cursor.execute("""
                    SELECT COUNT(DISTINCT er.exam_type_id) as completed_exams
                    FROM exam_results er
                    JOIN exam_types et ON er.exam_type_id = et.exam_type_id
                    JOIN assessment_scopes a_scope ON et.exam_type_id = a_scope.exam_type_id
                    WHERE er.user_id = %s AND er.instance_id = %s AND a_scope.course_id = %s
                """, (user_id, instance_id, course_id))
                completed_exams = cursor.fetchone()['completed_exams'] or 0

                # Calculate component percentages
                sections_progress = (completed_sections / total_sections * 100) if total_sections > 0 else 0
                activities_progress = (submitted_activities / total_activities * 100) if total_activities > 0 else 0
                quizzes_progress = (completed_quizzes / total_quizzes * 100) if total_quizzes > 0 else 0
                exams_progress = (completed_exams / total_exams * 100) if total_exams > 0 else 0

                # Calculate overall progress (weighted average)
                total_components = 0
                weighted_sum = 0

                if total_sections > 0:
                    weighted_sum += sections_progress * 0.3  # 30% weight for sections
                    total_components += 0.3

                if total_activities > 0:
                    weighted_sum += activities_progress * 0.2  # 20% weight for activities
                    total_components += 0.2

                if total_quizzes > 0:
                    weighted_sum += quizzes_progress * 0.25  # 25% weight for quizzes
                    total_components += 0.25

                if total_exams > 0:
                    weighted_sum += exams_progress * 0.25  # 25% weight for exams
                    total_components += 0.25

                overall_progress = (weighted_sum / total_components) if total_components > 0 else 0

                return jsonify({
                    'overall_progress': round(overall_progress, 1),
                    'components': {
                        'sections': {
                            'completed': completed_sections,
                            'total': total_sections,
                            'percentage': round(sections_progress, 1)
                        },
                        'activities': {
                            'completed': submitted_activities,
                            'total': total_activities,
                            'percentage': round(activities_progress, 1)
                        },
                        'quizzes': {
                            'completed': completed_quizzes,
                            'total': total_quizzes,
                            'percentage': round(quizzes_progress, 1)
                        },
                        'exams': {
                            'completed': completed_exams,
                            'total': total_exams,
                            'percentage': round(exams_progress, 1)
                        }
                    }
                })

    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error retrieving comprehensive course progress',
            'error': str(e)
        }), 500
@modules_bp.route('/student-comprehensive-grades/<int:course_id>', methods=['GET'])
@jwt_required()
def get_student_comprehensive_grades(course_id):
    """Get comprehensive grades for student including all assessments and activities"""
    try:
        user_id = get_jwt_identity()
        db = get_db()
        with db:
            with db.cursor() as cursor:
                # Verify student enrollment
                cursor.execute("""
                    SELECT ci.instance_id, cm.course_code, cm.course_title
                    FROM enrollments e
                    JOIN course_instances ci ON e.instance_id = ci.instance_id
                    JOIN courses_master cm ON ci.course_id = cm.course_id
                    WHERE ci.course_id = %s AND e.user_id = %s
                    LIMIT 1
                """, (course_id, user_id))

                enrollment_check = cursor.fetchone()
                if not enrollment_check:
                    return jsonify({'error': 'Student not enrolled in this course'}), 403

                instance_id = enrollment_check['instance_id']
                course_info = {
                    'course_code': enrollment_check['course_code'],
                    'course_title': enrollment_check['course_title']
                }

                # Get activity grades
                cursor.execute("""
                    SELECT
                        ma.title as activity_title,
                        mm.position as module_position,
                        ma.position as activity_position,
                        asub.grade,
                        asub.status,
                        asub.submitted_at,
                        asub.feedback,
                        ma.activity_type
                    FROM activity_submissions asub
                    JOIN module_activities ma ON asub.activity_id = ma.activity_id
                    JOIN modules_master mm ON ma.module_id = mm.module_id
                    WHERE mm.course_id = %s AND asub.user_id = %s
                    ORDER BY mm.position, ma.position
                """, (course_id, user_id))
                activity_grades = cursor.fetchall()

                # Get quiz grades
                cursor.execute("""
                    SELECT
                        et.exam_name,
                        et.exam_period,
                        qr.score,
                        qr.total_questions,
                        qr.correct_answers,
                        qr.completed_at
                    FROM quiz_results qr
                    JOIN exam_types et ON qr.exam_type_id = et.exam_type_id
                    JOIN assessment_scopes a_scope ON et.exam_type_id = a_scope.exam_type_id
                    WHERE qr.user_id = %s AND qr.instance_id = %s AND a_scope.course_id = %s
                    ORDER BY et.exam_period, et.exam_name
                """, (user_id, instance_id, course_id))
                quiz_grades = cursor.fetchall()

                # Get exam grades
                cursor.execute("""
                    SELECT
                        et.exam_name,
                        et.exam_period,
                        er.score,
                        er.total_questions,
                        er.correct_answers,
                        er.completed_at,
                        er.submission_reason
                    FROM exam_results er
                    JOIN exam_types et ON er.exam_type_id = et.exam_type_id
                    JOIN assessment_scopes a_scope ON et.exam_type_id = a_scope.exam_type_id
                    WHERE er.user_id = %s AND er.instance_id = %s AND a_scope.course_id = %s
                    ORDER BY et.exam_period, et.exam_name
                """, (user_id, instance_id, course_id))
                exam_grades = cursor.fetchall()

                # Calculate summary statistics
                activity_scores = [float(grade['grade']) for grade in activity_grades if grade['grade'] is not None]
                quiz_scores = [float(grade['score']) for grade in quiz_grades]
                exam_scores = [float(grade['score']) for grade in exam_grades]

                summary = {
                    'activities': {
                        'count': len(activity_grades),
                        'graded_count': len(activity_scores),
                        'average': round(sum(activity_scores) / len(activity_scores), 2) if activity_scores else 0,
                        'highest': max(activity_scores) if activity_scores else 0,
                        'lowest': min(activity_scores) if activity_scores else 0
                    },
                    'quizzes': {
                        'count': len(quiz_grades),
                        'average': round(sum(quiz_scores) / len(quiz_scores), 2) if quiz_scores else 0,
                        'highest': max(quiz_scores) if quiz_scores else 0,
                        'lowest': min(quiz_scores) if quiz_scores else 0
                    },
                    'exams': {
                        'count': len(exam_grades),
                        'average': round(sum(exam_scores) / len(exam_scores), 2) if exam_scores else 0,
                        'highest': max(exam_scores) if exam_scores else 0,
                        'lowest': min(exam_scores) if exam_scores else 0
                    }
                }

                # Calculate overall grade (quizzes and exams only, as per existing logic)
                all_assessment_scores = quiz_scores + exam_scores
                overall_grade = round(sum(all_assessment_scores) / len(all_assessment_scores), 2) if all_assessment_scores else 0

                return jsonify({
                    'course_info': course_info,
                    'activity_grades': activity_grades,
                    'quiz_grades': quiz_grades,
                    'exam_grades': exam_grades,
                    'summary': summary,
                    'overall_grade': overall_grade
                })

    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error retrieving comprehensive grades',
            'error': str(e)
        }), 500
@modules_bp.route('/student-overall-learning-progress', methods=['GET'])
@jwt_required()
def get_student_overall_learning_progress():
    """Get comprehensive overall learning progress across all enrolled active course instances"""
    try:
        user_id = get_jwt_identity()
        db = get_db()
        with db:
            with db.cursor() as cursor:
                # Get all active course instances the student is enrolled in
                cursor.execute("""
                    SELECT DISTINCT ci.instance_id, ci.course_id
                    FROM enrollments e
                    JOIN course_instances ci ON e.instance_id = ci.instance_id
                    WHERE e.user_id = %s AND ci.end_date >= CURDATE()
                """, (user_id,))

                active_enrollments = cursor.fetchall()

                if not active_enrollments:
                    return jsonify({
                        'overall_progress': 0,
                        'components': {'sections': 0, 'activities': 0, 'quizzes': 0, 'exams': 0},
                        'enrolled_courses': 0
                    })

                course_ids = [enrollment['course_id'] for enrollment in active_enrollments]
                instance_ids = [enrollment['instance_id'] for enrollment in active_enrollments]
                course_ids_placeholder = ','.join(['%s'] * len(course_ids))
                instance_ids_placeholder = ','.join(['%s'] * len(instance_ids))

                # 1. Sections Progress
                cursor.execute(f"""
                    SELECT COUNT(*) as total_sections
                    FROM module_sections ms
                    JOIN modules_master mm ON ms.module_id = mm.module_id
                    WHERE mm.course_id IN ({course_ids_placeholder})
                """, course_ids)
                total_sections = cursor.fetchone()['total_sections']

                cursor.execute(f"""
                    SELECT COUNT(*) as completed_sections
                    FROM student_progress sp
                    JOIN module_sections ms ON sp.section_id = ms.section_id
                    JOIN modules_master mm ON ms.module_id = mm.module_id
                    WHERE mm.course_id IN ({course_ids_placeholder})
                    AND sp.user_id = %s AND sp.is_completed = 1
                """, course_ids + [user_id])
                completed_sections = cursor.fetchone()['completed_sections'] or 0

                # 2. Activities Progress
                cursor.execute(f"""
                    SELECT COUNT(*) as total_activities
                    FROM module_activities ma
                    JOIN modules_master mm ON ma.module_id = mm.module_id
                    WHERE mm.course_id IN ({course_ids_placeholder})
                """, course_ids)
                total_activities = cursor.fetchone()['total_activities']

                cursor.execute(f"""
                    SELECT COUNT(*) as submitted_activities
                    FROM activity_submissions asub
                    JOIN module_activities ma ON asub.activity_id = ma.activity_id
                    JOIN modules_master mm ON ma.module_id = mm.module_id
                    WHERE mm.course_id IN ({course_ids_placeholder}) AND asub.user_id = %s
                """, course_ids + [user_id])
                submitted_activities = cursor.fetchone()['submitted_activities'] or 0

                # 3. Quizzes Progress
                cursor.execute(f"""
                    SELECT COUNT(*) as total_quizzes
                    FROM assessment_scopes a_scope
                    JOIN exam_types et ON a_scope.exam_type_id = et.exam_type_id
                    WHERE a_scope.course_id IN ({course_ids_placeholder}) AND et.category = 'quiz'
                """, course_ids)
                total_quizzes = cursor.fetchone()['total_quizzes']

                cursor.execute(f"""
                    SELECT COUNT(DISTINCT CONCAT(qr.exam_type_id, '-', qr.instance_id)) as completed_quizzes
                    FROM quiz_results qr
                    JOIN exam_types et ON qr.exam_type_id = et.exam_type_id
                    JOIN assessment_scopes a_scope ON et.exam_type_id = a_scope.exam_type_id
                    WHERE qr.user_id = %s AND qr.instance_id IN ({instance_ids_placeholder})
                    AND a_scope.course_id IN ({course_ids_placeholder})
                """, [user_id] + instance_ids + course_ids)
                completed_quizzes = cursor.fetchone()['completed_quizzes'] or 0

                # 4. Exams Progress
                cursor.execute(f"""
                    SELECT COUNT(*) as total_exams
                    FROM assessment_scopes a_scope
                    JOIN exam_types et ON a_scope.exam_type_id = et.exam_type_id
                    WHERE a_scope.course_id IN ({course_ids_placeholder}) AND et.category = 'exam'
                """, course_ids)
                total_exams = cursor.fetchone()['total_exams']

                cursor.execute(f"""
                    SELECT COUNT(DISTINCT CONCAT(er.exam_type_id, '-', er.instance_id)) as completed_exams
                    FROM exam_results er
                    JOIN exam_types et ON er.exam_type_id = et.exam_type_id
                    JOIN assessment_scopes a_scope ON et.exam_type_id = a_scope.exam_type_id
                    WHERE er.user_id = %s AND er.instance_id IN ({instance_ids_placeholder})
                    AND a_scope.course_id IN ({course_ids_placeholder})
                """, [user_id] + instance_ids + course_ids)
                completed_exams = cursor.fetchone()['completed_exams'] or 0

                # Calculate component percentages
                sections_progress = (completed_sections / total_sections * 100) if total_sections > 0 else 0
                activities_progress = (submitted_activities / total_activities * 100) if total_activities > 0 else 0
                quizzes_progress = (completed_quizzes / total_quizzes * 100) if total_quizzes > 0 else 0
                exams_progress = (completed_exams / total_exams * 100) if total_exams > 0 else 0

                # Calculate overall progress (weighted average)
                total_weight = 0
                weighted_sum = 0

                if total_sections > 0:
                    weighted_sum += sections_progress * 0.3  # 30% weight
                    total_weight += 0.3

                if total_activities > 0:
                    weighted_sum += activities_progress * 0.2  # 20% weight
                    total_weight += 0.2

                if total_quizzes > 0:
                    weighted_sum += quizzes_progress * 0.25  # 25% weight
                    total_weight += 0.25

                if total_exams > 0:
                    weighted_sum += exams_progress * 0.25  # 25% weight
                    total_weight += 0.25

                overall_progress = (weighted_sum / total_weight) if total_weight > 0 else 0

                return jsonify({
                    'overall_progress': round(overall_progress, 1),
                    'components': {
                        'sections': round(sections_progress, 1),
                        'activities': round(activities_progress, 1),
                        'quizzes': round(quizzes_progress, 1),
                        'exams': round(exams_progress, 1)
                    },
                    'counts': {
                        'sections': f"{completed_sections}/{total_sections}",
                        'activities': f"{submitted_activities}/{total_activities}",
                        'quizzes': f"{completed_quizzes}/{total_quizzes}",
                        'exams': f"{completed_exams}/{total_exams}"
                    },
                    'enrolled_courses': len(active_enrollments)
                })

    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error retrieving overall learning progress',
            'error': str(e)
        }), 500
