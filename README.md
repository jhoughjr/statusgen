# statusgen

statusgen makes self-hosted status boards from data. You write JSON, and the page shows it with a shared style. One hub lists every board. Each board is a folder with a `board.json`. Collectors refresh the project numbers. A deploy is one `git push` to a Dokku app behind a Cloudflare tunnel.

```
status.example.net/          → the hub (lists all boards)
status.example.net/demo/     → a board, rendered from demo/board.json
```

---

## How it works

statusgen is the tool. A site is an instance that uses the tool.

- **The tool** (this repo) holds a shared renderer (`renderer/board.css` and `renderer/board.js`), the data model (`BOARD_SCHEMA.md` and `bin/widgets.schema.json`), the validator (`bin/validate-board.py`), the collectors (`bin/collect/`), and the scripts that make and deploy a site (`bin/`).
- **A site** (for example `status-site/`) holds a hub `index.html`, a `status.json` manifest, a copy of the renderer in `_assets/`, and one folder per board (`<slug>/index.html` shell and `<slug>/board.json` data). It is a static site with a `Dockerfile` (`nginx:alpine`), and it deploys to a Dokku app.

The browser does the rendering. Each board shell loads the shared renderer, and the renderer gets the `board.json` and draws the sections. To update a board, write its `board.json` again and push the site. There is no template step and no build step in the browser.

The deploy has one build step, on the Dokku host. Each `git push` to the Dokku remote makes Dokku build a Docker image from the site's `Dockerfile` on that host. The image copies the site files into `nginx:alpine`. A deploy is complete only when that build is complete and Dokku serves the new container.

```
 board.json ──▶ renderer (board.js/css) ──▶ styled board
     ▲                                          ▲
 collectors (bin/collect)            Dokku builds the Dockerfile,
                                     nginx serves it, the Cloudflare
                                     tunnel reaches it (wildcard → :80)
```

---

## The house deployment

The house runs one site, at `status.<domain>`, with two machines in two roles:

- **The mini writes the boards.** It runs `roost status` every hour. roost runs the collectors, syncs the renderer, validates every board, and commits the site. Then it rebases on the GitHub mirror, force-pushes to the Dokku remote, and pushes to the mirror.
- **The opi (192.168.0.103) only deploys.** It is the Dokku host. It receives the push, builds the site's `Dockerfile`, and serves the result. It runs no collector and writes no board.

A laptop can also run `roost status` by hand. The mirror is the source of truth for the site repo, and the rebase keeps the two writers from overwriting each other.

The site is behind vault authentication. A request without a session gets a 302 redirect to the vault sign-in, so a plain `curl` of a board URL gets the redirect and not the board. See [Session chip](#session-chip-vault-gated-sites).

[INTERFACES.md](INTERFACES.md) gives the full split between statusgen, roost, the site, and the `ci-live` relay.

---

## Prerequisites (set up once)

> **Do you start from a bare machine?** [SETUP.md](SETUP.md) gives the full stack from zero. It installs Dokku, makes the Cloudflare tunnel, sets the DNS, and makes the stack survive a reboot. Then it sends you to the quickstart below.

statusgen expects a small, standard self-hosting stack:

1. **A Dokku host** that you can reach over SSH as the `dokku` user. That channel runs Dokku commands (`ssh dokku@HOST apps:create …`) and receives deploys (`git push dokku@HOST:app main`). Register your SSH public key with `dokku ssh-keys:add <name> < ~/.ssh/id_ed25519.pub`.
2. **A Cloudflare tunnel** from that host, which sends subdomains to nginx. Set a wildcard ingress rule `*.yourdomain → http://<host>:80` on the tunnel once. Then any subdomain goes to nginx, and Dokku routes it by vhost. Proxied wildcard DNS is Enterprise-only, so DNS stays per subdomain. Each subdomain needs one `cloudflared tunnel route dns` line, and the scripts print it for you.
3. **`cloudflared`** on the tunnel host, with its `cert.pem`, for the per-subdomain DNS records.

Set these environment variables for your infrastructure (the defaults are shown):

```sh
export DOKKU_HOST=dokku.example.net
export CF_TUNNEL=<your-tunnel-uuid>
export BASE_DOMAIN=example.net
```

---

## From nothing to a working board

```sh
git clone <this-repo> statusgen && cd statusgen
export DOKKU_HOST=… CF_TUNNEL=… BASE_DOMAIN=…

# 1. Make a site, its Dokku app, and the first deploy (creates ./status-site/)
bin/new-site.sh status
#    → creates Dokku app `status`, maps status.$BASE_DOMAIN, scaffolds the site,
#      pushes it, and PRINTS the DNS command to run next.

# 2. Make the DNS record (run the printed line on the tunnel host):
cloudflared tunnel route dns $CF_TUNNEL status.$BASE_DOMAIN

# 3. Add a board to the site
bin/new-board.sh status-site demo "Demo" "Cross-repo project status"

# 4. Write the board's data (by hand, or with a collector)
$EDITOR status-site/demo/board.json

# 5. Deploy
bin/update.sh status-site demo
```

Then `https://status.$BASE_DOMAIN/` is the hub, and `…/demo/` is the board. For each new board, do steps 3 to 5 again. A subdomain needs its DNS line only one time.

> Does the browser say "can't resolve" after you add the DNS record? The client has a cached negative lookup, and `dig` already works. On macOS, clear it with `sudo dscacheutil -flushcache && sudo killall -HUP mDNSResponder`.

---

## The data model

A board is `{ title, eyebrow, stamp, sections: [...] }`. The sections render in order, each by its `kind`: `stats`, `compare`, `banner`, `barchart`, `pie`, `table`, `cards`, `console`, `live-console`, and `split`. [BOARD_SCHEMA.md](BOARD_SCHEMA.md) gives the full model with examples. `bin/widgets.schema.json` is its machine-readable half, and `bin/validate-board.py` applies it. [examples/demo.board.json](examples/demo.board.json) is a complete example.

The smallest possible board:

```json
{
  "title": "My Project",
  "stamp": "Updated 2026-07-07",
  "sections": [
    { "kind": "stats", "items": [ { "n": "42", "label": "Things done", "tone": "go" } ] }
  ]
}
```

---

## Collectors

People and agents write the narrative sections (`table`, `cards`, `split`, and the banner lede). Collectors write the numbers. A collector is a script under `bin/collect/` that reads a data source and writes sections into a `board.json`. It gets its configuration from `~/.roostrc`, and it never fails a status push: with no configuration it prints a skip note, and on any error it leaves the board as it was and exits 0. `bin/collect/lib.py` holds the shared primitives, for example `upsert_section`, `save_board`, and `read_roostrc`.

roost runs most collectors from `roost stats`. `roost status` runs `history`, `rookery`, and `collectors` itself, after `roost stats`.

| Collector | What it writes |
|---|---|
| `api_consumption.py` | The "API consumption" consumed column from `performWith()` call sites, and the "Contract adoption" split from the tokens in `contract_adoption.json`. |
| `builds.py` | A "Builds" console with one line per CI-published build, each linked to its vault-gated download. |
| `ci_health.py` | Build time and build-green tiles for one workflow on one branch, and a build-time barchart of the last runs. |
| `ci_live.py` | A `CI — running now` section of kind `live-console` that points at the `ci-live` endpoint. It calls no CI API. |
| `ci_status.py` | The `CI — runs` console from the run ledger (GitHub through `gh`, and Forgejo through its API), and a ✓/✗ tile per repo. |
| `collectors.py` | A "Collectors" console with one line per collector from roost's run record: its result, duration, and age. |
| `git-stats.sh` | Prints raw repo numbers as JSON (`commits_7d`, `loc`, `test_files`, `tests_dir_loc`). It writes no board. |
| `hatchery_stacks.py` | A "Stacks" console with one line per service and its health, from hatchery's status route. |
| `history.py` | The site's History board from the site's git log: a digest, one console per board, and each board's banner revisions. |
| `loc.py` | Lines-of-code charts, rebuilt from the buckets in the `ROOST_LOC_CONFIG` file. |
| `narrative.py` | The timeline of merged PRs below the banner's `── shipped` marker. It does not touch the lede above the marker. |
| `proposal_state.py` | A "Proposals" table from the status lines in Clauffice `proposals/README.md`. |
| `repo_stats.py` | Test and coverage tiles, and the coverage, test-type, and "E2E suites" sections, from CI's `test-report.json`. |
| `rookery.py` | A "Seats" console with one line per rookery seat: role, state, execution mode, and runner. |
| `shipped_week.py` | A "Shipped this week" cards section, with one card per PR merged in the last 7 days. |
| `swift_test_report.py` | Test results and coverage for a Swift repo whose gate runs in CI, from its `test-report.json`. |
| `swift_tests.py` | The count of test cases that a Swift repo declares, for a repo whose suite does not run in CI. |
| `test_detail.py` | A `<slug>/tests/` detail page from the test report, and links from the test tiles to it. |
| `wayfinder.py` | The wayfinder planning sections from the Clauffice issue tracker: counts, the takeable frontier, blocked work, and map checks. |

Each collector's docstring gives its configuration keys. The split is on purpose: collectors write the numbers, and people write the story.

---

## Session chip (vault-gated sites)

A site behind a vault authentication instance can commit `_assets/site.json` with `{"vault": "https://<vault-host>"}`. When this file is present, the renderer shows a chip at the bottom right of every board page, with the signed-in user's avatar, email, and a sign-out link. With no file, the renderer shows nothing. `sync-renderer.sh` never changes `site.json`.

---

## Scripts

| Script | What it does |
|---|---|
| `bin/new-site.sh <app> [domain]` | Makes the Dokku app and domain, scaffolds `./<app>-site/`, does the first deploy, and prints the DNS line. |
| `bin/new-board.sh <site-dir> <slug> "<title>" ["<desc>"]` | Adds a board: the folder, the shell, a starter `board.json`, and a manifest entry. |
| `bin/sync-renderer.sh <site-dir>` | Copies the current renderer into the site's `_assets/`, and stamps a content hash into every shell's asset URLs so that the edge cache gets the new renderer. |
| `bin/update.sh <site-dir> <slug> [<html>]` | Refreshes a board (with an optional new HTML shell), stamps the date, commits, and deploys. |
| `bin/set-lede.sh <site-dir> <slug> < lede.txt` | Replaces the hand-written banner lede above the shipped marker. It pulls the published site first, checks the length rule, validates, and pushes. |
| `bin/validate-board.py <board.json>…` | Validates boards against `bin/widgets.schema.json`. A hard finding exits non-zero, and a soft finding prints a warning. |
| `bin/collect/*` | The collectors. See [Collectors](#collectors). |

The deploy scripts get the infrastructure from `DOKKU_HOST`, `CF_TUNNEL`, and `BASE_DOMAIN`. `set-lede.sh` uses the `DEPLOY_REMOTE` git remote (default `dokku`).

---

## Tests

Each file under `tests/` runs on its own from the repo root: `python3 tests/<file>.py` for the Python tests, and `node tests/<file>.mjs` for the renderer tests. `tests/test_widget_schema.py` holds the renderer, `bin/widgets.schema.json`, the validator, and every JSON example in `BOARD_SCHEMA.md` to one surface. Run it after a change to any of them.

---

## Why this shape

- **The tunnel is a simple pipe** (wildcard → :80, set once). Dokku routes by hostname, and statusgen scaffolds and deploys. A new board is a few CLI lines and never needs the Cloudflare dashboard.
- **The site is static and the browser renders it.** There is no framework and no application server. A board is a JSON file, and the only build is the `nginx:alpine` image that Dokku makes on each deploy.
- **The renderer is theme-aware** (light and dark) and has no dependencies.
