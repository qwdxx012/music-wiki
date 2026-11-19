import logging
import random
from datetime import datetime

from flask import Flask, request
from supabase import create_client
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config
from routes.main import bp as main_bp
from routes.recognize import bp as recognize_bp
from routes.seo import bp as seo_bp
from services.cache import DiskCache
from services.store import WikiStore
from services.quotes import MUSIC_QUOTES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # nginx передает исходный домен и протокол в X-Forwarded-*.
    # Без ProxyFix Flask считает, что запрос пришел по HTTP на внутренний адрес
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # Один клиент Supabase на всё приложение: и кэш, и предметная база
    # работают через него. Без ключей сайт всё равно открывается, но
    # данные не сохраняются - в лог попадает предупреждение
    supabase_url = app.config["SUPABASE_URL"]
    supabase_key = app.config["SUPABASE_KEY"]
    supabase = None
    if supabase_url and supabase_key:
        supabase = create_client(supabase_url, supabase_key)
    else:
        logging.getLogger(__name__).warning(
            "SUPABASE_URL и SUPABASE_KEY не заданы: база Supabase отключена"
        )
    app.extensions["supabase"] = supabase
    # Key-value кэш ответов внешних API
    app.extensions["disk_cache"] = DiskCache(supabase)
    # Структурированная база проекта (db/supabase_schema.sql)
    app.extensions["wiki_store"] = WikiStore(supabase)

    app.register_blueprint(main_bp)
    app.register_blueprint(recognize_bp)
    app.register_blueprint(seo_bp)

    @app.after_request
    def add_api_noindex(response):
        # JSON-ответы и адреса /api/ не должны попадать в поиск
        if request.path.startswith("/api/") or response.mimetype == "application/json":
            response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response

    @app.template_filter("num")
    def num_filter(value):
        """1234567 -> '1 234 567'"""
        try:
            return f"{int(value):,}".replace(",", " ")
        except (TypeError, ValueError):
            return value

    @app.context_processor
    def inject_globals():
        # Эти переменные доступны в любом шаблоне без передачи из каждого роута
        return {
            "now": datetime.now(),
            "site_url": app.config["SITE_URL"].rstrip("/"),
            "lastfm_enabled": bool(app.config["LASTFM_API_KEY"]),
            "audd_enabled": bool(app.config["AUDD_API_TOKEN"]),
            "max_upload_mb": app.config["MAX_UPLOAD_MB"],
            # Цитата для подсказки маскота: сервер кладёт одну случайную
            # (её видно даже без JS), а весь список отдаёт в JS, чтобы при
            # каждом наведении показывалась новая без перезагрузки страницы
            "mascot_quote": random.choice(MUSIC_QUOTES),
            "music_quotes": MUSIC_QUOTES,
        }

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
