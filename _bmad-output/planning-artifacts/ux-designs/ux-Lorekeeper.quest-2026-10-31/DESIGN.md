---
name: Lorekeeper
description: Self-hosted AI campaign companion for tabletop RPGs. This DESIGN.md is the brand-layer delta for the living-world expansion (F1–F10). It extends the existing theme CSS-variable system in src/frontend/src/themes and the shadcn-style primitives in components/ui. It does not replace them.
status: final
created: 2026-10-31
updated: 2026-10-31
sources:
  - ../../prds/prd-Lorekeeper.quest-2026-10-31/prd.md
  - ../../prds/prd-Lorekeeper.quest-2026-10-31/addendum.md
  - ../../scope-input.md
  - ../../brownfield-context.md
  - src/frontend/src/themes/*.ts
  - src/frontend/tailwind.config.ts
  - src/frontend/src/index.css
  - site/styles.css
colors:
  # INHERITED, not restated: background, foreground, card, card-foreground,
  # popover, popover-foreground, primary, primary-foreground, secondary,
  # secondary-foreground, muted, muted-foreground, accent, accent-foreground,
  # destructive, destructive-foreground, border, input, ring. Each theme file
  # owns these values as HSL triplets, and ThemeContext writes them to :root.
  #
  # NEW semantic tokens. Each is a TEXT/ICON-SAFE hue (>= 4.5:1 on that
  # theme's card and background, and on its own 14% wash over card). Fills
  # use the token at 14% alpha ("wash"). Implement them as new HSL keys in
  # ThemeColors (types/theme.ts) and every themes/*.ts file, then expose them
  # in tailwind.config.ts as hsl(var(--success)) and so on.
  # Unsuffixed keys = the default theme (dnd, "Dungeons & Dragons").
  success: '#5EBA6E'            # dnd 130 40% 55%
  warning: '#EF9A39'            # dnd 32 85% 58%
  info: '#75AED7'               # dnd 205 55% 65%
  gm: '#C490D5'                 # dnd 285 45% 70%
  live: '#EF756C'               # dnd 4 80% 68%
  danger: '#ED8282'             # dnd 0 75% 72%
  success-arcane: '#59C08C'     # 150 45% 55%
  warning-arcane: '#F0B042'     # 38 85% 60%
  info-arcane: '#64BBD8'        # 195 60% 62%
  gm-arcane: '#DF90C5'          # 320 55% 72%
  live-arcane: '#F0758A'        # 350 80% 70%
  danger-arcane: '#ED8282'      # 0 75% 72%
  success-highseas: '#5EBA85'   # 145 40% 55%
  warning-highseas: '#F09942'   # 30 85% 60%
  info-highseas: '#69C2D3'      # 190 55% 62%
  gm-highseas: '#C297D8'        # 280 45% 72%
  live-highseas: '#EF756C'      # 4 80% 68%
  danger-highseas: '#ED8282'    # 0 75% 72%
  success-forest: '#7BC059'     # 100 45% 55%
  warning-forest: '#EFAC39'     # 38 85% 58%
  info-forest: '#79B5D2'        # 200 50% 65%
  gm-forest: '#CB9BD4'          # 290 40% 72%
  live-forest: '#EF7E6C'        # 8 80% 68%
  danger-forest: '#ED8282'      # 0 75% 72%
  success-cyberpunk: '#25F425'  # 120 90% 55%
  warning-cyberpunk: '#FFD91A'  # 50 100% 55%
  info-cyberpunk: '#4DC3FF'     # 200 100% 65%
  gm-cyberpunk: '#BF80FF'       # 270 100% 75%
  live-cyberpunk: '#FF5C92'     # 340 100% 68%
  danger-cyberpunk: '#FF7070'   # 0 100% 72%
  success-light: '#147136'      # 142 70% 26%
  warning-light: '#9B4D08'      # 28 90% 32%
  info-light: '#11629C'         # 205 80% 34%
  gm-light: '#6F2E9E'           # 275 55% 40%
  live-light: '#B81E1E'         # 0 72% 42%
  danger-light: '#B81E1E'       # 0 72% 42%
  # Reference copies of inherited dnd values, used only to state contrast.
  # The theme file stays the source of truth.
  ref-dnd-background: '#120F0D'
  ref-dnd-card: '#1D1916'
  ref-dnd-foreground: '#EBE5D6'
  ref-dnd-primary: '#D3A122'
  ref-dnd-muted-foreground: '#A99D7E'
  # Brand foil (site/styles.css --foil), used only for Achievement moments.
  foil-start: '#B98526'
  foil-mid: '#F3D488'
  foil-end: '#C18B2A'
typography:
  # Families are always the theme variables, never literal fonts:
  # var(--font-heading) is Cinzel in dnd/arcane, Palatino in highseas,
  # Georgia in forest, Courier New in cyberpunk, and inherit in light.
  # var(--font-body) is Crimson Text in dnd, and so on per theme.
  page-title:
    fontFamily: 'var(--font-heading)'
    fontSize: 24px
    fontWeight: '700'
    lineHeight: '1.3'
    letterSpacing: 0.04em
  entity-title:
    fontFamily: 'var(--font-heading)'
    fontSize: 30px
    fontWeight: '700'
    lineHeight: '1.2'
    letterSpacing: 0.04em
  entity-title-mobile:
    fontFamily: 'var(--font-heading)'
    fontSize: 24px
    fontWeight: '700'
    lineHeight: '1.2'
  section-label:
    fontFamily: 'var(--font-heading)'
    fontSize: 12px
    fontWeight: '600'
    lineHeight: '1.4'
    letterSpacing: 0.1em
  body:
    fontFamily: 'var(--font-body)'
    fontSize: 16.8px
    fontWeight: '400'
    lineHeight: '1.65'
  body-sm:
    fontFamily: 'var(--font-body)'
    fontSize: 14px
    fontWeight: '400'
    lineHeight: '1.55'
  meta:
    fontFamily: 'var(--font-body)'
    fontSize: 12px
    fontWeight: '400'
    lineHeight: '1.4'
  quote:
    fontFamily: 'var(--font-body)'
    fontSize: 14px
    fontWeight: '400'
    lineHeight: '1.55'
  mono:
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace'
    fontSize: 12px
    fontWeight: '400'
    lineHeight: '1.4'
  stat-display:
    fontFamily: 'var(--font-heading)'
    fontSize: 24px
    fontWeight: '700'
    lineHeight: '1.2'
  caption-live:
    fontFamily: 'var(--font-body)'
    fontSize: 20px
    fontWeight: '400'
    lineHeight: '1.5'
  caption-table:
    fontFamily: 'var(--font-body)'
    fontSize: 36px
    fontWeight: '500'
    lineHeight: '1.3'
  recap-table:
    fontFamily: 'var(--font-body)'
    fontSize: 32px
    fontWeight: '400'
    lineHeight: '1.45'
  chronicle-body:
    fontFamily: 'bundled OFL book serif (addendum F, e.g. EB Garamond or Noto Serif)'
    fontSize: 11pt
    fontWeight: '400'
    lineHeight: '1.45'
  chronicle-chapter:
    fontFamily: 'Cinzel (OFL)'
    fontSize: 22pt
    fontWeight: '700'
    lineHeight: '1.2'
    letterSpacing: 0.06em
rounded:
  # Inherited from tailwind.config.ts. --radius is per theme: cyberpunk 0,
  # dnd 0.2rem, highseas 0.3rem, arcane 0.375rem, forest 0.4rem, light 0.5rem.
  sm: 'calc(var(--radius) - 4px)'
  md: 'calc(var(--radius) - 2px)'
  lg: 'var(--radius)'
  xl: 'calc(var(--radius) + 4px)'   # existing rounded-xl dropdowns; Tailwind default 12px today
  full: 9999px
spacing:
  # Tailwind 4-px scale inherited (1=4px ... 16=64px). Named tokens only:
  gutter-mobile: 16px
  page-max: 64rem          # max-w-5xl, the existing app shell width
  reading-max: 48rem       # max-w-3xl, existing journal/record width
  slideover-max: 32rem     # md:max-w-lg, existing SlideOver
  slideover-wide: 48rem    # md:max-w-3xl, new wide variant for Review Checklist
  tap-target: 44px
  tap-target-table: 56px
components:
  visibility-badge-party:
    background: 'transparent'
    foreground: '{colors.ref-dnd-muted-foreground}'
    border: '1px solid border'
    radius: '{rounded.full}'
    icon: 'lucide Eye'
    typography: '{typography.meta}'
  visibility-badge-gm:
    background: '{colors.gm} @ 14%'
    foreground: '{colors.gm}'
    border: '1px solid {colors.gm} @ 40%'
    radius: '{rounded.full}'
    icon: 'lucide Lock'
    typography: '{typography.meta}'
  visibility-badge-private:
    background: '{colors.info} @ 14%'
    foreground: '{colors.info}'
    border: '1px solid {colors.info} @ 40%'
    radius: '{rounded.full}'
    icon: 'lucide UserRound'
    typography: '{typography.meta}'
  secret-field:
    background: '{colors.gm} @ 6%'
    border: '1px dashed {colors.gm} @ 50%'
    radius: '{rounded.lg}'
  preview-banner:
    background: '{colors.info}'
    foreground: 'background (theme)'
    height: 40px
    typography: '{typography.body-sm}'
  role-badge:
    background: 'muted'
    foreground: 'foreground'
    radius: '{rounded.full}'
    typography: '{typography.meta}'
  job-tray-button:
    size: 36px
    badge-background: 'primary'
    badge-foreground: 'primary-foreground'
  job-row:
    background: 'card'
    border: '1px solid border'
    radius: '{rounded.lg}'
    progress-track: 'muted'
    progress-fill: 'primary'
    failed-foreground: '{colors.danger}'
  review-checklist:
    background: 'primary @ 5%'
    border: '1px solid primary @ 30%'
    radius: '{rounded.lg}'
    width: '{spacing.slideover-wide}'
  proposal-item:
    background: 'card'
    border: '1px solid border'
    radius: '{rounded.lg}'
    padding: 12px
    approved-accent: '{colors.success}'
    rejected-opacity: 0.55
    edited-accent: 'primary'
  proposal-item-attention:
    border-left: '3px solid {colors.warning}'
  diff-old:
    foreground: 'muted-foreground'
    decoration: 'line-through'
  diff-new:
    foreground: 'foreground'
    weight: '600'
  mention-quote:
    border-left: '2px solid border'
    foreground: 'muted-foreground'
    typography: '{typography.quote}'
    style: 'italic'
  continuity-flag:
    background: '{colors.warning} @ 14%'
    border: '1px solid {colors.warning} @ 45%'
    foreground: 'foreground'
    icon-color: '{colors.warning}'
    radius: '{rounded.lg}'
  canon-note:
    background: 'primary @ 6%'
    border-left: '3px solid primary'
    icon: 'lucide Feather'
    radius: '{rounded.lg}'
  status-badge:
    radius: '{rounded.full}'
    typography: '{typography.meta}'
    alive: '{colors.success}'
    deceased: 'muted-foreground, lucide Skull, label text'
    missing: '{colors.warning}'
    unknown: 'muted-foreground'
    destroyed: 'muted-foreground, lucide Ban'
  entity-chip:
    background: 'muted'
    foreground: 'foreground'
    radius: '{rounded.full}'
    height: 28px
  graph-node:
    fill: 'card'
    stroke: 'foreground @ 70%'
    stroke-pc: 'primary'
    stroke-gm-only: '{colors.gm}, dashed'
    deceased-opacity: 0.5
    focus-ring: 'ring, 3px'
    label: '{typography.meta}'
  graph-edge:
    stroke: 'muted-foreground @ 60%'
    hostile: '{colors.danger} @ 70%'
    ended: 'dashed'
  map-pin:
    fill: 'primary'
    foreground: 'primary-foreground'
    size: 32px
    hit-area: '{spacing.tap-target}'
  map-pin-gm:
    fill: 'card'
    border: '2px dashed {colors.gm}'
    foreground: '{colors.gm}'
  live-status-bar:
    background: 'card'
    border-bottom: '1px solid border'
    rec-dot: '{colors.live}'
    height: 56px
  caption-chunk:
    typography: '{typography.caption-live}'
    timestamp: '{typography.mono}'
  caption-pending:
    foreground: 'muted-foreground'
    border: '1px dashed border'
    radius: '{rounded.md}'
  lag-meter:
    ok: '{colors.success}'
    behind: '{colors.warning}'
    typography: '{typography.mono}'
  rolling-recap-card:
    background: 'card'
    border: '1px solid border'
    label-foreground: 'muted-foreground'
    radius: '{rounded.lg}'
  table-view:
    background: 'background'
    caption: '{typography.caption-table}'
    recap: '{typography.recap-table}'
    tap-target: '{spacing.tap-target-table}'
  recap-player:
    background: 'card'
    border: '1px solid border'
    radius: '{rounded.lg}'
    active-sentence: 'primary @ 14% background'
    control-size: '{spacing.tap-target}'
  npc-message:
    background: 'muted'
    name-typography: '{typography.section-label}'
    radius: '{rounded.lg}'
  not-from-memories-label:
    background: '{colors.warning} @ 14%'
    foreground: '{colors.warning}'
    radius: '{rounded.full}'
  milestone-card:
    background: 'card'
    border: '1px solid primary @ 40%'
    radius: '{rounded.lg}'
    title: '{typography.stat-display}'
  achievement-badge:
    background: 'muted'
    ring-earned: 'linear-gradient {colors.foil-start} → {colors.foil-mid} → {colors.foil-end}'
    size: 56px
    radius: '{rounded.full}'
  model-missing-notice:
    background: '{colors.warning} @ 14%'
    border: '1px solid {colors.warning} @ 40%'
    radius: '{rounded.lg}'
  empty-state:
    border: '1px dashed border'
    radius: '{rounded.xl}'
    padding: '64px 16px'
  toast:
    background: 'popover'
    border: '1px solid border'
    radius: '{rounded.lg}'
    shadow: 'shadow-xl'
---

## Brand & Style

Lorekeeper is a campaign companion that *remembers your world*. The marketing site calls its look "illuminated manuscript meets terminal": Cinzel capitals, gold foil on dark stone, and parchment as an object rather than a surface. Inside the app the same idea is carried by the **genre themes**. A GM picks a world (dungeon stone, wizard's study, pirate logbook, druid grove, neon street, or plain Parchment) and the whole interface takes on that world's palette, radius and type.

This expansion adds a living World Model, live play tools and player-facing surfaces. The brand rule for all of it: **new screens must look like they were always there.** The document specifies only the delta:

- six semantic hues the themes lack;
- type roles for reading at the table;
- the new components.

Everything else inherits from `themes/*.ts`, `index.css`, `tailwind.config.ts` and `components/ui`. Restyling the existing primitives is against the brand discipline.

The posture is a **trustworthy archivist**, not an oracle. Every AI-made thing on screen looks provisional until a GM approves it (dashed, tinted, labelled). Every fact shows where it came from, and every hidden thing looks hidden. The existing "Edit freely — nothing's saved yet" voice of the review panel is the emotional baseline: calm, unhurried and honest about what the machine did.

The site's six built-in themes are the contract. Custom themes (`lorekeeper-custom-themes` in localStorage) may omit the new tokens. In that case ThemeContext falls back to the dnd values for dark themes, or to the light values when the custom background has lightness above 50%.

## Colors

The base palette is inherited per theme and never restated here. Pages use only `bg-card`, `border-border`, `text-muted-foreground`, `bg-primary/5` and the like (brownfield §8). The expansion adds six **semantic tokens**. Each one is defined for every built-in theme (frontmatter), and each passes 4.5:1 as text on that theme's `card`, its `background` and its own 14% wash. They exist because new features have to say *safe*, *careful*, *hidden* and *live*, and the themes only have `primary`, `accent` and `destructive`, whose meaning changes from theme to theme.

- **Success (`{colors.success}`):** approved proposals, a "captions keeping up" lag, a finished Job, an alive status. It is never decoration.
- **Warning (`{colors.warning}`):** Continuity Flags, items in the Review Checklist that need attention, the backlog banner, the "Not from this NPC's memories" label, the missing status and the model-missing notice. Warning means "look before you trust this", not "error".
- **Info (`{colors.info}`):** Private visibility and the **View-as-Player preview banner**. Info is the "someone else's eyes" hue.
- **GM (`{colors.gm}`):** GM-only visibility, Secret fields, GM-only Pins and graph nodes. It means *players cannot see this*. Each theme's GM hue sits clear of that theme's `primary`: lilac on gold (dnd, highseas), orchid on purple (arcane), violet on green (forest), violet on cyan (cyberpunk), plum on navy (light).
- **Live (`{colors.live}`):** only the recording indicator and the Live Session "REC" state. It is never used for errors, so "recording" and "broken" don't look alike.
- **Danger (`{colors.danger}`):** readable destructive *text and icons*: failed Jobs, error lines, delete confirmations. The existing `destructive` token stays for fills (buttons, `bg-destructive/10`). Its dark-theme values (lightness 30–35%) fail AA as text, so new UI never sets `text-destructive` on a dark theme.
- **Foil (`{colors.foil-start}` → `{colors.foil-mid}` → `{colors.foil-end}`):** the site's gold-foil gradient, used *only* on an earned Achievement ring and a new Milestone card's title rule. It is the one place the marketing brand shows up in the app.

Contrast notes:

- Inherited Arcane `primary` on `card` measures 3.84:1, so it is fine for fills and large text, but new small primary-coloured text in Arcane uses `foreground`.
- Light theme `muted-foreground` on white is 4.75:1, so it passes but has no margin. Don't use it under 12px.
- About 50 hardcoded `green-*`, `amber-*` and `red-*` Tailwind classes in today's code are debt. New UI uses the tokens, and migrating the old uses is optional.

Encoding rule: **colour never carries meaning alone.** Every semantic colour comes with an icon and a word (a lock and "GM only", a skull and "Deceased", a dot and "REC").

## Typography

Families always come from `var(--font-heading)` and `var(--font-body)`, so Cinzel stays the wordmark and heading face in dnd and arcane, and each other theme keeps its own. The ramp mirrors what pages already do: `PageHeader` is `{typography.page-title}`, the uppercase widest-tracked section heads are `{typography.section-label}`, and body is the 1.05rem / 1.65 set in `index.css`.

New roles:

- **`{typography.entity-title}`:** the name at the top of an Entity wiki page. It is the one place the heading face appears at a large size inside the app, giving it a book-chapter feel. It drops to `entity-title-mobile` below `md`.
- **`{typography.quote}`** in italic: Mention quotes and the two sides of a Continuity Flag. A quote is always the journal's own words, so it reads as quoted.
- **`{typography.mono}`:** timestamps, caption lag, Job ETAs and counts that update in place. Tabular figures stop the numbers jittering.
- **`{typography.caption-live}`** (20px): Live Session captions in normal view, readable at arm's length on a tablet.
- **`{typography.caption-table}`** (36px) and **`{typography.recap-table}`** (32px): **Table view**, readable from across a table at about 1.5–2 m on a 10–13" screen. `[ASSUMPTION: sizes from distance rules of thumb; verify with a real table test]`
- **Chronicle export:** `{typography.chronicle-body}` in the bundled OFL book serif, with chapter heads in Cinzel (OFL). The PDF and EPUB carry the brand in its print form, whatever theme the GM uses on screen.

The cyberpunk theme's monospace body is kept in captions. Courier at 36px is legible, and changing a GM's chosen world font is a brand violation.

## Layout & Spacing

The Tailwind 4-px scale is inherited. Page shell: `max-w-5xl mx-auto px-4` (`{spacing.page-max}`, `{spacing.gutter-mobile}`), as on Dashboard and Analytics. Reading surfaces (journal, recap text) use `{spacing.reading-max}`.

| Surface | Layout |
|---|---|
| World hub | Page shell. A type filter row (chips) above a responsive card grid (`grid-cols-1 sm:grid-cols-2 lg:grid-cols-3`). Web and Maps are tabs of the hub and run full-bleed inside the shell. |
| Entity wiki page | `md:grid-cols-[1fr_280px]`: main column for Overview, Relationships, Mentions and History; a side rail for status, visibility, aliases, pins, "Talk to" and actions. A single column below `md`, with the rail moving under the header. |
| Review Checklist | Wide SlideOver (`{spacing.slideover-wide}`), full-screen below `md`, with a sticky action footer. |
| Relationship web | Canvas fills the tab's height (`calc(100dvh - 3.5rem - header)`), a floating toolbar sits top-left, and the panel opens in the standard SlideOver. |
| Live Session | **Leaves the page shell** and runs full width. Tablet landscape / `lg`: a two-column grid, captions `1fr` and a 360px right rail for lookup and Rolling Recap. Phone and tablet portrait: captions with a bottom tab bar (Captions · Lookup · Recap). Table view: one column, chrome hidden. |
| Player Portal | Mobile-first single column at 375px (FR-40). `md` and up: two columns, story on the left and character plus recap on the right. |
| Map viewer | The map fills the tab, a Pin list drawer sits on the right (`lg`) or a bottom sheet (phone), and the placement bar is pinned to the top of the map. |

Touch targets are at least `{spacing.tap-target}`. Live Session and Table view use `{spacing.tap-target-table}`, because hands at the table are holding dice.

## Elevation & Depth

Inherited: cards are flat with `border-border`. Dropdowns use `shadow-xl`, and the SlideOver uses `shadow-2xl` over a `bg-black/40` backdrop. New rules:

- The Job tray and the Entity quick card (Live Session lookup, graph hover) are popovers with `shadow-xl`, the same as the existing nav dropdown.
- The View-as-Player banner sits *above* the nav (z 60) with no shadow. It is a band, not a floating object.
- Map Pins have a 1px `background`-coloured outline so they separate from any map art without relying on shadow.
- Table view has no shadows and no translucency. It must hold up under bright room light and on low-end tablets.
- No glassmorphism beyond the nav's existing `backdrop-blur-sm`.

## Shapes

The radius is the theme's (`{rounded.lg}` = `--radius`, from 0 in cyberpunk to 0.5rem in light). New components never hardcode a radius. Pills (`{rounded.full}`) are reserved for **badges and chips**: visibility, status, role, Entity chips and the "Not from…" labels. This matches the existing `Badge`. Shape also encodes meaning where colour can't:

- **Graph node shape = Entity Type:** circle for Character, rounded square for Location, hexagon for Faction, diamond for Item. A lucide glyph sits inside each.
- **Dashed outline = not settled or not public:** pending AI proposals before approval, GM-only nodes, Pins and Secret fields, ended Relationships, and pending caption chunks.
- **Teardrop = Map Pin.** A GM-only Pin is the same teardrop with a dashed `{colors.gm}` outline and a hollow fill.

## Components

Inherited unchanged: `Button` (all variants), `Card`, `Badge`, `Input`, `Textarea`, `SlideOver`, `PageHeader`, `NarrativeReviewPanel`, `ModelReadyBanner`, `CampaignSelector` and the nav dropdown. Lucide is the icon set. The new components follow; the behaviour of each is in EXPERIENCE.md › Component Patterns.

**Shared spoiler-safety set**
- **VisibilityBadge:** a pill with an icon and a word: `visibility-badge-party` (Eye, "Party", neutral outline), `visibility-badge-gm` (Lock, "GM only", gm wash) or `visibility-badge-private` (UserRound, "Private", info wash). For GMs, the badge is also a button with a chevron. It is never shown to Players, apart from "Private" or "Shared" on their own journal entries.
- **SecretField:** wraps a GM-only field inside a Party record. It has a dashed gm border, a 6% gm wash and a lock label on the field's label row ("GM notes · GM only").
- **PreviewBanner:** a full-width band in `{colors.info}` above the nav. It reads "Viewing as Player · You're seeing exactly what players see." with an "Exit preview" button (outline variant, inverted).
- **RoleBadge:** a muted pill (GM, Co-GM or Player) beside the campaign name in the CampaignSwitcher.

**Jobs**
- **JobTrayButton:** a lucide Hourglass in a 36px ghost button with a primary count badge, plus a spinning ring segment while any Job runs (static under reduced motion).
- **JobRow:** a card row with the Job title, a stage line in `{typography.meta}`, a 4px determinate bar (primary fill on muted) or the text "Queued · 1 ahead", an ETA in `{typography.mono}`, and an action (View, Retry, Download). A failed row adds a danger icon and the reason.

**World Model**
- **ReviewChecklist (`EntityDiffReviewPanel`):** keeps NarrativeReviewPanel's shell (`border-primary/30 bg-primary/5`, the section-label title, "Edit freely — nothing's applied yet"). Group headers (New · Changed · Quest progress) are section labels with counts. A sticky footer carries the tallies and primary actions.
- **ProposalItem:** a card. Line 1 has the type icon, the Entity name in bold, the field, and the diff `{components.diff-old}` → `{components.diff-new}`. Line 2 has the `mention-quote` and the source entry link. On the right are the VisibilityBadge (editable) and three icon buttons (Approve ✓, Reject ✕, Edit ✎) with text labels from `md` up. The four states render as follows: pending is plain; edited has a primary left rule and an "Edited" chip; approved has a success check fill and a success left rule; rejected is at 55% opacity with the diff struck through. `proposal-item-attention` adds a warning left rule and a reason chip ("Possible duplicate", "Stale", "Contradicts canon").
- **Post-save card:** a `card` row under the saved entry with "Saved." in success, then one line per stage (stage text, a 4px bar like JobRow, an ETA in mono). When results are ready it becomes a primary-wash row with the counts and a primary "Review" button.
- **Reviews queue row:** a card row with the entry title in the heading face, date in meta, pending and flag counts as chips, and an outline "Open" button.
- **Merge dialog:** SlideOver content with two EntityCards side by side (stacked below `sm`), a survivor radio on each, a preview list of the combined aliases and counts, and a warning-wash note when Visibility differs.
- **MatchPicker:** a radio list inside an item: up to three candidate Entities (name, type, one-line description, alias count) plus "New entity". The chosen row gets a primary ring.
- **EntityCard:** a compact card with the type icon, name, StatusBadge, a one-line description and the latest two Mentions. It is used for lookup, graph hover and map pin popovers.
- **EntityPage header:** an `entity-title`, aliases as muted chips, StatusBadge with its source citation ("since *The Bell Tower*"), VisibilityBadge, and an overflow menu.
- **StatusBadge:** a pill. Alive is a success dot; deceased is muted with Skull and the word "Deceased", which also renders the entity name in muted colour in lists; missing is warning; unknown is muted.
- **HistoryList:** a vertical rule with event rows (date in mono, change diff, source link, approver). Canon Notes appear as `canon-note` blocks with a Feather icon and a "Retcon" or "Canon ruling" label. A revert link sits on each row.
- **MentionList:** quote blocks (`mention-quote`), newest first, each linking to its entry. Suggested Mentions are dashed with Confirm and Remove buttons (GM only).

**Canon guard**
- **ContinuityFlag:** a warning-wash card with a TriangleAlert icon. The header reads "Continuity flag · Mira". The body has two quote columns, "This entry" and "Canon (*The Bell Tower*, 12 Mar)", which stack below `sm`. The footer has the actions and a `meta` line: "Canon guard is best-effort. A missing flag doesn't prove the entry is consistent."
- **CanonNoteForm:** inline in the flag card. A required reason textarea, a checkbox "Also propose: Mira · deceased → alive", and a primary "Save Canon Note" button.

**Relationship web**
- **GraphCanvas:** nodes per `graph-node`, edges per `graph-edge`, arrowheads on directed edges, and labels shown at zoom ≥ 1 or on focus and hover.
- **GraphToolbar:** search input, filter chips (Entity Type, Relationship type, Faction), a "List view" toggle, zoom ±, and "Fit".
- **GraphListView:** a table (Entity · Type · Status · Relationships) with expandable rows listing each edge as "→ enemy of → Grukk".
- **NodeLegend:** a collapsible key that shows shape → type and line style → meaning.

**Maps**
- **MapViewer** with **MapPin** (`map-pin`, `map-pin-gm`) and a selected state (2px ring plus label tag).
- **PlacementBar:** a primary-wash bar pinned to the top of the map: "Placing *Sunken Archive* — click the map or press Enter to drop at the crosshair · Esc to cancel".
- **PinEditor:** a popover with label, Location combobox ("Create Location…" as the last option), linked entries, and VisibilityBadge.
- **PinList:** a list of Pin rows (icon, label, linked Location, visibility).

**Live Session**
- **LiveStatusBar:** `live-status-bar` with a REC dot plus the word "REC", elapsed time in mono, the **LagMeter**, Pause, End, and a Table-view toggle.
- **LagMeter:** a mono text "Captions ≈ 18 s behind" plus a three-segment pipeline glyph: Listening (a ring filling over the chunk window), Transcribing (a count) and Shown. It turns warning when lag exceeds the chunk window.
- **CaptionChunk:** a row with a mono time range on the left and `caption-live` text. Recognised Entity names are underlined with a dotted primary underline.
- **CaptionPending:** a dashed placeholder row reading "Transcribing 0:42–1:02…".
- **BacklogBanner:** a warning wash.
- **RollingRecapCard:** a card with the section label "Rolling recap", a `meta` line "From the transcript, not your journal · Updated 40 s ago · covers to 1:02:10", and a body.
- **QuickLookup:** a search input above an EntityCard.

**Recaps, NPC chat, keepsakes**
- **RecapPlayer:** a card with Narrator chip, play/pause (44px), scrubber, speed (0.75×–1.5×), download, and a "Table play" button. The text sits below with the current sentence highlighted (`active-sentence`). Text is always visible (NFR-10).
- **NpcChatHeader:** initials avatar, name in the heading face, StatusBadge, a KnowledgeScope chip ("Knows 14 entries · 2 hidden") and a VisibilityBadge ("Private"). Messages per `npc-message`, with the NPC's name above each reply as a section label.
- **NotFromMemoriesLabel:** a warning pill. The existing "not from your journal" label is restyled to match only in new surfaces.
- **PlayerJournalComposer:** title Input, Textarea (the existing primitives), and a SegmentedControl "Private · Share with party" with the VisibilityBadge shown next to it.
- **Field visibility hint:** `meta` helper text with an Eye icon under a focused Party field; GM-only fields use the SecretField label instead.
- **KnowledgeEditor:** a list of entry and field rows, each with a three-state segmented control: Mention (auto) · Granted · Hidden.
- **ChronicleExportPanel:** an edition segmented control, format checkboxes, include toggles (GM-only toggles carry the gm badge), a cover preview thumbnail, and an export button.
- **MilestoneCard:** a card with a foil top rule, a `stat-display` title ("10th Session") and a date. **AchievementBadge:** a 56px circle with a lucide glyph, a foil ring when earned and a muted outline when not yet earned (shown only to users who opted in).
- **StatTile, WeeklyBarChart, TagRankList:** inherited from AnalyticsPage and reused, not restyled.

**System**
- **ModelMissingNotice:** the inline per-feature variant of ModelReadyBanner. It uses the warning wash with no emoji (the existing banner's "⚠" glyph is replaced by a lucide TriangleAlert in new uses).
- **EmptyState:** a dashed `{rounded.xl}` box, a lucide icon at 40px in muted, a one-line title and one action. It replaces the emoji-headline pattern (📊, 🎙️) in new pages.
- **Toast:** popover surface, bottom-right on `md` and up, bottom-centre on phones. It holds one line of text plus an optional action ("Review", "Undo").
- **SegmentedControl, Tabs, Combobox:** new primitives in `components/ui`, cva-styled like `button.tsx`. The active segment is `bg-muted text-foreground font-medium`, matching the existing campaign tab buttons.

## Do's and Don'ts

| Do | Don't |
|---|---|
| Use theme tokens and the six new semantic tokens. | Hardcode `green-500`, `amber-500` or hex in new components. |
| Pair every semantic colour with an icon and a word. | Signal GM-only, deceased or "needs attention" with colour alone. |
| Keep the heading face for titles, section labels and NPC names. | Set body copy or captions in Cinzel. |
| Use dashed outlines for provisional (AI-proposed) and hidden things. | Use dashed outlines decoratively. |
| Use `{colors.live}` only for recording. | Use `live` for errors, or `danger` for recording. |
| Use foil only for an earned Achievement or a new Milestone. | Use foil on buttons, headers or nav. |
| Use `{colors.danger}` for error text, `destructive` for fills. | Use `text-destructive` on dark themes (fails AA). |
| Use lucide icons in new UI. | Use emoji as UI icons in new UI (✨, 📊, ⚠). |
| Give Table view its own type ramp. | Use browser zoom as the "big text" mode. |
| Make the preview banner visible on every screen of preview. | Show "View as Player" as a toggle that can be forgotten. |
