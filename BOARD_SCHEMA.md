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
  "sections": [ /* ordered array of section objects, each with a "kind" */ ]
}
```

`title` sets `<title>` and the H1. `eyebrow` is the small uppercase kicker. `stamp` is the mono sub-line under the title. `links` (optional) is an array of `{ label, href }` rendered as a header nav row — e.g. a detail page's "← back" or "all history". A board also auto-shows a **History →** link when a sibling `history/board.json` exists.

**Section headings** — any titled section may add `"icon"` (leading emoji), `"count"` (mono badge after the title), `"desc"` (grey suffix), and `"href"` (turns the title into a link, e.g. to a detail page). These are generic across kinds.

## Section kinds

Each section is `{ "kind": "...", ... }`. Supported kinds:

### `stats` — the tile row
```json
{ "kind": "stats", "items": [ { "n": "1196", "label": "Tests green", "tone": "go" } ] }
```
`tone` ∈ `go | you | srv | wip | done` (green / amber / blue / indigo / grey). `n` is a string (may be "#8", "CI", etc.).

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
- `barchart` `series[].value` and the chart `note`.
- `pie` `slices[].value` and the chart `note`.

Collectors patch these in place (match by section `kind` + `title`/label) and leave narrative sections (`table`, `cards`, `split`, `banner`) untouched. Tones/pills use the palette above; keep them stable so the renderer's CSS variables apply.
