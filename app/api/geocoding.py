from flask_restx import Namespace, Resource, fields, reqparse

from app.services import geocoding
from app.services.geocoding import GeocodingError

ns = Namespace("geocode", description="Address <-> coordinates lookup (OpenStreetMap Nominatim)")

location_model = ns.model(
    "Location",
    {
        "latitude": fields.Float,
        "longitude": fields.Float,
        "display_name": fields.String,
    },
)

search_parser = reqparse.RequestParser()
search_parser.add_argument("q", required=True, location="args", help="Address or place, e.g. 'Vake, Tbilisi'")
search_parser.add_argument("limit", type=int, default=5, location="args")

reverse_parser = reqparse.RequestParser()
reverse_parser.add_argument("lat", type=float, required=True, location="args")
reverse_parser.add_argument("lng", type=float, required=True, location="args")


@ns.route("")
@ns.response(502, "Geocoding service unavailable")
class GeocodeSearch(Resource):
    @ns.expect(search_parser)
    @ns.marshal_list_with(location_model)
    def get(self):
        args = search_parser.parse_args()
        if not args["q"].strip():
            ns.abort(400, "q must not be empty")
        try:
            matches = geocoding.search(args["q"].strip(), limit=min(max(args["limit"], 1), 10))
        except GeocodingError as exc:
            ns.abort(502, str(exc))
        return [m.to_dict() for m in matches]


@ns.route("/reverse")
@ns.response(404, "No address found at these coordinates")
@ns.response(502, "Geocoding service unavailable")
class GeocodeReverse(Resource):
    @ns.expect(reverse_parser)
    @ns.marshal_with(location_model)
    def get(self):
        args = reverse_parser.parse_args()
        if not (-90 <= args["lat"] <= 90 and -180 <= args["lng"] <= 180):
            ns.abort(400, "lat/lng out of range")
        try:
            match = geocoding.reverse(args["lat"], args["lng"])
        except GeocodingError as exc:
            ns.abort(502, str(exc))
        if match is None:
            ns.abort(404, "No address found at these coordinates")
        return match.to_dict()
