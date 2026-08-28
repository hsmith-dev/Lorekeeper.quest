"""
Queries the training_samples table and exports a PDF report.
Usage: python export_training_report.py [--output PATH] [--db-url URL]
"""
import argparse
import asyncio
import os
from datetime import datetime, timezone

import asyncpg
from fpdf import FPDF


def s(text: str) -> str:
    """Sanitize text to Latin-1 for core fpdf fonts."""
    return (
        str(text)
        .replace("—", "--").replace("–", "-")
        .replace("‘", "'").replace("’", "'")
        .replace("“", '"').replace("”", '"')
        .replace("…", "...").replace("é", "e")
        .replace("à", "a").replace("è", "e")
        .replace("ü", "u").replace("ö", "o")
        .encode("latin-1", errors="replace").decode("latin-1")
    )


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

class Report(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(80, 80, 80)
        self.cell(0, 8, s("Lorekeeper.quest -- Training Data Report"), align="L")
        self.ln(4)
        self.set_draw_color(180, 180, 180)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(4)

    def footer(self):
        self.set_y(-14)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 8, f"Page {self.page_no()}", align="C")

    # ── helpers ──────────────────────────────────────────────────────────

    def section_title(self, text: str):
        self.ln(4)
        self.set_font("Helvetica", "B", 13)
        self.set_text_color(30, 30, 30)
        self.cell(0, 8, text, ln=True)
        self.set_draw_color(100, 100, 200)
        self.set_line_width(0.5)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.set_line_width(0.2)
        self.ln(4)

    def stat_row(self, label: str, value: str, indent: int = 0):
        self.set_font("Helvetica", "", 10)
        self.set_text_color(60, 60, 60)
        x = self.l_margin + indent
        self.set_x(x)
        self.cell(80, 6, s(label), ln=False)
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(20, 20, 20)
        self.cell(0, 6, s(value), ln=True)

    def table(self, headers: list[str], rows: list[list[str]], col_widths: list[float]):
        # header row
        self.set_font("Helvetica", "B", 9)
        self.set_fill_color(230, 230, 245)
        self.set_text_color(30, 30, 30)
        for h, w in zip(headers, col_widths):
            self.cell(w, 7, s(h), border=1, fill=True)
        self.ln()
        # data rows
        self.set_font("Helvetica", "", 9)
        for i, row in enumerate(rows):
            self.set_fill_color(248, 248, 255) if i % 2 == 0 else self.set_fill_color(255, 255, 255)
            self.set_text_color(40, 40, 40)
            for cell, w in zip(row, col_widths):
                self.cell(w, 6, s(str(cell)), border=1, fill=True)
            self.ln()
        self.ln(3)

    def sample_block(self, genre: str, system: str, scenario: str,
                     shorthand: str, narrative: str):
        # card header
        self.set_fill_color(240, 240, 252)
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(60, 60, 130)
        label = f"  {genre.upper()} / {system} / {scenario}"
        self.cell(0, 7, s(label), border=1, fill=True, ln=True)

        # shorthand
        self.set_font("Helvetica", "B", 8)
        self.set_text_color(80, 80, 80)
        self.set_x(self.l_margin + 2)
        self.cell(25, 5, "Shorthand:", ln=False)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(50, 50, 50)
        self.multi_cell(0, 5, s(shorthand), border=0)

        # narrative (truncated at 600 chars)
        preview = narrative[:600].strip()
        if len(narrative) > 600:
            preview += "..."
        self.set_font("Helvetica", "B", 8)
        self.set_text_color(80, 80, 80)
        self.set_x(self.l_margin + 2)
        self.cell(25, 5, "Narrative:", ln=False)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(40, 40, 40)
        self.multi_cell(0, 5, s(preview), border=0)
        self.ln(3)


# ---------------------------------------------------------------------------
# Build the report
# ---------------------------------------------------------------------------

def build_pdf(data: dict, output_path: str) -> None:
    totals    = data["totals"]
    by_genre  = data["by_genre"]
    by_system = data["by_system"]
    by_scen   = data["by_scenario"]
    samples   = data["samples"]

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    gen_from = str(totals.get("generated_from", ""))[:19]
    gen_to   = str(totals.get("generated_to",   ""))[:19]

    pdf = Report(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.set_margins(left=15, top=15, right=15)

    # ── Cover / Summary ──────────────────────────────────────────────────
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(30, 30, 120)
    pdf.ln(6)
    pdf.cell(0, 12, "Training Data Report", align="C", ln=True)

    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(90, 90, 90)
    pdf.cell(0, 7, s("Lorekeeper.quest -- Shorthand -> Narrative Dataset"), align="C", ln=True)
    pdf.cell(0, 6, s(f"Generated: {generated_at}"), align="C", ln=True)
    pdf.ln(8)

    # summary stats box
    pdf.set_fill_color(245, 245, 255)
    pdf.set_draw_color(160, 160, 220)
    pdf.rect(pdf.l_margin, pdf.get_y(), pdf.w - pdf.l_margin - pdf.r_margin, 52, style="DF")
    pdf.ln(4)

    pdf.stat_row("Total samples:", f"{totals['total']:,}", indent=6)
    pdf.stat_row("Samples with narratives:", f"{totals['narrated']:,} ({int(totals['narrated']/totals['total']*100)}%)", indent=6)
    pdf.stat_row("Missing narratives:", str(totals['missing_narrative']), indent=6)
    pdf.stat_row("Avg narrative length:", f"{totals['avg_narrative_chars']:,} chars", indent=6)
    pdf.stat_row("Narrative length range:", f"{totals['min_narrative_chars']:,} – {totals['max_narrative_chars']:,} chars", indent=6)
    pdf.stat_row("Avg shorthand length:", f"{totals['avg_shorthand_chars']} chars", indent=6)
    pdf.stat_row("Generation window:", f"{gen_from}  ->  {gen_to}", indent=6)
    pdf.ln(6)

    # ── By Genre ─────────────────────────────────────────────────────────
    pdf.section_title("Breakdown by Genre")
    pdf.table(
        headers=["Genre", "Total", "Narrated", "Avg Narrative (chars)"],
        rows=[[r["genre"], r["total"], r["narrated"], r["avg_chars"]] for r in by_genre],
        col_widths=[50, 30, 35, 60],
    )

    # ── By Game System ───────────────────────────────────────────────────
    pdf.section_title("Breakdown by Genre / Game System")
    pdf.table(
        headers=["Genre", "Game System", "Total", "Narrated", "Avg Chars"],
        rows=[[r["genre"], r["game_system"], r["total"], r["narrated"], r["avg_chars"]]
              for r in by_system],
        col_widths=[30, 52, 22, 27, 44],
    )

    # ── By Scenario Type ─────────────────────────────────────────────────
    pdf.section_title("Breakdown by Scenario Type")
    pdf.table(
        headers=["Scenario Type", "Total", "Avg Narrative (chars)"],
        rows=[[r["scenario_type"], r["total"], r["avg_chars"]] for r in by_scen],
        col_widths=[70, 30, 75],
    )

    # ── Sample Pairs ─────────────────────────────────────────────────────
    pdf.add_page()
    pdf.section_title("Sample Shorthand -> Narrative Pairs (2 per Game System)")

    for sample in samples:
        if pdf.get_y() > 240:
            pdf.add_page()
        pdf.sample_block(
            genre=sample["genre"],
            system=sample["game_system"],
            scenario=sample["scenario_type"],
            shorthand=sample["shorthand"],
            narrative=sample["narrative"],
        )

    pdf.output(output_path)
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
