#!/usr/bin/env python3
"""The collectors collector: run record status as a console section."""
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "bin" / "collect"))
import collectors


RECORD_CLEAN = {
    "at": 1789012345678,
    "runs": [
        {"name": "repo_stats", "ok": True, "ms": 812, "at": 1789012345678},
        {"name": "ci_status", "ok": True, "ms": 1503, "at": 1789012345678},
        {"name": "ci_health", "ok": True, "ms": 625, "at": 1789012345678},
    ]
}

RECORD_WITH_FAILURES = {
    "at": 1789012345678,
    "runs": [
        {"name": "repo_stats", "ok": True, "ms": 812, "at": 1789012345678},
        {"name": "ci_status", "ok": False, "ms": 1503, "at": 1789012345678, "exit": 1},
        {"name": "ci_health", "ok": True, "ms": 625, "at": 1789012345678},
        {"name": "swift_tests", "ok": False, "ms": 2100, "at": 1789012345678, "exit": 2},
    ]
}

RECORD_EMPTY = {
    "at": 1789012345678,
    "runs": []
}

NOW_MS = 1789012345678 + 3661000  # 1 hour 1 minute 1 second after the record timestamp


class CollectorLinesTest(unittest.TestCase):
    def test_one_line_per_collector(self):
        """Each collector in runs becomes one line."""
        lines = collectors.collector_lines(RECORD_CLEAN, NOW_MS)
        self.assertEqual(len(lines), 3)

    def test_collector_name_in_text(self):
        """Collector name appears in line text."""
        lines = collectors.collector_lines(RECORD_CLEAN, NOW_MS)
        self.assertEqual(lines[0]["text"], "repo_stats")
        self.assertEqual(lines[1]["text"], "ci_status")
        self.assertEqual(lines[2]["text"], "ci_health")

    def test_success_tone_is_go(self):
        """Passing collector has tone 'go'."""
        lines = collectors.collector_lines(RECORD_CLEAN, NOW_MS)
        self.assertEqual(lines[0]["status"], "success")
        self.assertEqual(lines[0]["tone"], "go")

    def test_failure_tone_is_err(self):
        """Failing collector has tone 'err'."""
        lines = collectors.collector_lines(RECORD_WITH_FAILURES, NOW_MS)
        self.assertEqual(lines[1]["status"], "failure")
        self.assertEqual(lines[1]["tone"], "err")

    def test_meta_shows_duration_and_age(self):
        """Meta line shows duration in ms and age."""
        lines = collectors.collector_lines(RECORD_CLEAN, NOW_MS)
        self.assertIn("812ms", lines[0]["meta"])

    def test_failure_shows_exit_code(self):
        """Failed collector shows exit code in meta."""
        lines = collectors.collector_lines(RECORD_WITH_FAILURES, NOW_MS)
        self.assertIn("exit 1", lines[1]["meta"])
        self.assertIn("exit 2", lines[3]["meta"])

    def test_success_no_exit_code(self):
        """Successful collector does not show exit code."""
        lines = collectors.collector_lines(RECORD_CLEAN, NOW_MS)
        self.assertNotIn("exit", lines[0]["meta"])

    def test_age_formatting_milliseconds(self):
        """Ages under 1 second format as milliseconds."""
        now = 1789012345678 + 500
        lines = collectors.collector_lines(RECORD_CLEAN, now)
        self.assertIn("500ms", lines[0]["meta"])

    def test_age_formatting_seconds(self):
        """Ages under 1 minute format as seconds."""
        now = 1789012345678 + 45000
        lines = collectors.collector_lines(RECORD_CLEAN, now)
        self.assertIn("45s", lines[0]["meta"])

    def test_age_formatting_minutes(self):
        """Ages under 1 hour format as minutes."""
        now = 1789012345678 + 300000
        lines = collectors.collector_lines(RECORD_CLEAN, now)
        self.assertIn("5m", lines[0]["meta"])

    def test_age_formatting_hours(self):
        """Ages under 1 day format as hours."""
        now = 1789012345678 + 7200000
        lines = collectors.collector_lines(RECORD_CLEAN, now)
        self.assertIn("2h", lines[0]["meta"])

    def test_age_formatting_days(self):
        """Ages over 1 day format as days."""
        now = 1789012345678 + 86400000
        lines = collectors.collector_lines(RECORD_CLEAN, now)
        self.assertIn("1d", lines[0]["meta"])


class SectionTest(unittest.TestCase):
    def test_section_title_is_collectors(self):
        """Section title is 'Collectors'."""
        sec = collectors.section(RECORD_CLEAN, NOW_MS)
        self.assertEqual(sec["title"], "Collectors")

    def test_section_kind_is_console(self):
        """Section kind is 'console'."""
        sec = collectors.section(RECORD_CLEAN, NOW_MS)
        self.assertEqual(sec["kind"], "console")

    def test_section_icon(self):
        """Section has appropriate icon."""
        sec = collectors.section(RECORD_CLEAN, NOW_MS)
        self.assertEqual(sec["icon"], "🧩")

    def test_section_count_all_passed(self):
        """Count shows 3/3 passed when all succeed."""
        sec = collectors.section(RECORD_CLEAN, NOW_MS)
        self.assertEqual(sec["count"], "3/3 passed")

    def test_section_count_with_failures(self):
        """Count shows 2/4 passed when two fail."""
        sec = collectors.section(RECORD_WITH_FAILURES, NOW_MS)
        self.assertEqual(sec["count"], "2/4 passed")

    def test_section_count_empty(self):
        """Count shows 'no runs' when empty."""
        sec = collectors.section(RECORD_EMPTY, NOW_MS)
        self.assertEqual(sec["count"], "no runs")

    def test_section_line_count_matches_runs(self):
        """Section lines match run count."""
        sec = collectors.section(RECORD_CLEAN, NOW_MS)
        self.assertEqual(len(sec["lines"]), 3)
        sec = collectors.section(RECORD_WITH_FAILURES, NOW_MS)
        self.assertEqual(len(sec["lines"]), 4)

    def test_section_desc(self):
        """Section has description."""
        sec = collectors.section(RECORD_CLEAN, NOW_MS)
        self.assertIn("collector", sec["desc"].lower())


class PathResolutionTest(unittest.TestCase):
    def test_default_path_uses_xdg_state_home(self):
        """Default path uses XDG_STATE_HOME when set."""
        original_xdg = os.environ.get("XDG_STATE_HOME")
        try:
            os.environ["XDG_STATE_HOME"] = "/tmp/test-state"
            cfg = {}
            path = collectors.collector_log_path(cfg)
            self.assertEqual(path, pathlib.Path("/tmp/test-state/roost-collectors.json"))
        finally:
            if original_xdg:
                os.environ["XDG_STATE_HOME"] = original_xdg
            else:
                os.environ.pop("XDG_STATE_HOME", None)

    def test_default_path_falls_back_to_home_local_state(self):
        """Default path falls back to ~/.local/state when XDG_STATE_HOME not set."""
        original_xdg = os.environ.get("XDG_STATE_HOME")
        try:
            os.environ.pop("XDG_STATE_HOME", None)
            cfg = {}
            path = collectors.collector_log_path(cfg)
            expected = pathlib.Path.home() / ".local" / "state" / "roost-collectors.json"
            self.assertEqual(path, expected)
        finally:
            if original_xdg:
                os.environ["XDG_STATE_HOME"] = original_xdg

    def test_config_overrides_default(self):
        """Explicit ROOST_COLLECTOR_LOG config overrides default."""
        cfg = {"ROOST_COLLECTOR_LOG": "/custom/path/collectors.json"}
        path = collectors.collector_log_path(cfg)
        self.assertEqual(path, pathlib.Path("/custom/path/collectors.json"))


class MalformedRecordTest(unittest.TestCase):
    def test_malformed_json_raises(self):
        """Malformed JSON raises JSONDecodeError."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as fh:
            fh.write("{invalid json")
            path = fh.name
        try:
            with self.assertRaises(json.JSONDecodeError):
                collectors.load_run_record(path)
        finally:
            pathlib.Path(path).unlink()

    def test_missing_file_raises(self):
        """Missing file raises FileNotFoundError."""
        path = pathlib.Path("/nonexistent/path/to/file.json")
        with self.assertRaises(FileNotFoundError):
            collectors.load_run_record(path)


# Required for proper path resolution in pathlib.Path manipulation.
import os


if __name__ == "__main__":
    unittest.main()
