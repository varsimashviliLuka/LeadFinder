"""Sending email through the user's own Gmail account (SMTP with an App Password).

The address and App Password are kept in a local JSON file inside the
instance folder (never in the database, never returned by the API).
"""

import json
import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from app.extensions import db
from app.models import SentEmail
from app.models.common import utcnow

ADDRESS_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class MailError(Exception):
    """A problem worth showing the user as-is."""


class GmailError(MailError):
    """Gmail couldn't be reached, refused the login, or refused the message."""


def _settings_path(config):
    return config["MAIL_SETTINGS_FILE"]


def load_settings(config):
    try:
        with open(_settings_path(config), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not data.get("address") or not data.get("app_password"):
        return None
    return data


def public_settings(config):
    settings = load_settings(config) or {}
    return {
        "configured": bool(settings),
        "address": settings.get("address"),
        "sender_name": settings.get("sender_name"),
    }


def _clean_address(value, what="Email address"):
    address = (value or "").strip()
    if not ADDRESS_RE.match(address):
        raise MailError(f"{what} doesn't look valid")
    return address


def _login(config, address, app_password):
    try:
        smtp = smtplib.SMTP_SSL(
            config["MAIL_SMTP_HOST"],
            config["MAIL_SMTP_PORT"],
            timeout=config["MAIL_SMTP_TIMEOUT"],
            context=ssl.create_default_context(),
        )
    except (OSError, smtplib.SMTPException) as exc:
        raise GmailError(f"Couldn't reach Gmail: {exc}") from None
    try:
        smtp.login(address, app_password)
    except smtplib.SMTPAuthenticationError:
        smtp.close()
        raise GmailError(
            "Gmail didn't accept that password. Use a 16-letter App Password, "
            "not your normal Gmail password (see the steps on this page)."
        ) from None
    except (OSError, smtplib.SMTPException) as exc:
        smtp.close()
        raise GmailError(f"Couldn't sign in to Gmail: {exc}") from None
    return smtp


def save_settings(config, payload):
    """Check the login works, then store it. Keeps the saved password if none is given."""
    current = load_settings(config) or {}
    address = _clean_address(payload.get("address") or current.get("address"), "Gmail address")
    app_password = re.sub(r"\s+", "", payload.get("app_password") or "")
    if not app_password:
        if current.get("address") != address:
            raise MailError("Enter the App Password for this Gmail address")
        app_password = current["app_password"]
    sender_name = (payload.get("sender_name") or "").strip()[:120] or None

    _login(config, address, app_password).quit()

    path = _settings_path(config)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # Readable by the owner only: it holds a password.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"address": address, "app_password": app_password, "sender_name": sender_name}, fh)
    return public_settings(config)


def delete_settings(config):
    try:
        os.remove(_settings_path(config))
    except FileNotFoundError:
        pass


def send_email(config, to, subject, body):
    """Send one plain-text email from the connected account. Raises MailError."""
    settings = load_settings(config)
    if not settings:
        raise MailError("Connect your Gmail in Settings first")
    to = _clean_address(to, "Recipient address")
    subject = (subject or "").strip()
    body = (body or "").strip()
    if not subject:
        raise MailError("Subject is required")
    if not body:
        raise MailError("Message is required")

    message = EmailMessage()
    message["From"] = formataddr((settings.get("sender_name") or "", settings["address"]))
    message["To"] = to
    message["Subject"] = subject
    message["Message-ID"] = make_msgid(domain=settings["address"].split("@")[1])
    message.set_content(body)

    smtp = _login(config, settings["address"], settings["app_password"])
    try:
        smtp.send_message(message)
    except smtplib.SMTPRecipientsRefused:
        raise GmailError(f"Gmail refused to send to {to}") from None
    except (OSError, smtplib.SMTPException) as exc:
        raise GmailError(f"Gmail couldn't send the email: {exc}") from None
    finally:
        try:
            smtp.quit()
        except (OSError, smtplib.SMTPException):
            pass
    return settings["address"]


def email_business(config, business, payload):
    """Send to a lead and record it. Caller commits."""
    to = payload.get("to") or business.email
    if not to:
        raise MailError("This lead has no email address")
    subject, body = payload.get("subject"), payload.get("body")
    from_address = send_email(config, to, subject, body)
    sent = SentEmail(
        business=business, to_address=to.strip(), from_address=from_address,
        subject=subject.strip(), body=body.strip(), created_at=utcnow(),
    )
    db.session.add(sent)
    business.last_contacted_at = sent.created_at
    return sent
