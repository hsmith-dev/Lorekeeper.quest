from fpdf import FPDF
from fpdf.enums import XPos, YPos

from app.db.models.campaign import Campaign
from app.db.models.journal import JournalEntry


def _s(text: str) -> str:
    """Sanitize text to Latin-1 for core fpdf fonts."""
    return (
        str(text)
        .replace("—", "--").replace("–", "-")
        .replace("‘", "'").replace("’", "'")
        .replace("“", '"').replace("”", '"')
        .replace("…", "...")
        .encode("latin-1", errors="replace").decode("latin-1")
    )


def build_campaign_markdown(campaign: Campaign, entries: list[JournalEntry]) -> str:
    lines = [f"# {campaign.name}", "", f"*{campaign.genre.value.title()} campaign*", ""]
    if campaign.description:
        lines += [campaign.description, ""]
    lines.append("---")
    for entry in entries:
        date_str = entry.session_date.isoformat() if entry.session_date else entry.created_at.date().isoformat()
        lines += ["", f"## {date_str}", "", f"*Notes: {entry.shorthand}*", "", entry.narrative]
    return "\n".join(lines) + "\n"


def _cell(pdf: FPDF, h: float, text: str) -> None:
    pdf.multi_cell(0, h, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def build_campaign_pdf(campaign: Campaign, entries: list[JournalEntry]) -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 22)
    _cell(pdf, 12, _s(campaign.name))
    pdf.set_font("Helvetica", "I", 12)
    pdf.set_text_color(100, 100, 100)
    _cell(pdf, 8, _s(f"{campaign.genre.value.title()} campaign"))
    if campaign.description:
        pdf.ln(2)
        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(0, 0, 0)
        _cell(pdf, 6, _s(campaign.description))

    for entry in entries:
        pdf.add_page()
        date_str = entry.session_date.isoformat() if entry.session_date else entry.created_at.date().isoformat()
        pdf.set_font("Helvetica", "B", 16)
        pdf.set_text_color(0, 0, 0)
        _cell(pdf, 10, _s(date_str))

        pdf.set_font("Helvetica", "I", 10)
        pdf.set_text_color(110, 110, 110)
        _cell(pdf, 6, _s(f"Notes: {entry.shorthand}"))
        pdf.ln(2)

        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(0, 0, 0)
        _cell(pdf, 6, _s(entry.narrative))

    return bytes(pdf.output())
