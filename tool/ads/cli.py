"""Command-line interface.

  python -m ads ingest    --db case.sqlite --mft mft.csv --usn usn.csv --lnk lnk.csv \
                          --prefetch pf.csv --evtx evtx.csv
  python -m ads calibrate --db baseline.sqlite --out calibration.json
  python -m ads analyze   --db case.sqlite --out results/ [--calibration calibration.json]
  python -m ads evaluate  --results results/ --truth ground_truth.csv \
                          [--set-theta calibration.json --target-fpr 0.01]
  python -m ads IMAGE.img                             # raw FAT image -> first-look report (briefing.html)
"""

import argparse
import json
import os
import sys

from . import db, loaders, pipeline
from .config import load_config
from .evaluate import choose_theta, evaluate, label, load_results, load_truth, write_evaluation
from .rules import Context, evaluate_all
from .scoring import baseline_rates


def cmd_ingest(a):
    cfg = load_config(a.config)
    if os.path.exists(a.db) and not a.append:
        sys.exit("%s exists; pass --append to add to it or choose a new path" % a.db)
    con = db.connect(a.db)
    jobs = [("mft", a.mft, loaders.load_mft), ("usn", a.usn, loaders.load_usn),
            ("prefetch", a.prefetch, loaders.load_prefetch), ("evtx", a.evtx, loaders.load_evtx)]
    for kind, files, fn in jobs:
        for f in files or []:
            print("%-8s %6d rows  %s" % (kind, fn(con, f), f))
    for f in a.lnk or []:
        print("%-8s %6d rows  %s" % ("lnk", loaders.load_lnk(con, f, cfg["mount_prefix"]), f))
    for f in a.image or []:
        from .ntfs import load_mft_from_image
        print("%-8s %6d rows  %s (MFT read from the image)" % ("mft", load_mft_from_image(con, f), f))
    con.commit()
    con.close()


def _context(a):
    cfg = load_config(a.config)
    con = db.connect(a.db)
    return cfg, Context(con, cfg)


def cmd_calibrate(a):
    cfg, ctx = _context(a)
    rows = list(evaluate_all(ctx))
    rates = baseline_rates(rows)
    out = {"baseline_db": os.path.abspath(a.db), "files": len(ctx.candidates), "rates": rates}
    if os.path.exists(a.out):
        with open(a.out, encoding="utf-8") as fh:
            prev = json.load(fh)
        if "theta" in prev:
            out["theta"] = prev["theta"]
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    ctx.con.close()
    for rid, c in rates.items():
        print("%-4s fired %6d / %6d evaluable  p_r=%.4f" % (rid, c["violated"], c["evaluable"], c["p_r"]))


def cmd_analyze(a):
    cfg = load_config(a.config)
    calibration = None
    if a.calibration:
        with open(a.calibration, encoding="utf-8") as fh:
            calibration = json.load(fh)
    r = pipeline.analyze_db(a.db, a.out, cfg, calibration, a.theta, a.weight_mode,
                            calibration_path=a.calibration)
    print("scored %d files, flagged %d, %d cluster(s), system score %.2f -> %s"
          % (r["scored"], r["flagged"], r["clusters"], r["system_score"], a.out))
    print("open the plain-language report: %s" % os.path.join(a.out, "briefing.html"))


def cmd_evaluate(a):
    if a.set_theta:
        files, _ = load_results(a.results)
        labels = label(files, load_truth(a.truth))
        best = choose_theta({k: f["score"] for k, f in files.items()}, labels, a.target_fpr)
        if best is None:
            sys.exit("no threshold meets the target false positive rate")
        cal = {}
        if os.path.exists(a.set_theta):
            with open(a.set_theta, encoding="utf-8") as fh:
                cal = json.load(fh)
        cal["theta"] = best[0]
        cal["theta_source"] = {"results": os.path.abspath(a.results), "target_fpr": a.target_fpr,
                               "fpr": best[1], "tpr": best[2]}
        with open(a.set_theta, "w", encoding="utf-8") as fh:
            json.dump(cal, fh, indent=2)
        print("theta=%.4f (calibration FPR %.4f, TPR %.4f) written to %s" % (best[0], best[1], best[2], a.set_theta))
        return
    res = evaluate(a.results, a.truth, theta=a.theta)
    out = a.out or os.path.join(a.results, "evaluation.csv")
    print(write_evaluation(res, out))
    print("written", out)
    from . import charts
    html_path = charts.render(res, os.path.dirname(out) or ".")
    print("open the plain-language summary:", html_path)


def cmd_triage(a):
    import time
    from .briefing import write_triage
    from .triage import UnsupportedImage
    from .triage import Triage

    tty = sys.stdout.isatty()
    spin = "|/-\\"
    state = {"stage": None, "t": time.time()}

    def say(msg):
        print(msg, flush=True)

    def progress(stage, n):
        label = {"read": "Step 2 of 4  Reading files", "check": "Step 3 of 4  Asking eight questions of each file"}[stage]
        if tty:
            print("\r  %s %s %s files " % (label, spin[n // 500 % 4], format(n, ",")), end="", flush=True)
        elif state["stage"] != stage:
            say("  " + label + " ...")
        state["stage"] = stage

    image = os.path.abspath(a.image)
    if not os.path.isfile(image):
        sys.exit("Could not find the image file: %s" % image)
    out = os.path.abspath(a.out or os.path.splitext(os.path.basename(image))[0] + " report")
    say("")
    say("ADS first-look report")
    say("  Image:   %s" % image)
    say("  Output:  %s" % out)
    say("  The image is only read, never changed.")
    say("")
    say("  Step 1 of 4  Opening the drive")
    try:
        t = Triage(image, progress=progress)
    except UnsupportedImage as e:
        sys.exit("\n%s\nADS reads raw (.img, .dd, .raw) images of FAT and NTFS drives. Convert an E01 to raw first." % e)
    vol = t.vol.summary()
    say("               %s drive named \u201c%s\u201d" % (vol["fs_type"], (vol["label"] or "").strip()))
    t.collect().run()
    if tty:
        print("\r" + " " * 78 + "\r", end="")
        say("  Step 2 of 4  Reading files            done")
        say("  Step 3 of 4  Asking eight questions   done")
    say("  Step 4 of 4  Writing the report")
    data, html = write_triage(t, out, a.top)
    c = data["counts"]
    first = [l for l in data["leads"] if l["score"] >= data["tiers"]["strong"]]
    say("")
    say("Done in %.0f seconds. Checked %s files; %s had at least one clue." % (
        time.time() - state["t"], format(c["examined"], ","), format(c["with_findings"], ",")))
    if first:
        say("Look first:")
        for n, l in enumerate(first[:5], 1):
            say("  %d. %-28s score %d  (%s)" % (n, l["path"].split(" \u203a ")[-1].split("/")[-1][:28], round(l["score"] * 100),
                                                ", ".join(data["rules"][r]["name"].lower() for r in l["fired"])))
    say("")
    say("Report:  %s" % html)
    say("Also:    leads.csv (opens in Excel) and triage.json, in the same folder.")
    if not a.no_open:
        import webbrowser
        try:
            webbrowser.open("file://" + html)
        except Exception:
            pass


def main(argv=None):
    p = argparse.ArgumentParser(prog="ads", description="Artifact Disagreement Scorer")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("ingest", help="load Zimmerman CSV output into a case database")
    s.add_argument("--db", required=True)
    for k in ("mft", "usn", "lnk", "prefetch", "evtx"):
        s.add_argument("--" + k, nargs="+")
    s.add_argument("--config")
    s.add_argument("--image", nargs="+", help="raw NTFS image(s): read the MFT straight from the image "
                                               "(no MFTECmd needed; gives the MFT-only rules R6, R7, R11)")
    s.add_argument("--append", action="store_true")
    s.set_defaults(fn=cmd_ingest)

    s = sub.add_parser("calibrate", help="measure benign firing rates p_r on a baseline image")
    s.add_argument("--db", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--config")
    s.set_defaults(fn=cmd_calibrate)

    s = sub.add_parser("analyze", help="evaluate rules and indicators, score and report")
    s.add_argument("--db", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--config")
    s.add_argument("--calibration")
    s.add_argument("--theta", type=float)
    s.add_argument("--weight-mode", choices=["equal", "specificity", "full"])
    s.set_defaults(fn=cmd_analyze)

    s = sub.add_parser("evaluate", help="compare ADS and single rules against ground truth")
    s.add_argument("--results", required=True)
    s.add_argument("--truth", required=True)
    s.add_argument("--out")
    s.add_argument("--theta", type=float)
    s.add_argument("--set-theta", metavar="CALIBRATION_JSON",
                   help="choose theta on these (calibration-set) results and store it")
    s.add_argument("--target-fpr", type=float, default=0.01)
    s.set_defaults(fn=cmd_evaluate)

    s = sub.add_parser("gui", help="open a point-and-click control panel in the browser")
    s.add_argument("port", nargs="?", help="port to listen on (default 8765)")
    s.set_defaults(fn=lambda a: __import__("ads.gui", fromlist=["main"]).main([a.port] if a.port else None))

    s = sub.add_parser("triage", help="first-stop triage of a raw FAT image, with an interactive briefing")
    s.add_argument("image", help="the drive image file (.img, .dd, .raw)")
    s.add_argument("--out", help="folder for the report (default: '<image name> report' in the current folder)")
    s.add_argument("--top", type=int, default=40, help="files to include in full detail")
    s.add_argument("--no-open", action="store_true", help="do not open the report in a browser when done")
    s.set_defaults(fn=cmd_triage)

    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] not in sub.choices and not argv[0].startswith("-") and os.path.isfile(argv[0]):
        argv.insert(0, "triage")   # "python -m ads drive.img" is the same as "python -m ads triage drive.img"
    a = p.parse_args(argv)
    try:
        a.fn(a)
    except loaders.InputError as e:
        sys.exit(str(e))
