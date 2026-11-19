"""Key-value кэш в Supabase с временем жизни (TTL).

Зачем: MusicBrainz разрешает 1 запрос в секунду, у AudD всего 300 бесплатных
распознаваний. Всё, что уже скачали, храним в таблице cache, и повторное
открытие той же страницы не ходит в сеть.

Ошибки базы не роняют страницу: кэш просто считается пустым, а причина
пишется в лог.
"""

import logging
import random
import time

log = logging.getLogger(__name__)


class DiskCache:
    def __init__(self, client=None):
        self.client = client

    def get(self, key):
        """Значение по ключу или None, если его нет или срок жизни истёк."""
        if not self.client:
            return None
        try:
            rows = (
                self.client.table("cache")
                .select("value, expires_at")
                .eq("key", key)
                .limit(1)
                .execute()
                .data
            )
        except Exception:  # noqa: BLE001
            log.error("Кэш: не удалось прочитать %s", key, exc_info=True)
            return None
        if not rows:
            return None
        value, expires_at = rows[0]["value"], rows[0]["expires_at"]
        # expires_at хранится как абсолютное время (секунды с 1970 года).
        # Просроченную запись удаляем сразу, чтобы таблица не пухла
        if expires_at < time.time():
            self.delete(key)
            return None
        return value

    def set(self, key, value, ttl):
        """Сохраняет value (любой JSON-совместимый объект) на ttl секунд."""
        if not self.client:
            return
        try:
            self.client.table("cache").upsert(
                {"key": key, "value": value, "expires_at": time.time() + ttl},
                on_conflict="key",
            ).execute()
        except Exception:  # noqa: BLE001
            log.error("Кэш: не удалось записать %s", key, exc_info=True)

    def delete(self, key):
        if not self.client:
            return
        try:
            self.client.table("cache").delete().eq("key", key).execute()
        except Exception:  # noqa: BLE001
            log.error("Кэш: не удалось удалить %s", key, exc_info=True)

    def random_key(self, *prefixes):
        """Случайный живой ключ, начинающийся с одного из префиксов (или None).

        На этом держится кнопка "Мне повезёт": артист выбирается из того,
        что уже лежит в кэше, без единого запроса в интернет.
        """
        if not self.client or not prefixes:
            return None
        now = time.time()
        keys = []
        # PostgREST в LIKE использует "*" как "любые символы"
        for prefix in prefixes:
            try:
                rows = (
                    self.client.table("cache")
                    .select("key")
                    .like("key", prefix + "*")
                    .gt("expires_at", now)
                    .execute()
                    .data
                )
            except Exception:  # noqa: BLE001
                log.error("Кэш: не удалось выбрать случайный ключ", exc_info=True)
                continue
            keys.extend(row["key"] for row in rows)
        return random.choice(keys) if keys else None
