#!/usr/bin/env bash
# new-board.sh — add a board to an existing statusgen site.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RENDERER_DIR="$(cd "${SCRIPT_DIR}/../renderer" && pwd)"

usage() {
  cat <<EOF
Usage: $(basename "$0") <site-dir> <slug> "<title>" ["<description>"]

Add a new board to an existing statusgen site:
  - creates <site-dir>/<slug>/
  - writes <slug>/index.html from the shared board shell template
  - writes a minimal, valid starter <slug>/board.json (title + a stats
    section stub)
  - appends {slug, title, description, updated} to <site-dir>/status.json

Arguments:
  <site-dir>       Path to a statusgen site directory (e.g. ./myapp-site)
  <slug>           URL-safe board folder name (e.g. demo)
  <title>          Board title (quote it)
  [description]    Short description for the hub listing (quote it)
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -lt 3 || $# -gt 4 ]]; then
  echo "error: expected 3 or 4 arguments, got $#" >&2
  usage >&2
  exit 1
fi

site_dir="$1"
slug="$2"
title="$3"
description="${4:-}"

if [[ ! -d "$site_dir" ]]; then
  echo "error: site directory not found: ${site_dir}" >&2
  exit 1
fi

board_template="${RENDERER_DIR}/board.template.html"
if [[ ! -f "$board_template" ]]; then
  echo "error: renderer board template not found at ${board_template}" >&2
  exit 1
fi

board_dir="${site_dir}/${slug}"
if [[ -e "$board_dir" ]]; then
  echo "error: '${board_dir}' already exists; refusing to overwrite" >&2
  exit 1
fi

mkdir -p "$board_dir"
cp "$board_template" "${board_dir}/index.html"

today="$(date +%Y-%m-%d)"

# Starter board.json: title + a stats section stub, per BOARD_SCHEMA.md.
python3 - "${board_dir}/board.json" "$title" "$today" <<'PYEOF'
import json
import sys

board_path, title, today = sys.argv[1], sys.argv[2], sys.argv[3]

board = {
    "title": title,
    "eyebrow": "",
    "stamp": f"Updated {today}",
    "sections": [
        {"kind": "stats", "items": []},
    ],
}

with open(board_path, "w") as f:
    json.dump(board, f, indent=2)
    f.write("\n")
PYEOF

status_json="${site_dir}/status.json"

# Append (or replace, if the slug already has an entry) in the hub manifest.
python3 - "$status_json" "$slug" "$title" "$description" "$today" <<'PYEOF'
import json
import os
import sys

status_path, slug, title, description, today = sys.argv[1:6]

entries = []
if os.path.isfile(status_path):
    with open(status_path) as f:
        content = f.read().strip()
        if content:
            entries = json.loads(content)

entries = [e for e in entries if e.get("slug") != slug]
entries.append(
    {
        "slug": slug,
        "title": title,
        "description": description,
        "updated": today,
    }
)

with open(status_path, "w") as f:
    json.dump(entries, f, indent=2)
    f.write("\n")
PYEOF

echo "==> Board '${slug}' created at ${board_dir}" >&2
echo "    Edit ${board_dir}/board.json, then: bin/update.sh ${site_dir} ${slug}" >&2
