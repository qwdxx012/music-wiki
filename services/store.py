"""Структурированная база проекта в Supabase (PostgreSQL).

В отличие от services/cache.py (key-value кэш ответов внешних API),
этот модуль хранит нормализованные данные по схеме db/supabase_schema.sql:
artists -> albums -> tracks, жанры (M:N), факты "этот день" и два
аналитических журнала (recognitions, search_queries).

Работа идёт через Supabase REST API (PostgREST). Клиент создаётся один
раз в app.py и передаётся сюда, чтобы не открывать соединение на каждый
запрос. Если ключи Supabase не заданы, методы ничего не делают: сайт
продолжает открываться, а в лог пишется предупреждение.
"""

import logging
import random
from datetime import datetime, timezone

log = logging.getLogger(__name__)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class WikiStore:
    def __init__(self, client=None):
        self.client = client

    # ---------- запись доменных данных ----------

    def upsert_artist(self, artist):
        if not self.client:
            return
        self.client.table("artists").upsert(
            {
                "mbid": artist["id"],
                "name": artist.get("name", "?"),
                "type": artist.get("type"),
                "country": artist.get("country"),
                "begin_date": artist.get("begin_date"),
                "end_date": artist.get("end_date"),
                "disambiguation": artist.get("disambiguation"),
                "updated_at": _now(),
            },
            on_conflict="mbid",
        ).execute()
        self._upsert_genres(
            "artist_genres", "artist_mbid", artist["id"], artist.get("genres") or []
        )

    def upsert_album(self, album, artist_mbid):
        if not self.client:
            return
        self.client.table("albums").upsert(
            {
                "mbid": album["id"],
                "title": album.get("title", "?"),
                "primary_type": album.get("primary_type") or album.get("type"),
                "release_date": album.get("date"),
                "artist_mbid": artist_mbid,
                "updated_at": _now(),
            },
            on_conflict="mbid",
        ).execute()

    def upsert_track(self, track, album_mbid=None):
        if not self.client:
            return
        row = {
            "mbid": track["id"],
            "title": track.get("title", "?"),
            "length_ms": track.get("length_ms"),
            "first_release_date": track.get("first_release_date"),
            "updated_at": _now(),
        }
        # Если альбома нет, поле не отправляем: при обновлении уже
        # сохранённого трека ссылка на альбом останется прежней
        album_mbid = album_mbid or (track.get("release") or {}).get("id")
        if album_mbid:
            row["album_mbid"] = album_mbid
        self.client.table("tracks").upsert(row, on_conflict="mbid").execute()
        self._upsert_genres(
            "track_genres", "track_mbid", track["id"], track.get("genres") or []
        )

    def _upsert_genres(self, link_table, fk_col, entity_id, genre_names):
        if not self.client:
            return
        for name in dict.fromkeys(genre_names):
            self.client.table("genres").upsert(
                {"name": name}, on_conflict="name", ignore_duplicates=True
            ).execute()
            genre = (
                self.client.table("genres")
                .select("id")
                .eq("name", name)
                .single()
                .execute()
                .data
            )
            self.client.table(link_table).upsert(
                {fk_col: entity_id, "genre_id": genre["id"]},
                on_conflict=f"{fk_col},genre_id",
                ignore_duplicates=True,
            ).execute()

    def add_fact(self, month_day, text, source, year=None, artist_mbid=None, album_mbid=None):
        if not self.client:
            return
        self.client.table("facts").insert(
            {
                "month_day": month_day,
                "year": year,
                "text": text,
                "source": source,
                "artist_mbid": artist_mbid,
                "album_mbid": album_mbid,
            }
        ).execute()

    def log_recognition(self, artist_name, track_title, score=None, track_mbid=None, source="audd"):
        if not self.client:
            return
        self.client.table("recognitions").insert(
            {
                "recognized_at": _now(),
                "artist_name": artist_name,
                "track_title": track_title,
                "score": score,
                "track_mbid": track_mbid,
                "source": source,
            }
        ).execute()

    def log_search(self, query_text, kind, genre, results_count):
        if not self.client:
            return
        self.client.table("search_queries").insert(
            {
                "query_text": query_text,
                "kind": kind,
                "genre": genre,
                "results_count": results_count,
                "searched_at": _now(),
            }
        ).execute()

    # ---------- индекс дат релизов ("Этот день") ----------

    def upsert_release_dates(self, rows):
        if not self.client or not rows:
            return
        payload = [
            {
                "rg_id": row[0],
                "title": row[1],
                "artist_id": row[2],
                "artist_name": row[3],
                "rg_type": row[4],
                "date": row[5],
                "month_day": row[6],
            }
            for row in rows
        ]
        self.client.table("release_dates").upsert(payload, on_conflict="rg_id").execute()

    def random_releases(self, month_day, limit):
        if not self.client:
            return []
        rows = (
            self.client.table("release_dates")
            .select("rg_id, title, artist_id, artist_name, rg_type, date")
            .eq("month_day", month_day)
            .limit(200)
            .execute()
            .data
            or []
        )
        # PostgREST не умеет ORDER BY RANDOM(), поэтому перемешиваем на сервере
        random.shuffle(rows)
        return rows[:limit]

    # ---------- чтение / аналитика ----------

    def counts(self):
        if not self.client:
            return {}
        tables = (
            "artists", "albums", "tracks", "genres", "facts",
            "recognitions", "search_queries",
        )
        return {
            table: self.client.table(table)
            .select("*", count="exact", head=True)
            .execute()
            .count
            or 0
            for table in tables
        }

    def top_searches(self, limit=10):
        if not self.client:
            return []
        return (
            self.client.table("top_searches")
            .select("query_text, kind, n")
            .order("n", desc=True)
            .limit(limit)
            .execute()
            .data
        )

    def recent_recognitions(self, limit=10):
        if not self.client:
            return []
        return (
            self.client.table("recognitions")
            .select("recognized_at, artist_name, track_title, score, track_mbid")
            .order("recognized_at", desc=True)
            .limit(limit)
            .execute()
            .data
        )

    def artists_with_album_counts(self, limit=20):
        if not self.client:
            return []
        return (
            self.client.table("artists_album_counts")
            .select("name, country, albums")
            .order("albums", desc=True)
            .order("name")
            .limit(limit)
            .execute()
            .data
        )

    def list_artists_for_sitemap(self):
        if not self.client:
            return []
        return (
            self.client.table("artists")
            .select("mbid, updated_at")
            .order("name")
            .limit(1000)
            .execute()
            .data
        )

    def list_tracks_for_sitemap(self):
        if not self.client:
            return []
        return (
            self.client.table("tracks")
            .select("mbid, updated_at")
            .order("title")
            .limit(1000)
            .execute()
            .data
        )
