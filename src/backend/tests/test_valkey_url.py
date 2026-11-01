"""VALKEY_URL, with REDIS_URL as its deprecated fallback (Redis -> Valkey)."""

import logging

import pytest

from app.core import config
from app.core.config import DEFAULT_VALKEY_URL, Settings

BASE = dict(
    _env_file=None,
    database_url="postgresql+asyncpg://u:p@localhost/x_test",
    postgres_password="p",
    secret_key="s",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("VALKEY_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setattr(config, "_redis_url_warned", False)


def test_default_is_the_valkey_service():
    assert Settings(**BASE).valkey_url == DEFAULT_VALKEY_URL == "redis://valkey:6379/0"


def test_valkey_url_env(monkeypatch, caplog):
    monkeypatch.setenv("VALKEY_URL", "redis://kv.internal:6380/2")
    with caplog.at_level(logging.WARNING, logger="app.core.config"):
        assert Settings(**BASE).valkey_url == "redis://kv.internal:6380/2"
    assert "REDIS_URL is deprecated" not in caplog.text


def test_redis_url_fallback_warns_once(monkeypatch, caplog):
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    with caplog.at_level(logging.WARNING, logger="app.core.config"):
        assert Settings(**BASE).valkey_url == "redis://redis:6379/0"
        assert Settings(**BASE).valkey_url == "redis://redis:6379/0"
    assert caplog.text.count("REDIS_URL is deprecated") == 1


def test_valkey_url_wins_over_redis_url(monkeypatch, caplog):
    monkeypatch.setenv("VALKEY_URL", "redis://valkey:6379/1")
    monkeypatch.setenv("REDIS_URL", "redis://old:6379/0")
    with caplog.at_level(logging.WARNING, logger="app.core.config"):
        assert Settings(**BASE).valkey_url == "redis://valkey:6379/1"
    assert "REDIS_URL is deprecated" not in caplog.text


def test_empty_valkey_url_counts_as_unset(monkeypatch):
    monkeypatch.setenv("VALKEY_URL", "")
    monkeypatch.setenv("REDIS_URL", "redis://old:6379/0")
    assert Settings(**BASE).valkey_url == "redis://old:6379/0"


async def test_client_uses_valkey_url(monkeypatch):
    from app.core import valkey_client

    seen = {}

    def fake_from_url(url, **kw):
        seen["url"] = url
        return object()

    monkeypatch.setattr(valkey_client.aioredis, "from_url", fake_from_url)
    monkeypatch.setattr(valkey_client, "get_settings",
                        lambda: Settings(**BASE, valkey_url="redis://kv:6379/3"))
    monkeypatch.setattr(valkey_client, "_valkey", None)
    await valkey_client.init_valkey()
    assert seen["url"] == "redis://kv:6379/3"
    assert valkey_client.get_valkey() is not None


def test_old_module_names_still_import():
    from app.core import redis_client, valkey_client

    assert redis_client.get_redis is valkey_client.get_valkey
