import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-change-me")

    # Публичный адрес сайта для canonical, robots.txt и sitemap.xml.
    # Пока своего домена нет, используем заглушку из задания.
    SITE_URL = os.getenv("SITE_URL", "https://example.com").rstrip("/")

    LASTFM_API_KEY = os.getenv("LASTFM_API_KEY", "")
    # MusicBrainz просит указывать в User-Agent имя приложения и контакт,
    # иначе может начать отвечать 403/503 на наши запросы
    MB_CONTACT = os.getenv("MB_CONTACT", "you@example.com")
    MB_USER_AGENT = f"MusicWiki/1.0 ( {MB_CONTACT} )"

    # Supabase: PostgreSQL-база проекта и REST API (PostgREST).
    # URL проекта и ключ service_role хранятся только в .env
    SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
    # Сырые ответы MusicBrainz меняются редко, поэтому храним их неделю
    MB_CACHE_TTL = int(os.getenv("MB_CACHE_TTL", 7 * 24 * 3600))
    LASTFM_CACHE_TTL = int(os.getenv("LASTFM_CACHE_TTL", 24 * 3600))

    # Статика (CSS, JS, PNG) между запросами не меняется, поэтому браузер
    # может держать её в кэше час и не перекачивать при каждом переходе
    SEND_FILE_MAX_AGE_DEFAULT = int(os.getenv("STATIC_CACHE_SECONDS", 3600))

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
