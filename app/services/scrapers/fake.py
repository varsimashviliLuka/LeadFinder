import math
import random
import time

from app.services import nfc, search_area
from app.services.scrapers.base import BaseScraper

FAKE_RESULT_COUNT = 15
STREETS = ["Rustaveli Ave", "Chavchavadze Ave", "Pekini St", "Kostava St", "Aghmashenebeli Ave"]


class FakeScraper(BaseScraper):
    """Deterministic stand-in data for developing without hitting Google Maps."""

    name = "fake"

    def search(self, params, should_stop):
        rng = random.Random(f"{params.query}:{params.latitude:.4f}:{params.longitude:.4f}")
        delay = self.config.get("FAKE_SCRAPER_DELAY", 0)
        filtering = params.max_rating is not None or params.max_reviews is not None
        # When NFC caps are on, open up to FAKE_RESULT_COUNT places and only count matches.
        limit = FAKE_RESULT_COUNT if filtering else min(params.max_results, FAKE_RESULT_COUNT)
        yielded = 0

        for i in range(limit):
            if should_stop():
                return
            if delay:
                time.sleep(delay)

            if params.area_shape in ("rectangle", "polygon") and None not in (
                params.south, params.west, params.north, params.east
            ):
                lat = rng.uniform(params.south, params.north)
                lng = rng.uniform(params.west, params.east)
            else:
                distance = rng.uniform(0, params.radius_m)
                bearing = rng.uniform(0, 2 * math.pi)
                lat = params.latitude + (distance * math.cos(bearing)) / 111_320
                lng = params.longitude + (distance * math.sin(bearing)) / (
                    111_320 * math.cos(math.radians(params.latitude))
                )
            has_website = rng.random() < 0.6
            business = {
                "place_id": f"fake:{params.query}:{params.latitude:.4f}:{params.longitude:.4f}:{i}",
                "name": f"{params.query.title()} #{i + 1}",
                "category": params.query.title(),
                "address": f"{rng.randint(1, 120)} {rng.choice(STREETS)}, Tbilisi",
                "latitude": round(lat, 6),
                "longitude": round(lng, 6),
                "phone": f"+995 5{rng.randint(10, 99)} {rng.randint(10, 99)} {rng.randint(10, 99)} {rng.randint(10, 99)}"
                if rng.random() < 0.85
                else None,
                "website": f"https://{params.query.lower().replace(' ', '-')}-{i + 1}.example"
                if has_website
                else None,
                "rating": round(rng.uniform(3.2, 5.0), 1),
                "review_count": rng.randint(3, 400),
                "maps_url": None,
            }
            if not search_area.contains(
                business["latitude"],
                business["longitude"],
                shape=params.area_shape,
                latitude=params.latitude,
                longitude=params.longitude,
                radius_m=params.radius_m,
                south=params.south,
                west=params.west,
                north=params.north,
                east=params.east,
                polygon=params.polygon,
            ):
                continue
            if not nfc.matches_review_limits(
                business["rating"], business["review_count"], params.max_rating, params.max_reviews
            ):
                continue
            yield business
            yielded += 1
            if yielded >= params.max_results:
                return
