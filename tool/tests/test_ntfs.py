"""The pure-Python NTFS reader must agree with The Sleuth Kit.

tests/fixtures/ntfs_small.img.gz was made by make_ntfs_fixture.py with mkntfs and
ntfs-3g, and ntfs_small_truth.json is what pytsk3 (The Sleuth Kit) reports for
every live file in it. These tests need neither tool, only the two fixture files.
"""

import gzip
import hashlib
import json
import os
import shutil
import tempfile
import unittest
from collections import defaultdict

from ads import pipeline
from ads.config import load_config
from ads.ntfs import NTFSVolume, decode_runs
from ads.triage import Triage

HERE = os.path.dirname(os.path.abspath(__file__))
IMG_GZ = os.path.join(HERE, "fixtures", "ntfs_small.img.gz")
TRUTH = os.path.join(HERE, "fixtures", "ntfs_small_truth.json")


class NTFSFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.img = os.path.join(cls.tmp.name, "ntfs_small.img")
        with gzip.open(IMG_GZ) as src, open(cls.img, "wb") as dst:
            shutil.copyfileobj(src, dst)
        with open(TRUTH, encoding="utf-8") as fh:
            cls.truth = json.load(fh)["files"]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()


class TestReaderMatchesSleuthKit(NTFSFixture):
    def test_every_live_file_matches_path_size_contents_and_times(self):
        vol = NTFSVolume(self.img)
        mine = {e.entry: e for e in vol.walk() if not e.is_dir and not e.deleted}
        by_entry = defaultdict(list)
        for path, t in self.truth.items():
            by_entry[t["entry"]].append((path, t))
        self.assertEqual(set(mine), set(by_entry), "the reader lists exactly the files The Sleuth Kit lists")
        for entry, items in by_entry.items():
            e, t = mine[entry], items[0][1]
            with self.subTest(path=items[0][0]):
                self.assertIn(vol.path_of(e), [p for p, _ in items])     # hard links: any of the names
                self.assertEqual(e.size, t["size"])
                self.assertEqual(hashlib.sha256(vol.read(e)).hexdigest(), t["sha256"])
                self.assertEqual(list(e.si), t["si"])
        vol.close()

    def test_hard_cases_are_present(self):
        vol = NTFSVolume(self.img)
        by_name = {e.name: e for e in vol.walk() if not e.is_dir}
        self.assertGreater(len(by_name["frag.log"].runs), 1, "fixture really holds a fragmented file")
        self.assertIsNotNone(by_name["tiny.conf"].resident, "fixture really holds a resident file")
        linked = by_name["linked.dat"]
        self.assertTrue(any(a[0] == 0x20 for a in vol.records[linked.entry]["attrs"]), "attribute list present")
        self.assertTrue(by_name["hidden.txt"].hidden)
        self.assertTrue(by_name["deleted.txt"].deleted)
        self.assertEqual(vol.summary()["fs_type"], "NTFS")
        self.assertEqual(vol.summary()["label"], "Disk")
        vol.close()

    def test_runlist_decoding(self):
        # 0x21: 1-byte length, 2-byte offset. Second run is relative (-0x10) to the first; 0x01 is sparse.
        self.assertEqual(decode_runs(bytes([0x21, 0x08, 0x00, 0x01, 0x21, 0x04, 0xF0, 0xFF, 0x01, 0x03, 0x00])),
                         [(0x100, 8), (0xF0, 4), (None, 3)])


class TestNTFSInThePipeline(NTFSFixture):
    def test_first_look_report_opens_ntfs_images(self):
        t = Triage(self.img)
        self.addCleanup(t.close)          # closed even if a step fails (Windows cannot delete open files)
        t.collect().run()
        self.assertEqual(t.vol.summary()["fs_type"], "NTFS")
        paths = {i["path"] for i in t.items}
        self.assertIn("/Disk/bin/gzip", paths)
        self.assertIn("/Disk/tmp/.font-unix/fs-1/ini/template.pdf", paths)
        data = t.to_json()
        self.assertIn("NTFS volume", data["not_applicable"])

    def test_date_rules_run_straight_from_the_image(self):
        cfg = load_config(None)
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "case.sqlite")
            summary = pipeline.ingest_image(self.img, db, cfg)
            self.assertEqual(summary[0]["kind"], "mft")
            r = pipeline.analyze_db(db, os.path.join(d, "out"), cfg)
            self.assertGreater(r["scored"], 150)
            import csv
            with open(os.path.join(d, "out", "outcomes.csv"), encoding="utf-8") as fh:
                evaluable = {row["rule"] for row in csv.DictReader(fh) if row["outcome"] != "not_evaluable"}
            self.assertEqual(evaluable, {"R6", "R7", "R11"}, "only the MFT-only rules can run from the MFT alone")

    def test_self_calibration_is_used_and_recorded(self):
        cfg = load_config(None)
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "case.sqlite")
            pipeline.ingest_image(self.img, db, cfg)
            pipeline.analyze_db(db, os.path.join(d, "out"), cfg, self_calibrate=True)
            with open(os.path.join(d, "out", "run.json"), encoding="utf-8") as fh:
                run = json.load(fh)
            self.assertEqual(run["calibration"], "(rates measured on this image)")
            self.assertIsNotNone(run["weights"]["R7"]["p_r"])


if __name__ == "__main__":
    unittest.main()
