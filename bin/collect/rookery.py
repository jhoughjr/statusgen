#!/usr/bin/env python3
"""rookery.py — surface seats and their state from rookery as a board section.

A seat is one role, one worktree, one claude process.
This collector fetches current seats from rookery's /api/work endpoint and renders a Seats section showing each seat's role, state, execution mode, and which runner took it.

Config (~/.roostrc):
  ROOST_ROOKERY_BOARD=clauffice                # board dir under the site
  ROOST_ROOKERY_URL=https://rookery.jimmyhoughjr.net
  ROOST_ROOKERY_TOKEN=...                      # required for auth

Non-fatal by contract: no config → skip; any failure → board untouched, exit 0.
"""
import json
import pathlib
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lib

TONES = {
    "queued": "wip",
    "starting": "wip",
    "running": "wip",
    "blocked": "you",
    "finished": "go",
    "failed": "err",
}


def fetch_json(url, token):
    """Fetch JSON from a URL with bearer token auth. Raises on failure.

    The agent is named because the edge refuses the default one that python-urllib sends. Cloudflare answers 403 to it,
    which reads as rookery refusing the credential when rookery never saw the request.
    """
    request = urllib.request.Request(url, headers={"User-Agent": "roost-rookery-collector"})
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.reason}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"URL error: {e.reason}")


def seat_lines(assignments):
    """One console line per seat from the assignments list.
    Seats are folded into each assignment in /api/work, so extract and flatten them."""
    lines = []
    for assignment in assignments:
        seats = assignment.get("seats", [])
        for seat in seats:
            state = seat.get("state", "?")
            execution = seat.get("execution", "?")
            runner = seat.get("runner", "")
            agent = seat.get("agent", "")
            role = seat.get("role", "?")
            exit_code = seat.get("exitCode")

            # Build meta line showing where it ran and what exit code if failed.
            meta_parts = [execution]
            if runner:
                meta_parts.append(f"runner {runner}")
            if state == "failed" and exit_code is not None:
                meta_parts.append(f"exit {exit_code}")
            meta = "· " + " · ".join(meta_parts)

            # Include agent in text when present.
            text = role
            if agent:
                text = f"{role} ({agent})"

            line = {
                "status": state,
                "tone": TONES.get(state, "none"),
                "text": text,
                "meta": meta,
            }

            # Hosted seats run on the control plane, not on a runner machine.
            if execution == "hosted":
                line["meta"] = meta.replace("· hosted", "· hosted (control plane)")

            lines.append(line)
    return lines


def section(assignments, source):
    """Build a Seats console section from the /api/work assignments."""
    lines = seat_lines(assignments)
    return {
        "kind": "console",
        "icon": "🪑",
        "title": "Seats",
        "desc": f"active work, from {source}",
        "count": f"{len(lines)} seat(s)",
        "lines": lines,
    }


def main():
    cfg = lib.read_roostrc()
    board_dir = cfg.get("ROOST_ROOKERY_BOARD", "")
    url = cfg.get("ROOST_ROOKERY_URL", "").rstrip("/")
    token = cfg.get("ROOST_ROOKERY_TOKEN", "")

    if not board_dir or not url:
        print("rookery: ROOST_ROOKERY_BOARD/URL not configured — skipping")
        return 0

    board_path = lib.site_dir(cfg) / board_dir / "board.json"
    if not board_path.exists():
        print(f"rookery: {board_path} not found — skipping")
        return 0

    # Fetch assignments (which contain seats) from /api/work.
    try:
        payload = fetch_json(f"{url}/api/work", token)
        # The route answers an envelope, `{"assignments": [...], "can": ...}`, and the seats are folded into each
        # assignment. `can` says what this caller may do, which the board does not draw.
        assignments = payload.get("assignments") if isinstance(payload, dict) else payload
        if not isinstance(assignments, list):
            print("rookery: unexpected /api/work payload shape - leaving board as-is")
            return 0
    except Exception as error:
        print(f"rookery: {url}/api/work did not answer ({error}) — leaving board as-is")
        return 0

    board = lib.load_board(board_path)
    lib.upsert_section(board, "Seats", section(assignments, url), after_kind="compare")
    lib.save_board(board_path, board)
    seat_count = sum(len(a.get("seats", [])) for a in assignments)
    print(f"rookery: {seat_count} seat(s) onto {board_path}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"rookery: non-fatal error: {e}")
        sys.exit(0)
