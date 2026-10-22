from app.extensions import db
from app.models.common import utcnow


class LeadStatus:
    NEW = "new"
    NO_ANSWER = "no_answer"
    CALL_BACK = "call_back"
    INTERESTED = "interested"
    NOT_INTERESTED = "not_interested"
    CLIENT = "client"

    ALL = (NEW, NO_ANSWER, CALL_BACK, INTERESTED, NOT_INTERESTED, CLIENT)
    CALL_OUTCOMES = (NO_ANSWER, CALL_BACK, INTERESTED, NOT_INTERESTED, CLIENT)


search_job_results = db.Table(
    "search_job_results",
    db.Column("search_job_id", db.Integer, db.ForeignKey("search_jobs.id", ondelete="CASCADE"), primary_key=True),
    db.Column("business_id", db.Integer, db.ForeignKey("businesses.id", ondelete="CASCADE"), primary_key=True),
)


class Business(db.Model):
    __tablename__ = "businesses"

    id = db.Column(db.Integer, primary_key=True)
    place_id = db.Column(db.String(255), unique=True, nullable=False, index=True)

    name = db.Column(db.String(255), nullable=False)
    category = db.Column(db.String(255), index=True)
    address = db.Column(db.String(500))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    phone = db.Column(db.String(64))
    website = db.Column(db.String(500))
    email = db.Column(db.String(255))
    rating = db.Column(db.Float)
    review_count = db.Column(db.Integer)
    opening_hours = db.Column(db.JSON)
    maps_url = db.Column(db.String(1000))
    # False when Google shows "Claim this business": nobody manages the listing.
    claimed = db.Column(db.Boolean)
    price_level = db.Column(db.String(32))
    # From the newest reviews on Google Maps (only when a search reads reviews).
    latest_review_date = db.Column(db.Date)
    recent_reviews_checked = db.Column(db.Integer)
    recent_owner_replies = db.Column(db.Integer)

    whatsapp = db.Column(db.String(64))
    # Set once the website & social media lookup ran, so "none found" differs from "not checked".
    social_checked_at = db.Column(db.DateTime(timezone=True))
    # https, mobile_friendly, load_seconds, copyright_year, builder, error (see services.socials).
    website_check = db.Column(db.JSON(none_as_null=True))
    website_issue_count = db.Column(db.Integer, index=True)

    lead_status = db.Column(db.String(32), nullable=False, default=LeadStatus.NEW, index=True)
    notes = db.Column(db.Text)
    follow_up_date = db.Column(db.Date, index=True)
    last_contacted_at = db.Column(db.DateTime(timezone=True))

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    calls = db.relationship(
        "CallLog",
        back_populates="business",
        cascade="all, delete-orphan",
        order_by="desc(CallLog.created_at)",
    )
    emails = db.relationship(
        "SentEmail",
        back_populates="business",
        cascade="all, delete-orphan",
        order_by="desc(SentEmail.created_at)",
    )
    social_profiles = db.relationship(
        "SocialProfile",
        back_populates="business",
        cascade="all, delete-orphan",
        order_by="SocialProfile.platform, SocialProfile.id",
    )
    search_jobs = db.relationship("SearchJob", secondary=search_job_results, back_populates="businesses")

    def __repr__(self):
        return f"<Business {self.id} {self.name!r}>"
