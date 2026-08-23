#!/usr/bin/env python3
"""Validate board.json files against the statusgen widget schema.
Usage: validate-board.py <board.json> [...]   Exits 1 on any invalid board.

The field surface lives in bin/widgets.schema.json, one entry per kind and one entry per field.
This script walks that spec and keeps the checks the spec cannot express (banner prose, n-or-ts, tabs).
A `hard` finding fails the deploy gate. A `soft` finding prints a warning and the board still deploys,
because `roost status` aborts the whole site deploy on a hard failure, so a new rule must prove itself green on the live boards first.
"""
import json, pathlib, re, sys

SPEC = json.load(open(pathlib.Path(__file__).resolve().parent / "widgets.schema.json"))
KINDS = set(SPEC["kinds"])
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# `scalar` covers a value the renderer prints as-is, so both "1196" and 1196 are legal.
TYPES = {
    "str": str,
    "num": (int, float),
    "bool": bool,
    "list": list,
    "obj": dict,
    "scalar": (str, int, float),
}

# A banner renders as ONE flat <div> — no headings, no rows, no pills. It is the
# only kind with nowhere for a reader's eye to land, so it is the only kind that
# can silently become a wall. Everything a long banner wants to say is already
# expressible as a `cards` section (per-item headline + note + pill), which is
# scannable by construction.
#
# `narrative.py` preserves the prose above the `── shipped ·` marker verbatim, so
# nothing downstream trims it and nothing warns. These are the guard rails: a
# warning, never a hard fail — a board must always be able to deploy.
BANNER_MARKER = "── shipped ·"
BANNER_MAX_CHARS = 700       # ~a tight paragraph: a lede, not a write-up
BANNER_MAX_SENTENCES = 5
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def banner_prose(text):
    """The hand-written part of a banner — everything above the machine-written
    shipped block, which is line-broken already and scans fine."""
    return str(text or "").split(BANNER_MARKER)[0].strip()


def banner_warnings(text):
    """Structural complaints about one banner's prose. Empty when it reads as a
    lede. Each is phrased as the fix, not the violation — the reader is usually
    an agent about to rewrite it."""
    prose = banner_prose(text)
    if not prose:
        return []
    out = []
    paragraphs = [p for p in prose.split("\n\n") if p.strip()]
    sentences = [s for s in SENTENCE_END.split(prose) if s.strip()]
    if len(prose) > BANNER_MAX_CHARS:
        out.append(
            f"banner prose is {len(prose)} chars (guide: {BANNER_MAX_CHARS}) — keep the lede, "
            f"move the detail into a `cards` section so each point gets a headline and a pill")
    if len(sentences) > BANNER_MAX_SENTENCES:
        out.append(
            f"banner prose is {len(sentences)} sentences (guide: {BANNER_MAX_SENTENCES}) — "
            f"one banner is one flat <div>; a reader has no way to scan past sentence three")
    if len(prose) > BANNER_MAX_CHARS and len(paragraphs) == 1:
        out.append(
            "banner prose has no paragraph break — the renderer honours \\n\\n "
            "(white-space: pre-line), so nothing but the text itself is stopping it")
    return out


def _check_fields(obj, fields, where, errors, warnings):
    """Walk one object against one `fields` spec: required presence, then type, then any per-element `item` spec."""
    for name, fs in fields.items():
        need_hard = fs.get("need") == "hard"
        if name not in obj:
            if fs.get("required"):
                msg = f"{where}: missing {name}"
                (errors if need_hard else warnings).append(msg)
            continue
        val = obj[name]
        want = TYPES[fs["type"]]
        # bool is an int subclass in Python, so a bare isinstance check would pass True as a num.
        mistyped = isinstance(val, bool) and fs["type"] not in ("bool",) or not isinstance(val, want)
        if mistyped:
            msg = f"{where}: {name} must be {fs['type']}"
            (errors if need_hard else warnings).append(msg)
            continue
        item_spec = fs.get("item")
        if item_spec and isinstance(val, list):
            for j, element in enumerate(val):
                if not isinstance(element, dict):
                    warnings.append(f"{where}: {name}[{j}] should be an object")
                    continue
                _check_fields(element, item_spec["fields"], f"{where}: {name}[{j}]", errors, warnings)


def _check_unknown(obj, known, where, warnings):
    """The typo catcher: the renderer drops a misspelled field without a sound, so name what it will ignore."""
    for name in obj:
        if name not in known:
            warnings.append(f"{where}: unknown field {name!r} (the renderer ignores it)")


def validate_section(s, i, errors, warnings):
    """One section against its kind's spec plus the checks the spec cannot express."""
    k = s.get("kind")
    if k not in KINDS:
        errors.append(f"section {i}: unknown kind {k!r}")
        return
    where = f"section {i} ({k})"
    common = SPEC["sectionCommon"]["fields"]
    kind_fields = SPEC["kinds"][k]["fields"]
    _check_fields(s, common, where, errors, warnings)
    _check_fields(s, kind_fields, where, errors, warnings)
    _check_unknown(s, set(common) | set(kind_fields), where, warnings)

    if "asOf" in s:
        if not (isinstance(s["asOf"], str) and ISO_DATE.match(s["asOf"])):
            errors.append(f"{where}: asOf must be YYYY-MM-DD")
    if k == "banner":
        for w in banner_warnings(s.get("text")):
            warnings.append(f"{where}: {w}")
    if k == "stats":
        for j, it in enumerate(s.get("items") or []):
            # `ts` (a UTC timestamp the renderer localizes) is an alternative to a pre-formatted `n` value.
            if isinstance(it, dict) and "n" not in it and "ts" not in it:
                errors.append(f"{where}: items[{j}] needs n or ts")
    if k == "cards":
        # The renderer reads `pill.pill ?? pill.text`, so either key carries the label.
        for j, it in enumerate(s.get("items") or []):
            if isinstance(it, dict) and "pill" in it and not (
                    isinstance(it["pill"], dict) and ("text" in it["pill"] or "pill" in it["pill"])):
                errors.append(f"{where}: items[{j}]: pill must be {{text|pill, tone}}")
    if k == "compare":
        if isinstance(s.get("columns"), list) and not s["columns"]:
            errors.append(f"{where}: columns must not be empty")
    if k == "live-console":
        # Rows arrive at runtime from poll.url, so no `lines` here — just
        # a reachable endpoint the renderer can fetch.
        p = s.get("poll")
        if isinstance(p, dict) and not (isinstance(p.get("url"), str) and p["url"]):
            errors.append(f"{where}: live-console needs poll.url")


def validate_tabs(b, errors, warnings, notes):
    """tabs — optional section grouping, keyed by section title. Structure is
    a hard gate; a claimed title that isn't present is only a warning,
    because a tab may legitimately name a section no collector has seeded
    yet, and the renderer falls back to showing it pinned either way."""
    seen_ids, claimed = set(), {}
    titles = {s.get("title") for s in b.get("sections", []) if isinstance(s, dict) and s.get("title")}
    for j, t in enumerate(b["tabs"]):
        if not isinstance(t, dict):
            errors.append(f"tab {j}: must be an object")
            continue
        tid = t.get("id")
        if not (isinstance(tid, str) and tid):
            errors.append(f"tab {j}: needs a non-empty id")
            continue
        if tid in seen_ids:
            errors.append(f"tab {j}: duplicate id {tid!r}")
            continue
        seen_ids.add(tid)
        if not (isinstance(t.get("label"), str) and t["label"]):
            errors.append(f"tab {tid}: needs a non-empty label")
        if not isinstance(t.get("sections"), list):
            errors.append(f"tab {tid}: sections must be a list")
            continue
        for title in t["sections"]:
            if not isinstance(title, str):
                errors.append(f"tab {tid}: section titles must be strings")
                continue
            if title in claimed:
                errors.append(f"tab {tid}: {title!r} already claimed by tab {claimed[title]!r}")
                continue
            claimed[title] = tid
            if title not in titles:
                warnings.append(f"tab {tid!r} claims absent section {title!r}")
    for title in sorted(titles - set(claimed)):
        notes.append(f"section {title!r} is in no tab (renders pinned)")


def validate_board(b):
    """Every finding for one parsed board, split by consequence:
    errors fail the gate, warnings print, notes are informational."""
    errors, warnings, notes = [], [], []
    if not isinstance(b, dict):
        return ["board must be an object"], warnings, notes
    board_fields = SPEC["board"]["fields"]
    _check_fields(b, board_fields, "board", errors, warnings)
    _check_unknown(b, set(board_fields), "board", warnings)
    if isinstance(b.get("sections"), list):
        for i, s in enumerate(b["sections"]):
            if not isinstance(s, dict):
                errors.append(f"section {i}: must be an object")
                continue
            validate_section(s, i, errors, warnings)
    if isinstance(b.get("tabs"), list):
        validate_tabs(b, errors, warnings, notes)
    return errors, warnings, notes


def main(argv):
    fail = 0
    for path in argv:
        try:
            b = json.load(open(path))
        except (json.JSONDecodeError, OSError) as e:
            print(f"✗ {path}: {e}")
            fail = 1
            continue
        errors, warnings, notes = validate_board(b)
        for w in warnings:
            print(f"  ! {path}: {w}")
        for n in notes:
            print(f"  · {path}: {n}")
        if errors:
            for e in errors:
                print(f"✗ {path}: {e}")
            fail = 1
        else:
            print(f"✓ {path}")
    return fail


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
