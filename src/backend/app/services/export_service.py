from pathlib import Path

# Imported at module top so missing system libraries (Pango, HarfBuzz,
# fontconfig) fail at boot, not on the first export.
import weasyprint
from jinja2 import Environment, FileSystemLoader

from app.db.models.campaign import Campaign
from app.db.models.journal import JournalEntry

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates" / "export"

# autoescape: user text is printed as stored, never interpreted as HTML.
_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)


def _entry_date(entry: JournalEntry) -> str:
    return entry.session_date.isoformat() if entry.session_date else entry.created_at.date().isoformat()


def build_campaign_markdown(campaign: Campaign, entries: list[JournalEntry]) -> str:
    lines = [f"# {campaign.name}", "", f"*{campaign.genre.value.title()} campaign*", ""]
    if campaign.description:
        lines += [campaign.description, ""]
    lines.append("---")
    for entry in entries:
        lines += ["", f"## {_entry_date(entry)}", "", f"*Notes: {entry.shorthand}*", "", entry.narrative]
    return "\n".join(lines) + "\n"


def build_campaign_pdf(campaign: Campaign, entries: list[JournalEntry]) -> bytes:
    html = _env.get_template("campaign.html.j2").render(
        campaign=campaign,
        genre_line=f"{campaign.genre.value.title()} campaign",
        entries=[
            {"date": _entry_date(e), "shorthand": e.shorthand, "narrative": e.narrative}
            for e in entries
        ],
    )
    # base_url resolves the template's relative campaign.css link.
    return weasyprint.HTML(string=html, base_url=str(TEMPLATES_DIR)).write_pdf()
