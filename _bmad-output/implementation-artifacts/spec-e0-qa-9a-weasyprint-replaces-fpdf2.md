---
title: 'E0-QA.9 (PDF half): WeasyPrint replaces fpdf2 in the campaign PDF export'
type: 'refactor'
created: '2026-11-01'
status: 'done'
baseline_revision: '61abdbaea6e82be7c59c94e35d739c6d27c10d0d'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/docs/LICENSING.md'
  - '{project-root}/.github/license-policy.toml'
warnings: []
deferred:
  - summary: >-
      CJK, emoji, Thai and Devanagari text has no glyphs. DejaVu covers Latin, Greek, Cyrillic, Hebrew and Arabic only.
    evidence: |-
      Only fonts-dejavu-core/extra are installed. E8.2 owns bundled fonts (Noto fallback chain).
    location: >-
      src/backend/app/templates/export/campaign.css
    severity: medium
  - summary: >-
      Pyphen's bundled hyphenation dictionaries carry per-file licences. Nobody has reviewed them for the commercial edition.
    evidence: |-
      Hyphenation is not enabled, but the files ship in the image. Settle it by listing the hyph_*.dic licences in the installed pyphen package.
    location: >-
      licenses/register.yaml (Pyphen row)
    severity: medium (unverified)
  - summary: >-
      src/ml/scripts/export_training_report.py has no test, and no ML environment file declares weasyprint/jinja2 (fpdf2 was never declared either).
    evidence: |-
      grep for export_training_report finds only the script. src/ml/environments/*.yml list neither dependency.
    location: >-
      src/ml/scripts/export_training_report.py
    severity: low
  - summary: >-
      The export endpoint has no size bound. A very large campaign renders without limit (this predates the change).
    evidence: |-
      fpdf2 had the same unbounded loop. The render now runs in the thread pool, so the event loop is not blocked.
    location: >-
      src/backend/app/api/routes/campaigns.py export_campaign
    severity: low
---

<intent-contract>

## Intent

**Problem:** The campaign PDF export (`GET /api/campaigns/{id}/export?format=pdf`) uses fpdf2, which is LGPL-3.0 and needs an `OWNER TO CONFIRM` licence exception. Its core Helvetica font is Latin-1 only, so `_s()` turns "Ōkami", "Ведьма" or "—" into "?" or ASCII. OWNER DECISION 2026-11-01 (E0-QA.9): replace fpdf2 rather than accept it.

**Approach:** Render the same content through a Jinja2 HTML template with print CSS and turn it into a PDF with WeasyPrint (BSD-3-Clause), the engine E8 (Chronicle export) will reuse. Install WeasyPrint's system libraries (Pango, HarfBuzz, fontconfig, a Unicode font) in both backend images and in backend CI, and drop fpdf2 everywhere: requirements, register, policy exception and docs.

## Boundaries & Constraints

**Always:**
- Output parity with today's export: page 1 holds the campaign name (title), the "<Genre> campaign" line (italic, grey) and the description if any. Each journal entry starts a new page with its date heading (`session_date`, else `created_at` date, ISO format), an italic grey "Notes: <shorthand>" line, then the narrative. Entry order is unchanged (the route already orders them). A4 page.
- Text is printed exactly as stored. There is no Latin-1 sanitising, user text is HTML-escaped (Jinja autoescape), and newlines in the narrative and description are kept (`white-space: pre-wrap` or equivalent).
- Every font used is embedded. The font stack names the installed apt font family first (DejaVu, `fonts-dejavu-core`, which covers Latin Extended, Greek, Cyrillic, Hebrew and Arabic), then generic `sans-serif`.
- `build_campaign_pdf(campaign, entries) -> bytes` and `build_campaign_markdown` keep their signatures. The route in `app/api/routes/campaigns.py` stays unchanged.
- New Python deps are pinned in `requirements.txt` (`weasyprint==70.0`, and `Jinja2==3.1.6`, which is now imported directly).
- The register entries for WeasyPrint, its Python deps and the new Debian packages carry `images: [backend]` (or extend an existing row's `images`).

**Never:**
- Don't touch the Valkey/redis rows or compose files, OCR/easyocr/python-bidi files or rows, `sprint-status.yaml`, `epics.md`, or `tests/ev4/pending_baseline.txt`.
- No bundled font files under `assets/fonts/`, and no cover page, TOC, running headers or page numbers. Those belong to E8.2.
- Don't vendor or patch WeasyPrint or the LGPL system libraries. They are used dynamically and unmodified.
- Don't strip `/usr/share/doc` in the images (LICENSING.md obligation).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy path | Campaign with a description and 2 entries | 200, `application/pdf`, body starts `%PDF-`, pypdf reads 3 pages, page 1 has the name, genre line and description, each later page has its date, "Notes: …" and narrative | none |
| Unicode | Campaign name "Ælfrida’s Ōkami — Þórr" and an entry narrative containing "Ведьма", "“quotes”" and "Ελένη" | the extracted text contains each string exactly, with no "?" substitutions | none |
| No entries, no description | Campaign only | 1-page PDF with the name and genre line | none |
| HTML-looking text | shorthand `<b>x</b> & y` | printed literally (escaped), not interpreted | none |
| Not owner / missing | Another user's campaign id | 404, as before | unchanged |

</intent-contract>

## Code Map

- `src/backend/app/services/export_service.py` -- sole fpdf2 user: `_s()`, `_cell()` and `build_campaign_pdf` (FPDF, Helvetica). Replace with Jinja2 + WeasyPrint, delete `_s`/`_cell`, keep `build_campaign_markdown` as is.
- `src/backend/app/api/routes/campaigns.py:118-155` -- `export_campaign` route, owner-scoped query, calls `build_campaign_pdf`. Read-only.
- `src/backend/requirements.txt:22` -- `fpdf2==2.8.7`. Remove it and add the pins.
- `src/backend/Dockerfile` (no apt step today) and `src/backend/Dockerfile.prod` (apt line `build-essential libpq-dev`) -- add `libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b fontconfig fonts-dejavu-core` with `--no-install-recommends`. `tests/test_dockerfile_cpu_torch.py` parses these files and must keep passing.
- `.github/workflows/backend-tests.yml` -- add an apt step (the same packages) before "Install dependencies".
- `.github/license-policy.toml:240-252` -- the fpdf2 `[[exception]]` and its LGPL comment block, which also covers python-bidi, so keep the block's wording valid for python-bidi. `system_lib_allowlist` (line ~121) already matches pango, harfbuzz and glib2. Other LGPL/GPL Debian libraries the new installs pull in (e.g. libfribidi0, libthai0, libdatrie1, libgraphite2) must be added, reviewed, to `system_lib_allowlist` (when they are LGPL dynamic libs) or `os_aggregate_allowlist`, each with a comment.
- `licenses/register.yaml` -- one-line flow rows. The fpdf2 row is at ~line 593. Python rows are alphabetical in the python section, apt rows in the "apt: backend image" section (also alphabetical). Jinja2 row exists (line ~610). Update the `python` image entry notes (line ~50) to list the new apt installs.
- `docs/LICENSING.md:~173-179` -- "Owner-approved exceptions" lists fpdf2. Record the decision (replaced by WeasyPrint, 2026-11-01, E0-QA.9) and the new system libraries under the OS/system-library rule.
- `scripts/test_check_licenses.py:155-160` -- uses "fpdf2" only as a synthetic fixture name for LGPL logic. Leave it.
- `src/backend/tests/conftest.py` -- `client` and `db` fixtures. `tests/test_share.py` / `tests/test_journals.py` show how to register a user and create a campaign and entries over the API.
- `_bmad-output/planning-artifacts/brownfield-context.md:225,271` -- mentions fpdf2. Leave the planning docs alone.

## Tasks & Acceptance

**Execution:**
- `src/backend/app/templates/export/campaign.html.j2` + `campaign.css` (new) -- HTML template and print CSS (`@page { size: A4; margin: … }`, `break-before: page` per entry, grey italic meta lines, DejaVu Sans stack). Keep the CSS in its own file so E8 can follow the pattern.
- `src/backend/app/services/export_service.py` -- module-level Jinja2 `Environment(FileSystemLoader(<templates dir>), autoescape=True)`. `build_campaign_pdf` renders the template, then `weasyprint.HTML(string=..., base_url=<templates dir>).write_pdf()` returns bytes. Import WeasyPrint at module top so missing system libs fail at boot, not on first export.
- `src/backend/requirements.txt` -- remove fpdf2, add `weasyprint==70.0` and `Jinja2==3.1.6`.
- `src/backend/Dockerfile`, `src/backend/Dockerfile.prod` -- apt install the five packages (Dockerfile gets a new `apt-get update && install … && rm -rf /var/lib/apt/lists/*` layer), plus a one-line comment on why.
- `.github/workflows/backend-tests.yml` -- `sudo apt-get update && sudo apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b fontconfig fonts-dejavu-core`.
- `.github/license-policy.toml` -- remove the fpdf2 exception and fix the surrounding comment.
- `licenses/register.yaml` -- remove the fpdf2 row. Add python rows for weasyprint (BSD-3-Clause), pydyf, tinycss2, cssselect2, webencodings (BSD-3-Clause), tinyhtml5 (MIT), Pyphen (`GPL-2.0-or-later OR LGPL-2.1-or-later OR MPL-1.1`, used under MPL-1.1, noted), fonttools (MIT), brotli (MIT), zopfli (Apache-2.0), cffi (MIT-0), pycparser (BSD-3-Clause), Pillow, unless a row already exists (then make sure `backend` is in its `images`). The exact set and versions are reconciled against the real image scan (Verification).
- `docs/LICENSING.md` -- record the decision and the new libraries.
- `src/backend/tests/test_export_pdf.py` (new) -- endpoint tests for every matrix row: magic bytes, `len(PdfReader(...).pages)`, `extract_text()` contents.

**Acceptance Criteria:**
- Given the repo, when grepping `fpdf` outside `_bmad-output/` and `scripts/test_check_licenses.py`, then nothing matches.
- Given CI, when `backend-tests.yml` runs, then the PDF tests run (they are not skipped) and pass.
- Given the backend image built from `Dockerfile.prod`, when `scripts/check-licenses.py --register licenses/register.yaml --python-env --os-packages --artifact backend` runs in both editions, then it reports 0 violations.

## Review Triage Log

### 2026-11-01 — Review pass
- verdicts: 39 findings. high 0, medium 4, low 9, false 9, maybe-false 1. The other 16 are spec-drift and descriptive notes, all rejected because the fix would only edit this spec.
- findings:
  - `[medium]` `[patch]` The synchronous WeasyPrint render blocks the event loop. Fixed: the route awaits `run_in_threadpool(build_campaign_pdf, ...)`.
  - `[medium]` `[patch]` No test checks that both Dockerfiles and both workflows install the WeasyPrint apt set. Fixed: added `tests/test_weasyprint_apt_sync.py`.
  - `[low]` `[patch]` The description and narrative were not justified, because `pre-wrap` disables justification in WeasyPrint. Fixed: changed to `white-space: pre-line`, checked by re-rendering page 1.
  - `[low]` `[patch]` Newlines in the shorthand collapsed. Fixed: `.notes` gets `white-space: pre-line`.
  - `[low]` `[patch]` Long unbroken tokens in the title, date or notes could overflow the page. Fixed: `overflow-wrap: anywhere` on `html`.
  - `[medium]` `[defer]` No CJK, emoji or Thai glyphs. Bundled fonts belong to E8.2.
  - `[maybe-false]` `[defer]` Pyphen dictionary licences are unreviewed. Settle it by listing the per-file licences.
  - `[low]` `[defer]` The ML report script is untested and its dependencies are undeclared (verification gap, blind hunter). This predates the change.
  - `[low]` `[defer]` No export size bound. This predates the change.
  - `[false]` `[reject]` The defusedxml row was removed although something may still install it. The built-image scan reports 0 unregistered packages.
  - `[false]` `[reject]` No fc-cache step. The fontconfig postinst builds the cache during the apt install.
  - `[false]` `[reject]` Unpinned WeasyPrint dependencies make the scan fail. Version differences are informational in check-licenses.py.
  - `[false]` `[reject]` The default url_fetcher allows SSRF. All user text is autoescaped and the template has no user URLs, so no fetch is reachable.
  - `[false]` `[reject]` The font test misses XObject fonts. pdffonts on the real export lists only the 3 embedded DejaVu faces.
  - `[false]` `[reject]` The register rows for Pango/FriBidi break the scan. The scan passes with 0 violations in both editions, and the rows match the scan strings.
  - `[low]` `[reject]` Register rows are inconsistent about `scanned_license`. Cosmetic: the scan matches either way.
  - `[low]` `[reject]` MPL-1.1 is allowed policy-wide. MPL-1.1 is a permissive weak-copyleft licence, the same class as the allowed MPL-2.0.
  - `[low]` `[reject]` No RFC 5987 `filename*`. This is an enhancement; the ASCII filename works.
  - `[low]` `[reject]` No dev-setup docs for Pango. Backend dev runs in Docker, and the Dockerfile has the packages.
  - `[low]` `[reject]` RTL `dir=auto` is missing. Pango applies bidi per run. Adding it would mean a markup change with no reported user.
  - `[low]` `[reject]` The ML report adds running headers. That is not the campaign export, so E8.2's scope is untouched.
  - `[false]` `[reject]` The intent auditor said the image size and scan output are unrecorded. They are recorded under Auto Run Result.
  - The remaining rows (spec says route unchanged, 5 vs 6 packages, gates.yml and ML script missing from the Code Map, intent-reading descriptions) are rejected: their fix is to edit this spec. They are recorded below.

## Design Notes

The narrative is free text with newlines. Render it inside one block with `white-space: pre-wrap` so it matches fpdf2's `multi_cell` line breaks, rather than splitting it into `<p>` elements. pypdf's `extract_text()` may insert line breaks inside long lines, so tests check short strings (single words or names), and the long narrative check uses a whitespace-normalised comparison.

## Verification

**Commands:**
- `cd src/backend && python -m py_compile app/services/export_service.py tests/test_export_pdf.py` -- expected: no output
- Desktop: build `Dockerfile.prod`, run the full backend pytest suite in the `lorekeeper-backend-test` image plus the apt packages and new pins against `lorekeeper_test_e0qa9a` -- expected: everything passes, including the new export tests
- Desktop: run the image licence scan above in both editions -- expected: 0 violations
- Draft PR CI (`backend-tests`, `license-check`, `gates`) -- expected: green

**Manual checks (if no CLI):**
- Page-1 PNGs (pdftoppm) of the fpdf2 (main) and WeasyPrint exports of the seeded demo campaign show the same sections.

## Auto Run Result

Status: done

- **Summary:** fpdf2 is replaced by WeasyPrint 70.0 + Jinja2 (`app/templates/export/campaign.html.j2`, `campaign.css`) for `GET /api/campaigns/{id}/export?format=pdf`. DejaVu fonts are embedded, and text prints as stored (no Latin-1 `?`).
- **Deviations from the plan, all recorded:**
  - a sixth apt package, `fonts-dejavu-extra`, for the oblique face;
  - the route's `safe_name` is now ASCII-only, because a non-Latin name gave a 500 (Latin-1 header) and the route now renders in the thread pool;
  - `gates.yml` gets the apt step, since app import loads Pango;
  - `src/ml/scripts/export_training_report.py` is ported off fpdf2;
  - `scripts/test_check_licenses.py` now asserts the policy has no fpdf2 exception;
  - the defusedxml row is dropped, since only fpdf2 used it.
- **Files:**
  - `export_service.py`, the templates, `campaigns.py`, `requirements.txt`
  - both Dockerfiles, `backend-tests.yml`, `gates.yml`
  - `license-policy.toml`, `register.yaml`, `LICENSING.md`
  - `test_export_pdf.py`, `test_weasyprint_apt_sync.py`, `test_check_licenses.py`
  - the ML script
- **Review:** 5 patches applied (2 medium, 3 low), 4 deferred, the rest rejected (see the triage log).
- **Follow-up review recommended:** false. No high was patched, and the 2 medium patches are each covered: one by a test, the other is a one-line thread-pool call that the full suite exercises.
- **Verification (desktop, 2026-11-01):**
  - `Dockerfile.prod` builds.
  - The in-image licence scan reports 0 violations in agpl and commercial.
  - The full backend suite passes in the built image: 757 passed, 21 skipped.
  - The seeded demo export has 13 pages, the same as fpdf2.
  - Page-1 PNGs show the same sections.
  - The image grows from 6,984,843,380 to 7,039,229,485 bytes (+54.4 MB, +0.8%).
- **Residual risks:** CI's apt step installs Ubuntu builds of the libraries, not the Debian builds that ship. CJK and emoji glyphs are deferred to E8.2.
