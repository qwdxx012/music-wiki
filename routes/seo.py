"""robots.txt и sitemap.xml для поисковых роботов."""

from xml.sax.saxutils import escape

from flask import Blueprint, Response, current_app, url_for

bp = Blueprint("seo", __name__)


def _site_url():
    return current_app.config["SITE_URL"].rstrip("/")


def _lastmod(value):
    # В базе дата хранится как ISO-строка, для sitemap нужен только день
    if value and len(value) >= 10:
        return value[:10]
    return None


@bp.route("/robots.txt")
def robots_txt():
    site = _site_url()
    lines = [
        "User-agent: *",
        "Disallow: /search",
        "Disallow: /random",
        "Disallow: /track/lookup",
        "Disallow: /artist/lookup",
        "Disallow: /api/",
        "",
        "User-agent: Yandex",
        "Disallow: /search",
        "Disallow: /random",
        "Disallow: /track/lookup",
        "Disallow: /artist/lookup",
        "Disallow: /api/",
        "Clean-param: utm_source&utm_medium&utm_campaign&utm_content&utm_term",
        "",
        f"Sitemap: {site}/sitemap.xml",
        "",
    ]
    return Response("\n".join(lines), mimetype="text/plain")


@bp.route("/sitemap.xml")
def sitemap_xml():
    site = _site_url()
    urls = [
        {"loc": f"{site}{url_for('main.index')}"},
        {"loc": f"{site}{url_for('main.about')}"},
        {"loc": f"{site}{url_for('recognize.recognize')}"},
    ]

    # Карточки артистов и треков появляются в базе после открытия страниц,
    # поэтому sitemap собираем из базы, а не держим ручной список.
    store = current_app.extensions.get("wiki_store")
    if store:
        try:
            with store.connect() as con:
                artists = con.execute(
                    "SELECT mbid, updated_at FROM artists ORDER BY name"
                ).fetchall()
                tracks = con.execute(
                    "SELECT mbid, updated_at FROM tracks ORDER BY title"
                ).fetchall()
        except Exception:  # noqa: BLE001
            current_app.logger.error("Не удалось собрать sitemap.xml", exc_info=True)
        else:
            for mbid, updated_at in artists:
                urls.append(
                    {
                        "loc": f"{site}{url_for('main.artist', mbid=mbid)}",
                        "lastmod": _lastmod(updated_at),
                    }
                )
            for mbid, updated_at in tracks:
                urls.append(
                    {
                        "loc": f"{site}{url_for('main.track', mbid=mbid)}",
                        "lastmod": _lastmod(updated_at),
                    }
                )

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for item in urls:
        lines.append("  <url>")
        lines.append(f"    <loc>{escape(item['loc'])}</loc>")
        if item.get("lastmod"):
            lines.append(f"    <lastmod>{item['lastmod']}</lastmod>")
        lines.append("  </url>")
    lines.append("</urlset>")

    return Response("\n".join(lines), mimetype="application/xml")
