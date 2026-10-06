"""A board that names a wayfinder map draws its Features from the map's tickets (house#94).

Run:  python3 -m unittest discover -s tests   (from the statusgen root)
"""
import importlib.util
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("app_stats", os.path.join(ROOT, "bin", "collect", "app_stats.py"))
APP = importlib.util.module_from_spec(spec)
spec.loader.exec_module(APP)


class FeatureCardsTest(unittest.TestCase):
    TICKETS = [
        {"number": 104, "title": "Tiered appliance DB", "state": "closed", "html_url": "https://f/104"},
        {"number": 111, "title": "Meter readings vs estimates", "state": "open", "assignees": []},
        {"number": 118, "title": "A feature a seat holds", "state": "open", "assignees": [{"login": "morpheus"}]},
    ]

    def test_a_closed_ticket_is_shipped_an_open_one_is_next_and_a_held_one_is_in_flight(self):
        cards = APP.feature_cards(self.TICKETS)
        self.assertEqual([c["pill"]["text"] for c in cards], ["Shipped", "Next", "In flight"])
        self.assertEqual(cards[0]["id"], "#104")
        self.assertEqual(cards[0]["href"], "https://f/104")
        self.assertNotIn("href", cards[1])

    def test_the_features_section_is_replaced_in_place_with_a_count_and_a_stamp(self):
        board = {"sections": [{"kind": "stats", "items": []}, {"kind": "cards", "title": "Features", "items": [{"id": "W1", "q": "by hand"}]}, {"kind": "split", "title": "Operations"}]}
        APP.write_features(board, self.TICKETS, "jimmy/house#103")
        titles = [s.get("title") for s in board["sections"]]
        self.assertEqual(titles, [None, "Features", "Operations"], "replaced where it already sits")
        features = board["sections"][1]
        self.assertEqual(features["count"], "1 shipped of 3")
        self.assertEqual([c["id"] for c in features["items"]], ["#104", "#111", "#118"])
        self.assertIn("generatedAt", features)
        self.assertEqual(features["desc"], "from the tickets of jimmy/house#103")


if __name__ == "__main__":
    unittest.main()
