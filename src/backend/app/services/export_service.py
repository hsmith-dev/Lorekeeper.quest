"""Campaign export (Markdown, PDF) built from projected models only
(E0-Access.13): the route passes `project(campaign, ctx)` and
`project_all(db, entries, ctx)`, so a GM field (Shorthand) is in the export
exactly when the caller's projection carries it. Never pass ORM rows here."""
from pathlib import Path

# Imported at module top so missing system libraries (Pango, HarfBuzz,
# fontconfig) fail at boot, not on the first export.
import weasyprint
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates" / "export"

# autoescape: user text is printed as stored, never interpreted as HTML.
_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)


def _entry_date(entry: BaseModel) -> str:
    return entry.session_date.isoformat() if entry.session_date else entry.created_at.date().isoformat()


def _shorthand(entry: BaseModel) -> str | None:
    # Only the GM projection (JournalGMResponse) has the field. An ORM row
    # also has it, so refuse one: it would print Shorthand for anyone.
    if not isinstance(entry, BaseModel):
        raise TypeError("export_service: pass projected entries (project_all), not ORM rows")
    return getattr(entry, "shorthand", None)


def build_campaign_markdown(campaign: BaseModel, entries: list[BaseModel]) -> str:
    lines = [f"# {campaign.name}", "", f"*{campaign.genre.value.title()} campaign*", ""]
    if campaign.description:
        lines += [campaign.description, ""]
    lines.append("---")
    for entry in entries:
        lines += ["", f"## {_entry_date(entry)}", ""]
        if (shorthand := _shorthand(entry)) is not None:
            lines += [f"*Notes: {shorthand}*", ""]
        lines.append(entry.narrative)
    return "\n".join(lines) + "\n"


def build_campaign_pdf(campaign: BaseModel, entries: list[BaseModel]) -> bytes:
    html = _env.get_template("campaign.html.j2").render(
        campaign=campaign,
        genre_line=f"{campaign.genre.value.title()} campaign",
        entries=[
            {"date": _entry_date(e), "shorthand": _shorthand(e), "narrative": e.narrative}
            for e in entries
        ],
    )
    # base_url resolves the template's relative campaign.css link.
    return weasyprint.HTML(string=html, base_url=str(TEMPLATES_DIR)).write_pdf()
