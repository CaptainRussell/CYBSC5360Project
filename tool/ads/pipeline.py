"""One shared ingest-and-analyze path, used by both the command line and the GUI."""

import fnmatch
import glob
import os

from . import db, loaders
from .indicators import evaluate_indicators
from .report import write_outputs
from .rules import Context, evaluate_all
from .scoring import cluster, compute_weights, score_files, system_score

# How the Zimmerman CSVs are recognised inside a folder. Names are matched in lower case on every
# platform, and each file is given to the FIRST kind whose patterns match, so one file is never
# loaded twice. The journal comes before the MFT because MFTECmd's default names for both start
# with "MFTECmd" (e.g. 20261010_MFTECmd_$J_Output.csv and 20261010_MFTECmd_$MFT_Output.csv).
CSV_KINDS = [
    ("usn", ["*$j*", "*usn*", "*journal*"]),
    ("mft", ["*$mft*", "*mft*"]),
    ("lnk", ["*lnk*", "*lecmd*"]),
    ("prefetch", ["*prefetch*", "*pecmd*", "pf.csv", "*_pf.csv", "pf_*.csv"]),
    ("evtx", ["*evtx*", "*eventlog*", "*system*", "*security*", "*application*"]),
]
# Side outputs that look like parser CSVs but are not inputs: PECmd's run timeline, and the
# chain-of-custody hash list written by run_parsers.ps1.
CSV_SKIP = ["*timeline*", "hashes.csv"]


def classify_csv(name):
    """The kind a parser CSV holds, judged from its file name, or None to skip it."""
    n = os.path.basename(name).lower()
    if not n.endswith(".csv") or any(fnmatch.fnmatchcase(n, p) for p in CSV_SKIP):
        return None
    for kind, pats in CSV_KINDS:
        if any(fnmatch.fnmatchcase(n, p) for p in pats):
            return kind
    return None


def find_csvs(folder):
    """Return {kind: [paths]} for the Zimmerman CSVs found in a folder."""
    found = {}
    for p in sorted(glob.glob(os.path.join(folder, "*"))):
        kind = classify_csv(p) if os.path.isfile(p) else None
        if kind:
            found.setdefault(kind, []).append(p)
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


def analyze_db(dbpath, outdir, cfg, calibration=None, theta=None, weight_mode=None, calibration_path=None):
    """Evaluate rules and indicators, score, cluster, and write every output including briefing.html.

    calibration is the loaded calibration dict; calibration_path is where it came from, recorded in
    run.json and report.md so each run states how it was weighted.
    """
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
            "calibration": calibration_path or ("(in memory)" if calibration else None),
            "config": cfg, "inputs": inputs}
    write_outputs(outdir, ctx, rows, scored, indicators, clusters, weights, sys_score, meta)
    ctx.con.close()
    return {"scored": len(scored), "flagged": sum(r["flagged"] for r in scored),
            "clusters": len(clusters), "system_score": sys_score[0], "out": outdir}
