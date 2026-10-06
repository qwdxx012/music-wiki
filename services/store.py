"""Структурированная реляционная БД проекта (instance/wiki.sqlite3).

В отличие от services/cache.py (сырой key-value кэш ответов внешних API),
этот модуль хранит нормализованные данные по схеме db/schema.sql:
artists -> albums -> tracks, жанры (M:N), факты "этот день" и два
аналитических журнала (recognitions, search_queries).

Данные сюда попадают двумя путями:
1. Автоматически - когда реальный пользователь открывает страницу артиста,
   ищет трек или распознаёт запись (см. хуки в routes/main.py и
   routes/recognize.py: _persist_artist_page, _log_search, _log_recognition).
2. Из scripts/seed_demo.py - демонстрационные данные для отчёта/скриншотов,
   когда внешние API недоступны (например, в изолированной среде без сети).
"""

import logging
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "db" / "schema.sql"


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class WikiStore:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        self._lock = threading.Lock()
        with self.connect() as con:
            con.execute("PRAGMA foreign_keys = ON")
            con.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

    def connect(self):
        con = sqlite3.connect(self.path, timeout=10)
        con.execute("PRAGMA foreign_keys = ON")
        return _AutoClose(con)

    # ---------- запись доменных данных ----------

    def upsert_artist(self, artist):
        with self._lock, self.connect() as con:
            con.execute(
                "INSERT INTO artists (mbid, name, type, country, begin_date,"
                " end_date, disambiguation, updated_at) VALUES (?,?,?,?,?,?,?,?)"
                " ON CONFLICT(mbid) DO UPDATE SET name=excluded.name,"
                " type=excluded.type, country=excluded.country,"
                " disambiguation=excluded.disambiguation, updated_at=excluded.updated_at",
                (
                    artist["id"],
                    artist.get("name", "?"),
                    artist.get("type"),
                    artist.get("country"),
                    artist.get("begin_date"),
                    artist.get("end_date"),
                    artist.get("disambiguation"),
                    _now(),
                ),
            )
            self._upsert_genres(con, "artist_genres", "artist_mbid", artist["id"],
                                 artist.get("genres") or [])

    def upsert_album(self, album, artist_mbid):
        with self._lock, self.connect() as con:
            con.execute(
                "INSERT INTO albums (mbid, title, primary_type, release_date,"
                " artist_mbid, updated_at) VALUES (?,?,?,?,?,?)"
                " ON CONFLICT(mbid) DO UPDATE SET title=excluded.title,"
                " primary_type=excluded.primary_type, release_date=excluded.release_date,"
                " updated_at=excluded.updated_at",
                (
                    album["id"],
                    album.get("title", "?"),
                    album.get("primary_type") or album.get("type"),
                    album.get("date"),
                    artist_mbid,
                    _now(),
                ),
            )

    def upsert_track(self, track, album_mbid=None):
        with self._lock, self.connect() as con:
            con.execute(
                "INSERT INTO tracks (mbid, title, length_ms, first_release_date,"
                " album_mbid, updated_at) VALUES (?,?,?,?,?,?)"
                " ON CONFLICT(mbid) DO UPDATE SET title=excluded.title,"
                " length_ms=excluded.length_ms, album_mbid=COALESCE(excluded.album_mbid,"
                " tracks.album_mbid), updated_at=excluded.updated_at",
                (
                    track["id"],
                    track.get("title", "?"),
                    track.get("length_ms"),
                    track.get("first_release_date"),
                    album_mbid or (track.get("release") or {}).get("id"),
                    _now(),
                ),
            )
            self._upsert_genres(con, "track_genres", "track_mbid", track["id"],
                                 track.get("genres") or [])

    def _upsert_genres(self, con, link_table, fk_col, entity_id, genre_names):
        for name in genre_names:
            con.execute("INSERT OR IGNORE INTO genres (name) VALUES (?)", (name,))
            row = con.execute("SELECT id FROM genres WHERE name = ?", (name,)).fetchone()
            con.execute(
                f"INSERT OR IGNORE INTO {link_table} ({fk_col}, genre_id) VALUES (?, ?)",
                (entity_id, row[0]),
            )

    def add_fact(self, month_day, text, source, year=None, artist_mbid=None, album_mbid=None):
        with self._lock, self.connect() as con:
            con.execute(
                "INSERT INTO facts (month_day, year, text, source, artist_mbid,"
                " album_mbid) VALUES (?,?,?,?,?,?)",
                (month_day, year, text, source, artist_mbid, album_mbid),
            )

    def log_recognition(self, artist_name, track_title, score=None, track_mbid=None, source="audd"):
        with self._lock, self.connect() as con:
            con.execute(
                "INSERT INTO recognitions (recognized_at, artist_name, track_title,"
                " score, track_mbid, source) VALUES (?,?,?,?,?,?)",
                (_now(), artist_name, track_title, score, track_mbid, source),
            )

    def log_search(self, query_text, kind, genre, results_count):
        with self._lock, self.connect() as con:
            con.execute(
                "INSERT INTO search_queries (query_text, kind, genre, results_count,"
                " searched_at) VALUES (?,?,?,?,?)",
                (query_text, kind, genre, results_count, _now()),
            )

    # ---------- чтение / аналитика ----------

    def counts(self):
        tables = ("artists", "albums", "tracks", "genres", "facts",
                  "recognitions", "search_queries")
        with self.connect() as con:
            return {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}

    def top_searches(self, limit=10):
        with self.connect() as con:
            return con.execute(
                "SELECT query_text, kind, COUNT(*) AS n FROM search_queries"
                " WHERE query_text IS NOT NULL AND query_text != ''"
                " GROUP BY query_text, kind ORDER BY n DESC LIMIT ?",
                (limit,),
            ).fetchall()

    def recent_recognitions(self, limit=10):
        with self.connect() as con:
            return con.execute(
                "SELECT recognized_at, artist_name, track_title, score, track_mbid"
                " FROM recognitions ORDER BY recognized_at DESC LIMIT ?",
                (limit,),
            ).fetchall()

    def artists_with_album_counts(self, limit=20):
        with self.connect() as con:
            return con.execute(
                "SELECT a.name, a.country, COUNT(al.mbid) AS albums"
                " FROM artists a LEFT JOIN albums al ON al.artist_mbid = a.mbid"
                " GROUP BY a.mbid ORDER BY albums DESC, a.name LIMIT ?",
                (limit,),
            ).fetchall()


class _AutoClose:
    def __init__(self, con):
        self.con = con

    def __enter__(self):
        return self.con

    def __exit__(self, exc_type, *_):
        with closing(self.con):
            if exc_type is None:
                self.con.commit()
            else:
                self.con.rollback()
        return False
