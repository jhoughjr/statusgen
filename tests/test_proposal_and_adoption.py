#!/usr/bin/env python3
"""Unit tests for proposal_state.py and api_consumption.py adoption features.

Tests proposal table parsing (statuses map to tones, summary truncation) and
adoption scanning (token hits → adopted, no hits → pending, generated/test files excluded).

Monkeypatches git operations and board writes to avoid I/O.

Run:  python3 -m unittest discover -s tests   (from the statusgen root)
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin", "collect"))

import proposal_state
import api_consumption


class ProposalParsingTest(unittest.TestCase):
    """Test proposal_state.parse_proposals_table and related functions."""

    def test_extract_status_and_tone_merged(self):
        """Status 'merged' maps to ('merged', 'go')."""
        keyword, tone = proposal_state.extract_status_and_tone("Merged")
        self.assertEqual(keyword, "merged")
        self.assertEqual(tone, "go")

    def test_extract_status_and_tone_landed(self):
        """Status 'landed' maps to ('landed', 'go')."""
        keyword, tone = proposal_state.extract_status_and_tone("Code landed")
        self.assertEqual(keyword, "landed")
        self.assertEqual(tone, "go")

    def test_extract_status_and_tone_in_progress(self):
        """Status 'in-progress' maps to ('in-progress', 'you')."""
        keyword, tone = proposal_state.extract_status_and_tone("in-progress")
        self.assertEqual(keyword, "in-progress")
        self.assertEqual(tone, "you")

    def test_extract_status_and_tone_built(self):
        """Status 'built' maps to ('built', 'you')."""
        keyword, tone = proposal_state.extract_status_and_tone("Built v1")
        self.assertEqual(keyword, "built")
        self.assertEqual(tone, "you")

    def test_extract_status_and_tone_designed(self):
        """Status 'designed' maps to ('designed', 'srv')."""
        keyword, tone = proposal_state.extract_status_and_tone("Designed")
        self.assertEqual(keyword, "designed")
        self.assertEqual(tone, "srv")

    def test_extract_status_and_tone_exploring(self):
        """Status 'exploring' maps to ('exploring', 'wip')."""
        keyword, tone = proposal_state.extract_status_and_tone("Exploring options")
        self.assertEqual(keyword, "exploring")
        self.assertEqual(tone, "wip")

    def test_extract_status_and_tone_scaffolded(self):
        """Status 'scaffolded' maps to ('scaffolded', 'wip')."""
        keyword, tone = proposal_state.extract_status_and_tone("Scaffolded")
        self.assertEqual(keyword, "scaffolded")
        self.assertEqual(tone, "wip")

    def test_extract_status_and_tone_parked(self):
        """Status 'parked' maps to ('parked', 'done')."""
        keyword, tone = proposal_state.extract_status_and_tone("Parked")
        self.assertEqual(keyword, "parked")
        self.assertEqual(tone, "done")

    def test_extract_status_and_tone_closed(self):
        """Status 'closed' maps to ('closed', 'done')."""
        keyword, tone = proposal_state.extract_status_and_tone("Closed")
        self.assertEqual(keyword, "closed")
        self.assertEqual(tone, "done")

    def test_extract_status_and_tone_unknown(self):
        """Unknown status maps to (status, 'none')."""
        keyword, tone = proposal_state.extract_status_and_tone("Random text")
        self.assertEqual(keyword, "Random text")
        self.assertEqual(tone, "none")

    def test_extract_status_case_insensitive(self):
        """Status matching is case-insensitive."""
        keyword, tone = proposal_state.extract_status_and_tone("MERGED and landed")
        self.assertEqual(keyword, "merged")  # first match
        self.assertEqual(tone, "go")

    def test_strip_markdown_bold(self):
        """Remove **bold** markdown."""
        text = proposal_state.strip_markdown("This is **bold** text")
        self.assertEqual(text, "This is bold text")

    def test_strip_markdown_italic(self):
        """Remove *italic* markdown."""
        text = proposal_state.strip_markdown("This is *italic* text")
        self.assertEqual(text, "This is italic text")

    def test_strip_markdown_links(self):
        """Remove [link](url) markdown."""
        text = proposal_state.strip_markdown("See [this](https://example.com) page")
        self.assertEqual(text, "See this page")

    def test_truncate_summary_at_period(self):
        """Truncate to first sentence ending with period."""
        text = proposal_state.truncate_summary("First sentence. Second sentence. Third.")
        self.assertEqual(text, "First sentence.")

    def test_truncate_summary_at_question(self):
        """Truncate to first sentence ending with question mark."""
        text = proposal_state.truncate_summary("Is this a question? No it's not.")
        self.assertEqual(text, "Is this a question?")

    def test_truncate_summary_at_max_len(self):
        """Truncate to max_len when no punctuation."""
        text = proposal_state.truncate_summary("a" * 200, max_len=50)
        self.assertEqual(len(text), 51)  # 50 + ellipsis
        self.assertTrue(text.endswith("…"))

    def test_truncate_summary_with_markdown(self):
        """Truncate removes markdown before limiting length."""
        text = proposal_state.truncate_summary("**Bold** text here. More text.", max_len=20)
        self.assertEqual(text, "Bold text here.")

    def test_parse_proposals_table_basic(self):
        """Parse a simple markdown table with proposals."""
        md = """
# Proposals

| Proposal | Repos | Status | Summary |
|----------|-------|--------|---------|
| [Feature A](feature-a/README.md) | repo1 | Merged | Implements feature A. Done now. |
| [Feature B](feature-b/README.md) | repo2 | designed | New approach for B. |
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write(md)
            f.flush()
            try:
                proposals = proposal_state.parse_proposals_table(Path(f.name))
                self.assertEqual(len(proposals), 2)
                self.assertEqual(proposals[0]['slug'], 'Feature A')
                self.assertEqual(proposals[0]['tone'], 'go')
                self.assertEqual(proposals[1]['slug'], 'Feature B')
                self.assertEqual(proposals[1]['tone'], 'srv')
            finally:
                os.unlink(f.name)

    def test_parse_proposals_table_empty(self):
        """Empty markdown returns no proposals."""
        md = "# No proposals\n"
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write(md)
            f.flush()
            try:
                proposals = proposal_state.parse_proposals_table(Path(f.name))
                self.assertEqual(len(proposals), 0)
            finally:
                os.unlink(f.name)

    def test_build_table_rows(self):
        """Build table rows from proposals list."""
        proposals = [
            {'slug': 'Feature A', 'status': 'merged', 'tone': 'go', 'summary': 'Summary A.'},
            {'slug': 'Feature B', 'status': 'designed', 'tone': 'srv', 'summary': 'Summary B.'},
        ]
        rows = proposal_state.build_table_rows(proposals)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][0], 'Feature A')
        self.assertEqual(rows[0][1], {'pill': 'merged', 'tone': 'go'})
        self.assertEqual(rows[0][2], 'Summary A.')


class AdoptionScanTest(unittest.TestCase):
    """Test api_consumption adoption scanning."""

    def test_scan_src_for_tokens_found(self):
        """Scan finds tokens in hand-written source files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "src"
            src_dir.mkdir()
            (src_dir / "example.ts").write_text("const is_reconciled = true;")

            found = api_consumption.scan_src_for_tokens(tmpdir, ["is_reconciled"])
            self.assertTrue(found)

    def test_scan_src_for_tokens_not_found(self):
        """Scan returns False when no tokens match."""
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "src"
            src_dir.mkdir()
            (src_dir / "example.ts").write_text("const something_else = true;")

            found = api_consumption.scan_src_for_tokens(tmpdir, ["is_reconciled"])
            self.assertFalse(found)

    def test_scan_src_excludes_generated(self):
        """Scan skips files in /generated/ directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "src"
            gen_dir = src_dir / "generated"
            gen_dir.mkdir(parents=True)
            (gen_dir / "api.ts").write_text("const is_reconciled = true;")

            found = api_consumption.scan_src_for_tokens(tmpdir, ["is_reconciled"])
            self.assertFalse(found)

    def test_scan_src_excludes_test_files(self):
        """Scan skips .test.ts and .test.tsx files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "src"
            src_dir.mkdir()
            (src_dir / "example.test.ts").write_text("const is_reconciled = true;")
            (src_dir / "other.dom.test.tsx").write_text("const is_reconciled = true;")

            found = api_consumption.scan_src_for_tokens(tmpdir, ["is_reconciled"])
            self.assertFalse(found)

    def test_scan_src_includes_hand_written_tsx(self):
        """Scan finds tokens in hand-written .tsx files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "src"
            src_dir.mkdir()
            (src_dir / "Component.tsx").write_text("export const MyComponent = () => { return <div>{is_reconciled}</div>; };")

            found = api_consumption.scan_src_for_tokens(tmpdir, ["is_reconciled"])
            self.assertTrue(found)

    def test_build_adoption_section(self):
        """Build adoption section from manifest and scanned tokens."""
        manifest = {
            "Feature A": ["token_a", "token_b"],
            "Feature B": ["token_c"],
            "Feature C": ["token_d"],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "src"
            src_dir.mkdir()
            # Feature A and B have tokens; C doesn't
            (src_dir / "file1.ts").write_text("const token_a = 1; const token_b = 2; const token_c = 3;")

            section = api_consumption.build_adoption_section(tmpdir, manifest)
            self.assertIsNotNone(section)
            self.assertEqual(section["kind"], "split")
            self.assertEqual(section["title"], "Contract adoption")

            adopted = section["columns"][0]["items"]
            pending = section["columns"][1]["items"]

            self.assertEqual(len(adopted), 2)
            self.assertEqual(len(pending), 1)

            adopted_texts = [item["text"] for item in adopted]
            self.assertIn("Feature A", adopted_texts)
            self.assertIn("Feature B", adopted_texts)

            pending_texts = [item["text"] for item in pending]
            self.assertIn("Feature C", pending_texts)

    def test_build_adoption_section_empty_manifest(self):
        """Empty manifest returns None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            section = api_consumption.build_adoption_section(tmpdir, {})
            self.assertIsNone(section)

    def test_load_adoption_manifest(self):
        """Load adoption manifest from JSON file."""
        manifest = api_consumption.load_adoption_manifest()
        # Manifest should have been created at bin/collect/contract_adoption.json
        self.assertIsInstance(manifest, dict)
        self.assertIn("Invoice ledger (is_reconciled)", manifest)
        self.assertIn("Order requests", manifest)


if __name__ == "__main__":
    unittest.main()
