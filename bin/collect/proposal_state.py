#!/usr/bin/env python3
"""proposal_state.py — render Clauffice proposal statuses onto the board.

Parses proposals/README.md to extract proposal status, maps status text to tone,
and upserts a "Proposals" table section onto the board.

Config (~/.roostrc):
  ROOST_CLAUFFICE_DIR    # path to Clauffice clone (default ~/Clauffice, fallback ~/repos/Clauffice)
  ROOST_STATS_BOARD      # board dir under the status site

Non-fatal by contract: missing config → skip with message; any failure → board untouched, exit 0.
"""
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lib


def find_clauffice_dir(cfg):
    """Find Clauffice dir: try ROOST_CLAUFFICE_DIR, then ~/Clauffice, then ~/repos/Clauffice."""
    if "ROOST_CLAUFFICE_DIR" in cfg:
        p = pathlib.Path(cfg["ROOST_CLAUFFICE_DIR"])
        if p.exists():
            return p

    default = pathlib.Path("~/Clauffice").expanduser()
    if default.exists():
        return default

    fallback = pathlib.Path("~/repos/Clauffice").expanduser()
    if fallback.exists():
        return fallback

    return None


def git_pull(repo_dir):
    """Run git pull --ff-only. Non-fatal: return success bool, print note on failure."""
    result = lib.sh(["git", "pull", "--ff-only"], cwd=str(repo_dir))
    if result.returncode != 0:
        print(f"proposal-state: git pull failed (scanning stale): {result.stderr.strip()}")
        return False
    return True


def extract_status_and_tone(status_text):
    """Map status text to (keyword, tone).

    Case-insensitive keyword matching (first match):
      merged/landed → go
      built/in-progress → you
      designed → srv
      exploring/scaffolded → wip
      parked/closed → done
      else → none
    """
    status_lower = status_text.lower()

    patterns = [
        (r'\b(merged|landed)\b', "go"),
        (r'\b(built|in-progress)\b', "you"),
        (r'\b(designed)\b', "srv"),
        (r'\b(exploring|scaffolded)\b', "wip"),
        (r'\b(parked|closed)\b', "done"),
    ]

    for pattern, tone in patterns:
        m = re.search(pattern, status_lower)
        if m:
            keyword = m.group(1)
            return (keyword, tone)

    return (status_text, "none")


def strip_markdown(text):
    """Remove markdown formatting (bold, italic, links)."""
    # Remove bold/italic: **text** or *text* or __text__ or _text_
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'__(.+?)__', r'\1', text)
    text = re.sub(r'_(.+?)_', r'\1', text)
    # Remove links: [text](url)
    text = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', text)
    return text


def truncate_summary(text, max_len=110):
    """Truncate to first sentence, strip markdown, cap at max_len chars."""
    text = text.strip()
    original_len = len(text)

    # Extract first sentence (ends with . ! or ?)
    m = re.match(r'^([^.!?]*[.!?])', text)
    if m:
        text = m.group(1).strip()
    else:
        # No punctuation: take first max_len chars and mark as truncated
        text = text[:max_len].strip()

    text = strip_markdown(text)

    if len(text) > max_len:
        text = text[:max_len].rstrip() + "…"
    elif len(text) < original_len and not text.endswith((".", "!", "?")):
        # We truncated and there's no sentence boundary; add ellipsis
        text += "…"

    return text


def parse_proposals_table(readme_path):
    """Parse proposals/README.md markdown table.

    Returns list of {slug, status, summary} dicts.
    Table format: | [slug](slug/README.md) | repos | Status | Summary |
    """
    content = readme_path.read_text(encoding='utf-8', errors='ignore')
    proposals = []

    # Find markdown table rows (skip header separator line)
    lines = content.split('\n')
    in_table = False
    for line in lines:
        line = line.strip()
        if not line.startswith('|'):
            continue

        # Skip header separator (all dashes and pipes)
        if all(c in '|-:' for c in line):
            in_table = True
            continue

        if not in_table:
            continue

        # Parse row: | [slug](slug/README.md) | repos | Status | Summary |
        cells = [c.strip() for c in line.split('|')[1:-1]]  # skip first/last empty cells
        if len(cells) < 4:
            continue

        # Extract slug from [slug](url) link
        slug_cell = cells[0]
        m = re.match(r'\[(.+?)\]\(.+?\)', slug_cell)
        slug = m.group(1) if m else slug_cell

        status_text = cells[2] if len(cells) > 2 else ""
        summary_text = cells[3] if len(cells) > 3 else ""

        if not status_text:
            continue

        keyword, tone = extract_status_and_tone(status_text)
        summary = truncate_summary(summary_text)

        proposals.append({
            'slug': slug,
            'status': keyword,
            'tone': tone,
            'summary': summary,
        })

    return proposals


def build_table_rows(proposals):
    """Convert proposals list to table rows."""
    rows = []
    for p in proposals:
        rows.append([
            p['slug'],
            {'pill': p['status'], 'tone': p['tone']},
            p['summary'],
        ])
    return rows


def main():
    cfg = lib.read_roostrc()

    # Find Clauffice dir
    clauffice_dir = find_clauffice_dir(cfg)
    if not clauffice_dir:
        print("proposal-state: ROOST_CLAUFFICE_DIR/~/Clauffice not found — skipping")
        return 0

    board_dir = cfg.get("ROOST_STATS_BOARD", "")
    if not board_dir:
        print("proposal-state: ROOST_STATS_BOARD not configured — skipping")
        return 0

    board_path = lib.site_dir(cfg) / board_dir / "board.json"
    if not board_path.exists():
        print(f"proposal-state: {board_path} not found — skipping")
        return 0

    # Attempt git pull (non-fatal)
    git_pull(clauffice_dir)

    # Parse proposals table
    readme_path = clauffice_dir / "proposals" / "README.md"
    if not readme_path.exists():
        print(f"proposal-state: {readme_path} not found — skipping")
        return 0

    try:
        proposals = parse_proposals_table(readme_path)
    except Exception as e:
        print(f"proposal-state: failed to parse proposals table: {e}")
        return 0

    if not proposals:
        print("proposal-state: no proposals found in table — skipping")
        return 0

    # Build table section
    rows = build_table_rows(proposals)
    section = {
        'kind': 'table',
        'title': 'Proposals',
        'count': f"{len(proposals)} tracked",
        'columns': ['Proposal', 'Status', 'Summary'],
        'rows': rows,
    }

    # Upsert onto board (after "API consumption")
    board = lib.load_board(board_path)
    lib.upsert_section(board, 'Proposals', section, after_kind='split')
    # Wire the once-hardcoded "Resolved" tile to the count of proposals that
    # have landed or been parked/closed (merged/landed = go, parked/closed = done).
    resolved = sum(1 for p in proposals if p['tone'] in ('go', 'done'))
    lib.set_compare_tile(board, 'Resolved', str(resolved))
    lib.save_board(board_path, board)

    statuses = ', '.join(sorted(set(p['status'] for p in proposals))[:3])
    if len(set(p['status'] for p in proposals)) > 3:
        statuses += ', ...'
    print(f"proposal-state: {len(proposals)} proposals: {statuses}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # never break a status push
        print(f"proposal-state: non-fatal error: {e}")
        sys.exit(0)
