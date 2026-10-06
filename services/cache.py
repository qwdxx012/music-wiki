"""Key-value кэш на SQLite с временем жизни (TTL).

Зачем: MusicBrainz разрешает 1 запрос в секунду, у AudD всего 300 бесплатных
распознаваний. Всё, что уже скачали, храним в файле instance/cache.sqlite3,
и повторное открытие той же страницы не ходит в сеть.

Ошибки самой SQLite не роняют страницу: кэш просто считается пустым,
а причина пишется в лог.
"""

import json
import logging
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path

log = logging.getLogger(__name__)


class DiskCache:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        # Запись идёт под замком: dev-сервер Flask обслуживает запросы
        # в нескольких потоках, и два одновременных INSERT могли бы
        # получить "database is locked"
        self._lock = threading.Lock()
        with self.connect() as con:
            # WAL-режим: чтение не ждёт, пока другой поток закончит запись
            con.execute("PRAGMA journal_mode=WAL")
            con.execute(
                "CREATE TABLE IF NOT EXISTS cache ("
                " key TEXT PRIMARY KEY,"
                " value TEXT NOT NULL,"
                " expires_at REAL NOT NULL)"
            )

    def connect(self):
        # Новое соединение на каждую операцию: sqlite3-соединение нельзя
        # делить между потоками, а открыть файл заново почти ничего не стоит
        con = sqlite3.connect(self.path, timeout=10)
        return _AutoClose(con)

    def get(self, key):
        """Значение по ключу или None, если его нет или срок жизни истёк."""
        try:
            with self.connect() as con:
                row = con.execute(
                    "SELECT value, expires_at FROM cache WHERE key = ?", (key,)
                ).fetchone()
        except sqlite3.Error:
            log.error("Кэш: не удалось прочитать %s", key, exc_info=True)
            return None
        if row is None:
            return None
        value, expires_at = row
        # expires_at хранится как абсолютное время (секунды с 1970 года).
        # Просроченную запись удаляем сразу, чтобы база не пухла
        if expires_at < time.time():
            self.delete(key)
            return None
        return json.loads(value)

    def set(self, key, value, ttl):
        """Сохраняет value (любой JSON-совместимый объект) на ttl секунд."""
        try:
            with self._lock, self.connect() as con:
                con.execute(
                    "INSERT OR REPLACE INTO cache (key, value, expires_at)"
                    " VALUES (?, ?, ?)",
                    (key, json.dumps(value, ensure_ascii=False), time.time() + ttl),
                )
        except sqlite3.Error:
            log.error("Кэш: не удалось записать %s", key, exc_info=True)

    def delete(self, key):
        try:
            with self._lock, self.connect() as con:
                con.execute("DELETE FROM cache WHERE key = ?", (key,))
        except sqlite3.Error:
            log.error("Кэш: не удалось удалить %s", key, exc_info=True)

    def random_key(self, *prefixes):
        """Случайный живой ключ, начинающийся с одного из префиксов (или None).

        На этом держится кнопка "Мне повезёт": артист выбирается из того,
        что уже лежит в кэше, без единого запроса в интернет.
        """
        if not prefixes:
            return None
        where = " OR ".join("key LIKE ? ESCAPE '\\'" for _ in prefixes)
        # В LIKE символы % и _ означают "любые символы", а в наших ключах
        # встречается "_". Экранируем их, чтобы префикс искался буквально
        like = [
            p.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            for p in prefixes
        ]
        try:
            with self.connect() as con:
                row = con.execute(
                    f"SELECT key FROM cache WHERE ({where}) AND expires_at > ? "
                    "ORDER BY RANDOM() LIMIT 1",
                    (*like, time.time()),
                ).fetchone()
        except sqlite3.Error:
            log.error("Кэш: не удалось выбрать случайный ключ", exc_info=True)
            return None
        return row[0] if row else None


class _AutoClose:
    """sqlite3-соединение для with: при выходе commit (или rollback) и close.

    Стандартный "with sqlite3.connect()" делает только commit, но не закрывает
    соединение, из-за чего файл базы остаётся открытым.
    """

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
