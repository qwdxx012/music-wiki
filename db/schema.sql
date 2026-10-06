-- Music Wiki: структурированная реляционная база (SQLite).
--
-- Это ОТДЕЛЬНАЯ база от instance/cache.sqlite3 (там лежит только
-- технический key-value кэш сырых ответов MusicBrainz/Last.fm/AudD).
-- Здесь хранится нормализованная предметная модель: исполнители, альбомы,
-- треки, жанры, факты "этот день" и аналитические логи (распознавания,
-- поисковые запросы), которые накапливаются по мере работы с вики.

PRAGMA foreign_keys = ON;

-- Исполнители (карточка артиста из MusicBrainz)
CREATE TABLE IF NOT EXISTS artists (
    mbid            TEXT PRIMARY KEY,          -- MusicBrainz ID
    name            TEXT NOT NULL,
    type            TEXT,                      -- Персона / Группа / Оркестр ...
    country         TEXT,
    begin_date      TEXT,
    end_date        TEXT,
    disambiguation  TEXT,
    updated_at      TEXT NOT NULL
);

-- Альбомы / релиз-группы, привязанные к исполнителю
CREATE TABLE IF NOT EXISTS albums (
    mbid            TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    primary_type    TEXT,                      -- Album / EP / Single ...
    release_date    TEXT,                      -- ГГГГ-ММ-ДД, если известна
    artist_mbid     TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    FOREIGN KEY (artist_mbid) REFERENCES artists (mbid)
);
CREATE INDEX IF NOT EXISTS idx_albums_artist ON albums (artist_mbid);

-- Треки / записи (recording), опционально привязанные к альбому
CREATE TABLE IF NOT EXISTS tracks (
    mbid                TEXT PRIMARY KEY,
    title               TEXT NOT NULL,
    length_ms           INTEGER,
    first_release_date  TEXT,
    album_mbid          TEXT,
    updated_at          TEXT NOT NULL,
    FOREIGN KEY (album_mbid) REFERENCES albums (mbid)
);
CREATE INDEX IF NOT EXISTS idx_tracks_album ON tracks (album_mbid);

-- Справочник жанров/тегов
CREATE TABLE IF NOT EXISTS genres (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT NOT NULL UNIQUE
);

-- Жанры исполнителя (M:N)
CREATE TABLE IF NOT EXISTS artist_genres (
    artist_mbid TEXT NOT NULL,
    genre_id    INTEGER NOT NULL,
    PRIMARY KEY (artist_mbid, genre_id),
    FOREIGN KEY (artist_mbid) REFERENCES artists (mbid),
    FOREIGN KEY (genre_id) REFERENCES genres (id)
);

-- Жанры трека (M:N)
CREATE TABLE IF NOT EXISTS track_genres (
    track_mbid  TEXT NOT NULL,
    genre_id    INTEGER NOT NULL,
    PRIMARY KEY (track_mbid, genre_id),
    FOREIGN KEY (track_mbid) REFERENCES tracks (mbid),
    FOREIGN KEY (genre_id) REFERENCES genres (id)
);

-- Факты блока "Этот день в истории музыки"
-- (объединяет ручную таблицу data/on_this_day.json и релизы,
-- найденные автоматически на открытых страницах артистов)
CREATE TABLE IF NOT EXISTS facts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    month_day   TEXT NOT NULL,             -- 'MM-DD'
    year        INTEGER,
    text        TEXT NOT NULL,
    source      TEXT NOT NULL,             -- 'таблица фактов' | 'MusicBrainz'
    artist_mbid TEXT,
    album_mbid  TEXT,
    FOREIGN KEY (artist_mbid) REFERENCES artists (mbid),
    FOREIGN KEY (album_mbid) REFERENCES albums (mbid)
);
CREATE INDEX IF NOT EXISTS idx_facts_month_day ON facts (month_day);

-- Журнал распознаваний по аудио (AudD) — аналитика раздела "Что играет?"
CREATE TABLE IF NOT EXISTS recognitions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    recognized_at   TEXT NOT NULL,
    artist_name     TEXT NOT NULL,
    track_title     TEXT NOT NULL,
    score           REAL,
    track_mbid      TEXT,
    source          TEXT NOT NULL DEFAULT 'audd',
    FOREIGN KEY (track_mbid) REFERENCES tracks (mbid)
);

-- Журнал поисковых запросов — аналитика раздела "Поиск"
CREATE TABLE IF NOT EXISTS search_queries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    query_text      TEXT,
    kind            TEXT NOT NULL,          -- 'track' | 'artist'
    genre           TEXT,
    results_count   INTEGER NOT NULL DEFAULT 0,
    searched_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_search_kind ON search_queries (kind);
