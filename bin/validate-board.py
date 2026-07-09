#!/usr/bin/env python3
"""Validate board.json files against the statusgen schema basics.
Usage: validate-board.py <board.json> [...]   Exits 1 on any invalid board.
"""
import json, sys

KINDS = {"stats", "banner", "barchart", "pie", "table", "cards", "split",
         "compare", "console"}
fail = 0
for path in sys.argv[1:]:
    try:
        b = json.load(open(path))
        assert isinstance(b.get("title"), str) and b["title"], "missing title"
        assert isinstance(b.get("sections"), list), "sections must be a list"
        for i, s in enumerate(b["sections"]):
            k = s.get("kind")
            assert k in KINDS, f"section {i}: unknown kind {k!r}"
            if k == "stats":
                for it in s.get("items", []):
                    assert "n" in it and "label" in it, f"section {i}: stats items need n+label"
            if k == "cards":
                for it in s.get("items", []):
                    assert "q" in it, f"section {i}: cards items need q"
                    if "pill" in it:
                        assert isinstance(it["pill"], dict) and "text" in it["pill"], \
                            f"section {i}: pill must be {{text, tone}}"
            if k == "split":
                assert "columns" in s, f"section {i}: split needs columns"
            if k == "compare":
                assert isinstance(s.get("columns"), list) and s["columns"], \
                    f"section {i}: compare needs columns"
                for c in s["columns"]:
                    for it in c.get("items", []):
                        assert "n" in it and "label" in it, \
                            f"section {i}: compare items need n+label"
            if k == "console":
                assert isinstance(s.get("lines"), list), f"section {i}: console needs lines"
                for ln in s["lines"]:
                    assert "text" in ln, f"section {i}: console lines need text"
        print(f"✓ {path}")
    except (AssertionError, json.JSONDecodeError, OSError) as e:
        print(f"✗ {path}: {e}")
        fail = 1
sys.exit(fail)
