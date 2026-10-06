"""Клиент AudD: распознавание трека по аудиофайлу.
"""

import hashlib
import logging

import requests
from flask import current_app

AUDD_URL = "https://api.audd.io/"
log = logging.getLogger(__name__)


class AudDError(Exception):
    """Базовая ошибка распознавания.

    message - текст для пользователя, details - подсказка мелким шрифтом,
    title - заголовок окна-сообщения. Роут просто показывает эти поля.
    """

    title = "Ошибка распознавания"

    def __init__(self, message, details=None):
        super().__init__(message)
        self.message = message
        self.details = details


class AudDConfigError(AudDError):
    title = "Служба недоступна"


class AudDLimitError(AudDError):
    title = "Лимит исчерпан"


class AudDBadFile(AudDError):
    title = "Неверный формат"


class AudDNoMatch(AudDError):
    title = "Файл не может быть открыт"


# Коды ошибок из документации AudD -> (класс исключения, понятный текст).
# Сырые коды пользователю ничего не скажут, а так он видит, что делать дальше
ERROR_MAP = {
    900: (AudDConfigError, "Неверный API-токен AudD. Проверьте AUDD_API_TOKEN в .env."),
    901: (AudDLimitError, "Лимит бесплатных запросов AudD исчерпан."),
    902: (AudDLimitError, "Лимит запросов для этого токена AudD исчерпан."),
    700: (AudDBadFile, "Сервер не получил файл. Попробуйте загрузить ещё раз."),
    500: (AudDBadFile, "Аудиофайл повреждён или имеет неподдерживаемый формат."),
    400: (AudDBadFile, "Файл слишком большой или слишком длинный для распознавания."),
    300: (AudDBadFile, "Не удалось разобрать звук в файле. Попробуйте другой фрагмент."),
}


def _cache():
    return current_app.extensions["disk_cache"]


def recognize(data, filename, mimetype):
    """Возвращает dict с результатом или бросает AudDError / AudDNoMatch."""
    cfg = current_app.config
    token = cfg.get("AUDD_API_TOKEN")
    if not token:
        raise AudDConfigError("Распознавание не настроено: не задан AUDD_API_TOKEN.")

    # Ключ кэша - хэш самих байтов файла, а не его имени: "song.mp3" и
    # "копия song.mp3" с одинаковым содержимым дадут один и тот же ключ
    key = "audd:" + hashlib.sha256(data).hexdigest()
    cached = _cache().get(key)
    if cached is None:
        cached = _request(token, data, filename, mimetype, cfg["AUDD_TIMEOUT"])
        # "Не найдено" тоже кэшируем, но только на сутки: вдруг база AudD
        # пополнится. Пустой dict {} в кэше означает "искали, не нашли"
        ttl = cfg["AUDD_CACHE_TTL"] if cached else 24 * 3600
        _cache().set(key, cached or {}, ttl)

    if not cached:
        raise AudDNoMatch(
            "Файл не может быть открыт: совпадений не найдено.",
            "Попробуйте фрагмент 10-20 секунд без разговоров и шума.",
        )
    return cached


def _request(token, data, filename, mimetype, timeout):
    """Один запрос к AudD. None = трек не найден, ошибки = исключения."""
    try:
        resp = requests.post(
            AUDD_URL,
            # return=musicbrainz: AudD сразу вернёт MBID записи, и нам не
            # придётся отдельно искать трек в MusicBrainz по названию
            data={"api_token": token, "return": "musicbrainz"},
            files={
                "file": (
                    filename or "audio",
                    data,
                    mimetype or "application/octet-stream",
                )
            },
            timeout=timeout,
        )
        payload = resp.json()
    except requests.Timeout as exc:
        raise AudDError(
            "AudD не ответил вовремя. Повторите попытку.", f"Таймаут {timeout} с"
        ) from exc
    except (requests.RequestException, ValueError) as exc:
        # ValueError: сервер ответил не JSON (например, HTML-страницей ошибки)
        raise AudDError("Не удалось связаться с AudD.", str(exc)) from exc

    if payload.get("status") != "success":
        err = payload.get("error") or {}
        code = err.get("error_code")
        exc_class, message = ERROR_MAP.get(code, (AudDError, "AudD вернул ошибку."))
        log.warning("AudD error %s: %s", code, err.get("error_message"))
        raise exc_class(message, f"Код ошибки AudD: {code}" if code else None)

    # status=success, но result=null: запрос прошёл, а песню не узнали
    result = payload.get("result")
    if not result:
        return None

    mbids = [m.get("id") for m in result.get("musicbrainz") or [] if m.get("id")]
    return {
        "artist": result.get("artist", ""),
        "title": result.get("title", ""),
        "album": result.get("album", ""),
        "release_date": result.get("release_date", ""),
        "timecode": result.get("timecode", ""),
        "song_link": result.get("song_link", ""),
        "mbids": mbids,
    }
