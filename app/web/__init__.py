import socket

from flask import Blueprint, abort, current_app, render_template, request

from app.extensions import db
from app.models import Business, LeadStatus, SearchJobStatus, ServiceStatus, Trip
from app.services import nfc
from app.web.access import is_local_request, login_view, logout_view, remote_access_ready

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

SERVICE_STATUS_DISPLAY = {
    ServiceStatus.OFFERED: ("Offered", "info", "bi-megaphone", "You told them about it"),
    ServiceStatus.INTERESTED: ("Interested", "primary", "bi-hand-thumbs-up", "They want it or want to think about it"),
    ServiceStatus.SOLD: ("Sold", "success", "bi-bag-check", "They bought it"),
    ServiceStatus.DECLINED: ("Declined", "danger", "bi-x-circle", "They said no to this service"),
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
            "serviceStatuses": _display(SERVICE_STATUS_DISPLAY),
        },
        "suggested_categories": SUGGESTED_CATEGORIES,
        "signed_in_remotely": not is_local_request(),
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


def _lan_address():
    # Connecting a UDP socket sends nothing; it only picks the outgoing interface.
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
        except OSError:
            return None


def phone_access_info():
    bind = request.environ.get("SERVER_NAME", "")
    port = request.environ.get("SERVER_PORT", "5000")
    address = _lan_address()
    url = f"http://{address}:{port}" if address else None
    return {
        "listening": bind not in ("127.0.0.1", "localhost", "::1"),
        "port": port,
        "url": url,
        "qr": nfc.qr_code(url, "svg", inline=True).decode() if url else None,
        "ready": remote_access_ready(current_app.config),
        "password_set": bool(current_app.config.get("APP_PASSWORD")),
    }


@web_bp.route("/settings")
def settings():
    return render_template("settings.html", active="settings", phone=phone_access_info())


@web_bp.route("/trips")
def trips():
    return render_template("trips.html", active="trips")


@web_bp.route("/trips/<int:trip_id>")
def trip_detail(trip_id):
    trip = db.session.get(Trip, trip_id)
    if trip is None:
        abort(404)
    return render_template("trip_detail.html", active="trips", trip=trip)


@web_bp.route("/login", methods=["GET", "POST"])
def login():
    return login_view()


@web_bp.route("/logout", methods=["POST"])
def logout():
    return logout_view()


@web_bp.route("/businesses/<int:business_id>")
def business_detail(business_id):
    business = db.session.get(Business, business_id)
    if business is None:
        abort(404)
    return render_template("business_detail.html", active="leads", business=business)
