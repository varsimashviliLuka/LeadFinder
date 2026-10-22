from datetime import date

import pytest

from app.services.scrapers.google_maps import (
    build_business,
    distance_m,
    normalize_phone,
    parse_place_link,
    parse_rating,
    strip_label,
    zoom_for_radius,
)
from app.services.scrapers.pacing import ScraperState

HREF = (
    "https://www.google.com/maps/place/Minimalist/data=!4m7!3m6!1s0x404473c67f10fe27:0xe8095e15f442cf38"
    "!8m2!3d41.7097969!4d44.7547726!16s%2Fg%2F11z4ysv1pr!19sChIJJ_4Qf8ZzREAROM9C9BVeCeg"
    "?authuser=0&hl=ka&rclk=1"
)


def test_parse_place_link():
    link = parse_place_link(HREF)
    assert link["place_id"] == "ChIJJ_4Qf8ZzREAROM9C9BVeCeg"
    assert (link["latitude"], link["longitude"]) == (41.7097969, 44.7547726)
    assert "?" not in link["maps_url"]


def test_parse_place_link_falls_back_to_feature_id():
    href = "https://www.google.com/maps/place/X/data=!3m1!1s0x40440db929e061f5:0xa97eb0a393f0c382!3d41.7!4d44.8"
    assert parse_place_link(href)["place_id"] == "0x40440db929e061f5:0xa97eb0a393f0c382"
    assert parse_place_link("https://www.google.com/maps/@41.7,44.8,15z") is None
    assert parse_place_link(None) is None


@pytest.mark.parametrize(
    "text, labels, expected",
    [
        ("4,8\n(2 617)", [], (4.8, 2617)),
        ("4.9\n(212)", [], (4.9, 212)),
        ("5,0\n(1)", [], (5.0, 1)),
        ("4.5\n(2.6K)", ["4.5 stars", "2,612 reviews"], (4.5, 2612)),
        (None, [], (None, None)),
        ("", [], (None, None)),
    ],
)
def test_parse_rating(text, labels, expected):
    assert parse_rating(text, labels) == expected


def test_strip_label():
    assert strip_label("მისამართი: 7 დოქის შესახვევი, თბილისი 0102 ") == "7 დოქის შესახვევი, თბილისი 0102"
    assert strip_label("Address: 1 Main St") == "1 Main St"
    assert strip_label("No prefix") == "No prefix"
    assert strip_label(None) is None


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("568811857", "+995 568 81 18 57"),
        ("322123456", "+995 32 212 34 56"),
        ("+995591545460", "+995 591 54 54 60"),
        ("12", "12"),
        (None, None),
    ],
)
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw, "GE") == expected


def test_distance_and_zoom():
    assert distance_m(41.7099, 44.7556, 41.7099, 44.7556) == 0
    assert 1100 < distance_m(41.7099, 44.7556, 41.7199, 44.7556) < 1120
    assert zoom_for_radius(2000, 41.7) == 14
    assert zoom_for_radius(200, 41.7) == 18
    assert zoom_for_radius(50_000, 41.7) == 11


def test_build_business():
    details = {
        "name": "Dental Clinic - Dental care",
        "category": "სტომატოლოგიური კლინიკა",
        "address": "მისამართი: ვაჟა-ფშაველას78ა, თბილისი 0186 ",
        "phone": "591545460",
        "website": "https://dentalcare.ge/",
        "rating_text": "4,9\n(212)",
        "rating_labels": [],
        "hours": [["ორშაბათი", "10AM-7PM"], ["კვირა", "დაკეტილია"]],
        "unclaimed": False,
    }
    business = build_business(details, parse_place_link(HREF), "GE")
    assert business["phone"] == "+995 591 54 54 60"
    assert business["address"] == "ვაჟა-ფშაველას78ა, თბილისი 0186"
    assert business["rating"] == 4.9 and business["review_count"] == 212
    assert business["opening_hours"] == {"ორშაბათი": "10AM-7PM", "კვირა": "დაკეტილია"}
    assert business["claimed"] is True
    assert build_business({**details, "unclaimed": True, "hours": []}, parse_place_link(HREF), "GE")[
        "opening_hours"
    ] is None


def test_scraper_state(tmp_path):
    state = ScraperState(str(tmp_path / "state.json"))
    assert state.blocked_until() is None
    assert state.seconds_until_next_search(90) == 0
    assert state.places_today() == 0

    state.record_search_started()
    assert 85 < state.seconds_until_next_search(90) <= 90

    state.add_place()
    state.add_place()
    assert state.places_today() == 2

    assert state.mark_blocked(1) == state.blocked_until()
    state.clear_block()
    assert state.blocked_until() is None


def test_scraper_state_resets_daily_count(tmp_path):
    path = tmp_path / "state.json"
    path.write_text('{"daily": {"date": "2000-01-01", "places": 250}}')
    state = ScraperState(str(path))
    assert state.places_today() == 0
    state.add_place()
    assert state._load()["daily"] == {"date": date.today().isoformat(), "places": 1}


def test_missing_browser_fails_fast_without_cooldown(app, monkeypatch):
    from playwright.sync_api import Error as PlaywrightError

    from app.services.scrapers import SearchParams
    from app.services.scrapers import google_maps

    class FakeChromium:
        def launch_persistent_context(self, *args, **kwargs):
            raise PlaywrightError("BrowserType.launch_persistent_context: Executable doesn't exist at /x/chrome")

    class FakePlaywright:
        chromium = FakeChromium()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(google_maps, "sync_playwright", lambda: FakePlaywright())
    scraper = google_maps.GoogleMapsScraper(app.config)
    params = SearchParams(query="cafe", latitude=41.7, longitude=44.8, radius_m=1000, max_results=5, language="ka")

    with pytest.raises(RuntimeError, match="playwright install chromium"):
        list(scraper.search(params, lambda: False))
    state = ScraperState(app.config["SCRAPER_STATE_FILE"])
    assert state.seconds_until_next_search(app.config["SCRAPER_SEARCH_COOLDOWN"]) == 0


def test_viewport_offset_from_maps_url():
    from types import SimpleNamespace

    from app.services.scrapers import SearchParams
    from app.services.scrapers.google_maps import GoogleMapsScraper, format_distance

    params = SearchParams(query="x", latitude=41.72722, longitude=44.76381, radius_m=1000, max_results=5)
    page = SimpleNamespace(url="https://www.google.com/maps/search/beauty+salon/@41.72505,44.7353,16z?hl=ka")
    assert 2300 < GoogleMapsScraper._viewport_offset(page, params) < 2450
    assert GoogleMapsScraper._viewport_offset(SimpleNamespace(url="https://www.google.com/maps"), params) is None
    assert (format_distance(1000), format_distance(450)) == ("1.0 km", "450 m")
