"""Обёртки для внешних вызовов (MusicBrainz, Last.fm).
"""

import logging
from concurrent.futures import ThreadPoolExecutor

from flask import current_app

log = logging.getLogger("musicwiki.external")


def safe(label, fn, *args, reraise=(), **kwargs):
    """Вызывает fn(*args) и возвращает пару (результат, failed).

    failed=True значит "сервис упал, результата нет". label - человеческое
    название вызова для лога. Исключения из reraise (например, "артист не
    найден") не глотаются: их обработает общий обработчик ошибок Flask.
    """
    try:
        return fn(*args, **kwargs), False
    except reraise:
        raise
    except Exception as exc:  # noqa: BLE001
        # Ловим всё подряд сознательно: любой сбой внешнего сервиса = блок недоступен
        log.error("Внешний вызов «%s» упал: %s", label, exc, exc_info=True)
        return None, True


def parallel(jobs):
    """jobs: {имя: (label, fn, args)} -> {имя: (результат, failed)}.

    MusicBrainz и Last.fm опрашиваются одновременно: страница артиста
    ждёт самый медленный сервис, а не сумму всех.
    """
    # В новом потоке нет "текущего приложения" Flask, а сервисам нужны
    # current_app.config и кэш. Поэтому передаём сам объект app и в каждом
    # потоке заново входим в его контекст
    app = current_app._get_current_object()

    def run(label, fn, args):
        with app.app_context():
            return safe(label, fn, *args)

    with ThreadPoolExecutor(max_workers=max(1, len(jobs))) as pool:
        futures = {name: pool.submit(run, *job) for name, job in jobs.items()}
        return {name: future.result() for name, future in futures.items()}
