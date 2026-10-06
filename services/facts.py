"""Блок "Этот день в истории музыки" и бегущая строка на главной.

Два источника фактов для "Этого дня":
1. data/on_this_day.json - ручная таблица по ключу ММ-ДД (правится без
   перезапуска сервера).
2. Таблица release_dates в SQLite - альбомы, которые уже встречались на
   открытых страницах артистов. Так база фактов сама растёт, пока по вики ходят.
"""

import json
import logging
import random
import threading
from datetime import date, timedelta
from pathlib import Path

from flask import current_app

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
ON_THIS_DAY = DATA_DIR / "on_this_day.json"
TICKER = DATA_DIR / "music_facts.json"

MONTHS_GEN = [
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
]
RG_WORD = {"Album": "альбом", "EP": "EP", "Single": "сингл"}

# Кэш прочитанных JSON-файлов в памяти: {путь: (время изменения, данные)}
_json_cache = {}
_json_lock = threading.Lock()
# Для каких файлов базы уже создана таблица release_dates (делаем это один раз)
_schema_ready = set()


def _load_json(path, default):
    """Читает JSON, но перечитывает файл, только если он изменился.

    Сравниваем время изменения файла (mtime) с запомненным: если файл
    правили, берём новую версию. Поэтому факты можно дописывать в JSON
    прямо во время работы сайта, без перезапуска.
    """
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return default
    with _json_lock:
        hit = _json_cache.get(path)
        if hit and hit[0] == mtime:
            return hit[1]
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.error("Не удалось прочитать %s", path, exc_info=True)
            data = default
        _json_cache[path] = (mtime, data)
        return data


def human_date(d, year=None):
    text = f"{d.day} {MONTHS_GEN[d.month - 1]}"
    return f"{text} {year} года" if year else text


# ---------- индекс релизов в SQLite ----------


def _db():
    cache = current_app.extensions["disk_cache"]
    if cache.path not in _schema_ready:
        with cache.connect() as con:
            con.execute(
                "CREATE TABLE IF NOT EXISTS release_dates ("
                " rg_id TEXT PRIMARY KEY, title TEXT NOT NULL, artist_id TEXT,"
                " artist_name TEXT, rg_type TEXT, date TEXT NOT NULL,"
                " month_day TEXT NOT NULL)"
            )
            # индекс по ММ-ДД: выборка "что вышло 24 сентября" не перебирает всю таблицу
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_release_md ON release_dates(month_day)"
            )
        _schema_ready.add(cache.path)
    return cache.connect()


def index_releases(artist, disco):
    """Запоминает альбомы с полной датой (ГГГГ-ММ-ДД) для блока "Этот день"."""
    # Даты вида "1991" или "1991-09" пропускаем: по ним нельзя понять день
    rows = [
        (
            rg["id"],
            rg["title"],
            artist["id"],
            artist["name"],
            rg.get("primary_type", ""),
            rg["date"],
            rg["date"][5:10],
        )
        for rg in disco.get("albums", [])
        if len(rg.get("date") or "") == 10
    ]
    if not rows:
        return
    try:
        with _db() as con:
            con.executemany(
                "INSERT OR REPLACE INTO release_dates VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
    except Exception:  # noqa: BLE001
        # Индекс фактов - приятный бонус, из-за него страница артиста падать не должна
        log.error("Не удалось обновить индекс релизов", exc_info=True)


def _releases_on(month_day, limit):
    try:
        with _db() as con:
            rows = con.execute(
                "SELECT rg_id, title, artist_id, artist_name, rg_type, date"
                " FROM release_dates WHERE month_day = ? ORDER BY RANDOM() LIMIT ?",
                (month_day, limit),
            ).fetchall()
    except Exception:  # noqa: BLE001
        log.error("Не удалось прочитать индекс релизов", exc_info=True)
        return []
    return [
        {
            "year": int(r[5][:4]),
            "text": f"вышел {RG_WORD.get(r[4], 'релиз')} {r[3]} «{r[1]}»",
            "artist_id": r[2],
            "source": "MusicBrainz",
        }
        for r in rows
    ]


# ---------- публичное API ----------


def facts_for(d, limit=2):
    month_day = f"{d.month:02d}-{d.day:02d}"
    manual = _load_json(ON_THIS_DAY, {}).get(month_day) or []
    manual = [dict(f, source="таблица фактов") for f in manual if f.get("text")]
    random.shuffle(manual)

    def is_new(rel):
        # Релиз из кэша, который уже описан в ручной таблице, не дублируем
        title = rel["text"].rsplit("«", 1)[-1].rstrip("»")
        return not any(
            m.get("year") == rel["year"] and title in m["text"] for m in manual
        )

    cached = [r for r in _releases_on(month_day, limit + 3) if is_new(r)]
    picked = manual[:limit]
    if len(picked) < limit:
        picked += cached[: limit - len(picked)]
    elif cached and limit > 1:
        # Один факт из таблицы уступает место релизу из кэша, чтобы было видно,
        # что база пополняется сама
        picked[-1] = cached[0]
    for f in picked:
        f["date_text"] = human_date(d, f.get("year"))
    return sorted(picked, key=lambda f: f.get("year") or 0)


def on_this_day(today=None, limit=2, lookahead=60):
    """Факты на сегодня. Если на сегодня пусто, берём ближайший день впереди."""
    today = today or date.today()
    for shift in range(lookahead + 1):
        d = today + timedelta(days=shift)
        facts = facts_for(d, limit)
        if facts:
            return {"is_today": shift == 0, "day": human_date(d), "facts": facts}
    return {"is_today": True, "day": human_date(today), "facts": []}


def ticker_facts():
    facts = [f for f in _load_json(TICKER, []) if isinstance(f, str) and f.strip()]
    random.shuffle(facts)
    return facts
