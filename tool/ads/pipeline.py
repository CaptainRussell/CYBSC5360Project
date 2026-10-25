"""One shared ingest-and-analyze path, used by both the command line and the GUI."""

import glob
import json
import os

from . import db, loaders
from .evaluate import choose_theta, label, load_results, load_truth
from .indicators import evaluate_indicators
from .report import write_outputs
from .rules import Context, evaluate_all
from .scoring import cluster, compute_weights, score_files, system_score

# How the Zimmerman CSVs are recognised inside a folder, by filename substring.
CSV_PATTERNS = {
    "mft": ["*mft*.csv"],
    "usn": ["*usn*.csv", "*j.csv", "*journal*.csv"],
    "lnk": ["*lnk*.csv", "*lecmd*.csv"],
    "prefetch": ["*pf*.csv", "*prefetch*.csv", "*pecmd*.csv"],
    "evtx": ["*evtx*.csv", "*event*.csv", "*_system*.csv", "*_security*.csv", "*_application*.csv"],
}


def find_csvs(folder):
    """Return {kind: [paths]} for the Zimmerman CSVs found in a folder."""
    found = {}
    for kind, pats in CSV_PATTERNS.items():
        hits = []
        for pat in pats:
            for p in glob.glob(os.path.join(folder, pat)) + glob.glob(os.path.join(folder, pat.upper())):
                if os.path.isfile(p) and p not in hits:
                    hits.append(p)
        if hits:
            found[kind] = sorted(hits)
    return found


def ingest_folder(folder, dbpath, cfg, progress=None):
    """Load every recognised CSV in a folder into a fresh case database."""
    if os.path.exists(dbpath):
        os.remove(dbpath)
    csvs = find_csvs(folder)
    if "mft" not in csvs:
        raise loaders.InputError(
            "No MFT CSV found in %s. Run the parsers first (see scripts/run_parsers.ps1); "
            "the folder should hold mft.csv and, ideally, usn.csv, lnk.csv, prefetch.csv and evtx*.csv." % folder)
    con = db.connect(dbpath)
    loaders_by_kind = {"mft": loaders.load_mft, "usn": loaders.load_usn,
                       "prefetch": loaders.load_prefetch, "evtx": loaders.load_evtx}
    summary = []
    for kind, files in csvs.items():
        for f in files:
            if kind == "lnk":
                n = loaders.load_lnk(con, f, cfg["mount_prefix"])
            else:
                n = loaders_by_kind[kind](con, f)
            summary.append({"kind": kind, "file": os.path.basename(f), "rows": n})
            if progress:
                progress(kind, os.path.basename(f), n)
    con.commit()
    con.close()
    return summary


def analyze_db(dbpath, outdir, cfg, calibration=None, theta=None, weight_mode=None):
    """Evaluate rules and indicators, score, cluster, and write every output including briefing.html."""
    con = db.connect(dbpath)
    ctx = Context(con, cfg)
    th = theta if theta is not None else (calibration or {}).get("theta", cfg["theta"])
    mode = weight_mode or cfg["weight_mode"]
    weights = compute_weights(cfg, calibration, mode)
    rows = list(evaluate_all(ctx))
    indicators = evaluate_indicators(ctx)
    scored = score_files(ctx, rows, weights, indicators, th, cfg["min_evaluable"])
    clusters = cluster(ctx, scored, indicators, cfg)
    sys_score = system_score(indicators, cfg)
    inputs = [dict(r) for r in ctx.con.execute("SELECT * FROM inputs")]
    meta = {"db": os.path.abspath(dbpath), "theta": th, "weight_mode": mode,
            "calibration": None, "config": cfg, "inputs": inputs}
    write_outputs(outdir, ctx, rows, scored, indicators, clusters, weights, sys_score, meta)
    ctx.con.close()
    return {"scored": len(scored), "flagged": sum(r["flagged"] for r in scored),
            "clusters": len(clusters), "system_score": sys_score[0], "out": outdir}
