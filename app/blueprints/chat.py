from datetime import date
from flask import Blueprint, render_template, request, jsonify, Response, stream_with_context
from app import db
from app.models import Task, DailyCheckIn, ChatMessage, now_eastern
from app.blueprints.main import login_required
import anthropic
import json

chat_bp = Blueprint('chat', __name__)

GENERAL_CHAT_MODEL = 'claude-sonnet-4-6'
TASK_CHAT_MODEL = 'claude-opus-4-6'

# Maximum number of recent messages to send to the API per call.
# This prevents unbounded context growth and keeps token usage in check.
# Each "exchange" is roughly 2 messages (user + assistant), so 20 messages ≈ 10 exchanges.
MAX_CONTEXT_MESSAGES = 20


def get_anthropic_client():
    from flask import current_app
    return anthropic.Anthropic(api_key=current_app.config['ANTHROPIC_API_KEY'])


def get_learning_context():
    from app.models import LearningContext
    ctx = LearningContext.query.first()
    return ctx.content if ctx and ctx.content else ''


def trim_messages(messages, max_messages=MAX_CONTEXT_MESSAGES):
    """Return only the most recent messages to keep context bounded.

    If the history exceeds max_messages, prepend a short summary note so
    Claude knows older conversation existed but isn't distracted by it.
    Returns (trimmed_messages, was_trimmed).
    """
    if len(messages) <= max_messages:
        return messages, False

    trimmed = messages[-max_messages:]

    # Ensure the trimmed list starts with a 'user' message (API requirement)
    while trimmed and trimmed[0]['role'] != 'user':
        trimmed = trimmed[1:]

    summary_note = {
        'role': 'user',
        'content': (
            '[System note: Earlier conversation history has been trimmed to save context. '
            'Focus only on the current request. Do not reference tasks or topics from '
            'prior conversations unless the user explicitly brings them up again.]'
        )
    }
    return [summary_note] + trimmed, True


CREATE_TASK_TOOL = {
    "name": "create_task",
    "description": "Create a new task in the user's task list.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Short, clear task title."
            },
            "description": {
                "type": "string",
                "description": "Optional longer description of the task."
            },
            "priority": {
                "type": "string",
                "enum": ["low", "medium", "high", "critical"],
                "description": "Task priority. Default: medium."
            },
            "size": {
                "type": "string",
                "enum": ["S", "M", "L"],
                "description": "Effort size estimate. Default: M."
            },
            "product_area": {
                "type": "string",
                "description": "Category/area. E.g. 'Career: PRD-LIMCA', 'Home: Maintenance', 'Family'."
            },
            "deadline": {
                "type": "string",
                "description": "Optional deadline in YYYY-MM-DD format."
            },
            "work_location": {
                "type": "string",
                "enum": ["remote", "office", "hybrid"],
                "description": "Where the task can be done. Default: hybrid."
            }
        },
        "required": ["title"]
    }
}


def execute_create_task(args):
    from datetime import datetime as dt
    from app.models import Task
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
    return f"Task created: '{task.title}' (id={task.id})"


def build_general_system_prompt():
    today = date.today()
    checkin = DailyCheckIn.query.filter_by(date=today).first()
    checkin_str = checkin.to_context_str() if checkin else "No check-in submitted yet today."

    location_note = ''
    if checkin:
        location_note = f"\nToday I am working from: {checkin.work_location}."

    active_tasks = Task.query.filter(Task.status.in_(['in_progress', 'not_started', 'blocked'])).all()
    if active_tasks:
        tasks_str = '\n'.join(t.to_context_str() for t in active_tasks)
    else:
        tasks_str = "No active tasks."

    learning = get_learning_context()
    learning_section = f"\n\nWhat you know about me from past work:\n{learning}" if learning else ''

    return f"""You are my personal task coach and accountability partner. You have full context on my current workload and state of mind.{learning_section}

Here is my current check-in for today:
{checkin_str}{location_note}

Here is my current task list:
{tasks_str}

Rules:
- Give me one task at a time when I ask what to do next
- Match task difficulty to my energy level and available time
- When I'm working remotely, prioritize tasks that don't require physical presence; when in-office, highlight tasks that benefit from in-person collaboration
- If a task requires office presence and I'm remote today (or vice versa), flag it
- Prioritize: deadlines > blocking others > quick wins when low energy > deep work when high energy
- Keep responses short and direct unless I ask for detail
- When I say "done" with something, celebrate briefly and give me the next thing
- When I say "stuck", help me break it down or suggest timeboxing
- When I say "how am I doing", give me a completed vs remaining tally
- If I'm avoiding something, gently call it out
- Be warm but direct. Think coach, not assistant.
- You can create tasks directly. When the user asks you to add something to their task list, use the create_task tool to do it immediately, then confirm it was added."""


def build_task_system_prompt(task):
    deadline_str = task.deadline.strftime('%Y-%m-%d') if task.deadline else 'None'

    learning = get_learning_context()
    learning_section = f"\n\nContext about who I am and how I work:\n{learning}" if learning else ''

    return f"""You are helping me work through a specific task. Here is the full context:{learning_section}

Title: {task.title}
Description: {task.description or 'None'}
Status: {task.status}
Priority: {task.priority}
Size: {task.size}
Deadline: {deadline_str}
Deliverable: {task.deliverable or 'None'}
Reporting to: {task.reporting_to or 'None'}
Waiting on: {task.waiting_on or 'None'}
Product area: {task.product_area or 'None'}
Work location requirement: {task.work_location or 'hybrid'}

Help me think through and execute this task. You can:
- Help me break it into subtasks
- Draft documents, emails, or plans related to it
- Think through blockers or decisions
- Suggest next steps
- Flag if location (remote/office) affects how or when this can be done

Keep responses practical and focused on getting this task done."""


@chat_bp.route('/chat')
@login_required
def general_chat():
    messages = (
        ChatMessage.query
        .filter_by(task_id=None)
        .order_by(ChatMessage.created_at)
        .all()
    )
    return render_template('chat.html', messages=messages, task=None)


@chat_bp.route('/chat/send', methods=['POST'])
@login_required
def send_general_message():
    content = request.json.get('message', '').strip()
    if not content:
        return jsonify({'error': 'Empty message'}), 400

    user_msg = ChatMessage(task_id=None, role='user', content=content)
    db.session.add(user_msg)
    db.session.commit()

    history = (
        ChatMessage.query
        .filter_by(task_id=None)
        .order_by(ChatMessage.created_at)
        .all()
    )
    messages = [{'role': m.role, 'content': m.content} for m in history]
    messages, _ = trim_messages(messages)
    system_prompt = build_general_system_prompt()

    def generate():
        client = get_anthropic_client()
        full_response = ''
        created_tasks = []
        current_messages = messages[:]
        try:
            # Initial streaming call
            with client.messages.stream(
                model=GENERAL_CHAT_MODEL,
                max_tokens=4096,
                system=system_prompt,
                messages=current_messages,
                tools=[CREATE_TASK_TOOL]
            ) as stream:
                for text in stream.text_stream:
                    full_response += text
                    yield f"data: {json.dumps({'text': text})}\n\n"
                final_msg = stream.get_final_message()

            if final_msg.stop_reason == 'max_tokens':
                truncation_note = '\n\n_[Response truncated — please try a shorter request]_'
                full_response += truncation_note
                yield f"data: {json.dumps({'text': truncation_note})}\n\n"

            # Handle tool calls; use non-streaming for follow-ups to avoid nested stream issues
            while final_msg.stop_reason == 'tool_use':
                assistant_content = []
                tool_results = []
                for b in final_msg.content:
                    if b.type == 'text':
                        assistant_content.append({'type': 'text', 'text': b.text})
                    elif b.type == 'tool_use':
                        assistant_content.append({'type': 'tool_use', 'id': b.id, 'name': b.name, 'input': b.input})
                        if b.name == 'create_task':
                            result = execute_create_task(b.input)
                            created_tasks.append(b.input.get('title', ''))
                            tool_results.append({'type': 'tool_result', 'tool_use_id': b.id, 'content': result})

                if not tool_results:
                    break

                current_messages = current_messages + [
                    {'role': 'assistant', 'content': assistant_content},
                    {'role': 'user', 'content': tool_results}
                ]

                # Non-streaming follow-up avoids nested generator/stream complexity
                follow_up = client.messages.create(
                    model=GENERAL_CHAT_MODEL,
                    max_tokens=1024,
                    system=system_prompt,
                    messages=current_messages,
                    tools=[CREATE_TASK_TOOL]
                )

                follow_up_text = ''.join(b.text for b in follow_up.content if b.type == 'text')
                if follow_up_text:
                    full_response += follow_up_text
                    yield f"data: {json.dumps({'text': follow_up_text})}\n\n"

                final_msg = follow_up

            assistant_msg = ChatMessage(task_id=None, role='assistant', content=full_response)
            db.session.add(assistant_msg)
            db.session.commit()
            yield f"data: {json.dumps({'done': True, 'tasks_created': created_tasks})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'text': f'\\n\\n[Error: {str(e)}]'})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"

    response = Response(stream_with_context(generate()), mimetype='text/event-stream')
    response.headers['X-Accel-Buffering'] = 'no'
    response.headers['Cache-Control'] = 'no-cache'
    return response


@chat_bp.route('/chat/task/<int:task_id>/send', methods=['POST'])
@login_required
def send_task_message(task_id):
    task = Task.query.get_or_404(task_id)
    content = request.json.get('message', '').strip()
    if not content:
        return jsonify({'error': 'Empty message'}), 400

    user_msg = ChatMessage(task_id=task_id, role='user', content=content)
    db.session.add(user_msg)
    db.session.commit()

    history = (
        ChatMessage.query
        .filter_by(task_id=task_id)
        .order_by(ChatMessage.created_at)
        .all()
    )
    messages = [{'role': m.role, 'content': m.content} for m in history]
    messages, _ = trim_messages(messages)
    system_prompt = build_task_system_prompt(task)

    def generate():
        client = get_anthropic_client()
        full_response = ''
        try:
            with client.messages.stream(
                model=TASK_CHAT_MODEL,
                max_tokens=1024,
                system=system_prompt,
                messages=messages
            ) as stream:
                for text in stream.text_stream:
                    full_response += text
                    yield f"data: {json.dumps({'text': text})}\n\n"

            assistant_msg = ChatMessage(task_id=task_id, role='assistant', content=full_response)
            db.session.add(assistant_msg)
            db.session.commit()
        except Exception as e:
            yield f"data: {json.dumps({'text': f'[Error: {str(e)}]'})}\n\n"
        yield f"data: {json.dumps({'done': True})}\n\n"

    response = Response(stream_with_context(generate()), mimetype='text/event-stream')
    response.headers['X-Accel-Buffering'] = 'no'
    response.headers['Cache-Control'] = 'no-cache'
    return response


@chat_bp.route('/chat/clear', methods=['POST'])
@login_required
def clear_general_chat():
    ChatMessage.query.filter_by(task_id=None).delete()
    db.session.commit()
    return jsonify({'ok': True})
