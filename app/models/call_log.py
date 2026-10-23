from app.extensions import db
from app.models.common import utcnow


class ContactKind:
    CALL = "call"
    VISIT = "visit"

    ALL = (CALL, VISIT)


class CallLog(db.Model):
    """A phone call or an in-person visit and how it went."""

    __tablename__ = "call_logs"

    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(16), nullable=False, default=ContactKind.CALL)
    business_id = db.Column(
        db.Integer, db.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    outcome = db.Column(db.String(32), nullable=False)
    note = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    business = db.relationship("Business", back_populates="calls")
