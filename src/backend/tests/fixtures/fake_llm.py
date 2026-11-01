"""The fake LLM fixture and the KOBOLD_URL socket guard (E0-LLM.5).

tests/conftest.py imports both, so every test gets them:

- ``fake_llm``: llm_provider.fake_llm, reset before and after the test.
  ``fake_llm.script([...])`` queues replies (an exception instance is
  raised). Under ENVIRONMENT=test every config without a MockTransport on
  llm_provider._transport is answered by it (llm_provider.fake_llm_active).
- ``no_kobold_socket`` (autouse): CI has no model, so no test may open a
  socket to KOBOLD_URL. A connect to its resolved (ip, port) is refused
  (OSError) and recorded, and the test fails at teardown. ``ollama``-marked
  tests are exempt and set llm_provider._real_llm_in_test, which turns the
  fake off for them.
"""
from __future__ import annotations

import errno
import functools
import socket
from urllib.parse import urlsplit

import pytest

from app.clients.fakes import FakeLLM
from app.core.config import get_settings
from app.services import llm_provider


@pytest.fixture
def fake_llm() -> FakeLLM:
    llm_provider.fake_llm.reset()
    yield llm_provider.fake_llm
    llm_provider.fake_llm.reset()


@functools.lru_cache(maxsize=8)
def kobold_targets(url: str) -> frozenset[tuple[str, int]]:
    """The (host, port) pairs a connect to url can use: the literal host and
    every address it resolves to. A host that doesn't resolve keeps only the
    literal pair."""
    parts = urlsplit(url)
    host = parts.hostname or "localhost"
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        port = 80
    targets = {(host, port)}
    try:
        for *_, sockaddr in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM):
            targets.add((str(sockaddr[0]), int(sockaddr[1])))
    except OSError:
        pass
    return frozenset(targets)


class KoboldSocketGuard:
    """Refuses and records connects to KOBOLD_URL; verify() fails the test
    if any were recorded."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.targets = kobold_targets(url)
        self.hits: list[tuple] = []

    def _blocked(self, address) -> bool:
        if not isinstance(address, tuple) or len(address) < 2:
            return False  # AF_UNIX path, etc.
        try:
            return (str(address[0]), int(address[1])) in self.targets
        except (TypeError, ValueError):
            return False

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        real_connect = socket.socket.connect
        real_connect_ex = socket.socket.connect_ex
        guard = self

        def connect(sock, address):
            if guard._blocked(address):
                guard.hits.append(address)
                raise ConnectionRefusedError(
                    errno.ECONNREFUSED, f"no_kobold_socket: tests may not connect to KOBOLD_URL {guard.url}"
                )
            return real_connect(sock, address)

        def connect_ex(sock, address):
            if guard._blocked(address):
                guard.hits.append(address)
                return errno.ECONNREFUSED
            return real_connect_ex(sock, address)

        monkeypatch.setattr(socket.socket, "connect", connect)
        monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)

    def verify(self) -> None:
        if self.hits:
            pytest.fail(
                f"opened a socket to KOBOLD_URL ({self.url}) {len(self.hits)} time(s): {self.hits!r}. "
                "CI has no model: use the fake LLM (fake_llm fixture), an httpx.MockTransport on "
                "llm_provider._transport, or mark the test `ollama`.",
                pytrace=False,
            )


@pytest.fixture(autouse=True)
def no_kobold_socket(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    if request.node.get_closest_marker("ollama") is not None:
        monkeypatch.setattr(llm_provider, "_real_llm_in_test", True)
        yield None
        return
    guard = KoboldSocketGuard(get_settings().kobold_url)
    guard.install(monkeypatch)
    yield guard
    guard.verify()
