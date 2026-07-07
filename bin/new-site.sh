#!/usr/bin/env bash
# new-site.sh — bootstrap a whole statusgen static site + Dokku app.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RENDERER_DIR="$(cd "${SCRIPT_DIR}/../renderer" && pwd)"

DOKKU_HOST="${DOKKU_HOST:-dokku.example.net}"
CF_TUNNEL="${CF_TUNNEL:-<your-tunnel-uuid>}"
BASE_DOMAIN="${BASE_DOMAIN:-example.net}"

usage() {
  cat <<EOF
Usage: $(basename "$0") <app> [domain]

Bootstrap a whole statusgen static site + Dokku app:
  - creates the Dokku app <app> on \$DOKKU_HOST (tolerates "already exists")
  - maps [domain] (default: <app>.\$BASE_DOMAIN) to the app
  - scaffolds ./<app>-site/ (Dockerfile, .dockerignore, _assets/, hub
    index.html, empty status.json)
  - git init's the site dir, commits, adds the dokku remote, and pushes
    (first deploy)
  - prints the cloudflared DNS command to run on the tunnel host, and the
    final URL

Arguments:
  <app>       Dokku app name (also used as the site dir prefix: <app>-site/)
  [domain]    FQDN to map to the app. Default: <app>.\$BASE_DOMAIN

Environment variables (defaults shown):
  DOKKU_HOST   ${DOKKU_HOST}
  CF_TUNNEL    ${CF_TUNNEL}
  BASE_DOMAIN  ${BASE_DOMAIN}
EOF
}

if [[ $# -eq 0 || "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "error: expected 1 or 2 arguments, got $#" >&2
  usage >&2
  exit 1
fi

app="$1"
domain="${2:-${app}.${BASE_DOMAIN}}"
site_dir="./${app}-site"

# --- local preflight: fail before touching the remote host or dokku ---

if [[ -e "$site_dir" ]]; then
  echo "error: '${site_dir}' already exists; refusing to overwrite" >&2
  exit 1
fi

hub_template="${RENDERER_DIR}/hub.template.html"
if [[ ! -f "$hub_template" ]]; then
  echo "error: renderer hub template not found at ${hub_template}" >&2
  echo "       (expected renderer/hub.template.html alongside board.template.html)" >&2
  exit 1
fi

for f in board.css board.js; do
  if [[ ! -f "${RENDERER_DIR}/${f}" ]]; then
    echo "error: renderer asset not found at ${RENDERER_DIR}/${f}" >&2
    exit 1
  fi
done

# --- remote: dokku app + domain ---

echo "==> Creating Dokku app '${app}' on ${DOKKU_HOST}..." >&2
if ! out=$(ssh "dokku@${DOKKU_HOST}" apps:create "${app}" 2>&1); then
  if echo "$out" | grep -qi "already exists"; then
    echo "    app already exists, continuing" >&2
  else
    echo "$out" >&2
    exit 1
  fi
else
  echo "$out" >&2
fi

echo "==> Mapping domain '${domain}' to '${app}'..." >&2
if ! out=$(ssh "dokku@${DOKKU_HOST}" domains:add "${app}" "${domain}" 2>&1); then
  if echo "$out" | grep -qi "already"; then
    echo "    domain already mapped, continuing" >&2
  else
    echo "$out" >&2
    exit 1
  fi
else
  echo "$out" >&2
fi

# --- local: scaffold the site dir ---

echo "==> Scaffolding ${site_dir}..." >&2
mkdir -p "${site_dir}"

cat > "${site_dir}/Dockerfile" <<'EOF'
FROM nginx:alpine
COPY . /usr/share/nginx/html
EOF

cat > "${site_dir}/.dockerignore" <<'EOF'
.git
Dockerfile
.dockerignore
*.sh
README*
EOF

"${SCRIPT_DIR}/sync-renderer.sh" "${site_dir}"

cp "$hub_template" "${site_dir}/index.html"

echo '[]' > "${site_dir}/status.json"

# --- git init + first deploy ---

echo "==> Initializing git repo..." >&2
git -C "${site_dir}" init -b main >/dev/null
git -C "${site_dir}" add -A
git -C "${site_dir}" commit -q -m "Initial scaffold for ${app}"
git -C "${site_dir}" remote add dokku "dokku@${DOKKU_HOST}:${app}"

echo "==> Pushing first deploy..." >&2
git -C "${site_dir}" push dokku main

cat <<EOF

==> Site scaffolded at ${site_dir} and deployed.

Run this on the tunnel host (where cloudflared + cert.pem live):
  cloudflared tunnel route dns ${CF_TUNNEL} ${domain}

Once DNS resolves:
  https://${domain}/
EOF
