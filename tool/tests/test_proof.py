"""Proof of function: the scorer must reproduce the Project 1 comparison from the saved run."""

import csv
import os
import tempfile
import unittest

from ads import proof

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.dirname(HERE)
P1_RESULTS = os.path.join(TOOL, "results", "26Fall_Project1B")
P1_KEY = os.path.join(TOOL, "proof", "project1_answer_key.csv")
P2_KEY = os.path.join(TOOL, "proof", "project2_answer_key.csv")


class TestProjectOneReproduced(unittest.TestCase):
    def test_ranks_match_the_published_comparison(self):
        # comparison.md (written by hand from the same run): ranks of each item.
        want = {"transit/constants.java": 2, "figures/koala.jpg": 3, "docs/manual.docx": 4, "bin/cref_t1.exe": 5,
                "legal/readme.txt": 6, "sys/apt/methods/ssh": 7, "hello_world.zip › hello_world/sales.xls": 8,
                "hello_world.zip": 16, "temp.gif": 1}
        leads, _ = proof.load_run(P1_RESULTS)
        got = {s["alts"][0]: s["rank"] for s in proof.score(proof.load_key(P1_KEY), leads)}
        self.assertEqual(got, want)

    def test_summary_and_files(self):
        with tempfile.TemporaryDirectory() as d:
            path, s = proof.write(P1_RESULTS, P1_KEY, d)
            self.assertEqual((s["found"], s["evidence"], s["top10"], s["deepest"]), (7, 7, 6, 16))
            self.assertEqual((s["decoys_flagged"], s["decoys"]), (2, 2))
            page = open(path, encoding="utf-8").read()
            self.assertNotIn("@verdict@", page)
            with open(os.path.join(d, "proof.csv"), encoding="utf-8") as fh:
                self.assertEqual(len(list(csv.DictReader(fh))), 9)


class TestMatching(unittest.TestCase):
    def test_suffix_must_end_on_a_folder_boundary(self):
        self.assertTrue(proof._matches("/Disk/bin/gzip", "bin/gzip"))
        self.assertTrue(proof._matches("\\disk\\bin\\gzip", "bin/gzip"))           # date-report paths
        self.assertFalse(proof._matches("/Disk/sbin/gzip", "bin/gzip"))            # not a boundary
        self.assertFalse(proof._matches("/x/hello_world.zip › a/Sales.xls", "hello_world.zip"))
        self.assertTrue(proof._matches("/x/hello_world.zip › a/Sales.xls", "a/sales.xls"))

    def test_project_two_key_is_well_formed(self):
        key = proof.load_key(P2_KEY)
        self.assertEqual(sum(1 for k in key if k["question"] == "QA"), 5, "five envelope labels")
        self.assertTrue(all(k["kind"] in ("evidence", "decoy") for k in key))
        self.assertTrue(all(a and not a.startswith("/") for k in key for a in k["alts"]))


if __name__ == "__main__":
    unittest.main()
