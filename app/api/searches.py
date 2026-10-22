from flask import current_app
from flask_restx import Namespace, Resource, fields
from sqlalchemy import select

from app.api.common import json_body, page_model, paginate, pagination_parser
from app.extensions import db
from app.models import SearchJob, SearchJobStage, SearchJobStatus
from app.services.geocoding import GeocodingError
from app.services.scrapers.pacing import ScraperState
from app.services.searches import (
    cancel_search_job,
    create_search_job,
    delete_empty_search_jobs,
    delete_search_job,
)
from app.workers import job_runner

ns = Namespace("searches", description="Google Maps search jobs")

search_create_model = ns.model(
    "SearchCreate",
    {
        "query": fields.String(required=True, example="restaurant", description="What to search for"),
        "location_text": fields.String(
            example="Vake, Tbilisi", description="Address to geocode when coordinates are not given"
        ),
        "latitude": fields.Float(example=41.7151),
        "longitude": fields.Float(example=44.7661),
        "radius_m": fields.Integer(default=2000, description="100 to 50000 meters"),
        "max_results": fields.Integer(default=50, description="1 to 200"),
        "find_socials": fields.Boolean(
            default=False,
            description="After the Maps search, check each website and find email, WhatsApp and social accounts",
        ),
        "collect_reviews": fields.Boolean(
            default=False, description="Read each place's newest reviews (latest review date, owner replies)"
        ),
    },
)

search_job_model = ns.model(
    "SearchJob",
    {
        "id": fields.Integer(readonly=True),
        "query": fields.String,
        "location_text": fields.String,
        "latitude": fields.Float,
        "longitude": fields.Float,
        "radius_m": fields.Integer,
        "max_results": fields.Integer,
        "status": fields.String(enum=list(SearchJobStatus.ALL)),
        "results_found": fields.Integer,
        "results_new": fields.Integer,
        "find_socials": fields.Boolean,
        "collect_reviews": fields.Boolean,
        "stage": fields.String(enum=list(SearchJobStage.ALL), description="What a running job is doing now"),
        "socials_total": fields.Integer(description="Businesses queued for the social media lookup"),
        "socials_checked": fields.Integer,
        "socials_found": fields.Integer(description="Checked businesses with at least one account"),
        "error": fields.String,
        "created_at": fields.DateTime,
        "started_at": fields.DateTime,
        "finished_at": fields.DateTime,
    },
)

search_job_page_model = page_model(ns, "SearchJobPage", search_job_model)

list_parser = pagination_parser()


@ns.route("")
class SearchJobList(Resource):
    @ns.expect(list_parser)
    @ns.marshal_with(search_job_page_model)
    def get(self):
        args = list_parser.parse_args()
        stmt = select(SearchJob).order_by(SearchJob.created_at.desc(), SearchJob.id.desc())
        return paginate(db, stmt, args["page"], args["per_page"])

    @ns.expect(search_create_model)
    @ns.response(400, "Validation error")
    @ns.response(502, "Geocoding service unavailable")
    @ns.marshal_with(search_job_model, code=201)
    def post(self):
        """Start a search in the background; poll GET /searches/<id> for progress."""
        try:
            job = create_search_job(json_body(ns))
        except ValueError as exc:
            ns.abort(400, str(exc))
        except GeocodingError as exc:
            ns.abort(502, str(exc))
        job_runner.submit(job.id)
        db.session.refresh(job)
        return job, 201


scraper_status_model = ns.model(
    "ScraperStatus",
    {
        "provider": fields.String,
        "places_today": fields.Integer,
        "daily_limit": fields.Integer,
        "blocked_until": fields.DateTime,
        "next_search_in": fields.Integer(description="Seconds until the cooldown allows another search"),
    },
)


@ns.route("/scraper-status")
class ScraperStatus(Resource):
    @ns.marshal_with(scraper_status_model)
    def get(self):
        """Daily usage, cooldown and CAPTCHA pause for the Google Maps scraper."""
        config = current_app.config
        state = ScraperState(config["SCRAPER_STATE_FILE"])
        return {
            "provider": config["SCRAPER_PROVIDER"],
            "places_today": state.places_today(),
            "daily_limit": config["SCRAPER_DAILY_PLACE_LIMIT"],
            "blocked_until": state.blocked_until(),
            "next_search_in": round(state.seconds_until_next_search(config["SCRAPER_SEARCH_COOLDOWN"])),
        }


def get_job_or_404(job_id):
    job = db.session.get(SearchJob, job_id)
    if job is None:
        ns.abort(404, f"Search job {job_id} not found")
    return job


@ns.route("/<int:job_id>")
@ns.response(404, "Search job not found")
class SearchJobItem(Resource):
    @ns.marshal_with(search_job_model)
    def get(self, job_id):
        return get_job_or_404(job_id)

    @ns.response(204, "Deleted")
    @ns.response(409, "Search is still running or found businesses")
    def delete(self, job_id):
        """Delete a finished search that found nothing."""
        try:
            delete_search_job(get_job_or_404(job_id))
        except ValueError as exc:
            ns.abort(409, str(exc))
        return "", 204


@ns.route("/empty")
class EmptySearchJobs(Resource):
    @ns.marshal_with(ns.model("DeletedCount", {"deleted": fields.Integer}))
    def delete(self):
        """Delete all finished searches that found nothing."""
        return {"deleted": delete_empty_search_jobs()}


@ns.route("/<int:job_id>/cancel")
@ns.response(404, "Search job not found")
class SearchJobCancel(Resource):
    @ns.response(409, "Search job already finished")
    @ns.marshal_with(search_job_model)
    def post(self, job_id):
        """Cancel a pending or running search. Businesses already saved are kept."""
        job = get_job_or_404(job_id)
        try:
            return cancel_search_job(job, job_runner)
        except ValueError as exc:
            ns.abort(409, str(exc))
