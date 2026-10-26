"""Rebuild a report page from a results folder, without the image or the case database.

    python -m ads rerender RESULTS_FOLDER

A first-look results folder holds triage.json; a date-check folder holds
scores.csv, outcomes.csv, indicators.json, clusters.csv and run.json. Everything
the report page shows is in those files, so a page can be rebuilt after the
report's design changes, or on a computer that does not have the evidence.
Nothing is re-checked: the page shows exactly the results that were saved.
"""

import csv
import json
import os


def _split(s, sep):
    return [x for x in (s or "").split(sep) if x]


def rerender_triage(folder):
    from .briefing import render
    with open(os.path.join(folder, "triage.json"), encoding="utf-8") as fh:
        data = json.load(fh)
    out = os.path.join(folder, "briefing.html")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(render(data))
    return out


def rerender_dates(folder):
    from . import ntfs_briefing
    with open(os.path.join(folder, "run.json"), encoding="utf-8") as fh:
        run = json.load(fh)
    with open(os.path.join(folder, "scores.csv"), newline="", encoding="utf-8") as fh:
        scored = [{"entry": int(r["entry"]), "seq": int(r["seq"]), "path": r["path"], "score": float(r["score"]),
                   "flagged": r["flagged"] == "1", "evaluable": int(r["evaluable"]), "confidence": float(r["confidence"]),
                   "fired": _split(r["fired"], " "), "cluster": int(r["cluster"]) if r.get("cluster") else None,
                   "violated_from_degraded_sources": _split(r.get("violated_from_degraded_sources"), " ")}
                  for r in csv.DictReader(fh)]
    with open(os.path.join(folder, "outcomes.csv"), newline="", encoding="utf-8") as fh:
        outcome_rows = [((int(r["entry"]), int(r["seq"])), r["rule"], r["outcome"], json.loads(r["details"] or "{}"))
                        for r in csv.DictReader(fh)]
    with open(os.path.join(folder, "indicators.json"), encoding="utf-8") as fh:
        indicators = json.load(fh)
    clusters = []
    path = os.path.join(folder, "clusters.csv")
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as fh:
            clusters = [{"start": r["start"], "end": r["end"], "files": int(r["files"]), "paths": _split(r["paths"], "; "),
                         "prefetch_runs": _split(r["prefetch_runs"], "; "), "indicators": _split(r["indicators"], " ")}
                        for r in csv.DictReader(fh)]
    meta = {"theta": run["theta"], "weight_mode": run["weight_mode"], "inputs": run.get("inputs", []),
            "generated": run.get("generated", ""), "calibration": run.get("calibration"), "config": run.get("config")}
    data = ntfs_briefing.build_data(None, outcome_rows, scored, indicators, clusters,
                                    (run.get("system_score", 0.0), run.get("indicators_evaluable", 0)), meta)
    out = os.path.join(folder, "briefing.html")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(ntfs_briefing.render(data))
    return out


def rerender(folder):
    if os.path.exists(os.path.join(folder, "triage.json")):
        return rerender_triage(folder)
    if os.path.exists(os.path.join(folder, "scores.csv")):
        return rerender_dates(folder)
    raise FileNotFoundError("no triage.json or scores.csv in %s" % folder)
