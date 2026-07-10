#!/usr/bin/env python3
"""api_consumption.py — regenerate the board's "API consumption" → "Consumed" column
from actual performWith() call sites in the Phoenix-Electron clone, so the list can't go stale.

Counts performWith() invocations per API surface and creates one item per surface.

Config (~/.roostrc):
  ROOST_STATS_REPO_DIR=~/repos/Phoenix-Electron     # path to Phoenix clone
  ROOST_STATS_BOARD=clauffice                        # board dir

Non-fatal by contract: any failure → board untouched, exit 0.
"""
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lib

SECTION = "API consumption"
COLUMN = "Consumed"

# Surfaces whose camelCase split reads awkwardly on the board.
ALIASES = {"Po": "Purchase Order", "Gsx": "GSX"}


def split_camel_case(s):
    """Split camelCase into words with spaces (InventoryProductItem → Inventory Product Item)."""
    return re.sub(r'(?<!^)(?=[A-Z])', ' ', s)


def display_name(api_name):
    """Board label for an API surface: alias if defined, else camelCase split."""
    return ALIASES.get(api_name, split_camel_case(api_name))


def scan_phoenix_for_api_calls(repo_dir):
    """
    Recursively scan src/**/*.ts and src/**/*.tsx for performWith() calls.
    Returns dict: {api_surface_name: count, ...}
    """
    repo_path = pathlib.Path(repo_dir)
    src_path = repo_path / "src"

    if not src_path.exists():
        return {}

    api_calls = {}
    pattern = re.compile(r'performWith\s*\(\s*(\w+?)Api\b')

    # Recursively find all .ts and .tsx files
    for ts_file in src_path.rglob("*.ts"):
        # Skip generated files and test files
        if "/generated" in str(ts_file) or ts_file.name.endswith((".test.ts", ".dom.test.ts")):
            continue

        try:
            content = ts_file.read_text(encoding="utf-8", errors="ignore")
            for match in pattern.finditer(content):
                api_name = match.group(1)
                api_calls[api_name] = api_calls.get(api_name, 0) + 1
        except Exception:
            # Skip files we can't read
            pass

    for tsx_file in src_path.rglob("*.tsx"):
        # Skip generated files and test files
        if "/generated" in str(tsx_file) or tsx_file.name.endswith((".test.tsx", ".dom.test.tsx")):
            continue

        try:
            content = tsx_file.read_text(encoding="utf-8", errors="ignore")
            for match in pattern.finditer(content):
                api_name = match.group(1)
                api_calls[api_name] = api_calls.get(api_name, 0) + 1
        except Exception:
            # Skip files we can't read
            pass

    return api_calls


def build_items(api_calls):
    """Build board items from api_calls dict, sorted by count descending."""
    if not api_calls:
        return None  # Treat zero surfaces as scan failure

    items = []
    for api_name in sorted(api_calls.keys(), key=lambda k: api_calls[k], reverse=True):
        count = api_calls[api_name]
        items.append({
            "text": f"{display_name(api_name)} — {count} call site{'s' if count != 1 else ''}"
        })

    return items


def main():
    cfg = lib.read_roostrc()
    repo_dir = cfg.get("ROOST_STATS_REPO_DIR", "")
    board_dir = cfg.get("ROOST_STATS_BOARD", "")

    if not repo_dir or not board_dir:
        print("api-consumption: ROOST_STATS_REPO_DIR/ROOST_STATS_BOARD not configured — skipping")
        return 0

    repo_path = pathlib.Path(repo_dir)
    if not repo_path.exists():
        print(f"api-consumption: {repo_dir} not found — skipping")
        return 0

    board_path = lib.site_dir(cfg) / board_dir / "board.json"
    if not board_path.exists():
        print(f"api-consumption: {board_path} not found — skipping")
        return 0

    # Scan for API calls
    api_calls = scan_phoenix_for_api_calls(repo_dir)
    items = build_items(api_calls)

    if items is None:
        print("api-consumption: no API surfaces found (scan may have failed) — leaving section as-is")
        return 0

    # Load and update board
    board = lib.load_board(board_path)
    for s in board.get("sections", []):
        if s.get("title") != SECTION:
            continue

        # Find the "Consumed" column
        columns = s.get("columns", [])
        for col in columns:
            if col.get("h3") == COLUMN:
                col["items"] = items
                lib.save_board(board_path, board)
                api_names = ', '.join([c.get("text", "").split(" — ")[0] for c in items[:5]])
                if len(items) > 5:
                    api_names += f", ... ({len(items)} total)"
                print(f"api-consumption: {len(api_calls)} API surfaces, {len(items)} items: {api_names}")
                return 0

        # Column not found
        print(f"api-consumption: no '{COLUMN}' column in '{SECTION}' section — nothing to patch")
        return 0

    print(f"api-consumption: no '{SECTION}' section on board — nothing to patch")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # never break a status push
        print(f"api-consumption: non-fatal error: {e}")
        sys.exit(0)
