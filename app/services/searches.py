from flask import current_app
from sqlalchemy import delete, update

from app.extensions import db
from app.models import SearchJob, SearchJobStatus
from app.models.common import utcnow
from app.services import geocoding


def _number(payload, key, kind, default=None, low=None, high=None):
    value = payload.get(key, default)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a number")
    if kind is int:
        if value != int(value):
            raise ValueError(f"{key} must be a whole number")
        value = int(value)
    else:
        value = float(value)
    if (low is not None and value < low) or (high is not None and value > high):
        raise ValueError(f"{key} must be between {low} and {high}")
    return value


def create_search_job(payload):
    """Validate a search request and save it as a pending job.

    Coordinates win when given; otherwise location_text is geocoded.
    Raises ValueError for bad input and GeocodingError if lookup fails.
    """
    config = current_app.config

    query = payload.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query is required, e.g. 'restaurant' or 'beauty salon'")
    query = query.strip()

    location_text = payload.get("location_text")
    if location_text is not None and not isinstance(location_text, str):
        raise ValueError("location_text must be a string")
    location_text = (location_text or "").strip() or None

    latitude = _number(payload, "latitude", float, low=-90, high=90)
    longitude = _number(payload, "longitude", float, low=-180, high=180)
    if (latitude is None) != (longitude is None):
        raise ValueError("latitude and longitude must be given together")

    if latitude is None:
        if not location_text:
            raise ValueError("Provide latitude and longitude, or a location_text address")
        matches = geocoding.search(location_text, limit=1)
        if not matches:
            raise ValueError(f"Could not find a location for {location_text!r}")
        latitude, longitude = matches[0].latitude, matches[0].longitude

    find_socials = payload.get("find_socials", False)
    collect_reviews = payload.get("collect_reviews", False)
    for key, value in (("find_socials", find_socials), ("collect_reviews", collect_reviews)):
        if not isinstance(value, bool):
            raise ValueError(f"{key} must be true or false")

    radius_low, radius_high = config["SEARCH_RADIUS_RANGE"]
    results_low, results_high = config["SEARCH_MAX_RESULTS_RANGE"]
    job = SearchJob(
        query=query,
        location_text=location_text,
        latitude=latitude,
        longitude=longitude,
        radius_m=_number(payload, "radius_m", int, 2000, radius_low, radius_high),
        max_results=_number(payload, "max_results", int, 50, results_low, results_high),
        find_socials=find_socials,
        collect_reviews=collect_reviews,
    )
    db.session.add(job)
    db.session.commit()
    return job


def delete_search_job(job):
    """Delete a finished search that found nothing. Raises ValueError otherwise."""
    if job.status not in SearchJobStatus.FINISHED:
        raise ValueError("Stop the search before deleting it")
    if job.results_found:
        raise ValueError("Only searches that found nothing can be deleted; this one has saved businesses")
    db.session.delete(job)
    db.session.commit()


def delete_empty_search_jobs():
    """Delete every finished search that found nothing. Returns how many."""
    deleted = db.session.execute(
        delete(SearchJob).where(SearchJob.status.in_(SearchJobStatus.FINISHED), SearchJob.results_found == 0)
    ).rowcount
    db.session.commit()
    return deleted


def cancel_search_job(job, runner):
    """Stop a job. Pending jobs cancel immediately; running ones stop at the next result."""
    if job.status in SearchJobStatus.FINISHED:
        raise ValueError(f"Search job is already {job.status}")

    # Conditional update so a job the runner just picked up isn't marked
    # cancelled while it keeps running.
    cancelled_while_pending = db.session.execute(
        update(SearchJob)
        .where(SearchJob.id == job.id, SearchJob.status == SearchJobStatus.PENDING)
        .values(status=SearchJobStatus.CANCELLED, finished_at=utcnow())
    ).rowcount
    db.session.commit()
    if not cancelled_while_pending:
        runner.cancel(job.id)

    db.session.refresh(job)
    return job
