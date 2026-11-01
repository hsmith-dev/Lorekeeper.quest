"""Campaign PDF export (GET /api/campaigns/{id}/export?format=pdf), E0-QA.9.

WeasyPrint renders app/templates/export/campaign.html.j2. These tests read the
PDF back with pypdf. extract_text() can break long lines, so they look for
short strings, and the long narrative is compared with whitespace collapsed.
"""

import io
import uuid
from datetime import date

import pytest
from pypdf import PdfReader

from app.db.models.journal import JournalEntry


async def _register(client, promo_code) -> tuple[dict, uuid.UUID]:
    r = await client.post("/api/auth/register", json={
        "email": f"pdf_{uuid.uuid4().hex[:8]}@example.com", "password": "password123",
        "display_name": "GM", "promo_code": promo_code,
    })
    assert r.status_code in (200, 201), r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, uuid.UUID(r.json()["user_id"])


async def _campaign(client, headers, **body) -> uuid.UUID:
    r = await client.post("/api/campaigns/", json={"genre": "fantasy", **body}, headers=headers)
    assert r.status_code == 201, r.text
    return uuid.UUID(r.json()["id"])


async def _entry(db, user_id, campaign_id, shorthand, narrative, session_date=None) -> None:
    # Inserted directly: /journals/generate runs spaCy, embeddings and the LLM.
    db.add(JournalEntry(
        user_id=user_id, campaign_id=campaign_id, shorthand=shorthand, narrative=narrative,
        session_date=session_date, entry_hash=uuid.uuid4().hex,
    ))
    await db.commit()


async def _export(client, headers, campaign_id) -> PdfReader:
    r = await client.get(f"/api/campaigns/{campaign_id}/export?format=pdf", headers=headers)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF-")
    return PdfReader(io.BytesIO(r.content))


def _flat(text: str) -> str:
    return " ".join(text.split())


def _fonts(reader: PdfReader) -> list[tuple[str, bool]]:
    """(BaseFont, embedded?) for every font the pages use."""
    out = []
    for page in reader.pages:
        fonts = page.get("/Resources", {}).get("/Font", {})
        for ref in fonts.values():
            font = ref.get_object()
            descendants = [d.get_object() for d in font.get("/DescendantFonts", [])] or [font]
            for f in descendants:
                desc = f.get("/FontDescriptor")
                desc = desc.get_object() if desc is not None else {}
                embedded = any(k in desc for k in ("/FontFile", "/FontFile2", "/FontFile3"))
                out.append((str(f.get("/BaseFont", font.get("/BaseFont"))), embedded))
    return out


NARRATIVE_ONE = (
    "The party crossed the Grey Marches at dawn, where the old road sinks into the fen and "
    "the waymarkers lean like tired sentries. Brother Aldous counted the cairns aloud.\n"
    "Second line of the narrative."
)


@pytest.mark.asyncio
async def test_pdf_happy_path(client, db, promo_code):
    headers, user_id = await _register(client, promo_code)
    cid = await _campaign(client, headers, name="The Grey Marches",
                          description="A border campaign.\nSecond description line.")
    # Inserted out of order: the route orders by session_date.
    await _entry(db, user_id, cid, "fight at bridge", "The bridge held.", date(2026, 3, 9))
    await _entry(db, user_id, cid, "cross the fen", NARRATIVE_ONE, date(2026, 3, 2))

    reader = await _export(client, headers, cid)
    assert len(reader.pages) == 3

    first = reader.pages[0].extract_text()
    assert "The Grey Marches" in first
    assert "Fantasy campaign" in first
    assert "A border campaign." in first
    # Stored newlines are kept: the second line is its own line.
    assert "Second description line." in [line.strip() for line in first.splitlines()]

    second = reader.pages[1].extract_text()
    assert "2026-03-02" in second
    assert "Notes: cross the fen" in second
    assert _flat(NARRATIVE_ONE) in _flat(second)
    assert "Second line of the narrative." in [line.strip() for line in second.splitlines()]

    third = reader.pages[2].extract_text()
    assert "2026-03-09" in third
    assert "Notes: fight at bridge" in third
    assert "The bridge held." in third

    fonts = _fonts(reader)
    assert fonts, "no fonts found in the PDF"
    assert all(embedded for _, embedded in fonts), fonts
    assert all("DejaVu" in name for name, _ in fonts), fonts
    # The grey meta lines are italic: a real oblique face, not the upright one.
    assert any("Oblique" in name for name, _ in fonts), fonts


@pytest.mark.asyncio
async def test_pdf_entry_without_session_date_uses_created_at(client, db, promo_code):
    headers, user_id = await _register(client, promo_code)
    cid = await _campaign(client, headers, name="Undated")
    await _entry(db, user_id, cid, "notes", "Narrative.")

    reader = await _export(client, headers, cid)
    assert len(reader.pages) == 2
    entry = (await db.execute(
        JournalEntry.__table__.select().where(JournalEntry.campaign_id == cid))).one()
    assert entry.created_at.date().isoformat() in reader.pages[1].extract_text()


@pytest.mark.asyncio
async def test_pdf_unicode_is_printed_exactly(client, db, promo_code):
    headers, user_id = await _register(client, promo_code)
    name = "Ælfrida’s Ōkami — Þórr"
    cid = await _campaign(client, headers, name=name)
    await _entry(db, user_id, cid, "names", "Ведьма met “quotes” and Ελένη.", date(2026, 1, 1))

    r = await client.get(f"/api/campaigns/{cid}/export?format=pdf", headers=headers)
    # The download name keeps ASCII only (headers are Latin-1).
    assert r.headers["content-disposition"] == 'attachment; filename="lfridas_kami__rr.pdf"'
    reader = await _export(client, headers, cid)
    text = "\n".join(page.extract_text() for page in reader.pages)
    for s in ("Ælfrida’s", "Ōkami", "—", "Þórr", "Ведьма", "“quotes”", "Ελένη"):
        assert s in text, s
    assert "?" not in text


@pytest.mark.asyncio
async def test_pdf_no_entries_no_description(client, db, promo_code):
    headers, _ = await _register(client, promo_code)
    cid = await _campaign(client, headers, name="Empty Campaign", genre="scifi")

    reader = await _export(client, headers, cid)
    assert len(reader.pages) == 1
    text = reader.pages[0].extract_text()
    assert "Empty Campaign" in text
    assert "Scifi campaign" in text


@pytest.mark.asyncio
async def test_pdf_html_looking_text_is_escaped(client, db, promo_code):
    headers, user_id = await _register(client, promo_code)
    cid = await _campaign(client, headers, name="<i>Escaped</i>")
    await _entry(db, user_id, cid, "<b>x</b> & y", "<script>alert(1)</script>", date(2026, 1, 1))

    reader = await _export(client, headers, cid)
    assert len(reader.pages) == 2
    assert "<i>Escaped</i>" in reader.pages[0].extract_text()
    text = reader.pages[1].extract_text()
    assert "Notes: <b>x</b> & y" in text
    assert "<script>alert(1)</script>" in text


@pytest.mark.asyncio
async def test_pdf_other_users_campaign_is_404(client, db, promo_code):
    owner_headers, _ = await _register(client, promo_code)
    cid = await _campaign(client, owner_headers, name="Private")
    other_headers, _ = await _register(client, promo_code)

    r = await client.get(f"/api/campaigns/{cid}/export?format=pdf", headers=other_headers)
    assert r.status_code == 404
    r = await client.get(f"/api/campaigns/{uuid.uuid4()}/export?format=pdf", headers=owner_headers)
    assert r.status_code == 404
