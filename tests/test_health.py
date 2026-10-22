def test_health_ok(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "database": "ok"}


def test_swagger_docs_available(client):
    assert client.get("/api/docs").status_code == 200
    assert client.get("/api/swagger.json").status_code == 200


def test_pages_render(client):
    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert b"Start searching" in dashboard.data
    assert b'"callOutcomes"' in dashboard.data
    assert b"theme-toggle" in dashboard.data

    listing = client.get("/businesses")
    assert listing.status_code == 200
    assert b"Export to Excel (CSV)" in listing.data

    assert client.get("/businesses/999").status_code == 404
    assert client.get("/static/web/js/app.js").status_code == 200
