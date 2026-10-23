from flask import current_app
from flask_restx import Namespace, Resource, fields

from app.api.common import json_body
from app.extensions import db
from app.models import LeadStatus, StopStatus, TravelMode, Trip, TripStop
from app.services import nfc, trips

ns = Namespace("trips", description="Visiting businesses in person: stops, the fastest route, and visit outcomes")

stop_business_model = ns.model(
    "TripStopBusiness",
    {
        "id": fields.Integer,
        "place_id": fields.String,
        "name": fields.String,
        "category": fields.String,
        "address": fields.String,
        "phone": fields.String,
        "latitude": fields.Float,
        "longitude": fields.Float,
        "rating": fields.Float,
        "review_count": fields.Integer,
        "lead_status": fields.String,
        "service_content": fields.String,
        "service_nfc": fields.String,
        "review_url": fields.String(attribute=lambda b: nfc.review_url(b)),
    },
)

stop_model = ns.model(
    "TripStop",
    {
        "id": fields.Integer,
        "position": fields.Integer(description="0-based visiting order"),
        "status": fields.String(enum=list(StopStatus.ALL)),
        "visited_at": fields.DateTime,
        "outcome": fields.String(description="Visit outcome when visited"),
        "note": fields.String,
        "leg_duration_s": fields.Float(description="Travel from the previous stop"),
        "leg_distance_m": fields.Float,
        "eta": fields.String(attribute=lambda s: s["eta"].strftime("%Y-%m-%dT%H:%M"), description="Local arrival time"),
        "open_state": fields.String(enum=["open", "closes_soon", "closed", "unknown"]),
        "open_text": fields.String,
        "nfc_reasons": fields.List(fields.String),
        "business": fields.Nested(stop_business_model),
    },
)

trip_summary_model = ns.model(
    "TripSummary",
    {
        "id": fields.Integer(readonly=True),
        "name": fields.String,
        "mode": fields.String(enum=list(TravelMode.ALL)),
        "start_at": fields.String(
            attribute=lambda t: t["start_at"].strftime("%Y-%m-%dT%H:%M") if t["start_at"] else None,
            description="Local time you plan to reach the first stop; null = now",
        ),
        "minutes_per_stop": fields.Integer,
        "stop_count": fields.Integer,
        "done_count": fields.Integer(description="Visited or skipped"),
        "optimized": fields.Boolean(description="False until 'find best route' runs after the last change"),
        "total_duration_s": fields.Float(description="Travel time only"),
        "total_distance_m": fields.Float,
        "created_at": fields.DateTime,
    },
)

trip_model = ns.inherit(
    "Trip",
    trip_summary_model,
    {
        "planned_start": fields.String(attribute=lambda t: t["planned_start"].strftime("%Y-%m-%dT%H:%M")),
        "finish_at": fields.String(attribute=lambda t: t["finish_at"].strftime("%Y-%m-%dT%H:%M") if t["finish_at"] else None),
        "route_geometry": fields.Raw(description="[[lat, lng], ...] along the streets"),
        "route_estimated": fields.Boolean(description="True when the routing server was unreachable (straight lines)"),
        "stops": fields.List(fields.Nested(stop_model)),
    },
)

trip_input_model = ns.model(
    "TripInput",
    {
        "name": fields.String,
        "mode": fields.String(enum=list(TravelMode.ALL)),
        "start_at": fields.String(example="2026-10-24T10:00"),
        "minutes_per_stop": fields.Integer(example=15),
        "business_ids": fields.List(fields.Integer, description="Only when creating"),
    },
)

stops_input_model = ns.model("TripStopsInput", {"business_ids": fields.List(fields.Integer, required=True)})

skipped_model = ns.model("SkippedStop", {"id": fields.Integer, "name": fields.String, "reason": fields.String})

stops_result_model = ns.model(
    "TripStopsResult",
    {
        "added": fields.Integer,
        "skipped": fields.List(fields.Nested(skipped_model)),
        "trip": fields.Nested(trip_model),
    },
)

remove_closed_model = ns.model("TripRemoveClosedResult", {"removed": fields.Integer, "trip": fields.Nested(trip_model)})

visit_input_model = ns.model(
    "VisitInput",
    {
        "outcome": fields.String(
            required=True, enum=[*LeadStatus.CALL_OUTCOMES, StopStatus.SKIPPED],
            description="How it went; no_answer = owner not there. 'skipped' = didn't go in.",
        ),
        "note": fields.String,
        "service_content": fields.String,
        "service_nfc": fields.String,
    },
)


def get_trip_or_404(trip_id):
    trip = db.session.get(Trip, trip_id)
    if trip is None:
        ns.abort(404, f"Trip {trip_id} not found")
    return trip


def get_stop_or_404(trip, stop_id):
    stop = db.session.get(TripStop, stop_id)
    if stop is None or stop.trip_id != trip.id:
        ns.abort(404, f"Stop {stop_id} not found in this trip")
    return stop


def detail(trip):
    return trips.trip_detail(trip, current_app.config)


@ns.route("")
class TripList(Resource):
    @ns.marshal_list_with(trip_summary_model)
    def get(self):
        """All trips, newest first."""
        rows = db.session.scalars(db.select(Trip).order_by(Trip.created_at.desc())).all()
        return [trips.trip_summary(t) for t in rows]

    @ns.expect(trip_input_model)
    @ns.response(400, "Validation error")
    @ns.marshal_with(stops_result_model, code=201)
    def post(self):
        """Create a trip, optionally with businesses already in it."""
        payload = json_body(ns)
        trip = Trip(name=trips.default_trip_name(current_app.config), mode=TravelMode.FOOT, minutes_per_stop=15)
        db.session.add(trip)
        try:
            trips.update_trip(trip, {k: v for k, v in payload.items() if k != "business_ids"})
            added, skipped = trips.add_stops(trip, payload.get("business_ids") or [], current_app.config["TRIP_MAX_STOPS"])
        except ValueError as exc:
            db.session.rollback()
            ns.abort(400, str(exc))
        db.session.commit()
        return {"added": added, "skipped": skipped, "trip": detail(trip)}, 201


@ns.route("/<int:trip_id>")
@ns.response(404, "Trip not found")
class TripItem(Resource):
    @ns.marshal_with(trip_model)
    def get(self, trip_id):
        """The trip with each stop's arrival time and whether it's open then."""
        return detail(get_trip_or_404(trip_id))

    @ns.expect(trip_input_model)
    @ns.response(400, "Validation error")
    @ns.marshal_with(trip_model)
    def patch(self, trip_id):
        """Change name, travel mode, start time or minutes per stop."""
        trip = get_trip_or_404(trip_id)
        try:
            trips.update_trip(trip, json_body(ns))
        except ValueError as exc:
            ns.abort(400, str(exc))
        db.session.commit()
        return detail(trip)

    @ns.response(204, "Deleted")
    def delete(self, trip_id):
        """Delete the trip. Logged visits stay in each lead's history."""
        db.session.delete(get_trip_or_404(trip_id))
        db.session.commit()
        return "", 204


@ns.route("/<int:trip_id>/stops")
@ns.response(404, "Trip not found")
class TripStops(Resource):
    @ns.expect(stops_input_model)
    @ns.response(400, "Validation error")
    @ns.marshal_with(stops_result_model)
    def post(self, trip_id):
        """Add businesses. Not interested / client leads and ones without a location are skipped."""
        trip = get_trip_or_404(trip_id)
        try:
            added, skipped = trips.add_stops(
                trip, json_body(ns).get("business_ids"), current_app.config["TRIP_MAX_STOPS"]
            )
        except ValueError as exc:
            ns.abort(400, str(exc))
        db.session.commit()
        return {"added": added, "skipped": skipped, "trip": detail(trip)}


@ns.route("/<int:trip_id>/stops/<int:stop_id>")
@ns.response(404, "Trip or stop not found")
class TripStopItem(Resource):
    @ns.marshal_with(trip_model)
    def delete(self, trip_id, stop_id):
        """Remove a stop from the trip."""
        trip = get_trip_or_404(trip_id)
        trips.remove_stop(trip, get_stop_or_404(trip, stop_id))
        db.session.commit()
        return detail(trip)


@ns.route("/<int:trip_id>/optimize")
@ns.response(404, "Trip not found")
class TripOptimize(Resource):
    @ns.response(400, "No stops")
    @ns.marshal_with(trip_model)
    def post(self, trip_id):
        """Put the stops in the fastest walking/driving order (any stop can be first) and get the street route."""
        trip = get_trip_or_404(trip_id)
        try:
            trips.optimize(trip, current_app.config)
        except ValueError as exc:
            ns.abort(400, str(exc))
        db.session.commit()
        return detail(trip)


@ns.route("/<int:trip_id>/remove-closed")
@ns.response(404, "Trip not found")
class TripRemoveClosed(Resource):
    @ns.marshal_with(remove_closed_model)
    def post(self, trip_id):
        """Remove stops that will be closed when you arrive."""
        trip = get_trip_or_404(trip_id)
        removed = trips.remove_closed_stops(trip, current_app.config)
        db.session.commit()
        return {"removed": removed, "trip": detail(trip)}


@ns.route("/<int:trip_id>/stops/<int:stop_id>/visit")
@ns.response(404, "Trip or stop not found")
class TripStopVisit(Resource):
    @ns.expect(visit_input_model)
    @ns.response(400, "Validation error")
    @ns.marshal_with(trip_model)
    def post(self, trip_id, stop_id):
        """Log how the visit went (saved in the lead's history like a call), or skip the stop."""
        trip = get_trip_or_404(trip_id)
        stop = get_stop_or_404(trip, stop_id)
        try:
            trips.log_visit(stop, json_body(ns))
        except ValueError as exc:
            db.session.rollback()
            ns.abort(400, str(exc))
        db.session.commit()
        return detail(trip)

    @ns.marshal_with(trip_model)
    def delete(self, trip_id, stop_id):
        """Undo: mark the stop not visited and remove the visit from the lead's history."""
        trip = get_trip_or_404(trip_id)
        trips.undo_visit(get_stop_or_404(trip, stop_id))
        db.session.commit()
        return detail(trip)
