"""Circle, rectangle and freehand-polygon search areas for Google Maps jobs."""

import math

AREA_CIRCLE = "circle"
AREA_RECTANGLE = "rectangle"
AREA_POLYGON = "polygon"
AREA_SHAPES = (AREA_CIRCLE, AREA_RECTANGLE, AREA_POLYGON)

EARTH_RADIUS_M = 6_371_000
MIN_POLYGON_POINTS = 3
MAX_POLYGON_POINTS = 200


def distance_m(lat1, lng1, lat2, lng2):
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def covering_radius_m(south, west, north, east):
    """Radius from the box centre to a corner — enough to cover the whole rectangle."""
    center_lat = (south + north) / 2
    center_lng = (west + east) / 2
    return max(1, math.ceil(distance_m(center_lat, center_lng, north, east)))


def normalize_bounds(south, west, north, east):
    """Return (south, west, north, east) with corners ordered. Raises ValueError if degenerate."""
    if None in (south, west, north, east):
        raise ValueError("Rectangle bounds require south, west, north and east")
    for name, value, low, high in (
        ("south", south, -90, 90),
        ("north", north, -90, 90),
        ("west", west, -180, 180),
        ("east", east, -180, 180),
    ):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(f"{name} must be a number")
        if value < low or value > high:
            raise ValueError(f"{name} must be between {low} and {high}")
    lo_lat, hi_lat = sorted((float(south), float(north)))
    lo_lng, hi_lng = sorted((float(west), float(east)))
    if hi_lat - lo_lat < 1e-5 or hi_lng - lo_lng < 1e-5:
        raise ValueError("Rectangle is too small; drag a larger area on the map")
    return lo_lat, lo_lng, hi_lat, hi_lng


def _point_pair(raw):
    if isinstance(raw, (list, tuple)) and len(raw) >= 2:
        lat, lng = raw[0], raw[1]
    elif isinstance(raw, dict):
        lat, lng = raw.get("lat", raw.get("latitude")), raw.get("lng", raw.get("longitude"))
    else:
        raise ValueError("Each polygon point must be [lat, lng]")
    if isinstance(lat, bool) or isinstance(lng, bool) or not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
        raise ValueError("Polygon coordinates must be numbers")
    lat, lng = float(lat), float(lng)
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise ValueError("Polygon coordinates are out of range")
    return [lat, lng]


def normalize_polygon(raw):
    """Validate a freehand ring; return (ring, south, west, north, east).

    ring is a closed list of [lat, lng] (first point repeated at the end).
    """
    if not isinstance(raw, (list, tuple)) or len(raw) < MIN_POLYGON_POINTS:
        raise ValueError(f"Draw a shape with at least {MIN_POLYGON_POINTS} points")
    points = [_point_pair(p) for p in raw]
    # Drop consecutive duplicates.
    cleaned = [points[0]]
    for point in points[1:]:
        if point != cleaned[-1]:
            cleaned.append(point)
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1]:
        cleaned = cleaned[:-1]
    if len(cleaned) < MIN_POLYGON_POINTS:
        raise ValueError("Drawn shape is too small; right-click and drag a larger area")
    if len(cleaned) > MAX_POLYGON_POINTS:
        raise ValueError(f"Drawn shape has too many points (max {MAX_POLYGON_POINTS})")

    lats = [p[0] for p in cleaned]
    lngs = [p[1] for p in cleaned]
    south, north = min(lats), max(lats)
    west, east = min(lngs), max(lngs)
    if north - south < 1e-5 or east - west < 1e-5:
        raise ValueError("Drawn shape is too small; right-click and drag a larger area")

    ring = cleaned + [cleaned[0]]
    return ring, south, west, north, east


def point_in_polygon(lat, lng, ring):
    """Ray-casting; ring may be open or closed (first==last)."""
    if not ring or len(ring) < MIN_POLYGON_POINTS:
        return False
    pts = ring[:-1] if ring[0] == ring[-1] else ring
    inside = False
    j = len(pts) - 1
    for i, (lat_i, lng_i) in enumerate(pts):
        lat_j, lng_j = pts[j]
        if ((lng_i > lng) != (lng_j > lng)) and (
            lat < (lat_j - lat_i) * (lng - lng_i) / (lng_j - lng_i + 0.0) + lat_i
        ):
            inside = not inside
        j = i
    return inside


def contains(
    lat,
    lng,
    *,
    shape,
    latitude,
    longitude,
    radius_m,
    south=None,
    west=None,
    north=None,
    east=None,
    polygon=None,
):
    """True if the point is inside the search area. Missing coords are treated as inside."""
    if lat is None or lng is None:
        return True
    if shape == AREA_POLYGON:
        return point_in_polygon(lat, lng, polygon or [])
    if shape == AREA_RECTANGLE:
        return south <= lat <= north and west <= lng <= east
    return distance_m(latitude, longitude, lat, lng) <= radius_m


def area_description(shape, radius_m, south=None, west=None, north=None, east=None, polygon=None):
    """Short plain-language label for progress / empty-result messages."""
    if shape == AREA_POLYGON and polygon:
        return f"drawn area (~{_fmt(radius_m)} across)"
    if shape == AREA_RECTANGLE and None not in (south, west, north, east):
        height = distance_m(south, west, north, west)
        width = distance_m(south, west, south, east)
        return f"{_fmt(height)} × {_fmt(width)} rectangle"
    return f"{_fmt(radius_m)} circle"


def _fmt(meters):
    return f"{meters / 1000:.1f} km" if meters >= 1000 else f"{meters:.0f} m"
