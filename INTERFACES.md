# How statusgen, roost, and a status site fit together

Three pieces cooperate to publish a status site. Each has one job and talks to
the others through a named contract — so any one can be swapped without the
others noticing.

```
   roost (driver)                 statusgen (library)              site (data)
 ┌────────────────┐            ┌──────────────────────┐        ┌──────────────┐
 │ roost status   │──runs────▶ │ bin/collect/*        │──write▶│ <slug>/      │
 │  · resolves     │           │  (fleet, history,    │        │   board.json │
 │    paths (rc)   │           │   repo_stats, …)     │        │ status.json  │
 │  · runs         │──sync────▶│ bin/sync-renderer.sh │──copy─▶│ _assets/     │
 │    collectors   │           │ renderer/board.{js,  │        │   board.{js, │
 │  · syncs        │           │  css}                │        │    css}      │
 │    renderer     │──gate────▶│ bin/validate-board.py│──check─│ */board.json │
 │  · validates    │           │ BOARD_SCHEMA.md      │        │ <slug>/      │
 │  · deploys      │           └──────────────────────┘        │   index.html │
 └────────────────┘                                            └──────────────┘
```

## Responsibilities

**statusgen — the library.** Standalone and board-agnostic; knows nothing about
any specific site.
- Owns the **board.json schema** ([BOARD_SCHEMA.md](BOARD_SCHEMA.md)) and its
  **validator** (`bin/validate-board.py`).
- Owns the **renderer** (`renderer/board.{js,css}`) and the tool that installs
  it into a site (`bin/sync-renderer.sh`, with content-hash cache-busting).
- Owns the **generic collectors** (`bin/collect/*`) that produce `board.json`
  from a data source: `repo_stats`, `ci_status`, `shipped_week`,
  `api_consumption`, and `history` (a site's git log → the History board).
- Owns **scaffolding** (`bin/new-site.sh`, `bin/new-board.sh`).

**roost — the driver.** The one place that knows *where things live and when to
run them*. `roost status` is the sole orchestration entry point
([bin/status.sh](../roost/bin/status.sh)):
1. run the collectors (fleet + `roost stats` + history),
2. `sync-renderer.sh` so the deployed renderer matches statusgen,
3. `validate-board.py` as a hard gate,
4. usage ledger (optional),
5. commit + deploy the site.

It also owns the one collector that is genuinely roost-specific,
`fleet-board.py` (live Dokku platform metrics over SSH).

**site — pure data.** No scripts, no orchestration. Just:
- `<slug>/board.json` — each board's data (schema above), hand-authored or
  collector-generated.
- `<slug>/index.html` — a thin shell loading the shared renderer.
- `status.json` — the hub manifest: `{slug, title, icon?, description, updated}`
  per board. `icon` is optional; collectors that render per-board (e.g.
  `history`) read it from here rather than hardcoding, keeping them generic.
- `_assets/board.{js,css}` — the renderer, installed by `sync-renderer.sh`.
- `Dockerfile` + `nginx.conf` — how it's served.

## The four contracts (seams)

1. **board.json schema** — between every *producer* (collectors, hand edits) and
   the *consumer* (renderer + validator). Defined in `BOARD_SCHEMA.md`, enforced
   by `validate-board.py` on every `roost status`. This is the tight one; the
   others are modeled on it.

2. **Collector interface** — a collector is any script that writes a valid
   `board.json` (or, like `history`, a whole board + a manifest stamp). It takes
   its target from an argument or env, not a hardcoded path. Generic collectors
   live in `statusgen/bin/collect/`; roost-specific ones (fleet) live in roost.

3. **Renderer distribution** — statusgen is the source of truth for
   `renderer/board.{js,css}`; a site carries an installed *copy* in `_assets/`.
   `sync-renderer.sh` runs on every deploy (step 2 above), so an edited renderer
   can never silently fail to reach the live site.

4. **Path/config resolution** — nothing hardcodes `~/repos/*`. roost reads
   `~/.roostrc` (`ROOST_STATUS_SITE`, `ROOST_STATUSGEN`, `ROOST_DOCS`, …; see
   `roostrc.example`) and passes locations down to the collectors it runs.

## Adding things

- **A new board** → `new-board.sh` (shell + starter `board.json`), add a
  `status.json` entry (with an optional `icon`). It's data; no code.
- **A new metric** → a collector under `statusgen/bin/collect/`, wired into
  `roost stats` or `roost status`.
- **A new site** → `new-site.sh` scaffolds it and runs `sync-renderer.sh` once;
  point `ROOST_STATUS_SITE` at it.
