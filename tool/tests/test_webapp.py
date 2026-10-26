"""The browser version must give exactly the answers the Python version gives.

The browser engine (tool/web/src, built by ads.webapp) is run here under Node on the
same inputs as the Python version, and every result is compared field by field with
ads.compare: the test drives, seeded stress drives full of awkward and broken files,
the synthetic Windows record sets and seeded garbled copies of them. Skipped when
Node is not installed; the page itself is checked either way.
"""

import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import warnings

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import make_date_stress  # noqa: E402
import make_fat_fixture  # noqa: E402
import make_stress_fixture  # noqa: E402
from ads import briefing, pipeline, webapp  # noqa: E402
from ads.compare import compare, diff  # noqa: E402
from ads.config import load_config  # noqa: E402
from ads.triage import Triage  # noqa: E402

NODE = shutil.which("node")
warnings.filterwarnings("ignore", message="Overlapped entries")   # zipfile's note on a deliberately broken test archive
RUN = os.path.join(TOOL, "web", "test", "run.js")


@unittest.skipUnless(NODE, "Node.js is not installed")
class SameAnswers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.engine = os.path.join(cls.tmp, "engine.js")
        with open(cls.engine, "w", encoding="utf-8") as fh:
            fh.write(webapp.engine_js())

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def node(self, *args):
        out = os.path.join(self.tmp, "out.json")
        subprocess.run([NODE, RUN, self.engine] + list(args) + [out], check=True)
        with open(out, encoding="utf-8") as fh:
            return json.load(fh)

    def first_look(self, img):
        t = Triage(img)
        try:
            t.collect().run()
            d = tempfile.mkdtemp(dir=self.tmp)
            briefing.write_triage(t, d)
        finally:
            t.close()
        with open(os.path.join(d, "triage.json"), encoding="utf-8") as fh:
            py = json.load(fh)
        with open(os.path.join(d, "leads.csv"), newline="", encoding="utf-8") as fh:
            py_csv = fh.read()
        js = self.node("triage", img)
        self.assertEqual(diff(js["data"], py), [], img)
        self.assertEqual(js["leads_csv"], py_csv, "leads.csv differs for " + img)
        self.assertEqual(js["notes"], [])
        return py

    def date_checks(self, target):
        cfg = load_config(None)
        d = tempfile.mkdtemp(dir=self.tmp)
        db, out = os.path.join(d, "case.sqlite"), os.path.join(d, "out")
        if os.path.isdir(target):
            pipeline.ingest_folder(target, db, cfg)
            args = ["csv=" + p for p in sorted(glob.glob(os.path.join(target, "*.csv")))]
        else:
            pipeline.ingest_image(target, db, cfg)
            args = ["image=" + target]
        pipeline.analyze_db(db, out, cfg, self_calibrate=True)
        js = self.node("dates", *args)
        bd = os.path.join(d, "browser")
        os.makedirs(bd)
        for name, text in js["files"].items():
            with open(os.path.join(bd, name), "w", newline="", encoding="utf-8") as fh:
                fh.write(text)
        self.assertEqual(compare(bd, out)[1], [], target)
        with open(os.path.join(out, "briefing.html"), encoding="utf-8") as fh:
            py = json.loads(fh.read().split("D = ", 1)[1].split(";</script>", 1)[0])
        keep = lambda x: {k: v for k, v in x.items() if k not in ("generated", "inputs")}   # noqa: E731
        self.assertEqual(diff(keep(js["data"]), keep(py)), [], target)

    def test_fat_fixture(self):
        img = os.path.join(self.tmp, "fat.img")
        make_fat_fixture.build(img)
        self.first_look(img)

    def test_ntfs_fixture(self):
        import gzip
        img = os.path.join(self.tmp, "ntfs.img")
        with gzip.open(os.path.join(HERE, "fixtures", "ntfs_small.img.gz")) as src, open(img, "wb") as dst:
            shutil.copyfileobj(src, dst)
        self.first_look(img)
        self.date_checks(img)

    def test_stress_drives(self):
        for seed in (1, 2):
            img = os.path.join(self.tmp, "stress%d.img" % seed)
            make_stress_fixture.build_fat(img, seed)
            py = self.first_look(img)
            fired = {r: v["violated"] for r, v in py["rules"].items()}
            self.assertTrue(all(fired.values()), fired)    # every check found something somewhere

    def test_windows_records(self):
        for case in ("clean", "tampered"):
            self.date_checks(os.path.join(HERE, "fixtures", case))
        for seed in range(1, 9):
            self.date_checks(make_date_stress.build(seed, os.path.join(self.tmp, "dates%d" % seed)))


class Page(unittest.TestCase):
    def test_build(self):
        with tempfile.TemporaryDirectory() as d:
            out = webapp.build(os.path.join(d, "app.html"))
            with open(out, encoding="utf-8") as fh:
                page = fh.read()
        for token in ("/*@css@*/", "/*@engine@*/", "/*@templates@*/", "/*@app@*/", "@version@", "@tool@"):
            self.assertNotIn(token, page)
        self.assertIn("Created by Captain Scott Russell for CPRE 5360", page)
        self.assertNotIn("<script src=", page)       # offline: nothing is fetched
        self.assertNotIn("http://", page.split("<script")[0])

    def test_committed_page_is_current(self):
        """The HTML file in the repository must be rebuilt whenever the engine or the report changes."""
        committed = os.path.join(TOOL, webapp.OUT_NAME)
        if not os.path.exists(committed):
            self.skipTest("page not built yet")
        with tempfile.TemporaryDirectory() as d:
            fresh = webapp.build(os.path.join(d, "app.html"))
            with open(fresh, encoding="utf-8") as a, open(committed, encoding="utf-8") as b:
                self.assertEqual(a.read(), b.read().replace("\r\n", "\n"), "run: python -m ads build-web")
