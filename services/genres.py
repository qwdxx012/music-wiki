"""Ярлыки жанров и эпох на главной.

lastfm - тег Last.fm для топов (быстро и показывает известных артистов).
mb_recording / mb_artist - фильтр в синтаксисе поиска MusicBrainz (Lucene):
используется, если Last.fm недоступен или пользователь ищет текст внутри жанра.
icon - имя PNG из набора Silk в static/img/silk/.
"""


def _decade(start):
    # Диапазон дат в синтаксисе Lucene: [1970-01-01 TO 1979-12-31]
    return f"[{start}-01-01 TO {start + 9}-12-31]"


def _tag(label, icon, lastfm, mb_tag):
    return {
        "label": label,
        "icon": icon,
        "lastfm": lastfm,
        "mb_recording": f"tag:{mb_tag}",
        "mb_artist": f"tag:{mb_tag}",
    }


def _era(label, icon, start):
    return {
        "label": label,
        "icon": icon,
        "lastfm": f"{start % 100}s",
        # у записи смотрим дату первого релиза, у артиста - год начала карьеры
        "mb_recording": f"firstreleasedate:{_decade(start)}",
        "mb_artist": f"begin:{_decade(start)}",
    }


GENRES = {
    "rock": _tag("Рок", "lightning.png", "rock", "rock"),
    "electronic": _tag("Электроника", "computer.png", "electronic", "electronic"),
    "pop": _tag("Поп", "heart.png", "pop", "pop"),
    "hip-hop": _tag("Хип-хоп", "sound.png", "hip-hop", '"hip hop"'),
    "jazz": _tag("Джаз", "music.png", "jazz", "jazz"),
    "70s": _era("70-е", "rainbow.png", 1970),
    "80s": _era("80-е", "joystick.png", 1980),
    "90s": _era("90-е", "cd.png", 1990),
}


def get(key):
    return GENRES.get((key or "").strip().lower())
