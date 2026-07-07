#!/usr/bin/env bash
# update.sh — refresh a board and deploy.
set -euo pipefail

DOKKU_HOST="${DOKKU_HOST:-dokku.example.net}"
BASE_DOMAIN="${BASE_DOMAIN:-example.net}"

usage() {
  cat <<EOF
Usage: $(basename "$0") <site-dir> <slug> [<path-to-fresh-html>]

Refresh a board and deploy:
  - if <path-to-fresh-html> is given, copies it to <site-dir>/<slug>/index.html
  - stamps today's date on that slug's entry in <site-dir>/status.json
  - commits any changes and pushes to the dokku remote (triggers a deploy)
  - prints the deployed board URL

Arguments:
  <site-dir>              Path to a statusgen site directory (e.g. ./myapp-site)
  <slug>                  Board folder name within the site (e.g. demo)
  [path-to-fresh-html]    Optional replacement HTML shell for the board

Environment variables (defaults shown):
  DOKKU_HOST   ${DOKKU_HOST}
  BASE_DOMAIN  ${BASE_DOMAIN}
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -lt 2 || $# -gt 3 ]]; then
  echo "error: expected 2 or 3 arguments, got $#" >&2
  usage >&2
  exit 1
fi

site_dir="$1"
slug="$2"
fresh_html="${3:-}"

if [[ ! -d "$site_dir" ]]; then
  echo "error: site directory not found: ${site_dir}" >&2
  exit 1
fi

board_dir="${site_dir}/${slug}"
if [[ ! -d "$board_dir" ]]; then
  echo "error: board directory not found: ${board_dir}" >&2
  exit 1
fi

if [[ -n "$fresh_html" ]]; then
  if [[ ! -f "$fresh_html" ]]; then
    echo "error: fresh HTML file not found: ${fresh_html}" >&2
    exit 1
  fi
  cp "$fresh_html" "${board_dir}/index.html"
  echo "==> Replaced ${board_dir}/index.html from ${fresh_html}" >&2
fi

status_json="${site_dir}/status.json"
today="$(date +%Y-%m-%d)"

python3 - "$status_json" "$slug" "$today" <<'PYEOF'
import json
import os
import sys

status_path, slug, today = sys.argv[1:4]

entries = []
if os.path.isfile(status_path):
    with open(status_path) as f:
        content = f.read().strip()
        if content:
            entries = json.loads(content)

found = False
for e in entries:
    if e.get("slug") == slug:
        e["updated"] = today
        found = True

if not found:
    print(f"warning: no status.json entry for slug '{slug}' to stamp", file=sys.stderr)

with open(status_path, "w") as f:
    json.dump(entries, f, indent=2)
    f.write("\n")
PYEOF

echo "==> Committing and deploying..." >&2
git -C "$site_dir" add -A
if git -C "$site_dir" diff --cached --quiet; then
  echo "    no changes to commit" >&2
else
  git -C "$site_dir" commit -q -m "Update ${slug} board (${today})"
fi
git -C "$site_dir" push dokku main

# Resolve the deployed URL: parse the app name out of the dokku remote, then
# ask Dokku for its mapped domain (falls back to the <app>.$BASE_DOMAIN
# convention new-site.sh uses by default).
remote_url="$(git -C "$site_dir" remote get-url dokku)"
app="${remote_url##*:}"

domain=""
if report_out=$(ssh "dokku@${DOKKU_HOST}" domains:report "${app}" --domains-app-vhosts 2>/dev/null); then
  domain="$(echo "$report_out" | awk '{print $1}')"
fi
if [[ -z "$domain" ]]; then
  domain="${app}.${BASE_DOMAIN}"
fi

echo
echo "==> Deployed: https://${domain}/${slug}/"
