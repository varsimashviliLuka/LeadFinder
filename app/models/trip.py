from app.extensions import db
from app.models.common import utcnow


class TravelMode:
    FOOT = "foot"
    CAR = "car"

    ALL = (FOOT, CAR)


class StopStatus:
    PENDING = "pending"
    VISITED = "visited"
    SKIPPED = "skipped"

    ALL = (PENDING, VISITED, SKIPPED)


class Trip(db.Model):
    """A list of businesses to visit in person, in the order you'll walk or drive them."""

    __tablename__ = "trips"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    mode = db.Column(db.String(8), nullable=False, default=TravelMode.FOOT)
    # Local wall-clock time you plan to reach the first stop; null means "now".
    start_at = db.Column(db.DateTime)
    minutes_per_stop = db.Column(db.Integer, nullable=False, default=15)

    # Filled by "find best route"; cleared whenever the stops or the mode change.
    optimized_at = db.Column(db.DateTime(timezone=True))
    total_duration_s = db.Column(db.Float)
    total_distance_m = db.Column(db.Float)
    route_geometry = db.Column(db.JSON(none_as_null=True))  # [[lat, lng], ...]
    route_estimated = db.Column(db.Boolean, nullable=False, default=False)  # straight lines, routing server unreachable

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    stops = db.relationship(
        "TripStop", back_populates="trip", cascade="all, delete-orphan", order_by="TripStop.position"
    )

    def __repr__(self):
        return f"<Trip {self.id} {self.name!r}>"


class TripStop(db.Model):
    __tablename__ = "trip_stops"
    __table_args__ = (db.UniqueConstraint("trip_id", "business_id", name="uq_trip_stop_business"),)

    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey("trips.id", ondelete="CASCADE"), nullable=False, index=True)
    business_id = db.Column(db.Integer, db.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    position = db.Column(db.Integer, nullable=False)
    # Travel from the previous stop (null for the first stop or before optimizing).
    leg_duration_s = db.Column(db.Float)
    leg_distance_m = db.Column(db.Float)

    status = db.Column(db.String(16), nullable=False, default=StopStatus.PENDING)
    visited_at = db.Column(db.DateTime(timezone=True))
    call_id = db.Column(db.Integer, db.ForeignKey("call_logs.id", ondelete="SET NULL"))

    trip = db.relationship("Trip", back_populates="stops")
    business = db.relationship("Business", back_populates="trip_stops")
    call = db.relationship("CallLog")
