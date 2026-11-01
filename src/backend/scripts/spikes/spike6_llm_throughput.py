#!/usr/bin/env python
"""SPIKE-6 (x86): Ollama prompt and generation throughput per prompt shape,
plus the structured-extraction check the M-series spike skipped.

For each prompt shape, --n times, one streamed /api/chat call records Ollama's
own counters (prompt_eval_count/duration, eval_count/duration, load_duration)
and the client-side time to first token and total time:

  extraction_50 / extraction_300  a ≈500-word entry (demo seed narratives)
                                  with an Entity list of 50 or 300 (the demo
                                  seed's NPCs, Quests and Locations, padded
                                  with generated Entities), JSON proposals out
  continuity_verify               two Canon statements and a yes/no verdict
  rolling_recap                   recap so far plus 60 s of transcript
  npc_first_turn                  an NPC card and the Player's opening line
  recap_draft_300                 session summaries in, a 300-word recap out

Every call's user turn starts with a unique nonce, and an unrelated one-token
call runs before it, to keep Ollama's prompt cache from serving runs 2..n. A
prompt Ollama truncates (it keeps the tail) still hits llama-server's RAM
prompt cache; summarise() flags those runs as cache_hit. num_ctx is never sent (AD-8): the server's
OLLAMA_CONTEXT_LENGTH applies.

--structured N then runs complete_structured (app/services/llm_provider, the
FR-3 path: Ollama `format` set to the flat JSON schema, repair turns on an
invalid reply) N times on an E1-shaped extraction schema and records the
first-try, after-repair and failed counts and latency.

    python scripts/spikes/spike6_llm_throughput.py --url http://127.0.0.1:11500 \
        --model lorekeeper --n 3 --structured 10 --label cpu-4 --out results/spike6-cpu.json

Runs in the backend image (it imports app.*): see run_x86.sh. Measurement
harness only; E0-LLM owns acting on it (E0-LLM.6).
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Literal

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parents[1]
for p in (str(_HERE), str(_BACKEND)):
    if p not in sys.path:
        sys.path.insert(0, p)

import _bench  # noqa: E402

_SEED_DIRS = [*_BACKEND.parents, _BACKEND]  # the repo root's seeds/, or /seeds when mounted at the root
SEED = next((d / "seeds" / "demo_campaign.json" for d in _SEED_DIRS
             if (d / "seeds" / "demo_campaign.json").exists()), None)

TYPES = ["npc", "location", "faction", "item", "creature"]
SYLLABLES = ["kar", "dun", "bor", "in", "vey", "ra", "ald", "ric", "gru", "kk", "mor", "eth", "sil", "van",
             "tor", "ash", "el", "dra", "quin", "oth"]


def _seed() -> dict:
    if SEED is None:
        raise SystemExit("seeds/demo_campaign.json not found")
    return json.loads(SEED.read_text())


def entry_500(seed: dict) -> str:
    """The first demo narratives, joined until they reach ≈500 words."""
    out, words = [], 0
    for e in seed["entries"]:
        out.append(e["narrative"])
        words += len(e["narrative"].split())
        if words >= 480:
            break
    return "\n\n".join(out)


def entity_list(seed: dict, n: int) -> list[str]:
    known = [f"{x['name']} (npc): {x.get('description', '')[:80]}" for x in seed.get("npcs", [])]
    known += [f"{x.get('name') or x.get('title')} (location): {x.get('description', '')[:80]}"
              for x in seed.get("locations", [])]
    known += [f"{x.get('title') or x.get('name')} (quest): {x.get('description', '')[:80]}" for x in seed.get("quests", [])]
    i = 0
    while len(known) < n:
        a, b, c = SYLLABLES[i % 20], SYLLABLES[(i * 7 + 3) % 20], SYLLABLES[(i * 13 + 5) % 20]
        known.append(f"{(a + b).capitalize()} {(c + a).capitalize()} ({TYPES[i % 5]})")
        i += 1
    return known[:n]


def shapes(seed: dict) -> dict[str, tuple[list[dict], int]]:
    entry = entry_500(seed)
    recap = " ".join(e["narrative"] for e in seed["entries"][:4])
    summaries = "\n".join(f"Session {e['session_number']}: {e['narrative']}" for e in seed["entries"][:8])
    npc = seed["npcs"][0]

    def extraction(n: int):
        ents = "\n".join(f"- {x}" for x in entity_list(seed, n))
        return [
            {"role": "system", "content": "You read a tabletop RPG journal entry and propose changes to the "
             "campaign's world model. Reuse a known Entity's exact name when the entry mentions it."},
            {"role": "user", "content": f"Known Entities ({n}):\n{ents}\n\nJournal entry:\n{entry}\n\n"
             "Return JSON: {\"proposals\": [{\"kind\": \"new_entity|status_change|relationship|mention\", "
             "\"entity\": str, \"detail\": str, \"quote\": str}]}"},
        ], 400

    return {
        "extraction_50": extraction(50),
        "extraction_300": extraction(300),
        "continuity_verify": ([
            {"role": "system", "content": "You check a tabletop campaign's Canon for contradictions."},
            {"role": "user", "content": "Canon: Grukk cannot read.\nNew entry: Grukk read the ancient inscription "
             "aloud to the group.\nDo these contradict? Answer JSON {\"contradiction\": \"yes|no\", "
             "\"reason\": str} in one sentence."},
        ], 80),
        "rolling_recap": ([
            {"role": "system", "content": "You keep a short rolling recap of a live tabletop RPG session."},
            {"role": "user", "content": f"Recap so far:\n{recap[:1500]}\n\nLast minute of table talk:\n"
             "Okay, Grukk, you hear the drums again from below. Borin says the old roads run under the mountain. "
             "Veyra wants to scout ahead; roll stealth. Seventeen. You slip past the first guard post and see "
             "green light under a door. Aldric says we should warn the council first, but Grukk is already "
             "kicking the door open. Roll initiative.\n\nUpdate the recap in under 120 words."},
        ], 160),
        "npc_first_turn": ([
            {"role": "system", "content": f"You are {npc['name']}, an NPC in a tabletop campaign. "
             f"{npc.get('description', '')} Stay in character. Only state what this NPC knows."},
            {"role": "user", "content": "The party walks up to you. Veyra asks: what do you know about the "
             "cloaked stranger with the black dagger?"},
        ], 150),
        "recap_draft_300": ([
            {"role": "system", "content": "You write 'Previously on…' recaps for a tabletop campaign."},
            {"role": "user", "content": f"Session summaries:\n{summaries}\n\nWrite a 300-word narrated recap."},
        ], 450),
    }


NUM_THREAD: int | None = None  # --num-thread; None lets Ollama pick (one per host core)


async def stream_once(client, url: str, model: str, messages: list[dict], max_tokens: int) -> dict:
    # The nonce leads the first user turn: the lorekeeper template keeps only
    # the last system message, so a system-message nonce would be dropped and
    # the prompt cache would serve runs 2..n.
    nonce = f"[run {uuid.uuid4().hex[:12]}]\n"
    first_user = next(i for i, m in enumerate(messages) if m["role"] == "user")
    messages = [dict(m, content=nonce + m["content"]) if i == first_user else m for i, m in enumerate(messages)]
    options = {"temperature": 0, "num_predict": max_tokens}
    if NUM_THREAD:
        options["num_thread"] = NUM_THREAD
    body = {"model": model, "messages": messages, "stream": True, "options": options}
    t0 = time.perf_counter(); ttft = None; final = {}
    async with client.stream("POST", f"{url}/api/chat", json=body) as r:
        r.raise_for_status()
        async for line in r.aiter_lines():
            if not line:
                continue
            msg = json.loads(line)
            if msg.get("error"):
                raise RuntimeError(f"Ollama: {msg['error']}")
            if ttft is None and (msg.get("message") or {}).get("content"):
                ttft = time.perf_counter() - t0
            if msg.get("done"):
                final = msg
    total = time.perf_counter() - t0
    if not final:
        raise RuntimeError("Ollama stream ended without a done message")
    pe_n, pe_s = final.get("prompt_eval_count", 0), final.get("prompt_eval_duration", 0) / 1e9
    ev_n, ev_s = final.get("eval_count", 0), final.get("eval_duration", 0) / 1e9
    return {"ttft_s": round(ttft or total, 2), "total_s": round(total, 2),
            "prompt_tokens": pe_n, "prompt_tok_s": round(pe_n / pe_s, 1) if pe_s else None,
            "gen_tokens": ev_n, "gen_tok_s": round(ev_n / ev_s, 2) if ev_s else None,
            "load_s": round(final.get("load_duration", 0) / 1e9, 2)}


CACHE_HIT_TOK_S = 10_000


def summarise(runs: list[dict]) -> dict:
    """Stats per metric. A run whose prompt rate is over CACHE_HIT_TOK_S and
    10x the slowest run's was served from llama-server's RAM prompt cache (it
    survives the flush call when Ollama truncates the prompt to the same
    tail); it is counted in cache_hits and left out of the prompt-side stats
    (TTFT, prompt tok/s, total). No cold prefill measured on the desktop,
    GPU included, reached 10k tok/s."""
    pps = [r["prompt_tok_s"] for r in runs if r.get("prompt_tok_s")]
    floor = min(pps) if pps else 0
    for r in runs:
        pp = r.get("prompt_tok_s") or 0
        r["cache_hit"] = bool(floor and pp > CACHE_HIT_TOK_S and pp > 10 * floor)
    cold = [r for r in runs if not r["cache_hit"]]
    out = {"runs": runs, "cache_hits": len(runs) - len(cold)}
    for k in ("ttft_s", "total_s", "prompt_tok_s", "gen_tok_s"):
        src = runs if k == "gen_tok_s" else cold
        vals = [r[k] for r in src if r.get(k) is not None]
        out[k] = _bench.stats(vals, 2)
    out["prompt_tokens"] = runs[-1]["prompt_tokens"] if runs else 0
    out["gen_tokens"] = _bench.stats([r["gen_tokens"] for r in runs], 0)
    return out


async def structured_check(url: str, model: str, calls: int) -> dict:
    from pydantic import field_validator

    from app.core.errors import StructuredOutputError
    from app.schemas.llm import FlatModel
    from app.services import llm_provider
    from app.services.llm_provider import LLMConfig, complete_structured

    class Proposal(FlatModel):
        kind: Literal["new_entity", "status_change", "relationship", "mention"]
        entity: str
        detail: str
        quote: str

    class Extraction(FlatModel):
        proposals: list[Proposal]

        @field_validator("proposals")
        @classmethod
        def at_least_one(cls, v):
            if not v:
                raise ValueError("at least one proposal is required")
            return v

    seed = _seed()
    llm_provider.structured_stats.clear()
    cfg = LLMConfig(provider="kobold", api_url=url, model=model)
    if llm_provider.uses_platform_llm(cfg):
        raise SystemExit("--url is KOBOLD_URL: the gate and LOCAL_LLM_MODEL would apply; use another URL")
    assert await llm_provider.detect_backend(url) == llm_provider.BACKEND_OLLAMA, f"{url} is not an Ollama"
    entries = seed["entries"]
    lat, failed = [], 0
    for i in range(calls):
        entry = entries[i % len(entries)]["narrative"]
        msgs = [{"role": "system", "content": "You read a tabletop RPG journal entry and propose changes to the "
                 "campaign's world model."},
                {"role": "user", "content": f"Journal entry:\n{entry}\n\nList the proposals."}]
        t = time.perf_counter()
        try:
            await complete_structured(msgs, Extraction, cfg, task="spike6_extraction", timeout=900)
        except StructuredOutputError:
            failed += 1
        lat.append(time.perf_counter() - t)
    counts = llm_provider.structured_stats.get("spike6_extraction", {})
    return {"calls": calls, "first_try_valid": counts.get("first_try_valid", 0),
            "valid_after_repair": counts.get("valid_after_repair", 0), "failed": failed,
            "latency_s": _bench.stats(lat, 1)}


async def version(client, url: str, model: str) -> dict:
    v = (await client.get(f"{url}/api/version")).json().get("version")
    tags = (await client.get(f"{url}/api/tags")).json().get("models", [])
    digest = next((t.get("digest") for t in tags if t.get("name", "").split(":")[0] == model.split(":")[0]), None)
    return {"ollama": v, "model": model, "model_digest": (digest or "")[:12]}


async def run(args) -> dict:
    import httpx

    seed = _seed()
    url = args.url.rstrip("/")
    all_shapes = shapes(seed)
    wanted = args.shapes.split(",") if args.shapes else list(all_shapes)
    async with httpx.AsyncClient(timeout=httpx.Timeout(1800, connect=10)) as client:
        info = await version(client, url, args.model)
        # load the model (not measured)
        await stream_once(client, url, args.model, [{"role": "user", "content": "Say ok."}], 2)
        results = {}
        unknown = sorted(set(wanted) - set(all_shapes))
        if unknown:
            raise SystemExit(f"unknown shapes {unknown}; known: {sorted(all_shapes)}")
        for name in wanted:
            msgs, max_tokens = all_shapes[name]
            if args.max_tokens:
                max_tokens = min(max_tokens, args.max_tokens)
            runs = []
            for _ in range(args.n):
                # Ollama's llama-server reuses matching KV chunks even after a
                # differing prefix, so a nonce alone doesn't stop runs 2..n
                # hitting the cache. A short unrelated call in between leaves
                # the (single) slot holding something else.
                await stream_once(client, url, args.model, [{"role": "user", "content": "Say ok."}], 1)
                runs.append(await stream_once(client, url, args.model, msgs, max_tokens))
            results[name] = summarise(runs)
            print(f"{name}: ttft {results[name]['ttft_s'].get('median')}s, total {results[name]['total_s'].get('median')}s, "
                  f"pp {results[name]['prompt_tok_s'].get('median')} tok/s, tg {results[name]['gen_tok_s'].get('median')} tok/s",
                  file=sys.stderr)
    metrics = {"shapes": results}
    if args.structured:
        metrics["structured"] = await structured_check(url, args.model, args.structured)
    return {"spike": "SPIKE-6", "config": args.label, "column": args.column,
            "env": {**_bench.environment(), **info, "url": url, "num_thread": NUM_THREAD}, "metrics": metrics}


def main(argv=None) -> int:
    p = _bench.base_parser(__doc__)
    p.set_defaults(n=3)
    p.add_argument("--url", required=True, help="Ollama base URL")
    p.add_argument("--model", default="lorekeeper")
    p.add_argument("--label", required=True, help="operating point, e.g. cpu-4, cpu-capped-3, gpu")
    p.add_argument("--column", choices=["cpu", "gpu"], default="cpu")
    p.add_argument("--shapes", default=None, help="comma-separated subset of the prompt shapes")
    p.add_argument("--max-tokens", type=int, default=None, help="cap every shape's output tokens")
    p.add_argument("--structured", type=int, default=0, help="complete_structured calls to run (0 = skip)")
    p.add_argument("--num-thread", type=int, default=None,
                   help="send num_thread with every call (default: none). Prefer a Modelfile PARAMETER "
                        "(run_x86.sh ollama_threads): a per-request value reloads the model whenever it "
                        "differs, and complete_structured never sends one")
    args = p.parse_args(argv)
    global NUM_THREAD
    NUM_THREAD = args.num_thread
    _bench.emit(asyncio.run(run(args)), args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
