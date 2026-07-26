#!/usr/bin/env python3
"""ci_health.py — how a repo's pipeline is *doing*, not just what it last did.

ci_status.py answers "what ran?" — a console of the newest runs across every
watched repo, and a ✓/✗ tile per repo. That is enough for a suite that either
passes or fails in a couple of minutes. It is not enough for a build: a build
has a *cost*, and the interesting question about a compile-and-package pipeline
is how long it takes and how often it survives.

So this collector reads one workflow on one branch and writes, into that repo's
compare column:

    Build time    the newest successful run's wall clock  (5m36s)
    Build green   how many of the last N finished runs passed  (9/12)

…plus a "<label> — build time" barchart of the last N finished runs, newest
first, green bars for successes and amber for failures. That chart is the point:
a caching change that takes a build from 31m to 6m is invisible in a ✓, and a
build creeping back up is invisible in anything but a trend.

Config (~/.roostrc):
  ROOST_CI_HEALTH_BOARD=clauffice
  ROOST_CI_HEALTH=owner/repo:Column:branch:samples[:workflow], …

  Column   substring of the compare column title this repo owns ("MWServer"
           matches the "MWServer — server" column). Also the chart's label.
  branch   the branch whose pipeline this is (default dev)
  samples  how many finished runs to score and chart (default 12)
  workflow optional workflow name, when a repo runs more than one on `branch`

Non-fatal by contract: no config → skip; any failure → board untouched, exit 0.
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lib

# Only `push` runs. A pull_request run of the same workflow builds a different
# tree, and on repos that gate a build behind `if: github.event_name == 'push'`
# it does not build at all — it reports `skipped`, which would read as a
# suspiciously fast build.
EVENT = "push"

# Conclusions that represent a run that actually finished and produced a
# verdict. `cancelled`/`skipped` are concurrency churn (a newer push superseded
# this one), and their durations are the time-to-cancel, not the time to build
# — averaging those in makes the pipeline look faster the more it churns.
FINISHED = {"success", "failure", "timed_out", "startup_failure"}

# Bars fill by outcome using the board's tone vocabulary.
BAR_FILL = {"success": "go"}

DEFAULT_BRANCH = "dev"
DEFAULT_SAMPLES = 12
# Under three points there is no trend to see, only three numbers already on
# the tiles — so the chart stays off rather than shipping an empty-looking card.
MIN_CHART_POINTS = 3


def parse_sources(spec):
    """"owner/repo:Column:branch:samples[:workflow], …" → list of dicts.

    Every field past the repo is optional; a bad `samples` falls back to the
    default rather than taking the whole entry down with it."""
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        bits = [b.strip() for b in part.split(":")]
        repo = bits[0]
        if not repo:
            continue
        column = bits[1] if len(bits) > 1 and bits[1] else repo.split("/")[-1]
        branch = bits[2] if len(bits) > 2 and bits[2] else DEFAULT_BRANCH
        try:
            samples = int(bits[3]) if len(bits) > 3 and bits[3] else DEFAULT_SAMPLES
        except ValueError:
            samples = DEFAULT_SAMPLES
        workflow = bits[4] if len(bits) > 4 and bits[4] else None
        out.append({"repo": repo, "column": column, "branch": branch,
                    "samples": max(1, samples), "workflow": workflow})
    return out


def finished_runs(runs):
    """Runs with a real verdict, newest first (gh already sorts that way)."""
    return [r for r in (runs or []) if r.get("conclusion") in FINISHED]


def short_sha(run):
    return str(run.get("headSha", ""))[:7]


def build_chart(source, runs):
    """A barchart of the last N run durations, newest at the top.

    Runs still in flight and runs whose stamps do not parse have no duration,
    so they are simply absent — a bar of height 0 would read as an instant
    build rather than as no data."""
    series, ok_secs = [], []
    for r in runs:
        secs = lib.run_duration(r)
        if secs is None:
            continue
        passed = r.get("conclusion") == "success"
        if passed:
            ok_secs.append(secs)
        series.append({
            "label": short_sha(r) or r.get("headBranch", "?"),
            "value": round(secs / 60.0, 1),
            "valueText": lib.fmt_duration(secs),
            "fill": BAR_FILL.get(r.get("conclusion"), "you"),
        })
    if len(series) < MIN_CHART_POINTS:
        return None

    note = (f"Wall clock of the last {len(series)} finished "
            f"{source['branch']} runs, newest first. "
            "Bars are minutes; amber is a run that failed.")
    if ok_secs:
        # Spread over the SUCCESSFUL runs only, from raw seconds. A failure's
        # clock is how long it took to die — a build that failed to resolve
        # dependencies in a minute is not this pipeline's "fastest build" — and
        # re-deriving these from the rounded minutes above would disagree with
        # the bar labels by a few seconds.
        note += (f" Fastest green {lib.fmt_duration(min(ok_secs))}, "
                 f"slowest {lib.fmt_duration(max(ok_secs))}.")
    return {
        "kind": "barchart",
        "icon": "⏱️",
        "title": f"{source['column']} — build time",
        "desc": f"minutes per {source['branch']} run",
        "legend": [{"label": "passed", "fill": "go"},
                   {"label": "failed", "fill": "you"}],
        "series": series,
        "note": note,
    }


def apply_source(board, source):
    """Patch one repo's tiles + chart into `board`. Returns a status string for
    the log, or None when there was nothing to report."""
    runs = lib.gh_run_history(source["repo"], limit=max(source["samples"] * 3, 30),
                              branch=source["branch"], event=EVENT,
                              workflow=source["workflow"])
    if runs is None:
        return None
    done = finished_runs(runs)[:source["samples"]]
    if not done:
        return None

    # Build time comes from the newest run that actually built — a failed run's
    # clock is however far it got before dying, which is not a build time.
    newest_ok = next((r for r in done if r.get("conclusion") == "success"), None)
    if newest_ok is not None:
        secs = lib.run_duration(newest_ok)
        if secs is not None:
            lib.upsert_compare_tile(
                board, source["column"], "Build time",
                lib.fmt_duration(secs), tone="none",
                href=newest_ok.get("url"))

    passed = sum(1 for r in done if r.get("conclusion") == "success")
    # Amber below two-thirds: a pipeline red a third of the time is not a gate
    # anyone trusts, and the tile should say so before someone has to notice.
    tone = "go" if passed * 3 >= len(done) * 2 else "you"
    lib.upsert_compare_tile(board, source["column"], "Build green",
                            f"{passed}/{len(done)}", tone=tone)

    chart = build_chart(source, done)
    if chart:
        lib.upsert_section(board, chart["title"], chart, after_kind="compare")

    newest = done[0]
    return (f"{source['column']}: {passed}/{len(done)} green on "
            f"{source['branch']}, latest {newest.get('conclusion')} "
            f"@{short_sha(newest)}"
            + (f", {lib.fmt_duration(lib.run_duration(newest_ok))} build"
               if newest_ok is not None and lib.run_duration(newest_ok) else ""))


def main():
    cfg = lib.read_roostrc()
    spec = cfg.get("ROOST_CI_HEALTH", "")
    board_dir = cfg.get("ROOST_CI_HEALTH_BOARD", "")
    if not spec or not board_dir:
        print("ci-health: ROOST_CI_HEALTH/ROOST_CI_HEALTH_BOARD not configured — skipping")
        return 0
    board_path = lib.site_dir(cfg) / board_dir / "board.json"
    if not board_path.exists():
        print(f"ci-health: {board_path} not found — skipping")
        return 0

    sources = parse_sources(spec)
    if not sources:
        print("ci-health: ROOST_CI_HEALTH parsed to nothing — skipping")
        return 0

    board = lib.load_board(board_path)
    reports = [msg for msg in (apply_source(board, s) for s in sources) if msg]
    if not reports:
        print("ci-health: no finished runs found (gh unavailable?) — leaving board as-is")
        return 0

    lib.save_board(board_path, board)
    for msg in reports:
        print(f"ci-health: {msg}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # never break a status push
        print(f"ci-health: non-fatal error: {e}")
        sys.exit(0)
