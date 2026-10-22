import logging
import os
from logging.handlers import RotatingFileHandler

from dotenv import load_dotenv

load_dotenv()

from flask import Flask  # noqa: E402
from sqlalchemy import event  # noqa: E402

from app.config import config_by_name  # noqa: E402  reads env vars at import
from app.extensions import db, migrate  # noqa: E402


def create_app(config_name=None):
    config_name = config_name or os.getenv("APP_ENV", "development")

    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_by_name[config_name])

    os.makedirs(app.instance_path, exist_ok=True)
    if not app.config["SQLALCHEMY_DATABASE_URI"]:
        db_path = os.path.join(app.instance_path, "business_scraper.db")
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
    if not app.config["SCRAPER_PROFILE_DIR"]:
        app.config["SCRAPER_PROFILE_DIR"] = os.path.join(app.instance_path, "browser_profile")
    app.config.setdefault("SCRAPER_STATE_FILE", os.path.join(app.instance_path, "scraper_state.json"))
    if not app.config["MAIL_SETTINGS_FILE"]:
        app.config["MAIL_SETTINGS_FILE"] = os.path.join(app.instance_path, "mail_settings.json")

    _configure_logging(app)

    db.init_app(app)
    migrate.init_app(app, db, render_as_batch=True)
    _configure_sqlite(app)

    from app import models  # noqa: F401  registers models with SQLAlchemy
    from app.api import api_bp
    from app.web import web_bp
    from app.workers import job_runner

    job_runner.init_app(app)
    app.register_blueprint(api_bp)
    app.register_blueprint(web_bp)

    return app


LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


def _configure_logging(app):
    logging.basicConfig(level=app.config["LOG_LEVEL"], format=LOG_FORMAT)
    if app.testing:
        return

    root = logging.getLogger()
    log_path = os.path.join(app.instance_path, "logs", "app.log")
    if any(getattr(h, "baseFilename", None) == log_path for h in root.handlers):
        return
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    handler = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root.addHandler(handler)


def _configure_sqlite(app):
    uri = app.config["SQLALCHEMY_DATABASE_URI"]
    if not uri.startswith("sqlite") or ":memory:" in uri:
        return

    with app.app_context():
        # WAL lets the dashboard read while a search job is writing.
        @event.listens_for(db.engine, "connect")
        def set_sqlite_pragmas(dbapi_connection, _record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()
