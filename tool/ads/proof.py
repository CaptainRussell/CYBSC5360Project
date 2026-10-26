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
    from .theme import THEME_CSS, THEME_JS, icon
    ev = summ["evidence"]
    verdict = ("ADS listed %d of the %d evidence files found by hand, %d in its top 10. Reaching all of them means "
               "reviewing its top %d of %s files." % (summ["found"], ev, summ["top10"], summ["deepest"],
                                                    format(summ["examined"], ",")))
    if summ["found"] == 0:
        verdict = "ADS listed none of the %d evidence files found by hand. Each row says why." % ev
    chev = icon("chev", "ico chev")
    rows = ""
    for s_ in sorted(scored, key=lambda s: (s["kind"] != "evidence", s["rank"] is None, s["rank"] or 0)):
        found = s_["found"]
        rank = ('<span class="rk ok">#%d</span>' % s_["rank"]) if found else '<span class="rk no">—</span>'
        badge = '<span class="badge %s">%s</span>' % (("ok", "listed") if found else ("hot", "missed"))
        if s_["kind"] == "decoy":
            badge = '<span class="badge minor">decoy%s</span>' % (" · listed" if found else "")
        chips = "".join('<span class="chip"><b>%s</b></span>' % _e(c) for c, _n in s_["checks"])
        saw = ("<dt>Score</dt><dd>%s / 100 · %s</dd>" % (s_["score"], _e(s_["level"])) +
               "".join("<dt>%s</dt><dd>%s</dd>" % (_e(c), _e(n)) for c, n in s_["checks"])) if found else \
            ("<dt>ADS</dt><dd>No check fired. ADS points to files whose records or contents disagree; evidence that "
             "looks ordinary on its own is outside what it looks for.</dd>")
        rows += ('<div class="acc-item" data-kind="{kind}" data-found="{f}"><button class="acc-head" aria-expanded="false">{rank}'
                 '<div style="flex:1;min-width:0"><b>{item}</b><div class="note mono" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{path}</div></div>'
                 '<span class="chip">{q}</span><span class="cicons hide-s">{chips}</span>{badge}{chev}</button>'
                 '<div class="acc-body"><div><div class="acc-inner"><dl class="kv"><dt>In the image</dt><dd>{path}</dd>{saw}'
                 '<dt>Found by hand</dt><dd>{how}</dd>{note}</dl></div></div></div></div>'
                 ).format(kind=s_["kind"], f=int(found), rank=rank, item=_e(s_.get("item") or s_["path"]),
                          path=_e(s_["matched"] or s_["path"]), q=_e(s_.get("question", "")), chips=chips, badge=badge, chev=chev,
                          saw=saw, how=_e(s_.get("found_manually_by", "")),
                          note=("<dt>Note</dt><dd>%s</dd>" % _e(s_["note"])) if s_.get("note") else "")
    singles = ""
    for c in summ.get("singles", []):
        better = c["ads_same_budget"] > c["found"]
        worse = c["ads_same_budget"] < c["found"]
        singles += ('<tr><td><b class="mono">{id}</b> {name}</td><td class="num">{flags}</td>'
                    '<td><div class="duo"><div class="bar"><i data-w="{a:.0f}"></i></div><span class="mono">{found}</span></div></td>'
                    '<td><div class="duo"><div class="bar {cls}"><i data-w="{b:.0f}"></i></div><span class="mono">{ads}</span></div></td>'
                    '<td>{tag}</td></tr>').format(
            id=_e(c["check"]), name=_e(c["name"]), flags=format(c["flags"], ","), a=100 * c["found"] / max(1, ev), found=c["found"],
            b=100 * c["ads_same_budget"] / max(1, ev), ads=c["ads_same_budget"], cls="ok" if better else ("hot" if worse else ""),
            tag='<span class="badge ok">ADS better</span>' if better else ('<span class="badge hot">check better</span>' if worse else '<span class="badge minor">tie</span>'))
    pct = 100 * summ["found"] / max(1, ev)
    r = 54
    circ = 2 * 3.14159 * r
    donut = ('<svg viewBox="0 0 140 140" width="150" height="150" aria-label="share of evidence listed"><circle cx="70" cy="70" r="{r}" '
             'style="fill:none;stroke:var(--panel2);stroke-width:14"/><circle cx="70" cy="70" r="{r}" class="dn" style="fill:none;'
             'stroke:var(--accent);stroke-width:14;stroke-linecap:round;transform:rotate(-90deg);transform-origin:50% 50%" '
             'stroke-dasharray="{c:.1f}" stroke-dashoffset="{c:.1f}" data-off="{o:.1f}"/><text x="70" y="68" text-anchor="middle" '
             'style="font:700 26px var(--mono);fill:var(--text)">{f}/{e}</text><text x="70" y="90" text-anchor="middle" '
             'style="font:12px var(--ui);fill:var(--muted)">evidence listed</text></svg>').format(r=r, c=circ, o=circ * (1 - pct / 100), f=summ["found"], e=ev)
    return (PAGE.replace("@css@", THEME_CSS).replace("@js@", THEME_JS)
            .replace("@verdict@", _e(verdict)).replace("@rows@", rows).replace("@singles@", singles).replace("@donut@", donut)
            .replace("@found@", str(summ["found"])).replace("@evidence@", str(ev)).replace("@top10@", str(summ["top10"]))
            .replace("@depth@", str(summ["deepest"])).replace("@others@", str(summ["others_above"]))
            .replace("@leads@", format(summ["leads"], ",")).replace("@examined@", format(summ["examined"], ","))
            .replace("@kind@", _e(facts["kind"])).replace("@image@", _e(facts["image"] or "")).replace("@fs@", _e(facts["fs"]))
            .replace("@key@", _e(key_name)).replace("@decoys@", "%d of %d" % (summ["decoys_flagged"], summ["decoys"]))
            .replace("@ico_overview@", icon("overview")).replace("@ico_leads@", icon("leads")).replace("@ico_how@", icon("all"))
            .replace("@sun@", icon("sun")).replace("@print@", icon("print")))


PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>ADS Proof of Function</title>
<style>@css@
.rk{font:700 16px var(--mono);min-width:44px}.rk.ok{color:var(--ok)}.rk.no{color:var(--dim)}
.cicons{display:flex;gap:4px}
.duo{display:grid;grid-template-columns:minmax(60px,1fr) 24px;gap:8px;align-items:center}
.vbig{font-size:18px;line-height:1.5}
@media (max-width:620px){.hide-s{display:none!important}}
</style></head><body>
<header class="top"><div class="wrap"><div class="brand"><span class="dot"></span>ADS // PROOF</div>
<div class="case"><b>@image@</b><span class="pill acc">@fs@</span><span class="pill hide-s">@key@</span></div><div class="spacer"></div>
<button class="iconbtn" data-act="theme" title="Light or dark">@sun@</button><button class="iconbtn" data-act="print" title="Print every tab">@print@</button></div></header>
<nav class="tabs" aria-label="Sections"><div class="wrap">
<a class="tab" href="#summary" data-tab="summary">@ico_overview@Summary <kbd>1</kbd></a>
<a class="tab" href="#items" data-tab="items">@ico_leads@Item by item <span class="n">@evidence@</span> <kbd>2</kbd></a>
<a class="tab" href="#checks" data-tab="checks">@ico_how@Each check alone <kbd>3</kbd></a></div></nav>
<main class="wrap">
<section class="panel" id="p-summary"><div class="ph"><div><h2>Did ADS point to what was found by hand?</h2><div class="sub">Compared with the examiner's own findings, from the @kind@.</div></div></div>
<div class="grid" style="grid-template-columns:auto minmax(0,1fr);align-items:center">
<div class="card" style="display:grid;place-items:center">@donut@</div>
<div class="card"><p class="vbig">@verdict@</p></div></div>
<div class="grid g4" style="margin-top:14px">
<div class="card kpi ok"><div class="v" data-count="@top10@">0</div><div class="l">evidence files in the top 10</div></div>
<div class="card kpi acc"><div class="v" data-count="@depth@">0</div><div class="l">files to review to reach them</div></div>
<div class="card kpi warn"><div class="v" data-count="@others@">0</div><div class="l">of those not in the key</div></div>
<div class="card kpi"><div class="v" style="font-size:26px">@decoys@</div><div class="l">decoys also listed</div></div></div>
<p class="note" style="margin-top:12px">ADS listed @leads@ of @examined@ files. Files it lists that are not in the key are not necessarily false: the key is one examiner's findings.</p>
</section>
<section class="panel" id="p-items"><div class="ph"><div><h2>Item by item</h2><div class="sub">Each thing found by hand. Open one for detail.</div></div></div>
<div class="toolbar"><div class="seg" id="kf"><button aria-pressed="true" data-k="">All</button><button aria-pressed="false" data-k="1">Listed</button><button aria-pressed="false" data-k="0">Missed</button><button aria-pressed="false" data-k="decoy">Decoys</button></div></div>
<div id="il">@rows@</div></section>
<section class="panel" id="p-checks"><div class="ph"><div><h2>Each check alone, against all of them together</h2><div class="sub">A check alone flags files in no order. ADS gets the same number of files: its top ones.</div></div></div>
<div class="card scroll-x"><table class="t"><thead><tr><th>Check alone</th><th class="num">Files it flags</th><th>Evidence it catches</th><th>ADS, same budget</th><th></th></tr></thead><tbody>@singles@</tbody></table></div></section>
</main>
<footer class="foot"><div class="wrap">ADS points to files for an examiner to review; it does not answer the case questions itself.</div></footer>
<script>@js@</script>
<script>
document.querySelectorAll('#kf button').forEach(b=>b.addEventListener('click',()=>{
  document.querySelectorAll('#kf button').forEach(x=>x.setAttribute('aria-pressed','false'));b.setAttribute('aria-pressed','true');const k=b.dataset.k;
  document.querySelectorAll('#il .acc-item').forEach(it=>{const ok=!k||(k==='decoy'?it.dataset.kind==='decoy':(it.dataset.kind==='evidence'&&it.dataset.found===k));it.style.display=ok?'':'none';});}));
document.addEventListener('ads:tab',e=>{if(e.detail!=='summary')return;document.querySelectorAll('.dn').forEach(c=>{c.style.transition='stroke-dashoffset 1.2s cubic-bezier(.2,.8,.2,1)';
  c.style.strokeDashoffset=c.getAttribute('stroke-dasharray');requestAnimationFrame(()=>requestAnimationFrame(()=>c.style.strokeDashoffset=c.dataset.off));});});
</script></body></html>"""
