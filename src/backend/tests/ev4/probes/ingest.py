"""EV-4 probes for api/routes/ingest.py (E0-QA.13): image OCR (the `ml`
sidecar's fake), voice transcription (the `stt` sidecar's fake) and the
Discord paste cleaner.

None of them takes a Campaign or reads stored data: each turns the caller's
upload into text. So none is GM-only (there is no Campaign to answer
"missing" for); what must hold is that the answer depends only on the
caller's own input: no canary, and the same upload gives a byte-identical
answer before and after the GM of Campaign A sends canary content through
the same route. Without a login, every route refuses before reading the
upload.
"""
from __future__ import annotations

from tests.ev4.families import assert_no_canary
from tests.ev4.fixtures import mint_canary
from tests.ev4.probes._support import assert_same_answer, authenticated
from tests.ev4.probes.admin import check_denial
from tests.ev4.registry import ev4_probe


async def _stateless(ev4, actor, url: str, request, expect) -> None:
    """`request(actor, text)` posts `text` to `url`; `expect(text, body)` checks a 200 body."""
    text = "The party met Barnaby at the Drowsy Dragon."
    first = await request(actor, text)
    if not authenticated(actor):
        check_denial(actor, first, f"POST {url}")
    else:
        assert_no_canary(actor, first)
        assert first.status_code == 200, first.text
        expect(text, first.json())
    gm = await ev4.actor("gm_owner")
    secret = f"{mint_canary('XINGEST', ev4.a.campaign_id).token} is the lich."
    r_gm = await request(gm, secret)
    assert r_gm.status_code == 200, r_gm.text
    assert_same_answer(actor, first, await request(actor, text), f"{url} after another user's upload")


@ev4_probe("POST", "/api/ingest/image")
async def probe_ingest_image(ev4, actor):
    # The fake OCR reads the upload's bytes as UTF-8 text.
    async def post(who, text):
        return await who.post("/api/ingest/image", files={"file": ("notes.png", text.encode(), "image/png")})

    def expect(text, body):
        assert body == {"extracted_text": text}, body

    await _stateless(ev4, actor, "/api/ingest/image", post, expect)


@ev4_probe("POST", "/api/ingest/voice")
async def probe_ingest_voice(ev4, actor):
    # The fake stt sidecar transcribes to a hash of the audio bytes.
    async def post(who, text):
        return await who.post("/api/ingest/voice", files={"file": ("seg.webm", b"WEBM" + text.encode(), "audio/webm")})

    def expect(text, body):
        assert body["transcribed_text"].startswith("Fake transcript "), body

    await _stateless(ev4, actor, "/api/ingest/voice", post, expect)


@ev4_probe("POST", "/api/ingest/discord")
async def probe_ingest_discord(ev4, actor):
    async def post(who, text):
        return await who.post("/api/ingest/discord", json={"text": f"Grukk — Today at 9:14 PM\n{text}\n:fire: 2"})

    def expect(text, body):
        assert body == {"cleaned_text": text}, body

    await _stateless(ev4, actor, "/api/ingest/discord", post, expect)
