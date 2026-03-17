from datetime import date
from flask import Blueprint, render_template, redirect, url_for, request, flash
from app import db
from app.models import Task, now_eastern
from app.blueprints.main import login_required

tasks_bp = Blueprint('tasks', __name__)


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
