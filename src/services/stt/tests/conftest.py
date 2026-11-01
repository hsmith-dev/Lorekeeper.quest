"""Fakes for the HTTP tests: no faster-whisper, ctranslate2 or PyAV needed."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

# Importable whether pytest runs from src/services/stt (pytest.ini) or elsewhere.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stt_service.config import Config  # noqa: E402
from stt_service.models import AudioDecodeError, Segment, Transcription  # noqa: E402

# What FakeDecoder returns for any decodable container: 2 s of a quiet ramp.
DECODED = (np.arange(32000, dtype=np.float32) % 100) / 1000.0
UNDECODABLE = b"definitely not audio"


class FakeClock:
    """Monotonic clock the tests move by hand."""

    def __init__(self, start: float = 1000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeModel:
    """Records the array and prompt it receives; each call takes `cost_s` of clock."""

    def __init__(self, clock: FakeClock, cost_s: float = 0.5):
        self.clock = clock
        self.cost_s = cost_s
        self.calls: list[tuple[np.ndarray, str | None]] = []

    def transcribe(self, audio, initial_prompt):
        self.calls.append((np.array(audio, copy=True), initial_prompt))
        self.clock.advance(self.cost_s)
        return Transcription(
            text="Borin enters the tavern.",
            language="en",
            segments=[Segment(0, 1200, "Borin enters"), Segment(1200, 2000, "the tavern.")],
        )


class FakeDecoder:
    def __init__(self):
        self.calls: list[bytes] = []

    def __call__(self, data: bytes) -> np.ndarray:
        self.calls.append(data)
        if not data:
            raise AudioDecodeError("empty audio")
        if data == UNDECODABLE:
            raise AudioDecodeError("could not decode audio: InvalidDataError")
        return DECODED.copy()


class ModelFactory:
    """model_factory for create_app: counts loads, can be told to fail."""

    def __init__(self, model: FakeModel):
        self.model = model
        self.loads = 0
        self.fail = False
        self.configs: list[Config] = []

    def __call__(self, cfg: Config) -> FakeModel:
        self.loads += 1
        self.configs.append(cfg)
        if self.fail:
            raise RuntimeError("weights corrupt")
        return self.model


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def model_dir(tmp_path):
    d = tmp_path / "faster-whisper-base"
    d.mkdir()
    (d / "model.bin").write_bytes(b"\0" * 16)
    return d


@pytest.fixture
def config(model_dir):
    return Config(model_path=str(model_dir), max_upload_bytes=64 * 1024)


@pytest.fixture
def fake_model(clock):
    return FakeModel(clock)


@pytest.fixture
def factory(fake_model):
    return ModelFactory(fake_model)


@pytest.fixture
def decoder():
    return FakeDecoder()


@pytest.fixture
def app(config, factory, decoder, clock):
    from stt_service.app import create_app

    return create_app(config, model_factory=factory, decoder=decoder, clock=clock)


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient

    with TestClient(app) as c:  # the context runs the lifespan (idle unloader)
        yield c
