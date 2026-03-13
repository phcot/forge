from datetime import date
from flask import Blueprint, render_template, redirect, url_for, request, flash
from app import db
from app.models import DailyCheckIn
from app.blueprints.main import login_required

checkin_bp = Blueprint('checkin', __name__)


@checkin_bp.route('/checkin', methods=['GET', 'POST'])
@login_required
def checkin():
    today = date.today()
    existing = DailyCheckIn.query.filter_by(date=today).first()

    if request.method == 'POST':
        if existing:
            record = existing
        else:
            record = DailyCheckIn(date=today)
            db.session.add(record)

        record.energy_level = request.form.get('energy_level', 'medium')
        record.time_available = request.form.get('time_available', '')
        record.meetings = request.form.get('meetings', '')
        record.blockers = request.form.get('blockers', '')
        record.notes = request.form.get('notes', '')

        db.session.commit()
        return redirect(url_for('main.dashboard'))

    return render_template('checkin.html', checkin=existing, today=today)
