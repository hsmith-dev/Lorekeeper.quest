"""F3-world (03c0b504f1d1) is the first revision that needs PostgreSQL 15+
(`ON DELETE SET NULL (column)`). Its upgrade() refuses an older server with a
clear message before any DDL runs. No database is needed: the version query
is faked.
"""
import importlib.util
from pathlib import Path

import pytest

_REVISION = (Path(__file__).resolve().parents[2] / "migrations" / "versions"
             / "03c0b504f1d1_f3_world_entities_legacy_copy.py")


def _load():
    spec = importlib.util.spec_from_file_location("f3_world_revision_guard", _REVISION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


f3_world = _load()


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class FakeBind:
    def __init__(self, version_num: str):
        self.version_num = version_num
        self.statements: list[str] = []

    def execute(self, clause, *args, **kwargs):
        self.statements.append(str(clause))
        return _Result(self.version_num)


class RecordingOp:
    """Stands in for alembic.op: records every call; get_bind returns the fake."""

    def __init__(self, bind):
        self._bind = bind
        self.calls: list[str] = []

    def get_bind(self):
        return self._bind

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append(name)
        return record


class OnlineContext:
    @staticmethod
    def is_offline_mode():
        return False


@pytest.mark.parametrize("version_num, found", [("140011", "14.11"), ("130000", "13.0"), ("90624", "90624")])
def test_old_server_is_refused_with_a_clear_message(version_num, found):
    with pytest.raises(f3_world.UnsupportedPostgresError) as exc:
        f3_world.require_postgres_15(FakeBind(version_num))
    message = str(exc.value)
    assert f"requires PostgreSQL 15 or newer (found {found})" in message
    assert "pgvector/pgvector:pg16" in message and "docs/UPGRADING.md" in message


@pytest.mark.parametrize("version_num", ["150000", "150008", "160010", "170002"])
def test_supported_server_passes(version_num):
    bind = FakeBind(version_num)
    f3_world.require_postgres_15(bind)
    assert bind.statements == ["SHOW server_version_num"]


def test_upgrade_checks_the_version_before_any_ddl(monkeypatch):
    bind = FakeBind("140011")
    recorder = RecordingOp(bind)
    monkeypatch.setattr(f3_world, "op", recorder)
    monkeypatch.setattr(f3_world, "context", OnlineContext)
    with pytest.raises(f3_world.UnsupportedPostgresError):
        f3_world.upgrade()
    assert recorder.calls == [], f"DDL ran before the version guard: {recorder.calls}"
    assert bind.statements == ["SHOW server_version_num"]
