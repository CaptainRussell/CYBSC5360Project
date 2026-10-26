"""Check that the browser version gave the same answers as the Python version.

    python -m ads compare BROWSER_RESULTS PYTHON_RESULTS

Each argument is a results folder (or a triage.json). For a first-look run the two
triage.json files are compared field by field; for a date-check run, scores.csv,
outcomes.csv and indicators.json. Only what cannot match is left out: when the run
happened, the path the image was opened from, and the tool's own name line.
Numbers are compared as numbers (the two languages can write 2.0 and 2 differently)
and must agree to 12 significant digits. The browser version is the port; the
Python version is the reference whose first-look checks are frozen.
"""

import csv
import json
import math
import os

IGNORE = {("generated",), ("tool",), ("image", "path")}


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def diff(a, b, path=(), out=None, limit=50):
    """Differences between two JSON values, as readable strings (at most `limit`)."""
    out = [] if out is None else out
    if len(out) >= limit or path in IGNORE:
        return out
    where = "/".join(str(p) for p in path) or "(top)"
    if _num(a) and _num(b):
        if not math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12):
            out.append("%s: %r != %r" % (where, a, b))
    elif isinstance(a, dict) and isinstance(b, dict):
        for k in a.keys() | b.keys():
            if (path + (k,)) in IGNORE:
                continue
            if k not in a or k not in b:
                out.append("%s: key %r only in %s" % (where, k, "browser" if k in a else "Python"))
            else:
                diff(a[k], b[k], path + (k,), out, limit)
        if list(k for k in a if k in b) != list(k for k in b if k in a) and path in {("noise",), ("types",)}:
            out.append("%s: same entries in a different order" % where)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append("%s: %d items != %d items" % (where, len(a), len(b)))
        for i, (x, y) in enumerate(zip(a, b)):
            diff(x, y, path + (i,), out, limit)
    elif a != b:
        out.append("%s: %r != %r" % (where, a, b))
    return out


def _load_json(p):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def _rows(p):
    with open(p, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _typed(rows):
    """CSV cells -> numbers where they are numbers, JSON where they hold JSON (the outcome details)."""
    out = []
    for r in rows:
        t = {}
        for k, v in r.items():
            try:
                t[k] = float(v) if v not in ("",) and not v.startswith("{") else (json.loads(v) if v.startswith("{") else v)
            except ValueError:
                t[k] = v
        out.append(t)
    return out


def compare(browser, python):
    """-> (kind, list of differences). Each argument is a results folder or a triage.json."""
    def find(p, name):
        return p if os.path.isfile(p) else os.path.join(p, name)
    tb, tp = find(browser, "triage.json"), find(python, "triage.json")
    if os.path.exists(tb) and os.path.exists(tp):
        return "first look", diff(_load_json(tb), _load_json(tp))
    sb, sp = os.path.join(browser, "scores.csv"), os.path.join(python, "scores.csv")
    if os.path.exists(sb) and os.path.exists(sp):
        out = diff(_typed(_rows(sb)), _typed(_rows(sp)), ("scores.csv",))
        out += diff(_typed(_rows(os.path.join(browser, "outcomes.csv"))), _typed(_rows(os.path.join(python, "outcomes.csv"))), ("outcomes.csv",))
        out += diff(_load_json(os.path.join(browser, "indicators.json")), _load_json(os.path.join(python, "indicators.json")), ("indicators.json",))
        return "date checks", out
    raise FileNotFoundError("need two first-look results (triage.json) or two date-check results (scores.csv)")
