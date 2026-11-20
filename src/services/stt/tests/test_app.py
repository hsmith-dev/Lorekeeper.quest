"""HTTP contract of the stt sidecar against a fake model (the I/O matrix rows),
plus the real model / decoder wrappers against stub faster_whisper modules."""

from __future__ import annotations

import ast
import importlib.util
import shutil
import subprocess
import sys
import types
import wave
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from stt_service.app import create_app, rss_bytes, unload_interval
from stt_service.config import MAX_PROMPT_CHARS, MODEL_NAME, Config
from stt_service.models import (
    AudioDecodeError,
    FasterWhisperModel,
    LazyModelSlot,
    decode_container,
    pcm16_to_float32,
)

from tests.conftest import DECODED, UNDECODABLE

PKG = Path(__file__).resolve().parents[1] / "stt_service"


def _post(client, data: bytes, *, prompt: str | None = None, fmt: str | None = None):
    params = {"format": fmt} if fmt is not None else None
    form = {"initial_prompt": prompt} if prompt is not None else None
    return client.post("/v1/transcribe", params=params, data=form,
                       files={"file": ("audio", data, "application/octet-stream")})


# ── health ────────────────────────────────────────────────────────────────

def test_healthz_and_status_on_a_fresh_container(client, factory):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    body = client.get("/v1/status").json()
    assert body["models"] == [{"name": "faster-whisper-base", "kind": "stt", "state": "not_loaded"}]
    assert body["compute_type"] == "int8"
    assert body["device"] == "cpu"
    assert isinstance(body["rss_bytes"], int) and body["rss_bytes"] > 0
    assert factory.loads == 0  # health and status never load the model


def test_healthz_503_when_the_bake_is_broken(tmp_path, factory, decoder, clock):
    app = create_app(Config(model_path=str(tmp_path / "nothing-here")), model_factory=factory,
                     decoder=decoder, clock=clock)
    with TestClient(app) as c:
        r = c.get("/healthz")
    assert r.status_code == 503
    assert r.json() == {"status": "model_missing"}


def test_rss_bytes_positive():
    assert rss_bytes() > 0


# ── transcribe: container audio ───────────────────────────────────────────

def test_transcribe_container_audio(client, fake_model, decoder):
    r = _post(client, b"OggS fake container", prompt="Borin, Waterdeep")
    assert r.status_code == 200, r.text
    assert r.json() == {
        "text": "Borin enters the tavern.",
        "language": "en",
        "segments": [{"start_ms": 0, "end_ms": 1200, "text": "Borin enters"},
                     {"start_ms": 1200, "end_ms": 2000, "text": "the tavern."}],
        "rtf": 0.25,  # 0.5 s of (fake) clock over 2 s of audio
    }
    assert decoder.calls == [b"OggS fake container"]
    (audio, prompt), = fake_model.calls
    assert audio.dtype == np.float32
    np.testing.assert_array_equal(audio, DECODED)
    assert prompt == "Borin, Waterdeep"
    assert client.get("/v1/status").json()["models"][0]["state"] == "loaded"


def test_transcribe_without_prompt_passes_none(client, fake_model):
    assert _post(client, b"webm bytes").status_code == 200
    assert fake_model.calls[0][1] is None


def test_model_loads_once(client, factory):
    for _ in range(3):
        assert _post(client, b"webm bytes").status_code == 200
    assert factory.loads == 1


# ── transcribe: PCM16 ─────────────────────────────────────────────────────

def test_transcribe_pcm16_skips_the_container_decoder(client, fake_model, decoder):
    pcm = np.array([0, 16384, -16384, 32767, -32768] * 3200, dtype="<i2").tobytes()  # 1 s
    r = _post(client, pcm, prompt="Moradin", fmt="pcm16")
    assert r.status_code == 200, r.text
    assert r.json()["rtf"] == 0.5
    assert decoder.calls == []
    (audio, prompt), = fake_model.calls
    expected = np.frombuffer(pcm, "<i2").astype(np.float32) / 32768
    assert audio.dtype == np.float32
    np.testing.assert_array_equal(audio, expected)
    assert audio[1] == 0.5 and audio[4] == -1.0
    assert prompt == "Moradin"


def test_pcm16_helper():
    np.testing.assert_array_equal(pcm16_to_float32(b"\x00\x40\x00\xc0"), np.array([0.5, -0.5], np.float32))
    for bad in (b"", b"\x00\x01\x02"):
        with pytest.raises(AudioDecodeError):
            pcm16_to_float32(bad)


# ── bad input -> 422, too large -> 413 ────────────────────────────────────

@pytest.mark.parametrize("data,fmt", [
    (b"", None),             # empty file
    (b"", "pcm16"),
    (b"\x01\x02\x03", "pcm16"),  # odd-length PCM16
    (UNDECODABLE, None),     # undecodable bytes
    (b"\x00\x00", "wav"),    # format other than pcm16
    (b"\x00\x00", "PCM16"),
])
def test_bad_input_is_422(client, fake_model, data, fmt):
    r = _post(client, data, fmt=fmt)
    assert r.status_code == 422, r.text
    assert "detail" in r.json()
    assert fake_model.calls == []


def test_prompt_length_limit(client):
    assert _post(client, b"webm", prompt="a" * MAX_PROMPT_CHARS).status_code == 200
    r = _post(client, b"webm", prompt="a" * (MAX_PROMPT_CHARS + 1))
    assert r.status_code == 422
    assert "detail" in r.json()


def test_missing_file_is_422(client):
    assert client.post("/v1/transcribe", data={"initial_prompt": "x"}).status_code == 422


def test_upload_limit(client, config, fake_model):
    assert _post(client, b"\x00\x01" * (config.max_upload_bytes // 2)).status_code == 200
    r = _post(client, b"\x00" * (config.max_upload_bytes + 1))
    assert r.status_code == 413
    assert len(fake_model.calls) == 1


def test_default_upload_limit_is_32_mib():
    assert Config().max_upload_bytes == 32 * 1024 * 1024


def test_zero_sample_audio_never_reaches_the_model(config, factory, fake_model):
    app = create_app(config, model_factory=factory, decoder=lambda data: np.zeros(0, np.float32))
    with TestClient(app) as c:
        r = _post(c, b"header-only container")
        assert r.status_code == 200
        assert r.json() == {"text": "", "language": None, "segments": [], "rtf": 0.0}
        assert c.get("/v1/status").json()["models"][0]["state"] == "not_loaded"
    assert fake_model.calls == []
    assert factory.loads == 0


# ── model fails to load -> 503, then retried ──────────────────────────────

def test_load_failure_is_503_and_retried(client, factory):
    factory.fail = True
    r = _post(client, b"webm")
    assert r.status_code == 503
    assert r.json() == {"detail": "speech model unavailable"}
    assert client.get("/v1/status").json()["models"][0]["state"] == "failed"
    assert client.get("/healthz").status_code == 200  # the file is there; only the load failed

    factory.fail = False
    assert _post(client, b"webm").status_code == 200
    assert factory.loads == 2
    assert client.get("/v1/status").json()["models"][0]["state"] == "loaded"


def test_compute_type_reaches_the_loader(model_dir, factory, decoder, clock):
    for ct in ("int8", "float32"):
        app = create_app(Config(model_path=str(model_dir), compute_type=ct),
                         model_factory=factory, decoder=decoder, clock=clock)
        with TestClient(app) as c:
            assert _post(c, b"webm").status_code == 200
            assert c.get("/v1/status").json()["compute_type"] == ct
    assert [c.compute_type for c in factory.configs] == ["int8", "float32"]


# ── idle unload ───────────────────────────────────────────────────────────

def test_idle_unload_drops_the_model_and_reloads_on_demand(client, app, factory, clock):
    slot = app.state.slot
    assert _post(client, b"webm").status_code == 200
    assert slot.state == "loaded"

    assert slot.unload_if_idle(clock(), 600) is False  # just used
    clock.advance(599)
    assert slot.unload_if_idle(clock(), 600) is False
    clock.advance(2)
    assert slot.unload_if_idle(clock(), 600) is True
    assert client.get("/v1/status").json()["models"][0]["state"] == "not_loaded"

    assert _post(client, b"webm").status_code == 200
    assert factory.loads == 2
    assert slot.state == "loaded"


def test_idle_unload_disabled_with_zero(factory, clock):
    slot = LazyModelSlot(MODEL_NAME, "stt", lambda: factory(Config()), clock=clock)
    slot.run(lambda m: None)
    clock.advance(10_000)
    assert slot.unload_if_idle(clock(), 0) is False
    assert slot.state == "loaded"


def test_idle_unload_never_interrupts_a_request(factory, clock):
    slot = LazyModelSlot(MODEL_NAME, "stt", lambda: factory(Config()), clock=clock)
    seen = []

    def busy(model):
        clock.advance(10_000)
        seen.append(slot.unload_if_idle(clock(), 1))  # lock held by this very run
        return model

    slot.run(busy)
    assert seen == [False]
    assert slot.state == "loaded"


def test_last_used_is_stamped_after_a_long_inference(factory, clock):
    slot = LazyModelSlot(MODEL_NAME, "stt", lambda: factory(Config()), clock=clock)

    def slow(model):
        clock.advance(900)  # longer than the idle timeout
        return model

    slot.run(slow)
    assert slot.last_used == clock()
    assert slot.unload_if_idle(clock(), 600) is False  # just finished: not idle
    clock.advance(600)
    assert slot.unload_if_idle(clock(), 600) is True


def test_last_used_is_stamped_even_when_inference_raises(factory, clock):
    slot = LazyModelSlot(MODEL_NAME, "stt", lambda: factory(Config()), clock=clock)

    def boom(model):
        clock.advance(50)
        raise RuntimeError("decode blew up")

    with pytest.raises(RuntimeError):
        slot.run(boom)
    assert slot.last_used == clock()


def test_unloader_thread_lifecycle(app):
    with TestClient(app):
        thread = app.state.unloader
        assert thread is not None and thread.is_alive() and thread.daemon
    assert not thread.is_alive()


def test_no_unloader_thread_when_disabled(model_dir, factory, decoder, clock):
    app = create_app(Config(model_path=str(model_dir), idle_unload_s=0), model_factory=factory,
                     decoder=decoder, clock=clock)
    with TestClient(app):
        assert app.state.unloader is None


def test_unload_interval():
    assert unload_interval(600) == 30
    assert unload_interval(40) == 10


# ── the real wrappers: a stub faster_whisper, a fake ffmpeg subprocess ─────

class _StubSeg:
    def __init__(self, start, end, text):
        self.start, self.end, self.text = start, end, text


@pytest.fixture
def stub_faster_whisper(monkeypatch):
    calls = {}

    class WhisperModel:
        def __init__(self, path, device, compute_type, cpu_threads):
            calls["init"] = dict(path=path, device=device, compute_type=compute_type,
                                 cpu_threads=cpu_threads)

        def transcribe(self, audio, **kw):
            calls["transcribe"] = (audio, kw)
            segs = [_StubSeg(0.0, 1.2344, " Borin enters"), _StubSeg(1.2346, 2.0, " the tavern. ")]
            return iter(segs), types.SimpleNamespace(language="en")

    fw = types.ModuleType("faster_whisper")
    fw.WhisperModel = WhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fw)
    yield calls
    av = sys.modules.get("av")
    if av is not None and getattr(av, "__lorekeeper_av_placeholder__", False):
        del sys.modules["av"]  # the loader's placeholder must not leak into other tests


def test_faster_whisper_model_wrapper(stub_faster_whisper, model_dir):
    cfg = Config(model_path=str(model_dir), compute_type="float32", cpu_threads=2, beam_size=3)
    model = FasterWhisperModel(cfg)
    assert stub_faster_whisper["init"] == dict(path=str(model_dir), device="cpu", compute_type="float32",
                                               cpu_threads=2)
    audio = np.zeros(8, np.float32)
    out = model.transcribe(audio, "Borin")
    got_audio, kw = stub_faster_whisper["transcribe"]
    assert got_audio is audio
    assert kw == dict(language=None, beam_size=3, initial_prompt="Borin", vad_filter=False)
    assert out.text == "Borin enters the tavern."
    assert out.language == "en"
    assert [(s.start_ms, s.end_ms, s.text) for s in out.segments] == [
        (0, 1234, "Borin enters"), (1235, 2000, "the tavern.")]


class _FakeRun:
    """Stands in for subprocess.run: records argv and the temp file's bytes."""

    def __init__(self, returncode=0, stdout=b"", stderr=b"", exc=None):
        self.returncode, self.stdout, self.stderr, self.exc = returncode, stdout, stderr, exc
        self.calls = []

    def __call__(self, argv, **kw):
        with open(argv[argv.index("-i") + 1], "rb") as f:
            self.calls.append((argv, f.read(), kw))
        if self.exc:
            raise self.exc
        return types.SimpleNamespace(returncode=self.returncode, stdout=self.stdout, stderr=self.stderr)


def test_decode_container_runs_ffmpeg_as_a_subprocess():
    samples = np.array([0.5, -0.25, 0.0], dtype="<f4")
    run = _FakeRun(stdout=samples.tobytes() + b"\x00")  # a stray trailing byte is dropped
    out = decode_container(b"OggS...", run=run)
    assert out.dtype == np.float32 and out.tolist() == [0.5, -0.25, 0.0]
    argv, data, kw = run.calls[0]
    assert data == b"OggS..."  # the upload went through a temp file
    assert argv[0] == "ffmpeg"
    assert argv[argv.index("-ar") + 1] == "16000" and argv[argv.index("-ac") + 1] == "1"
    assert argv[argv.index("-f") + 1] == "f32le" and argv[-1] == "pipe:1"
    assert kw["timeout"] > 0 and kw["capture_output"] is True


def test_decode_container_errors():
    with pytest.raises(AudioDecodeError):
        decode_container(b"", run=_FakeRun())
    with pytest.raises(AudioDecodeError, match="Invalid data"):
        decode_container(b"junk", run=_FakeRun(returncode=1, stderr=b"x\npipe: Invalid data found\n"))
    with pytest.raises(AudioDecodeError, match="longer than"):
        decode_container(b"junk", run=_FakeRun(exc=subprocess.TimeoutExpired("ffmpeg", 1)))
    with pytest.raises(RuntimeError, match="cannot run"):  # a broken image is a 500, not a 422
        decode_container(b"junk", run=_FakeRun(exc=FileNotFoundError("ffmpeg")))


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="no ffmpeg CLI here (the image has one)")
def test_decode_container_with_the_real_ffmpeg(tmp_path):
    wav = tmp_path / "t.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x10" * 8000)  # 1 s at 8 kHz
    out = decode_container(wav.read_bytes())
    assert out.dtype == np.float32 and abs(len(out) - 16000) < 160


# ── no PyAV, ever ──────────────────────────────────────────────────────────

def test_whisper_loader_imports_faster_whisper_without_av(monkeypatch):
    """faster_whisper/audio.py does a bare `import av`: the loader satisfies it
    with an inert placeholder only when PyAV is genuinely absent."""
    from stt_service import whisper_loader

    monkeypatch.delitem(sys.modules, "av", raising=False)
    monkeypatch.setattr(whisper_loader.importlib.util, "find_spec",
                        lambda name, *a: None if name == "av" else importlib.util.find_spec(name, *a))
    fw = types.ModuleType("faster_whisper")

    class WhisperModel:  # what `from faster_whisper import WhisperModel` finds
        pass

    fw.WhisperModel = WhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fw)
    assert whisper_loader.whisper_model_class() is WhisperModel
    av = sys.modules["av"]
    assert getattr(av, whisper_loader.PLACEHOLDER_ATTR) is True
    with pytest.raises(whisper_loader.AvNotInstalled, match="deliberately not installed"):
        av.open  # noqa: B018 - any use of PyAV fails loudly
    del sys.modules["av"]


def test_whisper_loader_leaves_a_real_av_alone(monkeypatch):
    from stt_service import whisper_loader

    real = types.ModuleType("av")
    monkeypatch.setitem(sys.modules, "av", real)
    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=object))
    whisper_loader.whisper_model_class()
    assert sys.modules["av"] is real


def test_av_is_not_installed_in_the_image():
    """In the stt image (or a venv built from requirements*.txt) PyAV is absent.
    Skips in the backend-CI interpreter, which is not the image."""
    if importlib.util.find_spec("faster_whisper") is None:
        pytest.skip("not the stt image: faster_whisper is not installed here")
    assert importlib.util.find_spec("av") is None, "PyAV must never be installed in the stt image"


def test_no_module_imports_av():
    for path in PKG.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert "av" not in {a.name.split(".")[0] for a in node.names}, path.name
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] != "av", path.name
                assert node.module != "faster_whisper.audio", path.name


# ── separation ────────────────────────────────────────────────────────────

def test_no_backend_or_heavy_imports_at_module_level():
    """stt_service never imports `app`; only the model/decoder import the speech stack."""
    heavy = {"faster_whisper", "ctranslate2", "av", "torch", "whisper"}
    for path in PKG.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module.split(".")[0]]
            assert "app" not in names, f"{path.name} imports the backend app package"
        for node in tree.body:  # module level only
            if isinstance(node, ast.Import):
                assert not {a.name.split(".")[0] for a in node.names} & heavy, path.name
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in heavy, path.name


def test_importing_app_loads_no_speech_stack():
    import stt_service.app  # noqa: F401

    for mod in ("ctranslate2", "av"):
        assert mod not in sys.modules
