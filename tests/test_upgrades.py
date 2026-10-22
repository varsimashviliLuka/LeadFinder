from datetime import date

import pytest

from app.extensions import db
from app.models import Business, MessageTemplate
from app.services import socials
from app.services.scrapers.google_maps import build_business, parse_relative_date, summarize_reviews
from app.services.website_info import assess_website, extract_email, extract_whatsapp, website_issues

TODAY = date(2026, 10, 22)


# ---------- Contacts from the website ----------


def test_extract_email_prefers_mailto_on_own_domain():
    html = """
      <p>Built by studio@agency.com</p>
      <a href="mailto:info@salon.ge?subject=Hi">Write to us</a>
      <img src="logo@2x.png"> <span>noreply@sentry.io</span>
    """
    assert extract_email(html, "https://www.salon.ge/") == "info@salon.ge"


def test_extract_email_ranks_hiring_address_last():
    html = '<a href="mailto:job@gbar.ge">Work with us</a> <p>Bookings: gbar.booking@gmail.com</p>'
    assert extract_email(html, "https://gbar.ge/") == "gbar.booking@gmail.com"
    assert extract_email('<a href="mailto:jobs@gbar.ge">x</a>', "https://gbar.ge/") == "jobs@gbar.ge"


def test_extract_email_none_when_only_junk():
    assert extract_email('<img src="icon@2x.webp"> user@example.com', "https://salon.ge") is None


def test_extract_whatsapp_formats_number():
    html = '<a href="https://wa.me/995555123456?text=hi">WhatsApp</a>'
    assert extract_whatsapp(html, "GE") == "+995 555 12 34 56"
    assert extract_whatsapp('<a href="https://api.whatsapp.com/send?phone=995599111222">x</a>', "GE")
    assert extract_whatsapp("<p>no chat here</p>", "GE") is None


# ---------- Website quality ----------


def test_assess_modern_site_has_no_issues():
    html = '<meta name="viewport" content="width=device-width, initial-scale=1"><footer>© 2026 Salon</footer>'
    check = assess_website("https://salon.ge/", html, 1.234)
    assert check["https"] and check["mobile_friendly"]
    assert (check["load_seconds"], check["copyright_year"]) == (1.2, 2026)
    assert website_issues(check, today=TODAY) == []


def test_assess_old_site_lists_issues():
    html = '<meta name="generator" content="WordPress 4.9"><p>Copyright &copy; 2015-2019 Salon</p>'
    check = assess_website("http://salon.ge/", html, 6.0)
    assert check["builder"].startswith("WordPress")
    issues = website_issues(check, today=TODAY)
    assert len(issues) == 4
    assert any("HTTPS" in i for i in issues)
    assert any("mobile" in i for i in issues)
    assert any("2019" in i for i in issues)
    assert any("Slow" in i for i in issues)


def test_unreachable_and_social_only_sites():
    assert website_issues({"url": "https://x.ge", "error": "timed out"}) == ["Website doesn't open: timed out"]
    assert website_issues({"url": "https://instagram.com/x", "social_only": "instagram"}) == []


def test_finder_collects_contacts_and_website_check(app, monkeypatch):
    pages = {
        "https://salon.ge/": '<meta name="viewport" content="width=device-width"><a href="/contact">Contact</a>',
        "https://salon.ge/contact": '<a href="mailto:hello@salon.ge">mail</a><a href="https://wa.me/995555000111">wa</a>',
    }
    monkeypatch.setattr(socials, "fetch_page", lambda client, url: (url, pages[url]))
    b = Business(place_id="s1", name="Salon", website="https://salon.ge/")
    db.session.add(b)
    with socials.SocialFinder(app.config) as finder:
        socials.save_social_check(b, finder.find(b.website))
    db.session.commit()
    assert (b.email, b.whatsapp) == ("hello@salon.ge", "+995 555 00 01 11")
    assert b.website_check["https"] is True
    assert b.website_issue_count == 0


def test_listing_that_is_a_social_page_is_not_rechecked(client, app):
    b = Business(place_id="ig", name="IG only", website="https://www.instagram.com/ig.only/")
    db.session.add(b)
    db.session.commit()
    assert client.get("/api/businesses/stats").get_json()["needs_check"] == 1
    client.post(f"/api/businesses/{b.id}/socials/find")
    stats = client.get("/api/businesses/stats").get_json()
    assert stats["needs_check"] == 0
    assert stats["website_problems"] == 0


def test_previously_checked_lead_needs_website_check(client):
    b = Business(place_id="old", name="Checked before", website="https://old.ge/")
    b.social_checked_at = db.func.now()
    db.session.add(b)
    db.session.commit()
    ids = [x["id"] for x in client.get("/api/businesses?social=needs_check").get_json()["items"]]
    assert ids == [b.id]


# ---------- Google reviews ----------


@pytest.mark.parametrize(
    ("text", "days"),
    [
        ("3 კვირის წინ", 21),
        ("ერთი თვის წინ", 30),
        ("9 თვის წინ", 270),
        ("7 წლის წინ", 7 * 365),
        ("2 დღის წინ", 2),
        ("5 საათის წინ", 0),
        ("a month ago", 30),
        ("3 weeks ago", 21),
        ("2 years ago", 730),
        ("Edited 4 days ago", 4),
    ],
)
def test_parse_relative_date(text, days):
    assert (TODAY - parse_relative_date(text, TODAY)).days == days


def test_parse_relative_date_unknown():
    assert parse_relative_date("", TODAY) is None
    assert parse_relative_date("რაღაც", TODAY) is None


def test_summarize_reviews():
    reviews = [
        {"date": "3 კვირის წინ", "owner": True},
        {"date": "ერთი თვის წინ", "owner": False},
        {"date": "9 თვის წინ", "owner": True},
    ]
    assert summarize_reviews(reviews, TODAY) == {
        "latest_review_date": date(2026, 10, 1),
        "recent_reviews_checked": 3,
        "recent_owner_replies": 2,
    }
    assert summarize_reviews([], TODAY)["recent_reviews_checked"] == 0


def test_build_business_includes_price_and_reviews():
    details = {
        "name": "Cafe",
        "price_level": "₾₾",
        "reviews_summary": {"latest_review_date": TODAY, "recent_reviews_checked": 10, "recent_owner_replies": 0},
    }
    data = build_business(details, {"place_id": "c1", "maps_url": "https://maps.google.com/?cid=1"}, "GE")
    assert data["price_level"] == "₾₾"
    assert (data["recent_reviews_checked"], data["recent_owner_replies"]) == (10, 0)


def test_collect_reviews_is_saved_on_search(client):
    job = client.post(
        "/api/searches",
        json={"query": "cafe", "latitude": 41.7151, "longitude": 44.8271, "max_results": 2, "collect_reviews": True},
    ).get_json()
    assert job["collect_reviews"] is True
    bad = client.post("/api/searches", json={"query": "cafe", "latitude": 41.7, "longitude": 44.8, "collect_reviews": 1})
    assert bad.status_code == 400


# ---------- Lead API ----------


@pytest.fixture
def lead(app):
    b = Business(
        place_id="L1",
        name="Salon Nino",
        website="http://nino.ge/",
        email="nino@nino.ge",
        website_check={"url": "http://nino.ge/", "https": False, "mobile_friendly": True, "load_seconds": 1.0},
        website_issue_count=1,
        latest_review_date=TODAY,
        recent_reviews_checked=10,
        recent_owner_replies=3,
    )
    db.session.add_all([b, Business(place_id="L2", name="Fine site", website_check={"https": True}, website_issue_count=0)])
    db.session.commit()
    return b


def test_lead_api_fields_and_filters(client, lead):
    data = client.get(f"/api/businesses/{lead.id}").get_json()
    assert data["website_issues"] == ["No HTTPS: browsers mark it 'Not secure'"]
    assert data["latest_review_date"] == TODAY.isoformat()
    assert data["recent_owner_replies"] == 3

    names = lambda q: [b["name"] for b in client.get(f"/api/businesses?{q}").get_json()["items"]]  # noqa: E731
    assert names("website_quality=problems") == ["Salon Nino"]
    assert names("website_quality=ok") == ["Fine site"]
    assert names("has_email=true") == ["Salon Nino"]

    stats = client.get("/api/businesses/stats").get_json()
    assert (stats["with_email"], stats["website_problems"]) == (1, 1)


def test_whatsapp_editable_and_website_change_resets_check(client, lead):
    data = client.patch(f"/api/businesses/{lead.id}", json={"whatsapp": " +995 555 11 22 33 "}).get_json()
    assert data["whatsapp"] == "+995 555 11 22 33"
    data = client.patch(f"/api/businesses/{lead.id}", json={"website": "https://new.ge/"}).get_json()
    assert data["website_check"] is None and data["website_issues"] == []
    assert db.session.get(Business, lead.id).website_check is None


def test_csv_has_new_columns(client, lead):
    csv_text = client.get("/api/businesses/export").get_data(as_text=True)
    header = csv_text.splitlines()[0]
    for column in ("whatsapp", "website_issues", "latest_review_date", "recent_owner_replies", "price_level"):
        assert column in header
    assert "3 of 10" in csv_text
    assert "No HTTPS" in csv_text


# ---------- Message templates ----------


def test_template_crud(client):
    assert client.get("/api/templates").get_json() == []
    created = client.post("/api/templates", json={"name": "Intro", "body": "Hi {name}!"})
    assert created.status_code == 201
    tid = created.get_json()["id"]

    updated = client.patch(f"/api/templates/{tid}", json={"body": "Hello {name}"}).get_json()
    assert (updated["name"], updated["body"]) == ("Intro", "Hello {name}")

    assert client.post("/api/templates", json={"name": " ", "body": "x"}).status_code == 400
    assert client.patch(f"/api/templates/{tid}", json={"body": ""}).status_code == 400
    assert client.delete(f"/api/templates/{tid}").status_code == 204
    assert client.delete(f"/api/templates/{tid}").status_code == 404
    assert db.session.query(MessageTemplate).count() == 0


def test_templates_page_renders(client):
    page = client.get("/templates").get_data(as_text=True)
    assert "Message templates" in page and "{name}" in page
