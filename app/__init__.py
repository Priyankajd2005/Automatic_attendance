"""
app/__init__.py
---------------
Flask application factory.  All extensions are initialised here and
all blueprints are registered so that every part of the app is wired
up in one place, following the Application-Factory pattern.
"""

import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from flask_migrate import Migrate
from flask_cors import CORS

from config import config_map

# ---------------------------------------------------------------------------
# Extension singletons (imported by models and other modules)
# ---------------------------------------------------------------------------
db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()
migrate = Migrate()


def create_app(config_name: str = "default") -> Flask:
    """
    Create and configure a Flask application instance.

    Parameters
    ----------
    config_name : str
        Key into ``config_map`` — one of 'development', 'production',
        'testing', or 'default'.

    Returns
    -------
    Flask
        A fully configured Flask application.
    """
    app = Flask(__name__, instance_relative_config=False)

    # ------------------------------------------------------------------
    # Load configuration
    # ------------------------------------------------------------------
    cfg = config_map.get(config_name, config_map["default"])
    app.config.from_object(cfg)

    # ------------------------------------------------------------------
    # Initialise extensions
    # ------------------------------------------------------------------
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    migrate.init_app(app, db)
    CORS(app)

    # LoginManager settings
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please log in to access this page."
    login_manager.login_message_category = "warning"

    # ------------------------------------------------------------------
    # User loader for Flask-Login
    # ------------------------------------------------------------------
    from app.models import Teacher  # noqa: F401 – imported for side effects

    @login_manager.user_loader
    def load_user(user_id: str):
        return Teacher.query.get(int(user_id))

    # ------------------------------------------------------------------
    # Register blueprints
    # ------------------------------------------------------------------
    from app.routes.auth import auth_bp
    from app.routes.student import student_bp
    from app.routes.attendance import attendance_bp
    from app.routes.dashboard import dashboard_bp
    from app.routes.admin import admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(student_bp)
    app.register_blueprint(attendance_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(admin_bp)

    # ------------------------------------------------------------------
    # Ensure required directories exist at startup
    # ------------------------------------------------------------------
    with app.app_context():
        _ensure_directories(app)
        db.create_all()

    return app


def _ensure_directories(app: Flask) -> None:
    """Create upload and face-data directories if they do not exist."""
    for folder_key in ("UPLOAD_FOLDER", "FACE_DATA_FOLDER"):
        path = app.config.get(folder_key)
        if path:
            os.makedirs(path, exist_ok=True)
