#!/usr/bin/env bash
# sync-renderer.sh — copy the shared renderer into a site's _assets/.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RENDERER_DIR="$(cd "${SCRIPT_DIR}/../renderer" && pwd)"

usage() {
  cat <<EOF
Usage: $(basename "$0") <site-dir>

Copy the shared renderer (board.css, board.js) into <site-dir>/_assets/,
overwriting any existing copies there. The renderer directory is resolved
relative to this script's own location (../renderer), so it works
regardless of the caller's current directory.

Arguments:
  <site-dir>  Path to a statusgen site directory (e.g. ./myapp-site)
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -ne 1 ]]; then
  echo "error: expected exactly 1 argument, got $#" >&2
  usage >&2
  exit 1
fi

site_dir="$1"

if [[ ! -d "$site_dir" ]]; then
  echo "error: site directory not found: ${site_dir}" >&2
  exit 1
fi

assets_dir="${site_dir}/_assets"
mkdir -p "$assets_dir"

for f in board.css board.js; do
  src="${RENDERER_DIR}/${f}"
  if [[ ! -f "$src" ]]; then
    echo "error: renderer asset not found: ${src}" >&2
    exit 1
  fi
  cp "$src" "${assets_dir}/${f}"
  echo "==> synced ${f} -> ${assets_dir}/${f}" >&2
done

# Cache-busting. Cloudflare (and browsers) edge-cache .js/.css by URL for hours,
# so a plain /_assets/board.js reference serves a STALE renderer long after a
# deploy. We stamp a content hash into the asset URLs of every board shell, so
# the URL changes exactly when the renderer changes and the edge fetches fresh.
ver="$(cat "${assets_dir}/board.css" "${assets_dir}/board.js" | shasum -a 256 | cut -c1-10)"

shells=0
while IFS= read -r -d '' html; do
  # Rewrite /_assets/board.css and /_assets/board.js (with or without an
  # existing ?v=…) to carry the current version. Files without the ref are
  # left untouched (the hub is self-contained), so this is safe to run on all.
  if grep -qE '/_assets/board\.(css|js)' "$html"; then
    sed -i.bak -E "s#(/_assets/board\.(css|js))(\?v=[A-Za-z0-9]+)?#\1?v=${ver}#g" "$html"
    rm -f "${html}.bak"
    shells=$((shells + 1))
  fi
done < <(find "$site_dir" -name '*.html' -print0)

echo "==> stamped renderer version ${ver} into ${shells} shell(s)" >&2

# Regression guard: no shell may reference the renderer without a version query,
# or the edge-cache staleness bug is back. Fail loudly if one slipped through.
if grep -rEln '/_assets/board\.(css|js)("|\?v=dev)' "$site_dir" --include='*.html' >/dev/null 2>&1; then
  echo "error: a shell still references the renderer unversioned (or ?v=dev):" >&2
  grep -rEln '/_assets/board\.(css|js)("|\?v=dev)' "$site_dir" --include='*.html' >&2
  exit 1
fi
