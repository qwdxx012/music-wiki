import pytest

from app import create_app
from config import Config


class FakeWikiStore:
    """In-memory заглушка базы: тесты не ходят в Supabase."""

    def __init__(self):
        self.artists = {}
        self.tracks = {}

    def upsert_artist(self, artist):
        self.artists[artist["id"]] = {
            "mbid": artist["id"],
            "updated_at": "2026-01-01T00:00:00+00:00",
        }

    def upsert_track(self, track, album_mbid=None):
        self.tracks[track["id"]] = {
            "mbid": track["id"],
            "updated_at": "2026-01-01T00:00:00+00:00",
        }

    def list_artists_for_sitemap(self):
        return list(self.artists.values())

    def list_tracks_for_sitemap(self):
        return list(self.tracks.values())

    def log_search(self, *args, **kwargs):
        pass

    def log_recognition(self, *args, **kwargs):
        pass

    def upsert_album(self, *args, **kwargs):
        pass

    def counts(self):
        return {}


@pytest.fixture
def app(tmp_path):
    class TestConfig(Config):
        TESTING = True
        SECRET_KEY = "test"
        # Внешние API и Supabase в тестах не вызываются
        LASTFM_API_KEY = ""
        AUDD_API_TOKEN = ""
        SUPABASE_URL = ""
        SUPABASE_KEY = ""

    application = create_app(TestConfig)
    application.extensions["wiki_store"] = FakeWikiStore()
    return application


@pytest.fixture
def client(app):
    return app.test_client()
