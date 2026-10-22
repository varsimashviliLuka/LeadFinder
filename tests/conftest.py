import pytest

from app import create_app
from app.extensions import db


@pytest.fixture
def app(tmp_path):
    app = create_app("testing")
    app.config["SCRAPER_STATE_FILE"] = str(tmp_path / "scraper_state.json")
    app.config["MAIL_SETTINGS_FILE"] = str(tmp_path / "mail_settings.json")
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()
