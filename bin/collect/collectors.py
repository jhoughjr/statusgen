#!/usr/bin/env python3
"""collectors.py — render collector run records as a board section.

Displays the status of each collector from a run-record file written by roost.
One line per collector shows its name, success/failure, duration, and age.
Failing collectors are visually distinct.

Config (~/.roostrc):
  ROOST_COLLECTOR_LOG=<path>  # path to roost-collectors.json, defaults to ${XDG_STATE_HOME:-$HOME/.local/state}/roost-collectors.json

Non-fatal by contract: no config or no file means skip; any failure → board untouched, exit 0.
"""
import json
import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lib


def collector_log_path(cfg):
    """Path to the collector run log from config or default location."""
    if "ROOST_COLLECTOR_LOG" in cfg:
        return pathlib.Path(cfg["ROOST_COLLECTOR_LOG"])
    xdg_state = os.environ.get("XDG_STATE_HOME")
    if not xdg_state:
        xdg_state = os.path.expanduser("~/.local/state")
    return pathlib.Path(xdg_state) / "roost-collectors.json"


def load_run_record(path):
    """Load and parse the run record file. Raises on JSON parse error."""
    with open(path) as fh:
        return json.load(fh)


def age_ms(now_ms, event_ms):
    """Time since event in milliseconds."""
    return max(0, now_ms - event_ms)


def format_age(age_ms_val):
    """Format age in milliseconds as human-readable text."""
    if age_ms_val < 1000:
        return f"{age_ms_val}ms"
    seconds = age_ms_val / 1000
    if seconds < 60:
        return f"{int(seconds)}s"
    minutes = seconds / 60
    if minutes < 60:
        return f"{int(minutes)}m"
    hours = minutes / 60
    if hours < 24:
        return f"{int(hours)}h"
    days = hours / 24
    return f"{int(days)}d"


def collector_lines(record, now_ms):
    """One console line per collector from the run record.
    Each line shows name, status, duration, and age."""
    lines = []
    for run in record.get("runs", []):
        name = run.get("name", "?")
        ok = run.get("ok", False)
        ms = run.get("ms", 0)
        at = run.get("at", now_ms)
        exit_code = run.get("exit")

        status = "success" if ok else "failure"
        tone = "go" if ok else "err"

        age = age_ms(now_ms, at)
        age_text = format_age(age)

        meta_parts = [f"{int(ms)}ms"]
        meta_parts.append(age_text)
        if not ok and exit_code is not None:
            meta_parts.append(f"exit {exit_code}")
        meta = "· " + " · ".join(meta_parts)

        line = {
            "status": status,
            "tone": tone,
            "text": name,
            "meta": meta,
        }
        lines.append(line)
    return lines


def section(record, now_ms):
    """Build a Collectors console section from the run record."""
    lines = collector_lines(record, now_ms)
    passed = sum(1 for r in record.get("runs", []) if r.get("ok", False))
    total = len(record.get("runs", []))

    status_text = f"{passed}/{total} passed"
    if total == 0:
        status_text = "no runs"

    return {
        "kind": "console",
        "icon": "🧩",
        "title": "Collectors",
        "desc": "status of each collector",
        "count": status_text,
        "lines": lines,
    }


def main():
    cfg = lib.read_roostrc()
    log_path = collector_log_path(cfg)

    if not log_path.exists():
        print(f"collectors: {log_path} not found — skipping")
        return 0

    board_path = lib.site_dir(cfg) / "board.json"
    if not board_path.exists():
        print(f"collectors: {board_path} not found — skipping")
        return 0

    try:
        record = load_run_record(log_path)
        if not isinstance(record, dict):
            print("collectors: unexpected log file shape — leaving board as-is")
            return 0
    except json.JSONDecodeError as error:
        print(f"collectors: {log_path} is malformed JSON — leaving board as-is")
        return 0
    except Exception as error:
        print(f"collectors: {log_path} could not be read ({error}) — leaving board as-is")
        return 0

    if "at" not in record:
        print("collectors: log record missing 'at' timestamp — leaving board as-is")
        return 0

    now_ms = int(time.time() * 1000)
    board = lib.load_board(board_path)
    lib.upsert_section(board, "Collectors", section(record, now_ms), after_kind="console")
    lib.save_board(board_path, board)

    run_count = len(record.get("runs", []))
    print(f"collectors: {run_count} collector(s) onto {board_path}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"collectors: non-fatal error: {e}")
        sys.exit(0)
