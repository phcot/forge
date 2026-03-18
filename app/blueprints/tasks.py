from datetime import date
import json
import base64
from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify, Response, stream_with_context
from app import db
from app.models import Task, now_eastern
from app.blueprints.main import login_required
import anthropic

tasks_bp = Blueprint('tasks', __name__)

AI_MODEL = 'claude-sonnet-4-6'
MAX_AI_TASKS = 5


@tasks_bp.route('/task/new', methods=['GET', 'POST'])
@login_required
def new_task():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        if not title:
            flash('Title is required.')
            return render_template('task_form.html', task=None)

        task = Task(
            title=title,
            description=request.form.get('description', ''),
            status=request.form.get('status', 'not_started'),
            priority=request.form.get('priority', 'medium'),
            size=request.form.get('size', 'M'),
            deliverable=request.form.get('deliverable', ''),
            reporting_to=request.form.get('reporting_to', ''),
            waiting_on=request.form.get('waiting_on', ''),
            product_area=request.form.get('product_area', ''),
        )

        deadline_str = request.form.get('deadline', '').strip()
        if deadline_str:
            try:
                task.deadline = date.fromisoformat(deadline_str)
            except ValueError:
                pass

        sort_str = request.form.get('sort_order', '0').strip()
        task.sort_order = int(sort_str) if sort_str.isdigit() else 0

        db.session.add(task)
        db.session.commit()
        return redirect(url_for('tasks.task_detail', task_id=task.id))

    return render_template('task_form.html', task=None)


@tasks_bp.route('/task/<int:task_id>', methods=['GET'])
@login_required
def task_detail(task_id):
    task = Task.query.get_or_404(task_id)
    messages = [m for m in task.messages if m.task_id == task.id]
    messages.sort(key=lambda m: m.created_at)
    # Determine back URL from Referer, default to dashboard
    referer = request.headers.get('Referer', '')
    back_url = '/'
    if referer:
        from urllib.parse import urlparse
        path = urlparse(referer).path
        if path in ('/archive', '/learning', '/chat'):
            back_url = path
    return render_template('task_detail.html', task=task, messages=messages, back_url=back_url)


@tasks_bp.route('/task/<int:task_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_task(task_id):
    task = Task.query.get_or_404(task_id)

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        if not title:
            flash('Title is required.')
            return render_template('task_form.html', task=task)

        task.title = title
        task.description = request.form.get('description', '')
        old_status = task.status
        task.status = request.form.get('status', task.status)
        task.priority = request.form.get('priority', task.priority)
        task.size = request.form.get('size', task.size)
        task.deliverable = request.form.get('deliverable', '')
        task.reporting_to = request.form.get('reporting_to', '')
        task.waiting_on = request.form.get('waiting_on', '')
        task.product_area = request.form.get('product_area', '')

        deadline_str = request.form.get('deadline', '').strip()
        if deadline_str:
            try:
                task.deadline = date.fromisoformat(deadline_str)
            except ValueError:
                task.deadline = None
        else:
            task.deadline = None

        sort_str = request.form.get('sort_order', '0').strip()
        task.sort_order = int(sort_str) if sort_str.isdigit() else 0

        if task.status == 'done' and old_status != 'done':
            task.completed_at = now_eastern()
        elif task.status != 'done':
            task.completed_at = None

        db.session.commit()
        return redirect(url_for('tasks.task_detail', task_id=task.id))

    return render_template('task_form.html', task=task)


@tasks_bp.route('/task/<int:task_id>/delete', methods=['POST'])
@login_required
def delete_task(task_id):
    task = Task.query.get_or_404(task_id)
    db.session.delete(task)
    db.session.commit()
    return redirect(url_for('main.dashboard'))


# ── AI-powered task creation endpoint ────────────────────────────

CREATE_TASK_TOOL = {
    "name": "create_task",
    "description": "Create a new task. Call this once per task to create.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Short, clear task title."},
            "description": {"type": "string", "description": "Optional longer description."},
            "priority": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
            "size": {"type": "string", "enum": ["S", "M", "L"]},
            "product_area": {"type": "string", "description": "E.g. 'Career: PRD-LIMCA', 'Home: Maintenance', 'Family'."},
            "deadline": {"type": "string", "description": "YYYY-MM-DD format."},
            "work_location": {"type": "string", "enum": ["remote", "office", "hybrid"]},
        },
        "required": ["title"]
    }
}

PRODUCT_AREAS = [
    "Career: PLM-METAL", "Career: PRJ-ALNEXT2", "Career: PRD-ALSCAN",
    "Career: PRD-LIMCA", "Career: PRD-PREFIL/PODFA", "Career: SYST-ENG-ADMIN",
    "Enterprises: Rudbeckie", "Enterprises: Personal",
    "Home: Maintenance", "Home: Renovation",
    "Family",
    "Growth & Admin: Finance", "Growth & Admin: Education", "Growth & Admin: Life Admin",
]

AI_SYSTEM_PROMPT = f"""You are a task creation assistant. Extract actionable tasks from the user's input and create them using the create_task tool.

Rules:
- Create up to {MAX_AI_TASKS} tasks maximum per request.
- Each task needs at minimum a clear, concise title.
- Infer priority, size, product_area, and work_location when possible from context.
- Valid product areas: {', '.join(PRODUCT_AREAS)}
- If the input is vague, create the most reasonable task(s) you can.
- After creating tasks, briefly confirm what was created.
- Do NOT ask clarifying questions — just create the tasks with reasonable defaults."""


def _execute_create_task(args):
    from datetime import datetime as dt
    deadline = None
    if args.get('deadline'):
        try:
            deadline = dt.strptime(args['deadline'], '%Y-%m-%d').date()
        except ValueError:
            pass
    task = Task(
        title=args['title'],
        description=args.get('description', ''),
        priority=args.get('priority', 'medium'),
        size=args.get('size', 'M'),
        product_area=args.get('product_area', ''),
        deadline=deadline,
        work_location=args.get('work_location', 'hybrid'),
    )
    db.session.add(task)
    db.session.commit()
    return task


@tasks_bp.route('/task/ai-create', methods=['POST'])
@login_required
def ai_create_tasks():
    """Endpoint for Chat, Voice, and Image task creation modes.

    Expects JSON: { "mode": "chat"|"voice"|"image", "text": "...", "image": "base64..." }
    Returns streaming SSE with created task info.
    """
    data = request.get_json()
    mode = data.get('mode', 'chat')
    text = data.get('text', '').strip()
    image_data = data.get('image')  # base64 string
    image_type = data.get('image_type', 'image/jpeg')  # mime type

    if not text and not image_data:
        return jsonify({'error': 'No input provided'}), 400

    # Build messages for Claude
    messages_content = []

    if mode == 'image' and image_data:
        messages_content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": image_type,
                "data": image_data,
            }
        })
        prompt_text = text if text else "Analyze this image/document and create appropriate tasks based on its content."
        messages_content.append({"type": "text", "text": prompt_text})
    else:
        if mode == 'voice':
            messages_content.append({"type": "text", "text": f"Transcribed voice input: {text}"})
        else:
            messages_content.append({"type": "text", "text": text})

    api_messages = [{"role": "user", "content": messages_content}]

    def generate():
        from flask import current_app
        client = anthropic.Anthropic(api_key=current_app.config['ANTHROPIC_API_KEY'])
        created_tasks = []
        full_response = ''
        current_msgs = api_messages[:]

        try:
            with client.messages.stream(
                model=AI_MODEL,
                max_tokens=2048,
                system=AI_SYSTEM_PROMPT,
                messages=current_msgs,
                tools=[CREATE_TASK_TOOL],
            ) as stream:
                for text_chunk in stream.text_stream:
                    full_response += text_chunk
                    yield f"data: {json.dumps({'text': text_chunk})}\n\n"
                final_msg = stream.get_final_message()

            # Handle tool calls in a loop
            while final_msg.stop_reason == 'tool_use' and len(created_tasks) < MAX_AI_TASKS:
                assistant_content = []
                tool_results = []
                for b in final_msg.content:
                    if b.type == 'text':
                        assistant_content.append({'type': 'text', 'text': b.text})
                    elif b.type == 'tool_use':
                        assistant_content.append({
                            'type': 'tool_use', 'id': b.id,
                            'name': b.name, 'input': b.input
                        })
                        if b.name == 'create_task' and len(created_tasks) < MAX_AI_TASKS:
                            task = _execute_create_task(b.input)
                            created_tasks.append({
                                'id': task.id,
                                'title': task.title,
                                'priority': task.priority,
                                'size': task.size,
                            })
                            yield f"data: {json.dumps({'task_created': created_tasks[-1]})}\n\n"
                            tool_results.append({
                                'type': 'tool_result',
                                'tool_use_id': b.id,
                                'content': f"Task created: '{task.title}' (id={task.id})"
                            })
                        elif b.name == 'create_task':
                            tool_results.append({
                                'type': 'tool_result',
                                'tool_use_id': b.id,
                                'content': f"Limit reached: maximum {MAX_AI_TASKS} tasks per request.",
                                'is_error': True,
                            })

                if not tool_results:
                    break

                current_msgs = current_msgs + [
                    {'role': 'assistant', 'content': assistant_content},
                    {'role': 'user', 'content': tool_results},
                ]

                follow_up = client.messages.create(
                    model=AI_MODEL,
                    max_tokens=1024,
                    system=AI_SYSTEM_PROMPT,
                    messages=current_msgs,
                    tools=[CREATE_TASK_TOOL],
                )

                follow_text = ''.join(b.text for b in follow_up.content if b.type == 'text')
                if follow_text:
                    full_response += follow_text
                    yield f"data: {json.dumps({'text': follow_text})}\n\n"

                final_msg = follow_up

            yield f"data: {json.dumps({'done': True, 'tasks_created': created_tasks})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            yield f"data: {json.dumps({'done': True, 'tasks_created': created_tasks})}\n\n"

    response = Response(stream_with_context(generate()), mimetype='text/event-stream')
    response.headers['X-Accel-Buffering'] = 'no'
    response.headers['Cache-Control'] = 'no-cache'
    return response
