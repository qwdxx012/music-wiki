import re


def test_index_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.content_type


def test_about_page(client):
    response = client.get("/about")
    assert response.status_code == 200


def test_unknown_page_returns_404(client):
    response = client.get("/no-such-page")
    assert response.status_code == 404


def test_invalid_mbid_returns_404(client):
    # Неверный идентификатор отсекается без запроса к MusicBrainz
    response = client.get("/artist/not-a-mbid")
    assert response.status_code == 404


def test_empty_search_redirects_to_index(client):
    response = client.get("/search?q=")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")


def test_num_filter(app):
    assert app.jinja_env.filters["num"](1000) == "1 000"
    num = app.jinja_env.filters["num"]
    assert num(1234567) == "1 234 567"
    assert num("abc") == "abc"


def test_recognize_page_opens(client):
    response = client.get("/recognize")
    assert response.status_code in (200, 302)


def test_about_page_is_html(client):
    response = client.get("/about")
    assert "text/html" in response.content_type


def test_index_has_base_seo_tags(client):
    html = client.get("/").get_data(as_text=True)
    assert '<html lang="ru">' in html
    assert '<meta charset="utf-8">' in html
    assert '<meta name="viewport"' in html
    assert "<title>" in html
    assert '<meta name="description"' in html
    assert '<link rel="canonical"' in html
    assert '<meta property="og:title"' in html


def test_index_has_one_h1(client):
    html = client.get("/").get_data(as_text=True)
    assert len(re.findall(r"<h1\b", html)) == 1


def test_about_has_one_h1(client):
    html = client.get("/about").get_data(as_text=True)
    assert len(re.findall(r"<h1\b", html)) == 1
    assert "О проекте Music Wiki" in html


def test_robots_txt(client):
    response = client.get("/robots.txt")
    assert response.status_code == 200
    assert "text/plain" in response.content_type
    text = response.get_data(as_text=True)
    assert "User-agent: *" in text
    assert "Disallow: /search" in text
    assert "Sitemap: https://example.com/sitemap.xml" in text


def test_sitemap_xml(client):
    response = client.get("/sitemap.xml")
    assert response.status_code == 200
    assert "application/xml" in response.content_type
    text = response.get_data(as_text=True)
    assert "<urlset" in text
    assert "<loc>https://example.com/</loc>" in text
    assert "<loc>https://example.com/about</loc>" in text


def test_sitemap_adds_artist_and_track_from_db(app, client):
    store = app.extensions["wiki_store"]
    artist_id = "11111111-1111-1111-1111-111111111111"
    track_id = "22222222-2222-2222-2222-222222222222"
    store.upsert_artist({"id": artist_id, "name": "Test Artist"})
    store.upsert_track({"id": track_id, "title": "Test Track"})

    text = client.get("/sitemap.xml").get_data(as_text=True)
    assert f"https://example.com/artist/{artist_id}" in text
    assert f"https://example.com/track/{track_id}" in text


def test_search_results_have_noindex(client, monkeypatch):
    from routes import main as main_routes

    monkeypatch.setattr(main_routes.mb, "search_recordings", lambda *args, **kwargs: [])
    response = client.get("/search?q=test")
    assert response.status_code == 200
    assert '<meta name="robots" content="noindex, nofollow">' in response.get_data(as_text=True)


def test_error_page_has_noindex(client):
    html = client.get("/no-such-page").get_data(as_text=True)
    assert '<meta name="robots" content="noindex, nofollow">' in html
    assert len(re.findall(r"<h1\b", html)) == 1


def test_recognize_json_has_x_robots_tag(client):
    response = client.post("/recognize", headers={"X-Requested-With": "fetch"})
    assert response.status_code == 400
    assert response.headers["X-Robots-Tag"] == "noindex, nofollow"


def test_recognize_dialog_has_noindex(client):
    response = client.post("/recognize")
    assert response.status_code == 400
    assert '<meta name="robots" content="noindex, nofollow">' in response.get_data(as_text=True)
