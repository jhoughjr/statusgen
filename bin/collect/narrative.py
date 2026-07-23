#!/usr/bin/env python3
"""narrative.py — keep the banner's shipped timeline fresh from GitHub.

The banner is the board's dated hand-written narrative, and its weakness is
built in: the analysis deserves a human sentence, but the list of what merged
goes stale the moment the next PR lands. This collector splits the banner at a
marker line. Above the marker: hand-written prose, preserved verbatim. From
the marker down: a regenerated, timestamp-led timeline of the PRs merged into
the base branch — one line per PR, oldest first, local time:

    <hand-written lede — never touched>
    ── shipped · auto-refreshed · times CDT ──
    07-23 10:16 · #166 · SRO price edit contract, partial-code composer search
    07-23 11:53 · #168 · land the stranded confirm-sweep spec fixes

No marker in the banner yet? The block is appended below the existing text.
The window is the last ROOST_NARRATIVE_DAYS days; when that window is empty
the timeline falls back to the most recent day that had merges, so the banner
always shows the latest things that actually shipped.

Config (~/.roostrc):
  ROOST_STATS_GH_REPO=owner/repo
  ROOST_STATS_BOARD=clauffice
  ROOST_SHIPPED_BASE=dev       # optional: base branch (default dev, shared with shipped_week)
  ROOST_NARRATIVE_DAYS=2       # optional: days of merges to list (default 2)
  ROOST_NARRATIVE_MAX=20       # optional: max timeline lines (default 20)

Non-fatal by contract: any failure → board untouched, exit 0.
"""
import json
import pathlib
import subprocess
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lib

# Recognized by prefix so the timezone label can vary by machine.
MARKER_PREFIX = "── shipped ·"


# ── pure composition (tested without the network) ────────────────────────

def clean_title(title):
    """The squash-merge appends " (#123)" — the line already leads with the
    number, so drop it."""
    t = str(title).strip()
    if t.endswith(")") and " (#" in t:
        t = t[: t.rindex(" (#")].strip()
    return t


def local_dt(merged_at, tz=None):
    """GitHub's ISO-8601 UTC stamp as a local (or given-tz) datetime."""
    dt = datetime.fromisoformat(merged_at.replace("Z", "+00:00"))
    return dt.astimezone(tz)


def timeline(prs, tz=None, limit=20):
    """Timestamp-led lines, oldest first, capped at the newest `limit`."""
    ordered = sorted(prs, key=lambda p: p["mergedAt"])[-limit:]
    return [
        f"{local_dt(p['mergedAt'], tz):%m-%d %H:%M} · #{p['number']} · {clean_title(p['title'])}"
        for p in ordered
    ]


def render_block(prs, tz=None, limit=20):
    tzlabel = datetime.now(tz).astimezone(tz).strftime("%Z") or "local"
    marker = f"{MARKER_PREFIX} auto-refreshed · times {tzlabel} ──"
    return "\n".join([marker] + timeline(prs, tz, limit))


def splice(text, block):
    """Replace everything from the marker line down with `block`; append the
    block when no marker exists. Hand-written text above survives verbatim."""
    lines = (text or "").split("\n")
    for i, line in enumerate(lines):
        if line.strip().startswith(MARKER_PREFIX):
            lede = "\n".join(lines[:i]).rstrip()
            return (lede + "\n" + block) if lede else block
    lede = (text or "").rstrip()
    return (lede + "\n" + block) if lede else block


def pick_window(prs, days, now=None):
    """PRs merged in the last `days` days; when empty, the most recent local
    day that had merges — the timeline never goes blank while history exists."""
    if not prs:
        return []
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    recent = [p for p in prs if p["mergedAt"] >= since]
    if recent:
        return recent
    newest_day = max(p["mergedAt"] for p in prs)[:10]
    return [p for p in prs if p["mergedAt"][:10] == newest_day]


# ── collection ────────────────────────────────────────────────────────────

def merged_prs(slug, base):
    out = subprocess.run(
        ["gh", "pr", "list", "-R", slug, "--state", "merged", "--base", base,
         "-L", "50", "--json", "number,title,mergedAt"],
        capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError(f"gh pr list failed: {out.stderr.strip()[:200]}")
    return [p for p in json.loads(out.stdout or "[]") if p.get("mergedAt")]


def main():
    cfg = lib.read_roostrc()
    slug = cfg.get("ROOST_STATS_GH_REPO", "")
    board_dir = cfg.get("ROOST_STATS_BOARD", "")
    if not slug or not board_dir:
        print("narrative: ROOST_STATS_GH_REPO/ROOST_STATS_BOARD not configured — skipping")
        return 0
    board_path = lib.site_dir(cfg) / board_dir / "board.json"
    if not board_path.exists():
        print(f"narrative: {board_path} not found — skipping")
        return 0

    base = cfg.get("ROOST_SHIPPED_BASE", "dev")
    days = int(cfg.get("ROOST_NARRATIVE_DAYS", "2"))
    limit = int(cfg.get("ROOST_NARRATIVE_MAX", "20"))

    prs = pick_window(merged_prs(slug, base), days)
    if not prs:
        print(f"narrative: no merged PRs on {slug} — leaving banner as-is")
        return 0

    board = lib.load_board(board_path)
    for s in board.get("sections", []):
        if s.get("kind") != "banner":
            continue
        s["text"] = splice(s.get("text", ""), render_block(prs, limit=limit))
        lib.save_board(board_path, board)
        newest = max(prs, key=lambda p: p["mergedAt"])
        print(f"narrative: timeline refreshed — {len(prs)} PRs, newest #{newest['number']} {newest['mergedAt']}")
        return 0
    print("narrative: no banner section on board — nothing to patch")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # never break a status push
        print(f"narrative: non-fatal error: {e}")
        sys.exit(0)
