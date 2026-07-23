# Status board data model

Every board is **data + a shared renderer**:

- `<slug>/board.json` — the board's data (this schema).
- `<slug>/index.html` — a thin shell that loads the shared renderer and points it at `board.json`.
- `_assets/board.css` + `_assets/board.js` — the shared renderer (same for every board).

The renderer reads `board.json`, iterates `sections` in order, and renders each by its `kind`. Adding a board = a folder with `board.json` + the shell; updating = rewrite `board.json` and deploy.

## Top level

```json
{
  "title": "Demo",
  "eyebrow": "Demo Office",
  "stamp": "Updated 2026-07-07 — one-line status line",
  "links": [ { "label": "History →", "href": "history/" } ],
  "staleAfterDays": 7,
  "tabs": [ { "id": "now", "label": "Now", "icon": "⚡",
              "sections": ["CI — running now", "Builds"] } ],
  "sections": [ /* ordered array of section objects, each with a "kind" */ ]
}
```

`title` sets `<title>` and the H1. `eyebrow` is the small uppercase kicker. `stamp` is the mono sub-line under the title. `links` (optional) is an array of `{ label, href }` rendered as a header nav row — e.g. a detail page's "← back" or "all history". A board also auto-shows a **History →** link when a sibling `history/board.json` exists.

**Tile links** — a `stats` item or a `compare` column item may add `"href"`, which makes the whole tile a link (rendered as an `<a>`, so it keyboard-focuses and middle-clicks normally). A number on a board is the start of a question — "6,591 passed, which ones?" — and the tile is where the reader's eye already is. `collect/test_detail.py` uses this to point the test tiles at a generated `<slug>/tests/` page and the CI-build tile at the run itself.

**Section headings** — any titled section may add `"icon"` (leading emoji), `"count"` (mono badge after the title), `"desc"` (grey suffix), and `"href"` (turns the title into a link, e.g. to a detail page). These are generic across kinds.

## Tabs (optional)

A board past a dozen sections reads better grouped than scrolled. `tabs` is an ordered array of `{ id, label, icon?, sections: [title, …] }`; the renderer draws a tab bar and puts each named section in that tab's panel. The open tab lives in the URL hash (`…/clauffice/#code`), so a tab is linkable and survives reload.

Two rules matter:

- **Sections are claimed by title, not by a key on the section.** Collectors call `upsert_section()`, which replaces a section wholesale by title — a grouping key stored on the section would be wiped on the next collector run. Board-level mapping means tabs cost collectors nothing.
- **Anything no tab claims renders above the tab bar and stays visible on every tab.** That's where the untitled hero row and banner go (no title to key on), and it makes the failure mode safe: a section a tab forgot shows up rather than vanishing into a tab nobody opens.

A tab whose sections are all absent is dropped rather than drawn empty — a board may name a tab before its collector has ever seeded the section. Omit `tabs` entirely and the board renders as one flat column, exactly as before.

## Staleness (`asOf`)

A hand-written section may carry `"asOf": "2026-07-21"` — the date a human last verified it. The renderer shows a quiet `as of 2026-07-21` chip, and once the date is older than `staleAfterDays` (top level, default 7) the chip becomes a `⚠ 14d old` warning.

**Only put `asOf` on sections a human writes.** A collector-owned section is refreshed on every push and cannot drift, so a stamp there would be a claim about hand-authorship that stops being true the moment it ages. `collect/loc.py` deletes any `asOf` it finds on a chart it has taken over, for exactly this reason.

## Section kinds

Each section is `{ "kind": "...", ... }`. Supported kinds:

### `stats` — the tile row
```json
{ "kind": "stats", "items": [ { "n": "1196", "label": "Tests green", "tone": "go" } ] }
```
`tone` ∈ `go | you | srv | wip | done | err` (green / amber / blue / indigo / grey / red). `n` is a string (may be "#8", "CI", etc.). `err` is for genuine failure states (e.g. e2e tests failing) — an `err` stat tile also gets a red border + tinted background so red never hides in a tile row.

### `banner` — a full-width note
```json
{ "kind": "banner", "text": "…", "tone": "none" }
```

### `barchart` — horizontal magnitude bars
```json
{ "kind": "barchart", "title": "Codebase", "desc": "lines of code by area",
  "legend": [ { "label": "hand-written", "fill": "code" }, { "label": "generated", "fill": "gen" } ],
  "note": "This week: 99 commits …",
  "series": [ { "label": "App source", "value": 40362, "fill": "code" } ] }
```
Bar widths are computed by the renderer as `value / max(values) * 100%`. `fill` ∈ `code | gen`.

### `pie` — donut chart (share of a whole)
```json
{ "kind": "pie", "title": "Lines by repo", "note": "…optional…",
  "slices": [ { "label": "App source", "value": 40362, "tone": "go" } ] }
```
Rendered as an inline SVG donut (no dependency, no innerHTML) with a legend listing each slice's label, value, and percentage of the total. `tone` ∈ `go | you | srv | wip | done` (same palette as `stats`/pills). A single slice renders as a full ring; empty `slices` or an all-zero total renders "No data." instead of a chart.

### `table`
```json
{ "kind": "table", "title": "Proposals", "count": "6 tracked",
  "columns": ["Proposal", "Phase", "Phoenix scope", "Blocked on", "Status"],
  "rows": [ ["Businesses", "Features shipped", "…", "…", { "pill": "Resolved", "tone": "done" }] ] }
```
A cell is a string, or `{ "pill": "text", "tone": "…" }` to render a pill.

### `cards` — id / question / note / pill rows
```json
{ "kind": "cards", "title": "Shipped this week", "count": "9 tracked", "desc": "…",
  "items": [ { "id": "#2", "q": "Title", "note": "…", "meta": "Owner: Jimmy", "href": "https://…(optional, links the title)", "pill": { "text": "Resolved", "tone": "done" } } ] }
```
All item fields optional except `q`.

### `console` — terminal-styled log lines (CI runs)
```json
{ "kind": "console", "icon": "⚙️", "title": "CI — recent runs", "count": "8 runs",
  "lines": [ { "status": "success", "tone": "go", "text": "Phoenix · dev", "meta": "· push",
               "ts": "2026-07-13T19:03:04Z", "href": "https://github.com/…/runs/123",
               "cmd": "gh run watch -R owner/repo" } ] }
```
`tone` colors the dot. `ts` (UTC ISO) localizes to the viewer's timezone and prefixes `meta`.
`href` (optional) links the line text — e.g. straight to the Actions run. `cmd` (optional)
renders a copy-to-clipboard chip after the text — e.g. the `gh run watch` line that follows
each repo's runs.

### `split` — two columns of checklist items
```json
{ "kind": "split", "title": "API consumption",
  "columns": [
    { "h3": "Consumed", "style": "check", "items": [ { "text": "Roles — RolesView + gating" } ] },
    { "h3": "Pending server work", "style": "pend", "items": [ { "text": "owing_amount on BaseRow", "who": "Milo — …" } ] }
  ] }
```
`style` ∈ `check` (✓) | `pend` (◯).

### `console` — a log / feed of tone-dotted lines
```json
{ "kind": "console", "icon": "🕘", "title": "CI — recent runs", "count": "7 runs", "desc": "…",
  "href": "/clauffice/history/",
  "lines": [ { "status": "success", "tone": "go", "text": "Phoenix · dev",
               "ts": "2026-07-13T20:05:42Z", "meta": "· pull_request" } ] }
```
Each line renders a tone-colored dot + `status` word + `text`, with an optional right-aligned meta. `tone` uses the palette above. `ts` is a **UTC ISO-8601** instant (`…Z`) that the renderer localizes to the *viewer's* timezone; `meta` is any extra suffix, shown after the localized time. **Collectors must emit `ts`, never a pre-formatted local/UTC string** — otherwise every viewer sees the collector machine's clock. (Legacy field aliases the renderer still accepts: `items` for `lines`, `q` for `text`, `note` for `meta`.) Used by the History boards and the CI-runs section.

## Collectible fields (for `collect` scripts)

Quantitative values a per-project collector refreshes live come from the repo:
- `stats` tiles whose `label` matches a known metric (e.g. "Tests green").
- Whole self-seeded `stats` sections matched by `title` (e.g. "Test results",
  "Tests by type") — collectors upsert these; hand edits will be overwritten.
- `barchart` `series[].value` and the chart `note`.
- `pie` `slices[].value` and the chart `note`.
- Lines-of-code charts of either kind, rebuilt wholesale by `collect/loc.py`
  from `ROOST_LOC_CONFIG` (bucket = a set of paths/extensions to count). A
  bucket whose repo isn't on the pushing machine keeps its previous value
  rather than reporting 0 — two machines write this site and they don't have
  the same clones.

Collectors patch these in place (match by section `kind` + `title`/label) and leave narrative sections (`table`, `cards`, `split`, `banner`) untouched. Tones/pills use the palette above; keep them stable so the renderer's CSS variables apply.
