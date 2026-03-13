import markdown as md
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from markupsafe import Markup

db = SQLAlchemy()
migrate = Migrate()


def create_app():
    app = Flask(__name__)
    app.config.from_object('config.Config')

    db.init_app(app)
    migrate.init_app(app, db)

    @app.template_filter('markdown')
    def markdown_filter(text):
        if not text:
            return Markup('')
        return Markup(md.markdown(text or '', extensions=['fenced_code', 'tables', 'nl2br']))

    from app.blueprints.main import main_bp
    from app.blueprints.tasks import tasks_bp
    from app.blueprints.chat import chat_bp
    from app.blueprints.checkin import checkin_bp
    from app.blueprints.learning import learning_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(tasks_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(checkin_bp)
    app.register_blueprint(learning_bp)

    return app
