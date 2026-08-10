#!/usr/bin/env python3
"""wayfinder.py — render the Clauffice wayfinder planning state onto the board.

A wayfinder map is a decision-ticket map on the Clauffice issue tracker. The tracker shows
what moved; nothing showed where the planning stands — which tickets are takeable now, which
are blocked behind an open decision, and how much is still fog. This collector adds that.

The numbers come straight off the GitHub issue tracker through `gh`, so the collector needs no
clone and no checkout of any particular branch.

Sections written (each upserted by title, so hand edits elsewhere on the board survive):
  Wayfinder                   stats  — the counts, one tile per bucket
  Frontier — takeable now     cards  — the tickets a session can pick up right now
  In flight & blocked         cards  — who holds what, and what each blocked ticket waits on
  Beyond the tickets          split  — the fog and the out-of-scope rulings, collapsed
  Map hygiene                 cards  — only when a check fires, removed when both are clean

Config (~/.roostrc):
  ROOST_WAYFINDER_REPO   # owner/name of the tracker (default Austin-MacWorks/Clauffice)
  ROOST_STATS_BOARD      # board dir under the status site
  ROOST_WAYFINDER_TAB    # tab id to file the sections under (default "planning", empty disables the tab)

Non-fatal by contract: missing config → skip with message; any failure → board untouched, exit 0.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lib

DEFAULT_REPO = "Austin-MacWorks/Clauffice"
LABEL_PREFIX = "wayfinder:"
MAP_LABEL = "wayfinder:map"

SECTION_WAYFINDER = "Wayfinder"
SECTION_FRONTIER = "Frontier — takeable now"
SECTION_ACTIVE = "In flight & blocked"
SECTION_BEYOND = "Beyond the tickets"
SECTION_HYGIENE = "Map hygiene"

# Board order, top to bottom. The collector inserts in reverse so this reads as written.
SECTION_ORDER = [SECTION_WAYFINDER, SECTION_FRONTIER, SECTION_ACTIVE, SECTION_BEYOND, SECTION_HYGIENE]

# A ticket type says how its decision gets made, so it earns a different tone than its state.
TYPE_TONE = {"grilling": "you", "prototype": "wip", "research": "srv", "task": "done"}


def gh_json(args, timeout=60):
    """Run a gh command and parse its JSON, or return None on any failure."""
    result = lib.sh(["gh"] + args, timeout=timeout)
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def sections_of(body):
    """Split a map body into its "## " sections, keyed by lowercased heading."""
    out = {}
    for chunk in ("\n" + (body or "")).split("\n## ")[1:]:
        head, _, rest = chunk.partition("\n")
        out[head.strip().lower()] = rest
    return out


def bullets(text):
    return [line[2:].strip() for line in (text or "").split("\n") if line.startswith("- ")]


def prose(text):
    lines = [x for x in (text or "").split("\n") if x.strip() and not x.startswith("<!--")]
    return " ".join(lines).strip()


def bucket_of(state, assignees, open_blockers):
    """A closed ticket is done whatever else it carries.
    An assignee wins over a blocker, because a claimed chain is one person working in order.
    """
    if state == "closed":
        return "done"
    if assignees:
        return "claimed"
    if open_blockers > 0:
        return "blocked"
    return "frontier"


def gather(repo):
    """Read every open map and its child tickets off the tracker.

    GitHub reports a dependency *count* but never the blockers themselves, so each ticket that
    has one costs a second call. That is what lets a blocked card name what it waits on.
    """
    maps = gh_json(["issue", "list", "--repo", repo, "--label", MAP_LABEL,
                    "--state", "open", "--limit", "20",
                    "--json", "number,title,url,body"])
    if maps is None:
        print("wayfinder: gh returned nothing (offline or not logged in) — skipping")
        return None
    if not maps:
        return {"maps": [], "offMap": []}

    out, seen = [], set()
    for mp in maps:
        subs = gh_json(["api", f'repos/{repo}/issues/{mp["number"]}/sub_issues', "--paginate"],
                       timeout=120)
        if subs is None:
            continue

        tickets = []
        for i in subs:
            labels = [l["name"] for l in i.get("labels", [])]
            types = [l[len(LABEL_PREFIX):] for l in labels if l.startswith(LABEL_PREFIX)]
            who = [a["login"] for a in i.get("assignees", [])]
            dep = i.get("issue_dependencies_summary") or {}
            open_blockers = dep.get("blocked_by", 0)

            blocked_by = []
            if dep.get("total_blocked_by", 0) > 0:
                got = gh_json(["api", f'repos/{repo}/issues/{i["number"]}/dependencies/blocked_by'])
                blocked_by = [{"number": b["number"], "title": b["title"], "state": b["state"]}
                              for b in (got or [])]

            seen.add(i["number"])
            tickets.append({
                "number": i["number"],
                "title": i["title"],
                "url": i["html_url"],
                "type": types[0] if types else "untyped",
                "state": i["state"],
                "assignees": who,
                "openBlockers": open_blockers,
                "blocks": dep.get("blocking", 0),
                "blockedBy": blocked_by,
                "bucket": bucket_of(i["state"], who, open_blockers),
            })

        s = sections_of(mp.get("body"))
        out.append({
            "number": mp["number"],
            "title": mp["title"],
            "url": mp["url"],
            "destination": prose(s.get("destination")),
            "fog": bullets(s.get("not yet specified")),
            "outOfScope": bullets(s.get("out of scope")),
            "tickets": tickets,
            "counts": {
                "total": len(tickets),
                **{b: sum(1 for t in tickets if t["bucket"] == b)
                   for b in ("done", "frontier", "claimed", "blocked")},
            },
        })

    # A wayfinder ticket with no parent map is invisible to every frontier query.
    off = []
    everything = gh_json(["issue", "list", "--repo", repo, "--state", "open", "--limit", "300",
                          "--json", "number,title,url,labels"]) or []
    for i in everything:
        labels = [l["name"] for l in i.get("labels", [])]
        if not any(l.startswith(LABEL_PREFIX) for l in labels):
            continue
        if MAP_LABEL in labels or i["number"] in seen:
            continue
        off.append({"number": i["number"], "title": i["title"], "url": i["url"]})

    return {"maps": out, "offMap": off}


def pick(tickets, bucket):
    return [t for t in tickets if t["bucket"] == bucket]


def stats_section(m, counts):
    """The glance: one tile per bucket, plus the fog the tickets do not cover."""
    pct = round(counts["done"] * 100 / counts["total"]) if counts["total"] else 0
    return {
        "kind": "stats",
        "title": SECTION_WAYFINDER,
        "icon": "🧭",
        "href": m["url"],
        "desc": m["title"],
        "pill": {"pill": f'{counts["done"]}/{counts["total"]} closed · {pct}%', "tone": "go"},
        "items": [
            {"n": str(counts["frontier"]), "label": "Takeable now", "tone": "you", "href": m["url"]},
            {"n": str(counts["claimed"]), "label": "In flight", "tone": "srv"},
            {"n": str(counts["blocked"]), "label": "Blocked", "tone": "wip"},
            {"n": str(counts["done"]), "label": "Decided", "tone": "go"},
            {"n": str(len(m["fog"])), "label": "In the fog", "tone": "done"},
        ],
    }


def frontier_section(frontier):
    """The only list on the board that is a to-do. Map order is the order a session takes them in."""
    items = []
    for t in frontier:
        item = {
            "id": f'#{t["number"]}',
            "q": t["title"],
            "href": t["url"],
            "pill": {"text": t["type"], "tone": TYPE_TONE.get(t["type"], "none")},
        }
        if t["blocks"]:
            item["meta"] = f'Unblocks {t["blocks"]} ticket' + ("s" if t["blocks"] > 1 else "")
        items.append(item)
    return {
        "kind": "cards",
        "title": SECTION_FRONTIER,
        "count": f'{len(items)} ticket' + ("s" if len(items) != 1 else ""),
        "desc": "open, unclaimed, and every blocker closed",
        "items": items,
    }


def active_section(claimed, blocked):
    """Claimed first: a held ticket is moving, and a blocked one is waiting on a name."""
    items = []
    for t in claimed:
        item = {
            "id": f'#{t["number"]}',
            "q": t["title"],
            "href": t["url"],
            "pill": {"text": "in flight", "tone": "srv"},
            "meta": "Held by " + " and ".join(t["assignees"]),
        }
        waits = [b["title"] for b in t["blockedBy"] if b["state"] == "open"]
        if waits:
            item["meta"] += " · behind " + ", ".join(waits)
        items.append(item)
    for t in blocked:
        waits = [b["title"] for b in t["blockedBy"] if b["state"] == "open"]
        items.append({
            "id": f'#{t["number"]}',
            "q": t["title"],
            "href": t["url"],
            "pill": {"text": "blocked", "tone": "wip"},
            "meta": "Waits on " + ", ".join(waits) if waits else "Waits on an open ticket",
        })
    return {
        "kind": "cards",
        "title": SECTION_ACTIVE,
        "count": f'{len(claimed)} held · {len(blocked)} blocked',
        "items": items,
    }


def beyond_section(m):
    """Fog is in scope and not yet sharp enough to ticket. Out of scope never graduates."""
    return {
        "kind": "split",
        "title": SECTION_BEYOND,
        "collapsible": True,
        "collapsed": True,
        "count": f'{len(m["fog"])} in the fog · {len(m["outOfScope"])} ruled out',
        "columns": [
            {"h3": "Not yet specified", "style": "pend",
             "items": [{"text": x} for x in m["fog"]]},
            {"h3": "Out of scope", "style": "check",
             "items": [{"text": x} for x in m["outOfScope"]]},
        ],
    }


def hygiene_items(data, tickets):
    """Two checks no tracker query runs on its own. Empty means the map is clean."""
    items = []
    for t in data.get("offMap", []):
        items.append({
            "id": f'#{t["number"]}',
            "q": t["title"],
            "href": t["url"],
            "pill": {"text": "no map", "tone": "err"},
            "meta": "Carries a wayfinder label but no parent map, so no frontier query finds it",
        })
    for t in tickets:
        if t["bucket"] == "done" and t["openBlockers"] > 0:
            waits = [b["title"] for b in t["blockedBy"] if b["state"] == "open"]
            items.append({
                "id": f'#{t["number"]}',
                "q": t["title"],
                "href": t["url"],
                "pill": {"text": "closed early", "tone": "you"},
                "meta": "Closed while still blocked by " + ", ".join(waits) + " — the edge is stale, or the order was wrong",
            })
    return items


def remove_section(board, title):
    """Drop a section the collector no longer has anything to say about.

    A conditional section that is merely skipped keeps rendering yesterday's finding forever.
    """
    board["sections"] = [s for s in board.get("sections", []) if s.get("title") != title]


def ensure_tab(board, tab_id, titles):
    """Claim the sections for a tab, creating the tab once if the board has never carried it.

    A tab the board already defines is left alone past its section list, so a hand-set label
    or icon survives a collector run.
    """
    tabs = board.get("tabs")
    if not tabs:
        return
    for tab in tabs:
        if tab.get("id") == tab_id:
            tab["sections"] = titles
            return
    tabs.append({"id": tab_id, "label": "Planning", "icon": "🧭", "sections": titles})


def main():
    cfg = lib.read_roostrc()

    repo = cfg.get("ROOST_WAYFINDER_REPO", DEFAULT_REPO)
    board_dir = cfg.get("ROOST_STATS_BOARD", "")
    if not board_dir:
        print("wayfinder: ROOST_STATS_BOARD not configured — skipping")
        return 0

    board_path = lib.site_dir(cfg) / board_dir / "board.json"
    if not board_path.exists():
        print(f"wayfinder: {board_path} not found — skipping")
        return 0

    data = gather(repo)
    if not data:
        return 0
    maps = data.get("maps", [])
    if not maps:
        print("wayfinder: no open map on the tracker — skipping")
        return 0

    # One board section set per board, so the largest map wins when several are open.
    m = max(maps, key=lambda x: x["counts"]["total"])
    tickets = m["tickets"]
    counts = m["counts"]

    board = lib.load_board(board_path)

    sections = {
        SECTION_WAYFINDER: stats_section(m, counts),
        SECTION_FRONTIER: frontier_section(pick(tickets, "frontier")),
        SECTION_ACTIVE: active_section(pick(tickets, "claimed"), pick(tickets, "blocked")),
        SECTION_BEYOND: beyond_section(m),
    }

    hyg = hygiene_items(data, tickets)
    if hyg:
        sections[SECTION_HYGIENE] = {
            "kind": "cards",
            "title": SECTION_HYGIENE,
            "icon": "⚠️",
            "count": f'{len(hyg)} to fix',
            "desc": "checks the tracker never runs on its own",
            "items": hyg,
        }
    else:
        remove_section(board, SECTION_HYGIENE)

    # Reverse, because upsert_section inserts a section the board has never carried directly
    # after the compare block. Inserting bottom-up leaves SECTION_ORDER as the running order.
    for title in reversed(SECTION_ORDER):
        if title in sections:
            lib.upsert_section(board, title, sections[title])

    tab_id = cfg.get("ROOST_WAYFINDER_TAB", "planning")
    if tab_id:
        ensure_tab(board, tab_id, [t for t in SECTION_ORDER if t in sections])

    lib.save_board(board_path, board)
    print(f'wayfinder: {m["title"]} — {counts["done"]}/{counts["total"]} closed, '
          f'{counts["frontier"]} takeable, {counts["claimed"]} held, {counts["blocked"]} blocked, '
          f'{len(hyg)} hygiene')
    return 0


if __name__ == "__main__":
    sys.exit(main())
