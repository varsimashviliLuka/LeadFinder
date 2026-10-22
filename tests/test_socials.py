import pytest

from app.extensions import db
from app.models import Business, SocialProfile
from app.services import socials
from app.services.socials import PageFetchError, classify_social_url, extract_social_links, find_contact_pages

TBILISI = {"latitude": 41.7151, "longitude": 44.8271}


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://www.instagram.com/royal.dent/", ("instagram", "https://www.instagram.com/royal.dent/")),
        ("instagram.com/Royal.Dent?igsh=abc", ("instagram", "https://www.instagram.com/royal.dent/")),
        ("https://m.facebook.com/RoyalDent/about", ("facebook", "https://www.facebook.com/royaldent")),
        ("https://web.facebook.com/pg/RoyalDent/posts", ("facebook", "https://www.facebook.com/royaldent")),
        ("https://www.facebook.com/profile.php?id=1000123", ("facebook", "https://www.facebook.com/profile.php?id=1000123")),
        ("https://www.tiktok.com/@royal_dent/video/123", ("tiktok", "https://www.tiktok.com/@royal_dent")),
        ("https://www.instagram.com/p/Cx123/", None),
        ("https://www.facebook.com/sharer/sharer.php?u=x", None),
        ("https://www.facebook.com/groups/tbilisi", None),
        ("https://www.facebook.com/wix", None),
        ("https://www.tiktok.com/discover/salon", None),
        ("https://www.instagram.com/", None),
        ("https://notinstagram.com/royal", None),
        ("javascript:alert(1)", None),
        ("", None),
    ],
)
def test_classify_social_url(url, expected):
    link = classify_social_url(url)
    assert (link and (link.platform, link.url)) == (expected or None)


def test_extract_prefers_real_links_and_skips_share_buttons():
    html = """
      <footer>
        <a href="https://www.facebook.com/sharer/sharer.php?u=https://site.ge">Share</a>
        <a href="https://www.facebook.com/RoyalDent">Facebook</a>
        <a href="https://instagram.com/royal.dent">Instagram</a>
      </footer>
      <script>var cfg = {"theme": "https:\\/\\/www.facebook.com\\/SomeTheme"};</script>
      <script>window.tt = "https://www.tiktok.com/@royal_dent";</script>
    """
    links = extract_social_links(html)
    assert links["facebook"].url == "https://www.facebook.com/royaldent"
    assert links["instagram"].handle == "royal.dent"
    assert links["tiktok"].url == "https://www.tiktok.com/@royal_dent"


def test_find_contact_pages_same_site_only():
    html = """
      <a href="/contact">Contact</a>
      <a href="/ka/chven-shesakheb">ჩვენ შესახებ</a>
      <a href="https://other.ge/contact">Partner</a>
      <a href="#contact">Jump</a>
      <a href="/menu">Menu</a>
    """
    assert find_contact_pages(html, "https://www.site.ge/") == [
        "https://www.site.ge/contact",
        "https://www.site.ge/ka/chven-shesakheb",
    ]


@pytest.mark.parametrize(
    "html, expected",
    [
        ("<html><script> document.location.href='http://site.ge/ge/index';</script></html>", "http://site.ge/ge/index"),
        ('<meta http-equiv="refresh" content="0; url=/ka/">', "https://site.ge/ka/"),
        ("<script>window.location.replace('/en')</script>", "https://site.ge/en"),
        ("<html><body>Hello</body></html>", None),
    ],
)
def test_client_redirect_target(html, expected):
    assert socials.client_redirect_target(html, "https://site.ge/") == expected


def test_linktree_own_accounts_are_ignored():
    html = '<a href="https://instagram.com/salon.ge">ig</a><a href="https://www.tiktok.com/@linktr.ee">Linktree</a>'
    assert set(extract_social_links(html)) == {"instagram"}


def make_finder(app, pages):
    """A SocialFinder whose downloads come from a dict instead of the internet."""
    requested = []

    def fake_fetch(client, url):
        requested.append(url)
        page = pages.get(url)
        if isinstance(page, Exception):
            raise page
        if page is None:
            raise PageFetchError("Website returned an error (HTTP 404)")
        return url, page

    return requested, fake_fetch


def test_finder_listing_is_social_profile_without_fetching(app, monkeypatch):
    requested, fake_fetch = make_finder(app, {})
    monkeypatch.setattr(socials, "fetch_page", fake_fetch)
    with socials.SocialFinder(app.config) as finder:
        check = finder.find("https://www.instagram.com/royal.dent/")
    assert requested == []
    link, source = check.links["instagram"]
    assert (link.handle, source) == ("royal.dent", "google_maps")


def test_finder_checks_contact_page_for_missing_platforms(app, monkeypatch):
    requested, fake_fetch = make_finder(
        app,
        {
            "https://site.ge/": '<a href="https://facebook.com/SiteGe">fb</a><a href="/contact">Contact us</a>',
            "https://site.ge/contact": '<a href="https://instagram.com/site.ge">ig</a>',
        },
    )
    monkeypatch.setattr(socials, "fetch_page", fake_fetch)
    with socials.SocialFinder(app.config) as finder:
        check = finder.find("https://site.ge/")
    assert requested == ["https://site.ge/", "https://site.ge/contact"]
    assert {p: source for p, (_, source) in check.links.items()} == {"facebook": "website", "instagram": "website"}
    assert check.pages_checked == 2


def test_finder_follows_javascript_redirect(app, monkeypatch):
    requested, fake_fetch = make_finder(
        app,
        {
            "https://site.ge/": "<script>location.href='/ge/index'</script>",
            "https://site.ge/ge/index": '<a href="https://www.facebook.com/SiteGe">fb</a>',
        },
    )
    monkeypatch.setattr(socials, "fetch_page", fake_fetch)
    with socials.SocialFinder(app.config) as finder:
        check = finder.find("https://site.ge/")
    assert requested == ["https://site.ge/", "https://site.ge/ge/index"]
    assert check.links["facebook"][0].handle == "sitege"


def test_finder_reports_unreachable_site(app, monkeypatch):
    _, fake_fetch = make_finder(app, {"https://down.ge/": PageFetchError("Website took too long to respond")})
    monkeypatch.setattr(socials, "fetch_page", fake_fetch)
    with socials.SocialFinder(app.config) as finder:
        check = finder.find("https://down.ge/")
    assert check.links == {}
    assert check.error == "Website took too long to respond"


def test_fetch_page_refuses_private_addresses(app):
    with socials.SocialFinder(app.config) as finder:
        with pytest.raises(PageFetchError, match="private network"):
            socials.fetch_page(finder.client, "http://127.0.0.1:5000/")


def test_search_with_find_socials_runs_second_stage(client, monkeypatch):
    def fake_fetch(client_, url):
        handle = url.split("//")[1].split(".")[0].replace("-", "_")
        return url, f'<a href="https://www.instagram.com/{handle}">ig</a>'

    monkeypatch.setattr(socials, "fetch_page", fake_fetch)
    job = client.post(
        "/api/searches", json={"query": "cafe", **TBILISI, "max_results": 10, "find_socials": True}
    ).get_json()

    assert job["status"] == "completed"
    assert job["stage"] == "socials"
    assert job["socials_total"] == 10
    assert job["socials_checked"] == 10
    with_site = db.session.query(Business).filter(Business.website.isnot(None)).count()
    assert job["socials_found"] == with_site > 0
    assert db.session.query(Business).filter(Business.social_checked_at.is_(None)).count() == 0

    found = client.get("/api/businesses?social=instagram&per_page=100").get_json()
    assert found["total"] == with_site
    assert found["items"][0]["social_profiles"][0]["source"] == "website"
    none = client.get("/api/businesses?social=none&per_page=100").get_json()
    assert none["total"] == 10 - with_site

    # A repeat search doesn't look up the same businesses again.
    again = client.post(
        "/api/searches", json={"query": "cafe", **TBILISI, "max_results": 10, "find_socials": True}
    ).get_json()
    assert again["socials_total"] == 0


def test_search_without_find_socials_skips_lookup(client, monkeypatch):
    monkeypatch.setattr(socials, "fetch_page", lambda *a: pytest.fail("should not fetch"))
    job = client.post("/api/searches", json={"query": "cafe", **TBILISI, "max_results": 3}).get_json()
    assert job["stage"] == "maps"
    assert job["find_socials"] is False
    assert client.get("/api/businesses?social=unchecked").get_json()["total"] == 3


def test_find_socials_must_be_boolean(client):
    response = client.post("/api/searches", json={"query": "cafe", **TBILISI, "find_socials": "yes"})
    assert response.status_code == 400


@pytest.fixture
def business(app):
    b = Business(place_id="p1", name="Royal Dent", website="https://www.instagram.com/royal.dent/")
    db.session.add(b)
    db.session.commit()
    return b


def test_find_endpoint_for_one_business(client, business):
    response = client.post(f"/api/businesses/{business.id}/socials/find")
    assert response.status_code == 200
    data = response.get_json()
    assert data["added"] == 1 and data["error"] is None
    assert data["business"]["social_profiles"][0]["url"] == "https://www.instagram.com/royal.dent/"
    assert data["business"]["social_checked_at"]

    assert client.post(f"/api/businesses/{business.id}/socials/find").get_json()["added"] == 0
    assert client.post("/api/businesses/999/socials/find").status_code == 404


def test_add_and_remove_manual_profile(client, business):
    url = f"/api/businesses/{business.id}/socials"
    response = client.post(url, json={"url": "tiktok.com/@RoyalDent"})
    assert response.status_code == 201
    profile = response.get_json()["social_profiles"][0]
    assert (profile["platform"], profile["source"]) == ("tiktok", "manual")

    assert client.post(url, json={"url": "https://www.tiktok.com/@royaldent"}).status_code == 400
    assert client.post(url, json={"url": "https://royaldent.ge"}).status_code == 400
    assert client.post(url, json={}).status_code == 400

    other = Business(place_id="p2", name="Other")
    db.session.add(other)
    db.session.commit()
    assert client.delete(f"/api/businesses/{other.id}/socials/{profile['id']}").status_code == 404

    remaining = client.delete(f"{url}/{profile['id']}").get_json()
    assert remaining["social_profiles"] == []
    assert db.session.query(SocialProfile).count() == 0


def test_changing_website_allows_a_new_lookup(client, business):
    client.post(f"/api/businesses/{business.id}/socials/find")
    data = client.patch(f"/api/businesses/{business.id}", json={"website": "https://royaldent.ge"}).get_json()
    assert data["social_checked_at"] is None


def test_csv_and_stats_include_social(client, business):
    client.post(f"/api/businesses/{business.id}/socials/find")
    csv_text = client.get("/api/businesses/export").get_data(as_text=True)
    header, row = csv_text.lstrip("\ufeff").splitlines()[:2]
    assert "instagram" in header.split(",")
    assert "https://www.instagram.com/royal.dent/" in row

    stats = client.get("/api/businesses/stats").get_json()
    assert stats["with_social"] == 1 and stats["social_unchecked"] == 0
