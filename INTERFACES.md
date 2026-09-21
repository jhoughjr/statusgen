# How statusgen, roost, and a status site fit together

Four pieces work together to publish a status site. Each piece has one job, and it talks to the others through a named contract. You can replace one piece, and the others do not see a change.

Three pieces make the **push path**. On a schedule, roost runs the statusgen collectors, the collectors write the site's JSON, and the site deploys. The fourth piece, `ci-live`, is the **live path**. It does the one thing that a board published on a schedule cannot do: it shows CI runs while they run.

```
   roost (driver)                 statusgen (library)              site (data)
 ┌────────────────┐            ┌──────────────────────┐        ┌──────────────┐
 │ roost status   │──runs────▶ │ bin/collect/*        │──write▶│ <slug>/      │
 │  · resolves     │           │  (history, ci_status,│        │   board.json │
 │    paths (rc)   │           │   repo_stats, …)     │        │ status.json  │
 │  · runs         │──sync────▶│ bin/sync-renderer.sh │──copy─▶│ _assets/     │
 │    collectors   │           │ renderer/board.{js,  │        │   board.{js, │
 │  · syncs        │           │  css}                │        │    css}      │
 │    renderer     │──gate────▶│ bin/validate-board.py│──check─│ */board.json │
 │  · validates    │           │ BOARD_SCHEMA.md      │        │ <slug>/      │
 │  · deploys      │           └──────────────────────┘        │   index.html │
 └────────────────┘                                            └──────────────┘
```

The live path runs all the time, in parallel with the push path, and it never touches the site:

```
      mini (has `gh` auth)              opi                    a browser
 ┌──────────────────────────┐    ┌───────────────┐      ┌──────────────────┐
 │ roost/bin/               │    │  ci-live      │      │ live-console     │
 │   ci-live-report.sh      │───▶│  (dokku app)  │◀─────│ section polls    │
 │ launchd, every 20s       │POST│  last payload │ GET  │ poll.url         │
 │ keeps only queued,       │ key│  per project, │CORS *│ (seeded by       │
 │ in-progress, waiting and │    │  on a volume  │      │  collect/        │
 │ requested runs           │    └───────────────┘      │  ci_live.py)     │
 └──────────────────────────┘                           └──────────────────┘
```

## Responsibilities

**statusgen - the library.** It is standalone and board-agnostic. It knows nothing about a specific site.

- It owns the **board.json schema** ([BOARD_SCHEMA.md](BOARD_SCHEMA.md) and `bin/widgets.schema.json`) and its **validator** (`bin/validate-board.py`).
- It owns the **renderer** (`renderer/board.{js,css}`) and the tool that copies it into a site (`bin/sync-renderer.sh`). The tool stamps a content hash into the asset URLs, so the edge cache gets a new renderer when the renderer changes.
- It owns the **generic collectors** (`bin/collect/*`). Each one makes board sections from one data source. The [README Collectors table](README.md#collectors) lists all of them with one line each.
- It owns the **scaffolding** (`bin/new-site.sh`, `bin/new-board.sh`) and the lede tool (`bin/set-lede.sh`).

On a multi-repo board, the collectors split by the repo that they speak for, and each one writes only into that repo's compare column. `ci_status` owns the ✓/✗. `ci_health` owns the build's cost. `repo_stats` owns a JavaScript repo with a CI test report. `swift_test_report` owns a Swift repo with a CI test report. `swift_tests` owns a repo whose suite does not run in CI. An unscoped write puts a number under the heading of a different repo.

`swift_tests` and `swift_test_report` are mutually exclusive per repo. When a repo's gate starts to emit a report, move the repo from `ROOST_SWIFT_TESTS` to `ROOST_SWIFT_REPORT`. If the repo stays in both, the two collectors write the same tile on every push, and the last one to run wins.

**roost - the driver.** roost is the one place that knows where things are and when to run them. `roost status` is the only orchestration entry point ([bin/status.sh](../roost/bin/status.sh)):

1. Run the collectors: roost's `fleet-board.py`, then `roost stats` (most statusgen collectors), then `history`, `rookery`, and `collectors`. roost records the result of each collector (see contract 6).
2. Run `sync-renderer.sh`, so the deployed renderer matches statusgen.
3. Run `validate-board.py` on every board as a hard gate.
4. Write the usage ledger (optional).
5. Commit the site, rebase on the GitHub mirror, force-push to the Dokku remote, and push to the mirror. roost then reads Dokku's deploy output and fails if Dokku did not serve the `status.<domain>` host.

roost also owns the one collector that is specific to roost, `fleet-board.py` (live Dokku platform metrics over SSH).

**ci-live - the live path.** This is a relay of about 200 lines with no dependencies ([jhoughjr/ci-live](https://github.com/jhoughjr/ci-live)). It deploys as its own Dokku app. It knows nothing about CI or boards. An authenticated `POST` replaces the payload of one project. A public CORS `GET` reads the payload back. The relay keeps the last payload per project on a volume, so a restart does not empty the board.

**Why the live path exists.** The code explains only the mechanism, so this part is easy to lose. The goal is to see a build while it runs and go directly to it. Every live row has a `gh run watch <run-id> -R <repo>` copy chip, and that is why the rows need the run id. Two facts make a relay the only way to get this:

- **A board is a static file on a schedule.** It cannot show a run that starts between two pushes. Also, the push itself happens inside a CI run. A board that showed in-progress runs would freeze that run as "in progress" on the board. That is why `collect/ci_status.py` drops in-progress runs (`CONSOLE_SKIP`), and the live path adds them back, live.
- **A browser cannot ask GitHub directly.** The repos are private, so the request needs a token, and a token cannot be in a page. CORS and rate limits also stop it. So a machine that has `gh` auth asks, and it posts the answer to a place that the page can read.

The poller sends in one direction and keeps no state. If it stops, the endpoint serves its last payload, and the board's live dot goes stale. Nothing else changes.

**The live-console section.** `collect/ci_live.py` writes one `live-console` section, `CI — running now`, into the board named by `ROOST_CI_LIVE_BOARD`. A new section goes after the first `compare` section, above the static runs console. A section that exists stays where it is. Its `poll.url` is `ROOST_CI_LIVE_URL?project=ROOST_CI_LIVE_PROJECT`, and its `poll.intervalMs` comes from `ROOST_CI_LIVE_INTERVAL` (seconds, default 30). The collector calls no CI API. If one of the three keys is missing, or the board does not exist, it skips.

In the browser, the renderer gets `poll.url` when the page loads and then at each interval. It starts with `poll.intervalMs`. When a response has its own `intervalMs`, the renderer uses that value from then on. When a fetch fails, the live dot goes stale and the status row says `unreachable — retrying`. [BOARD_SCHEMA.md](BOARD_SCHEMA.md) gives the section fields.

**site - data only.** A site has no scripts and no orchestration. It has:

- `<slug>/board.json`: the data of each board (the schema above), written by hand or by a collector.
- `<slug>/index.html`: a thin shell that loads the shared renderer.
- `status.json`: the hub manifest, `{slug, title, icon?, description, updated}` per board. `icon` is optional. A collector that renders per board (for example `history`) reads the icon from this file and does not hardcode it, so the collector stays generic.
- `_assets/board.{js,css}`: the renderer, copied by `sync-renderer.sh`.
- `_assets/site.json` (optional): the vault address for the session chip.
- `Dockerfile` and `nginx.conf`: how the site is served. Dokku builds the `Dockerfile` on each deploy.

## The six contracts

1. **The board.json schema** is between every producer (collectors, hand edits) and the consumer (the renderer and the validator). `BOARD_SCHEMA.md` and `bin/widgets.schema.json` define it, and `validate-board.py` applies it on every `roost status`. This contract is the strictest, and the others copy its model.

2. **The collector interface.** A collector is a script that writes a valid `board.json` (or, like `history`, a full board and a manifest stamp). It gets its target from an argument, the environment, or `~/.roostrc`, and never from a hardcoded path. It never fails the push: on any error it leaves the board as it was and exits 0. The generic collectors are in `statusgen/bin/collect/`. The collectors that are specific to roost (fleet) are in roost.

3. **Renderer distribution.** statusgen is the source of truth for `renderer/board.{js,css}`. A site has a copy in `_assets/`. `sync-renderer.sh` runs on every deploy (step 2 above), so an edited renderer always gets to the live site.

4. **Path and config resolution.** Nothing hardcodes `~/repos/*`. roost reads `~/.roostrc` (`ROOST_STATUS_SITE`, `ROOST_STATUSGEN`, `ROOST_DOCS`, and others, see `roostrc.example`) and gives the locations to the collectors that it runs.

5. **The live-run relay** is between the poller, the relay, and the board. The payload is `{ project, lines: [<console-line>…], intervalMs }`, and each line has the same shape as a `console` section line. Two rules apply. First, writes need a shared key (`~/.roost_ci_key`, the same as the app's `CI_KEY`), and reads are public and CORS-open. Second, **the endpoint gives its own `intervalMs`**, and the board follows it. The poller sets the refresh rate one time for each project (`ROOST_CI_LIVE_REPOS`), and no viewer sets it. A board with no relay configured has no live section (`collect/ci_live.py` skips), and the push path does not change.

6. **The collector run record** is between roost and `collect/collectors.py`. roost's collector wrapper times each collector and merges the results by name into `roost-collectors.json` (`ROOST_COLLECTOR_LOG`, default `${XDG_STATE_HOME:-~/.local/state}/roost-collectors.json`). The shape is `{ at, runs: [{ name, ok, ms, at, exit? }] }`, with times in epoch milliseconds. `collectors.py` draws it as the `Collectors` console on the board named by `ROOST_COLLECTOR_BOARD` (default `clauffice`). A collector that fails shows red, with its exit code. Its own row is one pass behind, because the record is written before the section is drawn.

## Adding things

- **A new board:** run `new-board.sh`. It makes the shell, a starter `board.json`, and the `status.json` entry. Add an `icon` to the entry if you want one. A board is data, and it needs no code.
- **A new metric:** add a collector under `statusgen/bin/collect/`, run it from `roost stats` or `roost status`, and add it to the README Collectors table.
- **A new site:** `new-site.sh` scaffolds it and runs `sync-renderer.sh` one time. Then set `ROOST_STATUS_SITE` to the site.
