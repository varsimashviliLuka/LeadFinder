"""Message templates for WhatsApp, Viber and email outreach."""

from app.extensions import db
from app.models import MessageTemplate
from app.models.common import utcnow


def list_templates():
    return db.session.scalars(db.select(MessageTemplate).order_by(MessageTemplate.id)).all()


def save_template(template, payload):
    """Create or update from {name, body}. Raises ValueError on bad input. Caller commits."""
    name = payload.get("name", template.name if template else None)
    body = payload.get("body", template.body if template else None)
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name is required")
    if not isinstance(body, str) or not body.strip():
        raise ValueError("body is required")
    if len(name.strip()) > 120:
        raise ValueError("name must be at most 120 characters")
    if template is None:
        template = MessageTemplate()
        db.session.add(template)
    template.name = name.strip()
    template.body = body.strip()
    template.updated_at = utcnow()
    return template
