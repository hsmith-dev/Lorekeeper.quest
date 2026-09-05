"""Talk to the stack's own Ollama instance (the thing KOBOLD_URL points at in
the default self-hosted deployment) over its NATIVE API — /api/tags, /api/pull,
/api/create, /api/copy — rather than the OpenAI-compat surface llm_provider.py
uses for completions.

This exists so a self-hoster never has to shell into the ollama container:
the admin portal's System tab can see which models are installed and install
the recommended ones straight from their public registries (the fine-tune
from Hugging Face, the base model from the Ollama library) with live
progress. Every function here degrades to a clear error string instead of
raising — the callers are diagnostics/UI surfaces where "Ollama is down:
<why>" is the useful output, not a 500.
"""

import json
import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# The published fine-tune. Ollama can pull GGUF repos straight off Hugging
# Face by this ref — no local file, no Modelfile on disk needed.
HF_FINETUNED_REF = "hf.co/harrisonsmith/Lorekeeper-Mistral-7B-GGUF"
# The un-fine-tuned counterpart, from the Ollama library — same base
# architecture (Mistral 7B Instruct) the LoRA was trained on.
BASE_LIBRARY_REF = "mistral:7b-instruct-q4_0"

# Mistral-instruct chat template + stop params, identical to
# src/ml/models/lorekeeper-Modelfile — applied when creating the `lorekeeper`
# model from the HF pull so behavior matches a manual `ollama create` from
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
        async with httpx.AsyncClient(timeout=5) as client:
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
    async with httpx.AsyncClient(timeout=timeouts) as client:
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


async def create_model(name: str, from_ref: str, template: str | None = None, stop: list[str] | None = None) -> None:
    """Create/overwrite model `name` derived from an already-pulled `from_ref`
    (Ollama's newer file-less /api/create). Raises RuntimeError on failure."""
    payload: dict = {"model": name, "from": from_ref, "stream": False}
    if template:
        payload["template"] = template
    if stop:
        payload["parameters"] = {"stop": stop}
    async with httpx.AsyncClient(timeout=300) as client:
        r = await client.post(f"{_base_url()}/api/create", json=payload)
        if r.status_code != 200:
            raise RuntimeError(f"Ollama create '{name}' failed (HTTP {r.status_code}): {r.text[:300]}")
        # Non-stream create still replies with a status JSON; surface errors.
        try:
            if r.json().get("error"):
                raise RuntimeError(f"Ollama create '{name}' failed: {r.json()['error']}")
        except ValueError:
            pass


async def copy_model(source: str, destination: str) -> None:
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(f"{_base_url()}/api/copy", json={"source": source, "destination": destination})
        if r.status_code != 200:
            raise RuntimeError(f"Ollama copy {source} → {destination} failed (HTTP {r.status_code}): {r.text[:300]}")


async def install_model_events(variant: str):
    """The whole install flow for one variant as a stream of JSON-able dicts —
    what the admin System tab renders as a progress bar.

    variant "finetuned": pull the published fine-tune from Hugging Face, then
    create `KOBOLD_MODEL` from it with the exact template/stop params from the
    repo's Modelfile. variant "base": pull Mistral 7B Instruct from the Ollama
    library and copy it to `KOBOLD_BASE_MODEL` (library models already carry
    the right template).

    Yields progress dicts and finally {"done": True} on success; on failure
    yields {"error": msg} and stops. Never raises — this feeds an SSE
    response where an exception would just sever the stream wordlessly.
    """
    s = get_settings()
    if variant == "base":
        ref, target = BASE_LIBRARY_REF, s.kobold_base_model
    else:
        ref, target = HF_FINETUNED_REF, s.kobold_model

    try:
        yield {"status": f"contacting Ollama at {_base_url()}"}
        async for event in pull_model(ref):
            out = {"status": event.get("status", "")}
            if "total" in event:
                out["total"] = event["total"]
                out["completed"] = event.get("completed", 0)
            yield out
        yield {"status": f"registering model as '{target}'"}
        if variant == "base":
            await copy_model(ref, target)
        else:
            await create_model(target, ref, template=MISTRAL_TEMPLATE, stop=MISTRAL_STOP)
        yield {"done": True, "model": target}
    except Exception as exc:
        logger.error("Model install (%s) failed", variant, exc_info=exc)
        yield {"error": str(exc)}
