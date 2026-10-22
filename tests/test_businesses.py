from datetime import date, timedelta

import pytest

from app.extensions import db
from app.models import Business, SearchJob
from app.services.businesses import upsert_business


def scraped(place_id="place-1", **overrides):
    data = {
        "place_id": place_id,
        "name": "Cafe Tbilisi",
        "category": "Cafe",
        "address": "1 Rustaveli Ave, Tbilisi",
        "phone": "+995 555 12 34 56",
        "website": "https://cafe.example",
        "rating": 4.5,
        "review_count": 120,
    }
    data.update(overrides)
    return data


@pytest.fixture
def business(app):
    business, _ = upsert_business(scraped())
    db.session.commit()
    return business


def test_upsert_creates_then_dedupes(app):
    job = SearchJob(query="cafe", latitude=41.7, longitude=44.8)
    db.session.add(job)

    first, created = upsert_business(scraped(), job)
    db.session.commit()
    assert created

    first.lead_status = "interested"
    first.notes = "Call Monday"
    second, created = upsert_business(scraped(rating=4.7, phone=None), job)
    db.session.commit()

    assert not created
    assert second.id == first.id
    assert db.session.query(Business).count() == 1
    assert second.rating == 4.7
    assert second.phone == "+995 555 12 34 56"
    assert second.lead_status == "interested"
    assert second.notes == "Call Monday"
    assert second.search_jobs == [job]


def test_upsert_requires_place_id_and_name(app):
    with pytest.raises(ValueError):
        upsert_business({"name": "No id"})
    with pytest.raises(ValueError):
        upsert_business({"place_id": "x"})


def test_list_and_filters(client, app):
    upsert_business(scraped("a", name="Barber One", category="Barber shop", website=None, rating=3.9))
    upsert_business(scraped("b", name="Dental Smile", category="Dentist", phone=None))
    upsert_business(scraped("c", name="Cafe Two"))
    db.session.commit()

    data = client.get("/api/businesses").get_json()
    assert data["total"] == 3
    assert {"items", "page", "per_page", "pages"} <= data.keys()

    def names(query):
        return {b["name"] for b in client.get(f"/api/businesses?{query}").get_json()["items"]}

    assert names("q=dental") == {"Dental Smile"}
    assert names("category=barber") == {"Barber One"}
    assert names("has_website=false") == {"Barber One"}
    assert names("has_phone=false") == {"Dental Smile"}
    assert names("min_rating=4") == {"Dental Smile", "Cafe Two"}

    ordered = client.get("/api/businesses?sort=name&order=asc").get_json()["items"]
    assert [b["name"] for b in ordered] == ["Barber One", "Cafe Two", "Dental Smile"]

    paged = client.get("/api/businesses?per_page=2&page=2").get_json()
    assert len(paged["items"]) == 1 and paged["pages"] == 2


def test_filter_by_search_job(client, app):
    job = SearchJob(query="cafe", latitude=41.7, longitude=44.8)
    db.session.add(job)
    upsert_business(scraped("a", name="In job"), job)
    upsert_business(scraped("b", name="Not in job"))
    db.session.commit()

    items = client.get(f"/api/businesses?search_job_id={job.id}").get_json()["items"]
    assert [b["name"] for b in items] == ["In job"]


def test_get_and_404(client, business):
    data = client.get(f"/api/businesses/{business.id}").get_json()
    assert data["name"] == "Cafe Tbilisi"
    assert data["lead_status"] == "new"
    assert data["calls"] == []
    assert client.get("/api/businesses/9999").status_code == 404


def test_patch_updates_lead_fields(client, business):
    response = client.patch(
        f"/api/businesses/{business.id}",
        json={"lead_status": "call_back", "notes": "  Owner back Friday ", "follow_up_date": "2026-10-23"},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["lead_status"] == "call_back"
    assert data["notes"] == "Owner back Friday"
    assert data["follow_up_date"] == "2026-10-23"

    cleared = client.patch(f"/api/businesses/{business.id}", json={"follow_up_date": None}).get_json()
    assert cleared["follow_up_date"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {"lead_status": "bogus"},
        {"follow_up_date": "23/10/2026"},
        {"name": "Renamed"},
        {"notes": 123},
    ],
)
def test_patch_rejects_bad_input(client, business, payload):
    assert client.patch(f"/api/businesses/{business.id}", json=payload).status_code == 400


def test_log_call_updates_status(client, business):
    response = client.post(
        f"/api/businesses/{business.id}/calls", json={"outcome": "interested", "note": "Wants a quote"}
    )
    assert response.status_code == 201
    assert response.get_json()["outcome"] == "interested"

    detail = client.get(f"/api/businesses/{business.id}").get_json()
    assert detail["lead_status"] == "interested"
    assert detail["last_contacted_at"] is not None
    assert [c["note"] for c in detail["calls"]] == ["Wants a quote"]

    assert client.post(f"/api/businesses/{business.id}/calls", json={"outcome": "new"}).status_code == 400


def test_delete(client, business):
    client.post(f"/api/businesses/{business.id}/calls", json={"outcome": "no_answer"})
    assert client.delete(f"/api/businesses/{business.id}").status_code == 204
    assert client.get(f"/api/businesses/{business.id}").status_code == 404


def test_stats(client, app):
    upsert_business(scraped("a", website=None, claimed=False))
    b, _ = upsert_business(scraped("b", phone=None, claimed=True))
    b.lead_status = "client"
    b.follow_up_date = date.today() - timedelta(days=1)
    db.session.commit()

    stats = client.get("/api/businesses/stats").get_json()
    assert stats["total"] == 2
    assert stats["by_status"]["new"] == 1
    assert stats["by_status"]["client"] == 1
    assert stats["with_phone"] == 1
    assert stats["with_website"] == 1
    assert stats["unclaimed"] == 1
    assert stats["follow_ups_due"] == 1

    unclaimed = client.get("/api/businesses?claimed=false").get_json()["items"]
    assert [x["place_id"] for x in unclaimed] == ["a"]


def test_search_jobs_endpoints(client, app):
    job = SearchJob(query="dentist", location_text="Vake, Tbilisi", latitude=41.71, longitude=44.75)
    db.session.add(job)
    db.session.commit()

    listing = client.get("/api/searches").get_json()
    assert listing["total"] == 1
    assert listing["items"][0]["status"] == "pending"
    assert client.get(f"/api/searches/{job.id}").get_json()["query"] == "dentist"
    assert client.get("/api/searches/999").status_code == 404


def test_detail_page_renders(client, business):
    response = client.get(f"/businesses/{business.id}")
    assert response.status_code == 200
    assert b"Cafe Tbilisi" in response.data


def test_export_csv(client, app):
    upsert_business(scraped("a", name="ბარბერი", opening_hours={"ორშაბათი": "10AM-7PM"}, claimed=False))
    upsert_business(scraped("b", name="=HYPERLINK(\"http://evil\")", website=None))
    db.session.commit()

    response = client.get("/api/businesses/export?has_website=true")
    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    assert "attachment" in response.headers["Content-Disposition"]
    text = response.get_data(as_text=True)
    assert text.startswith("\ufeffname,category,phone")
    assert "ბარბერი" in text
    assert "ორშაბათი: 10AM-7PM" in text
    assert ",no," in text
    assert "+995 555 12 34 56" in text
    assert "HYPERLINK" not in text

    everything = client.get("/api/businesses/export").get_data(as_text=True)
    assert "'=HYPERLINK" in everything


def test_scraper_status(client):
    status = client.get("/api/searches/scraper-status").get_json()
    assert status == {
        "provider": "fake",
        "places_today": 0,
        "daily_limit": 300,
        "blocked_until": None,
        "next_search_in": 0,
    }


def test_delete_call_undoes_its_status(client, business):
    calls_url = f"/api/businesses/{business.id}/calls"
    first = client.post(calls_url, json={"outcome": "no_answer"}).get_json()
    second = client.post(calls_url, json={"outcome": "interested", "note": "Wrong lead"}).get_json()

    detail = client.delete(f"{calls_url}/{second['id']}").get_json()
    assert detail["lead_status"] == "no_answer"
    assert [c["id"] for c in detail["calls"]] == [first["id"]]
    assert detail["last_contacted_at"] is not None

    detail = client.delete(f"{calls_url}/{first['id']}").get_json()
    assert detail["lead_status"] == "new"
    assert detail["calls"] == []
    assert detail["last_contacted_at"] is None

    assert client.delete(f"{calls_url}/{first['id']}").status_code == 404


def test_delete_call_keeps_manual_status(client, business):
    calls_url = f"/api/businesses/{business.id}/calls"
    call = client.post(calls_url, json={"outcome": "call_back"}).get_json()
    client.patch(f"/api/businesses/{business.id}", json={"lead_status": "client"})

    detail = client.delete(f"{calls_url}/{call['id']}").get_json()
    assert detail["lead_status"] == "client"


def test_delete_call_of_other_business_is_404(client, business):
    other, _ = upsert_business(scraped("other"))
    db.session.commit()
    call = client.post(f"/api/businesses/{other.id}/calls", json={"outcome": "no_answer"}).get_json()
    assert client.delete(f"/api/businesses/{business.id}/calls/{call['id']}").status_code == 404
