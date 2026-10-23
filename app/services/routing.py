"""Travel times between stops and the fastest order to visit them.

Uses the public OSRM servers run by FOSSGIS (routing.openstreetmap.de, OpenStreetMap
data, separate walking and driving profiles). If they can't be reached, falls back to
straight-line estimates so a trip can still be planned.
"""

import itertools
import logging
import math

import httpx

from app.models import TravelMode

logger = logging.getLogger(__name__)

OSRM_PROFILES = {TravelMode.FOOT: "routed-foot", TravelMode.CAR: "routed-car"}
# Straight-line fallback: typical speed and how much longer real streets are than a straight line.
FALLBACK_SPEED_MPS = {TravelMode.FOOT: 1.3, TravelMode.CAR: 7.0}
FALLBACK_DETOUR = {TravelMode.FOOT: 1.3, TravelMode.CAR: 1.5}
EXACT_LIMIT = 10  # stops up to which every order is checked (Held-Karp)


class RoutingError(Exception):
    pass


def haversine_m(a, b):
    lat1, lng1, lat2, lng2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(h))


def straight_line(a, b, mode):
    distance = haversine_m(a, b) * FALLBACK_DETOUR[mode]
    return distance / FALLBACK_SPEED_MPS[mode], distance


class Router:
    """points are (lat, lng) tuples."""

    def __init__(self, config):
        self.provider = config["ROUTING_PROVIDER"]
        self.base_url = config["ROUTING_URL"].rstrip("/")
        self.timeout = config["ROUTING_TIMEOUT"]
        self.user_agent = config["GEOCODER_USER_AGENT"]

    def _get(self, mode, service, points, params):
        coords = ";".join(f"{lng:.6f},{lat:.6f}" for lat, lng in points)
        url = f"{self.base_url}/{OSRM_PROFILES[mode]}/{service}/v1/driving/{coords}"
        try:
            response = httpx.get(url, params=params, timeout=self.timeout, headers={"User-Agent": self.user_agent})
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RoutingError(f"Routing server unavailable: {exc}") from None
        if data.get("code") != "Ok":
            raise RoutingError(f"Routing server couldn't route these stops: {data.get('message') or data.get('code')}")
        return data

    def matrix(self, points, mode):
        """(durations, distances, estimated): n×n seconds and metres from each stop to each other."""
        n = len(points)
        fallback = [[straight_line(points[i], points[j], mode) for j in range(n)] for i in range(n)]
        if self.provider == "osrm":
            try:
                data = self._get(mode, "table", points, {"annotations": "duration,distance"})
                durations = [
                    [d if d is not None else fallback[i][j][0] for j, d in enumerate(row)]
                    for i, row in enumerate(data["durations"])
                ]
                distances = [
                    [d if d is not None else fallback[i][j][1] for j, d in enumerate(row)]
                    for i, row in enumerate(data["distances"])
                ]
                return durations, distances, False
            except RoutingError as exc:
                logger.warning("%s; using straight-line estimates", exc)
        return [[c[0] for c in row] for row in fallback], [[c[1] for c in row] for row in fallback], True

    def route(self, points, mode):
        """The street route through points in order: legs [(seconds, metres)], geometry [[lat, lng]], estimated."""
        if self.provider == "osrm" and len(points) > 1:
            try:
                data = self._get(mode, "route", points, {"overview": "full", "geometries": "geojson", "steps": "false"})
                route = data["routes"][0]
                legs = [(leg["duration"], leg["distance"]) for leg in route["legs"]]
                geometry = [[lat, lng] for lng, lat in route["geometry"]["coordinates"]]
                return legs, geometry, False
            except (RoutingError, KeyError, IndexError) as exc:
                logger.warning("%s; using straight-line estimates", exc)
        legs = [straight_line(a, b, mode) for a, b in zip(points, points[1:])]
        return legs, [list(p) for p in points], True


def path_cost(order, cost):
    return sum(cost[a][b] for a, b in zip(order, order[1:]))


def _exact(cost):
    """Held-Karp for an open path with any start and end."""
    n = len(cost)
    best = {(1 << j, j): (0.0, None) for j in range(n)}
    for size in range(2, n + 1):
        for subset in itertools.combinations(range(n), size):
            mask = sum(1 << j for j in subset)
            for j in subset:
                prev_mask = mask & ~(1 << j)
                best[(mask, j)] = min(
                    (best[(prev_mask, k)][0] + cost[k][j], k) for k in subset if k != j
                )
    full = (1 << n) - 1
    end = min(range(n), key=lambda j: best[(full, j)][0])
    order, mask = [], full
    while end is not None:
        order.append(end)
        end, mask = best[(mask, end)][1], mask & ~(1 << end)
    return order[::-1]


def _nearest_neighbour(start, cost):
    order, left = [start], set(range(len(cost))) - {start}
    while left:
        nxt = min(left, key=lambda j: cost[order[-1]][j])
        order.append(nxt)
        left.remove(nxt)
    return order


def _improve(order, cost):
    """2-opt reversals and moving short runs of stops, until nothing gets faster."""
    best, best_cost = order, path_cost(order, cost)
    improved = True
    while improved:
        improved = False
        n = len(best)
        for i in range(n - 1):
            for j in range(i + 1, n):
                candidate = best[:i] + best[i:j + 1][::-1] + best[j + 1:]
                c = path_cost(candidate, cost)
                if c < best_cost - 1e-6:
                    best, best_cost, improved = candidate, c, True
        for length in (1, 2, 3):
            for i in range(n - length + 1):
                run, rest = best[i:i + length], best[:i] + best[i + length:]
                for k in range(len(rest) + 1):
                    candidate = rest[:k] + run + rest[k:]
                    c = path_cost(candidate, cost)
                    if c < best_cost - 1e-6:
                        best, best_cost, improved = candidate, c, True
    return best


def best_order(cost):
    """Fastest order to visit every stop once, starting and ending wherever is best."""
    n = len(cost)
    if n <= 2:
        return list(range(n)) if n < 2 or cost[0][1] <= cost[1][0] else [1, 0]
    if n <= EXACT_LIMIT:
        return _exact(cost)
    starts = sorted(range(n), key=lambda s: path_cost(_nearest_neighbour(s, cost), cost))[:6]
    return min((_improve(_nearest_neighbour(s, cost), cost) for s in starts), key=lambda o: path_cost(o, cost))
