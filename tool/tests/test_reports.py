"""Tests for the plain-language reports and the shared pipeline added for the
usable, non-technical interface: the NTFS briefing, the evaluation charts, the
folder-based ingest, and the explanation wording."""

import os
import tempfile
import unittest

from ads import charts, explain, ntfs_briefing, pipeline
from ads.config import RULE_IDS, load_config

HERE = os.path.dirname(os.path.abspath(__file__))
TAMPERED = os.path.join(HERE, "fixtures", "tampered")
TRUTH = os.path.join(HERE, "fixtures", "ground_truth.csv")


class TestExplain(unittest.TestCase):
    def test_every_rule_has_plain_words(self):
        for rid in RULE_IDS:
            self.assertTrue(explain.rule_name(rid))
            self.assertTrue(explain.rule_what(rid))

    def test_say_uses_the_values(self):
        s = explain.say("R6", {"si_c": "2019-03-01 12:00:00", "fn_c": "2026-10-10 09:20:00"})
        self.assertIn("2019-03-01", s)
        self.assertIn("2026-10-10", s)

    def test_say_never_raises_on_missing_fields(self):
        for rid in RULE_IDS:
            self.assertIsInstance(explain.say(rid, {}), str)


class TestPipelineAndBriefing(unittest.TestCase):
    def test_folder_ingest_analyze_and_reports(self):
        cfg = load_config(None)
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "case.sqlite")
            summary = pipeline.ingest_folder(TAMPERED, db, cfg)
            kinds = {s["kind"] for s in summary}
            self.assertEqual(kinds, {"mft", "usn", "lnk", "prefetch", "evtx"})
            out = os.path.join(d, "out")
            r = pipeline.analyze_db(db, out, cfg)
            self.assertGreater(r["scored"], 0)
            # The plain-language briefing is written and is a full HTML page.
            html = open(os.path.join(out, "briefing.html"), encoding="utf-8").read()
            self.assertIn("<!doctype html>", html)
            self.assertIn("Flagged files", html)
            # No stray template tokens survived substitution.
            self.assertNotIn("@leads@", html)
            self.assertNotIn("@palette@", html)

    def test_ingest_without_mft_is_a_clear_error(self):
        cfg = load_config(None)
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(Exception):
                pipeline.ingest_folder(d, os.path.join(d, "c.sqlite"), cfg)


class TestCharts(unittest.TestCase):
    def test_roc_svg_and_summary(self):
        from ads.evaluate import evaluate
        cfg = load_config(None)
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "case.sqlite")
            pipeline.ingest_folder(TAMPERED, db, cfg)
            out = os.path.join(d, "out")
            pipeline.analyze_db(db, out, cfg)
            res = evaluate(out, TRUTH)
            path = charts.render(res, out)
            page = open(path, encoding="utf-8").read()
            self.assertIn("<svg", page)
            self.assertNotIn("@verdict@", page)
            self.assertTrue(os.path.exists(os.path.join(out, "roc.svg")))


if __name__ == "__main__":
    unittest.main()
