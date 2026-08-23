#!/usr/bin/env python3
"""builds.py — surface CI-published builds on a board as a "Builds" console
section, with each line linking to the vault-gated download.

A CI runner publishes signed build zips to its local disk and serves them
(with an index.json manifest) over LAN; vault proxies admin-gated downloads.
This collector reads each configured manifest and keeps the board's links
current — build names carry a timestamp+sha, so hand links go stale.

Config (~/.roostrc), one source per product:
  ROOST_BUILDS_BOARD=clauffice                       # board dir under the site
  ROOST_BUILDS_SOURCES='[{"label": "Phoenix", "logo": "ts",
      "index": "http://localhost:8090/phoenix/index.json",
      "vault": "https://vault.jimmyhoughjr.net/api/files/phoenix-builds"}]'

The legacy pair ROOST_BUILDS_INDEX + ROOST_BUILDS_VAULT still works and means
one Phoenix source. `logo` marks each line with its stack (swift | ts | js),
which is what lets client and server builds share one merged feed.

Non-fatal by contract: no config → skip; total failure → board untouched,
exit 0. One source failing keeps its existing lines on the board (matched by
logo) rather than letting a product's builds vanish for a cycle.
"""
import json
import pathlib
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lib

PER_SOURCE = 5


def sources_from(cfg):
    """The configured manifest sources. ROOST_BUILDS_SOURCES (a JSON list) wins;
    the legacy INDEX+VAULT pair means one Phoenix source."""
    raw = (cfg.get("ROOST_BUILDS_SOURCES") or "").strip()
    if raw:
        parsed = json.loads(raw)
        return [s for s in parsed
                if isinstance(s, dict) and s.get("index") and s.get("vault")]
    index_url = cfg.get("ROOST_BUILDS_INDEX", "")
    vault_base = cfg.get("ROOST_BUILDS_VAULT", "")
    if index_url and vault_base:
        return [{"label": "Phoenix", "logo": "ts", "index": index_url, "vault": vault_base}]
    return []


def build_lines(files, source):
    """Map one manifest's entries to console lines, newest first.

    `mtime` is a UTC ISO-8601 instant from the runner's manifest. Per
    BOARD_SCHEMA it goes out as `ts` so the renderer localizes it to each
    viewer's clock; only the size goes in `meta`. (Slicing it into a bare
    "2026-07-13 21:42" string here showed the runner's UTC to everyone.)
    """
    vault_base = source["vault"].rstrip("/")
    lines = []
    for i, f in enumerate(files[:PER_SOURCE]):
        mb = f.get("size", 0) / 1048576
        line = {
            "status": "signed",
            # The newest build of EACH product reads green — with two products
            # in one feed, "latest" is per product, not per feed.
            "tone": "go" if i == 0 else "none",
            "text": f["name"],
            "meta": f"· {mb:.0f} MB",
            "href": vault_base + "/" + urllib.parse.quote(f["name"]),
        }
        if source.get("logo"):
            line["logo"] = source["logo"]
        mtime = f.get("mtime") or ""
        if mtime:
            line["ts"] = mtime
        lines.append(line)
    return lines


def fetch_manifest(source):
    with urllib.request.urlopen(source["index"], timeout=10) as r:
        return json.load(r).get("files", [])


def collect_lines(sources, fetch, existing_lines):
    """Every source's lines, merged newest-first across products.

    A source whose fetch fails keeps its lines already on the board — matched
    by logo — because a build that vanishes from the feed for a cycle reads
    exactly like a build that never happened. Returns (lines, notes)."""
    merged, notes = [], []
    for source in sources:
        try:
            files = fetch(source)
            merged.extend(build_lines(files, source))
        except Exception as e:
            kept = [ln for ln in existing_lines if ln.get("logo") == source.get("logo")]
            merged.extend(kept)
            notes.append(f"{source.get('label') or source['index']}: fetch failed "
                         f"({e}) — kept {len(kept)} existing lines")
    merged.sort(key=lambda ln: ln.get("ts") or "", reverse=True)
    return merged, notes


def main():
    cfg = lib.read_roostrc()
    board_dir = cfg.get("ROOST_BUILDS_BOARD", "")
    sources = sources_from(cfg)
    if not board_dir or not sources:
        print("builds: ROOST_BUILDS_BOARD/SOURCES (or INDEX+VAULT) not configured — skipping")
        return 0
    board_path = lib.site_dir(cfg) / board_dir / "board.json"
    if not board_path.exists():
        print(f"builds: {board_path} not found — skipping")
        return 0

    board = lib.load_board(board_path)
    existing = next((s.get("lines") or [] for s in board.get("sections", [])
                     if s.get("title") == "Builds"), [])
    lines, notes = collect_lines(sources, fetch_manifest, existing)
    for note in notes:
        print(f"builds: note: {note}")
    if not lines:
        print("builds: nothing collected — leaving board as-is")
        return 0

    section = {
        "kind": "console", "icon": "📦", "title": "Builds",
        "desc": "signed builds — vault sign-in required to download",
        "count": f"{len(lines)} kept",
        "lines": lines,
    }
    lib.upsert_section(board, "Builds", section, after_kind="console")
    lib.save_board(board_path, board)
    print(f"builds: {len(lines)} builds from {len(sources)} source(s), latest {lines[0]['text']}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # never break a status push
        print(f"builds: non-fatal error: {e}")
        sys.exit(0)
