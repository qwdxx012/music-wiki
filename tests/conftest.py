import pytest

from app import create_app
from config import Config


@pytest.fixture
def app(tmp_path):
    class TestConfig(Config):
        TESTING = True
        SECRET_KEY = "test"
        # Внешние API в тестах не вызываются
        LASTFM_API_KEY = ""
        AUDD_API_TOKEN = ""
        CACHE_DB = str(tmp_path / "cache.sqlite3")
        WIKI_DB = str(tmp_path / "wiki.sqlite3")

    return create_app(TestConfig)


@pytest.fixture
def client(app):
    return app.test_client()
