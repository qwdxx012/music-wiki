import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-change-me")

    LASTFM_API_KEY = os.getenv("LASTFM_API_KEY", "")
    # MusicBrainz просит указывать в User-Agent имя приложения и контакт,
    # иначе может начать отвечать 403/503 на наши запросы
    MB_CONTACT = os.getenv("MB_CONTACT", "you@example.com")
    MB_USER_AGENT = f"MusicWiki/1.0 ( {MB_CONTACT} )"

    CACHE_DB = os.getenv("CACHE_DB", str(BASE_DIR / "instance" / "cache.sqlite3"))
    # Структурированная предметная БД (artists/albums/tracks/genres/facts/...),
    # отдельно от технического key-value кэша выше. См. db/schema.sql
    WIKI_DB = os.getenv("WIKI_DB", str(BASE_DIR / "instance" / "wiki.sqlite3"))
    # Сырые ответы MusicBrainz меняются редко, поэтому храним их неделю
    MB_CACHE_TTL = int(os.getenv("MB_CACHE_TTL", 7 * 24 * 3600))
    LASTFM_CACHE_TTL = int(os.getenv("LASTFM_CACHE_TTL", 24 * 3600))

    # Таймаут на КАЖДЫЙ запрос к MusicBrainz и Last.fm, секунды:
    # если сервис завис, страница не будет висеть вместе с ним
    HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", 5))
    # Готовая страница артиста (MusicBrainz + Last.fm) целиком: 24 часа
    ARTIST_PAGE_TTL = int(os.getenv("ARTIST_PAGE_TTL", 24 * 3600))

    # AudD (https://dashboard.audd.io), бесплатно 300 запросов
    AUDD_API_TOKEN = os.getenv("AUDD_API_TOKEN", "")
    # Распознавание идёт дольше обычного запроса, поэтому таймаут больше
    AUDD_TIMEOUT = int(os.getenv("AUDD_TIMEOUT", 30))
    AUDD_CACHE_TTL = int(os.getenv("AUDD_CACHE_TTL", 30 * 24 * 3600))
    # AudD не принимает файлы больше 10 МБ. Flask сам отклонит такой запрос
    # (ошибка 413) ещё до того, как мы потратим на него лимит AudD
    MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", 10))
    MAX_CONTENT_LENGTH = MAX_UPLOAD_MB * 1024 * 1024
