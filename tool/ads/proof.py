"""Proof of function: compare an ADS run with the examiner's own findings.

The answer key is what the examiner found by hand in a commercial tool (EnCase,
FTK), one row per item:

    item,question,path,kind,found_manually_by,note

  path   the end of the file's path inside the image, e.g. bin/gzip. Matching
         ignores case and slash direction and must end on a folder boundary.
         Several alternatives may be separated by "|".
  kind   evidence (part of an answer) or decoy (planted to mislead).

The run is either a first-look report (triage.json) or a Windows date report
(scores.csv). For each item this finds where ADS ranked it, if at all, and
writes proof.csv and a plain-language proof.html. It does not change the run.
"""

import csv
import html
import json
import os

from .explain import rule_name


def _norm(p):
    return p.replace("\\", "/").lower().strip()


def load_key(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = [r for r in csv.DictReader(fh) if (r.get("path") or "").strip()]
    for r in rows:
        r["alts"] = [_norm(a) for a in r["path"].split("|") if a.strip()]
        r["kind"] = (r.get("kind") or "evidence").strip().lower()
    return rows


def load_run(results):
    """Ranked leads [{rank, path, score (0-100), checks:[(id, name)], level}] and run facts."""
    tj = os.path.join(results, "triage.json")
    if os.path.exists(tj):
        with open(tj, encoding="utf-8") as fh:
            d = json.load(fh)
        rules, tiers = d["rules"], d["tiers"]
        leads = []
        for n, l in enumerate(d["all_leads"], 1):
            level = ("Look first" if l["score"] >= tiers["strong"]
                     else "Worth a look" if l["score"] >= tiers["moderate"] else "Minor")
            leads.append({"rank": n, "path": l["path"], "score": round(l["score"] * 100),
                          "checks": [(r, rules[r]["name"]) for r in l["fired"]], "level": level})
        facts = {"kind": "first-look report", "examined": d["counts"]["examined"],
                 "fs": d["image"].get("fs_type", ""), "image": d["image"].get("name", "")}
        return leads, facts
    sc = os.path.join(results, "scores.csv")
    if os.path.exists(sc):
        with open(sc, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        hits = [r for r in rows if float(r["score"]) > 0]
        leads = [{"rank": n, "path": r["path"], "score": round(float(r["score"]) * 100),
                  "checks": [(c, rule_name(c)) for c in r["fired"].split()],
                  "level": "Flagged" if r["flagged"] == "1" else "Below the flag line"}
                 for n, r in enumerate(hits, 1)]
        return leads, {"kind": "Windows date report", "examined": len(rows), "fs": "NTFS", "image": ""}
    raise FileNotFoundError("no triage.json or scores.csv in %s" % results)


def _matches(lead_path, alt):
    p = _norm(lead_path)
    return p == alt or any(p.endswith(sep + alt) for sep in ("/", " › "))


def score(key, leads):
    out = []
    for item in key:
        hits = [l for l in leads if any(_matches(l["path"], a) for a in item["alts"])]
        best = min(hits, key=lambda l: l["rank"]) if hits else None
        out.append({**item, "found": best is not None, "rank": best["rank"] if best else None,
                    "score": best["score"] if best else None, "level": best["level"] if best else "",
                    "checks": best["checks"] if best else [], "matched": best["path"] if best else "",
                    "matches": len(hits)})
    return out


def single_checks(key, leads):
    """Each check on its own against the combined ranking, at the same number of files to review.

    A check alone flags every file it fires on, with no order among them, so an examiner reviews all
    of them. For a fair comparison ADS gets the same budget: its top n files, where n is the number
    of files the single check flags.
    """
    ev = [k for k in key if k["kind"] == "evidence"]
    ranks = {}
    for k in ev:
        hits = [l["rank"] for l in leads if any(_matches(l["path"], a) for a in k["alts"])]
        ranks[k["path"]] = min(hits) if hits else None
    ids = sorted({c for l in leads for c, _ in l["checks"]}, key=lambda c: (c[0], int(c[1:]) if c[1:].isdigit() else 0))
    out = []
    for cid in ids:
        flagged = [l for l in leads if any(c == cid for c, _ in l["checks"])]
        name = next(n for l in flagged for c, n in l["checks"] if c == cid)
        found = sum(1 for k in ev if any(_matches(l["path"], a) for l in flagged for a in k["alts"]))
        n = len(flagged)
        ads = sum(1 for r in ranks.values() if r is not None and r <= n)
        out.append({"check": cid, "name": name, "flags": n, "found": found, "ads_same_budget": ads})
    return out


def summarize(scored, leads, facts):
    ev = [s for s in scored if s["kind"] == "evidence"]
    found = [s for s in ev if s["found"]]
    deepest = max((s["rank"] for s in found), default=0)
    key_paths = {s["matched"] for s in scored if s["found"]}
    others_above = sum(1 for l in leads[:deepest] if l["path"] not in key_paths)
    return {"evidence": len(ev), "found": len(found), "top10": sum(1 for s in found if s["rank"] <= 10),
            "deepest": deepest, "others_above": others_above, "leads": len(leads),
            "examined": facts["examined"],
            "decoys": sum(1 for s in scored if s["kind"] == "decoy"),
            "decoys_flagged": sum(1 for s in scored if s["kind"] == "decoy" and s["found"])}


def write(results, key_path, out=None):
    key = load_key(key_path)
    leads, facts = load_run(results)
    scored = score(key, leads)
    summ = summarize(scored, leads, facts)
    summ["singles"] = single_checks(key, leads)
    out = out or results
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "proof.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["item", "question", "kind", "answer_key_path", "found_by_ads", "rank", "score_out_of_100",
                    "level", "checks", "ads_path", "found_manually_by"])
        for s in scored:
            w.writerow([s.get("item", ""), s.get("question", ""), s["kind"], s["path"], "yes" if s["found"] else "no",
                        s["rank"] or "", "" if s["score"] is None else s["score"], s["level"],
                        "; ".join("%s %s" % c for c in s["checks"]), s["matched"], s.get("found_manually_by", "")])
    page = render(scored, summ, facts, os.path.basename(key_path))
    path = os.path.join(out, "proof.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(page)
    return path, summ


def _e(s):
    return html.escape(str(s if s is not None else ""))


def render(scored, summ, facts, key_name):
    verdict = ("ADS put %d of the %d evidence files the examiner found by hand on its list, %d of them in its top "
               "10. To reach every one it found, an examiner would review the top %d of %s files checked, %d of "
               "which are not in the answer key." % (
                   summ["found"], summ["evidence"], summ["top10"], summ["deepest"], format(summ["examined"], ","),
                   summ["others_above"]))
    if summ["found"] == 0:
        verdict = ("ADS did not put any of the %d evidence files the examiner found on its list. See each row for why."
                   % summ["evidence"])
    rows = ""
    for s in sorted(scored, key=lambda s: (s["kind"] != "evidence", s["rank"] is None, s["rank"] or 0)):
        if s["found"]:
            status = '<span class="yes">#%d</span>' % s["rank"]
            why = "; ".join("%s (%s)" % (n, c) for c, n in s["checks"])
            detail = "%s · score %s/100 · %s" % (_e(s["level"]), s["score"], _e(why))
        else:
            status = '<span class="no">not listed</span>'
            detail = ("None of the checks fired on this file. ADS points to files whose records or contents "
                      "disagree; evidence that looks ordinary on its own (for example a browser history file in "
                      "its normal place) is outside what it looks for.")
        rows += ('<tr class="%s"><td>%s</td><td><b>%s</b><div class="q">%s</div><div class="p">%s</div></td>'
                 '<td>%s<div class="d">%s</div></td><td class="m">%s</td></tr>'
                 % (s["kind"], status, _e(s.get("item") or s["path"]), _e(s.get("question", "")),
                    _e(s["matched"] or s["path"]), "Decoy" if s["kind"] == "decoy" else "Evidence", detail,
                    _e(s.get("found_manually_by", ""))))
    singles = ""
    for c in summ.get("singles", []):
        better = c["ads_same_budget"] > c["found"]
        singles += ('<tr><td><b>%s</b> %s</td><td>%s</td><td>%d of %d</td><td class="%s">%d of %d</td></tr>'
                    % (_e(c["check"]), _e(c["name"]), format(c["flags"], ","), c["found"], summ["evidence"],
                       "yes" if better else "", c["ads_same_budget"], summ["evidence"]))
    return (PAGE.replace("@verdict@", _e(verdict)).replace("@rows@", rows).replace("@singles@", singles)
            .replace("@found@", str(summ["found"])).replace("@evidence@", str(summ["evidence"]))
            .replace("@top10@", str(summ["top10"])).replace("@leads@", format(summ["leads"], ","))
            .replace("@examined@", format(summ["examined"], ",")).replace("@kind@", _e(facts["kind"]))
            .replace("@image@", _e(facts["image"] or "")).replace("@fs@", _e(facts["fs"]))
            .replace("@key@", _e(key_name)).replace("@decoys@", "%d of %d" % (summ["decoys_flagged"], summ["decoys"])))


PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>ADS Proof of Function</title>
<style>
:root{--cardinal:#C8102E;--gold:#F1BE48;--ink:#1A1A1A;--muted:#5E5A5A;--line:#DAD6D6;--paper:#fff;--panel:#F7F4F2;--ok:#2E7D4F;--soft:#FBECEE;
--head:Cambria,Georgia,serif;--body:Calibri,"Segoe UI",Arial,sans-serif}
@media(prefers-color-scheme:dark){:root{--cardinal:#E2304C;--ink:#EDE8E6;--muted:#ADA5A3;--line:#3A3434;--paper:#151212;--panel:#1F1A1A;--ok:#6CC596;--soft:#2A1A1D;color-scheme:dark}}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:17px/1.55 var(--body)}
.wrap{max-width:1000px;margin:0 auto;padding:0 16px}
.band{background:var(--cardinal);color:#fff;border-bottom:8px solid var(--gold)}.band .wrap{padding:26px 16px}
.eyebrow{color:var(--gold);font-weight:700;letter-spacing:.14em;text-transform:uppercase;font-size:13px}
h1{font-family:var(--head);font-size:clamp(24px,4vw,38px);margin:6px 0}
h2{font-family:var(--head);color:var(--cardinal);font-size:22px;margin:26px 0 6px}
.verdict{font-size:19px;background:var(--panel);border-left:6px solid var(--cardinal);border-radius:8px;padding:14px 16px;margin:18px 0}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:12px 0}
.stat{background:var(--panel);border-radius:10px;padding:12px}.stat .n{font:700 30px/1 var(--head)}.stat .l{font-size:14px;color:var(--muted)}
@media(max-width:640px){.stats{grid-template-columns:repeat(2,1fr)}}
table{border-collapse:collapse;width:100%;font-size:15px}
th,td{text-align:left;padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-size:13px;text-transform:uppercase;letter-spacing:.05em}
.yes{font:700 18px var(--head);color:var(--ok)}
td.yes{font-size:16px}.no{font-weight:700;color:var(--cardinal)}
.q{color:var(--muted);font-size:14px}.p{font-family:Consolas,monospace;font-size:12px;color:var(--muted);overflow-wrap:anywhere}
.d{font-size:14px;color:var(--muted)}.m{font-size:14px}
tr.decoy td{background:var(--soft)}
footer{color:var(--muted);font-size:14px;padding:26px 0 50px}
</style></head><body>
<div class="band"><div class="wrap"><div class="eyebrow">Artifact Disagreement Scorer · proof of function</div>
<h1>Did ADS point to what the examiner found by hand?</h1>
<p>@image@ · @fs@ drive · compared with the answer key @key@ · from the @kind@</p></div></div>
<div class="wrap">
<p class="verdict">@verdict@</p>
<div class="stats">
<div class="stat"><div class="n">@found@ / @evidence@</div><div class="l">evidence files on ADS's list</div></div>
<div class="stat"><div class="n">@top10@</div><div class="l">of them in the top 10</div></div>
<div class="stat"><div class="n">@leads@</div><div class="l">files on the list, of @examined@ checked</div></div>
<div class="stat"><div class="n">@decoys@</div><div class="l">decoys also listed</div></div>
</div>
<h2>Item by item</h2>
<p>Each row is something the examiner found by hand. “#3” means it was third on ADS's list. Decoys (shaded) are
files planted to mislead; listing them is not an error, since the examiner had to rule them out too.</p>
<table><tr><th>ADS rank</th><th>What the examiner found</th><th>What ADS saw</th><th>How it was found by hand</th></tr>@rows@</table>
<h2>Each check on its own, against all of them together</h2>
<p>A single check flags every file it fires on, in no order, so an examiner would have to review all of them.
The last column gives ADS the same number of files to review (its top files) and counts the evidence files
among them. Where it is higher, combining the checks found more for the same effort.</p>
<table><tr><th>Check on its own</th><th>Files it flags</th><th>Evidence it catches</th><th>ADS, same number of files</th></tr>@singles@</table>
</div>
<footer><div class="wrap">ADS points to files for an examiner to review; it does not answer the case questions itself.
A file not on the list was not flagged by any check.</div></footer>
</body></html>"""
