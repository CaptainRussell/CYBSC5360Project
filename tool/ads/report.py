"""Write the ranked CSV, per-rule outcomes, indicators, clusters and a readable report."""

import csv
import json
import os

from .config import RULE_IDS
from .rules import NOT_EVALUABLE, RULES, VIOLATED
from .timeutil import now_utc_iso


def _public(details):
    return {k: v for k, v in details.items() if not k.startswith("_")}


def write_outputs(out_dir, ctx, outcome_rows, scored, indicators, clusters, weights, sys_score, meta):
    os.makedirs(out_dir, exist_ok=True)
    by_key = {(r["entry"], r["seq"]): r for r in scored}

    with open(os.path.join(out_dir, "scores.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["rank", "entry", "seq", "path", "score", "flagged", "evaluable", "coverage",
                    "confidence", "fired", "consistent_from_degraded_sources",
                    "violated_from_degraded_sources", "cluster"])
        for i, r in enumerate(scored, 1):
            w.writerow([i, r["entry"], r["seq"], r["path"], "%.4f" % r["score"], int(r["flagged"]),
                        r["evaluable"], "%.3f" % r["coverage"], "%.3f" % r["confidence"],
                        " ".join(r["fired"]), " ".join(r["consistent_from_degraded_sources"]),
                        " ".join(r["violated_from_degraded_sources"]), r.get("cluster", "")])

    with open(os.path.join(out_dir, "outcomes.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["entry", "seq", "path", "rule", "outcome", "details"])
        for key, rid, outcome, details in outcome_rows:
            w.writerow([key[0], key[1], by_key[key]["path"], rid, outcome,
                        json.dumps(_public(details), sort_keys=True)])

    with open(os.path.join(out_dir, "indicators.json"), "w", encoding="utf-8") as fh:
        json.dump([{k: v for k, v in i.items() if k != "times"} for i in indicators], fh, indent=2)

    with open(os.path.join(out_dir, "clusters.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["cluster", "start", "end", "files", "paths", "prefetch_runs", "indicators"])
        for c in clusters:
            w.writerow([c["cluster"], c["start"], c["end"], c["files"], "; ".join(c["paths"]),
                        "; ".join(c["prefetch_runs"]), " ".join(c["indicators"])])

    with open(os.path.join(out_dir, "run.json"), "w", encoding="utf-8") as fh:
        json.dump({"generated": now_utc_iso(), **meta, "weights": weights,
                   "system_score": sys_score[0], "indicators_evaluable": sys_score[1]}, fh, indent=2)

    _write_markdown(os.path.join(out_dir, "report.md"), ctx, outcome_rows, scored, indicators,
                    clusters, weights, sys_score, meta)

    # Plain-language HTML briefing for a non-specialist reader.
    from . import ntfs_briefing
    bmeta = dict(meta, generated=now_utc_iso())
    data = ntfs_briefing.build_data(ctx, outcome_rows, scored, indicators, clusters, sys_score, bmeta)
    with open(os.path.join(out_dir, "briefing.html"), "w", encoding="utf-8") as fh:
        fh.write(ntfs_briefing.render(data))


def _write_markdown(path, ctx, outcome_rows, scored, indicators, clusters, weights, sys_score, meta):
    outcomes = {}
    for key, rid, outcome, details in outcome_rows:
        outcomes.setdefault(key, {})[rid] = (outcome, details)
    flagged = [r for r in scored if r["flagged"]]
    L = []
    L.append("# ADS report\n")
    L.append("Generated %s. Threshold θ = %s, weight mode `%s`%s.\n" % (
        now_utc_iso(), meta["theta"], meta["weight_mode"],
        "" if meta.get("calibration") else " (no baseline calibration: specificity terms are 1)"))
    L.append("## Inputs\n")
    L.append("| Kind | File | Rows | SHA-256 |\n|---|---|---|---|")
    for i in meta["inputs"]:
        L.append("| %s | %s | %s | `%s` |" % (i["kind"], os.path.basename(i["path"]), i["rows"], i["sha256"]))
    L.append("\nFiles scored: %d. Flagged: %d. LNK files not joined to a target: %d.\n" % (
        len(scored), len(flagged), ctx.lnk_unresolved))

    L.append("## System-level indicators\n")
    L.append("System score: **%.2f** over %d evaluable indicators.\n" % sys_score)
    L.append("| ID | Indicator | Status | Details |\n|---|---|---|---|")
    for i in indicators:
        L.append("| %s | %s | %s | `%s` |" % (i["id"], i["name"], i["status"],
                                             json.dumps(i["details"], sort_keys=True)[:400]))

    L.append("\n## Rule weights\n")
    L.append("| Rule | p_r | log(1/p_r) | t_r (source) | w_r |\n|---|---|---|---|---|")
    for rid in RULE_IDS:
        w = weights[rid]
        L.append("| %s | %s | %.3f | %.2f (%s) | %.3f |" % (
            rid, "-" if w["p_r"] is None else "%.4f" % w["p_r"], w["specificity"],
            w["resistance"], w["reference_source"], w["weight"]))

    L.append("\n## Candidate events (temporal clusters)\n")
    if not clusters:
        L.append("None.\n")
    for c in clusters:
        L.append("**Cluster %d**: %s to %s, %d file(s). Prefetch: %s. Indicators: %s." % (
            c["cluster"], c["start"], c["end"], c["files"], ", ".join(c["prefetch_runs"]) or "none",
            ", ".join(c["indicators"]) or "none"))
        for p in c["paths"]:
            L.append("- `%s`" % p)
        L.append("")

    L.append("## Flagged files\n")
    if not flagged:
        L.append("None.\n")
    for r in flagged:
        key = (r["entry"], r["seq"])
        L.append("### `%s` (MFT %d-%d)\n" % (r["path"], r["entry"], r["seq"]))
        L.append("D(f) = **%.3f**, %d of %d rules evaluable, confidence %.2f%s.\n" % (
            r["score"], r["evaluable"], len(RULE_IDS), r["confidence"],
            ", cluster %s" % r["cluster"] if r.get("cluster") else ""))
        if r["consistent_from_degraded_sources"] or r["violated_from_degraded_sources"]:
            L.append("Outcomes resting on sources a system indicator reports as degraded: "
                     "consistent %s; violated %s.\n" % (
                         ", ".join(r["consistent_from_degraded_sources"]) or "none",
                         ", ".join(r["violated_from_degraded_sources"]) or "none"))
        L.append("| Rule | Outcome | Weight | Values compared |\n|---|---|---|---|")
        for rid in RULE_IDS:
            outcome, details = outcomes[key][rid]
            mark = "**violated**" if outcome == VIOLATED else outcome
            wt = "-" if outcome == NOT_EVALUABLE else "%.3f" % weights[rid]["weight"]
            L.append("| %s | %s | %s | `%s` |" % (rid, mark, wt, json.dumps(_public(details), sort_keys=True)))
        L.append("")

    L.append("## Rule definitions\n")
    for rid in RULE_IDS:
        L.append("- **%s**: %s" % (rid, RULES[rid].__doc__.strip().splitlines()[0]))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
