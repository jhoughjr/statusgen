#!/usr/bin/env python3
"""The hatchery stacks collector: hatchery's status payload becomes a console
section, one line per service, worsening states toned to catch the eye."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "bin" / "collect"))
import hatchery_stacks


PAYLOAD = [
    {"name": "mwlab", "backend": "dokku", "environment": "dev", "host": "192.168.0.103",
     "services": [
         {"name": "mwlab", "state": "responding", "latencyMs": 23,
          "domains": ["mwlab.jimmyhoughjr.net"]},
         {"name": "paylab", "state": "degraded", "latencyMs": None, "domains": []},
     ]},
    {"name": "mwcloud", "backend": "appPlatform", "environment": "staging", "host": None,
     "services": [{"name": "mwcloud", "state": None, "domains": []}]},
]


class StackLinesTest(unittest.TestCase):
    def test_one_line_per_service_with_tone_meta_and_link(self):
        lines = hatchery_stacks.stack_lines(PAYLOAD)
        self.assertEqual([l["text"] for l in lines], ["mwlab/mwlab", "mwlab/paylab", "mwcloud/mwcloud"])
        self.assertEqual(lines[0]["tone"], "go")
        self.assertEqual(lines[0]["meta"], "· dokku · dev · 192.168.0.103 · 23ms")
        self.assertEqual(lines[0]["href"], "https://mwlab.jimmyhoughjr.net")
        self.assertEqual(lines[1]["tone"], "you")
        self.assertNotIn("href", lines[1])
        # No report is a question, not a fault, and a managed backend has no host.
        self.assertEqual(lines[2]["status"], "no report")
        self.assertEqual(lines[2]["tone"], "none")
        self.assertIn("managed", lines[2]["meta"])

    def test_the_section_counts_stacks_and_services(self):
        section = hatchery_stacks.section(PAYLOAD, "http://mini:7878")
        self.assertEqual(section["title"], "Stacks")
        self.assertEqual(section["count"], "2 stack(s), 3 service(s)")
        self.assertEqual(len(section["lines"]), 3)
        self.assertIn("http://mini:7878", section["desc"])


if __name__ == "__main__":
    unittest.main()
