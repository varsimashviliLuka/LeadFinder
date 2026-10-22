from app.extensions import db
from app.models.common import utcnow


class SentEmail(db.Model):
    """An email sent to a lead from the app through the connected Gmail account."""

    __tablename__ = "sent_emails"

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(
        db.Integer, db.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    to_address = db.Column(db.String(255), nullable=False)
    from_address = db.Column(db.String(255), nullable=False)
    subject = db.Column(db.String(255), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    business = db.relationship("Business", back_populates="emails")
