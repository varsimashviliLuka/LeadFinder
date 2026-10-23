import itertools
import random
from datetime import date, datetime, timedelta

import pytest

from app.extensions import db
from app.models import Business, StopStatus, TripStop
from app.services import nfc, routing
from app.services.opening_hours import open_status, parse_ranges

WEEK = ("ორშაბათი", "სამშაბათი", "ოთხშაბათი", "ხუთშაბათი", "პარასკევი", "შაბათი", "კვირა")
# Monday 26 Oct 2026.
MONDAY = datetime(2026, 10, 26)


def hours(**overrides):
    week = dict.fromkeys(WEEK, "10AM-8PM")
    week.update(overrides)
    return week


def make_business(i, lat, lng, **kwargs):
    defaults = dict(
        place_id=f"ChIJtestplace{i:04d}", name=f"Shop {i}", latitude=lat, longitude=lng,
        rating=4.8, review_count=300, opening_hours=hours(),
    )
    defaults.update(kwargs)
    business = Business(**defaults)
    db.session.add(business)
    return business


@pytest.fixture
def shops(app):
    points = [(41.7117, 44.7553), (41.7126, 44.7561), (41.7143, 44.7583), (41.7090, 44.7600), (41.7160, 44.7500)]
    items = [make_business(i, lat, lng) for i, (lat, lng) in enumerate(points)]
    db.session.commit()
    return items


# ---------- Opening hours ----------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("10AM-8PM", [(600, 1200)]),
        ("10:30AM-8:30PM", [(630, 1230)]),
        ("9-10AM", [(540, 600)]),
        ("12-8AM,10AM-12AM", [(0, 480), (600, 1440)]),
        ("6PM-2AM", [(1080, 1560)]),
        ("Closed", []),
        ("24 hours", [(0, 1440)]),
        ("whenever", None),
    ],
)
def test_parse_ranges(text, expected):
    assert parse_ranges(text) == expected


def test_open_status():
    h = hours(პარასკევი="Closed", შაბათი="6PM-2AM")
    assert open_status(h, MONDAY.replace(hour=12))["state"] == "open"
    assert open_status(h, MONDAY.replace(hour=9, minute=30)) == {"state": "closed", "text": "Closed when you arrive, opens at 10:00"}
    assert open_status(h, MONDAY.replace(hour=19, minute=50), stay_minutes=15)["state"] == "closes_soon"
    assert open_status(h, MONDAY.replace(hour=21))["text"] == "Closed when you arrive"
    friday = MONDAY + timedelta(days=4)
    assert open_status(h, friday.replace(hour=12))["text"] == "Closed that day"
    # Saturday's late hours still count after midnight on Sunday.
    assert open_status(h, (MONDAY + timedelta(days=6)).replace(hour=1))["state"] == "open"
    assert open_status(None, MONDAY)["state"] == "unknown"


# ---------- Route order ----------


def brute_force(cost):
    return min(itertools.permutations(range(len(cost))), key=lambda o: routing.path_cost(o, cost))


def test_best_order_is_optimal_for_small_trips():
    rng = random.Random(4)
    for n in (3, 5, 7):
        pts = [(rng.random(), rng.random()) for _ in range(n)]
        # Asymmetric, like real one-way streets.
        cost = [[abs(a[0] - b[0]) + abs(a[1] - b[1]) * (1.3 if i < j else 1) for j, b in enumerate(pts)] for i, a in enumerate(pts)]
        assert routing.path_cost(routing.best_order(cost), cost) == pytest.approx(routing.path_cost(brute_force(cost), cost))


def test_best_order_for_bigger_trips_visits_everyone_and_beats_random():
    rng = random.Random(7)
    pts = [(rng.random(), rng.random()) for _ in range(25)]
    cost = [[routing.haversine_m(a, b) for b in pts] for a in pts]
    order = routing.best_order(cost)
    assert sorted(order) == list(range(25))
    shuffled = list(range(25))
    rng.shuffle(shuffled)
    assert routing.path_cost(order, cost) < routing.path_cost(shuffled, cost) / 2

    # Stops on a line: the best path just walks along it.
    line = [[abs(i - j) for j in range(12)] for i in range(12)]
    assert routing.path_cost(routing.best_order(line), line) == 11


def test_router_falls_back_to_straight_lines(app):
    app.config.update(ROUTING_PROVIDER="osrm", ROUTING_URL="http://127.0.0.1:9", ROUTING_TIMEOUT=1)
    router = routing.Router(app.config)
    durations, distances, estimated = router.matrix([(41.71, 44.75), (41.72, 44.76)], "foot")
    assert estimated and durations[0][1] > 0 and distances[0][1] > 1000
    legs, geometry, estimated = router.route([(41.71, 44.75), (41.72, 44.76)], "car")
    assert estimated and len(legs) == 1 and geometry == [[41.71, 44.75], [41.72, 44.76]]


# ---------- Trips API ----------


def test_create_trip_skips_leads_you_cant_visit(client, shops):
    no_location = make_business(90, None, None)
    declined = make_business(91, 41.7, 44.7, lead_status="not_interested")
    client_lead = make_business(92, 41.7, 44.7, lead_status="client")
    db.session.commit()
    ids = [s.id for s in shops] + [no_location.id, declined.id, client_lead.id, shops[0].id]
    r = client.post("/api/trips", json={"business_ids": ids, "mode": "car"})
    assert r.status_code == 201
    data = r.get_json()
    assert data["added"] == 5
    assert {s["reason"] for s in data["skipped"]} == {"no location on the map", "marked Not interested", "already a client"}
    assert data["trip"]["mode"] == "car" and data["trip"]["optimized"] is False

    again = client.post(f"/api/trips/{data['trip']['id']}/stops", json={"business_ids": [shops[0].id]}).get_json()
    assert again["added"] == 0 and again["skipped"][0]["reason"] == "already in this trip"


def test_trip_stop_limit(client, app):
    app.config["TRIP_MAX_STOPS"] = 3
    items = [make_business(i, 41.7 + i / 1000, 44.7) for i in range(5)]
    db.session.commit()
    data = client.post("/api/trips", json={"business_ids": [b.id for b in items]}).get_json()
    assert data["added"] == 3 and len(data["skipped"]) == 2


def test_optimize_orders_stops_and_schedules_them(client, shops):
    trip = client.post("/api/trips", json={
        "business_ids": [s.id for s in shops], "start_at": "2026-10-26T11:00", "minutes_per_stop": 10,
    }).get_json()["trip"]
    r = client.post(f"/api/trips/{trip['id']}/optimize")
    assert r.status_code == 200
    data = r.get_json()
    assert data["optimized"] and data["route_estimated"]  # testing uses straight-line estimates
    assert data["total_distance_m"] > 0 and len(data["route_geometry"]) == 5
    stops = data["stops"]
    assert [s["position"] for s in stops] == [0, 1, 2, 3, 4]
    assert stops[0]["leg_duration_s"] is None and all(s["leg_duration_s"] > 0 for s in stops[1:])
    assert stops[0]["eta"] == "2026-10-26T11:00"
    second = datetime(2026, 10, 26, 11, 10) + timedelta(seconds=stops[1]["leg_duration_s"])
    assert stops[1]["eta"] == second.strftime("%Y-%m-%dT%H:%M")
    assert all(s["open_state"] == "open" for s in stops)
    assert data["finish_at"] > stops[-1]["eta"]
    assert stops[0]["business"]["review_url"].startswith("https://search.google.com/local/writereview?placeid=ChIJ")

    # The optimizer found an order no worse than the original one.
    cost = [[routing.haversine_m((a.latitude, a.longitude), (b.latitude, b.longitude)) for b in shops] for a in shops]
    by_id = {s.id: i for i, s in enumerate(shops)}
    chosen = [by_id[s["business"]["id"]] for s in stops]
    assert routing.path_cost(chosen, cost) <= routing.path_cost(list(range(5)), cost) + 1


def test_changing_mode_or_stops_needs_a_new_route(client, shops):
    trip_id = client.post("/api/trips", json={"business_ids": [s.id for s in shops]}).get_json()["trip"]["id"]
    client.post(f"/api/trips/{trip_id}/optimize")
    assert client.patch(f"/api/trips/{trip_id}", json={"mode": "car"}).get_json()["optimized"] is False
    client.post(f"/api/trips/{trip_id}/optimize")
    stop_id = client.get(f"/api/trips/{trip_id}").get_json()["stops"][2]["id"]
    data = client.delete(f"/api/trips/{trip_id}/stops/{stop_id}").get_json()
    assert data["optimized"] is False and [s["position"] for s in data["stops"]] == [0, 1, 2, 3]


def test_trip_validation(client, shops):
    assert client.post("/api/trips", json={"mode": "bike"}).status_code == 400
    trip_id = client.post("/api/trips", json={}).get_json()["trip"]["id"]
    assert client.post(f"/api/trips/{trip_id}/optimize").status_code == 400
    assert client.patch(f"/api/trips/{trip_id}", json={"start_at": "tomorrow"}).status_code == 400
    assert client.patch(f"/api/trips/{trip_id}", json={"minutes_per_stop": 999}).status_code == 400
    assert client.patch(f"/api/trips/{trip_id}", json={"name": " "}).status_code == 400
    assert client.post(f"/api/trips/{trip_id}/stops", json={"business_ids": "1,2"}).status_code == 400
    assert client.get("/api/trips/999").status_code == 404


def test_remove_closed_stops(client, shops):
    shops[1].opening_hours = hours(ორშაბათი="Closed")
    shops[2].opening_hours = hours(ორშაბათი="6PM-11PM")
    db.session.commit()
    trip_id = client.post("/api/trips", json={
        "business_ids": [s.id for s in shops], "start_at": "2026-10-26T11:00",
    }).get_json()["trip"]["id"]
    states = {s["business"]["id"]: s["open_state"] for s in client.get(f"/api/trips/{trip_id}").get_json()["stops"]}
    assert states[shops[1].id] == "closed" and states[shops[2].id] == "closed"
    data = client.post(f"/api/trips/{trip_id}/remove-closed").get_json()
    assert data["removed"] == 2 and len(data["trip"]["stops"]) == 3


def test_log_visit_updates_lead_and_can_be_undone(client, shops):
    data = client.post("/api/trips", json={"business_ids": [shops[0].id, shops[1].id]}).get_json()
    trip_id, stop = data["trip"]["id"], data["trip"]["stops"][0]
    url = f"/api/trips/{trip_id}/stops/{stop['id']}/visit"

    assert client.post(url, json={"outcome": "maybe"}).status_code == 400
    assert client.post(url, json={"outcome": "interested", "service_nfc": "bogus"}).status_code == 400
    assert client.get(f"/api/businesses/{shops[0].id}").get_json()["calls"] == []

    r = client.post(url, json={"outcome": "interested", "note": "Owner likes the card", "service_nfc": "interested"})
    assert r.status_code == 200
    visited = r.get_json()["stops"][0]
    assert visited["status"] == "visited" and visited["outcome"] == "interested" and visited["note"] == "Owner likes the card"
    lead = client.get(f"/api/businesses/{shops[0].id}").get_json()
    assert lead["lead_status"] == "interested" and lead["service_nfc"] == "interested"
    assert lead["calls"][0]["kind"] == "visit"
    assert client.post(url, json={"outcome": "client"}).status_code == 400  # already done

    undone = client.delete(url).get_json()["stops"][0]
    assert undone["status"] == "pending" and undone["outcome"] is None
    lead = client.get(f"/api/businesses/{shops[0].id}").get_json()
    assert lead["calls"] == [] and lead["lead_status"] == "new"
    assert lead["service_nfc"] == "interested"  # what they said about the card is kept

    skipped = client.post(url, json={"outcome": "skipped"}).get_json()["stops"][0]
    assert skipped["status"] == "skipped"
    assert client.get(f"/api/businesses/{shops[0].id}").get_json()["calls"] == []


def test_deleting_the_visit_from_history_reopens_the_stop(client, shops):
    data = client.post("/api/trips", json={"business_ids": [shops[0].id]}).get_json()
    trip_id, stop_id = data["trip"]["id"], data["trip"]["stops"][0]["id"]
    client.post(f"/api/trips/{trip_id}/stops/{stop_id}/visit", json={"outcome": "call_back"})
    call_id = client.get(f"/api/businesses/{shops[0].id}").get_json()["calls"][0]["id"]
    assert client.delete(f"/api/businesses/{shops[0].id}/calls/{call_id}").status_code == 200
    assert db.session.get(TripStop, stop_id).status == StopStatus.PENDING


def test_deleting_trip_keeps_visits_and_leads(client, shops):
    data = client.post("/api/trips", json={"business_ids": [shops[0].id]}).get_json()
    trip_id, stop_id = data["trip"]["id"], data["trip"]["stops"][0]["id"]
    client.post(f"/api/trips/{trip_id}/stops/{stop_id}/visit", json={"outcome": "interested"})
    assert client.delete(f"/api/trips/{trip_id}").status_code == 204
    assert client.get("/api/trips").get_json() == []
    assert len(client.get(f"/api/businesses/{shops[0].id}").get_json()["calls"]) == 1

    # Deleting a lead removes it from trips too.
    trip_id = client.post("/api/trips", json={"business_ids": [shops[1].id, shops[2].id]}).get_json()["trip"]["id"]
    client.delete(f"/api/businesses/{shops[1].id}")
    assert len(client.get(f"/api/trips/{trip_id}").get_json()["stops"]) == 1


def test_trips_list(client, shops):
    trip_id = client.post("/api/trips", json={"business_ids": [s.id for s in shops]}).get_json()["trip"]["id"]
    listed = client.get("/api/trips").get_json()
    assert listed[0]["id"] == trip_id and listed[0]["stop_count"] == 5 and listed[0]["done_count"] == 0


# ---------- NFC cards and services ----------


def test_nfc_prospect_reasons():
    today = date(2026, 10, 23)
    busy = Business(review_count=400, rating=4.7, latest_review_date=today)
    assert nfc.prospect_reasons(busy, today) == []
    quiet = Business(review_count=12, rating=4.0, latest_review_date=today - timedelta(days=200))
    assert nfc.prospect_reasons(quiet, today) == [
        "Only 12 Google reviews", "Rating 4: more happy-customer reviews would lift it", "No new review in about 7 months",
    ]
    assert nfc.prospect_reasons(Business(), today) == ["No Google reviews yet"]
    assert nfc.review_url(Business(place_id="ChIJN1t_tDeuEmsRUsoyG83frY4")) == (
        "https://search.google.com/local/writereview?placeid=ChIJN1t_tDeuEmsRUsoyG83frY4"
    )
    assert nfc.review_url(Business(place_id="fake-123")) is None


def test_nfc_filter_qr_and_services(client, shops):
    shops[0].review_count = 8
    db.session.commit()
    prospects = client.get("/api/businesses?nfc_prospect=true").get_json()
    assert [b["id"] for b in prospects["items"]] == [shops[0].id]
    assert prospects["items"][0]["nfc_reasons"] == ["Only 8 Google reviews"]
    assert client.get("/api/businesses?nfc_prospect=false").get_json()["total"] == 4

    svg = client.get(f"/api/businesses/{shops[0].id}/review-qr.svg")
    assert svg.status_code == 200 and svg.mimetype == "image/svg+xml" and b"<svg" in svg.data
    png = client.get(f"/api/businesses/{shops[0].id}/review-qr.png")
    assert png.status_code == 200 and png.data.startswith(b"\x89PNG")
    no_id = make_business(50, 41.7, 44.7, place_id="sample-1")
    db.session.commit()
    assert client.get(f"/api/businesses/{no_id.id}/review-qr.svg").status_code == 404

    r = client.patch(f"/api/businesses/{shops[0].id}", json={"service_nfc": "sold", "service_content": "offered"})
    assert r.status_code == 200 and r.get_json()["service_nfc"] == "sold"
    assert client.patch(f"/api/businesses/{shops[0].id}", json={"service_nfc": "maybe"}).status_code == 400
    assert client.get("/api/businesses?service=nfc:sold").get_json()["total"] == 1
    assert client.get("/api/businesses?service=nfc:none").get_json()["total"] == 5
    assert client.get("/api/businesses?service=content:offered").get_json()["total"] == 1
    stats = client.get("/api/businesses/stats").get_json()
    assert stats["nfc_sold"] == 1 and stats["nfc_prospects"] == 1
    assert client.patch(f"/api/businesses/{shops[0].id}", json={"service_nfc": None}).get_json()["service_nfc"] is None


def test_map_points(client, shops):
    make_business(60, None, None)
    db.session.commit()
    points = client.get("/api/businesses/map").get_json()
    assert len(points) == 5 and set(points[0]) >= {"id", "latitude", "longitude", "lead_status", "nfc_prospect"}


def test_call_kind(client, shops):
    url = f"/api/businesses/{shops[0].id}/calls"
    assert client.post(url, json={"outcome": "interested", "kind": "visit"}).get_json()["kind"] == "visit"
    assert client.post(url, json={"outcome": "interested"}).get_json()["kind"] == "call"
    assert client.post(url, json={"outcome": "interested", "kind": "letter"}).status_code == 400


def test_trip_pages_render(client, shops):
    trip_id = client.post("/api/trips", json={"business_ids": [shops[0].id]}).get_json()["trip"]["id"]
    assert b"Visits" in client.get("/trips").data
    assert client.get(f"/trips/{trip_id}").status_code == 200
    assert client.get("/trips/999").status_code == 404


# ---------- Opening the app from a phone ----------

PHONE = {"REMOTE_ADDR": "192.168.1.20"}


def test_other_devices_are_blocked_until_a_password_is_set(client):
    r = client.get("/", environ_base=PHONE)
    assert r.status_code == 403 and b"APP_PASSWORD" in r.data
    assert client.get("/api/businesses", environ_base=PHONE).status_code == 403
    assert client.get("/").status_code == 200  # this computer


def test_phone_sign_in(app, client):
    app.config.update(APP_PASSWORD="open sesame", SECRET_KEY="a-long-random-secret-for-tests")
    r = client.get("/trips", environ_base=PHONE)
    assert r.status_code == 302 and "/login?next=/trips" in r.headers["Location"]
    assert client.get("/api/trips", environ_base=PHONE).status_code == 401
    assert client.get("/login", environ_base=PHONE).status_code == 200

    bad = client.post("/login", data={"password": "nope"}, environ_base=PHONE)
    assert bad.status_code == 401 and b"Wrong password" in bad.data
    ok = client.post("/login?next=/trips", data={"password": "open sesame"}, environ_base=PHONE)
    assert ok.status_code == 302 and ok.headers["Location"].endswith("/trips")
    assert client.get("/api/trips", environ_base=PHONE).status_code == 200

    client.post("/logout", environ_base=PHONE)
    assert client.get("/api/trips", environ_base=PHONE).status_code == 401


def test_sign_in_needs_a_real_secret_key_and_limits_guessing(app, client):
    app.config.update(APP_PASSWORD="open sesame", SECRET_KEY="change-me")
    assert client.get("/login", environ_base=PHONE).status_code == 403

    app.config["SECRET_KEY"] = "a-long-random-secret-for-tests"
    guesser = {"REMOTE_ADDR": "192.168.1.66"}
    for _ in range(8):
        client.post("/login", data={"password": "guess"}, environ_base=guesser)
    blocked = client.post("/login", data={"password": "open sesame"}, environ_base=guesser)
    assert b"Too many wrong passwords" in blocked.data


def test_login_does_not_redirect_offsite(app, client):
    app.config.update(APP_PASSWORD="pw", SECRET_KEY="a-long-random-secret-for-tests")
    r = client.post("/login?next=//evil.example", data={"password": "pw"}, environ_base={"REMOTE_ADDR": "10.0.0.5"})
    assert r.headers["Location"] == "/"
