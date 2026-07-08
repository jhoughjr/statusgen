# Roost Fleet-Health Collector

`roost-fleet.sh` gathers live Dokku platform metrics from the Roost pi and emits a statusgen `board.json` showing fleet health.

## What it collects

- **App inventory & status**: `dokku apps:list` + per-app `dokku ps:report` → app names, up/down status, restart counts, deployed timestamps
- **System metrics**: `free -m`, `df -h /`, `uptime` → memory usage %, disk usage %, load average
- **Board sections emitted**:
  - `stats`: apps up/total, memory%, disk%, load (tiles with tones: green if healthy, amber if stressed)
  - `cards`: one row per app with name, last-deploy timestamp, and status pill (green for up, amber for down)

## Prerequisites

- Dokku installed on the host with apps deployed
- SSH access to the Dokku host as the `dokku@` user (or local access if running on the pi)
- `free`, `df`, `uptime` available on the host (standard Linux/Unix)

## Usage

### On the Roost pi (as dokku@)

```bash
# Write to a file (e.g. for use in a status-site board)
ssh dokku@roost.local bin/collect/roost-fleet.sh > /tmp/fleet-metrics.json

# Or run directly on the pi:
bin/collect/roost-fleet.sh /path/to/status-site/fleet/board.json
```

### Integrating with a status board

1. Create a fleet board in your status-site:
   ```bash
   bin/new-board.sh status-site fleet "Fleet Health" "Live platform metrics"
   ```

2. Manually run the collector and write its output to the board:
   ```bash
   bin/collect/roost-fleet.sh status-site/fleet/board.json
   ```

3. Commit and deploy:
   ```bash
   bin/update.sh status-site fleet
   ```

### Automating collection

To auto-refresh the fleet board at an interval, wrap the collector in a cron job on the pi:

```bash
# /etc/cron.d/statusgen-fleet (or in crontab)
*/5 * * * * dokku /path/to/statusgen/bin/collect/roost-fleet.sh /path/to/status-site/fleet/board.json && cd /path/to/status-site && git add fleet/board.json && git commit -m "auto: fleet metrics" && git push dokku main
```

## Defensive design

The script is written to **not fail if any single command fails**:

- If `dokku apps:list` fails, apps list is empty (no crash).
- If `dokku ps:report <app>` fails, that app gets status "unknown" and restarts=0.
- If system metrics are unavailable, they default to 0 or placeholder values.
- All errors are logged to `/tmp/roost-fleet-collect.log`.

Missing data yields placeholder values (0, "unknown", "never"); the board always emits valid JSON.

## Output schema

The emitted `board.json` matches the statusgen schema (see `BOARD_SCHEMA.md`):

```json
{
  "title": "Roost Fleet Health",
  "eyebrow": "Platform Status",
  "stamp": "Updated YYYY-MM-DD HH:MM:SS — live platform metrics",
  "sections": [
    {
      "kind": "stats",
      "items": [
        { "n": "3/5", "label": "Apps up / total", "tone": "go" },
        { "n": "42%", "label": "Memory used", "tone": "go" },
        { "n": "65%", "label": "Disk used", "tone": "go" },
        { "n": "1.23", "label": "Load average", "tone": "go" }
      ]
    },
    {
      "kind": "cards",
      "title": "Apps",
      "count": "Live status",
      "items": [
        { "q": "app-name-1", "meta": "2026-07-08 10:30:45", "pill": { "text": "up", "tone": "go" } },
        { "q": "app-name-2", "meta": "never", "pill": { "text": "down", "tone": "you" } }
      ]
    }
  ]
}
```

## Testing

Syntax check (no dependencies required):
```bash
bash -n bin/collect/roost-fleet.sh
```

Full test requires Dokku and a pihost — run on the pi itself.

## Limitations

- **Untested locally** (requires Dokku): this script is designed for the Roost pi environment. Syntax passes, but runtime behavior depends on `dokku` command availability.
- **Linux only** (for now): uses `free` and `df`. macOS/BSD would need `vm_stat` fallback (see `collect_system_metrics` function).
- **Per-app drill-down**: currently shows status summary; detailed app logs/errors would require additional `dokku logs` parsing.
