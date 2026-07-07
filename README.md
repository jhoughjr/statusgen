# statusgen

Data-driven, self-hosted **status boards**. Write JSON, get a styled page. One
hub lists every board; each board is a folder with a `board.json`. Project stats
can be auto-collected. Deploy is one `git push` to Dokku behind a Cloudflare
tunnel — no dashboard, no build step.

```
status.example.net/                → the hub (lists all boards)
status.example.net/demo/      → a board, rendered from demo/board.json
```

---

## How it works

statusgen is the **tool**; a *site* is an **instance** that consumes it.

- **The tool** (this repo): a shared **renderer** (`renderer/board.css` +
  `board.js`), the **data model** (`BOARD_SCHEMA.md`), and **scripts** (`bin/`)
  that scaffold and deploy.
- **A site** (e.g. `status-site/`): a hub `index.html` + `status.json` manifest,
  the renderer vendored into `_assets/`, and one folder per board
  (`<slug>/index.html` shell + `<slug>/board.json` data). It's a plain static
  site with a `Dockerfile` (`nginx:alpine`), deployed to a Dokku app.

Rendering happens in the browser: each board's shell loads the shared renderer,
which fetches its `board.json` and draws the sections. Updating a board = rewrite
its `board.json` and `git push`. **No server-side build, no templating step.**

```
 board.json ──▶ renderer (board.js/css) ──▶ styled board
     ▲                                          ▲
 collect.sh (auto stats)              served by Dokku/nginx
                                      reached via Cloudflare tunnel (wildcard → :80)
```

---

## Prerequisites (set up once)

> **Starting from a bare machine?** [**SETUP.md**](SETUP.md) walks you through the
> whole stack from scratch — install Dokku, create the Cloudflare tunnel, wire
> DNS, and make it survive reboots — then hands off to the quickstart below.

statusgen assumes a small, standard self-hosting stack — the same one this was
built on:

1. **A Dokku host** you can reach over SSH as the `dokku` user. That channel both
   runs Dokku commands (`ssh dokku@HOST apps:create …`) and receives deploys
   (`git push dokku@HOST:app main`). Your SSH public key must be registered:
   `dokku ssh-keys:add <name> < ~/.ssh/id_ed25519.pub`.
2. **A Cloudflare tunnel** from that host, configured so subdomains reach nginx.
   The clean "set once" pattern: a **wildcard ingress rule**
   `*.yourdomain → http://<host>:80` on the tunnel, so *any* subdomain flows to
   nginx and **Dokku routes it by vhost**. (Proxied *wildcard DNS* is
   Enterprise-only, so DNS stays per-subdomain — one `cloudflared tunnel route
   dns` line each, which the scripts print for you.)
3. **`cloudflared`** installed on the tunnel host (with its `cert.pem`), for the
   per-subdomain DNS records.

Point the scripts at your infra with env vars (defaults shown):

```sh
export DOKKU_HOST=dokku.example.net
export CF_TUNNEL=<your-tunnel-uuid>
export BASE_DOMAIN=example.net
```

---

## Nothing → working

```sh
git clone <this-repo> statusgen && cd statusgen
export DOKKU_HOST=… CF_TUNNEL=… BASE_DOMAIN=…

# 1. Stand up a site + its Dokku app + first deploy (creates ./status-site/)
bin/new-site.sh status
#    → creates Dokku app `status`, maps status.$BASE_DOMAIN, scaffolds the site,
#      pushes it, and PRINTS the DNS command to run next.

# 2. Create the DNS record (run the printed line on the tunnel host):
cloudflared tunnel route dns $CF_TUNNEL status.$BASE_DOMAIN

# 3. Add a board to the site
bin/new-board.sh status-site demo "Demo" "Cross-repo project status"

# 4. Fill in the board's data (hand-write, or generate — see "Stats" below)
$EDITOR status-site/demo/board.json

# 5. Deploy
bin/update.sh status-site demo
```

Now: `https://status.$BASE_DOMAIN/` is the hub, `…/demo/` is the board.
Every later board is steps 3–5 again (and the DNS line is only needed once per
subdomain).

> DNS just added and the browser says "can't resolve"? It's a cached negative
> lookup — `dig` will already work. Flush: `sudo dscacheutil -flushcache &&
> sudo killall -HUP mDNSResponder` (macOS).

---

## The data model

A board is `{ title, eyebrow, stamp, sections: [...] }`. Sections render in
order, each by its `kind`: `stats` (tiles), `banner`, `barchart`, `pie`,
`table`, `cards`, `split`. Full spec + examples:
**[BOARD_SCHEMA.md](BOARD_SCHEMA.md)**. A complete example:
**[examples/demo.board.json](examples/demo.board.json)**.

Smallest possible board:

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

## Stats: automate the numbers

The narrative sections (`table`, `cards`, `split`) are hand/agent-authored. The
*quantitative* ones (`stats` tiles, `barchart` values) can be refreshed from a
repo. `bin/collect/git-stats.sh <repo>` emits the raw numbers:

```sh
bin/collect/git-stats.sh ~/repos/my-project
# → { "commits_7d": 99, "loc": 40362, "test_files": 128, "tests_dir_loc": 23760 }
```

Wire a per-project collector that merges those into the right fields of its
`board.json`, then `bin/update.sh` to deploy. The split is deliberate: **numbers
are collected, story is written.**

---

## Scripts

| Script | What it does |
|---|---|
| `bin/new-site.sh <app> [domain]` | Create the Dokku app + domain, scaffold `./<app>-site/`, first deploy, print the DNS line. |
| `bin/new-board.sh <site-dir> <slug> "<title>" ["<desc>"]` | Add a board: folder + shell + starter `board.json` + manifest entry. |
| `bin/sync-renderer.sh <site-dir>` | Copy the current renderer into the site's `_assets/`. |
| `bin/update.sh <site-dir> <slug> [<html>]` | Refresh a board (optional new HTML), stamp the date, commit, deploy. |
| `bin/collect/git-stats.sh <repo>` | Emit quantitative stats for a repo as JSON. |

All take infra from `DOKKU_HOST` / `CF_TUNNEL` / `BASE_DOMAIN`.

---

## Why this shape

- **Tunnel = dumb pipe** (wildcard → :80, set once) → **Dokku routes by
  hostname** → **statusgen scaffolds + deploys**. New board = a couple of CLI
  lines, never the Cloudflare dashboard.
- **Static + client-rendered** → no build server, no framework; a board is a
  JSON file and 20 lines of shell to ship it.
- **Theme-aware** (light/dark) and dependency-free.
