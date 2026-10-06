import logging
import re

from flask import Blueprint, current_app, redirect, render_template, request, url_for

from routes.safe import parallel, safe
from services import facts, genres, lastfm
from services import musicbrainz as mb

bp = Blueprint("main", __name__)
log = logging.getLogger("musicwiki.external")

# MBID - идентификатор MusicBrainz вида 8-4-4-4-12 шестнадцатеричных символов.
# MBID_RE проверяет строку целиком, MBID_ANY ищет MBID внутри ключа кэша
MBID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
MBID_ANY = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
TRACK_TABS = {"general": "Общие", "studio": "Запись и студия", "lineup": "Состав"}
SEARCH_KINDS = {"track": "Треки", "artist": "Исполнители"}


def _require_mbid(mbid):
    # Мусор в адресе отсекаем сразу, не тратя запрос к MusicBrainz
    if not MBID_RE.match(mbid):
        return _error(404, "Ошибка", "Неверный идентификатор MusicBrainz.")
    return None


def _cache():
    return current_app.extensions["disk_cache"]


def _store():
    return current_app.extensions["wiki_store"]


@bp.route("/")
def index():
    return render_template(
        "index.html",
        today=facts.on_this_day(),
        ticker=facts.ticker_facts(),
        genres=genres.GENRES,
    )


@bp.route("/about")
def about():
    return render_template("about.html")


# ---------- поиск ----------


def _fmt_duration(sec):
    return f"{sec // 60}:{sec % 60:02d}" if sec else ""


def _lastfm_results(kind, genre):
    """Топ Last.fm по тегу -> строки таблицы. Возвращает (results, failed).

    У Last.fm часто нет MBID, поэтому ссылки ведут на */lookup: там мы
    сами найдём нужную страницу в MusicBrainz по имени.
    """
    if kind == "artist":
        items, failed = safe(
            "Last.fm: топ артистов по тегу", lastfm.tag_top_artists, genre["lastfm"]
        )
        rows = [
            {
                "rank": a["rank"],
                "name": a["name"],
                "href": url_for(".artist_lookup", name=a["name"], mbid=a["mbid"] or ""),
            }
            for a in items or []
        ]
        return rows, failed

    items, failed = safe(
        "Last.fm: топ треков по тегу", lastfm.tag_top_tracks, genre["lastfm"]
    )
    rows = []
    for t in items or []:
        artist_href = url_for(
            ".artist_lookup", name=t["artist"], mbid=t["artist_mbid"] or ""
        )
        rows.append(
            {
                "rank": t["rank"],
                "title": t["title"],
                "length": _fmt_duration(t["duration"]),
                "href": url_for(
                    ".track_lookup",
                    artist=t["artist"],
                    title=t["title"],
                    mbid=t["mbid"] or "",
                ),
                "artists": [{"name": t["artist"], "join": "", "href": artist_href}],
            }
        )
    return rows, failed


@bp.route("/search")
def search():
    q = request.args.get("q", "").strip()
    genre_key = request.args.get("genre", "").strip().lower()
    genre = genres.get(genre_key)
    if not genre:
        genre_key = ""
    # По ярлыку жанра (без текста) по умолчанию показываем исполнителей
    kind = request.args.get("type") or ("artist" if genre and not q else "track")
    if kind not in SEARCH_KINDS:
        kind = "track"
    if not q and not genre:
        return redirect(url_for(".index"))

    results, error, notice, source, lfm_mode = [], None, None, "MusicBrainz", False

    # Чистый жанр без текста: сначала пробуем топ Last.fm (там известные имена).
    # Не вышло - молча переходим на поиск MusicBrainz с фильтром по тегу
    if genre and not q and current_app.config["LASTFM_API_KEY"]:
        results, failed = _lastfm_results(kind, genre)
        if results:
            lfm_mode, source = True, f"Last.fm, тег «{genre['lastfm']}»"
        elif failed:
            notice = "Last.fm временно недоступен, показываю данные MusicBrainz."

    if not lfm_mode:
        extra = None
        if genre:
            extra = genre["mb_artist"] if kind == "artist" else genre["mb_recording"]
        try:
            if kind == "artist":
                results = mb.search_artists(q, extra=extra)
            else:
                results = mb.search_recordings(q, extra=extra)
        except mb.MBBadQuery:
            # Остальные ошибки MusicBrainz ловит общий обработчик mb_error ниже
            log.error(
                "MusicBrainz не понял запрос q=%r genre=%r", q, genre_key, exc_info=True
            )
            error = "MusicBrainz не понял запрос. Попробуйте убрать спецсимволы."

    # Аналитика: каждый выполненный поиск (текст и/или жанр) пишем в
    # search_queries, чтобы потом можно было посчитать самые частые запросы
    try:
        _store().log_search(q, kind, genre_key or None, len(results))
    except Exception:  # noqa: BLE001
        log.error("Не удалось записать поисковый запрос в БД", exc_info=True)

    heading = " / ".join(part for part in (q, genre["label"] if genre else "") if part)
    return render_template(
        "search.html",
        q=q,
        heading=heading,
        kind=kind,
        kinds=SEARCH_KINDS,
        results=results,
        error=error,
        notice=notice,
        source=source,
        lfm_mode=lfm_mode,
        genre=genre,
        genre_key=genre_key,
        genres=genres.GENRES,
    )


# ---------- трек ----------


@bp.route("/track/<mbid>")
def track(mbid):
    bad = _require_mbid(mbid)
    if bad:
        return bad
    tab = request.args.get("tab", "general")
    if tab not in TRACK_TABS:
        tab = "general"

    rec = mb.get_recording(mbid, with_release_credits=(tab != "general"))
    try:
        _store().upsert_track(rec, album_mbid=(rec.get("release") or {}).get("id"))
    except Exception:  # noqa: BLE001
        log.error("Не удалось сохранить трек %s в БД", mbid, exc_info=True)
    main_artist = rec["artists"][0]["name"] if rec["artists"] else None
    lfm, lfm_failed = None, False
    if main_artist:
        lfm, lfm_failed = safe(
            "Last.fm: трек", lastfm.track_info, main_artist, rec["title"]
        )
    return render_template(
        "track.html", rec=rec, lfm=lfm, lfm_failed=lfm_failed, tab=tab, tabs=TRACK_TABS
    )


@bp.route("/track/lookup")
def track_lookup():
    """Переход с Last.fm на MusicBrainz: сначала по mbid, иначе по исполнителю+названию."""
    artist = request.args.get("artist", "").strip()
    title = request.args.get("title", "").strip()
    mbid = request.args.get("mbid", "").strip()
    if mbid and MBID_RE.match(mbid):
        # MBID от Last.fm бывает устаревшим, поэтому сначала проверяем, что он живой
        rec, _ = safe("MusicBrainz: проверка записи", mb.get_recording, mbid)
        if rec:
            return redirect(url_for(".track", mbid=mbid))
    found, _ = safe("MusicBrainz: поиск записи", mb.find_recording, artist, title)
    if found:
        return redirect(url_for(".track", mbid=found))
    fallback_q = f"{artist} {title}".strip() or "?"
    return redirect(url_for(".search", q=fallback_q, type="track"))


# ---------- артист ----------


def _artist_page(mbid):
    """Все данные страницы артиста. Возвращает (page, from_cache).

    Кэш двухуровневый: сырые ответы MusicBrainz/Last.fm кэшируются внутри
    сервисов, а здесь на 24 часа кэшируется уже собранная страница целиком,
    чтобы повторный заход вообще не трогал сеть.
    """
    lfm_on = bool(current_app.config["LASTFM_API_KEY"])
    # В ключ входит "включён ли Last.fm": после добавления ключа в .env
    # страница соберётся заново уже с биографией, а не возьмётся старая из кэша
    key = f"page:artist:{mbid}:{int(lfm_on)}"
    page = _cache().get(key)
    if page is not None:
        return page, True

    # Карточка артиста - обязательная часть. MBNotFound пробрасываем дальше:
    # его превратит в страницу "Объект не найден" обработчик mb_not_found
    core, core_failed = safe(
        "MusicBrainz: артист", mb.get_artist_core, mbid, reraise=(mb.MBNotFound,)
    )
    if core_failed:
        return None, False

    # Остальные блоки необязательные: каждый может упасть сам по себе
    res = parallel(
        {
            "disco": ("MusicBrainz: дискография", mb.get_discography, (mbid,)),
            "info": ("Last.fm: биография", lastfm.artist_info, (core["name"],)),
            "similar": ("Last.fm: похожие артисты", lastfm.similar_artists, (core["name"],)),
        }
    )
    page = {
        "artist": core,
        "disco": res["disco"][0],
        "info": res["info"][0],
        "similar": res["similar"][0] or [],
        "failed": {name: failed for name, (_, failed) in res.items()},
    }
    if page["disco"]:
        facts.index_releases(core, page["disco"])
    _persist_artist_page(core, page["disco"])
    # Частичные данные (что-то упало) НЕ кэшируем: иначе плашка "Last.fm
    # недоступен" провисела бы сутки. В следующий раз просто попробуем снова
    if not any(page["failed"].values()):
        _cache().set(key, page, current_app.config["ARTIST_PAGE_TTL"])
    return page, False


def _persist_artist_page(core, disco):
    """Сохраняет карточку артиста и его альбомы в структурированную БД
    (services/store.py), помимо технического кэша сырых ответов MusicBrainz.
    Любой сбой здесь не должен ронять страницу - только пишем в лог.
    """
    try:
        store = _store()
        store.upsert_artist(core)
        if disco:
            for album in disco.get("albums", []) + disco.get("other_releases", []):
                store.upsert_album(album, core["id"])
    except Exception:  # noqa: BLE001
        log.error("Не удалось сохранить артиста %s в БД", core.get("id"), exc_info=True)


@bp.route("/artist/<mbid>")
def artist(mbid):
    bad = _require_mbid(mbid)
    if bad:
        return bad
    page, from_cache = _artist_page(mbid)
    if page is None:
        return _error(
            503,
            "MusicBrainz",
            "Информация об исполнителе временно недоступна.",
            "MusicBrainz не ответил. Подробности в логе сервера.",
            retry=True,
        )
    return render_template("artist.html", **page, from_cache=from_cache)


@bp.route("/artist/lookup")
def artist_lookup():
    """Переход с Last.fm на MusicBrainz: сначала по mbid, если он живой, иначе по имени."""
    name = request.args.get("name", "").strip()
    mbid = request.args.get("mbid", "").strip()
    if mbid and MBID_RE.match(mbid):
        exists, _ = safe("MusicBrainz: проверка артиста", mb.artist_exists, mbid)
        if exists:
            return redirect(url_for(".artist", mbid=mbid))
    if not name:
        return redirect(url_for(".index"))
    hit, _ = safe("MusicBrainz: поиск артиста", mb.find_artist_by_name, name)
    if hit:
        return redirect(url_for(".artist", mbid=hit["id"]))
    return redirect(url_for(".search", q=name, type="artist"))


@bp.route("/random")
def random_artist():
    """Кнопка "Мне повезёт": случайный артист ТОЛЬКО из локального кэша, без запросов в сеть.

    Смотрим два вида ключей: готовые страницы ("page:artist:<mbid>:...") и
    сырые карточки MusicBrainz ("mb:/artist/<mbid>?..."). Из ключа
    регуляркой достаём MBID и переходим на страницу артиста.
    """
    key = _cache().random_key("page:artist:", "mb:/artist/")
    found = MBID_ANY.search(key or "")
    if found:
        return redirect(url_for(".artist", mbid=found.group(0)))
    return _error(
        200,
        "Мне повезёт",
        "Пока не из чего выбирать: в кэше нет ни одного исполнителя.",
        "Откройте пару страниц артистов, и кнопка заработает.",
        kind="info",
    )


# ---------- ошибки в виде системных окон ----------


def _error(code, title, message, details=None, retry=False, kind="error"):
    # Кнопка "Повтор" ведёт на тот же адрес, с которого пришла ошибка
    retry_url = request.full_path if retry else None
    return (
        render_template(
            "error.html",
            title=title,
            message=message,
            kind=kind,
            details=details,
            retry_url=retry_url,
        ),
        code,
    )


# app_errorhandler срабатывает для исключений из ЛЮБОГО роута приложения,
# поэтому в самих роутах не нужно оборачивать каждый вызов MusicBrainz в try.
# MBNotFound - подкласс MusicBrainzError, Flask выбирает самый точный обработчик


@bp.app_errorhandler(mb.MBNotFound)
def mb_not_found(exc):
    log.error("MusicBrainz 404 на %s: %s", request.path, exc, exc_info=exc)
    return _error(
        404,
        "Объект не найден",
        "MusicBrainz не знает такой записи.",
        "Возможно, её удалили или объединили с другой.",
    )


@bp.app_errorhandler(mb.MusicBrainzError)
def mb_error(exc):
    log.error("MusicBrainz упал на %s: %s", request.path, exc, exc_info=exc)
    return _error(
        502,
        "MusicBrainz",
        "Сервер MusicBrainz не отвечает. Повторите попытку позже.",
        str(exc),
        retry=True,
    )


@bp.app_errorhandler(404)
def not_found(_exc):
    return _error(
        404,
        "Ошибка",
        "Не удаётся найти страницу. Проверьте правильность адреса и повторите попытку.",
    )


@bp.app_errorhandler(500)
def server_error(exc):
    original = getattr(exc, "original_exception", exc)
    log.error("Необработанная ошибка на %s", request.path, exc_info=original)
    return _error(
        500,
        "Критическая ошибка",
        "Программа выполнила недопустимую операцию и будет закрыта.",
        "Если ошибка повторяется, обратитесь к разработчику.",
    )
