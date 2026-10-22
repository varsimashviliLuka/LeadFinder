from flask import Blueprint, abort, render_template

from app.extensions import db
from app.models import Business, LeadStatus, SearchJobStatus

web_bp = Blueprint(
    "web",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/static/web",
)

# value: (label, bootstrap color, icon, what it means)
LEAD_STATUS_DISPLAY = {
    LeadStatus.NEW: ("New", "secondary", "bi-stars", "Not contacted yet"),
    LeadStatus.NO_ANSWER: ("No answer", "warning", "bi-telephone-x", "You called, nobody picked up"),
    LeadStatus.CALL_BACK: ("Call back", "info", "bi-clock-history", "They asked you to call again later"),
    LeadStatus.INTERESTED: ("Interested", "primary", "bi-hand-thumbs-up", "They want to hear your offer"),
    LeadStatus.NOT_INTERESTED: ("Not interested", "danger", "bi-hand-thumbs-down", "They said no"),
    LeadStatus.CLIENT: ("Client", "success", "bi-trophy", "They became a customer"),
}

SEARCH_STATUS_DISPLAY = {
    SearchJobStatus.PENDING: ("Waiting", "secondary", "bi-hourglass-split", "Waiting for the previous search to finish"),
    SearchJobStatus.RUNNING: ("Searching", "primary", "bi-search", "The browser window is collecting businesses"),
    SearchJobStatus.COMPLETED: ("Done", "success", "bi-check-circle", "Finished; all results are saved"),
    SearchJobStatus.FAILED: ("Failed", "danger", "bi-exclamation-triangle", "Stopped because of a problem"),
    SearchJobStatus.CANCELLED: ("Stopped", "dark", "bi-stop-circle", "Stopped early; results so far are saved"),
}

SUGGESTED_CATEGORIES = [
    "restaurant",
    "cafe",
    "beauty salon",
    "barber shop",
    "nail salon",
    "dental clinic",
    "gym",
    "bakery",
    "clothing store",
    "flower shop",
    "hotel",
    "car service",
    "real estate agency",
    "pet shop",
]


def _display(mapping):
    return [
        {"value": value, "label": label, "color": color, "icon": icon, "help": help_text}
        for value, (label, color, icon, help_text) in mapping.items()
    ]


@web_bp.app_context_processor
def inject_app_data():
    return {
        "app_data": {
            "statuses": _display(LEAD_STATUS_DISPLAY),
            "searchStatuses": _display(SEARCH_STATUS_DISPLAY),
            "callOutcomes": list(LeadStatus.CALL_OUTCOMES),
        },
        "suggested_categories": SUGGESTED_CATEGORIES,
    }


@web_bp.route("/")
def dashboard():
    return render_template("dashboard.html", active="search")


@web_bp.route("/businesses")
def businesses():
    return render_template("businesses.html", active="leads")


@web_bp.route("/templates")
def templates():
    return render_template("templates.html", active="templates")


@web_bp.route("/settings")
def settings():
    return render_template("settings.html", active="settings")


@web_bp.route("/businesses/<int:business_id>")
def business_detail(business_id):
    business = db.session.get(Business, business_id)
    if business is None:
        abort(404)
    return render_template("business_detail.html", active="leads", business=business)
