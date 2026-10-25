"""Plain-language HTML briefing for the Windows (NTFS) analysis.

The command-line `analyze` writes report.md for examiners. This renders the same
results as one self-contained web page a non-specialist can read: what was found,
why, and the evidence behind each flag, with the technical detail folded away.
"""

import html
import json
import re

from .config import RULE_IDS
from .explain import INDICATOR_PLAIN, nice, rule_name, rule_what, say
from .rules import VIOLATED

# Only files above the flag threshold θ are shown. Among them, "Look first" needs at least two
# independent checks disagreeing and a score of at least STRONG (or θ, if θ is set higher);
# every other flagged file is "Worth a look". Both tiers can therefore occur at any θ.
STRONG = 0.50
_TS = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?")


def _nice_text(s):
    """Rewrite every stored timestamp inside a string in the plain '10 Oct 2026, 09:25:03 UTC' form."""
    return _TS.sub(lambda m: nice(m.group(0)), str(s))


def _strong(theta):
    return max(float(theta), STRONG)
PALETTE = """
:root{--cardinal:#C8102E;--cardinal-ink:#9E0B23;--gold:#F1BE48;--gold-deep:#B07A0C;--ink:#1A1A1A;
--muted:#5E5A5A;--line:#DAD6D6;--paper:#FFF;--panel:#F7F4F2;--bar:#161616;--on-bar:#F2F2F2;--ok:#2E7D4F;
--soft:#FBECEE;--head:Cambria,Georgia,"Times New Roman",serif;--body:Calibri,"Segoe UI",Arial,sans-serif;
--mono:Consolas,"Courier New",monospace}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){--cardinal:#E2304C;--cardinal-ink:#FF8095;
--gold:#F1BE48;--gold-deep:#F1BE48;--ink:#EDE8E6;--muted:#ADA5A3;--line:#3A3434;--paper:#151212;
--panel:#1F1A1A;--bar:#0B0909;--ok:#6CC596;--soft:#2A1A1D;color-scheme:dark}}
:root[data-theme=dark]{--cardinal:#E2304C;--cardinal-ink:#FF8095;--gold:#F1BE48;--gold-deep:#F1BE48;
--ink:#EDE8E6;--muted:#ADA5A3;--line:#3A3434;--paper:#151212;--panel:#1F1A1A;--bar:#0B0909;--ok:#6CC596;
--soft:#2A1A1D;color-scheme:dark}
"""


def _tier(f, theta):
    if f["score"] >= _strong(theta) and len(f["fired"]) >= 2:
        return "Look first", "hot"
    return "Worth a look", "warm"


def _esc(s):
    return html.escape(str(s))


def build_data(ctx, outcome_rows, scored, indicators, clusters, sys_score, meta):
    """Collect everything the page shows into one plain dict."""
    outcomes = {}
    for key, rid, outcome, details in outcome_rows:
        outcomes.setdefault((key[0], key[1]), {})[rid] = (outcome, details)
    flagged = [r for r in scored if r["flagged"]]
    leads = []
    for r in sorted(flagged, key=lambda r: (-r["score"], -len(r["fired"]))):
        key = (r["entry"], r["seq"])
        fired = []
        for rid in r["fired"]:
            _o, d = outcomes[key][rid]
            fired.append({"id": rid, "name": rule_name(rid), "say": say(rid, d),
                          "tech": {k: v for k, v in d.items() if not k.startswith("_")}})
        tier, cls = _tier(r, meta["theta"])
        leads.append({"path": r["path"], "entry": r["entry"], "seq": r["seq"],
                      "score": round(r["score"] * 100), "tier": tier, "cls": cls,
                      "evaluable": r["evaluable"], "confidence": round(r["confidence"] * 100),
                      "cluster": r.get("cluster"), "fired": fired,
                      "weak": r["violated_from_degraded_sources"]})
    warnings = [{"id": i["id"], "name": i["name"], "status": i["status"],
                 "plain": INDICATOR_PLAIN.get(i["id"], ""), "details": i["details"]}
                for i in indicators]
    level = "clear"
    if any(w["status"] == "fired" for w in warnings):
        level = "degraded"
    return {
        "generated": meta.get("generated", ""),
        "theta": meta["theta"], "weight_mode": meta["weight_mode"],
        "inputs": meta["inputs"],
        "counts": {"scored": len(scored), "flagged": len(flagged),
                   "look_first": sum(1 for l in leads if l["tier"] == "Look first")},
        "system": {"score": round(sys_score[0] * 100), "evaluable": sys_score[1], "level": level},
        "leads": leads,
        "clusters": [{"start": c["start"], "end": c["end"], "files": c["files"], "paths": c["paths"],
                      "prefetch": c["prefetch_runs"], "indicators": c["indicators"]} for c in clusters],
        "warnings": warnings,
        "rules": {rid: {"name": rule_name(rid), "what": rule_what(rid)} for rid in RULE_IDS},
    }


def _lead_html(l):
    chips = ""
    for f in l["fired"]:
        tech = json.dumps(f["tech"], indent=1, default=str)
        chips += (
            '<div class="clue"><div class="chd"><span class="cid">%s</span><b>%s</b></div>'
            '<p>%s</p><details><summary>Technical detail</summary><pre>%s</pre></details></div>'
            % (_esc(f["id"]), _esc(f["name"]), _esc(f["say"]), _esc(tech)))
    weak = ""
    if l["weak"]:
        weak = ('<p class="weak">Note: some of this rests on records a warning below reports as damaged '
                '(%s), so treat it with care.</p>' % _esc(", ".join(l["weak"])))
    event = (" · part of event %s" % l["cluster"]) if l["cluster"] else ""
    return (
        '<article class="lead {cls}" id="f{entry}-{seq}">'
        '<header><div class="score"><span class="num">{score}</span><span class="of">/100</span></div>'
        '<div class="who"><span class="tier {cls}">{tier}</span>'
        '<h3>{path}</h3><p class="meta">{evaluable} of 11 checks could be run · '
        '{conf}% rest on undamaged records{event}</p></div></header>'
        '{weak}{chips}</article>'
    ).format(cls=l["cls"], entry=l["entry"], seq=l["seq"], score=l["score"], tier=_esc(l["tier"]),
             path=_esc(l["path"]), evaluable=l["evaluable"], conf=l["confidence"],
             event=event, weak=weak, chips=chips)


def render(data):
    d = data
    sysline = ("No sign that the records themselves were tampered with."
               if d["system"]["level"] == "clear"
               else "Some records look damaged or incomplete — see “About the records” below.")
    leads = "".join(_lead_html(l) for l in d["leads"]) or '<p class="none">No file crossed the flag threshold.</p>'

    clusters = ""
    for n, c in enumerate(d["clusters"], 1):
        pf = ("<br>Programs that ran in this window: " + _esc(_nice_text(", ".join(c["prefetch"])).replace(" @ ", " at "))) if c["prefetch"] else ""
        inds = ("<br>Warnings in this window: " + _esc(", ".join(c["indicators"]))) if c["indicators"] else ""
        files = "".join("<li>%s</li>" % _esc(p) for p in c["paths"])
        start, end = nice(c["start"]), nice(c["end"])
        when = ("at %s" % start) if start == end else ("between %s and %s" % (start, end))
        many = ("%d files were changed within a few minutes of each other" % c["files"]) if c["files"] > 1 \
            else "1 file was changed"
        clusters += ('<div class="event"><h3>Event %d — %s</h3><p>%s %s.%s%s</p><ul>%s</ul></div>'
                     % (n, _esc(start), many, _esc(when), pf, inds, files))
    clusters = clusters or '<p class="none">No files were flagged close enough together in time to form an event.</p>'

    warns = ""
    for w in d["warnings"]:
        badge = {"fired": "⚠ found", "clear": "✓ clear", "not_evaluable": "– not checked"}.get(w["status"], w["status"])
        wc = {"fired": "wfired", "clear": "wclear"}.get(w["status"], "wna")
        det = ("<details><summary>Detail</summary><pre>%s</pre></details>"
               % _esc(json.dumps(w["details"], indent=1, default=str))) if w["details"] else ""
        warns += ('<tr class="%s"><td><b>%s</b></td><td>%s</td><td>%s</td><td>%s</td></tr>'
                  % (wc, _esc(w["id"]), _esc(badge), _esc(w["plain"] or w["name"]), det))

    rules = "".join('<tr><td><b>%s</b></td><td>%s</td><td>%s</td></tr>'
                    % (_esc(rid), _esc(r["name"]), _esc(r["what"])) for rid, r in d["rules"].items())
    inputs = "".join('<tr><td>%s</td><td>%s</td><td>%s</td><td class="h">%s</td></tr>'
                     % (_esc(i["kind"]), _esc(i["path"].rsplit("/", 1)[-1].rsplit("\\", 1)[-1]),
                        _esc(i["rows"]), _esc(i["sha256"][:16] + "…")) for i in d["inputs"])

    repl = {
        "@palette@": PALETTE, "@scored@": d["counts"]["scored"], "@flagged@": d["counts"]["flagged"],
        "@look@": d["counts"]["look_first"], "@sysscore@": d["system"]["score"], "@sysline@": _esc(sysline),
        "@generated@": _esc(d["generated"]), "@theta@": int(round(float(d["theta"]) * 100)), "@mode@": _esc(d["weight_mode"]),
        "@leads@": leads, "@clusters@": clusters, "@warns@": warns, "@rules@": rules, "@inputs@": inputs,
        "@strong@": int(round(_strong(d["theta"]) * 100)),
    }
    page = TEMPLATE
    for k, v in repl.items():
        page = page.replace(k, str(v))
    return page


TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ADS Windows Report</title>
<style>@palette@
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font:17px/1.55 var(--body)}
.wrap{max-width:1040px;margin:0 auto;padding:0 16px}
h1,h2,h3{font-family:var(--head);margin:0}
h2{color:var(--cardinal);font-size:clamp(24px,4vw,34px);margin-top:8px}
h3{font-size:20px}
p{margin:.4em 0;max-width:72ch}
a{color:var(--cardinal)}
code,pre{font-family:var(--mono);font-size:.84em}
#bar{position:sticky;top:0;z-index:9;background:var(--bar);color:var(--on-bar)}
#bar .wrap{display:flex;gap:4px;align-items:center;height:50px;overflow-x:auto}
#bar .brand{color:var(--gold);font-weight:700;letter-spacing:.08em;text-transform:uppercase;font-size:14px;margin-right:10px;white-space:nowrap}
#bar a{color:inherit;text-decoration:none;padding:6px 10px;border-radius:7px;white-space:nowrap;font-size:15px}
#bar a:hover{background:rgba(255,255,255,.12)}
.band{background:var(--cardinal);color:#fff;border-bottom:9px solid var(--gold)}
.band .wrap{padding:34px 16px 30px}
.band .eyebrow{color:var(--gold);font-weight:700;letter-spacing:.14em;text-transform:uppercase;font-size:13px}
.band h1{font-size:clamp(28px,5vw,46px);margin:8px 0;line-height:1.08}
.band p{max-width:52ch;font-size:18px}
.stats{display:grid;grid-template-columns:repeat(4,1fr);background:var(--bar);color:var(--on-bar)}
.stat{padding:16px}
.stat+.stat{border-left:1px solid rgba(255,255,255,.14)}
.stat .n{font:700 clamp(26px,4vw,40px)/1 var(--head)}
.stat .l{font-size:14px;color:#BDB5B3}
.stat.hot .n{color:var(--gold)}
section{padding:40px 0 10px;border-bottom:1px solid var(--line)}
.kick{font:700 13px var(--mono);letter-spacing:.08em;color:var(--muted)}
.lead{border:1px solid var(--line);border-left-width:6px;border-radius:12px;padding:16px;margin:16px 0;background:var(--paper)}
.lead.hot{border-left-color:var(--cardinal)}
.lead.warm{border-left-color:var(--gold-deep)}
.lead header{display:flex;gap:16px;align-items:flex-start}
.score{flex:none;width:76px;text-align:center;background:var(--panel);border-radius:10px;padding:8px 4px}
.score .num{font:700 30px/1 var(--head)}
.score .of{display:block;font-size:12px;color:var(--muted)}
.who h3{margin:3px 0;overflow-wrap:anywhere}
.tier{font:700 12px var(--body);letter-spacing:.06em;text-transform:uppercase;padding:2px 9px;border-radius:999px;background:var(--soft);color:var(--cardinal-ink)}
.tier.hot{background:var(--cardinal);color:#fff}
.meta{font-size:14px;color:var(--muted)}
.clue{background:var(--panel);border-radius:10px;padding:11px 13px;margin-top:10px}
.chd{display:flex;gap:8px;align-items:center}
.cid{font:700 12px var(--mono);background:var(--cardinal);color:#fff;border-radius:5px;padding:1px 7px}
.clue p{margin:5px 0 4px}
details{margin-top:4px}
summary{cursor:pointer;color:var(--muted);font-size:14px}
pre{background:var(--panel);padding:10px;border-radius:8px;overflow-x:auto;white-space:pre-wrap;word-break:break-word}
.weak{color:var(--cardinal-ink);font-size:14px;font-style:italic}
.event{border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin:14px 0}
.event ul{margin:6px 0 0;padding-left:20px}
table{border-collapse:collapse;width:100%;margin:12px 0;font-size:15px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-size:13px;text-transform:uppercase;letter-spacing:.05em}
td.h{font-family:var(--mono);font-size:12px;color:var(--muted)}
tr.wfired td{background:var(--soft)}
tr.wclear td b{color:var(--ok)}
.none{color:var(--muted);font-style:italic}
footer{padding:26px 0 50px;color:var(--muted);font-size:14px}
@media(max-width:640px){.stats{grid-template-columns:repeat(2,1fr)}.stat:nth-child(n+3){border-top:1px solid rgba(255,255,255,.14)}.stat:nth-child(3){border-left:0}.lead header{flex-wrap:wrap}}
</style></head><body>
<div id="bar"><div class="wrap"><span class="brand">ADS</span>
<a href="#summary">Summary</a><a href="#first">Look first</a><a href="#events">Events</a>
<a href="#records">About the records</a><a href="#how">How it works</a><a href="#method">Method</a></div></div>

<div class="band"><div class="wrap">
<div class="eyebrow">Artifact Disagreement Scorer · Windows drive report</div>
<h1>What the records say — and where they disagree</h1>
<p>This drive keeps several separate records of what happened to each file. This report lines them up,
points out where they contradict each other, and explains each one in plain words.</p>
</div></div>

<div class="stats"><div class="wrap" style="display:contents">
<div class="stat"><div class="n">@scored@</div><div class="l">files checked</div></div>
<div class="stat hot"><div class="n">@flagged@</div><div class="l">files flagged</div></div>
<div class="stat hot"><div class="n">@look@</div><div class="l">to look at first</div></div>
<div class="stat"><div class="n">@sysscore@</div><div class="l">record-damage score /100</div></div>
</div></div>

<section id="summary"><div class="wrap">
<div class="kick">SUMMARY</div><h2>In short</h2>
<p>Of @scored@ files examined, @flagged@ were flagged because their own records disagree with each other.
@look@ of those are the ones to look at first. @sysline@</p>
<p>Every flag below is explained in one plain sentence, with the exact dates and the technical detail folded
underneath for an examiner. All times in this report are UTC (Coordinated Universal Time), the clock Windows
keeps internally; for US Central time subtract 5 or 6 hours.</p>
</div></section>

<section id="first"><div class="wrap">
<div class="kick">FILES TO LOOK AT FIRST</div><h2>Flagged files</h2>
<p>Ranked by how strongly the records disagree. A higher number means more independent records contradict
each other for that file.</p>
@leads@
</div></section>

<section id="events"><div class="wrap">
<div class="kick">CANDIDATE EVENTS</div><h2>Files changed together</h2>
<p>Tampering often touches several files at once, around the moment a single program ran. These groups are a
good place to reconstruct what happened.</p>
@clusters@
</div></section>

<section id="records"><div class="wrap">
<div class="kick">ABOUT THE RECORDS</div><h2>Were the records themselves tampered with?</h2>
<p>Deleting a whole record can be easier than faking one. These checks look for records that were cleared,
reset, or are missing. They do not accuse any single file; they say how much to trust the rest.</p>
<table><tr><th>ID</th><th>Status</th><th>What it means</th><th></th></tr>@warns@</table>
</div></section>

<section id="how"><div class="wrap">
<div class="kick">HOW IT WORKS</div><h2>The idea in one line</h2>
<p>Windows records the same event in several places, written by different parts of the system. A cover-up can
change one or two of them, but keeping them all agreeing is hard — so disagreement is the clue. The tool runs
eleven checks for disagreement and weighs them together, so one noisy check never raises an alarm on its own.</p>
<table><tr><th>Check</th><th>Plain name</th><th>What it looks for</th></tr>@rules@</table>
</div></section>

<section id="method"><div class="wrap">
<div class="kick">METHOD &amp; WORDS</div><h2>How to read the score, and the fine print</h2>
<p>Each file's score is the weighted share of the checks that disagreed, out of the checks that could be run,
as a number from 0 to 100. A file is flagged when its score is above @theta@. Flagged files are “Look first”
when they score @strong@ or more with at least two checks disagreeing, and “Worth a look” otherwise.
Weighting mode: @mode@.</p>
<p>The records were read with standard, widely used forensic tools; this report only cross-checks and explains
them. Each input and its fingerprint (SHA-256):</p>
<table><tr><th>Record</th><th>File</th><th>Rows</th><th>Fingerprint</th></tr>@inputs@</table>
<p>Generated @generated@.</p>
</div></section>

<footer><div class="wrap">Artifact Disagreement Scorer · CPRE 5360 · This report points to files for an examiner to review;
it does not by itself prove tampering.</div></footer>
</body></html>
"""
