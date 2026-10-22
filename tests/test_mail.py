import os
import smtplib
import stat

import pytest

from app.extensions import db
from app.models import Business, SentEmail
from app.services import mailer

GOOD_PASSWORD = "abcdefghijklmnop"


class FakeSMTP:
    """Stands in for smtplib.SMTP_SSL; records what would have been sent."""

    sent = []
    refuse = False

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port = host, port

    def login(self, user, password):
        if password != GOOD_PASSWORD:
            raise smtplib.SMTPAuthenticationError(535, b"Username and Password not accepted")

    def send_message(self, message):
        if FakeSMTP.refuse:
            raise smtplib.SMTPRecipientsRefused({message["To"]: (550, b"no such user")})
        FakeSMTP.sent.append(message)

    def quit(self):
        pass

    close = quit


@pytest.fixture(autouse=True)
def fake_smtp(monkeypatch):
    FakeSMTP.sent = []
    FakeSMTP.refuse = False
    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", FakeSMTP)
    return FakeSMTP


def connect(client, **overrides):
    body = {"address": "me@gmail.com", "app_password": "abcd efgh ijkl mnop", "sender_name": "Luka", **overrides}
    return client.put("/api/mail/settings", json=body)


@pytest.fixture
def lead(app):
    b = Business(place_id="m1", name="Salon Nino", email="nino@salon.ge")
    db.session.add(b)
    db.session.commit()
    return b


def test_connect_checks_login_and_hides_password(client, app):
    assert client.get("/api/mail/settings").get_json() == {"configured": False, "address": None, "sender_name": None}

    bad = connect(client, app_password="my normal password")
    assert bad.status_code == 400
    assert "App Password" in bad.get_json()["message"]
    assert not os.path.exists(app.config["MAIL_SETTINGS_FILE"])

    data = connect(client).get_json()
    assert data == {"configured": True, "address": "me@gmail.com", "sender_name": "Luka"}
    assert "app_password" not in client.get("/api/mail/settings").get_json()
    mode = stat.S_IMODE(os.stat(app.config["MAIL_SETTINGS_FILE"]).st_mode)
    assert mode == 0o600


def test_saving_without_password_keeps_the_saved_one(client):
    connect(client)
    assert connect(client, app_password="", sender_name="New name").get_json()["sender_name"] == "New name"
    assert connect(client, address="other@gmail.com", app_password="").status_code == 400


def test_disconnect(client):
    connect(client)
    assert client.delete("/api/mail/settings").status_code == 204
    assert client.get("/api/mail/settings").get_json()["configured"] is False


def test_send_test_email(client, fake_smtp):
    assert client.post("/api/mail/test").status_code == 400
    connect(client)
    assert client.post("/api/mail/test").get_json() == {"sent_to": "me@gmail.com"}
    assert fake_smtp.sent[0]["To"] == "me@gmail.com"


def test_email_lead_sends_and_records(client, lead, fake_smtp):
    assert client.post(f"/api/businesses/{lead.id}/emails", json={"subject": "Hi", "body": "Hello"}).status_code == 400

    connect(client)
    response = client.post(f"/api/businesses/{lead.id}/emails", json={"subject": " Photos ", "body": "Hello Nino"})
    assert response.status_code == 201
    data = response.get_json()
    assert data["emails"][0]["subject"] == "Photos"
    assert data["emails"][0]["to_address"] == "nino@salon.ge"
    assert data["last_contacted_at"]

    message = fake_smtp.sent[0]
    assert message["From"] == "Luka <me@gmail.com>"
    assert message["To"] == "nino@salon.ge"
    assert message.get_content().strip() == "Hello Nino"


def test_email_validation_and_gmail_refusal(client, lead, fake_smtp):
    connect(client)
    url = f"/api/businesses/{lead.id}/emails"
    assert client.post(url, json={"subject": "", "body": "x"}).status_code == 400
    assert client.post(url, json={"subject": "x", "body": " "}).status_code == 400
    assert client.post(url, json={"to": "not-an-email", "subject": "x", "body": "y"}).status_code == 400

    fake_smtp.refuse = True
    response = client.post(url, json={"subject": "x", "body": "y"})
    assert response.status_code == 502
    assert "refused" in response.get_json()["message"]
    assert db.session.query(SentEmail).count() == 0


def test_settings_page_renders(client):
    page = client.get("/settings").get_data(as_text=True)
    assert "App Password" in page and "apppasswords" in page
