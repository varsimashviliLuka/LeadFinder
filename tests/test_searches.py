import pytest

from app.extensions import db
from app.models import Business, SearchJob
from app.services import geocoding
from app.services.geocoding import GeocodingError, Location
from app.services.scrapers.base import BaseScraper
from app.workers import job_runner

TBILISI = {"latitude": 41.7151, "longitude": 44.8271}


@pytest.fixture
def fake_geocoder(monkeypatch):
    calls = []

    def search(query, limit=5):
        calls.append(query)
        if query == "nowhere":
            return []
        if query == "offline":
            raise GeocodingError("Geocoding service unavailable")
        return [Location(41.7099, 44.7556, f"{query}, Tbilisi, Georgia")][:limit]

    def reverse(lat, lng):
        return Location(lat, lng, "Rustaveli Ave, Tbilisi, Georgia")

    monkeypatch.setattr(geocoding, "search", search)
    monkeypatch.setattr(geocoding, "reverse", reverse)
    return calls


def test_create_search_with_coordinates_runs_job(client):
    response = client.post("/api/searches", json={"query": "cafe", **TBILISI, "max_results": 10})
    assert response.status_code == 201
    job = response.get_json()
    assert job["status"] == "completed"
    assert job["results_found"] == 10
    assert job["results_new"] == 10
    assert job["started_at"] and job["finished_at"]

    items = client.get(f"/api/businesses?search_job_id={job['id']}&per_page=100").get_json()
    assert items["total"] == 10


def test_repeat_search_dedupes(client):
    first = client.post("/api/searches", json={"query": "cafe", **TBILISI, "max_results": 5}).get_json()
    second = client.post("/api/searches", json={"query": "cafe", **TBILISI, "max_results": 5}).get_json()
    assert first["results_new"] == 5
    assert second["results_found"] == 5
    assert second["results_new"] == 0
    assert db.session.query(Business).count() == 5


def test_create_search_geocodes_location_text(client, fake_geocoder):
    response = client.post("/api/searches", json={"query": "dentist", "location_text": "Vake"})
    assert response.status_code == 201
    job = response.get_json()
    assert fake_geocoder == ["Vake"]
    assert (job["latitude"], job["longitude"]) == (41.7099, 44.7556)
    assert job["location_text"] == "Vake"


@pytest.mark.parametrize(
    "payload, status",
    [
        ({}, 400),
        ({"query": "  "}, 400),
        ({"query": "cafe"}, 400),
        ({"query": "cafe", "latitude": 41.7}, 400),
        ({"query": "cafe", "latitude": 141.7, "longitude": 44.8}, 400),
        ({"query": "cafe", **TBILISI, "radius_m": 10}, 400),
        ({"query": "cafe", **TBILISI, "max_results": 500}, 400),
        ({"query": "cafe", **TBILISI, "max_results": "10"}, 400),
        ({"query": "cafe", **TBILISI, "radius_m": True}, 400),
        ({"query": "cafe", "location_text": "nowhere"}, 400),
        ({"query": "cafe", "location_text": "offline"}, 502),
    ],
)
def test_create_search_validation(client, fake_geocoder, payload, status):
    assert client.post("/api/searches", json=payload).status_code == status
    assert db.session.query(SearchJob).count() == 0


def test_cancel_while_running_stops_job(client, monkeypatch):
    class CancelMidway(BaseScraper):
        def search(self, params, should_stop):
            for i in range(10):
                if i == 3:
                    job_id = db.session.query(SearchJob.id).scalar()
                    assert job_runner.cancel(job_id)
                if should_stop():
                    return
                yield {"place_id": f"p{i}", "name": f"Place {i}"}

    monkeypatch.setattr("app.workers.runner.get_scraper", lambda name, config: CancelMidway(config))

    job = client.post("/api/searches", json={"query": "cafe", **TBILISI}).get_json()
    assert job["status"] == "cancelled"
    assert job["results_found"] == 3
    assert not job_runner.cancel(job["id"])


def test_cancel_endpoint(client):
    job = SearchJob(query="cafe", **TBILISI)
    db.session.add(job)
    db.session.commit()

    response = client.post(f"/api/searches/{job.id}/cancel")
    assert response.status_code == 200
    assert response.get_json()["status"] == "cancelled"
    assert client.post(f"/api/searches/{job.id}/cancel").status_code == 409
    assert client.post("/api/searches/999/cancel").status_code == 404


def test_scraper_crash_marks_job_failed(client, monkeypatch):
    class BrokenScraper(BaseScraper):
        def search(self, params, should_stop):
            yield {"place_id": "ok-1", "name": "Saved before crash"}
            raise RuntimeError("Google Maps layout changed")

    monkeypatch.setattr("app.workers.runner.get_scraper", lambda name, config: BrokenScraper(config))

    job = client.post("/api/searches", json={"query": "cafe", **TBILISI}).get_json()
    assert job["status"] == "failed"
    assert "layout changed" in job["error"]
    assert job["results_found"] == 1
    assert db.session.query(Business).count() == 1


def test_invalid_results_are_skipped(client, monkeypatch):
    class SloppyScraper(BaseScraper):
        def search(self, params, should_stop):
            yield {"name": "No place id"}
            yield {"place_id": "good", "name": "Good one"}

    monkeypatch.setattr("app.workers.runner.get_scraper", lambda name, config: SloppyScraper(config))

    job = client.post("/api/searches", json={"query": "cafe", **TBILISI}).get_json()
    assert job["status"] == "completed"
    assert job["results_found"] == 1


def test_recover_interrupted_jobs(app):
    db.session.add_all(
        [
            SearchJob(query="a", status="running", **TBILISI),
            SearchJob(query="b", status="pending", **TBILISI),
            SearchJob(query="c", status="completed", **TBILISI),
        ]
    )
    db.session.commit()

    assert job_runner.recover_interrupted_jobs() == 2
    statuses = {j.query: j.status for j in db.session.query(SearchJob)}
    assert statuses == {"a": "failed", "b": "failed", "c": "completed"}


def test_geocode_endpoints(client, fake_geocoder):
    matches = client.get("/api/geocode?q=Saburtalo").get_json()
    assert matches[0]["display_name"].startswith("Saburtalo")

    assert client.get("/api/geocode?q=offline").status_code == 502
    assert client.get("/api/geocode").status_code == 400

    reverse = client.get("/api/geocode/reverse?lat=41.7&lng=44.8").get_json()
    assert reverse["display_name"] == "Rustaveli Ave, Tbilisi, Georgia"
    assert client.get("/api/geocode/reverse?lat=100&lng=44.8").status_code == 400


def test_delete_search_only_when_finished_and_empty(client):
    empty = SearchJob(query="a", status="failed", **TBILISI)
    running = SearchJob(query="b", status="running", **TBILISI)
    with_results = SearchJob(query="c", status="completed", results_found=3, **TBILISI)
    db.session.add_all([empty, running, with_results])
    db.session.commit()

    assert client.delete(f"/api/searches/{running.id}").status_code == 409
    assert client.delete(f"/api/searches/{with_results.id}").status_code == 409
    assert client.delete(f"/api/searches/{empty.id}").status_code == 204
    assert client.delete(f"/api/searches/{empty.id}").status_code == 404
    assert {j.query for j in db.session.query(SearchJob)} == {"b", "c"}


def test_clear_empty_searches(client):
    db.session.add_all(
        [
            SearchJob(query="failed", status="failed", **TBILISI),
            SearchJob(query="stopped", status="cancelled", **TBILISI),
            SearchJob(query="pending", status="pending", **TBILISI),
            SearchJob(query="kept", status="completed", results_found=2, **TBILISI),
        ]
    )
    db.session.commit()

    assert client.delete("/api/searches/empty").get_json() == {"deleted": 2}
    assert {j.query for j in db.session.query(SearchJob)} == {"pending", "kept"}


def test_empty_search_explains_why(client, monkeypatch):
    class NothingNearby(BaseScraper):
        def search(self, params, should_stop):
            self.stop_reason = "none inside the 1.0 km circle"
            return
            yield

    monkeypatch.setattr("app.workers.runner.get_scraper", lambda name, config: NothingNearby(config))
    job = client.post("/api/searches", json={"query": "cafe", **TBILISI}).get_json()
    assert job["status"] == "completed"
    assert job["error"] == "none inside the 1.0 km circle"
