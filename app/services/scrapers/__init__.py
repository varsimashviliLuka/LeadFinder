from app.services.scrapers.base import BaseScraper, SearchParams
from app.services.scrapers.fake import FakeScraper
from app.services.scrapers.google_maps import GoogleMapsScraper

SCRAPERS = {
    FakeScraper.name: FakeScraper,
    GoogleMapsScraper.name: GoogleMapsScraper,
}


def get_scraper(name, config):
    try:
        scraper_class = SCRAPERS[name]
    except KeyError:
        raise ValueError(f"Unknown scraper provider {name!r}; available: {', '.join(SCRAPERS)}") from None
    return scraper_class(config)


__all__ = ["BaseScraper", "SearchParams", "get_scraper"]
