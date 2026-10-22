from flask import Blueprint
from flask_restx import Api

from app.api.businesses import ns as businesses_ns
from app.api.geocoding import ns as geocoding_ns
from app.api.health import ns as health_ns
from app.api.mail import ns as mail_ns
from app.api.searches import ns as searches_ns
from app.api.templates import ns as templates_ns

api_bp = Blueprint("api", __name__, url_prefix="/api")

api = Api(
    api_bp,
    title="Business Scraper API",
    version="1.0",
    description="Find local businesses on Google Maps and manage them as leads.",
    doc="/docs",
)

api.add_namespace(health_ns)
api.add_namespace(businesses_ns)
api.add_namespace(searches_ns)
api.add_namespace(geocoding_ns)
api.add_namespace(templates_ns)
api.add_namespace(mail_ns)
