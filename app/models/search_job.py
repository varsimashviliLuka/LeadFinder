from app.extensions import db
from app.models.business import search_job_results
from app.models.common import utcnow


class SearchJobStatus:
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    ALL = (PENDING, RUNNING, COMPLETED, FAILED, CANCELLED)
    FINISHED = (COMPLETED, FAILED, CANCELLED)


class SearchJobStage:
    MAPS = "maps"
    SOCIALS = "socials"

    ALL = (MAPS, SOCIALS)


class SearchJob(db.Model):
    __tablename__ = "search_jobs"

    id = db.Column(db.Integer, primary_key=True)
    query = db.Column(db.String(255), nullable=False)
    location_text = db.Column(db.String(500))
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    radius_m = db.Column(db.Integer, nullable=False, default=2000)
    max_results = db.Column(db.Integer, nullable=False, default=50)

    status = db.Column(db.String(32), nullable=False, default=SearchJobStatus.PENDING, index=True)
    results_found = db.Column(db.Integer, nullable=False, default=0)
    results_new = db.Column(db.Integer, nullable=False, default=0)
    error = db.Column(db.Text)

    find_socials = db.Column(db.Boolean, nullable=False, default=False)
    collect_reviews = db.Column(db.Boolean, nullable=False, default=False)
    stage = db.Column(db.String(32))
    socials_total = db.Column(db.Integer, nullable=False, default=0)
    socials_checked = db.Column(db.Integer, nullable=False, default=0)
    socials_found = db.Column(db.Integer, nullable=False, default=0)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    started_at = db.Column(db.DateTime(timezone=True))
    finished_at = db.Column(db.DateTime(timezone=True))

    businesses = db.relationship("Business", secondary=search_job_results, back_populates="search_jobs")

    def __repr__(self):
        return f"<SearchJob {self.id} {self.query!r} {self.status}>"
