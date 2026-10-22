from app.extensions import db
from app.models.common import utcnow


class CallLog(db.Model):
    __tablename__ = "call_logs"

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(
        db.Integer, db.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    outcome = db.Column(db.String(32), nullable=False)
    note = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    business = db.relationship("Business", back_populates="calls")
