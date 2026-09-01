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
  "sections": [ { "kind": "banner", "text": "An ordered array of section objects, each with a kind." } ]
}
```

`title` sets `<title>` and the H1. `eyebrow` is the small uppercase kicker. `stamp` is the mono sub-line under the title. `links` (optional) is an array of `{ label, href }` rendered as a header nav row — e.g. a detail page's "← back" or "all history". A board also auto-shows a **History →** link when a sibling `history/board.json` exists.

`staleAfterMinutes` (optional) arms the frozen-board banner: when the `board.json` file itself is older than this many minutes, the renderer shows a full-width warning that every age on the page is measured from a frozen snapshot. Set it a little above the board's refresh cadence (e.g. `60` for a 15-minute pipeline). Without it a stalled deploy reads as "nothing built for days" instead of "delivery is broken".

**The machine spec.** `bin/widgets.schema.json` is this document's enforceable half: one entry per kind, one entry per field, with a type and a severity for each. `bin/validate-board.py` walks it over every board in the deploy sweep, and `tests/test_widget_schema.py` holds the spec, the validator, the renderer's kind list, and every ```json example in this file to the same surface. A field added to the renderer is not done until it is in the spec.

**Tile links** — a `stats` item or a `compare` column item may add `"href"`, which makes the whole tile a link (rendered as an `<a>`, so it keyboard-focuses and middle-clicks normally). A number on a board is the start of a question — "6,591 passed, which ones?" — and the tile is where the reader's eye already is. `collect/test_detail.py` uses this to point the test tiles at a generated `<slug>/tests/` page and the CI-build tile at the run itself.

**Section headings** — any titled section may add `"icon"` (leading emoji), `"count"` (mono badge after the title), `"pill"` (a colored verdict badge — same `{pill, tone}` shape as a table/cards cell, e.g. `{"pill": "all green", "tone": "go"}`), `"desc"` (grey suffix), and `"href"` (turns the title into a link, e.g. to a detail page). These are generic across kinds.

**Collapsible sections** — any section may add `"collapsible": true` to render inside a native `<details>`/`<summary>` disclosure instead of a plain heading (dependency-free — the browser's own widget, restyled). `"collapsed": true` starts it closed; omitted or `false` starts it open. The heading (title/count/pill/desc, above) becomes the `<summary>` line, so a collapsed section states its verdict just as plainly as an expanded one — only the rows underneath are hidden. `collect/repo_stats.py`'s "E2E suites" table uses this: collapsed by default on an all-green run, auto-expanded when any suite failed (collapsed-green, expanded-red) — a clean run doesn't need the click, a red one shouldn't need one either.

**Stack marks (`logo`)** — `swift | ts | js`, an inline brand mark drawn (never fetched) for the stack a thing belongs to. Valid on a **section heading**, a **compare column**, a **tab**, and a single **console line**. Everywhere it appears it takes the place of `icon` rather than sitting beside it, and an unrecognised name falls back to the icon.

Most sections on a multi-repo board are about *one* repo. Until they say so, a reader has no way to tell which — a test-results row reads as the board's tests when it is one repo's. On a console the mark goes per line, so one merged chronological feed can still say whose each run is, which beats splitting it into one console per repo.

A collector rebuilds its section from data every push, so `logo` is carried over from the section it replaces (`lib.PRESERVED_SECTION_KEYS`) — otherwise setting one by hand would silently un-do itself within the hour.

## Tabs (optional)

A board past a dozen sections reads better grouped than scrolled. `tabs` is an ordered array of `{ id, label, icon?, logo?, sections: [title, …] }`; the renderer draws a tab bar and puts each named section in that tab's panel. The open tab lives in the URL hash (`…/clauffice/#code`), so a tab is linkable and survives reload.

Two rules matter:

- **A tab's sections render in *board* order, not in the order the tab lists them.** The tab list is a set of claims; `sections` is the running order. Reordering a tab means reordering the board array.
- **Sections are claimed by title, not by a key on the section.** Collectors call `upsert_section()`, which replaces a section wholesale by title — a grouping key stored on the section would be wiped on the next collector run. Board-level mapping means tabs cost collectors nothing.
- **Anything no tab claims renders above the tab bar and stays visible on every tab.** That's where the untitled hero row and banner go (no title to key on), and it makes the failure mode safe: a section a tab forgot shows up rather than vanishing into a tab nobody opens.

A tab whose sections are all absent is dropped rather than drawn empty — a board may name a tab before its collector has ever seeded the section. Omit `tabs` entirely and the board renders as one flat column, exactly as before.

## Staleness (`asOf`)

A hand-written section may carry `"asOf": "2026-07-21"` — the date a human last verified it. The renderer shows a quiet `as of 2026-07-21` chip, and once the date is older than `staleAfterDays` (top level, default 7) the chip becomes a `⚠ 14d old` warning.

**Only put `asOf` on sections a human writes.** A collector-owned section is refreshed on every push and cannot drift, so a stamp there would be a claim about hand-authorship that stops being true the moment it ages. `collect/loc.py` deletes any `asOf` it finds on a chart it has taken over, for exactly this reason.

## Per-board `config.json` (optional)

Everything in `board.json` is derived data: collectors rewrite it wholesale every cycle, and the site repo's rule is that the remote always wins. A hand edit there does not survive — the clauffice `staleAfterMinutes` was set by hand on 2026-08-20 and steamrolled by the next scheduled run. Settings that must outlive regeneration live in a sibling `config.json`, which no collector touches:

```json
{
  "staleAfterMinutes": 60,
  "hide": ["A section title"],
  "order": ["First", "Second"]
}
```

The renderer fetches it on the board's own 60s refresh cycle and applies it over the data, so an edit lands within a minute. A missing, empty, or unparseable config costs nothing — the board renders exactly as `board.json` says.

- `staleAfterMinutes` arms the frozen-board banner (see above) and wins over any value in `board.json`.
- `hide` drops sections by **title** — the same addressing tabs use, for the same reason: collectors replace sections wholesale by title, so any key stored on the section would be wiped within the hour. An untitled section (the hero row, the banner) cannot be hidden, so the failure mode stays "it shows up".
- `order` rearranges only the sections it names, within the slots those sections already occupy. An unlisted section — including one a new collector seeds tomorrow — keeps its place instead of being shoved to one end.

`bin/validate-board.py` visits each board's sibling `config.json` in the same sweep and warns (never fails) on a typo'd key, a wrong type, or a title no section carries. The renderer ignores all of those silently, which is the safe failure and also the one this sweep exists to name.

**The viewer's layer.** Every board also carries a ⚙ **sections** control in its header nav: a checkbox per titled section, so one viewer can hide sections they never read — or reveal one the config hides. These overrides live in that browser's `localStorage`, keyed by board path, and are never canonical: a private window, cleared site data, or another device comes up on the board's declared default. The gear shows `⚙ sections*` while overrides are active, and the panel offers a reset back to the default. Only disagreement with the default is stored, so a viewer who toggles back to the declared state carries no entry at all.

## Section kinds

Each section is `{ "kind": "...", ... }`. Supported kinds:

### `stats` — the tile row
```json
{ "kind": "stats", "items": [ { "n": "1196", "label": "Tests green", "tone": "go" } ] }
```
`tone` ∈ `go | you | srv | wip | done | err` (green / amber / blue / indigo / grey / red). `n` is a string (may be "#8", "CI", etc.). `err` is for genuine failure states (e.g. e2e tests failing) — an `err` stat tile also gets a red border + tinted background so red never hides in a tile row.

**A tile has three lines, and they answer three different questions.** `n` is the headline: the answer the reader came for. `label` says what the headline is an answer *about*. `meta` (optional) is the provenance line: the evidence the headline was read from, set small, faint and monospaced because it is the footnote, not the claim.

```json
{ "n": "✓", "label": "CI build · dev", "meta": "132dab0",
  "since": "2026-08-20T19:05:29Z", "tone": "go", "href": "…/runs/32406777042" }
```

Renders as **✓** / `CI build · dev` / `132dab0 · 4d ago`. Reach for `meta` when a number is only trustworthy if you know where it came from — a verdict and the commit it was measured at, a rate and its sample size. The alternative is a second tile beside the first, and two tiles can drift apart with no way for a reader to tell which one to believe.

**`since` is a timestamp, never a rendered age.** The renderer computes "4d ago" when the page draws, so the age decays honestly while a board sits open on a wall. A collector that writes "4d ago" into `n` publishes a string that is true for as long as it takes to push the file and wrong forever after. The age attaches to whatever the tile names last: it joins `meta` when there is one, because the age dates the *commit*, not the tick beside it.

### `compare` — the same tiles, side by side per subject
```json
{ "kind": "compare", "title": "Phoenix ⟷ MWServer", "columns": [
  { "title": "Phoenix — client", "logo": "ts",
    "items": [ { "n": "6605", "label": "Tests green", "tone": "go" } ] },
  { "title": "MWServer — server", "logo": "swift",
    "items": [ { "n": "1196", "label": "Tests green", "tone": "go" } ] } ] }
```
Each column is a `stats` row under its own heading. Items take the same `n`/`label`/`meta`/`since`/`tone`/`href` as `stats`.

**A compare section is read across, not down.** "Is the client's coverage better than the server's" is answered by two tiles at the same height in two columns. Nothing holds them at that height on its own: every tile is written by a different collector, each appends when its tile is new, so a column's order is otherwise a fossil of the order its collectors first happened to run in — and two columns fossilise differently.

**`order`** fixes that. It is a list of label prefixes on the section, applied to every column at save time (`lib.apply_column_order`, called from `lib.save_board`, so it holds whichever collector wrote last):

```json
{ "kind": "compare", "title": "Phoenix ⟷ MWServer",
  "order": ["CI build", "Build green", "Build time", "Tests green",
            "Coverage", "Test files", "Added"],
  "columns": [
    { "title": "Phoenix — client", "logo": "ts",
      "items": [ { "n": "7525", "label": "Tests green", "tone": "go" } ] },
    { "title": "MWServer — server", "logo": "swift",
      "items": [ { "n": "618", "label": "Tests green", "tone": "go" } ] } ] }
```

Prefixes, so `"CI build"` claims `CI build · dev` and `CI build · master` and holds them in the order their collector wrote them (trunk preference: the working trunk above the stable one). A label no prefix claims keeps its relative position at the *end*, so a new collector adds a tile without editing this list. A section that declares no `order` is left exactly as it is.

Put the metrics both sides can answer at the top in the same order, and let each side's one-sided tiles fall to the bottom. A tile only one column can ever carry ("Blocked on server") is a fact about the *seam* between the two subjects rather than about either one, and it reads that way when it sits below the rows that pair up.

A column may carry `"logo"` — a brand mark for the stack it stands for, drawn inline (`swift | ts | js`). It replaces `"icon"` (an emoji) when both are set, and an unrecognised name falls back to the icon rather than leaving a gap. Marks are drawn, never fetched: a board served behind a gate that blocks outbound requests would render a remote image as a broken box.

**Collectors must scope their writes to a column** (`lib.set_compare_tile(column=…)`, `lib.upsert_compare_tile`). An unscoped write matches the first tile with that label in *any* column, which is how one repo's number ends up rendered under another repo's heading.

### `banner` — a full-width note
```json
{ "kind": "banner", "text": "…", "tone": "none" }
```

**A banner is a lede, not a write-up.** It renders as one flat `<div>` — no heading, no rows, no pills, nothing for an eye to land on. Every other kind gives a reader a place to stop; this one doesn't, so it is the only kind that can quietly grow into a wall. The board's own numbers are the argument: a banner that reached 3,100 characters and fourteen sentences restated the coverage figure the hero tiles already showed, and by then the two disagreed — the prose said 93%, the collected tile said 92%.

The rule, enforced as a **warning** by `bin/validate-board.py` (never a hard fail — a board must always be able to deploy):

- **≤ ~700 characters and ≤ 5 sentences** of hand-written prose. Past that you are writing a section, not a lede.
- **Say what the day means, not what it measured.** Any number a collector already writes — test counts, coverage, SHAs, PR counts — is on a tile above the banner. Restating it adds a second source of truth that ages at a different rate than the first.
- **Detail goes in `cards`.** One finding per item: `q` is the headline a reader scans, `note` is the paragraph they read only if the headline earned it, `pill` is the verdict they can skim down a column. That is the same prose, made scannable by structure rather than by editing.
- **Use `\n\n`.** The renderer is `white-space: pre-line`, so paragraph breaks already work — nothing but the text itself is stopping them.

The check measures only the prose *above* the `── shipped ·` marker. Everything below it is regenerated by `bin/collect/narrative.py` on every run, is line-broken already, and is not the author's to keep short. Note that a long shipped block inside a banner is usually redundant anyway: `collect/shipped_week.py` renders the same merged PRs as a proper `cards` section, with ids, dates and pills.

### `barchart` — horizontal magnitude bars
```json
{ "kind": "barchart", "title": "Codebase", "desc": "lines of code by area",
  "legend": [ { "label": "hand-written", "fill": "code" }, { "label": "generated", "fill": "gen" } ],
  "note": "This week: 99 commits …",
  "series": [ { "label": "App source", "value": 40362, "fill": "code" } ] }
```
Bar widths are computed by the renderer as `value / max(values) * 100%`.

`fill` ∈ `code | gen` (the structural pair) **or** any `stats`/pie tone — `go | you | srv | wip | done | err`. Use a tone when a bar means an *outcome* rather than a category, so a chart of passed/failed builds reads in the same green and amber as the tiles above it.

A series entry may add `"valueText"` — what to print at the end of the bar, when the raw number is not how a reader wants to see it:
```json
{ "label": "fc44010", "value": 5.6, "valueText": "5m36s", "fill": "go" }
```
The bar's *length* still comes from `value`, so the series stays measurable and comparable; only the printed label changes. Formatting the number into `value` itself instead would make it non-numeric and draw a zero-width bar.

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
{ "kind": "console", "icon": "⚙️", "title": "CI — runs", "count": "144 runs", "scroll": 10,
  "lines": [ { "status": "success", "tone": "go", "text": "Phoenix · dev", "meta": "· push",
               "ts": "2026-07-13T19:03:04Z", "href": "https://github.com/…/runs/123",
               "cmd": "gh run watch -R owner/repo" } ] }
```
`tone` colors the dot. `ts` (UTC ISO) localizes to the viewer's timezone and prefixes `meta`.
`href` (optional) links the line text — e.g. straight to the Actions run. `cmd` (optional)
renders a copy-to-clipboard chip after the text — e.g. the `gh run watch` line that follows
each repo's runs.

`scroll` (optional, a row count) caps the block at that many rows and scrolls the rest, so a
console can carry a long record without pushing every section below it off the page. Omit it
and the block renders at full height, which is what every console without one keeps doing.
A console that scrolls should lead with its `cmd` chips rather than end with them: anything
after the rows is below the fold and cannot be found.

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
- A self-seeded `table` section titled "E2E suites" (`collect/repo_stats.py`,
  from CI's `test-report.json` additive `e2eSuites` array): one row per e2e
  spec file, failing suites sorted first and flagged with the same `err`/`go`
  pill tones the "Test results" tiles above it use. Absent on reports without
  the key — a board that never had one stays without it, and one that has it
  keeps its last-good run rather than clearing. Collapsible (see above):
  collapsed by default when every suite is green, auto-expanded when any
  suite failed.
- Lines-of-code charts of either kind, rebuilt wholesale by `collect/loc.py`
  from `ROOST_LOC_CONFIG` (bucket = a set of paths/extensions to count). A
  bucket whose repo isn't on the pushing machine keeps its previous value
  rather than reporting 0 — two machines write this site and they don't have
  the same clones.

Collectors patch these in place (match by section `kind` + `title`/label). A
`table`/`cards`/`split`/`banner` section is narrative — hand-authored and left
untouched — *unless* a collector explicitly self-seeds it by title, as above;
an unclaimed section of any kind is always safe from a collector rewrite.
Tones/pills use the palette above; keep them stable so the renderer's CSS
variables apply.
