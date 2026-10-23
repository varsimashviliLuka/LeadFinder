"""Google review NFC cards: who needs one, and the link to write onto it."""

import io
import re
from datetime import date, timedelta

import segno
from sqlalchemy import and_, or_

from app.models import Business

FEW_REVIEWS = 50
LOW_RATING = 4.3
STALE_REVIEW_DAYS = 90

GOOGLE_PLACE_ID_RE = re.compile(r"^ChIJ[\w-]{10,}$")
WRITE_REVIEW_URL = "https://search.google.com/local/writereview?placeid={}"


def prospect_reasons(business, today=None):
    """Plain-language reasons this business would benefit from more Google reviews."""
    today = today or date.today()
    reasons = []
    if not business.review_count:
        reasons.append("No Google reviews yet")
    elif business.review_count < FEW_REVIEWS:
        reasons.append(f"Only {business.review_count} Google reviews")
    if business.rating is not None and business.rating < LOW_RATING:
        reasons.append(f"Rating {business.rating:g}: more happy-customer reviews would lift it")
    if business.latest_review_date and (today - business.latest_review_date).days > STALE_REVIEW_DAYS:
        months = round((today - business.latest_review_date).days / 30)
        reasons.append(f"No new review in about {months} months")
    return reasons


def prospect_condition(today=None):
    """SQL version of prospect_reasons(...) being non-empty."""
    today = today or date.today()
    return or_(
        Business.review_count.is_(None),
        Business.review_count < FEW_REVIEWS,
        Business.rating < LOW_RATING,
        Business.latest_review_date < today - timedelta(days=STALE_REVIEW_DAYS),
    )


def not_prospect_condition(today=None):
    """SQL for 'already gets plenty of reviews'; missing rating/dates don't count against it."""
    today = today or date.today()
    return and_(
        Business.review_count >= FEW_REVIEWS,
        or_(Business.rating.is_(None), Business.rating >= LOW_RATING),
        or_(
            Business.latest_review_date.is_(None),
            Business.latest_review_date >= today - timedelta(days=STALE_REVIEW_DAYS),
        ),
    )


def review_url(business):
    """The link that opens Google's 'write a review' box for this business, or None."""
    if business.place_id and GOOGLE_PLACE_ID_RE.match(business.place_id):
        return WRITE_REVIEW_URL.format(business.place_id)
    return None


def qr_code(url, kind="svg", inline=False):
    """QR code image bytes (svg or png) for a URL. inline=True: scalable svg to embed in a page."""
    qr = segno.make(url, error="m")
    buffer = io.BytesIO()
    if kind == "svg":
        qr.save(buffer, kind="svg", scale=8, border=2, xmldecl=False, omitsize=inline)
    else:
        qr.save(buffer, kind=kind, scale=10, border=2)
    return buffer.getvalue()
