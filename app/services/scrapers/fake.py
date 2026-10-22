import math
import random
import time

from app.services.scrapers.base import BaseScraper

FAKE_RESULT_COUNT = 15
STREETS = ["Rustaveli Ave", "Chavchavadze Ave", "Pekini St", "Kostava St", "Aghmashenebeli Ave"]


class FakeScraper(BaseScraper):
    """Deterministic stand-in data for developing without hitting Google Maps."""

    name = "fake"

    def search(self, params, should_stop):
        rng = random.Random(f"{params.query}:{params.latitude:.4f}:{params.longitude:.4f}")
        delay = self.config.get("FAKE_SCRAPER_DELAY", 0)

        for i in range(min(params.max_results, FAKE_RESULT_COUNT)):
            if should_stop():
                return
            if delay:
                time.sleep(delay)

            distance = rng.uniform(0, params.radius_m)
            bearing = rng.uniform(0, 2 * math.pi)
            lat = params.latitude + (distance * math.cos(bearing)) / 111_320
            lng = params.longitude + (distance * math.sin(bearing)) / (
                111_320 * math.cos(math.radians(params.latitude))
            )
            has_website = rng.random() < 0.6

            yield {
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
