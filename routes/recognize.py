import logging
import os

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from werkzeug.exceptions import RequestEntityTooLarge

from routes.safe import safe
from services import audd
from services import musicbrainz as mb

bp = Blueprint("recognize", __name__)
log = logging.getLogger("musicwiki.external")

ALLOWED_EXT = {
    ".mp3",
    ".wav",
    ".ogg",
    ".oga",
    ".opus",
    ".m4a",
    ".mp4",
    ".aac",
    ".flac",
    ".webm",
    ".3gp",
    ".amr",
    ".wma",
    ".aiff",
    ".aif",
    ".caf",
}
# Телефоны пишут голосовые как video/mp4, video/webm, video/3gpp
ALLOWED_MIME_PREFIX = ("audio/", "video/")


def _wants_json():
    """Запись с микрофона шлётся из recorder.js через fetch() с этим заголовком.

    Одна и та же ручка /recognize обслуживает и обычную форму (ответ -
    HTML-страница), и fetch (ответ - JSON, дальше решает JavaScript).
    """
    return request.headers.get("X-Requested-With") == "fetch"


def _dialog(title, message, details=None, code=422, kind="error"):
    if _wants_json():
        return (
            jsonify(ok=False, title=title, message=message, details=details, kind=kind),
            code,
        )
    dialog = {"title": title, "message": message, "details": details, "kind": kind}
    return render_template("recognize.html", dialog=dialog), code


def _go(url):
    # fetch() не умеет "перейти на страницу" по redirect, поэтому для него
    # возвращаем адрес в JSON, а JS сам делает window.location.href = url
    if _wants_json():
        return jsonify(ok=True, redirect=url)
    return redirect(url)


def _pick_upload():
    """В форме два поля name="audio": "выбрать файл" и "диктофон телефона".

    Blob с микрофона приходит под тем же именем. Берём первый непустой файл.
    """
    for f in request.files.getlist("audio"):
        if f and f.filename:
            return f
    return None


def _validate(upload):
    # Проверяем и расширение, и MIME-тип: у записи с телефона расширения может
    # не быть, а у файла с диска MIME-тип браузер иногда не знает
    ext = os.path.splitext(upload.filename)[1].lower()
    mime = (upload.mimetype or "").lower()
    if ext not in ALLOWED_EXT and not mime.startswith(ALLOWED_MIME_PREFIX):
        raise audd.AudDBadFile(
            f"Файл «{upload.filename}» не является аудиофайлом.",
            "Поддерживаются MP3, WAV, OGG, M4A, FLAC, WEBM и другие аудиоформаты.",
        )
    data = upload.read()
    if not data:
        raise audd.AudDBadFile("Файл пустой.", "Возможно, запись прервалась.")
    return data


def _find_mbid(match):
    """MBID от AudD, а если его нет - ищем в MusicBrainz по исполнителю и названию."""
    for mbid in match["mbids"]:
        if len(mbid) == 36:
            return mbid
    found, _ = safe(
        "MusicBrainz: поиск распознанного трека",
        mb.find_recording,
        match["artist"],
        match["title"],
    )
    return found


@bp.route("/recognize", methods=["GET", "POST"])
def recognize():
    if request.method == "GET":
        return render_template("recognize.html", dialog=None)

    upload = _pick_upload()
    if upload is None:
        return _dialog(
            "Что играет?",
            "Сначала выберите файл или запишите звук.",
            code=400,
            kind="warning",
        )
    try:
        data = _validate(upload)
        match = audd.recognize(data, upload.filename, upload.mimetype)
    except audd.AudDNoMatch as exc:
        # "Не нашли" - нормальная ситуация, а не сбой: пишем в лог как info
        log.info(
            "AudD: совпадений нет (%s, %d байт)",
            upload.filename,
            request.content_length or 0,
        )
        return _dialog(exc.title, exc.message, exc.details, code=404)
    except audd.AudDError as exc:
        log.error("AudD упал: %s", exc.message, exc_info=True)
        # 503 - проблема на нашей стороне (нет токена, кончился лимит),
        # 422 - проблема с самим файлом
        limits = (audd.AudDConfigError, audd.AudDLimitError)
        code = 503 if isinstance(exc, limits) else 422
        return _dialog(exc.title, exc.message, exc.details, code=code)

    label = f'{match["artist"]} - {match["title"]}'
    note = f" (фрагмент с {match['timecode']})" if match["timecode"] else ""
    mbid = _find_mbid(match)

    # Аналитика: каждое успешное распознавание AudD пишем в таблицу
    # recognitions (services/store.py), даже если MusicBrainz не нашёл MBID
    try:
        current_app.extensions["wiki_store"].log_recognition(
            match["artist"], match["title"], match.get("score"), track_mbid=mbid
        )
    except Exception:  # noqa: BLE001
        log.error("Не удалось записать распознавание в БД", exc_info=True)

    if mbid:
        flash(f"Распознано: {label}{note}")
        return _go(url_for("main.track", mbid=mbid))

    # Трек AudD знает, а MusicBrainz нет: отправляем в поиск, чтобы не потерять результат
    flash(f"Распознано: {label}{note}. Точной записи в MusicBrainz нет, вот похожие.")
    return _go(url_for("main.search", q=f'{match["artist"]} {match["title"]}'))


@bp.app_errorhandler(RequestEntityTooLarge)
def too_large(_exc):
    # Сюда Flask попадает сам, если файл больше MAX_CONTENT_LENGTH из config.py
    mb_limit = current_app.config["MAX_UPLOAD_MB"]
    return _dialog(
        "Файл слишком большой",
        f"Размер файла превышает {mb_limit} МБ.",
        "Обрежьте запись до 10-20 секунд и попробуйте снова.",
        code=413,
    )
