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


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class TestExplain(unittest.TestCase):
    def test_every_rule_has_plain_words(self):
        for rid in RULE_IDS:
            self.assertTrue(explain.rule_name(rid))
            self.assertTrue(explain.rule_what(rid))

    def test_say_uses_the_values(self):
        s = explain.say("R6", {"si_c": "2019-03-01 12:00:00", "fn_c": "2026-10-10 09:20:00"})
        self.assertIn("1 Mar 2019", s)
        self.assertIn("10 Oct 2026", s)

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
            html = _read(os.path.join(out, "briefing.html"))
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
            page = _read(path)
            self.assertIn("<svg", page)
            self.assertNotIn("@verdict@", page)
            self.assertTrue(os.path.exists(os.path.join(out, "roc.svg")))



# ---- Regression tests for the review fixes -----------------------------------------------------


class TestCalibrationRecorded(unittest.TestCase):
    """analyze must record which calibration it used (it once always claimed 'none')."""

    def test_report_and_run_json_name_the_calibration(self):
        import json
        from ads.cli import main
        with tempfile.TemporaryDirectory() as d:
            db, cal, out = (os.path.join(d, n) for n in ("c.sqlite", "cal.json", "out"))
            main(["ingest", "--db", db, "--mft", TAMPERED + "/mft.csv", "--usn", TAMPERED + "/usn.csv"])
            main(["calibrate", "--db", db, "--out", cal])
            main(["analyze", "--db", db, "--out", out, "--calibration", cal])
            run = json.loads(_read(os.path.join(out, "run.json")))
            self.assertEqual(run["calibration"], cal)
            md = _read(os.path.join(out, "report.md"))
            self.assertNotIn("no baseline calibration", md)


class TestCsvDetection(unittest.TestCase):
    def test_zimmerman_default_names_go_to_one_kind_each(self):
        c = pipeline.classify_csv
        self.assertEqual(c("20261010_MFTECmd_$J_Output.csv"), "usn")      # not mft, despite "MFTECmd"
        self.assertEqual(c("20261010_MFTECmd_$MFT_Output.csv"), "mft")
        self.assertEqual(c("20261010_PECmd_Output.csv"), "prefetch")
        self.assertIsNone(c("20261010_PECmd_Output_Timeline.csv"))       # side output, not an input
        self.assertEqual(c("20261010_LECmd_Output.csv"), "lnk")
        self.assertEqual(c("EVTX_SYSTEM.CSV"), "evtx")                   # case does not matter
        self.assertIsNone(c("hashes.csv"))
        self.assertIsNone(c("notes.txt"))


class TestFastRocMatchesDefinition(unittest.TestCase):
    """The sort-based roc/auc must equal the pairwise definitions they replaced."""

    def test_random_cases(self):
        import random
        from ads.evaluate import auc, roc
        rng = random.Random(7)
        for _ in range(200):
            n = rng.randint(2, 40)
            sc = {i: rng.choice([0, 0, 0.25, 0.5, 1.0, rng.random()]) for i in range(n)}
            lb = {i: rng.random() < 0.3 for i in range(n)}
            pos = sum(lb.values())
            neg = n - pos
            want = [(0.0, 0.0, float("inf"))]
            for t in sorted(set(sc.values()) | {-1.0}, reverse=True):
                tp = sum(1 for k, s in sc.items() if s > t and lb[k])
                fp = sum(1 for k, s in sc.items() if s > t and not lb[k])
                want.append((fp / neg if neg else 0.0, tp / pos if pos else 0.0, t))
            self.assertEqual(roc(sc, lb), want)
            p = [s for k, s in sc.items() if lb[k]]
            q = [s for k, s in sc.items() if not lb[k]]
            got = auc(sc, lb)
            if not p or not q:
                self.assertIsNone(got)
            else:
                exp = sum(1.0 if a > b else 0.5 if a == b else 0.0 for a in p for b in q) / (len(p) * len(q))
                self.assertAlmostEqual(got, exp, places=12)


class TestChartsBestCheck(unittest.TestCase):
    def test_best_single_check_is_chosen_at_the_target_false_alarm_rate(self):
        rows = [
            {"detector": "ADS", "auc": 0.9, "tpr_at_fpr_0.01": 0.6, "points": [(0, 0), (1, 1)], "precision": 1},
            # Higher AUC, but worse at 1% false alarms: must NOT be called the best single check.
            {"detector": "R1 only", "auc": 0.95, "tpr_at_fpr_0.01": 0.1, "points": [(0, 0), (1, 1)], "precision": 1},
            {"detector": "R8 only", "auc": 0.70, "tpr_at_fpr_0.01": 0.5, "points": [(0, 0), (1, 1)], "precision": 1},
        ]
        with tempfile.TemporaryDirectory() as d:
            page = _read(charts.render({"tampered": 2, "benign": 9, "detectors": rows}, d))
            self.assertIn(explain.rule_name("R8"), page.split("</p>")[0])


class TestPlainWording(unittest.TestCase):
    def test_r4_name_matches_what_the_rule_flags(self):
        self.assertIn("after", explain.rule_name("R4"))

    def test_dates_are_plain_and_say_utc(self):
        self.assertEqual(explain.nice("2026-10-10 09:25:03.5555555"), "10 Oct 2026, 09:25:03 UTC")
        self.assertIn("UTC", explain.say("R8", {"filecreate_time": "2026-10-10 09:20:00.0000000",
                                                "si_c": "2019-03-01 12:00:00.0000000"}))


class TestGuiRefusesOtherSites(unittest.TestCase):
    """The control panel must only obey its own page: right Host header and the per-run token."""

    def setUp(self):
        import threading
        from http.server import ThreadingHTTPServer
        from ads import gui
        self.gui = gui
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), gui.Handler)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def _req(self, method, path, body=None, host=None):
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Host": host or "127.0.0.1:%d" % self.port}
        if body is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        c.request(method, path, body=body, headers=headers)
        r = c.getresponse()
        data = r.read().decode("utf-8")
        c.close()
        return r.status, data

    def test_page_carries_token_and_run_needs_it(self):
        status, page = self._req("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(self.gui.TOKEN, page)
        self.assertNotIn("@TOKEN@", page)
        body = "kind=ntfs&path=%s" % TAMPERED
        self.assertEqual(self._req("POST", "/run", body)[0], 403)                       # no token
        self.assertEqual(self._req("POST", "/run", body + "&t=wrong")[0], 403)          # wrong token
        self.assertEqual(self._req("GET", "/status?job=x")[0], 403)                      # no token

    def test_foreign_host_header_is_refused(self):
        self.assertEqual(self._req("GET", "/", host="evil.example:%d" % self.port)[0], 403)
        body = "kind=ntfs&path=%s&t=%s" % (TAMPERED, self.gui.TOKEN)
        self.assertEqual(self._req("POST", "/run", body, host="evil.example")[0], 403)


if __name__ == "__main__":
    unittest.main()
