#!/usr/bin/env python3
"""hatchery_stacks.py — surface what hatchery declares, live, as a "Stacks"
console section: one line per service with its health, from hatchery's own
status route.

This is the boundary seam roost and hatchery agreed on: roost owns the board,
hatchery owns the stacks, and health flows hatchery to roost through this
collector instead of the board polling dokku itself. The mini reaches the
control plane over the LAN, so hatchery serve must bind an address the mini
can see (hatchery serve --bind 0.0.0.0, or the control plane's LAN address).

Config (~/.roostrc):
  ROOST_HATCHERY_BOARD=clauffice                    # board dir under the site
  ROOST_HATCHERY_URL=http://mini-reachable-host:7878
  ROOST_HATCHERY_TOKEN=...   # serve requires one when bound off-host

Non-fatal by contract: no config → skip; any failure → board untouched, exit 0.
"""
import json
import pathlib
import sys
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lib

# hatchery's health states, in board tones. Worsening states catch the eye,
# and a service hatchery has no report for is a question rather than a fault.
TONES = {"ready": "go", "responding": "go", "degraded": "you", "unreachable": "you"}


def stack_lines(stacks):
    """One console line per service, stacks in manifest order."""
    lines = []
    for stack in stacks:
        label = "{} · {} · {}".format(
            stack.get("backend", "?"), stack.get("environment", "?"),
            stack.get("host") or "managed")
        for service in stack.get("services", []):
            state = service.get("state") or "no report"
            line = {
                "status": state,
                "tone": TONES.get(state, "none"),
                "text": "{}/{}".format(stack.get("name", "?"), service.get("name", "?")),
                "meta": "· " + label,
            }
            latency = service.get("latencyMs")
            if latency is not None:
                line["meta"] += " · {}ms".format(latency)
            domains = service.get("domains") or []
            if domains:
                line["href"] = "https://" + domains[0]
            lines.append(line)
    return lines


def section(stacks, source):
    lines = stack_lines(stacks)
    return {
        "kind": "console",
        "icon": "🐣",
        "title": "Stacks",
        "desc": "what hatchery declares, live from " + source,
        "count": "{} stack(s), {} service(s)".format(len(stacks), len(lines)),
        "lines": lines,
    }


def main():
    cfg = lib.read_roostrc()
    board_dir = cfg.get("ROOST_HATCHERY_BOARD", "")
    url = cfg.get("ROOST_HATCHERY_URL", "")
    if not board_dir or not url:
        print("hatchery-stacks: ROOST_HATCHERY_URL/ROOST_HATCHERY_BOARD not configured — skipping")
        return 0
    board_path = lib.site_dir(cfg) / board_dir / "board.json"
    if not board_path.exists():
        print("hatchery-stacks: {} not found — skipping".format(board_path))
        return 0
    request = urllib.request.Request(url.rstrip("/") + "/api/status")
    token = cfg.get("ROOST_HATCHERY_TOKEN", "")
    if token:
        # serve requires the token whenever it binds off-host, which a polled serve does.
        request.add_header("X-Hatchery-Token", token)
    try:
        with urllib.request.urlopen(request, timeout=15) as answer:
            payload = json.load(answer)
    except Exception as error:  # never break a status push
        print("hatchery-stacks: {} did not answer ({}) — leaving board as-is".format(url, error))
        return 0
    stacks = payload.get("stacks") if isinstance(payload, dict) else payload
    if not isinstance(stacks, list):
        print("hatchery-stacks: unexpected payload shape — leaving board as-is")
        return 0

    board = lib.load_board(board_path)
    lib.upsert_section(board, "Stacks", section(stacks, url), after_kind="console")
    lib.save_board(board_path, board)
    print("hatchery-stacks: {} stack(s) onto {}".format(len(stacks), board_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
