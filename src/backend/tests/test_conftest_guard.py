"""Unit tests for the conftest guard that stops the suite wiping a non-test DB."""
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

from tests.conftest import (
    DEFAULT_TEST_DB_URL,
    _guard_test_database,
    is_test_database_name,
    resolve_test_db_url,
)


@pytest.mark.parametrize(
    "name",
    ["lorekeeper_test", "lorekeeper_test_e0qa4", "lorekeeper_test_A1", "x_test"],
)
def test_accepts_test_database_names(name):
    assert is_test_database_name(name)


@pytest.mark.parametrize(
    "name",
    [
        "lorekeeper",
        "lorekeeper_testing",
        "lorekeeper_test_",
        "lorekeeper_test_e0-qa4",
        "lorekeeper_test_a_b",
        "test",
        "",
        None,
    ],
)
def test_rejects_non_test_database_names(name):
    assert not is_test_database_name(name)


def test_url_without_database_name_is_rejected():
    assert not is_test_database_name(make_url("postgresql+asyncpg://u:p@h:5432").database)


def test_default_url_passes_guard():
    assert DEFAULT_TEST_DB_URL == "postgresql+asyncpg://lorekeeper:changeme@localhost:5432/lorekeeper_test"
    assert is_test_database_name(make_url(DEFAULT_TEST_DB_URL).database)


@pytest.mark.parametrize("environ", [{}, {"TEST_DATABASE_URL": ""}])
def test_unset_or_empty_env_falls_back_to_default(environ):
    assert resolve_test_db_url(environ) == DEFAULT_TEST_DB_URL


def test_env_override_is_used():
    url = "postgresql+asyncpg://lorekeeper:changeme@db.example:5432/lorekeeper_test_e0qa4"
    assert resolve_test_db_url({"TEST_DATABASE_URL": url}) == url


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://lorekeeper:changeme@localhost:5432/lorekeeper",
        "postgresql+asyncpg://lorekeeper:changeme@localhost:5432/lorekeeper_testing",
        "postgresql+asyncpg://u:p@h:5432",
    ],
)
def test_guard_exits_session_for_non_test_database(url):
    with pytest.raises(pytest.exit.Exception) as exc:
        _guard_test_database(url)
    assert exc.value.returncode == 1
    assert "Refusing to run tests" in str(exc.value)


def test_guard_allows_lane_database():
    _guard_test_database("postgresql+asyncpg://u:p@h:5432/lorekeeper_test_e0qa4")


def test_guard_exits_on_unparseable_url_without_echoing_it():
    bad = "not a url"
    with pytest.raises(pytest.exit.Exception) as exc:
        _guard_test_database(bad)
    assert exc.value.returncode == 1
    assert "Refusing to run tests" in str(exc.value)
    assert bad not in str(exc.value)


BACKEND_DIR = Path(__file__).resolve().parent.parent


def _run_backend(args, test_db_url):
    return subprocess.run(
        [sys.executable, *args],
        cwd=BACKEND_DIR,
        env={**os.environ, "TEST_DATABASE_URL": test_db_url},
        capture_output=True,
        text=True,
        timeout=300,
    )


def test_session_aborts_before_connecting_to_non_test_database():
    result = _run_backend(
        [
            "-m",
            "pytest",
            "tests/test_conftest_guard.py::test_guard_allows_lane_database",
            "-p",
            "no:cacheprovider",
            "-q",
        ],
        "postgresql+asyncpg://u:p@127.0.0.1:1/lorekeeper",
    )
    assert result.returncode != 0
    assert "Refusing to run tests" in result.stdout + result.stderr


def test_module_level_test_db_url_reads_env_var():
    url = "postgresql+asyncpg://u:p@db.example:5432/lorekeeper_test_e0qa4"
    result = _run_backend(["-c", "import tests.conftest as c; print(c.TEST_DB_URL)"], url)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == url
