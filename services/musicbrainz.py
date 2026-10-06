"""Клиент MusicBrainz API: ограничение 1 запрос/с, кэш в SQLite, разбор ответов."""

import logging
import re
import threading
import time
from urllib.parse import urlencode

import requests
from flask import current_app

MB_ROOT = "https://musicbrainz.org/ws/2"
# Правила MusicBrainz: не чаще 1 запроса в секунду с одного IP.
# Берём 1.1 с, чтобы небольшая погрешность часов не приводила к бану
MIN_INTERVAL = 1.1

log = logging.getLogger(__name__)
_rate_lock = threading.Lock()
_last_call = 0.0


class MusicBrainzError(Exception):
    """MusicBrainz недоступен или вернул ошибку."""


class MBNotFound(MusicBrainzError):
    """Сущность с таким MBID не найдена."""


class MBBadQuery(MusicBrainzError):
    """MusicBrainz не понял поисковый запрос (HTTP 400)."""


# ---------- справочники ----------

ARTIST_TYPE_RU = {
    "Person": "Персона",
    "Group": "Группа",
    "Orchestra": "Оркестр",
    "Choir": "Хор",
    "Character": "Персонаж",
    "Other": "Другое",
}
RG_TYPE_RU = {
    "Album": "Альбом",
    "EP": "EP",
    "Single": "Сингл",
    "Broadcast": "Эфир",
    "Other": "Другое",
    "Compilation": "Сборник",
    "Live": "Концертный",
    "Soundtrack": "Саундтрек",
    "Remix": "Ремиксы",
    "Demo": "Демо",
    "Interview": "Интервью",
    "Spokenword": "Разговорный",
}
ROLE_RU = {
    "producer": "продюсер",
    "engineer": "инженер",
    "audio": "аудиоинженер",
    "mix": "сведение",
    "recording": "звукозапись",
    "mastering": "мастеринг",
    "programming": "программирование",
    "sound": "звук",
    "editor": "монтаж",
    "balance": "баланс",
    "instrument": "инструмент",
    "vocal": "вокал",
    "performer": "исполнитель",
    "performing orchestra": "оркестр",
    "conductor": "дирижёр",
    "chorus master": "хормейстер",
    "concertmaster": "концертмейстер",
    "arranger": "аранжировщик",
    "instrument arranger": "аранжировка",
    "vocal arranger": "аранжировка вокала",
    "orchestrator": "оркестровка",
    "remixer": "ремикс",
    "misc": "прочее",
    "composer": "композитор",
    "lyricist": "автор текста",
    "writer": "автор",
    "librettist": "либреттист",
    "recorded at": "запись",
    "mixed at": "сведение",
    "mastered at": "мастеринг",
    "edited at": "монтаж",
    "engineered at": "инженерия",
    "produced at": "продюсирование",
}
PERFORMER_TYPES = {
    "instrument",
    "vocal",
    "performer",
    "performing orchestra",
    "conductor",
    "chorus master",
    "concertmaster",
}
ENGINEER_TYPES = {
    "engineer",
    "audio",
    "mix",
    "recording",
    "mastering",
    "programming",
    "sound",
    "editor",
    "balance",
}
WRITER_TYPES = {"composer", "lyricist", "writer", "librettist"}

# inc = какие связанные данные MusicBrainz положит в ответ сразу,
# чтобы не делать отдельный запрос на студии, авторов и жанры
REC_INC = (
    "artists+releases+release-groups+artist-rels+place-rels"
    "+work-rels+work-level-rels+genres+tags"
)
ARTIST_INC = "genres+tags+artist-rels"

# Если в запросе есть "artist:", "rgid:" и т.п., пользователь пишет на языке
# запросов MusicBrainz сам, и экранировать ничего нельзя
ADVANCED_FIELDS = re.compile(
    r"\b(artist|recording|release|rgid|arid|reid|rid|tag|date|firstreleasedate"
    r"|begin|country|isrc|type|status|primarytype):",
    re.I,
)
LUCENE_SPECIAL = re.compile(r'([+\-&|!(){}\[\]^"~*?:\\/])')


# ---------- HTTP ----------


def _cache():
    return current_app.extensions["disk_cache"]


def _get(path, **params):
    """GET к MusicBrainz с кэшем, ограничением скорости и понятными ошибками.

    Порядок: 1) смотрим кэш; 2) если пусто, ждём, пока с прошлого запроса
    пройдёт 1.1 с; 3) делаем запрос с таймаутом; 4) успешный ответ кладём в кэш.
    Любая проблема превращается в MusicBrainzError с человеческим текстом.
    """
    params["fmt"] = "json"
    key = "mb:" + path + "?" + urlencode(sorted(params.items()))
    cached = _cache().get(key)
    if cached is not None:
        return cached

    global _last_call
    cfg = current_app.config
    timeout = cfg["HTTP_TIMEOUT"]
    resp = None
    # Замок общий для всех потоков: даже если страница артиста параллельно
    # просит дискографию и карточку, в MusicBrainz они уйдут строго по очереди
    with _rate_lock:
        for attempt in (1, 2):
            wait = MIN_INTERVAL - (time.monotonic() - _last_call)
            if wait > 0:
                time.sleep(wait)
            try:
                resp = requests.get(
                    MB_ROOT + path,
                    params=params,
                    headers={
                        "User-Agent": cfg["MB_USER_AGENT"],
                        "Accept": "application/json",
                    },
                    # таймаут 5 с, чтобы страница не висела, если MusicBrainz не отвечает
                    timeout=timeout,
                )
            except requests.Timeout as exc:
                raise MusicBrainzError(
                    f"MusicBrainz: таймаут {timeout} с ({path})"
                ) from exc
            except requests.RequestException as exc:
                raise MusicBrainzError(
                    f"MusicBrainz: сетевая ошибка ({path}): {exc}"
                ) from exc
            finally:
                # время запоминаем даже при ошибке: неудачный запрос тоже считается
                _last_call = time.monotonic()
            # 503/429 = нас притормозили: одна повторная попытка через 2 секунды
            if resp.status_code in (429, 503) and attempt == 1:
                log.warning(
                    "MusicBrainz: HTTP %s на %s, повтор через 2 с",
                    resp.status_code,
                    path,
                )
                time.sleep(2)
                continue
            break

    if resp.status_code == 404:
        raise MBNotFound(f"MusicBrainz: HTTP 404, не найдено ({path})")
    if resp.status_code == 400:
        raise MBBadQuery(f"MusicBrainz: HTTP 400, неверный запрос: {resp.text[:200]}")
    if resp.status_code in (429, 503):
        raise MusicBrainzError(f"MusicBrainz: rate limit, HTTP {resp.status_code} ({path})")
    if not resp.ok:
        raise MusicBrainzError(f"MusicBrainz: HTTP {resp.status_code} ({path})")
    try:
        data = resp.json()
    except ValueError as exc:
        raise MusicBrainzError(f"MusicBrainz: некорректный JSON ({path})") from exc

    # В кэш попадают только успешные ответы: ошибку в следующий раз переспросим
    _cache().set(key, data, cfg["MB_CACHE_TTL"])
    return data


# ---------- мелкие хелперы ----------


def _prepare_query(q):
    """Обычный текст экранируем, продвинутый синтаксис (artist:..., rgid:...) не трогаем.

    Без экранирования запрос "AC/DC" сломался бы: "/" в языке запросов
    MusicBrainz - служебный символ, и сервер вернул бы HTTP 400.
    """
    q = q.strip()
    if ADVANCED_FIELDS.search(q):
        return q
    return LUCENE_SPECIAL.sub(r"\\\1", q)


def _year(date):
    return (date or "")[:4]


def _length(ms):
    if not ms:
        return ""
    sec = int(ms) // 1000
    return f"{sec // 60}:{sec % 60:02d}"


def _dates(begin, end):
    if begin and end and begin != end:
        return f"{begin} ... {end}"
    return begin or end or ""


def _lifespan(ls):
    ls = ls or {}
    begin, end = _year(ls.get("begin")), _year(ls.get("end"))
    if begin and end:
        return f"{begin} - {end}"
    if begin:
        return f"{begin} - ?" if ls.get("ended") else f"с {begin}"
    return end


def _credits(artist_credit):
    return [
        {
            "id": c["artist"]["id"],
            "name": c.get("name") or c["artist"].get("name", "?"),
            "join": c.get("joinphrase", ""),
        }
        for c in artist_credit or []
        if c.get("artist")
    ]


def _names(entity, limit=6):
    """Жанры, а если их нет, теги; по убыванию числа голосов."""
    items = entity.get("genres") or entity.get("tags") or []
    items = sorted(items, key=lambda t: t.get("count", 0), reverse=True)
    return [t["name"] for t in items[:limit] if t.get("name")]


def _rg_type(rg):
    parts = [rg.get("primary-type")] + list(rg.get("secondary-types") or [])
    return " / ".join(RG_TYPE_RU.get(p, p) for p in parts if p)


def _release_sort_key(rel):
    # False < True, поэтому "not is_album" ставит студийные альбомы вперёд,
    # затем официальные релизы, затем самые ранние по дате
    rg = rel.get("release-group") or {}
    is_album = rg.get("primary-type") == "Album" and not rg.get("secondary-types")
    official = rel.get("status") == "Official"
    return (not is_album, not official, rel.get("date") or "9999")


def _pick_release(releases):
    """Самый "канонический" релиз: официальный студийный альбом, самый ранний."""
    return min(releases, key=_release_sort_key) if releases else None


def _release_summary(rel):
    rg = rel.get("release-group") or {}
    return {
        "id": rel["id"],
        "title": rel.get("title", "?"),
        "date": rel.get("date", ""),
        "year": _year(rel.get("date")),
        "country": rel.get("country", ""),
        "rg_id": rg.get("id"),
        "rg_type": _rg_type(rg),
    }


def _role(rtype, attrs):
    if rtype == "instrument" and attrs:
        return ", ".join(attrs)
    base = ROLE_RU.get(rtype, rtype)
    return f"{base} ({', '.join(attrs)})" if attrs else base


def _parse_relations(relations):
    """Раскладывает связи записи по полочкам: студии, продюсеры, состав и т.д."""
    out = {
        "studios": [],
        "producers": [],
        "engineers": [],
        "lineup": [],
        "writers": [],
        "other": [],
        "recording_dates": [],
    }
    # Один музыкант может быть указан несколько раз (гитара, вокал...):
    # собираем его роли в одну строку по id
    lineup = {}
    for rel in relations:
        rtype = rel.get("type", "")
        target = rel.get("target-type")
        attrs = rel.get("attributes") or []
        dates = _dates(rel.get("begin"), rel.get("end"))

        if target == "place":
            place = rel.get("place") or {}
            out["studios"].append(
                {
                    "name": place.get("name", "?"),
                    "area": (place.get("area") or {}).get("name", ""),
                    "role": ROLE_RU.get(rtype, rtype),
                    "dates": dates,
                }
            )
            if rtype == "recorded at" and dates:
                out["recording_dates"].append(dates)

        elif target == "artist":
            artist = rel.get("artist") or {}
            if not artist.get("id"):
                continue
            entry = {
                "id": artist["id"],
                "name": artist.get("name", "?"),
                "role": _role(rtype, attrs),
                "dates": dates,
            }
            if rtype in PERFORMER_TYPES:
                person = lineup.setdefault(artist["id"], {**entry, "roles": []})
                person["roles"].append(entry["role"])
                person["dates"] = person["dates"] or dates
                if dates:
                    out["recording_dates"].append(dates)
            elif rtype == "producer":
                out["producers"].append(entry)
            elif rtype in ENGINEER_TYPES:
                out["engineers"].append(entry)
                if rtype == "recording" and dates:
                    out["recording_dates"].append(dates)
            else:
                out["other"].append(entry)

        elif target == "work":
            # Авторы песни привязаны не к записи, а к произведению (work):
            # одна песня может иметь много записей, а авторы у неё одни
            for wrel in (rel.get("work") or {}).get("relations") or []:
                wartist = wrel.get("artist") or {}
                if wrel.get("type") in WRITER_TYPES and wartist.get("id"):
                    out["writers"].append(
                        {
                            "id": wartist["id"],
                            "name": wartist.get("name", "?"),
                            "role": ROLE_RU.get(wrel["type"], wrel["type"]),
                            "dates": "",
                        }
                    )

    for person in lineup.values():
        # dict.fromkeys убирает повторы, сохраняя порядок (в отличие от set)
        person["role"] = ", ".join(dict.fromkeys(person.pop("roles")))
    out["lineup"] = list(lineup.values())
    out["recording_dates"] = list(dict.fromkeys(out["recording_dates"]))
    return out


# ---------- публичные функции ----------


def _combine(query, extra):
    """Текст пользователя + фильтр жанра/эпохи (фильтр уже в синтаксисе Lucene)."""
    parts = []
    if query and query.strip():
        parts.append(f"({_prepare_query(query)})")
    if extra:
        parts.append(f"({extra})")
    return " AND ".join(parts)


def search_recordings(query, limit=25, extra=None):
    data = _get("/recording", query=_combine(query, extra), limit=limit)
    results = []
    for rec in data.get("recordings", []):
        rel = _pick_release(rec.get("releases") or [])
        results.append(
            {
                "id": rec["id"],
                "title": rec.get("title", "?"),
                "artists": _credits(rec.get("artist-credit")),
                "year": _year(rec.get("first-release-date")),
                "album": _release_summary(rel) if rel else None,
                "length": _length(rec.get("length")),
            }
        )
    return results


def _artist_summary(a):
    return {
        "id": a["id"],
        "name": a.get("name", "?"),
        "type": ARTIST_TYPE_RU.get(a.get("type"), a.get("type") or ""),
        "country": (a.get("area") or {}).get("name") or a.get("country") or "",
        "years": _lifespan(a.get("life-span")),
        "disambiguation": a.get("disambiguation", ""),
        "score": int(a.get("score") or 0),
    }


def search_artists(query, limit=25, extra=None):
    data = _get("/artist", query=_combine(query, extra), limit=limit)
    return [_artist_summary(a) for a in data.get("artists", [])]


def _quote(value):
    """Строка в кавычках для запроса MusicBrainz, кавычки внутри экранированы."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def find_artist_by_name(name):
    """Лучшее совпадение по точному имени или None.

    score - уверенность поиска MusicBrainz (0-100). Ниже 90 считаем, что
    это какой-то другой артист, и лучше показать список результатов.
    """
    hits = search_artists(f"artist:{_quote(name)}", limit=5)
    return hits[0] if hits and hits[0]["score"] >= 90 else None


def find_recording(artist, title):
    """MBID записи по исполнителю и названию (лучшее совпадение) или None."""
    if not (artist and title):
        return None
    query = f"recording:{_quote(title)} AND artist:{_quote(artist)}"
    hits = search_recordings(query, limit=5)
    return hits[0]["id"] if hits else None


def artist_exists(mbid):
    try:
        # Тот же ключ кэша, что у get_artist_core: проверка не тратит лишний запрос,
        # а следующая страница артиста откроется уже из кэша
        _get(f"/artist/{mbid}", inc=ARTIST_INC)
        return True
    except MBNotFound:
        return False


def get_recording(mbid, with_release_credits=False):
    rec = _get(f"/recording/{mbid}", inc=REC_INC)
    primary = _pick_release(rec.get("releases") or [])
    primary_summary = _release_summary(primary) if primary else None
    credits = _parse_relations(rec.get("relations") or [])
    credits["from_release"] = False
    credits["labels"] = []

    # Студия и продюсер часто указаны не у записи, а у релиза. Это +1 запрос,
    # поэтому делаем его только на вкладках "Запись и студия" и "Состав"
    if with_release_credits and primary:
        try:
            release = _get(
                f"/release/{primary['id']}", inc="artist-rels+place-rels+labels"
            )
        except MusicBrainzError:
            # Кредиты релиза не критичны: вкладка покажет данные самой записи
            log.error(
                "MusicBrainz: не удалось получить кредиты релиза %s",
                primary["id"],
                exc_info=True,
            )
            release = {}
            credits["release_failed"] = True
        rc = _parse_relations(release.get("relations") or [])
        for key in ("studios", "producers", "engineers", "lineup", "other", "recording_dates"):
            if not credits[key] and rc[key]:
                credits[key] = rc[key]
                credits["from_release"] = True
        credits["labels"] = [
            {
                "name": li["label"].get("name", "?"),
                "catalog": li.get("catalog-number") or "",
            }
            for li in release.get("label-info") or []
            if li.get("label")
        ]

    # Обложку браузер грузит сам с Cover Art Archive. Ссылку на группу релизов
    # берём охотнее: там обложка есть чаще, чем у конкретного издания
    cover_url = None
    if primary_summary:
        if primary_summary["rg_id"]:
            cover_url = (
                "https://coverartarchive.org/release-group/"
                f"{primary_summary['rg_id']}/front-250"
            )
        else:
            cover_url = (
                f"https://coverartarchive.org/release/{primary_summary['id']}/front-250"
            )

    return {
        "id": rec["id"],
        "title": rec.get("title", "?"),
        "disambiguation": rec.get("disambiguation", ""),
        "length": _length(rec.get("length")),
        "artists": _credits(rec.get("artist-credit")),
        "first_release_date": rec.get("first-release-date", ""),
        "year": _year(rec.get("first-release-date")),
        "release": primary_summary,
        "release_count": len(rec.get("releases") or []),
        "genres": _names(rec),
        "credits": credits,
        "cover_url": cover_url,
    }


def get_artist_core(mbid):
    """Карточка артиста: имя, тип, годы, жанры, участники. 1 запрос."""
    a = _get(f"/artist/{mbid}", inc=ARTIST_INC)
    members, member_of = [], []
    for rel in a.get("relations") or []:
        if rel.get("type") != "member of band" or rel.get("target-type") != "artist":
            continue
        other_artist = rel.get("artist") or {}
        if not other_artist.get("id"):
            continue
        entry = {
            "id": other_artist["id"],
            "name": other_artist.get("name", "?"),
            "role": ", ".join(rel.get("attributes") or []),
            "dates": _dates(_year(rel.get("begin")), _year(rel.get("end"))),
            "ended": rel.get("ended", False),
        }
        # Связь "member of band" одна, но читается в обе стороны:
        # backward = "этот человек - участник нашей группы",
        # forward  = "наш артист - участник другой группы"
        if rel.get("direction") == "backward":
            members.append(entry)
        else:
            member_of.append(entry)
    members.sort(key=lambda m: m["ended"])  # действующие участники сверху

    return {
        **_artist_summary(a),
        "begin_area": (a.get("begin-area") or {}).get("name", ""),
        "genres": _names(a),
        "members": members,
        "member_of": member_of,
    }


def _by_year(item):
    # альбомы без года уходят в конец списка
    return (item["year"] or "9999", item["title"].lower())


def get_discography(mbid):
    """Альбомы и EP артиста. 1 запрос."""
    browse = _get("/release-group", artist=mbid, type="album|ep", limit=100)
    albums, other = [], []
    for rg in browse.get("release-groups", []):
        item = {
            "id": rg["id"],
            "title": rg.get("title", "?"),
            "date": rg.get("first-release-date", ""),
            "year": _year(rg.get("first-release-date")),
            "type": _rg_type(rg),
            "primary_type": rg.get("primary-type") or "",
        }
        # secondary-types (Live, Compilation...) - это не студийные альбомы
        (other if rg.get("secondary-types") else albums).append(item)
    albums.sort(key=_by_year)
    other.sort(key=_by_year)
    return {
        "albums": albums,
        "other_releases": other,
        "count": browse.get("release-group-count", len(albums) + len(other)),
    }
