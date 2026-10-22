from dataclasses import dataclass


@dataclass
class SearchParams:
    query: str
    latitude: float
    longitude: float
    radius_m: int
    max_results: int
    language: str = "ka"
    collect_reviews: bool = False


class BaseScraper:
    """A source of businesses near a location.

    search() yields dicts with the keys accepted by upsert_business
    (place_id and name are required). It should check should_stop()
    between slow steps and return early when it is True.
    """

    name = "base"

    def __init__(self, config):
        self.config = config
        # Plain-language note on why a search ended early, shown when it found nothing.
        self.stop_reason = None

    def search(self, params, should_stop):
        raise NotImplementedError
