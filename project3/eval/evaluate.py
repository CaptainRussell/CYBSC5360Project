"""Score the toolkit on block sets whose answer is known.

For each set: run the toolkit, then compare with the answer key.
  sorted right     the block was put in the file it came from
  exact position   ... and at the position it came from
  right neighbour  the block after it in the rebuilt file is the true next block
                   (a fairer measure for long runs that are right but shifted)
  identical file   the rebuilt file is byte-for-byte the original
The first-pass guess is scored too, so the gain from rebuilding is visible.

    py -3 eval/evaluate.py eval/sets/set01 eval/sets/set02 ... --out eval/results.json
"""

import argparse
import csv
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from blockrecover import recover  # noqa: E402

EXT = {"PDF": "pdf", "Word": "doc", "JPEG": "jpg"}


def score(d, progress=None):
    t = time.time()
    R = recover.run(os.path.join(d, "blocks"), progress=progress)
    took = time.time() - t
    key = {}
    with open(os.path.join(d, "answer_key.csv"), newline="") as fh:
        for r in csv.DictReader(fh):
            key[r["block"]] = (r["file"], int(r["position"]))
    truth = {}
    for b, (f, p) in key.items():
        truth.setdefault(f, {})[p] = b
    placed = R.placed()
    out = {"set": os.path.basename(d), "seconds": round(took, 1), "blocks": len(key), "files": {}}
    guess_ok = sum(1 for b, (f, p) in key.items() if R.guesses[b][0] == f)
    out["first_guess_right"] = guess_ok
    out["first_guess_unsure"] = sum(1 for b in key if R.guesses[b][0] == "unsure")
    out["sorted_right"] = sum(1 for b, (f, p) in key.items() if b in placed and placed[b][0]["kind"] == f)
    out["exact_position"] = sum(1 for b, (f, p) in key.items()
                                if b in placed and placed[b][0]["kind"] == f and placed[b][1] == p)
    for kind, pos in truth.items():
        f = next((x for x in R.files if x["kind"] == kind), None)
        n = len(pos)
        res = {"blocks": n}
        if f is None:
            res.update(rebuilt=False)
        else:
            at = f["layout"].at
            exact = sum(1 for p, b in pos.items() if p < len(at) and at[p] is not None and
                        (at[p].name == b or at[p].data == _data(d, b)))
            nxt = {pos[p]: pos.get(p + 1) for p in pos}
            pairs = sum(1 for p in range(len(at) - 1) if at[p] is not None and at[p + 1] is not None and
                        nxt.get(at[p].name) == at[p + 1].name)
            with open(os.path.join(d, "original." + EXT[kind]), "rb") as fh:
                orig = fh.read()
            res.update(rebuilt=True, checked=f["ok"], exact_or_identical_copy=exact,
                       right_neighbour=pairs, neighbour_pairs=n - 1,
                       identical=recover.file_bytes(f) == orig)
        out["files"][kind] = res
    return out


_cache = {}


def _data(d, name):
    k = (d, name)
    if k not in _cache:
        with open(os.path.join(d, "blocks", name), "rb") as fh:
            _cache[k] = fh.read()
    return _cache[k]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sets", nargs="+")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    results = []
    for d in a.sets:
        r = score(d)
        results.append(r)
        print(json.dumps(r))
    if a.out:
        with open(a.out, "w") as fh:
            json.dump(results, fh, indent=1)


if __name__ == "__main__":
    main()
