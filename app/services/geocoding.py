import logging
from dataclasses import asdict, dataclass

import httpx
from flask import current_app

logger = logging.getLogger(__name__)


class GeocodingError(Exception):
    pass


@dataclass
class Location:
    latitude: float
    longitude: float
    display_name: str

    def to_dict(self):
        return asdict(self)


def _request(path, params):
    config = current_app.config
    params = {"format": "jsonv2", "accept-language": config["GEOCODER_LANGUAGE"], **params}
    try:
        response = httpx.get(
            f"{config['GEOCODER_URL'].rstrip('/')}/{path}",
            params=params,
            headers={"User-Agent": config["GEOCODER_USER_AGENT"]},
            timeout=config["GEOCODER_TIMEOUT"],
        )
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Geocoding request to %s failed: %s", path, exc)
        raise GeocodingError(f"Geocoding service unavailable: {exc}") from exc


def _to_location(item):
    return Location(
        latitude=float(item["lat"]),
        longitude=float(item["lon"]),
        display_name=item.get("display_name", ""),
    )


def search(query, limit=5):
    """Address or place name -> candidate locations, best match first."""
    params = {"q": query, "limit": limit}
    country_codes = current_app.config["GEOCODER_COUNTRY_CODES"]
    if country_codes:
        params["countrycodes"] = country_codes
    return [_to_location(item) for item in _request("search", params)]


def reverse(latitude, longitude):
    """Coordinates -> nearest address, or None if nothing is there."""
    data = _request("reverse", {"lat": latitude, "lon": longitude})
    if not data or "error" in data:
        return None
    return _to_location(data)
