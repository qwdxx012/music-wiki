import logging
import random
from datetime import datetime

from flask import Flask

from config import Config
from routes.main import bp as main_bp
from routes.recognize import bp as recognize_bp
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

    # Один объект кэша на всё приложение. Сервисы достают его через
    # current_app.extensions, чтобы не открывать базу в каждом модуле заново
    app.extensions["disk_cache"] = DiskCache(app.config["CACHE_DB"])
    # Структурированная реляционная БД проекта (db/schema.sql), отдельно
    # от технического кэша выше
    app.extensions["wiki_store"] = WikiStore(app.config["WIKI_DB"])

    app.register_blueprint(main_bp)
    app.register_blueprint(recognize_bp)

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
