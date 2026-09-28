"""
config.py
---------
Flask configuration classes for the Automatic Attendance Management System.
Supports Development, Production, and Testing environments via environment variables.
"""

import os
from dotenv import load_dotenv

# Load .env file variables into the environment
load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    """Base configuration shared by all environments."""

    # ------------------------------------------------------------------ #
    # Security
    # ------------------------------------------------------------------ #
    SECRET_KEY = os.environ.get("SECRET_KEY") or "dev-fallback-secret-key-change-me"

    # ------------------------------------------------------------------ #
    # Database
    # ------------------------------------------------------------------ #
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or (
        "sqlite:///" + os.path.join(BASE_DIR, "instance", "attendance.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ------------------------------------------------------------------ #
    # File uploads
    # ------------------------------------------------------------------ #
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "app", "static", "uploads")
    FACE_DATA_FOLDER = os.path.join(BASE_DIR, "face_data")
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg"}

    # ------------------------------------------------------------------ #
    # Google Sheets / Drive integration
    # ------------------------------------------------------------------ #
    GOOGLE_CREDENTIALS_FILE = os.environ.get("GOOGLE_CREDENTIALS_FILE") or "google_credentials.json"
    GOOGLE_SPREADSHEET_ID = os.environ.get("GOOGLE_SPREADSHEET_ID") or ""
    GOOGLE_SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]

    # ------------------------------------------------------------------ #
    # Face recognition
    # ------------------------------------------------------------------ #
    FACE_RECOGNITION_TOLERANCE = float(os.environ.get("FACE_RECOGNITION_TOLERANCE") or 0.5)

    # ------------------------------------------------------------------ #
    # WTForms / CSRF
    # ------------------------------------------------------------------ #
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600  # seconds


class DevelopmentConfig(Config):
    """Development-specific configuration with debug enabled."""

    DEBUG = True
    SQLALCHEMY_ECHO = False  # Set True to log every SQL statement to stdout


class ProductionConfig(Config):
    """Production-specific configuration with strict security settings."""

    DEBUG = False
    TESTING = False

    # In production, SECRET_KEY must be set via environment variable.
    SECRET_KEY = os.environ.get("SECRET_KEY")

    # Use a production-grade database (PostgreSQL, MySQL, etc.) via env var.
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or (
        "sqlite:///" + os.path.join(BASE_DIR, "instance", "attendance.db")
    )

    # Enforce HTTPS cookie security in production
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = True


class TestingConfig(Config):
    """Testing configuration using an in-memory SQLite database."""

    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    SECRET_KEY = "testing-secret-key"


# Mapping string names to config classes — used by create_app()
config_map = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
    "default": DevelopmentConfig,
}
