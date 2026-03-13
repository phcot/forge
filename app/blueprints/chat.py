from datetime import date
from flask import Blueprint, render_template, request, jsonify, Response, stream_with_context
from app import db
from app.models import Task, DailyCheckIn, ChatMessage, now_eastern
from app.blueprints.main import login_required
import anthropic
import json

chat_bp = Blueprint('chat', __name__)

MODEL = 'claude-sonnet-4-20250514'


def get_anthropic_client():
    from flask import current_app
    return anthropic.Anthropic(api_key=current_app.config['ANTHROPIC_API_KEY'])


def get_learning_context():
    from app.models import LearningContext
    ctx = LearningContext.query.first()
    return ctx.content if ctx and ctx.content else ''


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
- Be warm but direct. Think coach, not assistant."""


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
    system_prompt = build_general_system_prompt()

    def generate():
        client = get_anthropic_client()
        full_response = ''
        with client.messages.stream(
            model=MODEL,
            max_tokens=1024,
            system=system_prompt,
            messages=messages
        ) as stream:
            for text in stream.text_stream:
                full_response += text
                yield f"data: {json.dumps({'text': text})}\n\n"

        assistant_msg = ChatMessage(task_id=None, role='assistant', content=full_response)
        db.session.add(assistant_msg)
        db.session.commit()
        yield f"data: {json.dumps({'done': True})}\n\n"

    return Response(stream_with_context(generate()), mimetype='text/event-stream')


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
    system_prompt = build_task_system_prompt(task)

    def generate():
        client = get_anthropic_client()
        full_response = ''
        with client.messages.stream(
            model=MODEL,
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
        yield f"data: {json.dumps({'done': True})}\n\n"

    return Response(stream_with_context(generate()), mimetype='text/event-stream')


@chat_bp.route('/chat/clear', methods=['POST'])
@login_required
def clear_general_chat():
    ChatMessage.query.filter_by(task_id=None).delete()
    db.session.commit()
    return jsonify({'ok': True})
