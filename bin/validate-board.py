#!/usr/bin/env python3
"""Validate board.json files against the statusgen schema basics.
Usage: validate-board.py <board.json> [...]   Exits 1 on any invalid board.
"""
import json, re, sys

KINDS = {"stats", "banner", "barchart", "pie", "table", "cards", "split",
         "compare", "console", "live-console"}
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
fail = 0
for path in sys.argv[1:]:
    try:
        b = json.load(open(path))
        assert isinstance(b.get("title"), str) and b["title"], "missing title"
        assert isinstance(b.get("sections"), list), "sections must be a list"
        if "staleAfterDays" in b:
            assert isinstance(b["staleAfterDays"], (int, float)), \
                "staleAfterDays must be a number"
        for i, s in enumerate(b["sections"]):
            k = s.get("kind")
            assert k in KINDS, f"section {i}: unknown kind {k!r}"
            if "asOf" in s:
                assert isinstance(s["asOf"], str) and ISO_DATE.match(s["asOf"]), \
                    f"section {i}: asOf must be YYYY-MM-DD"
            if k == "stats":
                for it in s.get("items", []):
                    # `ts` (a UTC timestamp the renderer localizes) is an
                    # alternative to a pre-formatted `n` value.
                    assert ("n" in it or "ts" in it) and "label" in it, \
                        f"section {i}: stats items need n-or-ts + label"
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
            if k == "live-console":
                # Rows arrive at runtime from poll.url, so no `lines` here — just
                # a reachable endpoint the renderer can fetch.
                p = s.get("poll")
                assert isinstance(p, dict) and isinstance(p.get("url"), str) and p["url"], \
                    f"section {i}: live-console needs poll.url"
        # tabs — optional section grouping, keyed by section title. Structure is
        # a hard gate; a claimed title that isn't present is only a warning,
        # because a tab may legitimately name a section no collector has seeded
        # yet, and the renderer falls back to showing it pinned either way.
        if "tabs" in b:
            assert isinstance(b["tabs"], list), "tabs must be a list"
            seen_ids, claimed = set(), {}
            titles = {s.get("title") for s in b["sections"] if s.get("title")}
            for j, t in enumerate(b["tabs"]):
                assert isinstance(t, dict), f"tab {j}: must be an object"
                tid = t.get("id")
                assert isinstance(tid, str) and tid, f"tab {j}: needs a non-empty id"
                assert tid not in seen_ids, f"tab {j}: duplicate id {tid!r}"
                seen_ids.add(tid)
                assert isinstance(t.get("label"), str) and t["label"], \
                    f"tab {tid}: needs a non-empty label"
                assert isinstance(t.get("sections"), list), \
                    f"tab {tid}: sections must be a list"
                for title in t["sections"]:
                    assert isinstance(title, str), f"tab {tid}: section titles must be strings"
                    assert title not in claimed, \
                        f"tab {tid}: {title!r} already claimed by tab {claimed[title]!r}"
                    claimed[title] = tid
                    if title not in titles:
                        print(f"  ! {path}: tab {tid!r} claims absent section {title!r}")
            for title in sorted(titles - set(claimed)):
                print(f"  · {path}: section {title!r} is in no tab (renders pinned)")
        print(f"✓ {path}")
    except (AssertionError, json.JSONDecodeError, OSError) as e:
        print(f"✗ {path}: {e}")
        fail = 1
sys.exit(fail)
