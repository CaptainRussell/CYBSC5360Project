"""Build test block sets whose true answer is known.

Each set is one PDF, one Word (.doc) and one JPEG, made fresh from a seed, cut into
512-byte blocks, shuffled, and renamed BLOCK0001... like the course's set. The
answer key (which file and position each block came from) is written beside it.

Needs LibreOffice (soffice) and Pillow, which only the test builder uses; the
toolkit itself is standard-library Python.

    py -3 eval/make_sets.py --out eval/sets --seeds 1 2 3
"""

import argparse
import csv
import hashlib
import io
import math
import os
import random
import shutil
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
TEXT_SOURCE = os.path.join(HERE, "..", "..", "paper", "paper.md")


def landscape(rng, w, h):
    """A painted-looking landscape: sky gradient, fractal hills, texture and a few shapes."""
    sky = Image.new("RGB", (w, h))
    top = (rng.randint(60, 140), rng.randint(90, 170), rng.randint(170, 240))
    low = (rng.randint(200, 255), rng.randint(140, 210), rng.randint(110, 190))
    px = sky.load()
    for y in range(h):
        t = y / h
        c = tuple(int(top[i] * (1 - t) + low[i] * t) for i in range(3))
        for x in range(w):
            px[x, y] = c
    d = ImageDraw.Draw(sky)
    for layer in range(4):
        base = h * (0.45 + 0.13 * layer)
        amp = h * (0.10 - 0.02 * layer)
        pts = []
        phase = [rng.random() * 6.28 for _ in range(5)]
        for x in range(0, w + 8, 8):
            y = base + sum(amp / (k + 1) * math.sin(x / w * (k + 1) * 6.28 + phase[k]) for k in range(5))
            pts.append((x, y))
        pts += [(w, h), (0, h)]
        g = (rng.randint(30, 120), rng.randint(70, 160), rng.randint(20, 90))
        d.polygon(pts, fill=g)
    for _ in range(rng.randint(3, 8)):
        x, y, r = rng.randint(0, w), rng.randint(0, h), rng.randint(5, w // 12)
        d.ellipse((x - r, y - r, x + r, y + r), fill=tuple(rng.randint(0, 255) for _ in range(3)))
    noise = Image.effect_noise((w, h), rng.randint(20, 45)).convert("RGB")
    out = Image.blend(sky, noise, 0.12).filter(ImageFilter.GaussianBlur(0.8))
    return out


def paragraphs(rng, n):
    with open(TEXT_SOURCE, encoding="utf-8") as fh:
        paras = [p.strip().replace("\n", " ") for p in fh.read().split("\n\n") if len(p.strip()) > 80]
    start = rng.randint(0, max(0, len(paras) - n))
    return paras[start:start + n]


def soffice(src, fmt, outdir):
    subprocess.run(["soffice", "--headless", "--convert-to", fmt, "--outdir", outdir, src],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)


def make_files(seed, work):
    rng = random.Random(seed)
    # JPEG
    w, h = rng.choice([(640, 480), (800, 600), (720, 540)])
    img = landscape(rng, w, h)
    jb = io.BytesIO()
    img.save(jb, "JPEG", quality=rng.choice([75, 85, 92]),
             subsampling=rng.choice([0, 2]), **({"restart_marker_rows": 1} if rng.random() < 0.3 else {}))
    jpg = jb.getvalue()
    # Word: text only, from the paper
    html = "<html><body>%s</body></html>" % "".join(
        "<h2>%s</h2>" % p[:60] if i % 7 == 0 else "<p>%s</p>" % p for i, p in enumerate(paragraphs(rng, 30)))
    hp = os.path.join(work, "doc.html")
    with open(hp, "w", encoding="utf-8") as fh:
        fh.write(html)
    soffice(hp, "doc:MS Word 97", work)
    with open(os.path.join(work, "doc.doc"), "rb") as fh:
        doc = fh.read()
    # PDF: text plus a small picture
    pic = landscape(rng, 300, 200)
    pic_path = os.path.join(work, "pic.jpg")
    pic.save(pic_path, "JPEG", quality=85)
    html = "<html><body>%s<img src='pic.jpg'>%s</body></html>" % (
        "".join("<p>%s</p>" % p for p in paragraphs(rng, 8)), "".join("<p>%s</p>" % p for p in paragraphs(rng, 8)))
    hp = os.path.join(work, "pdf.html")
    with open(hp, "w", encoding="utf-8") as fh:
        fh.write(html)
    # keep the picture as it is (no downsampling, which would re-encode it as a progressive JPEG)
    soffice(hp, 'pdf:writer_web_pdf_Export:{"ReduceImageResolution":{"type":"boolean","value":"false"}}', work)
    with open(os.path.join(work, "pdf.pdf"), "rb") as fh:
        pdfdata = fh.read()
    return {"PDF": pdfdata, "Word": doc, "JPEG": jpg}


def make_set(seed, out):
    work = tempfile.mkdtemp()
    try:
        files = make_files(seed, work)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    rng = random.Random(seed * 7919)
    pieces = []
    for kind, data in files.items():
        data += b"\0" * (-len(data) % 512)
        for p in range(len(data) // 512):
            pieces.append((kind, p, data[512 * p:512 * (p + 1)]))
    rng.shuffle(pieces)
    d = os.path.join(out, "set%02d" % seed)
    blocks = os.path.join(d, "blocks")
    os.makedirs(blocks, exist_ok=True)
    with open(os.path.join(d, "answer_key.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["block", "file", "position"])
        for i, (kind, p, data) in enumerate(pieces, 1):
            name = "BLOCK%04d" % i
            with open(os.path.join(blocks, name), "wb") as bf:
                bf.write(data)
            w.writerow([name, kind, p])
    for kind, data in files.items():
        with open(os.path.join(d, "original." + {"PDF": "pdf", "Word": "doc", "JPEG": "jpg"}[kind]), "wb") as fh:
            fh.write(data)
    return d, {k: len(v) for k, v in files.items()}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "sets"))
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3])
    a = ap.parse_args()
    for s in a.seeds:
        d, sizes = make_set(s, a.out)
        print(d, sizes)
