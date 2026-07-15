#!/usr/bin/env python3
"""builds.py — surface CI-published app builds on a board as a "Builds"
console section, with each line linking to the vault-gated download.

The CI runner publishes signed build zips to its local disk and serves
them (with an index.json manifest) over LAN; vault proxies admin-gated
downloads. This collector reads the manifest and keeps the board's links
current — build names carry a timestamp+sha, so hand links go stale.

Config (~/.roostrc):
  ROOST_BUILDS_BOARD=clauffice                       # board dir under the site
  ROOST_BUILDS_INDEX=http://localhost:8090/phoenix/index.json
  ROOST_BUILDS_VAULT=https://vault.jimmyhoughjr.net/api/files/phoenix-builds

Non-fatal by contract: no config → skip; any failure → board untouched, exit 0.
"""
import json
import pathlib
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lib


def main():
    cfg = lib.read_roostrc()
    board_dir = cfg.get("ROOST_BUILDS_BOARD", "")
    index_url = cfg.get("ROOST_BUILDS_INDEX", "")
    vault_base = cfg.get("ROOST_BUILDS_VAULT", "").rstrip("/")
    if not board_dir or not index_url or not vault_base:
        print("builds: ROOST_BUILDS_BOARD/INDEX/VAULT not configured — skipping")
        return 0
    board_path = lib.site_dir(cfg) / board_dir / "board.json"
    if not board_path.exists():
        print(f"builds: {board_path} not found — skipping")
        return 0

    with urllib.request.urlopen(index_url, timeout=10) as r:
        manifest = json.load(r)
    files = manifest.get("files", [])
    if not files:
        print("builds: manifest empty — leaving board as-is")
        return 0

    lines = []
    for i, f in enumerate(files[:5]):
        mb = f.get("size", 0) / 1048576
        when = (f.get("mtime") or "")[:16].replace("T", " ")
        lines.append({
            "status": "signed",
            "tone": "go" if i == 0 else "none",
            "text": f["name"],
            "meta": f"· {mb:.0f} MB · {when}",
            "href": vault_base + "/" + urllib.parse.quote(f["name"]),
        })

    section = {
        "kind": "console", "icon": "📦", "title": "Builds",
        "desc": "signed builds — vault sign-in required to download",
        "count": f"{len(lines)} kept",
        "lines": lines,
    }
    board = lib.load_board(board_path)
    lib.upsert_section(board, "Builds", section, after_kind="console")
    lib.save_board(board_path, board)
    print(f"builds: {len(lines)} builds, latest {lines[0]['text']}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # never break a status push
        print(f"builds: non-fatal error: {e}")
        sys.exit(0)
