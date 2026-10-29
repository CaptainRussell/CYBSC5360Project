"""The whole job: sort a pile of blocks into files and put each file back together.

Order of work: the PDF first (its own map places most of it, and its encryption
lets every other block be ruled out quickly), then the Word file from what is
left, then the JPEG picture from what is left after that. A block's file is
the file it was placed in; the first-pass guess is kept beside it for comparison.
"""

import hashlib
import json
import os
import time

from . import blocks as blockmod, classify, jpegfile, pdf, streams, word
from .layout import PlaceError


# The MD5 the course published for its block set
COURSE_MD5 = "017c90727e8dfcb757ae189cacc74c18"


def fingerprint(name, data):
    """The input's hashes, recorded so anyone can confirm which evidence was analysed."""
    md5 = hashlib.md5(data).hexdigest()
    return {"name": name, "md5": md5, "sha256": hashlib.sha256(data).hexdigest(), "course_set": md5 == COURSE_MD5}


class Result:
    def __init__(self, blocks):
        self.blocks = blocks
        self.input = None          # fingerprint() of the ZIP, when the input was one
        self.files = []            # dicts: kind, name, layout, size, note, ok
        self.log = []              # (seconds, stage, message)
        self.t0 = time.time()

    def say(self, stage, *msg):
        self.log.append((round(time.time() - self.t0, 2), stage, " ".join(str(m) for m in msg)))

    def placed(self):
        out = {}
        for f in self.files:
            for p, b in enumerate(f["layout"].at):
                if b is not None:
                    out[b.name] = (f, p)
        return out


def run(path_or_blocks, progress=None, stages=("PDF", "Word", "JPEG"), thorough=False):
    blocks = blockmod.load(path_or_blocks) if isinstance(path_or_blocks, str) else path_or_blocks
    R = Result(blocks)
    if isinstance(path_or_blocks, str) and os.path.isfile(path_or_blocks):
        with open(path_or_blocks, "rb") as fh:
            R.input = fingerprint(os.path.basename(path_or_blocks), fh.read())

    def say(stage, *msg):
        R.say(stage, *msg)
        if progress:
            progress(stage, " ".join(str(m) for m in msg))

    say("start", "%d blocks of %d bytes" % (len(blocks), len(blocks[0].data) if blocks else 0))
    R.guesses = {b.name: classify.guess(b) for b in blocks}
    free = list(blocks)

    # PDF
    if "PDF" in stages and any(b.data.startswith(b"%PDF-") for b in free):
        P = pdf.PDF(free, log=say)
        try:
            P.anchor()
            for s in sorted(P.streams, key=lambda s: (s["filter"] == "DCTDecode", s["length"])):
                kind, placed = streams.order(P, s, log=say)
                for p, b in placed:
                    P.place(p, b, "inside stream %d (%s)" % (s["num"], kind))
                if placed:
                    say("stream", "object %d, %s: %d blocks ordered and checked" % (s["num"], kind, len(placed)))
            ok, note = True, "every stream decrypts and closes correctly (zlib checksums, JPEG end markers)"
        except PlaceError as e:
            ok, note = False, str(e)
            say("PDF", "stopped:", e)
        if getattr(P, "L", None) is not None:
            R.files.append(_file("PDF", "recovered.pdf", P.L, P.size, ok, note))
            free = list(P.free.values())

    # Word
    if "Word" in stages and any(b.data.startswith(word.MAGIC) for b in free):
        W = word.Word(free, log=say)
        try:
            W.anchor()
            # leftovers: low-content blocks that are not JPEG picture data. (A mostly-zero
            # Word block can pass the JPEG byte rule by chance; picture data is never that sparse.)
            from . import features
            cands = [b for b in W.free.values() if b"\xff\xd9" not in b.data and not b.data.startswith(b"\xff\xd8")
                     and features.entropy(b.data) < 6.5
                     and not (features.jpeg_scan_like(b.data) == "yes" and features.entropy(b.data) >= 6.0)]
            W.leftovers(cands)
            ok, note = all(x is not None for x in W.L.at), "header, FAT, directory and Word's own tables agree"
        except PlaceError as e:
            ok, note = False, str(e)
            say("Word", "stopped:", e)
        if getattr(W, "L", None) is not None:
            R.files.append(_file("Word", "recovered.doc", W.L, W.L.n * 512, ok, note))
            free = list(W.free.values())

    # JPEG
    if "JPEG" in stages and any(b.data[:3] == b"\xff\xd8\xff" for b in free):
        try:
            L = jpegfile.rebuild(free, log=say, beams=jpegfile.THOROUGH if thorough else jpegfile.BEAMS)
            used = {b.name for b in L.at if b}
            free = [b for b in free if b.name not in used]
            exact = getattr(L, "exact", True)
            R.files.append(_file("JPEG", "recovered.jpg", L, None, exact,
                                 "decodes to the last row, then the end-of-image marker" if exact else
                                 "best order found; some blocks could not be placed with confidence"))
        except PlaceError as e:
            say("JPEG", "stopped:", e)

    R.unplaced = free
    say("done", "%d blocks placed in %d files, %d left over" % (
        len(blocks) - len(free), len(R.files), len(free)))
    return R


def _file(kind, name, L, size, ok, note):
    return {"kind": kind, "name": name, "layout": L, "size": size, "ok": ok, "note": note}


def file_bytes(f):
    data = b"".join((b.data if b else b"\0" * 512) for b in f["layout"].at)
    if f["kind"] == "JPEG":
        k = data.rfind(b"\xff\xd9")
        if k >= 0:
            data = data[:k + 2]
    elif f["size"]:
        data = data[:f["size"]]
    return data


def write(R, out):
    """Rebuilt files, the full block map (CSV and JSON), and the run log."""
    os.makedirs(out, exist_ok=True)
    placed = R.placed()
    rows = []
    for f in R.files:
        data = file_bytes(f)
        with open(os.path.join(out, f["name"]), "wb") as fh:
            fh.write(data)
        f["sha256"] = hashlib.sha256(data).hexdigest()
        f["md5"] = hashlib.md5(data).hexdigest()
        f["bytes"] = len(data)
    for b in R.blocks:
        g, why = R.guesses[b.name]
        f, p = placed.get(b.name, (None, None))
        rows.append({
            "block": b.name, "md5": hashlib.md5(b.data).hexdigest(),
            "first_guess": g, "first_guess_reason": why,
            "file": f["kind"] if f else "unplaced", "position": p,
            "offset": p * 512 if p is not None else None,
            "how": f["layout"].how[p] if f else "",
        })
    with open(os.path.join(out, "block_map.csv"), "w", newline="", encoding="utf-8") as fh:
        import csv
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    summary = {
        "blocks": len(R.blocks),
        "files": [{k: f[k] for k in ("kind", "name", "ok", "note", "bytes", "md5", "sha256")}
                  | {"blocks": sum(1 for x in f["layout"].at if x), "positions": f["layout"].n}
                  for f in R.files],
        "unplaced": [b.name for b in R.unplaced],
        "input": R.input,
        "log": R.log,
    }
    with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump({"summary": summary, "blocks": rows}, fh, indent=1)
    return summary
