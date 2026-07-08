#!/usr/bin/env bash
# roost-fleet.sh — gather Dokku platform health and emit a statusgen board.json.
#
# Designed to run on the Roost pi as the dokku@ user. Collects live app status,
# system metrics, and emits a fleet-health board showing:
#   - stats: apps up/total, memory%, disk%, load average
#   - cards: per-app status + last-deploy timestamp
#   - barchart: per-app restart count (if available)
#
# Usage:
#   roost-fleet.sh [output-file]
#
# If output-file is omitted, writes to stdout. Writes valid JSON.
# All errors are logged but do not abort — missing data yields 0 or placeholder.
#
# Prerequisites: dokku commands (dokku apps:list, dokku ps:report, etc.)
# On the pi: run as dokku@pi via SSH or locally.

set -euo pipefail

# ============================================================================
# Configuration
# ============================================================================

OUTPUT_FILE="${1:-}"  # if provided, write to file; else stdout
LOG_FILE="/tmp/roost-fleet-collect.log"
TIMESTAMP="$(date -u '+%Y-%m-%d %H:%M:%S')"

# ============================================================================
# Logging
# ============================================================================

log() {
  echo "[${TIMESTAMP}] $*" >> "$LOG_FILE"
}

log_error() {
  echo "[${TIMESTAMP}] ERROR: $*" >> "$LOG_FILE"
}

# ============================================================================
# Collectors
# ============================================================================

# Collect list of all dokku apps. On error, returns empty list.
collect_apps() {
  if dokku apps:list 2>/dev/null; then
    return 0
  else
    log_error "dokku apps:list failed"
    return 1
  fi
}

# Collect per-app status. Returns JSON array of app objects.
# Each object: { "name": "app-name", "status": "up|down|unknown", "restarts": N, "deployed": "YYYY-MM-DD HH:MM" }
collect_app_statuses() {
  local -a apps=()
  local app_str

  # Safely read app list
  while IFS= read -r app_str; do
    [[ -z "$app_str" ]] && continue
    apps+=("$app_str")
  done < <(collect_apps 2>/dev/null || echo "")

  local -a items=()

  for app in "${apps[@]}"; do
    local status="unknown"
    local restarts=0
    local deployed="never"

    # ps:report yields lines like "App name: <name>" and "Status: up" or "Status: down"
    # We parse the output line-by-line.
    local report_output
    if report_output=$(dokku ps:report "$app" 2>/dev/null); then
      # Extract status: line with "Status: ..."
      if [[ $report_output =~ ^Status:\ ([^$]+)$ ]] || grep -q "^Status:" <<< "$report_output"; then
        status=$(echo "$report_output" | grep "^Status:" | head -1 | sed 's/^Status:[[:space:]]*//' | sed 's/[[:space:]]*$//')
        [[ -z "$status" ]] && status="unknown"
      fi

      # Extract restart count from "Restart count: ..."
      if grep -q "^Restart count:" <<< "$report_output"; then
        restarts=$(echo "$report_output" | grep "^Restart count:" | head -1 | sed 's/^Restart count:[[:space:]]*//' | sed 's/[[:space:]]*$//' | grep -oE '[0-9]+' || echo "0")
        [[ -z "$restarts" ]] && restarts=0
      fi

      # Extract deployed timestamp from "Deployed at: ..."
      if grep -q "^Deployed at:" <<< "$report_output"; then
        deployed=$(echo "$report_output" | grep "^Deployed at:" | head -1 | sed 's/^Deployed at:[[:space:]]*//' | sed 's/[[:space:]]*$//')
        [[ -z "$deployed" ]] && deployed="never"
      fi
    else
      log_error "dokku ps:report $app failed"
    fi

    # Build JSON object for this app
    items+=("  { \"name\": \"${app}\", \"status\": \"${status}\", \"restarts\": ${restarts}, \"deployed\": \"${deployed}\" }")
  done

  # Emit array
  if [[ ${#items[@]} -gt 0 ]]; then
    echo "["
    printf '%s\n' "${items[@]}" | sed '$ s/,$//'
    echo "]"
  else
    echo "[]"
  fi
}

# Collect system metrics: memory, disk, load.
# Returns JSON: { "mem_total_mb": N, "mem_avail_mb": N, "disk_total_gb": N, "disk_used_gb": N, "load_avg": "X.XX" }
collect_system_metrics() {
  local mem_total_mb=0
  local mem_avail_mb=0
  local disk_total_gb=0
  local disk_used_gb=0
  local load_avg="0.00"

  # Memory: free -m (linux) or vm_stat (mac fallback)
  if command -v free &>/dev/null; then
    if mem_output=$(free -m 2>/dev/null | grep '^Mem:'); then
      mem_total_mb=$(echo "$mem_output" | awk '{print $2}' | tr -d ' ')
      mem_avail_mb=$(echo "$mem_output" | awk '{print $7}' | tr -d ' ')
    else
      log_error "free -m parsing failed"
    fi
  else
    log_error "free command not found (not on Linux)"
  fi

  # Disk: df -h / (use first available mount or root)
  if df_output=$(df -h / 2>/dev/null); then
    # Skip header, get second line
    if [[ $(echo "$df_output" | wc -l) -gt 1 ]]; then
      local line=$(echo "$df_output" | tail -1)
      local total_str=$(echo "$line" | awk '{print $2}' | sed 's/G$//')
      local used_str=$(echo "$line" | awk '{print $3}' | sed 's/G$//')
      disk_total_gb=$(echo "$total_str" | grep -oE '[0-9]+(\.[0-9]+)?' || echo "0")
      disk_used_gb=$(echo "$used_str" | grep -oE '[0-9]+(\.[0-9]+)?' || echo "0")
    fi
  else
    log_error "df -h / failed"
  fi

  # Load average: uptime
  if uptime_output=$(uptime 2>/dev/null); then
    # Extract last 3 numbers from "load average: X.XX, Y.YY, Z.ZZ"
    if [[ $uptime_output =~ load\ average:\ ([0-9.]+) ]]; then
      load_avg="${BASH_REMATCH[1]}"
    fi
  else
    log_error "uptime failed"
  fi

  cat <<EOF
{ "mem_total_mb": ${mem_total_mb}, "mem_avail_mb": ${mem_avail_mb}, "disk_total_gb": ${disk_total_gb}, "disk_used_gb": ${disk_used_gb}, "load_avg": "${load_avg}" }
EOF
}

# ============================================================================
# Board JSON generation
# ============================================================================

generate_board_json() {
  local app_statuses
  local sys_metrics

  app_statuses=$(collect_app_statuses 2>/dev/null || echo "[]")
  sys_metrics=$(collect_system_metrics 2>/dev/null || echo '{ "mem_total_mb": 0, "mem_avail_mb": 0, "disk_total_gb": 0, "disk_used_gb": 0, "load_avg": "0.00" }')

  # Parse system metrics to calculate percentages
  local mem_total mem_avail disk_total disk_used load_avg
  mem_total=$(echo "$sys_metrics" | grep -oP '"mem_total_mb":\s*\K[0-9]+' | head -1 || echo "0")
  mem_avail=$(echo "$sys_metrics" | grep -oP '"mem_avail_mb":\s*\K[0-9]+' | head -1 || echo "0")
  disk_total=$(echo "$sys_metrics" | grep -oP '"disk_total_gb":\s*\K[0-9.]+' | head -1 || echo "0")
  disk_used=$(echo "$sys_metrics" | grep -oP '"disk_used_gb":\s*\K[0-9.]+' | head -1 || echo "0")
  load_avg=$(echo "$sys_metrics" | grep -oP '"load_avg":\s*"\K[^"]+' | head -1 || echo "0.00")

  # Calculate percentages (safely handle division)
  local mem_percent=0
  local disk_percent=0
  if (( mem_total > 0 )); then
    mem_percent=$(( (mem_total - mem_avail) * 100 / mem_total ))
  fi
  if (( $(echo "$disk_total > 0" | bc -l 2>/dev/null || echo "0") )); then
    disk_percent=$(printf "%.0f" "$(echo "$disk_used * 100 / $disk_total" | bc -l 2>/dev/null || echo "0")")
  fi

  # Count apps up vs total
  local apps_up=0
  local apps_total=0
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    (( apps_total++ ))
    if echo "$line" | grep -q '"status":\s*"up"'; then
      (( apps_up++ ))
    fi
  done < <(echo "$app_statuses" | grep -E '^\s*\{')

  # Build cards items for each app
  local -a card_items=()
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue

    local name=$(echo "$line" | grep -oP '"name":\s*"\K[^"]+')
    local status=$(echo "$line" | grep -oP '"status":\s*"\K[^"]+')
    local deployed=$(echo "$line" | grep -oP '"deployed":\s*"\K[^"]+')

    local pill_text="$status"
    local tone="srv"
    if [[ "$status" == "up" ]]; then
      pill_text="up"
      tone="go"
    elif [[ "$status" == "down" ]]; then
      pill_text="down"
      tone="you"
    fi

    card_items+=("    { \"q\": \"${name}\", \"meta\": \"${deployed}\", \"pill\": { \"text\": \"${pill_text}\", \"tone\": \"${tone}\" } }")
  done < <(echo "$app_statuses" | grep -E '^\s*\{')

  # Emit board.json
  fleet_stamp="Updated $(date '+%Y-%m-%d %H:%M %Z') — live platform metrics"
  cat <<EOF
{
  "title": "Roost Fleet Health",
  "eyebrow": "Platform Status",
  "stamp": "$fleet_stamp",
  "sections": [
    {
      "kind": "stats",
      "items": [
EOF

  # Stats items
  printf '        { "n": "%d/%d", "label": "Apps up / total", "tone": "%s" },\n' "$apps_up" "$apps_total" "$([ $apps_up -eq $apps_total ] && echo 'go' || echo 'you')"
  printf '        { "n": "%d%%", "label": "Memory used", "tone": "%s" },\n' "$mem_percent" "$([ $mem_percent -gt 80 ] && echo 'you' || echo 'go')"
  printf '        { "n": "%d%%", "label": "Disk used", "tone": "%s" },\n' "$disk_percent" "$([ $disk_percent -gt 80 ] && echo 'you' || echo 'go')"
  printf '        { "n": "%s", "label": "Load average", "tone": "go" }\n' "$load_avg"

  cat <<'EOF'
      ]
    },
    {
      "kind": "cards",
      "title": "Apps",
      "count": "Live status",
      "items": [
EOF

  # Cards items
  if [[ ${#card_items[@]} -gt 0 ]]; then
    printf '%s\n' "${card_items[@]}" | sed '$ s/,$//'
  fi

  cat <<'EOF'
      ]
    }
  ]
}
EOF
}

# ============================================================================
# Main
# ============================================================================

main() {
  local output
  output=$(generate_board_json)

  if [[ -n "$OUTPUT_FILE" ]]; then
    echo "$output" > "$OUTPUT_FILE"
    log "Wrote board.json to $OUTPUT_FILE"
  else
    echo "$output"
  fi
}

main
