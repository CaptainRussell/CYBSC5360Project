"""Tests for ADS on the synthetic fixtures. Run from the tool folder:

    python -m unittest discover -s tests -v
"""

import csv
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import make_fixtures  # noqa: E402
from ads import db, loaders, paths  # noqa: E402
from ads.cli import main  # noqa: E402
from ads.config import load_config  # noqa: E402
from ads.indicators import evaluate_indicators  # noqa: E402
from ads.rules import CONSISTENT, NOT_EVALUABLE, VIOLATED, Context, evaluate_all  # noqa: E402
from ads.scoring import compute_weights, score_files  # noqa: E402
from ads.timeutil import fmt_ts, parse_ts, subsecond  # noqa: E402

C, V, N = CONSISTENT, VIOLATED, NOT_EVALUABLE
REPORT, BUDGET, NOTES, PHOTO, MEMO = (100, 2), (105, 1), (110, 4), (115, 1), (120, 6)


def build_case(tmp, case):
    fx = os.path.join(tmp, "fixtures")
    if not os.path.isdir(fx):
        make_fixtures.build(fx)
    con = db.connect(os.path.join(tmp, case + ".sqlite"))
    d = os.path.join(fx, case)
    loaders.load_mft(con, os.path.join(d, "mft.csv"))
    loaders.load_usn(con, os.path.join(d, "usn.csv"))
    loaders.load_lnk(con, os.path.join(d, "lnk.csv"))
    loaders.load_prefetch(con, os.path.join(d, "prefetch.csv"))
    loaders.load_evtx(con, os.path.join(d, "evtx.csv"))
    con.commit()
    cfg = load_config()
    return Context(con, cfg)


def outcome_map(ctx):
    out = {}
    for key, rid, outcome, details in evaluate_all(ctx):
        out[(key, rid)] = (outcome, details)
    return out


class TimeAndPaths(unittest.TestCase):
    def test_round_trip_keeps_100ns(self):
        s = "2026-10-12 11:00:00.7777777"
        self.assertEqual(fmt_ts(parse_ts(s)), s)
        self.assertEqual(subsecond(parse_ts(s)), 7777777)

    def test_offsets_and_blanks(self):
        self.assertEqual(parse_ts("2026-10-12T13:00:00+02:00"), parse_ts("2026-10-12 11:00:00"))
        self.assertEqual(parse_ts("2026-10-12T11:00:00Z"), parse_ts("2026-10-12 11:00:00"))
        self.assertIsNone(parse_ts(""))
        self.assertIsNone(parse_ts("1601-01-01 00:00:00"))
        self.assertEqual(parse_ts("2026-10-12 11:00:00"), parse_ts("2026-10-12 11:00:00.0000000"))

    def test_path_normalization(self):
        want = r"\users\bob\documents\x.docx"
        self.assertEqual(paths.join_mft_path(r".\Users\bob\Documents", "x.docx"), want)
        self.assertEqual(paths.norm_path(r"C:\Users\bob\Documents\x.docx"), want)
        self.assertEqual(paths.norm_path(r"\VOLUME{01d9-1234}\USERS\BOB\DOCUMENTS\X.DOCX"), want)
        self.assertEqual(paths.from_shell_path(r"My Computer\C:\Users\bob\Documents\x.docx"), want)
        self.assertEqual(paths.anchor_suffixes(r"\c\users\bob\x.lnk"), [r"\users\bob\x.lnk"])


class CleanCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.ctx = build_case(cls.tmp, "clean")
        cls.o = outcome_map(cls.ctx)

    def expect(self, key, table):
        got = {rid: self.o[(key, rid)][0] for rid in table}
        self.assertEqual(got, table)

    def test_joins(self):
        self.assertEqual(self.ctx.lnk_unresolved, 0)
        joins = {l["target_key"]: l["join"] for l in self.ctx.lnks}
        self.assertEqual(joins[REPORT], "mft_reference")   # hex entry number
        self.assertEqual(joins[BUDGET], "path")             # LocalPath only
        self.assertEqual(joins[MEMO], "mft_reference")
        self.assertTrue(all(l["own_key"] for l in self.ctx.lnks))   # E:\C mount prefix resolved

    def test_benign_report_is_fully_consistent(self):
        self.expect(REPORT, {"R1": N, "R2": C, "R3": C, "R4": C, "R5": C, "R6": C, "R7": C,
                             "R8": C, "R9": C, "R10": N, "R11": C})

    def test_t1_sia_stomp(self):
        self.expect(BUDGET, {"R1": V, "R2": V, "R3": C, "R4": V, "R5": N, "R6": V, "R7": V,
                             "R8": V, "R9": V, "R10": V, "R11": V})
        hits = self.o[(BUDGET, "R10")][1]["coinciding_executions"]
        self.assertEqual([h["exe"] for h in hits], ["util.exe"])
        self.assertTrue(hits[0]["file_in_files_loaded"])

    def test_t3_backdated_new_file(self):
        # SIA-E was not altered and FNA was backdated too, so R1 and R6 stay consistent.
        self.expect(NOTES, {"R1": C, "R2": N, "R5": N, "R6": C, "R7": V, "R8": V, "R10": V, "R11": V})

    def test_archive_extraction_is_benign_noise(self):
        self.expect(PHOTO, {"R1": C, "R5": C, "R6": C, "R7": V, "R8": C, "R10": V, "R11": C})

    def test_office_save_tunneling_explains_r8(self):
        outcome, details = self.o[(MEMO, "R8")]
        self.assertEqual(outcome, C)
        self.assertIn("explained_by_tunneling", details)
        self.expect(MEMO, {"R2": C, "R3": C, "R4": C, "R9": C})

    def test_no_indicators_fire(self):
        status = {i["id"]: i["status"] for i in evaluate_indicators(self.ctx)}
        self.assertEqual(status, {"S1": "clear", "S2": "clear", "S3": "clear", "S4": "clear", "S5": "clear"})

    def test_scoring_flags_only_tampered(self):
        rows = list(evaluate_all(self.ctx))
        w = compute_weights(self.ctx.cfg, None, "equal")
        scored = score_files(self.ctx, rows, w, evaluate_indicators(self.ctx), 0.5)
        flagged = {(r["entry"], r["seq"]) for r in scored if r["flagged"]}
        self.assertEqual(flagged, {BUDGET, NOTES})
        by = {(r["entry"], r["seq"]): r for r in scored}
        self.assertAlmostEqual(by[BUDGET]["score"], 9 / 10)
        self.assertAlmostEqual(by[NOTES]["score"], 4 / 6)
        self.assertAlmostEqual(by[PHOTO]["score"], 2 / 7)
        self.assertEqual(by[BUDGET]["evaluable"], 10)


class TamperedCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.ctx = build_case(cls.tmp, "tampered")
        cls.o = outcome_map(cls.ctx)
        cls.ind = {i["id"]: i for i in evaluate_indicators(cls.ctx)}

    def test_all_indicators_fire(self):
        self.assertEqual({k: v["status"] for k, v in self.ind.items()},
                         {"S1": "fired", "S2": "fired", "S3": "fired", "S4": "fired", "S5": "fired"})

    def test_indicator_details(self):
        self.assertEqual({e["event_id"] for e in self.ind["S1"]["details"]["events"]}, {104, 1102})
        self.assertTrue(self.ind["S2"]["details"]["unwrapped_journal_starts_late"])
        self.assertEqual(self.ind["S3"]["details"]["record_gaps"][0]["missing"], 2)
        shifts = {c["shift_s"] for c in self.ind["S4"]["details"]["changes"]}
        self.assertEqual(shifts, {-172800.0})
        self.assertEqual(self.ind["S5"]["details"]["prefetch_in_journal_but_absent"], ["cleaner.exe-55aa66bb.pf"])
        self.assertEqual(self.ind["S5"]["details"]["lnk_in_journal_but_absent"], ["secret.lnk"])

    def test_journal_rules_not_evaluable_after_reset(self):
        for rid in ("R1", "R8", "R10"):
            self.assertEqual(self.o[(BUDGET, rid)][0], N, rid)

    def test_stomped_file_still_flagged_without_journal(self):
        rows = list(evaluate_all(self.ctx))
        w = compute_weights(self.ctx.cfg, None, "equal")
        scored = score_files(self.ctx, rows, w, list(self.ind.values()), 0.5)
        by = {(r["entry"], r["seq"]): r for r in scored}
        self.assertTrue(by[BUDGET]["flagged"])
        self.assertIn("R3", by[BUDGET]["consistent_from_degraded_sources"])   # LNK degraded by S5
        self.assertLess(by[BUDGET]["confidence"], 1.0)


class CommandLine(unittest.TestCase):
    def test_end_to_end(self):
        tmp = tempfile.mkdtemp()
        fx = os.path.join(tmp, "fx")
        make_fixtures.build(fx)
        c = os.path.join(fx, "clean")
        dbp, out, cal = os.path.join(tmp, "c.sqlite"), os.path.join(tmp, "out"), os.path.join(tmp, "cal.json")
        main(["ingest", "--db", dbp, "--mft", c + "/mft.csv", "--usn", c + "/usn.csv", "--lnk", c + "/lnk.csv",
              "--prefetch", c + "/prefetch.csv", "--evtx", c + "/evtx.csv"])
        # Calibrating on the same image is only a smoke test; real runs use the benign baseline.
        main(["calibrate", "--db", dbp, "--out", cal])
        main(["analyze", "--db", dbp, "--out", out, "--calibration", cal])
        for f in ("scores.csv", "outcomes.csv", "indicators.json", "clusters.csv", "report.md", "run.json"):
            self.assertTrue(os.path.exists(os.path.join(out, f)), f)
        with open(os.path.join(out, "run.json")) as fh:
            run = json.load(fh)
        self.assertEqual(len(run["inputs"]), 5)
        self.assertTrue(all(len(i["sha256"]) == 64 for i in run["inputs"]))
        truth = os.path.join(fx, "ground_truth.csv")
        main(["evaluate", "--results", out, "--truth", truth])
        with open(os.path.join(out, "evaluation.csv")) as fh:
            ev = {r["detector"]: r for r in csv.DictReader(fh)}
        self.assertEqual(float(ev["ADS"]["auc"]), 1.0)
        self.assertEqual(int(ev["ADS"]["tp"]), 2)
        self.assertEqual(int(ev["ADS"]["fp"]), 0)
        self.assertGreater(int(ev["R7 only"]["fp"]), 0)   # single rule trips on benign photo.jpg
        main(["evaluate", "--results", out, "--truth", truth, "--set-theta", cal, "--target-fpr", "0.0"])
        with open(cal) as fh:
            self.assertIn("theta", json.load(fh))
        with self.assertRaises(SystemExit):
            main(["ingest", "--db", dbp, "--mft", c + "/mft.csv"])   # refuses to overwrite


if __name__ == "__main__":
    unittest.main()
