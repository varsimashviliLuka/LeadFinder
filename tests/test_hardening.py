import threading
import time

import pytest

from app.extensions import db
from app.models import SearchJob
from app.services.scrapers.base import BaseScraper, SearchParams
from app.services.scrapers.google_maps import GoogleMapsScraper
from app.services.scrapers.pacing import ScraperBlockedError, ScraperLimitError, ScraperState
from app.workers import job_runner
from app.workers.runner import SHUTDOWN_MESSAGE

TBILISI = {"latitude": 41.7151, "longitude": 44.8271}


def params(**overrides):
    values = dict(query="cafe", radius_m=1000, max_results=10, **TBILISI)
    values.update(overrides)
    return SearchParams(**values)


def use_scraper(monkeypatch, scraper_class):
    monkeypatch.setattr("app.workers.runner.get_scraper", lambda name, config: scraper_class(config))


def test_scraper_cleanup_runs_when_max_results_reached(client, monkeypatch):
    cleaned_up = []

    class Endless(BaseScraper):
        def search(self, params, should_stop):
            try:
                i = 0
                while True:
                    yield {"place_id": f"p{i}", "name": f"Place {i}"}
                    i += 1
            finally:
                cleaned_up.append(True)

    use_scraper(monkeypatch, Endless)
    job = client.post("/api/searches", json={"query": "cafe", **TBILISI, "max_results": 3}).get_json()
    assert job["status"] == "completed"
    assert job["results_found"] == 3
    assert cleaned_up == [True]


def test_google_maps_refuses_while_blocked(app):
    state = ScraperState(app.config["SCRAPER_STATE_FILE"])
    state.mark_blocked(2)
    with pytest.raises(ScraperBlockedError, match="paused until"):
        next(GoogleMapsScraper(app.config).search(params(), lambda: False))


def test_google_maps_refuses_over_daily_limit(app):
    app.config["SCRAPER_DAILY_PLACE_LIMIT"] = 2
    state = ScraperState(app.config["SCRAPER_STATE_FILE"])
    state.add_place()
    state.add_place()
    with pytest.raises(ScraperLimitError, match="Daily limit of 2"):
        next(GoogleMapsScraper(app.config).search(params(), lambda: False))


def test_google_maps_cooldown_wait_can_be_cancelled(app, monkeypatch):
    def fail_launch():
        raise AssertionError("browser should not launch")

    monkeypatch.setattr("app.services.scrapers.google_maps.sync_playwright", fail_launch)
    app.config["SCRAPER_SEARCH_COOLDOWN"] = 600
    ScraperState(app.config["SCRAPER_STATE_FILE"]).record_search_started()

    started = time.monotonic()
    assert list(GoogleMapsScraper(app.config).search(params(), lambda: True)) == []
    assert time.monotonic() - started < 2


def test_shutdown_cancels_running_job(app, monkeypatch):
    started = threading.Event()

    class Slow(BaseScraper):
        def search(self, params, should_stop):
            for i in range(100):
                if should_stop():
                    return
                yield {"place_id": f"s{i}", "name": f"Slow {i}"}
                started.set()
                time.sleep(0.05)

    use_scraper(monkeypatch, Slow)
    app.config["JOB_RUNNER_SYNC"] = False
    job = SearchJob(query="cafe", max_results=100, **TBILISI)
    db.session.add(job)
    db.session.commit()

    job_runner.submit(job.id)
    assert started.wait(5)
    job_runner.shutdown(timeout=5)

    db.session.expire_all()
    job = db.session.get(SearchJob, job.id)
    assert job.status == "cancelled"
    assert job.error == SHUTDOWN_MESSAGE
    assert 0 < job.results_found < 100

    # A runner that is shutting down doesn't start new work.
    other = SearchJob(query="bar", **TBILISI)
    db.session.add(other)
    db.session.commit()
    job_runner._run(other.id)
    db.session.refresh(other)
    assert other.status == "pending"


def test_layout_change_error_is_reported(client, monkeypatch):
    class LayoutChanged(BaseScraper):
        def search(self, params, should_stop):
            yield {"place_id": "ok", "name": "Read fine"}
            raise RuntimeError(
                "Couldn't read 5 businesses in a row. Google Maps may have changed its page layout; "
                "results so far are saved"
            )

    use_scraper(monkeypatch, LayoutChanged)
    job = client.post("/api/searches", json={"query": "cafe", **TBILISI}).get_json()
    assert job["status"] == "failed"
    assert "changed its page layout" in job["error"]
    assert job["results_found"] == 1
