"""The browser edition must give the same answers as the Python toolkit.

Node runs the JavaScript engine (the very code inside BlockRecovery.html) on the same
blocks, and every block's file and position must match. Skipped when Node is not installed.

    py -3 -m unittest tests.test_web
"""

import io
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "web"))

import build  # noqa: E402
from blockrecover import recover  # noqa: E402
from blockrecover.blocks import Block  # noqa: E402

try:
    from PIL import Image
except ImportError:          # pragma: no cover
    Image = None

NODE = shutil.which("node")
COURSE_SET = os.path.join(HERE, "data", "CP3-3-blockset.zip")

DRIVER = r"""
const fs = require("fs"), path = require("path");
eval(fs.readFileSync(process.argv[2], "utf8"));
const src = process.argv[3], stages = process.argv[4].split(",");
let items = [];
if (fs.statSync(src).isDirectory()) items = fs.readdirSync(src).map(n => [n, new Uint8Array(fs.readFileSync(path.join(src, n)))]);
else items = BR.recover.readZip(new Uint8Array(fs.readFileSync(src)));
const R = BR.recover.run(BR.recover.makeBlocks(items), null, stages);
const out = BR.recover.summarize(R);
process.stdout.write(JSON.stringify({ files: out.summary.files.map(f => [f.kind, f.ok, f.md5]),
  rows: out.blocks.map(r => [r.block, r.file, r.position]) }));
"""


def python_answer(src, stages):
    R = recover.run(src, stages=stages)
    out = tempfile.mkdtemp()
    try:
        recover.write(R, out)
        with open(os.path.join(out, "summary.json"), encoding="utf-8") as fh:
            S = json.load(fh)
    finally:
        shutil.rmtree(out, ignore_errors=True)
    return {"files": [[f["kind"], f["ok"], f["md5"]] for f in S["summary"]["files"]],
            "rows": [[r["block"], r["file"], r["position"]] for r in S["blocks"]]}


@unittest.skipUnless(NODE, "Node is not installed")
class TestBrowserEdition(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.engine = os.path.join(cls.tmp, "engine.js")
        with open(cls.engine, "w", encoding="utf-8") as fh:
            fh.write(build.engine_js())
        cls.driver = os.path.join(cls.tmp, "driver.js")
        with open(cls.driver, "w", encoding="utf-8") as fh:
            fh.write(DRIVER)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def node_answer(self, src, stages):
        out = subprocess.run([NODE, "--stack-size=8000", self.driver, self.engine, src, ",".join(stages)],
                             capture_output=True, check=True, timeout=3600)
        return json.loads(out.stdout)

    def test_page_builds(self):
        page = os.path.join(self.tmp, "page.html")
        build.build(page)
        with open(page, encoding="utf-8") as fh:
            html = fh.read()
        for mark in ("/*CSS*/", "/*JS*/", "/*APP*/", "/*ENGINE*/", "/*REPORT*/"):
            self.assertNotIn(mark, html)
        self.assertIn("Created by Captain Scott Russell for CPRE 5360", html)

    def picture_folder(self, name, drop=None):
        img = Image.new("RGB", (160, 120))
        px = img.load()
        for y in range(120):
            for x in range(160):
                px[x, y] = (x * 255 // 159, y * 255 // 119, (x * y) % 256)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85)
        data = buf.getvalue()
        data += b"\0" * (-len(data) % 512)
        folder = os.path.join(self.tmp, name)
        os.makedirs(folder)
        names = ["B%03d" % i for i in range(len(data) // 512)]
        random.Random(5).shuffle(names)
        for i, n in enumerate(names):
            if i != drop:
                with open(os.path.join(folder, n), "wb") as fh:
                    fh.write(data[512 * i:512 * i + 512])
        return folder

    @unittest.skipUnless(Image, "Pillow is not installed")
    def test_same_picture_order(self):
        folder = self.picture_folder("picture")
        stages = ("PDF", "Word", "JPEG")
        self.assertEqual(self.node_answer(folder, stages), python_answer(folder, stages))

    @unittest.skipUnless(Image, "Pillow is not installed")
    def test_same_answer_when_a_block_is_missing(self):
        folder = self.picture_folder("missing", drop=6)
        stages = ("PDF", "Word", "JPEG")
        py = python_answer(folder, stages)
        self.assertEqual([f[:2] for f in py["files"]], [["JPEG", False]])
        self.assertEqual(self.node_answer(folder, stages), py)

    @unittest.skipUnless(os.path.exists(COURSE_SET), "course block set not present")
    def test_same_answer_on_course_set(self):
        stages = ("PDF", "Word")
        self.assertEqual(self.node_answer(COURSE_SET, stages), python_answer(COURSE_SET, stages))


if __name__ == "__main__":
    unittest.main()
