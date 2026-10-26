"""Plain-language HTML report for the Windows (NTFS) date checks.

The command-line `analyze` writes report.md for examiners. This renders the same
results as one self-contained, tabbed page in the shared ADS theme: an overview,
the flagged files (each a compact row that expands to its plain sentences and the
values behind them), candidate events, the health of the records themselves, and
how the checks work. No external fonts or scripts are loaded.
"""

import html
import json
import re

from .config import RULE_IDS
from .explain import INDICATOR_PLAIN, nice, rule_name, rule_what, say
from .rules import NOT_EVALUABLE, VIOLATED
from .theme import THEME_CSS, THEME_JS, icon

# Only files above the flag threshold θ are shown as flagged. Among them, "Look first" needs at least
# two independent checks disagreeing and a score of at least STRONG (or θ, if θ is set higher);
# every other flagged file is "Worth a look". Both tiers can therefore occur at any θ.
STRONG = 0.50
# A check that fires on at least this share of the files it could check is reported as a drive-wide
# pattern: it cannot single out files, but it says something about the whole drive.
DRIVE_WIDE = 0.90
DRIVE_WIDE_MIN = 50      # ...and only when it could check enough files for "nearly every file" to mean something
_TS = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?")


def _nice_text(s):
    """Rewrite every stored timestamp inside a string in the plain '10 Oct 2026, 09:25:03 UTC' form."""
    return _TS.sub(lambda m: nice(m.group(0)), str(s))


def _strong(theta):
    return max(float(theta), STRONG)


def _tier(f, theta):
    if f["score"] >= _strong(theta) and len(f["fired"]) >= 2:
        return "Look first", "hot"
    return "Worth a look", "warn"


def _esc(s):
    return html.escape(str(s))


def build_data(ctx, outcome_rows, scored, indicators, clusters, sys_score, meta):
    """Collect everything the page shows into one plain dict."""
    outcomes = {}
    activity = {rid: {"evaluable": 0, "violated": 0} for rid in RULE_IDS}
    for key, rid, outcome, details in outcome_rows:
        outcomes.setdefault((key[0], key[1]), {})[rid] = (outcome, details)
        if outcome != NOT_EVALUABLE:
            activity[rid]["evaluable"] += 1
            activity[rid]["violated"] += outcome == VIOLATED
    flagged = [r for r in scored if r["flagged"]]
    leads = []
    for r in sorted(flagged, key=lambda r: (-r["score"], -len(r["fired"]))):
        key = (r["entry"], r["seq"])
        fired = []
        for rid in r["fired"]:
            _o, d = outcomes[key][rid]
            fired.append({"id": rid, "name": rule_name(rid), "say": say(rid, d),
                          "tech": {k: v for k, v in d.items() if not k.startswith("_")}})
        status = {}
        for rid in RULE_IDS:
            o, d = outcomes[key].get(rid, (NOT_EVALUABLE, {}))
            status[rid] = [o, d.get("reason", "")]
        tier, cls = _tier(r, meta["theta"])
        leads.append({"path": r["path"], "entry": r["entry"], "seq": r["seq"],
                      "score": round(r["score"] * 100), "tier": tier, "cls": cls,
                      "evaluable": r["evaluable"], "confidence": round(r["confidence"] * 100),
                      "cluster": r.get("cluster"), "fired": fired, "status": status,
                      "weak": r["violated_from_degraded_sources"]})
    warnings = [{"id": i["id"], "name": i["name"], "status": i["status"],
                 "plain": INDICATOR_PLAIN.get(i["id"], ""), "details": i["details"]}
                for i in indicators]
    level = "degraded" if any(w["status"] == "fired" for w in warnings) else "clear"
    return {
        "generated": meta.get("generated", ""),
        "theta": meta["theta"], "weight_mode": meta["weight_mode"],
        "calibration": meta.get("calibration"),
        "inputs": meta["inputs"],
        "counts": {"scored": len(scored), "flagged": len(flagged),
                   "look_first": sum(1 for l in leads if l["tier"] == "Look first")},
        "system": {"score": round(sys_score[0] * 100), "evaluable": sys_score[1], "level": level},
        "leads": leads,
        "activity": activity,
        "clusters": [{"start": c["start"], "end": c["end"], "files": c["files"], "paths": c["paths"],
                      "prefetch": c["prefetch_runs"], "indicators": c["indicators"]} for c in clusters],
        "warnings": warnings,
        "rules": {rid: {"name": rule_name(rid), "what": rule_what(rid)} for rid in RULE_IDS},
    }


def _name_dir(path):
    p = str(path).replace("/", "\\")
    if "\\" in p.strip("\\"):
        d, n = p.rsplit("\\", 1)
        return n, d or "\\"
    return p.strip("\\") or p, "\\"


def _chev():
    return icon("chev", "ico chev")


def _strip(status):
    out = []
    for rid in RULE_IDS:
        o, reason = status.get(rid, [NOT_EVALUABLE, ""])
        k = {"violated": "fired", "consistent": "clean"}.get(o, "na")
        tip = {"fired": "Disagreement found", "clean": "Checked: records agree"}.get(k, "Could not check" + (": " + reason if reason else ""))
        out.append('<div class="c8 %s" data-tip="<b>%s %s</b><br>%s"><i></i>%s</div>'
                   % (k, rid, _esc(rule_name(rid)), _esc(tip), rid))
    return '<div class="checks11">%s</div>' % "".join(out)


def _lead_html(i, l):
    name, folder = _name_dir(l["path"])
    chips = "".join('<span class="chip" data-tip="%s"><b>%s</b></span>' % (_esc(f["name"]), f["id"]) for f in l["fired"])
    why = "".join('<li><span class="cic">%s</span><div><div class="t">%s · %s</div><div class="s">%s</div></div></li>'
                  % (icon("time"), f["id"], _esc(f["name"]), _esc(f["say"])) for f in l["fired"])
    tech = "".join("<dt>%s</dt><dd>%s</dd>" % (f["id"], _esc(json.dumps(f["tech"], default=str, sort_keys=True))) for f in l["fired"])
    weak = ('<div class="note" style="color:var(--warn);margin-top:8px">Some of this rests on records a warning reports as '
            'damaged (%s); treat it with care.</div>' % _esc(", ".join(l["weak"]))) if l["weak"] else ""
    return (
        '<div class="acc-item" data-text="{text}"><button class="acc-head" aria-expanded="false"><div class="lead-row">'
        '<span class="rank">#{rank}</span><div class="score"><div class="v">{score}<small>/100</small></div>'
        '<div class="bar {cls}"><i data-w="{score}"></i></div></div><div class="fname"><b>{name}</b><span>{folder}</span></div>'
        '<div class="cicons">{chips}</div><span class="badge {cls}">{tier}</span>{chev}</div></button>'
        '<div class="acc-body"><div><div class="acc-inner"><div class="why"><ul>{why}</ul></div>{weak}'
        '<details class="more"><summary>Technical detail</summary><dl class="kv"><dt>Full path</dt><dd>{path}</dd>'
        '<dt>MFT record</dt><dd>{entry}-{seq}</dd><dt>Checks run</dt><dd>{ev} of 11 ({conf}% on undamaged records)</dd>{event}{tech}</dl>'
        '<div class="note" style="margin-top:10px">All eleven date checks for this file:</div>{strip}</details>'
        '</div></div></div></div>'
    ).format(text=_esc(l["path"].lower()), rank=i, score=l["score"], cls=l["cls"], name=_esc(name), folder=_esc(folder),
             chips=chips, tier=_esc(l["tier"]), chev=_chev(), why=why, weak=weak, path=_esc(l["path"]),
             entry=l["entry"], seq=l["seq"], ev=l["evaluable"], conf=l["confidence"],
             event=("<dt>Event</dt><dd>%s</dd>" % l["cluster"]) if l["cluster"] else "", tech=tech, strip=_strip(l["status"]))


def render(data):
    d = data
    c, sysd = d["counts"], d["system"]
    theta100 = int(round(float(d["theta"]) * 100))

    # ---- check activity (drive-wide patterns) ----
    act_rows, wide = "", []
    for rid in d["rules"]:
        a = d.get("activity", {}).get(rid, {"evaluable": 0, "violated": 0})
        ev, vi = a["evaluable"], a["violated"]
        share = vi / ev if ev else 0
        is_wide = ev >= DRIVE_WIDE_MIN and share >= DRIVE_WIDE
        if is_wide:
            wide.append((rid, vi, ev, share))
        cls = "hot" if is_wide else ("warn" if vi else "ok")
        label = ("not checkable" if not ev else "%s / %s · %s%%" % (format(vi, ","), format(ev, ","),
                                                                     ("%.1f" % (100 * share)).rstrip("0").rstrip(".")))
        act_rows += ('<div class="cbar" data-tip="<b>{rid} {name}</b><br>{what}"><span class="cic">{ic}</span><div><div class="nm">{rid} · {name}</div>'
                     '<div class="bar {cls}"><i data-w="{w:.1f}"></i></div></div><span class="mono note" style="text-align:right">{label}</span></div>'
                     ).format(rid=rid, name=_esc(d["rules"][rid]["name"]), what=_esc(d["rules"][rid]["what"]), ic=icon("time"),
                              cls=cls if ev else "minor", w=100 * share if ev else 0, label=label)
    wide_html = ""
    if wide:
        items = "".join("<li><b>%s</b> %s fired on %s of %s files</li>" % (rid, _esc(rule_name(rid)), format(vi, ","), format(ev, ","))
                        for rid, vi, ev, _s in wide)
        wide_html = ('<div class="card" style="border-color:var(--hot);margin-top:14px"><h3 style="color:var(--hot)">%sDrive-wide pattern</h3>'
                     '<p>These checks disagree on nearly every file, so they cannot single any file out, but they say something about '
                     'the whole drive, for example that every visible date was set at once.</p><ul class="note" style="margin:8px 0 0">%s</ul></div>'
                     % (icon("events"), items))

    leads = "".join(_lead_html(i, l) for i, l in enumerate(d["leads"], 1)) or \
        '<div class="card"><div class="empty">No file crossed the flag line. See Check activity on the Overview for drive-wide patterns.</div></div>'

    events = ""
    for n, cl in enumerate(d["clusters"], 1):
        start, end = nice(cl["start"]), nice(cl["end"])
        when = start if start == end else "%s → %s" % (start, end)
        pf = "".join('<span class="chip">%s</span> ' % _esc(_nice_text(p).replace(" @ ", " at ")) for p in cl["prefetch"])
        inds = "".join('<span class="badge warn">%s</span> ' % _esc(x) for x in cl["indicators"])
        files = "".join('<div class="mono note">%s</div>' % _esc(p) for p in cl["paths"])
        events += ('<div class="acc-item"><button class="acc-head"><span class="cic">{ic}</span><div style="flex:1;min-width:0"><b>Event {n}</b>'
                   '<div class="note mono">{when}</div></div><span class="chip"><b>{k}</b>&nbsp;file{s}</span>{chev}</button>'
                   '<div class="acc-body"><div><div class="acc-inner"><div style="margin-top:10px">{files}</div>'
                   '{pf}{inds}</div></div></div></div>'
                   ).format(ic=icon("events"), n=n, when=_esc(when), k=cl["files"], s="" if cl["files"] == 1 else "s", chev=_chev(),
                            files=files, pf=('<div class="note" style="margin-top:8px">Programs that ran then: %s</div>' % pf) if pf else "",
                            inds=('<div class="note" style="margin-top:8px">Warnings then: %s</div>' % inds) if inds else "")
    events = events or '<div class="card"><div class="empty">No flagged files were changed close enough together to form an event.</div></div>'

    recs = ""
    for w in d["warnings"]:
        st = {"fired": ("hot", "Found"), "clear": ("ok", "Clear"), "not_evaluable": ("minor", "Not checked")}.get(w["status"], ("minor", w["status"]))
        det = ('<details class="more"><summary>Detail</summary><div class="ctx mono" style="margin-top:6px;white-space:pre-wrap">%s</div></details>'
               % _esc(json.dumps(w["details"], indent=1, default=str))) if w["details"] else ""
        recs += ('<div class="card"><div style="display:flex;justify-content:space-between;gap:8px;align-items:center"><b>%s · %s</b>'
                 '<span class="badge %s">%s</span></div><p class="note" style="margin-top:6px">%s</p>%s</div>'
                 % (w["id"], _esc(w["name"]), st[0], st[1], _esc(w["plain"]), det))

    rules = "".join(('<div class="acc-item" style="margin:0"><button class="acc-head"><span class="cic">{ic}</span><div style="flex:1;min-width:0">'
                     '<b>{rid} · {name}</b><div class="note">{what}</div></div>{chev}</button><div class="acc-body"><div><div class="acc-inner">'
                     '<dl class="kv"><dt>Files it could check</dt><dd>{ev}</dd><dt>Disagreements</dt><dd>{vi}</dd></dl></div></div></div></div>'
                     ).format(ic=icon("time"), rid=rid, name=_esc(r["name"]), what=_esc(r["what"]), chev=_chev(),
                              ev=format(d.get("activity", {}).get(rid, {}).get("evaluable", 0), ","),
                              vi=format(d.get("activity", {}).get(rid, {}).get("violated", 0), ","))
                    for rid, r in d["rules"].items())
    inputs = "".join('<tr><td>%s</td><td class="mono">%s</td><td class="num">%s</td><td class="mono note">%s…</td></tr>'
                     % (_esc(i["kind"]), _esc(i["path"].replace("\\", "/").rsplit("/", 1)[-1]), format(i["rows"], ","),
                        _esc(i["sha256"][:16])) for i in d["inputs"])
    tops = "".join('<div class="mini" data-go="flagged"><span class="rank">#%d</span><span class="badge %s">%d</span><div class="fname"><b>%s</b><span>%s</span></div><span></span></div>'
                   % (i, l["cls"], l["score"], _esc(_name_dir(l["path"])[0]), _esc(_name_dir(l["path"])[1])) for i, l in enumerate(d["leads"][:5], 1))

    tabs = [("overview", "Overview", "overview", ""), ("flagged", "Flagged files", "leads", c["flagged"]),
            ("events", "Events", "events", len(d["clusters"])), ("records", "Records", "shield", ""), ("how", "How it works", "how", "")]
    tabbar = "".join('<a class="tab" href="#%s" data-tab="%s" role="tab">%s%s%s <kbd>%d</kbd></a>'
                     % (t, t, icon(ic), lab, (' <span class="n">%s</span>' % n) if n != "" else "", i)
                     for i, (t, lab, ic, n) in enumerate(tabs, 1))
    rec_note = ("No sign that the records themselves were damaged." if sysd["level"] == "clear"
                else "Some records look cleared, reset or incomplete.")

    body = (
        '<section class="panel" id="p-overview"><div class="ph"><div><h2>Overview</h2><div class="sub">{scored} files checked. '
        'All times are UTC.</div></div></div><div class="grid g4">'
        '<div class="card kpi acc"><div class="v" data-count="{scored_n}">0</div><div class="l">files checked</div></div>'
        '<div class="card kpi warn"><div class="v" data-count="{flagged}">0</div><div class="l">flagged</div></div>'
        '<div class="card kpi hot"><div class="v" data-count="{look}">0</div><div class="l">look first</div></div>'
        '<div class="card kpi {syscls}"><div class="v" data-count="{sys}">0</div><div class="l">record damage /100</div></div></div>'
        '{wide}<div class="grid g2" style="margin-top:14px"><div class="card"><h3>Check activity</h3>{act}'
        '<div class="note" style="margin-top:6px">How often each date check found a disagreement.</div></div>'
        '<div class="card"><h3>Top flagged files</h3>{tops}<p class="note" style="margin-top:8px">{recnote}</p></div></div></section>'
        '<section class="panel" id="p-flagged"><div class="ph"><div><h2>Flagged files</h2><div class="sub">Files whose own records '
        'disagree. Open one to see why.</div></div></div><div class="toolbar"><label class="search">{sic}<input id="fq" '
        'placeholder="Search path" aria-label="Search flagged files"></label></div><div id="fl">{leads}</div></section>'
        '<section class="panel" id="p-events"><div class="ph"><div><h2>Events</h2><div class="sub">Flagged files changed within '
        'minutes of each other.</div></div></div>{events}</section>'
        '<section class="panel" id="p-records"><div class="ph"><div><h2>Records</h2><div class="sub">Were the records themselves '
        'cleared, reset or removed?</div></div></div><div class="grid g2">{recs}</div></section>'
        '<section class="panel" id="p-how"><div class="ph"><div><h2>How it works</h2><div class="sub">Eleven checks compare the '
        'dates Windows keeps in different places.</div></div></div><div class="grid g2">{rules}</div>'
        '<div class="grid g2" style="margin-top:14px"><div class="card"><h3>The score</h3><p>The weighted share of checks that '
        'found a disagreement, out of 100. Flagged above {theta}; “Look first” at {strong}+ with two or more checks.</p>'
        '<dl class="kv"><dt>Weighting</dt><dd>{mode}</dd><dt>Rates from</dt><dd>{cal}</dd></dl></div>'
        '<div class="card"><h3>Inputs</h3><div class="scroll-x"><table class="t"><thead><tr><th>Record</th><th>File</th>'
        '<th class="num">Rows</th><th>SHA-256</th></tr></thead><tbody>{inputs}</tbody></table></div></div></div></section>'
    ).format(scored=format(c["scored"], ","), scored_n=c["scored"], flagged=c["flagged"], look=c["look_first"], sys=sysd["score"],
             syscls="hot" if sysd["level"] != "clear" else "ok", wide=wide_html, act=act_rows, tops=tops or '<div class="empty">None.</div>',
             recnote=_esc(rec_note), sic=icon("search"), leads=leads, events=events, recs=recs, rules=rules, theta=theta100,
             strong=int(round(_strong(d["theta"]) * 100)), mode=_esc(d["weight_mode"]), cal=_esc(d.get("calibration") or "defaults"),
             inputs=inputs)

    return PAGE.replace("@css@", THEME_CSS).replace("@js@", THEME_JS).replace("@tabs@", tabbar).replace("@body@", body) \
        .replace("@generated@", _esc(d["generated"])).replace("@sun@", icon("sun")).replace("@print@", icon("print"))


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>ADS Windows Date Report</title>
<style>@css@
.lead-row{display:grid;grid-template-columns:44px 92px minmax(0,1fr) auto auto 18px;align-items:center;gap:12px;width:100%}
.rank{font:700 13px var(--mono);color:var(--dim)}
.score{display:grid;gap:4px}.score .v{font:700 16px/1 var(--mono)}.score .v small{font-size:11px;color:var(--dim)}
.fname{min-width:0}.fname b{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.fname span{display:block;font:12px var(--mono);color:var(--dim);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.cicons{display:flex;gap:4px}
.cic{width:26px;height:26px;border-radius:7px;display:grid;place-items:center;background:var(--accent-soft);color:var(--accent-ink);flex:none}
.cic .ico{width:15px;height:15px}
.why ul{margin:12px 0 0;padding:0;display:grid;gap:8px}.why li{list-style:none;display:grid;grid-template-columns:26px 1fr;gap:10px}
.why .t{font-weight:650}.why .s{color:var(--muted);font-size:14px}
.checks11{display:grid;grid-template-columns:repeat(11,minmax(0,1fr));gap:5px;margin-top:8px}
.c8{border:1px solid var(--line);border-radius:8px;padding:6px 2px;text-align:center;font:700 11px var(--mono);background:var(--panel)}
.c8 i{display:block;width:8px;height:8px;border-radius:50%;margin:0 auto 4px;background:var(--dim)}
.c8.fired{border-color:var(--hot);color:var(--hot)}.c8.fired i{background:var(--hot)}.c8.clean i{background:var(--ok)}.c8.na{color:var(--dim)}
.cbar{display:grid;grid-template-columns:30px minmax(0,1fr) 168px;gap:10px;align-items:center;padding:5px 6px;border-radius:8px}
.cbar .nm{font-size:13px}
.mini{display:grid;grid-template-columns:34px 46px minmax(0,1fr) 0;gap:10px;align-items:center;padding:8px 6px;border-radius:8px;cursor:pointer}
.mini:hover{background:var(--panel2)}
.ctx{background:var(--panel2);border:1px solid var(--line);border-radius:6px;padding:8px;font-size:12px;overflow-wrap:anywhere}
.empty{color:var(--dim);font-style:italic}
@media (max-width:760px){.lead-row{grid-template-columns:34px 70px minmax(0,1fr) 18px}.lead-row .cicons,.lead-row .badge{display:none}
  .checks11{grid-template-columns:repeat(6,minmax(0,1fr))}.cbar{grid-template-columns:30px minmax(0,1fr)}.cbar .note{grid-column:2}}
</style></head><body>
<header class="top"><div class="wrap"><div class="brand"><span class="dot"></span>ADS // DATE CHECKS</div>
<div class="case"><span class="pill acc">NTFS</span><span class="pill hide-s">@generated@</span></div><div class="spacer"></div>
<button class="iconbtn" data-act="theme" title="Light or dark">@sun@</button><button class="iconbtn" data-act="print" title="Print every tab">@print@</button></div></header>
<nav class="tabs" aria-label="Report sections"><div class="wrap">@tabs@</div></nav>
<main class="wrap">@body@</main>
<footer class="foot"><div class="wrap">Artifact Disagreement Scorer · read-only · This report points to files for an examiner to review; it does not by itself prove tampering.</div></footer>
<script>@js@</script>
<script>
document.addEventListener('click',e=>{const g=e.target.closest('[data-go]');if(g){e.preventDefault();ADS_SHOW(g.dataset.go);}});
document.addEventListener('click',e=>{const h=e.target.closest('.acc-head');if(h)setTimeout(()=>ADS_ANIMATE(h.closest('.acc-item')),10);});
const fq=document.getElementById('fq');if(fq)fq.addEventListener('input',()=>{const q=fq.value.trim().toLowerCase();
  document.querySelectorAll('#fl .acc-item').forEach(it=>it.style.display=(!q||it.dataset.text.includes(q))?'':'none');});
</script>
</body></html>
"""
