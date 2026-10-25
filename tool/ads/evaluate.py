"""Evaluation against a ground-truth log (Section IV-F metrics, experiments E1 and E4).

Ground-truth CSV columns: entry_number, sequence_number (or path), category,
host_time_utc, snapshot. Listed files are tampered; every other scored file
is benign.
"""

import csv
import json
from collections import defaultdict

from .config import RULE_IDS
from .paths import norm_path


def load_truth(path):
    keys, paths_ = set(), set()
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            e, s = (row.get("entry_number") or "").strip(), (row.get("sequence_number") or "").strip()
            if e:
                keys.add((int(e), int(s) if s else None))
            elif row.get("path"):
                paths_.add(norm_path(row["path"]))
    return keys, paths_


def load_results(results_dir):
    files, rules = {}, defaultdict(dict)
    with open(results_dir + "/scores.csv", newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            files[(int(r["entry"]), int(r["seq"]))] = {"path": r["path"], "score": float(r["score"])}
    with open(results_dir + "/outcomes.csv", newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            rules[r["rule"]][(int(r["entry"]), int(r["seq"]))] = 1.0 if r["outcome"] == "violated" else 0.0
    return files, rules


def label(files, truth):
    keys, paths_ = truth
    return {k: (k in keys or (k[0], None) in keys or f["path"] in paths_) for k, f in files.items()}


def roc(scores, labels):
    """ROC points (fpr, tpr, threshold) for 'flag if score > threshold'."""
    pos = sum(1 for v in labels.values() if v)
    neg = len(labels) - pos
    thresholds = sorted({s for s in scores.values()} | {-1.0}, reverse=True)
    pts = [(0.0, 0.0, float("inf"))]
    for t in thresholds:
        tp = sum(1 for k, s in scores.items() if s > t and labels[k])
        fp = sum(1 for k, s in scores.items() if s > t and not labels[k])
        pts.append((fp / neg if neg else 0.0, tp / pos if pos else 0.0, t))
    return pts


def auc(scores, labels):
    """Probability a tampered file outscores a benign one (ties count half)."""
    p = [s for k, s in scores.items() if labels[k]]
    n = [s for k, s in scores.items() if not labels[k]]
    if not p or not n:
        return None
    wins = sum((1.0 if a > b else 0.5 if a == b else 0.0) for a in p for b in n)
    return wins / (len(p) * len(n))


def tpr_at_fpr(points, max_fpr):
    ok = [tpr for fpr, tpr, _ in points if fpr <= max_fpr]
    return max(ok) if ok else 0.0


def choose_theta(scores, labels, target_fpr):
    """Smallest theta whose false positive rate (score > theta) is at most target_fpr."""
    best = None
    for fpr, tpr, t in roc(scores, labels):
        if fpr <= target_fpr and t != float("inf") and (best is None or t < best[0]):
            best = (t, fpr, tpr)
    return best


def confusion(scores, labels, theta):
    tp = sum(1 for k, s in scores.items() if s > theta and labels[k])
    fp = sum(1 for k, s in scores.items() if s > theta and not labels[k])
    fn = sum(1 for k, s in scores.items() if s <= theta and labels[k])
    tn = len(scores) - tp - fp - fn
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "tpr": tp / (tp + fn) if tp + fn else None,
            "fpr": fp / (fp + tn) if fp + tn else None,
            "precision": tp / (tp + fp) if tp + fp else None}


def evaluate(results_dir, truth_path, fprs=(0.01, 0.001), theta=None):
    files, rules = load_results(results_dir)
    labels = label(files, load_truth(truth_path))
    detectors = {"ADS": {k: f["score"] for k, f in files.items()}}
    for rid in RULE_IDS:
        detectors[rid + " only"] = {k: rules[rid].get(k, 0.0) for k in files}
    rows = []
    for name, scores in detectors.items():
        pts = roc(scores, labels)
        row = {"detector": name, "auc": auc(scores, labels),
               "points": [(round(fpr, 5), round(tpr, 5)) for fpr, tpr, _ in pts]}
        for f in fprs:
            row["tpr_at_fpr_%g" % f] = tpr_at_fpr(pts, f)
        t = theta if name == "ADS" and theta is not None else 0.5
        row.update(confusion(scores, labels, t))
        rows.append(row)
    return {"tampered": sum(labels.values()), "benign": len(labels) - sum(labels.values()),
            "detectors": rows}


def write_evaluation(result, out_path):
    cols = ["detector", "auc"] + sorted(k for k in result["detectors"][0]
                                        if k.startswith("tpr_at")) + \
           ["tp", "fp", "fn", "tn", "tpr", "fpr", "precision"]
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for r in result["detectors"]:
            w.writerow(["" if r[c] is None else (round(r[c], 4) if isinstance(r[c], float) else r[c])
                        for c in cols])
    return json.dumps({k: v for k, v in result.items() if k != "detectors"})
