"""The fine-tune installer (ollama_service.install_model_events "finetuned"):
GGUF download from Hugging Face -> Ollama blob upload -> /api/create, with
both HF and Ollama faked by one httpx.MockTransport."""

import hashlib
import json
from collections import namedtuple

import httpx
import pytest

from app.services import ollama_service as svc

OLLAMA = "http://ollama.test:11434"
GGUF = bytes(range(256)) * 1200  # ~300KB, several chunks at the patched chunk size
GGUF_DIGEST = "sha256:" + hashlib.sha256(GGUF).hexdigest()


class FakeWorld:
    """Hugging Face + Ollama, enough of each for the installer."""

    def __init__(self, *, blobs=(), hf_digest=GGUF_DIGEST, hf_body=GGUF, hf_status=200, create_lines=None):
        self.blobs: dict[str, bytes] = {d: b"" for d in blobs}
        self.hf_digest = hf_digest
        self.hf_body = hf_body
        self.hf_status = hf_status
        self.create_lines = create_lines or [{"status": "parsing GGUF"}, {"status": "writing manifest"}, {"status": "success"}]
        self.calls: list[tuple[str, str]] = []
        self.create_payloads: list[dict] = []

    async def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append((request.method, path))
        if request.url.host == "huggingface.co":
            if self.hf_status != 200:
                return httpx.Response(self.hf_status, text="Entry not found")
            if request.method == "HEAD":
                headers = {"x-linked-size": str(len(GGUF)), "location": "https://cdn.test/x"}
                if self.hf_digest:
                    headers["x-linked-etag"] = f'"{self.hf_digest.removeprefix("sha256:")}"'
                return httpx.Response(302, headers=headers)
            return httpx.Response(200, content=self.hf_body)
        if path == "/api/version":
            return httpx.Response(200, json={"version": "0.40.3"})
        if path.startswith("/api/blobs/"):
            digest = path.removeprefix("/api/blobs/")
            if request.method == "HEAD":
                return httpx.Response(200 if digest in self.blobs else 404)
            body = await request.aread()
            if "sha256:" + hashlib.sha256(body).hexdigest() != digest:
                return httpx.Response(400, json={"error": "digest mismatch"})
            self.blobs[digest] = body
            return httpx.Response(201)
        if path == "/api/create":
            payload = json.loads(await request.aread())
            self.create_payloads.append(payload)
            text = "\n".join(json.dumps(line) for line in self.create_lines) + "\n"
            return httpx.Response(200, text=text)
        return httpx.Response(404)

    def count(self, method: str, prefix: str) -> int:
        return sum(1 for m, p in self.calls if m == method and p.startswith(prefix))


Run = namedtuple("Run", "events error done")


@pytest.fixture
def world(monkeypatch):
    def make(**kwargs) -> FakeWorld:
        w = FakeWorld(**kwargs)
        monkeypatch.setattr(svc, "_transport", httpx.MockTransport(w.handler))
        return w

    monkeypatch.setattr(svc, "_CHUNK_BYTES", 64 * 1024)
    monkeypatch.setattr(svc, "_PROGRESS_INTERVAL_S", 0)
    monkeypatch.setattr(svc, "HF_GGUF_APPROX_BYTES", len(GGUF))
    return make


async def run_install(tmp_path, **kwargs) -> Run:
    events = [
        ev
        async for ev in svc.install_model_events(
            "finetuned", target="lorekeeper-test", base_url=OLLAMA, download_dir=str(tmp_path), **kwargs
        )
    ]
    errors = [e["error"] for e in events if "error" in e]
    return Run(events, errors[0] if errors else None, any(e.get("done") for e in events))


def phase(events, word):
    return [e for e in events if word in e.get("status", "") and "total" in e]


async def test_full_install_downloads_uploads_and_creates(world, tmp_path):
    w = world()
    run = await run_install(tmp_path)

    assert run.error is None and run.done
    assert run.events[-1] == {"done": True, "model": "lorekeeper-test"}
    assert w.blobs[GGUF_DIGEST] == GGUF  # uploaded byte-for-byte
    assert w.create_payloads == [
        {
            "model": "lorekeeper-test",
            "files": {"lorekeeper-7b-q4.gguf": GGUF_DIGEST},
            "template": svc.MISTRAL_TEMPLATE,
            "parameters": {"stop": ["[INST]", "[/INST]", "</s>"]},
            "stream": True,
        }
    ]
    # Both phases report progress in the same {total, completed} shape the UI renders.
    for word in ("downloading", "uploading"):
        prog = phase(run.events, word)
        assert len(prog) > 2, word
        assert all(p["total"] == len(GGUF) for p in prog)
        assert prog[-1]["completed"] == len(GGUF)
    assert list(tmp_path.iterdir()) == []  # temp file cleaned up


async def test_rerun_skips_download_when_ollama_has_blob(world, tmp_path):
    w = world()
    assert (await run_install(tmp_path)).done
    w.calls.clear()

    run = await run_install(tmp_path)

    assert run.done and run.error is None
    assert w.count("GET", "/harrisonsmith") == 0
    assert w.count("POST", "/api/blobs") == 0
    assert any("skipping download" in e.get("status", "") for e in run.events)
    assert len(w.create_payloads) == 2  # create re-run overwrites; still succeeds


async def test_downloaded_blob_already_present_skips_upload(world, tmp_path):
    w = world(blobs=[GGUF_DIGEST])
    run = await run_install(tmp_path, reuse_existing_blob=False)

    assert run.done
    assert w.count("GET", "/harrisonsmith") == 1
    assert w.count("POST", "/api/blobs") == 0
    assert any("skipping upload" in e.get("status", "") for e in run.events)
    assert list(tmp_path.iterdir()) == []


async def test_no_published_digest_still_installs(world, tmp_path):
    w = world(hf_digest=None)
    run = await run_install(tmp_path)

    assert run.done
    assert w.create_payloads[0]["files"] == {"lorekeeper-7b-q4.gguf": GGUF_DIGEST}


async def test_checksum_mismatch_fails_and_cleans_up(world, tmp_path):
    w = world(hf_body=GGUF[:-1] + b"X")
    run = await run_install(tmp_path)

    assert not run.done
    assert "checksum" in run.error
    assert w.count("POST", "/api/blobs") == 0 and w.create_payloads == []
    assert list(tmp_path.iterdir()) == []


async def test_not_enough_disk_fails_before_download(world, tmp_path, monkeypatch):
    w = world()
    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(svc.shutil, "disk_usage", lambda _: Usage(10**9, 10**9, 1024))
    run = await run_install(tmp_path)

    assert "Not enough free disk space" in run.error and "LLM_DOWNLOAD_DIR" in run.error
    assert w.count("GET", "/harrisonsmith") == 0


async def test_missing_download_dir_is_reported(world, tmp_path):
    world()
    run = await run_install(tmp_path / "nope")
    assert "not usable" in run.error


async def test_hf_missing_file_is_reported(world, tmp_path):
    world(hf_status=404)
    run = await run_install(tmp_path)
    assert "Hugging Face has no file" in run.error and "404" in run.error


async def test_ollama_unreachable_is_reported(monkeypatch, tmp_path):
    def refuse(request):
        raise httpx.ConnectError("connection refused", request=request)

    monkeypatch.setattr(svc, "_transport", httpx.MockTransport(refuse))
    run = await run_install(tmp_path)
    assert "Ollama is not reachable" in run.error


async def test_create_error_is_reported(world, tmp_path):
    world(create_lines=[{"status": "parsing GGUF"}, {"error": "invalid file magic"}])
    run = await run_install(tmp_path)
    assert not run.done
    assert "invalid file magic" in run.error


async def test_create_without_success_is_an_error(world, tmp_path):
    world(create_lines=[{"status": "parsing GGUF"}])
    run = await run_install(tmp_path)
    assert "without reporting success" in run.error


async def test_abandoned_install_removes_temp_file(world, tmp_path):
    world()
    gen = svc.install_model_events("finetuned", target="t", base_url=OLLAMA, download_dir=str(tmp_path))
    async for ev in gen:
        if "downloading" in ev.get("status", "") and ev.get("completed"):
            assert len(list(tmp_path.iterdir())) == 1  # mid-download
            break
    await gen.aclose()  # what Starlette does when the browser tab goes away
    assert list(tmp_path.iterdir()) == []
    assert not svc._install_lock.locked()


async def test_concurrent_install_is_refused(world, tmp_path):
    world()
    async with svc._install_lock:
        run = await run_install(tmp_path)
    assert "already running" in run.error
