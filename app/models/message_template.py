from app.extensions import db
from app.models.common import utcnow


class MessageTemplate(db.Model):
    """A reusable WhatsApp / Viber / email message. {name} and {category} are filled per lead."""

    __tablename__ = "message_templates"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    def __repr__(self):
        return f"<MessageTemplate {self.id} {self.name!r}>"
