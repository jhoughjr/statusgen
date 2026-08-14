# How statusgen, roost, and a status site fit together

Four pieces cooperate to publish a status site. Each has one job and talks to
the others through a named contract — so any one can be swapped without the
others noticing.

Three of them are the **push path**: on a schedule, roost runs statusgen's
collectors, they write the site's JSON, and the site deploys. The fourth,
`ci-live`, is the **live path** — the one thing a published-on-a-schedule board
cannot do for itself.

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

The live path runs continuously alongside it, and never touches the site:

```
      mini (has `gh` auth)              opi                    a browser
 ┌──────────────────────────┐    ┌───────────────┐      ┌──────────────────┐
 │ roost/bin/               │    │  ci-live      │      │ live-console     │
 │   ci-live-report.sh      │───▶│  (dokku app)  │◀─────│ section polls    │
 │ launchd, every 20s       │POST│  last payload │ GET  │ poll.url         │
 │ keeps only QUEUED and    │ key│  per project, │CORS *│ (seeded by       │
 │ IN-PROGRESS runs         │    │  on a volume  │      │  collect/        │
 └──────────────────────────┘    └───────────────┘      │  ci_live.py)     │
                                                        └──────────────────┘
```

## Responsibilities

**statusgen — the library.** Standalone and board-agnostic; knows nothing about
any specific site.
- Owns the **board.json schema** ([BOARD_SCHEMA.md](BOARD_SCHEMA.md)) and its
  **validator** (`bin/validate-board.py`).
- Owns the **renderer** (`renderer/board.{js,css}`) and the tool that installs
  it into a site (`bin/sync-renderer.sh`, with content-hash cache-busting).
- Owns the **generic collectors** (`bin/collect/*`) that produce `board.json`
  from a data source: `repo_stats`, `ci_status`, `ci_health`, `swift_tests`,
  `swift_test_report`, `shipped_week`, `api_consumption`, and `history` (a
  site's git log → the History board).

  On a multi-repo board these split by *which repo they speak for*, and each
  scopes its writes to that repo's compare column: `ci_status` owns the ✓/✗,
  `ci_health` the build's cost, `repo_stats` a JavaScript repo with a CI test
  report, `swift_test_report` a Swift repo with one, `swift_tests` a repo whose
  suite does not run in CI at all. An unscoped write is how a number ends up
  rendered under another repo's heading.

  The last two are mutually exclusive per repo, and the day a repo's gate
  starts emitting a report is the day it moves from `ROOST_SWIFT_TESTS` to
  `ROOST_SWIFT_REPORT`. Left in both, they fight over the same tile on every
  push and the winner is whichever ran last.
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

**ci-live — the live path.** A ~200-line, zero-dependency relay
([jhoughjr/ci-live](https://github.com/jhoughjr/ci-live)), deployed as its own
dokku app. It knows nothing about CI or boards: authenticated `POST` replaces
one project's payload, public CORS `GET` reads it back, and the last payload
per project is mirrored to a volume so a restart doesn't blank the board.

**Why it exists at all** — the part that is easy to lose, because the code only
ever explains the mechanism. The goal is to *catch a build while it is running*
and hop straight into it: every live row carries a `gh run watch <run-id>`
copy-chip, which is why the rows need the run id at all. Two things make a
relay the only way to get that:

- **A board is a static file on a schedule.** It cannot show a run that starts
  between pushes. Worse, the push happens *inside* a CI run, so a board that
  showed in-progress runs would freeze that very run as "in progress" forever —
  which is why `collect/ci_status.py` deliberately drops them (`CONSOLE_SKIP`)
  and this path exists to add them back, live.
- **A browser cannot ask GitHub directly.** The repos are private, so it needs
  a token, and a token cannot live in a page — quite apart from CORS and rate
  limits. So a machine that already holds `gh` auth does the asking and posts
  the answer somewhere the page is allowed to read.

The poller is one-way and stateless: if it stops, the endpoint simply serves
its last payload and the board's live dot goes stale. Nothing else notices.

**site — pure data.** No scripts, no orchestration. Just:
- `<slug>/board.json` — each board's data (schema above), hand-authored or
  collector-generated.
- `<slug>/index.html` — a thin shell loading the shared renderer.
- `status.json` — the hub manifest: `{slug, title, icon?, description, updated}`
  per board. `icon` is optional; collectors that render per-board (e.g.
  `history`) read it from here rather than hardcoding, keeping them generic.
- `_assets/board.{js,css}` — the renderer, installed by `sync-renderer.sh`.
- `Dockerfile` + `nginx.conf` — how it's served.

## The five contracts (seams)

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

5. **The live-run relay** — between the poller, the relay and the board. The
   payload is `{ project, lines: [<console-line>…], intervalMs }`, where a line
   is exactly a `console` section's line. Two rules keep it honest: writes are
   authenticated by a shared key (`~/.roost_ci_key`, matching the app's
   `CI_KEY`) while reads are public and CORS-open; and **the endpoint advertises
   its own `intervalMs`**, which the board follows — cadence is set once, on the
   poller, not per viewer. A board with no relay configured simply has no live
   section (`collect/ci_live.py` skips), and the push path is unaffected.

## Adding things

- **A new board** → `new-board.sh` (shell + starter `board.json`), add a
  `status.json` entry (with an optional `icon`). It's data; no code.
- **A new metric** → a collector under `statusgen/bin/collect/`, wired into
  `roost stats` or `roost status`.
- **A new site** → `new-site.sh` scaffolds it and runs `sync-renderer.sh` once;
  point `ROOST_STATUS_SITE` at it.
