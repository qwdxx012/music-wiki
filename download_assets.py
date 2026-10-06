import re
from pathlib import Path
from urllib.parse import urljoin

import requests

STATIC = Path(__file__).resolve().parent / "static"

XP_CSS_URL = "https://unpkg.com/xp.css/dist/XP.css"

# Silk icon set 1.3, Mark James, famfamfam.com, CC BY 2.5.
# Пробуем два зеркала по очереди: npm-пакет через unpkg и репозиторий на GitHub
SILK_MIRRORS = [
    "https://unpkg.com/famfamfam-silk/dist/png/{name}.png",
    "https://raw.githubusercontent.com/legacy-icons/famfamfam-silk/master/dist/png/{name}.png",
]
# Все иконки, на которые ссылаются шаблоны, CSS и services/genres.py
SILK_ICONS = [
    "music",  # трек, favicon
    "cd",  # альбом, заглушка обложки, эпоха 90-х
    "user",  # исполнитель, заглушка фото
    "lightbulb",  # совет дня
    "calendar",  # этот день в истории
    "information",  # окно-сообщение: инфо
    "error",  # окно-сообщение: предупреждение (жёлтый треугольник)
    "exclamation",  # окно-сообщение: ошибка (красный круг)
    "sound",  # кнопка "Записать", жанр хип-хоп
    "wand",  # кнопка "Мне повезёт"
    "lightning",  # рок
    "computer",  # электроника
    "heart",  # поп
    "rainbow",  # 70-е
    "joystick",  # 80-е
]


def download_xp_css():
    dest = STATIC / "css"
    dest.mkdir(parents=True, exist_ok=True)
    resp = requests.get(XP_CSS_URL, timeout=30)
    resp.raise_for_status()
    css = resp.text
    (dest / "xp.css").write_text(css, encoding="utf-8")
    print("saved xp.css from", resp.url)

    # xp.css ссылается на шрифты и картинки относительными путями url(...).
    # Скачиваем их рядом, сохраняя структуру папок. data: URI и внешние
    # адреса пропускаем: первые уже внутри CSS, вторые браузер загрузит сам
    for ref in set(re.findall(r"url\(['\"]?([^'\")]+)['\"]?\)", css)):
        if ref.startswith(("data:", "http:", "https:", "#")):
            continue
        target = dest / ref.split("?")[0].split("#")[0]
        target.parent.mkdir(parents=True, exist_ok=True)
        r = requests.get(urljoin(resp.url, ref), timeout=30)
        if r.ok:
            target.write_bytes(r.content)
            print("saved", ref)
        else:
            print("skip", ref, r.status_code)


def download_silk():
    dest = STATIC / "img" / "silk"
    dest.mkdir(parents=True, exist_ok=True)
    missing = []
    for name in SILK_ICONS:
        for mirror in SILK_MIRRORS:
            try:
                r = requests.get(mirror.format(name=name), timeout=30)
            except requests.RequestException:
                continue
            if r.ok and r.content.startswith(b"\x89PNG"):
                (dest / f"{name}.png").write_bytes(r.content)
                print("saved silk", name)
                break
        else:
            missing.append(name)
    if missing:
        print("НЕ СКАЧАНЫ:", ", ".join(missing))


if __name__ == "__main__":
    download_xp_css()
    download_silk()
