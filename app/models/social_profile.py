from app.extensions import db
from app.models.common import utcnow


class SocialPlatform:
    FACEBOOK = "facebook"
    INSTAGRAM = "instagram"
    TIKTOK = "tiktok"

    ALL = (FACEBOOK, INSTAGRAM, TIKTOK)


class SocialSource:
    GOOGLE_MAPS = "google_maps"  # the listing's "website" was the profile itself
    WEBSITE = "website"  # linked from the business's own website
    MANUAL = "manual"  # added by you

    ALL = (GOOGLE_MAPS, WEBSITE, MANUAL)


class SocialProfile(db.Model):
    __tablename__ = "social_profiles"
    __table_args__ = (db.UniqueConstraint("business_id", "url", name="uq_social_profiles_business_url"),)

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(
        db.Integer, db.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform = db.Column(db.String(32), nullable=False, index=True)
    url = db.Column(db.String(500), nullable=False)
    handle = db.Column(db.String(255))
    source = db.Column(db.String(32), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    business = db.relationship("Business", back_populates="social_profiles")

    def __repr__(self):
        return f"<SocialProfile {self.platform} {self.url}>"
