from datetime import date

from flask import Response, current_app
from flask_restx import Namespace, Resource, fields, inputs

from app.api.common import json_body, page_model, paginate, pagination_parser
from app.extensions import db
from app.models import (
    Business,
    CallLog,
    ContactKind,
    LeadStatus,
    ServiceStatus,
    SocialPlatform,
    SocialProfile,
    SocialSource,
)
from app.services import mailer, nfc, socials
from app.services.website_info import website_issues
from app.services.businesses import (
    SERVICE_FILTERS,
    SOCIAL_FILTERS,
    SORTABLE_FIELDS,
    build_business_query,
    business_stats,
    businesses_to_csv,
    delete_call,
    log_call,
    update_business,
)

ns = Namespace("businesses", description="Businesses found on Google Maps, managed as leads")

social_profile_model = ns.model(
    "SocialProfile",
    {
        "id": fields.Integer(readonly=True),
        "platform": fields.String(enum=list(SocialPlatform.ALL)),
        "url": fields.String,
        "handle": fields.String,
        "source": fields.String(enum=list(SocialSource.ALL), description="Where the link was found"),
        "created_at": fields.DateTime(readonly=True),
    },
)

business_model = ns.model(
    "Business",
    {
        "id": fields.Integer(readonly=True),
        "place_id": fields.String(readonly=True),
        "name": fields.String,
        "category": fields.String,
        "address": fields.String,
        "latitude": fields.Float,
        "longitude": fields.Float,
        "phone": fields.String,
        "website": fields.String,
        "email": fields.String,
        "rating": fields.Float,
        "review_count": fields.Integer,
        "opening_hours": fields.Raw,
        "maps_url": fields.String,
        "claimed": fields.Boolean(description="False when the Google listing is unclaimed"),
        "price_level": fields.String(description="As shown on Google Maps, e.g. ₾₾ or ₾10–20"),
        "latest_review_date": fields.Date(description="Approximate date of the newest Google review"),
        "recent_reviews_checked": fields.Integer(description="Newest reviews read"),
        "recent_owner_replies": fields.Integer(description="How many of those the owner replied to"),
        "whatsapp": fields.String,
        "service_content": fields.String(enum=list(ServiceStatus.ALL), description="Content creation; null = not offered"),
        "service_nfc": fields.String(enum=list(ServiceStatus.ALL), description="Google review NFC card; null = not offered"),
        "nfc_reasons": fields.List(
            fields.String, attribute=lambda b: nfc.prospect_reasons(b),
            description="Why a review NFC card would help; empty = not a prospect",
        ),
        "review_url": fields.String(
            attribute=lambda b: nfc.review_url(b), description="Google 'write a review' link to put on the NFC card"
        ),
        "social_profiles": fields.List(fields.Nested(social_profile_model)),
        "social_checked_at": fields.DateTime(description="When website & social media were last checked; null if never"),
        "website_check": fields.Raw(description="https, mobile_friendly, load_seconds, copyright_year, builder, error"),
        "website_issues": fields.List(
            fields.String, attribute=lambda b: website_issues(b.website_check), description="Problems worth mentioning"
        ),
        "lead_status": fields.String(enum=list(LeadStatus.ALL)),
        "notes": fields.String,
        "follow_up_date": fields.Date,
        "last_contacted_at": fields.DateTime,
        "created_at": fields.DateTime,
        "updated_at": fields.DateTime,
    },
)

call_model = ns.model(
    "CallLog",
    {
        "id": fields.Integer(readonly=True),
        "kind": fields.String(enum=list(ContactKind.ALL)),
        "outcome": fields.String(enum=list(LeadStatus.CALL_OUTCOMES)),
        "note": fields.String,
        "created_at": fields.DateTime(readonly=True),
    },
)

sent_email_model = ns.model(
    "SentEmail",
    {
        "id": fields.Integer(readonly=True),
        "to_address": fields.String,
        "from_address": fields.String,
        "subject": fields.String,
        "body": fields.String,
        "created_at": fields.DateTime(readonly=True),
    },
)

email_create_model = ns.model(
    "EmailCreate",
    {
        "to": fields.String(description="Defaults to the lead's email"),
        "subject": fields.String(required=True),
        "body": fields.String(required=True),
    },
)

business_detail_model = ns.inherit(
    "BusinessDetail",
    business_model,
    {
        "calls": fields.List(fields.Nested(call_model)),
        "emails": fields.List(fields.Nested(sent_email_model), description="Emails sent from the app, newest first"),
    },
)

business_page_model = page_model(ns, "BusinessPage", business_model)

business_update_model = ns.model(
    "BusinessUpdate",
    {
        "lead_status": fields.String(enum=list(LeadStatus.ALL)),
        "notes": fields.String,
        "follow_up_date": fields.Date(description="YYYY-MM-DD, or null to clear"),
        "email": fields.String,
        "phone": fields.String,
        "website": fields.String,
        "whatsapp": fields.String,
        "service_content": fields.String(enum=list(ServiceStatus.ALL), description="null = not offered"),
        "service_nfc": fields.String(enum=list(ServiceStatus.ALL), description="null = not offered"),
    },
)

call_create_model = ns.model(
    "CallCreate",
    {
        "outcome": fields.String(required=True, enum=list(LeadStatus.CALL_OUTCOMES)),
        "note": fields.String,
        "kind": fields.String(enum=list(ContactKind.ALL), default=ContactKind.CALL, description="Phone call or visit"),
    },
)

stats_model = ns.model(
    "BusinessStats",
    {
        "total": fields.Integer,
        "by_status": fields.Raw(example={s: 0 for s in LeadStatus.ALL}),
        "with_phone": fields.Integer,
        "with_website": fields.Integer,
        "unclaimed": fields.Integer,
        "with_social": fields.Integer,
        "social_unchecked": fields.Integer(description="Never looked up and no accounts saved"),
        "needs_check": fields.Integer(description="Never looked up, or website quality never checked"),
        "with_email": fields.Integer,
        "website_problems": fields.Integer(description="Websites with at least one issue"),
        "nfc_prospects": fields.Integer(description="Few reviews, low rating or no recent reviews"),
        "nfc_sold": fields.Integer,
        "content_sold": fields.Integer,
        "follow_ups_due": fields.Integer,
    },
)

social_create_model = ns.model(
    "SocialCreate",
    {"url": fields.String(required=True, example="https://www.instagram.com/yourbusiness")},
)

social_find_result_model = ns.model(
    "SocialFindResult",
    {
        "added": fields.Integer(description="New accounts found"),
        "error": fields.String(description="Why the website couldn't be checked, if it failed"),
        "business": fields.Nested(business_detail_model),
    },
)

list_parser = pagination_parser()
list_parser.add_argument("q", location="args", help="Search name, address, category, phone")
list_parser.add_argument("status", location="args", help="Comma-separated lead statuses")
list_parser.add_argument("category", location="args")
list_parser.add_argument("has_phone", type=inputs.boolean, location="args")
list_parser.add_argument("has_website", type=inputs.boolean, location="args")
list_parser.add_argument("min_rating", type=float, location="args")
list_parser.add_argument("has_email", type=inputs.boolean, location="args")
list_parser.add_argument(
    "website_quality", choices=["problems", "ok"], location="args", help="problems = at least one website issue"
)
list_parser.add_argument("claimed", type=inputs.boolean, location="args", help="false = unclaimed listings")
list_parser.add_argument("search_job_id", type=int, location="args")
list_parser.add_argument("follow_up_due", type=inputs.boolean, location="args")
list_parser.add_argument(
    "social",
    choices=list(SOCIAL_FILTERS),
    location="args",
    help="any / none (checked, nothing found) / unchecked / needs_check / facebook / instagram / tiktok",
)
list_parser.add_argument(
    "nfc_prospect", type=inputs.boolean, location="args", help="true = few reviews, low rating or no recent reviews"
)
list_parser.add_argument(
    "service", choices=list(SERVICE_FILTERS), location="args", help="e.g. nfc:sold, content:interested, nfc:none"
)
list_parser.add_argument("sort", choices=list(SORTABLE_FIELDS), default="created_at", location="args")
list_parser.add_argument("order", choices=["asc", "desc"], default="desc", location="args")

export_parser = list_parser.copy()
export_parser.remove_argument("page")
export_parser.remove_argument("per_page")

map_point_model = ns.model(
    "BusinessMapPoint",
    {
        "id": fields.Integer,
        "name": fields.String,
        "category": fields.String,
        "latitude": fields.Float,
        "longitude": fields.Float,
        "lead_status": fields.String,
        "rating": fields.Float,
        "review_count": fields.Integer,
        "nfc_prospect": fields.Boolean(attribute=lambda b: bool(nfc.prospect_reasons(b))),
    },
)


def get_business_or_404(business_id):
    business = db.session.get(Business, business_id)
    if business is None:
        ns.abort(404, f"Business {business_id} not found")
    return business


@ns.route("")
class BusinessList(Resource):
    @ns.expect(list_parser)
    @ns.marshal_with(business_page_model)
    def get(self):
        args = list_parser.parse_args()
        page, per_page = args.pop("page"), args.pop("per_page")
        return paginate(db, build_business_query(**args), page, per_page)


@ns.route("/export")
class BusinessExport(Resource):
    @ns.expect(export_parser)
    @ns.produces(["text/csv"])
    def get(self):
        """Download the filtered businesses as CSV (opens in Excel with Georgian text intact)."""
        args = export_parser.parse_args()
        businesses = db.session.scalars(build_business_query(**args)).all()
        filename = f"businesses-{date.today().isoformat()}.csv"
        return Response(
            businesses_to_csv(businesses),
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )


@ns.route("/map")
class BusinessMap(Resource):
    @ns.expect(export_parser)
    @ns.marshal_list_with(map_point_model)
    def get(self):
        """Every matching business that has a location, with just what a map needs."""
        args = export_parser.parse_args()
        stmt = build_business_query(**args).where(Business.latitude.isnot(None), Business.longitude.isnot(None))
        return db.session.scalars(stmt).all()


@ns.route("/<int:business_id>/review-qr.<string:kind>")
@ns.response(404, "Business not found, or no Google review link for it")
class BusinessReviewQr(Resource):
    @ns.produces(["image/svg+xml", "image/png"])
    def get(self, business_id, kind):
        """QR code of the business's Google 'write a review' link (svg or png)."""
        if kind not in ("svg", "png"):
            ns.abort(404, "Use review-qr.svg or review-qr.png")
        business = get_business_or_404(business_id)
        url = nfc.review_url(business)
        if not url:
            ns.abort(404, "No Google review link for this business")
        mimetype = "image/svg+xml" if kind == "svg" else "image/png"
        headers = {}
        if kind == "png":
            safe = "".join(c if c.isalnum() else "-" for c in business.name)[:60].strip("-") or "business"
            headers["Content-Disposition"] = f'attachment; filename="review-qr-{safe}.png"'
        return Response(nfc.qr_code(url, kind), mimetype=mimetype, headers=headers)


@ns.route("/stats")
class BusinessStats(Resource):
    @ns.marshal_with(stats_model)
    def get(self):
        return business_stats()


@ns.route("/<int:business_id>")
@ns.response(404, "Business not found")
class BusinessItem(Resource):
    @ns.marshal_with(business_detail_model)
    def get(self, business_id):
        return get_business_or_404(business_id)

    @ns.expect(business_update_model)
    @ns.response(400, "Validation error")
    @ns.marshal_with(business_detail_model)
    def patch(self, business_id):
        """Update lead fields: lead_status, notes, follow_up_date, contacts, website, service_content, service_nfc."""
        business = get_business_or_404(business_id)
        try:
            update_business(business, json_body(ns))
        except ValueError as exc:
            ns.abort(400, str(exc))
        db.session.commit()
        return business

    @ns.response(204, "Deleted")
    def delete(self, business_id):
        business = get_business_or_404(business_id)
        db.session.delete(business)
        db.session.commit()
        return "", 204


@ns.route("/<int:business_id>/calls")
@ns.response(404, "Business not found")
class BusinessCalls(Resource):
    @ns.marshal_list_with(call_model)
    def get(self, business_id):
        return get_business_or_404(business_id).calls

    @ns.expect(call_create_model)
    @ns.response(400, "Validation error")
    @ns.marshal_with(call_model, code=201)
    def post(self, business_id):
        """Log a call or visit; the business's lead_status becomes the outcome."""
        business = get_business_or_404(business_id)
        payload = json_body(ns)
        note = payload.get("note")
        if note is not None and not isinstance(note, str):
            ns.abort(400, "note must be a string")
        try:
            call = log_call(business, payload.get("outcome"), note, kind=payload.get("kind") or ContactKind.CALL)
        except ValueError as exc:
            ns.abort(400, str(exc))
        db.session.commit()
        return call, 201


@ns.route("/<int:business_id>/emails")
@ns.response(404, "Business not found")
class BusinessEmails(Resource):
    @ns.expect(email_create_model)
    @ns.response(400, "Validation error or Gmail not connected")
    @ns.response(502, "Gmail couldn't send it")
    @ns.marshal_with(business_detail_model, code=201)
    def post(self, business_id):
        """Send an email to this lead from your connected Gmail and record it."""
        business = get_business_or_404(business_id)
        payload = json_body(ns)
        if not all(isinstance(payload.get(k) or "", str) for k in ("to", "subject", "body")):
            ns.abort(400, "to, subject and body must be strings")
        if not mailer.load_settings(current_app.config):
            ns.abort(400, "Connect your Gmail in Settings first")
        try:
            mailer.email_business(current_app.config, business, payload)
        except mailer.MailError as exc:
            db.session.rollback()
            ns.abort(502 if isinstance(exc, mailer.GmailError) else 400, str(exc))
        db.session.commit()
        return business, 201


@ns.route("/<int:business_id>/calls/<int:call_id>")
@ns.response(404, "Business or call not found")
class BusinessCallItem(Resource):
    @ns.marshal_with(business_detail_model)
    def delete(self, business_id, call_id):
        """Delete a logged call. If it set the current status, the status goes back to the previous one."""
        business = get_business_or_404(business_id)
        call = db.session.get(CallLog, call_id)
        if call is None or call.business_id != business.id:
            ns.abort(404, f"Call {call_id} not found for business {business_id}")
        delete_call(business, call)
        db.session.commit()
        return business


@ns.route("/<int:business_id>/socials")
@ns.response(404, "Business not found")
class BusinessSocials(Resource):
    @ns.expect(social_create_model)
    @ns.response(400, "Not a Facebook, Instagram or TikTok profile link")
    @ns.marshal_with(business_detail_model, code=201)
    def post(self, business_id):
        """Add a social media account by hand."""
        business = get_business_or_404(business_id)
        try:
            socials.add_manual_profile(business, json_body(ns).get("url"))
        except ValueError as exc:
            ns.abort(400, str(exc))
        db.session.commit()
        return business, 201


@ns.route("/<int:business_id>/socials/find")
@ns.response(404, "Business not found")
class BusinessSocialsFind(Resource):
    @ns.marshal_with(social_find_result_model)
    def post(self, business_id):
        """Look up social accounts now, from the Google Maps link and the business's website."""
        business = get_business_or_404(business_id)
        added, error = socials.find_for_business(business, current_app.config)
        db.session.commit()
        return {"added": added, "error": error, "business": business}


@ns.route("/<int:business_id>/socials/<int:profile_id>")
@ns.response(404, "Business or account not found")
class BusinessSocialItem(Resource):
    @ns.marshal_with(business_detail_model)
    def delete(self, business_id, profile_id):
        """Remove a social account that is wrong or no longer used."""
        business = get_business_or_404(business_id)
        profile = db.session.get(SocialProfile, profile_id)
        if profile is None or profile.business_id != business.id:
            ns.abort(404, f"Account {profile_id} not found for business {business_id}")
        business.social_profiles.remove(profile)
        db.session.commit()
        return business
