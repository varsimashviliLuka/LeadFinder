"""Planning trips to visit businesses in person."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.extensions import db
from app.models import Business, ContactKind, LeadStatus, StopStatus, TravelMode, Trip, TripStop
from app.models.common import utcnow
from app.services import nfc
from app.services.businesses import delete_call, log_call, set_services
from app.services.opening_hours import open_status
from app.services.routing import Router, best_order

# Leads not worth a visit; they're left out when adding stops.
EXCLUDED_STATUSES = (LeadStatus.NOT_INTERESTED, LeadStatus.CLIENT)


def default_trip_name(config):
    now = datetime.now(ZoneInfo(config["SCRAPER_TIMEZONE"]))
    return f"Trip {now:%d %b}"


def _invalidate_route(trip):
    trip.optimized_at = None
    trip.total_duration_s = None
    trip.total_distance_m = None
    trip.route_geometry = None
    trip.route_estimated = False
    for stop in trip.stops:
        stop.leg_duration_s = None
        stop.leg_distance_m = None


def update_trip(trip, payload):
    """Edit name, mode, start time and minutes per stop. Raises ValueError. Caller commits."""
    if "name" in payload:
        name = payload["name"]
        if not isinstance(name, str) or not name.strip():
            raise ValueError("name is required")
        trip.name = name.strip()[:120]
    if "mode" in payload:
        if payload["mode"] not in TravelMode.ALL:
            raise ValueError(f"mode must be one of: {', '.join(TravelMode.ALL)}")
        if payload["mode"] != trip.mode:
            trip.mode = payload["mode"]
            _invalidate_route(trip)
    if "start_at" in payload:
        value = payload["start_at"]
        if value in (None, ""):
            trip.start_at = None
        else:
            try:
                trip.start_at = datetime.fromisoformat(value).replace(tzinfo=None, second=0, microsecond=0)
            except (TypeError, ValueError):
                raise ValueError("start_at must be like 2026-10-24T10:00") from None
    if "minutes_per_stop" in payload:
        minutes = payload["minutes_per_stop"]
        if not isinstance(minutes, int) or isinstance(minutes, bool) or not 0 <= minutes <= 240:
            raise ValueError("minutes_per_stop must be a whole number from 0 to 240")
        trip.minutes_per_stop = minutes
    return trip


def add_stops(trip, business_ids, max_stops):
    """Add businesses to the end of the trip. Returns (added, skipped) where skipped
    lists {"id", "name", "reason"}. Caller commits."""
    if not isinstance(business_ids, list) or not all(isinstance(i, int) for i in business_ids):
        raise ValueError("business_ids must be a list of ids")
    existing = {s.business_id for s in trip.stops}
    businesses = {b.id: b for b in db.session.scalars(db.select(Business).where(Business.id.in_(business_ids)))}
    added, skipped = 0, []
    for business_id in dict.fromkeys(business_ids):
        business = businesses.get(business_id)
        reason = None
        if business is None:
            continue
        if business_id in existing:
            reason = "already in this trip"
        elif business.latitude is None or business.longitude is None:
            reason = "no location on the map"
        elif business.lead_status in EXCLUDED_STATUSES:
            reason = "marked Not interested" if business.lead_status == LeadStatus.NOT_INTERESTED else "already a client"
        elif len(trip.stops) >= max_stops:
            reason = f"a trip can have at most {max_stops} stops"
        if reason:
            skipped.append({"id": business.id, "name": business.name, "reason": reason})
            continue
        trip.stops.append(TripStop(business=business, position=len(trip.stops)))
        existing.add(business_id)
        added += 1
    if added:
        _invalidate_route(trip)
    return added, skipped


def _renumber(trip):
    for position, stop in enumerate(trip.stops):
        stop.position = position


def remove_stop(trip, stop):
    trip.stops.remove(stop)
    _renumber(trip)
    _invalidate_route(trip)


def optimize(trip, config):
    """Reorder the stops into the fastest walking/driving order and store the route. Caller commits."""
    stops = list(trip.stops)
    if not stops:
        raise ValueError("Add some businesses to the trip first")
    router = Router(config)
    points = [(s.business.latitude, s.business.longitude) for s in stops]
    durations, _, matrix_estimated = router.matrix(points, trip.mode)
    order = best_order(durations)
    ordered = [stops[i] for i in order]
    legs, geometry, route_estimated = router.route([points[i] for i in order], trip.mode)

    for position, stop in enumerate(ordered):
        stop.position = position
        stop.leg_duration_s, stop.leg_distance_m = legs[position - 1] if position else (None, None)
    trip.stops.sort(key=lambda s: s.position)
    trip.total_duration_s = sum(d for d, _ in legs)
    trip.total_distance_m = sum(m for _, m in legs)
    trip.route_geometry = geometry
    trip.route_estimated = matrix_estimated or route_estimated
    trip.optimized_at = utcnow()
    return trip


def _start_time(trip, config):
    if trip.start_at:
        return trip.start_at
    now = datetime.now(ZoneInfo(config["SCRAPER_TIMEZONE"])).replace(tzinfo=None, second=0, microsecond=0)
    return now


def schedule(trip, config):
    """Arrival time and opening status per stop id, plus when you'd finish."""
    clock = _start_time(trip, config)
    result = {}
    for index, stop in enumerate(trip.stops):
        if index:
            clock += timedelta(seconds=stop.leg_duration_s or 0)
        result[stop.id] = {
            "eta": clock,
            "open": open_status(stop.business.opening_hours, clock, trip.minutes_per_stop),
        }
        clock += timedelta(minutes=trip.minutes_per_stop)
    return result, clock


def remove_closed_stops(trip, config):
    """Drop not-yet-visited stops that will be closed on arrival. Returns how many. Caller commits."""
    times, _ = schedule(trip, config)
    closed = [s for s in trip.stops if s.status == StopStatus.PENDING and times[s.id]["open"]["state"] == "closed"]
    for stop in closed:
        trip.stops.remove(stop)
    if closed:
        _renumber(trip)
        _invalidate_route(trip)
    return len(closed)


def log_visit(stop, payload):
    """Record how a visit went (like a call), or mark the stop skipped. Caller commits."""
    if stop.status != StopStatus.PENDING:
        raise ValueError("This stop is already done. Undo it first to change it")
    outcome = payload.get("outcome")
    if outcome == StopStatus.SKIPPED:
        stop.status = StopStatus.SKIPPED
        stop.visited_at = utcnow()
        return stop
    note = payload.get("note")
    if note is not None and not isinstance(note, str):
        raise ValueError("note must be a string")
    set_services(stop.business, payload)
    stop.call = log_call(stop.business, outcome, note, kind=ContactKind.VISIT)
    stop.status = StopStatus.VISITED
    stop.visited_at = stop.call.created_at
    return stop


def undo_visit(stop):
    """Put a stop back to 'not visited', removing the visit it logged. Caller commits."""
    if stop.call is not None:
        delete_call(stop.business, stop.call)
        stop.call = None
    stop.status = StopStatus.PENDING
    stop.visited_at = None


def trip_summary(trip):
    done = sum(1 for s in trip.stops if s.status != StopStatus.PENDING)
    return {
        "id": trip.id,
        "name": trip.name,
        "mode": trip.mode,
        "start_at": trip.start_at,
        "minutes_per_stop": trip.minutes_per_stop,
        "stop_count": len(trip.stops),
        "done_count": done,
        "optimized": trip.optimized_at is not None,
        "total_duration_s": trip.total_duration_s,
        "total_distance_m": trip.total_distance_m,
        "created_at": trip.created_at,
    }


def trip_detail(trip, config):
    times, finish = schedule(trip, config)
    data = trip_summary(trip)
    data.update(
        route_geometry=trip.route_geometry,
        route_estimated=trip.route_estimated,
        planned_start=_start_time(trip, config),
        finish_at=finish if trip.stops else None,
        stops=[
            {
                "id": s.id,
                "position": s.position,
                "status": s.status,
                "visited_at": s.visited_at,
                "outcome": s.call.outcome if s.call else None,
                "note": s.call.note if s.call else None,
                "leg_duration_s": s.leg_duration_s,
                "leg_distance_m": s.leg_distance_m,
                "eta": times[s.id]["eta"],
                "open_state": times[s.id]["open"]["state"],
                "open_text": times[s.id]["open"]["text"],
                "business": s.business,
                "nfc_reasons": nfc.prospect_reasons(s.business),
            }
            for s in trip.stops
        ],
    )
    return data
