"""Клиент Last.fm API: биография, похожие артисты, обложки, топы по тегам.

Договорённость для вызывающего кода:
- ключ не задан или "не найдено" (код 6)   -> функции возвращают None / []
- таймаут, сеть, неверный ключ, лимит      -> бросается LastFMError
Роуты оборачивают вызовы в safe(), поэтому LastFMError превращается
в плашку "Last.fm временно недоступен", а не в ошибку 500.
"""

import html
import logging
import re
from urllib.parse import urlencode

import requests
from flask import current_app

log = logging.getLogger(__name__)

LASTFM_ROOT = "https://ws.audioscrobbler.com/2.0/"
# С 2019 года Last.fm вместо фото артистов отдаёт одну и ту же картинку-звёздочку.
# Узнаём её по хэшу в URL и считаем, что фото нет
PLACEHOLDER_HASH = "2a96cbd8b46e442fc41c2b86b821562f"
NOT_FOUND_TTL = 6 * 3600

# https://www.last.fm/api/errorcodes
ERROR_TEXT = {
    10: "неверный API-ключ",
    26: "API-ключ заблокирован",
    29: "превышен лимит запросов (rate limit)",
    11: "сервис временно недоступен",
    16: "временная ошибка, повторите позже",
    8: "внутренняя ошибка Last.fm",
}


class LastFMError(Exception):
    """Last.fm недоступен или отказал. Текст содержит точную причину."""


def _call(method, **params):
    cfg = current_app.config
    api_key = cfg.get("LASTFM_API_KEY")
    if not api_key:
        return None

    params = {k: v for k, v in params.items() if v}
    params.update(method=method, format="json")
    cache = current_app.extensions["disk_cache"]
    # Параметры сортируем, чтобы один и тот же запрос всегда давал один ключ.
    # API-ключ добавляется только в сам запрос, в базу кэша он не попадает
    key = "lfm:" + urlencode(sorted(params.items()))

    cached = cache.get(key)
    if cached is not None:
        # {"__error__": 6} - запомненное "не найдено", в сеть не идём
        return None if "__error__" in cached else cached

    timeout = cfg["HTTP_TIMEOUT"]
    try:
        resp = requests.get(
            LASTFM_ROOT,
            params={**params, "api_key": api_key},
            headers={"User-Agent": cfg["MB_USER_AGENT"]},
            # 5 секунд: если Last.fm тормозит, страница покажет остальное без него
            timeout=timeout,
        )
    except requests.Timeout as exc:
        raise LastFMError(f"Last.fm {method}: таймаут {timeout} с") from exc
    except requests.RequestException as exc:
        raise LastFMError(f"Last.fm {method}: сетевая ошибка: {exc}") from exc

    if resp.status_code == 429:
        raise LastFMError(f"Last.fm {method}: HTTP 429, rate limit")
    try:
        data = resp.json()
    except ValueError as exc:
        raise LastFMError(
            f"Last.fm {method}: HTTP {resp.status_code}, ответ не JSON"
        ) from exc

    # Last.fm сообщает об ошибках полем "error" в JSON, иногда даже с HTTP 200
    if isinstance(data, dict) and "error" in data:
        code = data.get("error")
        if code == 6:
            # "Не найдено" запоминаем на 6 часов, чтобы не спрашивать снова
            cache.set(key, {"__error__": 6}, NOT_FOUND_TTL)
            return None
        reason = ERROR_TEXT.get(code, data.get("message") or "неизвестная ошибка")
        raise LastFMError(
            f"Last.fm {method}: {reason} (код {code}, HTTP {resp.status_code})"
        )
    if not resp.ok:
        raise LastFMError(f"Last.fm {method}: HTTP {resp.status_code}")

    cache.set(key, data, cfg["LASTFM_CACHE_TTL"])
    return data


def _as_list(value):
    # Last.fm возвращает один элемент как объект, а несколько - как список
    if not value:
        return []
    return value if isinstance(value, list) else [value]


def _image(images, sizes=("extralarge", "large", "medium")):
    by_size = {
        i.get("size"): i.get("#text") for i in _as_list(images) if isinstance(i, dict)
    }
    for size in sizes:
        url = by_size.get(size)
        if url and PLACEHOLDER_HASH not in url:
            return url
    return None


def _clean_text(raw):
    """HTML из Last.fm -> список абзацев чистого текста."""
    if not raw:
        return []
    text = re.sub(r"<a [^>]*>\s*Read more on Last\.fm\s*</a>\.?", "", raw, flags=re.I)
    text = re.sub(r"User-contributed text is available.*$", "", text, flags=re.I | re.S)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    return [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]


def _tags(block):
    tags = _as_list((block or {}).get("tag"))
    return [t.get("name") for t in tags if t.get("name")][:6]


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def artist_info(name):
    data = _call("artist.getInfo", artist=name, autocorrect=1, lang="ru")
    artist = (data or {}).get("artist")
    if artist and not (artist.get("bio") or {}).get("content", "").strip():
        # Русской биографии нет: делаем второй запрос без lang и берём английскую
        english = _call("artist.getInfo", artist=name, autocorrect=1) or {}
        artist = english.get("artist") or artist
    if not artist:
        return None

    bio = artist.get("bio") or {}
    summary = _clean_text(bio.get("summary"))
    content = _clean_text(bio.get("content"))
    return {
        "name": artist.get("name"),
        "url": artist.get("url"),
        "image": _image(artist.get("image")),
        "listeners": (artist.get("stats") or {}).get("listeners"),
        "playcount": (artist.get("stats") or {}).get("playcount"),
        "tags": _tags(artist.get("tags")),
        "summary": summary,
        # "Читать полностью" показываем, только если полный текст длиннее краткого
        "content": content if len(content) > len(summary) else [],
    }


def similar_artists(name, limit=12):
    data = _call("artist.getSimilar", artist=name, autocorrect=1, limit=limit)
    items = _as_list(((data or {}).get("similarartists") or {}).get("artist"))
    out = []
    for a in items:
        try:
            # Last.fm даёт похожесть долей от 0 до 1, нам нужны проценты
            match = round(float(a.get("match") or 0) * 100)
        except (TypeError, ValueError):
            match = 0
        out.append(
            {
                "name": a.get("name", "?"),
                "mbid": a.get("mbid") or None,
                "match": match,
                "url": a.get("url"),
                "image": _image(a.get("image")),
            }
        )
    return out


def track_info(artist, title):
    data = _call("track.getInfo", artist=artist, track=title, autocorrect=1)
    track = (data or {}).get("track")
    if not track:
        return None
    album = track.get("album") or {}
    return {
        "url": track.get("url"),
        "album": album.get("title"),
        "image": _image(album.get("image")),
        "listeners": track.get("listeners"),
        "playcount": track.get("playcount"),
        "tags": _tags(track.get("toptags")),
        "summary": _clean_text((track.get("wiki") or {}).get("summary")),
    }


def tag_top_artists(tag, limit=30):
    data = _call("tag.getTopArtists", tag=tag, limit=limit)
    items = _as_list(((data or {}).get("topartists") or {}).get("artist"))
    return [
        {
            "name": a.get("name", "?"),
            "mbid": a.get("mbid") or None,
            "rank": _int((a.get("@attr") or {}).get("rank")),
        }
        for a in items
    ]


def tag_top_tracks(tag, limit=30):
    data = _call("tag.getTopTracks", tag=tag, limit=limit)
    items = _as_list(((data or {}).get("tracks") or {}).get("track"))
    out = []
    for t in items:
        artist = t.get("artist") or {}
        out.append(
            {
                "title": t.get("name", "?"),
                "mbid": t.get("mbid") or None,
                "artist": artist.get("name", "?"),
                "artist_mbid": artist.get("mbid") or None,
                "duration": _int(t.get("duration")),
                "rank": _int((t.get("@attr") or {}).get("rank")),
            }
        )
    return out
