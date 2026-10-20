"""Scoring model (Section III-F): weighted disagreement score and temporal clustering.

    D(f) = sum_r w_r * v_r(f) / sum_r w_r      over rules evaluable for f
    w_r  = log(1 / p_r) * t_r

p_r is rule r's firing rate on the benign baseline image and t_r the
tamper-resistance factor of the rule's reference source, derived from the
factor scores of Vanini et al. [2].
"""

import math
from collections import defaultdict

from .config import INDICATOR_DEGRADES, RULE_IDS, RULE_SOURCES, TIME_RULES
from .rules import CONSISTENT, NOT_EVALUABLE, VIOLATED
from .timeutil import fmt_ts, seconds


def baseline_rates(outcome_rows):
    """Per-rule counts on a benign baseline -> {rule: {violated, evaluable, p_r}}."""
    counts = {r: {"violated": 0, "evaluable": 0} for r in RULE_IDS}
    for _key, rid, outcome, _d in outcome_rows:
        if outcome == NOT_EVALUABLE:
            continue
        counts[rid]["evaluable"] += 1
        if outcome == VIOLATED:
            counts[rid]["violated"] += 1
    for c in counts.values():
        # Add-half smoothing keeps log(1/p) finite for rules that never fire.
        c["p_r"] = (c["violated"] + 0.5) / (c["evaluable"] + 1)
    return counts


def resistance_factor(scores):
    """Vanini et al. score 1 (hard to tamper) to 3 (easy) per factor; map the mean to 1..3."""
    return 4.0 - sum(scores) / len(scores)


def compute_weights(cfg, calibration=None, mode=None):
    mode = mode or cfg["weight_mode"]
    rates = (calibration or {}).get("rates", {})
    out = {}
    for rid in RULE_IDS:
        p = rates.get(rid, {}).get("p_r")
        spec = math.log(1.0 / p) if p else 1.0
        src = cfg["rule_reference_source"][rid]
        res = resistance_factor(cfg["tamper_scores"][src])
        w = {"equal": 1.0, "specificity": spec, "full": spec * res}[mode]
        out[rid] = {"weight": w, "p_r": p, "specificity": spec, "resistance": res,
                    "reference_source": src}
    return out


def degraded_rules(indicators):
    """Rules whose sources a fired indicator has degraded -> list of indicator ids."""
    out = defaultdict(list)
    for ind in indicators:
        if ind["status"] != "fired":
            continue
        hit = INDICATOR_DEGRADES[ind["id"]]
        for rid in RULE_IDS:
            if RULE_SOURCES[rid] & hit or ("clock" in hit and rid in TIME_RULES):
                out[rid].append(ind["id"])
    return out


def score_files(ctx, outcome_rows, weights, indicators, theta, min_evaluable=1):
    by_key = defaultdict(dict)
    for key, rid, outcome, details in outcome_rows:
        by_key[key][rid] = (outcome, details)
    degraded = degraded_rules(indicators)
    results = []
    for key, rules in by_key.items():
        num = den = 0.0
        evaluable, fired, weak, weak_fired = [], [], [], []
        evidence = []
        for rid in RULE_IDS:
            outcome, details = rules.get(rid, (NOT_EVALUABLE, {}))
            if outcome == NOT_EVALUABLE:
                continue
            w = weights[rid]["weight"]
            evaluable.append(rid)
            den += w
            if outcome == VIOLATED:
                num += w
                fired.append(rid)
                if rid in degraded:
                    weak_fired.append(rid)
                if "_evidence_time" in details:
                    evidence.append(details["_evidence_time"])
            elif outcome == CONSISTENT and rid in degraded:
                weak.append(rid)
        d = num / den if den else 0.0
        f = ctx.mft[key]
        clean = [r for r in evaluable if r not in degraded]
        results.append({
            "entry": key[0], "seq": key[1], "path": f["path"],
            "score": d, "evaluable": len(evaluable), "coverage": len(evaluable) / len(RULE_IDS),
            "fired": fired, "evaluable_rules": evaluable,
            "consistent_from_degraded_sources": weak,
            "violated_from_degraded_sources": weak_fired,
            "confidence": len(clean) / len(evaluable) if evaluable else 0.0,
            "flagged": d > theta and len(evaluable) >= min_evaluable,
            # Anchor for clustering: the time a journal or Prefetch record shows the
            # change happening, else the latest metadata change time in either attribute.
            "anchor": max(evidence) if evidence else max(filter(None, (f["si_e"], f["fn_e"])), default=None),
            "anchor_source": "journal/prefetch record" if evidence else "latest SIA-E/FNA-E",
        })
    results.sort(key=lambda r: (-r["score"], -r["evaluable"], r["entry"]))
    return results


def single_rule_scores(outcome_rows, rid):
    """Baseline detector 'rule r only': 1 if violated, else 0 (not evaluable -> 0)."""
    return {key: 1.0 if o == VIOLATED else 0.0 for key, r, o, _ in outcome_rows if r == rid}


def system_score(indicators, cfg):
    w = cfg["indicator_weights"]
    ev = [i for i in indicators if i["status"] != "not_evaluable"]
    den = sum(w.get(i["id"], 1.0) for i in ev)
    num = sum(w.get(i["id"], 1.0) for i in ev if i["status"] == "fired")
    return (num / den if den else 0.0), len(ev)


def cluster(ctx, scored, indicators, cfg):
    """Group flagged files whose anchor times lie within cluster_window_s of each other."""
    window = seconds(cfg["cluster_window_s"])
    pad = seconds(cfg["cluster_pad_s"])
    flagged = sorted((r for r in scored if r["flagged"] and r["anchor"]), key=lambda r: r["anchor"])
    groups, cur = [], []
    for r in flagged:
        if cur and r["anchor"] - cur[-1]["anchor"] > window:
            groups.append(cur)
            cur = []
        cur.append(r)
    if cur:
        groups.append(cur)
    clusters = []
    for i, g in enumerate(groups, 1):
        start, end = g[0]["anchor"], g[-1]["anchor"]
        runs = ctx.pf_runs_between(start - pad, end + pad)
        inds = sorted({ind["id"] for ind in indicators
                       if any(start - pad <= t <= end + pad for t in ind["times"])})
        for r in g:
            r["cluster"] = i
        clusters.append({
            "cluster": i, "start": fmt_ts(start), "end": fmt_ts(end), "files": len(g),
            "paths": [r["path"] for r in g],
            "prefetch_runs": sorted({"%s @ %s" % (exe, fmt_ts(t)) for t, exe, _ in runs}),
            "indicators": inds,
        })
    return clusters
