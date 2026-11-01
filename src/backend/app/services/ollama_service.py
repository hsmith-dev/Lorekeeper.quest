"""Talk to the stack's own Ollama instance (the thing KOBOLD_URL points at in
the default self-hosted deployment) over its NATIVE API — /api/tags, /api/pull,
/api/blobs, /api/create, /api/copy — rather than the OpenAI-compat surface llm_provider.py
uses for completions.

This exists so a self-hoster never has to shell into the ollama container:
the admin portal's System tab can see which models are installed and install
the recommended ones straight from their public registries (the fine-tune
from Hugging Face, the base model from the Ollama library) with live
progress. Every function here degrades to a clear error string instead of
raising — the callers are diagnostics/UI surfaces where "Ollama is down:
<why>" is the useful output, not a 500.
"""

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import time
from contextlib import aclosing

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# The published fine-tune. NOT pulled with `ollama pull hf.co/...`: the HF
# repo also carries the safetensors LoRA adapter (lorekeeper-lora/) next to
# the GGUF, and Ollama's HF bridge rejects any such mixed repo with
# "400: Repository is not GGUF or is not compatible with llama.cpp". So the
# installer downloads the one GGUF file itself, hands it to Ollama as a blob
# (/api/blobs) and builds the model from it (/api/create with `files`) —
# the API equivalent of `ollama create -f lorekeeper-Modelfile`.
HF_REPO = "harrisonsmith/Lorekeeper-Mistral-7B-GGUF"
HF_GGUF_FILENAME = "lorekeeper-7b-q4.gguf"
HF_GGUF_URL = f"https://huggingface.co/{HF_REPO}/resolve/main/{HF_GGUF_FILENAME}"
# Used for the free-disk check only when Hugging Face doesn't report a size.
HF_GGUF_APPROX_BYTES = 4_372_815_616
# Slack on top of the file size before we start a multi-GB download.
DISK_HEADROOM_BYTES = 512 * 1024 * 1024
_CHUNK_BYTES = 1024 * 1024
# Progress events are throttled to this — the UI only needs a few per second.
_PROGRESS_INTERVAL_S = 0.5

# The un-fine-tuned counterpart, from the Ollama library — same base
# architecture (Mistral 7B Instruct) the LoRA was trained on.
BASE_LIBRARY_REF = "mistral:7b-instruct-q4_0"

# Mistral-instruct chat template + stop params, identical to
# src/ml/models/lorekeeper-Modelfile — applied when creating the `lorekeeper`
# model from the downloaded GGUF so behavior matches a manual `ollama create` from
# the repo's own Modelfile exactly, instead of trusting whatever template
# Ollama infers from GGUF metadata.
MISTRAL_TEMPLATE = """{{- if .Messages }}
{{- range $index, $_ := .Messages }}
{{- if eq .Role "user" }}
{{- if and (eq (len (slice $.Messages $index)) 1) $.Tools }}[AVAILABLE_TOOLS] {{ $.Tools }}[/AVAILABLE_TOOLS]
{{- end }}[INST] {{ if and $.System (eq (len (slice $.Messages $index)) 1) }}{{ $.System }}

{{ end }}{{ .Content }}[/INST]
{{- else if eq .Role "assistant" }}
{{- if .Content }}{{ .Content }}
{{- else if .ToolCalls }}[TOOL_CALLS] [
{{- range .ToolCalls }}{"name": "{{ .Function.Name }}", "arguments": {{ .Function.Arguments }}}
{{- end }}]
{{- end }}</s>
{{- else if eq .Role "tool" }}[TOOL_RESULTS] {"content": {{ .Content }}} [/TOOL_RESULTS]
{{- end }}
{{- end }}
{{- else }}[INST] {{ if .System }}{{ .System }}

{{ end }}{{ .Prompt }}[/INST]
{{- end }}{{ .Response }}
{{- if .Response }}</s>
{{- end }}"""

MISTRAL_STOP = ["[INST]", "[/INST]", "</s>"]


# Tests swap in an httpx.MockTransport here; None = real network.
_transport: httpx.AsyncBaseTransport | None = None

# One fine-tune install at a time per worker: two concurrent runs would both
# stage 4.4GB on disk and race each other's /api/create.
_install_lock = asyncio.Lock()


def _client(**kwargs) -> httpx.AsyncClient:
    if _transport is not None:
        kwargs["transport"] = _transport
    return httpx.AsyncClient(**kwargs)


def _base_url() -> str:
    return get_settings().kobold_url.rstrip("/")


async def ollama_status(base_url: str | None = None) -> dict:
    """Reachability + installed model names, or why not.

    Returns {"reachable": bool, "models": [name, ...], "error": str | None}.
    "reachable" here specifically means the native Ollama API answered —
    a KoboldCpp deployment (which doesn't speak /api/tags) reports
    unreachable, which is correct for this module's purpose: the model
    installer only works against Ollama.
    """
    base = (base_url or _base_url()).rstrip("/")
    try:
        async with _client(timeout=5) as client:
            r = await client.get(f"{base}/api/tags")
            r.raise_for_status()
            models = [m.get("name", "") for m in r.json().get("models", [])]
            return {"reachable": True, "models": models, "error": None}
    except Exception as exc:
        return {"reachable": False, "models": [], "error": f"{type(exc).__name__}: {exc}"}


def model_installed(name: str, installed: list[str]) -> bool:
    """Ollama lists models with an explicit tag ("lorekeeper:latest") while
    config/env usually names them bare ("lorekeeper") — match either form."""
    return any(m == name or m.split(":", 1)[0] == name for m in installed)


async def pull_model(ref: str, timeout: float = 7200):
    """Async generator over Ollama's /api/pull progress events for `ref`.

    Yields dicts as Ollama reports them: {"status": ...} and, during the
    download phase, {"status": "pulling ...", "total": bytes, "completed":
    bytes}. Raises RuntimeError with a readable message on failure. The long
    total timeout is deliberate — a 4.4GB download on residential broadband
    is easily an hour; the read timeout stays short-ish because Ollama emits
    progress events continuously while anything is actually happening.
    """
    timeouts = httpx.Timeout(timeout, connect=10, read=120)
    async with _client(timeout=timeouts) as client:
        async with client.stream("POST", f"{_base_url()}/api/pull", json={"model": ref, "stream": True}) as r:
            if r.status_code != 200:
                body = (await r.aread()).decode(errors="replace")[:300]
                raise RuntimeError(f"Ollama pull failed (HTTP {r.status_code}): {body}")
            async for line in r.aiter_lines():
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get("error"):
                    raise RuntimeError(f"Ollama pull failed: {event['error']}")
                yield event


async def copy_model(source: str, destination: str) -> None:
    async with _client(timeout=60) as client:
        r = await client.post(f"{_base_url()}/api/copy", json={"source": source, "destination": destination})
        if r.status_code != 200:
            raise RuntimeError(f"Ollama copy {source} → {destination} failed (HTTP {r.status_code}): {r.text[:300]}")


def _gb(n: int) -> str:
    return f"{n / 1024**3:.1f} GB"


def _progress(status: str, completed: int, total: int | None) -> dict:
    """Same shape as Ollama's own pull events, so the admin UI's progress bar
    renders downloads, uploads and pulls identically."""
    out: dict = {"status": status}
    if total:
        out["total"] = total
        out["completed"] = completed
    return out


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


async def hf_file_info(client: httpx.AsyncClient, url: str) -> tuple[str | None, int | None]:
    """(sha256 digest "sha256:<hex>", size) of a Hugging Face LFS file, without
    downloading it. HF's /resolve/ endpoint answers HEAD with a redirect to
    its CDN whose headers carry X-Linked-ETag (the LFS object's sha256) and
    X-Linked-Size. Either may come back None if HF stops sending them — the
    installer then just can't skip the download, and falls back to hashing
    what it downloads."""
    try:
        r = await client.head(url, follow_redirects=False)
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Hugging Face is not reachable ({url}): {type(exc).__name__}: {exc}")
    if r.status_code in (401, 403, 404):
        raise RuntimeError(f"Hugging Face has no file at {url} (HTTP {r.status_code}).")
    if r.status_code >= 400:
        raise RuntimeError(f"Hugging Face returned HTTP {r.status_code} for {url}.")
    etag = (r.headers.get("x-linked-etag") or "").removeprefix("W/").strip('"').lower()
    digest = f"sha256:{etag}" if _SHA256_RE.match(etag) else None
    try:
        size = int(r.headers.get("x-linked-size", "")) or None
    except ValueError:
        size = None
    return digest, size


async def blob_exists(client: httpx.AsyncClient, base: str, digest: str) -> bool:
    r = await client.head(f"{base}/api/blobs/{digest}")
    if r.status_code == 200:
        return True
    if r.status_code == 404:
        return False
    raise RuntimeError(f"Ollama blob check failed (HTTP {r.status_code}) for {digest}.")


def check_disk_space(directory: str, needed: int) -> None:
    """Raise a readable RuntimeError unless `directory` can hold `needed`
    bytes plus headroom."""
    try:
        free = shutil.disk_usage(directory).free
    except OSError as exc:
        raise RuntimeError(
            f"Model download folder {directory!r} is not usable: {exc}. Set LLM_DOWNLOAD_DIR to a writable folder."
        )
    if free < needed + DISK_HEADROOM_BYTES:
        raise RuntimeError(
            f"Not enough free disk space to download the model: it needs about {_gb(needed + DISK_HEADROOM_BYTES)} "
            f"in {directory}, but only {_gb(free)} is free. Free up space, or set LLM_DOWNLOAD_DIR to a folder "
            f"on a bigger disk. (Ollama's own storage needs another {_gb(needed)} too.)"
        )


def _write_and_hash(fh, hasher, chunk: bytes) -> None:
    fh.write(chunk)
    hasher.update(chunk)


async def _download_events(client: httpx.AsyncClient, url: str, fh, expected_size: int | None, state: dict):
    """Stream `url` into the open file `fh`, hashing as it goes. Yields
    progress dicts; on success leaves state["digest"] and state["size"]."""
    hasher = hashlib.sha256()
    done = 0
    last = 0.0
    status = f"downloading {HF_GGUF_FILENAME} from Hugging Face"
    async with client.stream("GET", url, follow_redirects=True) as r:
        if r.status_code != 200:
            body = (await r.aread()).decode(errors="replace")[:300]
            raise RuntimeError(f"Download from Hugging Face failed (HTTP {r.status_code}): {body}")
        total = int(r.headers.get("content-length") or 0) or expected_size
        yield _progress(status, 0, total)
        async for chunk in r.aiter_bytes(_CHUNK_BYTES):
            await asyncio.to_thread(_write_and_hash, fh, hasher, chunk)
            done += len(chunk)
            now = time.monotonic()
            if now - last >= _PROGRESS_INTERVAL_S:
                last = now
                yield _progress(status, done, total)
    if total and done != total:
        raise RuntimeError(f"Download from Hugging Face was cut off ({_gb(done)} of {_gb(total)}). Try again.")
    await asyncio.to_thread(fh.flush)
    yield _progress(status, done, total or done)
    state["digest"] = f"sha256:{hasher.hexdigest()}"
    state["size"] = done


async def _upload_blob_events(client: httpx.AsyncClient, base: str, path: str, digest: str, size: int):
    """POST the file at `path` to Ollama as blob `digest`, yielding upload
    progress while the request body streams out."""
    sent = 0

    async def body():
        nonlocal sent
        with open(path, "rb") as f:
            while chunk := await asyncio.to_thread(f.read, _CHUNK_BYTES):
                sent += len(chunk)
                yield chunk

    status = "uploading model file to Ollama"
    task = asyncio.create_task(
        client.post(f"{base}/api/blobs/{digest}", content=body(), headers={"Content-Length": str(size)})
    )
    try:
        yield _progress(status, 0, size)
        while not task.done():
            await asyncio.wait({task}, timeout=_PROGRESS_INTERVAL_S)
            yield _progress(status, sent, size)
        r = task.result()
    finally:
        if not task.done():
            task.cancel()
            with contextlib.suppress(BaseException):
                await task
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Ollama rejected the model file upload (HTTP {r.status_code}): {r.text[:300]}")


async def create_model_events(
    name: str,
    files: dict[str, str],
    template: str | None = None,
    stop: list[str] | None = None,
    base: str | None = None,
):
    """Ollama /api/create from already-uploaded blobs (`files` maps file name
    to "sha256:<hex>"), as a stream of {"status": ...} dicts. Re-running it
    for the same name overwrites the model, so a repeat install is safe.
    Raises RuntimeError on failure."""
    payload: dict = {"model": name, "files": files, "stream": True}
    if template:
        payload["template"] = template
    if stop:
        payload["parameters"] = {"stop": stop}
    base = (base or _base_url()).rstrip("/")
    succeeded = False
    async with _client(timeout=httpx.Timeout(1800, connect=10, read=600)) as client:
        async with client.stream("POST", f"{base}/api/create", json=payload) as r:
            if r.status_code != 200:
                body = (await r.aread()).decode(errors="replace")[:300]
                raise RuntimeError(f"Ollama create '{name}' failed (HTTP {r.status_code}): {body}")
            async for line in r.aiter_lines():
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get("error"):
                    raise RuntimeError(f"Ollama create '{name}' failed: {event['error']}")
                if event.get("status") == "success":
                    succeeded = True
                yield {"status": event.get("status", "")}
    if not succeeded:
        raise RuntimeError(f"Ollama create '{name}' ended without reporting success.")


async def install_finetuned_events(
    target: str,
    *,
    gguf_url: str = HF_GGUF_URL,
    base_url: str | None = None,
    download_dir: str | None = None,
    reuse_existing_blob: bool = True,
):
    """Install the fine-tune as `target`: download the GGUF from Hugging Face
    to a temp file (hashing it on the way), upload it to Ollama as a blob
    unless Ollama already has it, then /api/create `target` from it with the
    Modelfile's template and stop params. Yields progress dicts; raises
    RuntimeError on failure. The temp file is always removed.

    With reuse_existing_blob, a re-run whose GGUF (by HF's published sha256)
    is already in Ollama skips the 4.4GB download entirely."""
    base = (base_url or _base_url()).rstrip("/")
    directory = download_dir or get_settings().llm_download_dir or tempfile.gettempdir()
    timeouts = httpx.Timeout(7200, connect=10, read=300, write=300)
    async with _client(timeout=timeouts) as client:
        yield {"status": f"contacting Ollama at {base}"}
        try:
            (await client.get(f"{base}/api/version")).raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Ollama is not reachable at {base}: {type(exc).__name__}: {exc}")

        yield {"status": "checking the model file on Hugging Face"}
        expected_digest, expected_size = await hf_file_info(client, gguf_url)

        digest = expected_digest
        if reuse_existing_blob and expected_digest and await blob_exists(client, base, expected_digest):
            yield {"status": "model file already in Ollama, skipping download"}
        else:
            check_disk_space(directory, expected_size or HF_GGUF_APPROX_BYTES)
            fd, path = tempfile.mkstemp(prefix="lorekeeper-", suffix=".gguf.part", dir=directory)
            try:
                state: dict = {}
                with os.fdopen(fd, "wb") as fh:
                    async with aclosing(_download_events(client, gguf_url, fh, expected_size, state)) as events:
                        async for ev in events:
                            yield ev
                digest, size = state["digest"], state["size"]
                if expected_digest and digest != expected_digest:
                    raise RuntimeError(
                        f"Downloaded file is corrupt: its checksum ({digest}) doesn't match the one Hugging Face "
                        f"publishes ({expected_digest}). Try again."
                    )
                if await blob_exists(client, base, digest):
                    yield {"status": "model file already in Ollama, skipping upload"}
                else:
                    async with aclosing(_upload_blob_events(client, base, path, digest, size)) as events:
                        async for ev in events:
                            yield ev
            finally:
                with contextlib.suppress(OSError):
                    os.unlink(path)

    yield {"status": f"creating model '{target}'"}
    async with aclosing(
        create_model_events(target, {HF_GGUF_FILENAME: digest}, MISTRAL_TEMPLATE, MISTRAL_STOP, base=base)
    ) as events:
        async for ev in events:
            yield ev


async def install_model_events(variant: str, target: str | None = None, **finetuned_kwargs):
    """The whole install flow for one variant as a stream of JSON-able dicts —
    what the admin System tab renders as a progress bar.

    variant "finetuned": see install_finetuned_events — installed as
    `target` (default KOBOLD_MODEL). variant "base": pull Mistral 7B Instruct
    from the Ollama library and copy it to `target` (default
    KOBOLD_BASE_MODEL; library models already carry the right template).

    Yields progress dicts and finally {"done": True, "model": target} on
    success; on failure yields {"error": msg} and stops. Never raises — this
    feeds an SSE response where an exception would just sever the stream
    wordlessly.
    """
    s = get_settings()
    if variant == "base":
        target = target or s.kobold_base_model
    else:
        target = target or s.kobold_model

    try:
        if variant == "base":
            yield {"status": f"contacting Ollama at {_base_url()}"}
            async for event in pull_model(BASE_LIBRARY_REF):
                out = {"status": event.get("status", "")}
                if "total" in event:
                    out["total"] = event["total"]
                    out["completed"] = event.get("completed", 0)
                yield out
            yield {"status": f"registering model as '{target}'"}
            await copy_model(BASE_LIBRARY_REF, target)
        else:
            if _install_lock.locked():
                raise RuntimeError("A model install is already running. Wait for it to finish.")
            # aclosing everywhere a generator relays a nested one: when the
            # admin closes the tab, Starlette closes only the outermost
            # generator; without it the inner ones (and their temp-file
            # cleanup) would wait for garbage collection.
            async with _install_lock, aclosing(install_finetuned_events(target, **finetuned_kwargs)) as events:
                async for event in events:
                    yield event
        yield {"done": True, "model": target}
    except Exception as exc:
        logger.error("Model install (%s) failed", variant, exc_info=exc)
        msg = str(exc) if isinstance(exc, RuntimeError) else f"{type(exc).__name__}: {exc}"
        yield {"error": msg}
