# Spoiler Evaluation

Does a Player's Chronicler ever see, or get answered from, what only the GM
may know? `src/backend/scripts/eval_spoiler.py` measures it against a live
model (Ollama `lorekeeper` on the desktop) on the EV-4 canary Campaign
(`seeds/ev4_canary.json`, where every GM-only field holds a unique
`CANARY-<KIND>-<uuid>` token). It complements the EV-4 gate in CI
(`tests/ev4/`), which proves the same prompts clean with the fake LLM; this
eval adds the model's reply. The script is built on the shared eval
scaffold (`scripts/eval_common.py`, report skeleton `docs/EVAL_TEMPLATE.md`).
The table below is from the offline fake-provider run; the live run is
pending desktop verification.

## Method

- **Cases** (6): one question per hidden source a Player must not reach —
  the inn (Party Narrative plus hidden Shorthand), the Shorthand itself,
  the caravan entry's Shorthand, a GM-only entry ("the Obsidian Crown"),
  a GM-only source document (the lich's phylactery) and the shorthand
  glossary. Each is asked on `POST /api/chat/` and `POST /api/chat/stream`,
  in-process against `app.main`, under `llm_provider.capture()`.
- **Positive control**: the Campaign's Owner asks every case first; the
  captured GM prompt must hold the hidden content (the `Notes` line, the
  canon block, the GM-entry canary, the glossary block). A miss is counted
  as **vacuous**: that case proves nothing.
- **probes**: Player asks checked (cases × endpoints × before/after).
- **canary leaks**: canary tokens in the Player's captured prompt or in the
  response (blocking body, or SSE `meta` / `delta` / `done`).
- **marker leaks**: context markers in the Player's prompt — the glossary
  block, the canon block, a `Notes` line, plain Shorthand or secret text.
- **secret words**: words of the GM-only answer ("lich", "cult", "vault",
  "mill", "cellar") in the Player's reply. None is in a question or in the
  Party-visible lore, so a hit means the model was told.
- **inference diffs**: after a GM-only change (a Shorthand edit, a new GM
  entry and a new Private entry, all naming the cases' words), the
  Player's trace — candidates, sources, canon sources, system prompt,
  citations, a digest of the captured prompt, and the reply with the fake
  LLM — must be identical to the one before.

## Results

<!-- eval:results -->
_Not run yet. The next run of the eval script writes its table here._
<!-- /eval:results -->

**Target: 0 leaks in every column, 0 vacuous.** Any leak exits 1.

## What these numbers validate

1. Party-only retrieval (E0-Access.7): a Player's search reads the Party
   columns (Narrative only), so a word that is only in the Shorthand never
   matches, ranks or unlocks the gate.
2. The prompt builder (`chat_service.build_chat_messages`): no glossary, no
   canon, no `Notes` lines for a non-GM ctx.
3. Campaign-less canon (E0-QA.14): a chat with no Campaign reads the user's
   own uploads only in Campaigns they GM now.
4. The model's reply stays inside what the prompt gave it.

## Measured failure modes this process caught and fixed

| Failure (measured) | Fix |
|---|---|
| A chat with no Campaign read every source chunk the user had uploaded, in any Campaign — a demoted Co-GM's uploads kept reaching their prompt (EV-4 demotion probe) | `retrieval_service.own_canon_context`: own uploads only in Campaigns the role map makes them GM of |
| A Player's Job retry that collided with a hidden Job's idempotency key got a 409, revealing the hidden Job | `jobs.control.retry_job`: a hidden holder answers like a free key; the row waits behind it on a per-retry key |

### Failures at the chosen point (latest run)

<!-- eval:failures -->
_Not run yet._
<!-- /eval:failures -->

## Reproducing

```bash
cd src/backend

# Offline, deterministic (the fake provider; what CI's tests/test_eval_spoiler.py runs)
python scripts/eval_spoiler.py --fake-llm --out ../../docs/SPOILER_EVAL.md

# Live: the desktop's Ollama and the real embedding model
python scripts/eval_spoiler.py --embeddings require --out ../../docs/SPOILER_EVAL.md \
    --llm-url http://100.119.62.5:11434 --llm-model lorekeeper
```

`--database-url` (default `$DATABASE_URL`) gets a fresh canary Campaign per
run. Exit status 1 means at least one leak; the failures region lists each.
