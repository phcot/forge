from datetime import datetime
import pytz
from app import db

EASTERN = pytz.timezone('America/Toronto')


def now_eastern():
    return datetime.now(pytz.utc).astimezone(EASTERN).replace(tzinfo=None)


class Task(db.Model):
    __tablename__ = 'tasks'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, default='')
    status = db.Column(db.String(20), default='not_started')  # not_started, in_progress, blocked, done, archived
    priority = db.Column(db.String(20), default='medium')     # low, medium, high, critical
    size = db.Column(db.String(5), default='M')               # S, M, L
    deadline = db.Column(db.Date, nullable=True)
    deliverable = db.Column(db.Text, default='')
    reporting_to = db.Column(db.String(255), default='')
    waiting_on = db.Column(db.Text, default='')
    product_area = db.Column(db.String(255), default='')
    work_location = db.Column(db.String(20), default='hybrid')  # remote, office, hybrid
    created_at = db.Column(db.DateTime, default=now_eastern)
    updated_at = db.Column(db.DateTime, default=now_eastern, onupdate=now_eastern)
    completed_at = db.Column(db.DateTime, nullable=True)
    sort_order = db.Column(db.Integer, default=0)
    is_backlog = db.Column(db.Boolean, default=False)

    messages = db.relationship('ChatMessage', backref='task', lazy=True,
                               foreign_keys='ChatMessage.task_id',
                               cascade='all, delete-orphan')

    def to_context_str(self):
        deadline_str = self.deadline.strftime('%Y-%m-%d') if self.deadline else 'None'
        return (
            f"- [{self.status.upper()}] {self.title} | "
            f"Priority: {self.priority} | Size: {self.size} | "
            f"Deadline: {deadline_str} | Area: {self.product_area or 'N/A'} | "
            f"Location: {self.work_location or 'hybrid'} | "
            f"Waiting on: {self.waiting_on or 'nothing'}"
        )


class DailyCheckIn(db.Model):
    __tablename__ = 'daily_checkins'

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, unique=True)
    energy_level = db.Column(db.String(10), default='medium')  # low, medium, high
    work_location = db.Column(db.String(10), default='remote')  # remote, office
    time_available = db.Column(db.String(255), default='')
    meetings = db.Column(db.Text, default='')
    blockers = db.Column(db.Text, default='')
    notes = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime, default=now_eastern)

    def to_context_str(self):
        return (
            f"Energy: {self.energy_level} | "
            f"Working from: {self.work_location} | "
            f"Time available: {self.time_available or 'unknown'} | "
            f"Meetings: {self.meetings or 'none'} | "
            f"Blockers: {self.blockers or 'none'} | "
            f"Notes: {self.notes or 'none'}"
        )


class ChatMessage(db.Model):
    __tablename__ = 'chat_messages'

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('tasks.id'), nullable=True)
    role = db.Column(db.String(10), nullable=False)   # user, assistant
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=now_eastern)


class LearningContext(db.Model):
    __tablename__ = 'learning_context'

    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, default='')          # synthesized insights
    task_count = db.Column(db.Integer, default=0)     # how many tasks were analyzed
    updated_at = db.Column(db.DateTime, default=now_eastern, onupdate=now_eastern)
