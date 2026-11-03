"""load_config: defaults, every STT_* variable, and the compute-type check."""

from __future__ import annotations

import pytest

from stt_service.config import COMPUTE_TYPES, DEFAULT_MODEL_PATH, Config, load_config


def test_defaults():
    cfg = load_config({})
    assert cfg == Config()
    assert cfg.model_path == DEFAULT_MODEL_PATH == "/models/faster-whisper-base"
    assert cfg.compute_type == "int8"
    assert cfg.device == "cpu"
    assert cfg.cpu_threads == 0
    assert cfg.idle_unload_s == 600
    assert cfg.max_upload_bytes == 32 * 1024 * 1024
    assert cfg.language is None  # auto-detect, as openai-whisper did
    assert cfg.beam_size == 5


def test_every_variable():
    cfg = load_config({
        "STT_MODEL_PATH": "/tmp/fw", "STT_COMPUTE_TYPE": "float32", "STT_DEVICE": "cuda",
        "STT_CPU_THREADS": "2", "STT_IDLE_UNLOAD_S": "0", "STT_MAX_UPLOAD_BYTES": "1024",
        "STT_LANGUAGE": "en", "STT_BEAM_SIZE": "1",
    })
    assert cfg == Config(model_path="/tmp/fw", compute_type="float32", device="cuda", cpu_threads=2,
                         idle_unload_s=0, max_upload_bytes=1024, language="en", beam_size=1)


def test_empty_values_mean_default():
    assert load_config({"STT_COMPUTE_TYPE": "", "STT_LANGUAGE": "", "STT_IDLE_UNLOAD_S": ""}) == Config()


@pytest.mark.parametrize("ct", COMPUTE_TYPES)
def test_known_compute_types(ct):
    assert load_config({"STT_COMPUTE_TYPE": ct}).compute_type == ct


def test_bogus_compute_type_fails_at_startup():
    with pytest.raises(ValueError, match="bogus"):
        load_config({"STT_COMPUTE_TYPE": "bogus"})
    with pytest.raises(ValueError):
        Config(compute_type="int4")


def test_bogus_compute_type_stops_create_app(monkeypatch):
    from stt_service.app import create_app

    monkeypatch.setenv("STT_COMPUTE_TYPE", "bogus")
    with pytest.raises(ValueError):
        create_app()
