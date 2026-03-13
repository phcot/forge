from datetime import date, datetime
from functools import wraps
from flask import Blueprint, render_template, redirect, url_for, session, request, flash, jsonify
from app import db
from app.models import Task, DailyCheckIn, now_eastern

main_bp = Blueprint('main', __name__)


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('authenticated'):
            return redirect(url_for('main.login'))
        return f(*args, **kwargs)
    return decorated


@main_bp.route('/login', methods=['GET', 'POST'])
def login():
    from flask import current_app
    if request.method == 'POST':
        pin = request.form.get('pin', '')
        if pin == current_app.config['APP_PIN']:
            session['authenticated'] = True
            session.permanent = True
            return redirect(url_for('main.dashboard'))
        flash('Incorrect PIN. Try again.')
    return render_template('login.html')


@main_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('main.login'))


@main_bp.route('/')
@login_required
def dashboard():
    today = date.today()
    checkin = DailyCheckIn.query.filter_by(date=today).first()

    active_statuses = ['in_progress', 'not_started', 'blocked']
    active_tasks = (
        Task.query
        .filter(Task.status.in_(active_statuses))
        .order_by(
            db.case(
                (Task.status == 'in_progress', 0),
                (Task.status == 'not_started', 1),
                (Task.status == 'blocked', 2),
                else_=3
            ),
            Task.sort_order,
            Task.created_at
        )
        .all()
    )

    # Tasks completed today
    today_start = datetime.combine(today, datetime.min.time())
    completed_today = (
        Task.query
        .filter(Task.status == 'done', Task.completed_at >= today_start)
        .order_by(Task.completed_at.desc())
        .all()
    )

    return render_template(
        'dashboard.html',
        checkin=checkin,
        active_tasks=active_tasks,
        completed_today=completed_today,
        today=today
    )


@main_bp.route('/task/<int:task_id>/quick-status', methods=['POST'])
@login_required
def quick_status(task_id):
    task = Task.query.get_or_404(task_id)
    new_status = request.form.get('status')
    valid = ['not_started', 'in_progress', 'blocked', 'done', 'archived']
    if new_status in valid:
        task.status = new_status
        if new_status == 'done' and not task.completed_at:
            task.completed_at = now_eastern()
        elif new_status != 'done':
            task.completed_at = None
        db.session.commit()
    return redirect(url_for('main.dashboard'))


@main_bp.route('/archive')
@login_required
def archive():
    q = request.args.get('q', '').strip()
    query = Task.query.filter(Task.status.in_(['done', 'archived']))
    if q:
        query = query.filter(
            db.or_(
                Task.title.ilike(f'%{q}%'),
                Task.product_area.ilike(f'%{q}%'),
                Task.description.ilike(f'%{q}%')
            )
        )
    tasks = query.order_by(Task.completed_at.desc().nullslast(), Task.updated_at.desc()).all()
    return render_template('archive.html', tasks=tasks, q=q)
