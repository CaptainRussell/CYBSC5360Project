"""Tests for the FAT reader and triage checks on a synthetic FAT16 image.

    python -m unittest discover -s tests -v
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import make_fat_fixture  # noqa: E402
from ads import sniff  # noqa: E402
from ads.cli import main  # noqa: E402
from ads.fat import FATVolume  # noqa: E402
from ads.triage import Triage  # noqa: E402


class FatTriage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.img = os.path.join(cls.tmp, "test.img")
        make_fat_fixture.build(cls.img)
        cls.t = Triage(cls.img)
        try:
            cls.t.collect().run()
        finally:
            cls.t.close()
        cls.by = {i["path"]: i for i in cls.t.items}

    def fired(self, path):
        return self.by[path]["fired"]

    def test_reader(self):
        v = FATVolume(self.img)
        self.addCleanup(v.close)
        self.assertEqual(v.fat_type, 16)
        names = {e.path: e for e in v.walk()}
        self.assertIn("/docs/figures/photo.jpg", names)            # long names
        self.assertTrue(names["/old.txt"].deleted)
        self.assertEqual(v.read(names["/old.txt"]), b"deleted content " * 10)   # recovered
        self.assertEqual(str(names["/bin/tool"].modified), "2011-09-06 14:02:00")

    def test_sniff(self):
        self.assertEqual(sniff.sniff(make_fat_fixture.jpeg(10))[0], "jpeg")
        self.assertEqual(sniff.ole_kind(make_fat_fixture.encrypted_ooxml())[:2], ("encrypted-ooxml", True))
        j = make_fat_fixture.jpeg(50)
        self.assertEqual(sniff.jpeg_end(j + b"trailing"), len(j))

    def test_planted_findings(self):
        self.assertEqual(self.fired("/bin/tool"), ["C4", "F1"])
        self.assertIn("C1", self.fired("/legal/ReadMe.txt"))
        self.assertIn("C3", self.fired("/docs/notes.docx"))
        self.assertIn("F1", self.fired("/docs/notes.docx"))
        photo = self.by["/docs/figures/photo.jpg"]
        self.assertTrue({"C2", "C5", "C6"} <= set(photo["fired"]))
        self.assertEqual(photo["outcomes"]["C2"][1]["hidden_members"][0]["name"], "suspect.jpg")
        self.assertIn("C7", self.fired("/mail.zip"))
        hit = self.by["/bin/tool"]["outcomes"]["C4"][1]["hits"][0]
        self.assertEqual(hit["candidate"], "hunter42x")

    def test_ordinary_files_are_quiet(self):
        quiet = [p for p, i in self.by.items() if p.startswith("/lib/") and i.get("fired")]
        self.assertEqual(quiet, [])
        self.assertEqual(self.by["/docs/._notes.docx"]["noise"], "Mac hidden helper files (names starting \u201c._\u201d)")

    def test_ranking(self):
        top = [i["path"] for i in self.t.leads()[:4]]
        self.assertEqual(set(top), {"/bin/tool", "/legal/ReadMe.txt", "/docs/figures/photo.jpg", "/docs/notes.docx"})

    def test_cli_writes_briefing(self):
        out = os.path.join(self.tmp, "out")
        with contextlib.redirect_stdout(io.StringIO()):
            main(["triage", self.img, "--out", out, "--no-open"])
        for f in ("briefing.html", "triage.json", "leads.csv"):
            self.assertTrue(os.path.exists(os.path.join(out, f)), f)
        with open(os.path.join(out, "triage.json")) as fh:
            self.assertEqual(json.load(fh)["image"]["fs_type"], "FAT16")
        with open(os.path.join(out, "briefing.html"), encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn("/bin/tool", html)
        self.assertNotIn("__DATA__", html)
        self.assertIn("Created by Captain Scott Russell for CPRE 5360", html)
        self.assertNotIn("Every finding is a reason to look", html)
        with open(os.path.join(out, "leads.csv"), encoding="utf-8") as fh:
            self.assertIn("Password written down", fh.read())

    def test_image_path_alone_runs_triage(self):
        out = os.path.join(self.tmp, "short")
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            main([self.img, "--out", out, "--no-open"])
        self.assertTrue(os.path.exists(os.path.join(out, "briefing.html")))
        self.assertIn("Look first", buf.getvalue())

    def test_plain_wording(self):
        say = self.by["/legal/ReadMe.txt"]["outcomes"]["C1"][1]["say"]
        self.assertIn("really a photo", say)
        self.assertNotIn("JPEG", say.split("(")[0])


if __name__ == "__main__":
    unittest.main()
