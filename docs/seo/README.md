# SEO-отчет

Проект: Music Wiki (Flask + Jinja2).

## Что сделано

- В `templates/layout.html` добавлены метатеги `description`, `canonical` и Open Graph.
  `lang`, `charset` и `viewport` уже были в проекте.
- Для каждой страницы заданы свои `title` и `description`.
- На каждой странице один `h1`. На главной добавлены `h2` для основных блоков,
  на странице артиста - для дискографии и похожих исполнителей.
- `robots.txt` отдается по адресу `/robots.txt` и закрывает служебные разделы:
  `/search`, `/random`, `/track/lookup`, `/artist/lookup`, `/api/`.
- `sitemap.xml` отдается по адресу `/sitemap.xml`. В него попадают главная,
  `/about`, `/recognize`, а также карточки артистов и треков из SQLite.
- На страницы ошибок, в результатах поиска и в диалогах распознавания добавлен
  `meta name="robots" content="noindex, nofollow"`.
- Для JSON-ответов API добавлен заголовок `X-Robots-Tag: noindex, nofollow`.
- Адрес сайта берется из `SITE_URL` в `.env`.
- Для скорости GIF маскота для страницы уменьшен до 160x112 (163 КБ), у иконок,
  аватара и обложки указаны `width` и `height`, у аватара и обложки добавлен
  `decoding="async"`, статика отдается с `Cache-Control: public, max-age=3600`.

## Lighthouse

Замеры в Lighthouse 13.4.1, режим Navigation, Desktop, категории Performance и SEO.
Проект запускался на локальном WSGI-сервере waitress.

- SEO 100;
- Performance 99, LCP 0.8 с, CLS 0, TBT 0 мс.

`python -m pytest -q` - 18 passed.
`python -m black --check app.py config.py routes/seo.py tests` - 6 files unchanged.

## Итог

Все пункты задания выполнены. `/search` закрыт в `robots.txt`, поэтому страницы
выдачи не попадают в sitemap. Карточки артистов и треков добавляются в sitemap
автоматически, когда появляются в базе.
