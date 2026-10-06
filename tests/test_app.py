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
    num = app.jinja_env.filters["num"]
    assert num(1234567) == "1 234 567"
    assert num("abc") == "abc"


def test_recognize_page_opens(client):
    response = client.get("/recognize")
    assert response.status_code in (200, 302)


def test_about_page_is_html(client):
    response = client.get("/about")
    assert "text/html" in response.content_type
