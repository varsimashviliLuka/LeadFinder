import csv
import io
import re
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.models import (
    Business,
    CallLog,
    ContactKind,
    LeadStatus,
    SearchJob,
    ServiceStatus,
    SocialPlatform,
    SocialProfile,
    StopStatus,
    TripStop,
)
from app.models.common import utcnow
from app.services import nfc
from app.services.website_info import website_issues

SCRAPED_FIELDS = (
    "name",
    "category",
    "address",
    "latitude",
    "longitude",
    "phone",
    "website",
    "rating",
    "review_count",
    "opening_hours",
    "maps_url",
    "claimed",
    "price_level",
    "latest_review_date",
    "recent_reviews_checked",
    "recent_owner_replies",
)

EDITABLE_FIELDS = ("lead_status", "notes", "follow_up_date", "email", "phone", "website", "whatsapp")

SORTABLE_FIELDS = {
    "created_at": Business.created_at,
    "name": Business.name,
    "rating": Business.rating,
    "review_count": Business.review_count,
    "last_contacted_at": Business.last_contacted_at,
    "follow_up_date": Business.follow_up_date,
}

# any: has an account; none: checked, nothing found; unchecked: never looked up;
# needs_check: never looked up, or has a website whose quality was never checked.
SOCIAL_FILTERS = ("any", "none", "unchecked", "needs_check", *SocialPlatform.ALL)
NEEDS_ONLINE_CHECK = or_(
    Business.social_checked_at.is_(None) & ~Business.social_profiles.any(),
    Business.website.isnot(None) & Business.website_check.is_(None),
)


def needs_online_check(business):
    if business.social_checked_at is None and not business.social_profiles:
        return True
    return bool(business.website) and business.website_check is None


def upsert_business(data, search_job=None):
    """Create or refresh a business by its Google place_id.

    Scraped fields are only overwritten with non-empty values, and lead
    fields (status, notes, follow-up) are never touched. Caller commits.
    Returns (business, created).
    """
    place_id = data.get("place_id")
    if not place_id:
        raise ValueError("place_id is required")

    business = db.session.scalar(select(Business).filter_by(place_id=place_id))
    created = business is None
    if created:
        if not data.get("name"):
            raise ValueError("name is required for new businesses")
        business = Business(place_id=place_id)
        db.session.add(business)

    for field in SCRAPED_FIELDS:
        value = data.get(field)
        if value not in (None, ""):
            setattr(business, field, value)

    if search_job is not None and search_job not in business.search_jobs:
        business.search_jobs.append(search_job)

    return business, created


def update_business(business, payload):
    """Apply user edits from the dashboard. Raises ValueError on bad input."""
    unknown = set(payload) - set(EDITABLE_FIELDS) - set(SERVICE_FIELDS)
    if unknown:
        raise ValueError(f"Fields not editable: {', '.join(sorted(unknown))}")

    set_services(business, payload)
    for key, value in payload.items():
        if key in SERVICE_FIELDS:
            continue
        if key == "lead_status":
            if value not in LeadStatus.ALL:
                raise ValueError(f"lead_status must be one of: {', '.join(LeadStatus.ALL)}")
        elif key == "follow_up_date":
            if value:
                try:
                    value = date.fromisoformat(value)
                except (TypeError, ValueError):
                    raise ValueError("follow_up_date must be YYYY-MM-DD") from None
            else:
                value = None
        else:
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{key} must be a string")
            value = (value.strip() or None) if value else None
            if key == "website" and value != business.website:
                business.social_checked_at = None
                business.website_check = None
                business.website_issue_count = None
        setattr(business, key, value)

    return business


SERVICE_FIELDS = ("service_content", "service_nfc")


def set_services(business, payload):
    """Apply service_content / service_nfc from payload if present (null = not offered). Raises ValueError."""
    for field in SERVICE_FIELDS:
        if field not in payload:
            continue
        value = payload[field] or None
        if value is not None and value not in ServiceStatus.ALL:
            raise ValueError(f"{field} must be one of: {', '.join(ServiceStatus.ALL)}, or null")
        setattr(business, field, value)


def log_call(business, outcome, note=None, kind=ContactKind.CALL):
    """Record a call or visit and move the lead to the outcome status. Caller commits."""
    if outcome not in LeadStatus.CALL_OUTCOMES:
        raise ValueError(f"outcome must be one of: {', '.join(LeadStatus.CALL_OUTCOMES)}")
    if kind not in ContactKind.ALL:
        raise ValueError(f"kind must be one of: {', '.join(ContactKind.ALL)}")

    now = utcnow()
    call = CallLog(business=business, kind=kind, outcome=outcome, note=(note or "").strip() or None, created_at=now)
    business.lead_status = outcome
    business.last_contacted_at = now
    db.session.add(call)
    return call


def delete_call(business, call):
    """Remove a logged call, undoing its effect on the lead. Caller commits.

    If the call set the current status (it was the latest and the status
    still matches), the status falls back to the previous call's outcome,
    or "new" when no calls remain.
    """
    remaining = [c for c in business.calls if c.id != call.id]
    was_latest = bool(business.calls) and business.calls[0].id == call.id
    if was_latest and business.lead_status == call.outcome:
        business.lead_status = remaining[0].outcome if remaining else LeadStatus.NEW
    business.last_contacted_at = remaining[0].created_at if remaining else None
    for stop in db.session.scalars(db.select(TripStop).where(TripStop.call_id == call.id)):
        stop.call = None
        stop.status = StopStatus.PENDING
        stop.visited_at = None
    business.calls.remove(call)


def build_business_query(
    q=None,
    status=None,
    category=None,
    has_phone=None,
    has_website=None,
    min_rating=None,
    has_email=None,
    website_quality=None,
    claimed=None,
    search_job_id=None,
    follow_up_due=None,
    social=None,
    nfc_prospect=None,
    service=None,
    sort="created_at",
    order="desc",
):
    stmt = select(Business).options(selectinload(Business.social_profiles))

    if q:
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Business.name.ilike(pattern),
                Business.address.ilike(pattern),
                Business.category.ilike(pattern),
                Business.phone.ilike(pattern),
            )
        )
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        stmt = stmt.where(Business.lead_status.in_(statuses))
    if category:
        stmt = stmt.where(Business.category.ilike(f"%{category.strip()}%"))
    if has_phone is not None:
        stmt = stmt.where(Business.phone.isnot(None) if has_phone else Business.phone.is_(None))
    if has_website is not None:
        stmt = stmt.where(Business.website.isnot(None) if has_website else Business.website.is_(None))
    if min_rating is not None:
        stmt = stmt.where(Business.rating >= min_rating)
    if has_email is not None:
        stmt = stmt.where(Business.email.isnot(None) if has_email else Business.email.is_(None))
    if website_quality == "problems":
        stmt = stmt.where(Business.website_issue_count > 0)
    elif website_quality == "ok":
        stmt = stmt.where(Business.website_issue_count == 0)
    if claimed is not None:
        stmt = stmt.where(Business.claimed.is_(claimed))
    if search_job_id is not None:
        stmt = stmt.where(Business.search_jobs.any(SearchJob.id == search_job_id))
    if follow_up_due:
        stmt = stmt.where(Business.follow_up_date <= date.today())
    if social == "any":
        stmt = stmt.where(Business.social_profiles.any())
    elif social == "none":
        stmt = stmt.where(Business.social_checked_at.isnot(None), ~Business.social_profiles.any())
    elif social == "unchecked":
        stmt = stmt.where(Business.social_checked_at.is_(None), ~Business.social_profiles.any())
    elif social == "needs_check":
        stmt = stmt.where(NEEDS_ONLINE_CHECK)
    elif social in SocialPlatform.ALL:
        stmt = stmt.where(Business.social_profiles.any(SocialProfile.platform == social))
    if nfc_prospect is not None:
        stmt = stmt.where(nfc.prospect_condition() if nfc_prospect else nfc.not_prospect_condition())
    if service:
        field, value = parse_service_filter(service)
        column = getattr(Business, field)
        stmt = stmt.where(column.is_(None) if value == "none" else column == value)

    column = SORTABLE_FIELDS.get(sort, Business.created_at)
    ordering = column.asc() if order == "asc" else column.desc()
    return stmt.order_by(ordering.nulls_last(), Business.id.desc())


SERVICE_FILTERS = tuple(
    f"{name}:{value}" for name in ("content", "nfc") for value in (*ServiceStatus.ALL, "none")
)


def parse_service_filter(value):
    """'nfc:sold' -> ('service_nfc', 'sold'); 'content:none' -> ('service_content', 'none')."""
    if value not in SERVICE_FILTERS:
        raise ValueError(f"service must be one of: {', '.join(SERVICE_FILTERS)}")
    name, status = value.split(":")
    return f"service_{name}", status


CSV_COLUMNS = (
    "name",
    "category",
    "phone",
    "website",
    *SocialPlatform.ALL,
    "email",
    "whatsapp",
    "website_issues",
    "address",
    "rating",
    "review_count",
    "latest_review_date",
    "recent_owner_replies",
    "price_level",
    "claimed",
    "lead_status",
    "service_content",
    "service_nfc",
    "nfc_review_link",
    "follow_up_date",
    "last_contacted_at",
    "notes",
    "opening_hours",
    "maps_url",
    "latitude",
    "longitude",
    "created_at",
)


FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
PHONE_RE = re.compile(r"^\+?[\d\s()-]+$")


def _csv_safe(column, value):
    """Stop spreadsheet apps from executing scraped text as a formula."""
    if not isinstance(value, str) or not value.startswith(FORMULA_PREFIXES):
        return value
    if column == "phone" and PHONE_RE.match(value):
        return value
    return f"'{value}"


def businesses_to_csv(businesses):
    buffer = io.StringIO()
    # BOM so Excel detects UTF-8 and shows Georgian correctly.
    buffer.write("\ufeff")
    writer = csv.writer(buffer)
    writer.writerow(CSV_COLUMNS)
    for business in businesses:
        row = []
        for column in CSV_COLUMNS:
            if column in SocialPlatform.ALL:
                value = " ".join(p.url for p in business.social_profiles if p.platform == column) or None
            elif column == "website_issues":
                value = "; ".join(website_issues(business.website_check)) or None
            elif column == "nfc_review_link":
                value = nfc.review_url(business)
            elif column == "recent_owner_replies" and business.recent_reviews_checked:
                value = f"{business.recent_owner_replies} of {business.recent_reviews_checked}"
            else:
                value = getattr(business, column)
            if column == "opening_hours" and value:
                value = "; ".join(f"{day}: {hours}" for day, hours in value.items())
            elif column == "claimed" and value is not None:
                value = "yes" if value else "no"
            elif hasattr(value, "isoformat"):
                value = value.isoformat()
            row.append("" if value is None else _csv_safe(column, value))
        writer.writerow(row)
    return buffer.getvalue()


def business_stats():
    total = db.session.scalar(select(func.count(Business.id)))
    by_status = dict.fromkeys(LeadStatus.ALL, 0)
    rows = db.session.execute(select(Business.lead_status, func.count()).group_by(Business.lead_status))
    for lead_status, count in rows:
        by_status[lead_status] = count

    def count_where(condition):
        return db.session.scalar(select(func.count()).select_from(Business).where(condition))

    return {
        "total": total,
        "by_status": by_status,
        "with_phone": count_where(Business.phone.isnot(None)),
        "with_website": count_where(Business.website.isnot(None)),
        "unclaimed": count_where(Business.claimed.is_(False)),
        "with_social": count_where(Business.social_profiles.any()),
        "social_unchecked": count_where(Business.social_checked_at.is_(None) & ~Business.social_profiles.any()),
        "needs_check": count_where(NEEDS_ONLINE_CHECK),
        "with_email": count_where(Business.email.isnot(None)),
        "website_problems": count_where(Business.website_issue_count > 0),
        "nfc_prospects": count_where(nfc.prospect_condition()),
        "nfc_sold": count_where(Business.service_nfc == ServiceStatus.SOLD),
        "content_sold": count_where(Business.service_content == ServiceStatus.SOLD),
        "follow_ups_due": count_where(Business.follow_up_date <= date.today()),
    }
