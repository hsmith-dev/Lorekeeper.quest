"""
Queries the training_samples table and exports a PDF report.
Usage: python export_training_report.py [--output PATH] [--db-url URL]

Rendered with WeasyPrint (BSD-3-Clause, E0-QA.9), like the backend's campaign
export. Needs Pango and fontconfig on the machine (see src/backend/Dockerfile).
"""
import argparse
import asyncio
import os
from datetime import datetime, timezone

import asyncpg
import weasyprint
from jinja2 import Environment

# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

async def fetch_data(db_url: str) -> dict:
    conn = await asyncpg.connect(db_url)

    totals = dict(await conn.fetchrow("""
        SELECT
            COUNT(*)                                         AS total,
            COUNT(narrative)                                 AS narrated,
            COUNT(*) FILTER (WHERE narrative IS NULL)        AS missing_narrative,
            ROUND(AVG(LENGTH(narrative))::numeric, 1)        AS avg_narrative_chars,
            MIN(LENGTH(narrative))                           AS min_narrative_chars,
            MAX(LENGTH(narrative))                           AS max_narrative_chars,
            ROUND(AVG(LENGTH(shorthand))::numeric, 1)        AS avg_shorthand_chars,
            MIN(created_at)                                  AS generated_from,
            MAX(created_at)                                  AS generated_to
        FROM training_samples
    """))

    by_genre = [dict(r) for r in await conn.fetch("""
        SELECT genre,
               COUNT(*)                                  AS total,
               COUNT(narrative)                          AS narrated,
               ROUND(AVG(LENGTH(narrative))::numeric, 1) AS avg_chars
        FROM training_samples
        GROUP BY genre
        ORDER BY genre
    """)]

    by_system = [dict(r) for r in await conn.fetch("""
        SELECT genre, game_system,
               COUNT(*)                                  AS total,
               COUNT(narrative)                          AS narrated,
               ROUND(AVG(LENGTH(narrative))::numeric, 1) AS avg_chars
        FROM training_samples
        GROUP BY genre, game_system
        ORDER BY genre, game_system
    """)]

    by_scenario = [dict(r) for r in await conn.fetch("""
        SELECT scenario_type,
               COUNT(*)                                  AS total,
               ROUND(AVG(LENGTH(narrative))::numeric, 1) AS avg_chars
        FROM training_samples
        GROUP BY scenario_type
        ORDER BY scenario_type
    """)]

    samples = [dict(r) for r in await conn.fetch("""
        SELECT genre, game_system, scenario_type, shorthand, narrative
        FROM (
            SELECT *,
                   ROW_NUMBER() OVER (
                       PARTITION BY game_system
                       ORDER BY created_at
                   ) AS rn
            FROM training_samples
            WHERE narrative IS NOT NULL
        ) t
        WHERE rn <= 2
        ORDER BY genre, game_system, scenario_type
    """)]

    await conn.close()
    return {
        "totals": totals,
        "by_genre": by_genre,
        "by_system": by_system,
        "by_scenario": by_scenario,
        "samples": samples,
    }


# ---------------------------------------------------------------------------
# PDF builder
# ---------------------------------------------------------------------------

CSS = """
@page {
  size: A4;
  margin: 24mm 15mm 18mm 15mm;
  @top-left {
    content: "Lorekeeper.quest \\2014  Training Data Report";
    font: bold 10pt "DejaVu Sans", sans-serif; color: #505050;
    border-bottom: 0.2mm solid #b4b4b4; width: 100%; vertical-align: bottom; padding-bottom: 2mm;
  }
  @bottom-center { content: "Page " counter(page); font: 8pt "DejaVu Sans", sans-serif; color: #969696; }
}
html { font-family: "DejaVu Sans", sans-serif; font-size: 10pt; color: #141414; }
h1 { text-align: center; font-size: 20pt; color: #1e1e78; margin: 6mm 0 3mm; }
.sub { text-align: center; color: #5a5a5a; font-size: 11pt; margin: 1mm 0; }
.summary { background: #f5f5ff; border: 0.3mm solid #a0a0dc; padding: 4mm 6mm; margin: 8mm 0 6mm; }
.summary td { padding: 0.8mm 0; }
.summary td:first-child { width: 80mm; color: #3c3c3c; }
.summary td:last-child { font-weight: bold; }
h2 { font-size: 13pt; color: #1e1e1e; border-bottom: 0.5mm solid #6464c8; padding-bottom: 1mm; margin: 6mm 0 4mm; }
table.data { border-collapse: collapse; font-size: 9pt; margin-bottom: 3mm; }
table.data th { background: #e6e6f5; text-align: left; }
table.data th, table.data td { border: 0.2mm solid #000; padding: 1mm 1.5mm; }
table.data tr:nth-child(even) td { background: #f8f8ff; }
.samples { break-before: page; }
.sample { margin-bottom: 3mm; font-size: 8pt; break-inside: avoid; }
.sample .head { background: #f0f0fc; border: 0.2mm solid #000; padding: 1mm 2mm;
                font-weight: bold; font-size: 9pt; color: #3c3c82; }
.sample .row { display: flex; padding: 0.5mm 0.5mm 0; }
.sample .label { flex: 0 0 25mm; font-weight: bold; color: #505050; }
.sample .shorthand { font-style: italic; color: #323232; }
.sample .text { white-space: pre-wrap; }
"""

TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><style>{{ css | safe }}</style></head><body>
<h1>Training Data Report</h1>
<p class="sub">Lorekeeper.quest &mdash; Shorthand &rarr; Narrative Dataset</p>
<p class="sub">Generated: {{ generated_at }}</p>
<table class="summary">
{%- for label, value in stats %}
  <tr><td>{{ label }}</td><td>{{ value }}</td></tr>
{%- endfor %}
</table>
{%- for section in sections %}
<h2>{{ section.title }}</h2>
<table class="data">
  <tr>{% for h in section.headers %}<th>{{ h }}</th>{% endfor %}</tr>
  {%- for row in section.rows %}
  <tr>{% for cell in row %}<td>{{ cell }}</td>{% endfor %}</tr>
  {%- endfor %}
</table>
{%- endfor %}
<section class="samples">
<h2>Sample Shorthand &rarr; Narrative Pairs (2 per Game System)</h2>
{%- for s in samples %}
<div class="sample">
  <div class="head">{{ s.genre | upper }} / {{ s.game_system }} / {{ s.scenario_type }}</div>
  <div class="row"><span class="label">Shorthand:</span><span class="text shorthand">{{ s.shorthand }}</span></div>
  <div class="row"><span class="label">Narrative:</span><span class="text">{{ s.preview }}</span></div>
</div>
{%- endfor %}
</section>
</body></html>
"""


# ---------------------------------------------------------------------------
# Build the report
# ---------------------------------------------------------------------------

def build_pdf(data: dict, output_path: str) -> None:
    totals = data["totals"]
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    gen_from = str(totals.get("generated_from", ""))[:19]
    gen_to = str(totals.get("generated_to", ""))[:19]

    stats = [
        ("Total samples:", f"{totals['total']:,}"),
        ("Samples with narratives:",
         f"{totals['narrated']:,} ({int(totals['narrated'] / totals['total'] * 100)}%)"),
        ("Missing narratives:", str(totals["missing_narrative"])),
        ("Avg narrative length:", f"{totals['avg_narrative_chars']:,} chars"),
        ("Narrative length range:",
         f"{totals['min_narrative_chars']:,} – {totals['max_narrative_chars']:,} chars"),
        ("Avg shorthand length:", f"{totals['avg_shorthand_chars']} chars"),
        ("Generation window:", f"{gen_from}  →  {gen_to}"),
    ]
    sections = [
        {"title": "Breakdown by Genre",
         "headers": ["Genre", "Total", "Narrated", "Avg Narrative (chars)"],
         "rows": [[r["genre"], r["total"], r["narrated"], r["avg_chars"]] for r in data["by_genre"]]},
        {"title": "Breakdown by Genre / Game System",
         "headers": ["Genre", "Game System", "Total", "Narrated", "Avg Chars"],
         "rows": [[r["genre"], r["game_system"], r["total"], r["narrated"], r["avg_chars"]]
                  for r in data["by_system"]]},
        {"title": "Breakdown by Scenario Type",
         "headers": ["Scenario Type", "Total", "Avg Narrative (chars)"],
         "rows": [[r["scenario_type"], r["total"], r["avg_chars"]] for r in data["by_scenario"]]},
    ]
    samples = []
    for sample in data["samples"]:
        narrative = sample["narrative"]
        preview = narrative[:600].strip() + ("..." if len(narrative) > 600 else "")
        samples.append({**sample, "preview": preview})

    html = Environment(autoescape=True).from_string(TEMPLATE).render(
        css=CSS, generated_at=generated_at, stats=stats, sections=sections, samples=samples)
    weasyprint.HTML(string=html).write_pdf(output_path)
    print(f"PDF saved to: {output_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="/home/smith/Documents/Capstone/docs/training_data_report.pdf")
    parser.add_argument("--db-url", default=None)
    args = parser.parse_args()

    db_url = args.db_url or os.environ.get(
        "DATABASE_URL",
        "postgresql://lorekeeper:changeme@localhost:5432/lorekeeper"
    ).replace("postgresql+asyncpg://", "postgresql://")

    data = asyncio.run(fetch_data(db_url))
    build_pdf(data, args.output)


if __name__ == "__main__":
    main()
