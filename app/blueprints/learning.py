from flask import Blueprint, jsonify, render_template
from app import db
from app.models import Task, LearningContext, now_eastern
from app.blueprints.main import login_required
import anthropic

learning_bp = Blueprint('learning', __name__)

MODEL = 'claude-sonnet-4-20250514'


def get_anthropic_client():
    from flask import current_app
    return anthropic.Anthropic(api_key=current_app.config['ANTHROPIC_API_KEY'])


def get_learning_context():
    """Return the current learning context string, or empty string if none."""
    ctx = LearningContext.query.first()
    if ctx and ctx.content:
        return ctx.content
    return ''


@learning_bp.route('/learning/synthesize', methods=['POST'])
@login_required
def synthesize():
    tasks = Task.query.filter(Task.status.in_(['done', 'archived'])).all()
    if not tasks:
        return jsonify({'error': 'No completed tasks to analyze yet.'}), 400

    # Build rich task descriptions
    lines = []
    for t in tasks:
        deadline_str = t.deadline.strftime('%Y-%m-%d') if t.deadline else 'no deadline'
        completed_str = t.completed_at.strftime('%Y-%m-%d') if t.completed_at else 'unknown'
        lines.append(
            f"- Title: {t.title}\n"
            f"  Area: {t.product_area or 'unspecified'} | Priority: {t.priority} | Size: {t.size} | "
            f"Location: {t.work_location or 'hybrid'} | Deadline: {deadline_str} | Completed: {completed_str}\n"
            f"  Description: {t.description or 'none'}\n"
            f"  Deliverable: {t.deliverable or 'none'}\n"
            f"  Reporting to: {t.reporting_to or 'none'} | Waiting on: {t.waiting_on or 'none'}"
        )

    task_list_str = '\n\n'.join(lines)

    existing_ctx = LearningContext.query.first()
    existing_insights = f"\n\nPrevious insights to build upon and refine:\n{existing_ctx.content}" if existing_ctx and existing_ctx.content else ''

    prompt = f"""You are analyzing my completed work tasks to build a rich, evolving understanding of my job, role, and working patterns.

Here are all my completed tasks ({len(tasks)} total):{existing_insights}

Completed tasks:
{task_list_str}

Synthesize this into a dense, practical profile written in second person ("You work on..."). Cover:
1. **Role & Responsibilities** — what kind of work you do, your apparent seniority and scope
2. **Key Projects & Product Areas** — recurring areas, what each seems to involve
3. **Stakeholders & Relationships** — who you report to, collaborate with, or unblock
4. **Work Patterns** — typical task sizes, urgency patterns, remote vs in-office preferences
5. **Strengths & Working Style** — inferred from the types of tasks completed
6. **Useful Context for Coaching** — things a task coach should know to give better advice

Be specific. Use details from the tasks. This context will be injected into every coaching conversation, so make it maximally useful. Keep it under 600 words."""

    client = get_anthropic_client()
    response = client.messages.create(
        model=MODEL,
        max_tokens=1200,
        messages=[{'role': 'user', 'content': prompt}]
    )

    synthesis = response.content[0].text

    if existing_ctx:
        existing_ctx.content = synthesis
        existing_ctx.task_count = len(tasks)
        existing_ctx.updated_at = now_eastern()
    else:
        ctx = LearningContext(content=synthesis, task_count=len(tasks))
        db.session.add(ctx)

    db.session.commit()
    return jsonify({'ok': True, 'content': synthesis, 'task_count': len(tasks)})


@learning_bp.route('/learning')
@login_required
def learning_view():
    ctx = LearningContext.query.first()
    done_count = Task.query.filter(Task.status.in_(['done', 'archived'])).count()
    return render_template('learning.html', ctx=ctx, done_count=done_count)
