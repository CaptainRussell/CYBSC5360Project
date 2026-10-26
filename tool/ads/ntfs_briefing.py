"""Plain-language HTML report for the Windows (NTFS) date checks.

The command-line `analyze` writes report.md for examiners. This renders the same
results as one self-contained, tabbed page in the shared theme: an overview,
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
from .config import load_config
from .theme import THEME_CSS, THEME_JS, brand, credit, icon

# Only files above the flag threshold θ are shown as flagged. Among them, "Look first" needs at least
# two independent checks disagreeing and a score of at least STRONG (or θ, if θ is set higher);
# every other flagged file is "Worth a look". Both tiers can therefore occur at any θ.
STRONG = 0.50
# A check that fires on at least this share of the files it could check is reported as a drive-wide
# pattern: it cannot single out files, but it says something about the whole drive.
DRIVE_WIDE = 0.90
DRIVE_WIDE_MIN = 50      # ...and only when it could check enough files for "nearly every file" to mean something
_TS = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?")


# What each date check does inside the tool, step by step. {names} come from the run's settings.
RULE_TECH = {
    "R1": ["Windows logs every change to a file's details in the change journal ($UsnJrnl:$J) as a <b>BasicInfoChange</b> entry, stamped with the journal's own clock.",
           "The file's record-changed date ($STANDARD_INFORMATION, “E”) is the moment its details last changed, so it should be at or after the latest such journal entry.",
           "If it is earlier by more than {tau_journal_s:g} seconds, the date was set back after the change was logged."],
    "R2": ["Find the shortcuts (.lnk files) that point to this file: first by the MFT record number stored inside the shortcut, otherwise by its path.",
           "Take the most recently changed shortcut and compare its own record-changed date with the file's.",
           "A gap of more than {tau_lnk_s:g} seconds means one of the two was changed separately."],
    "R3": ["A shortcut can only be made after the file it points to exists.",
           "So every shortcut's created date must be at or after the file's visible created date (allowing {tau_lnk_s:g} seconds).",
           "A shortcut older than its file means the file's created date was moved later, or the shortcut's earlier."],
    "R4": ["Opening a file through its shortcut opens the file too.",
           "So the most recent shortcut's last-opened date should be at or before the file's own last-opened date (allowing {tau_lnk_s:g} seconds).",
           "A shortcut opened after the file's last-opened date means the file's date was set back."],
    "R5": ["Rebuild user sessions from the System event log: logon (event 7001) to logoff (7002), cut short by start-up and shutdown events (6005, 6006, 6008, 41).",
           "The file's visible created and modified dates should fall inside a session (allowing {tau_session_s:g} seconds).",
           "Dates outside the period the log covers are not judged."],
    "R6": ["Each file's MFT record keeps its created date twice: in <b>$STANDARD_INFORMATION</b>, which Explorer shows and any program can change, and in <b>$FILE_NAME</b>, which Windows itself writes when the file is created, moved or renamed.",
           "Date-changing tools usually change only the first.",
           "So the visible created date should never be earlier than the protected $FILE_NAME copy."],
    "R7": ["NTFS dates count in steps of 100 nanoseconds, seven digits after the second, so a real date almost never ends in exactly .0000000.",
           "Many date-changing tools write whole seconds.",
           "If the visible created or modified date has all seven sub-second digits zero, the check finds something."],
    "R8": ["The change journal records the moment the file was created (a <b>FileCreate</b> entry).",
           "The visible created date should match it within {tau_journal_s:g} seconds.",
           "Exception: NTFS “tunneling”. When a file is deleted or renamed and a new file takes the same name in the same folder within {tunneling_window_s:g} seconds, Windows deliberately copies the old created date, so that case is not counted."],
    "R9": ["Every shortcut stores a copy of its target's created date, taken when the shortcut was made.",
           "That copy should match the file's current visible created date (within {tau_lnk_s:g} seconds).",
           "If it does not, the file's created date changed after the shortcut was made."],
    "R10": ["For every BasicInfoChange in the journal, look for programs that ran (from Prefetch) within {tau_prefetch_s:g} seconds of it.",
            "Ignore Windows' own background programs (Explorer, search indexing, Defender and similar) and programs that routinely open this file (it is in their list of files loaded and they ran {r10_min_assoc_runs} or more times).",
            "Any program left over, such as a date-changing tool, makes the check find something."],
    "R11": ["Windows hands out MFT record numbers roughly in order, so records next to each other were usually created around the same time.",
            "Compare the file's visible created date with the middle (median) created date of its {r11_neighbors} neighbors on each side.",
            "If it is more than {r11_delta_days:g} days older, it claims an age its position does not support."],
}
SOURCES = [("$MFT · $STANDARD_INFORMATION", "the four dates Explorer shows; any program can change them", "R1 R2 R3 R4 R5 R6 R7 R8 R9 R11"),
           ("$MFT · $FILE_NAME", "a protected copy written by Windows itself", "R6"),
           ("Change journal ($J)", "a log of every change, with its own clock", "R1 R8 R10"),
           ("Shortcuts (.lnk)", "made when a file is opened; keep copies of its dates", "R2 R3 R4 R9"),
           ("Prefetch", "which programs ran, and when", "R10"),
           ("Event logs", "when someone was logged on", "R5")]


def _tech(rid, cfg):
    try:
        return [t.format(**cfg) for t in RULE_TECH.get(rid, [])]
    except (KeyError, ValueError):
        return [t.format(**load_config(None)) for t in RULE_TECH.get(rid, [])]


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
        "config": {k: v for k, v in (meta.get("config") or load_config(None)).items() if isinstance(v, (int, float, str))},
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
        act_rows += ('<div class="cbar" data-nav="how" data-target="#q-{rid}" data-tip="<b>{rid} {name}</b><br>{what}"><span class="cic">{ic}</span><div><div class="nm">{rid} · {name}</div>'
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

    cfg = d.get("config") or load_config(None)
    rules = "".join(('<div class="acc-item" style="margin:0" id="q-{rid}"><button class="acc-head"><span class="cic">{ic}</span><div style="flex:1;min-width:0">'
                     '<b>{rid} · {name}</b><div class="note">{what}</div></div><span class="chip"><b>{vi}</b>&nbsp;files</span>{chev}</button>'
                     '<div class="acc-body"><div><div class="acc-inner"><div class="capx">How the tool checks it</div><ol class="tech-steps">{steps}</ol>'
                     '<div class="math"><b>On this drive:</b> could check {ev} files, found a disagreement in {vi}.</div></div></div></div></div>'
                     ).format(ic=icon("time"), rid=rid, name=_esc(r["name"]), what=_esc(r["what"]), chev=_chev(),
                              steps="".join("<li><div>%s</div></li>" % t for t in _tech(rid, cfg)),
                              ev=format(d.get("activity", {}).get(rid, {}).get("evaluable", 0), ","),
                              vi=format(d.get("activity", {}).get(rid, {}).get("violated", 0), ","))
                    for rid, r in d["rules"].items())
    sources = "".join('<div class="src"><b>%s</b><span>%s</span><div>%s</div></div>'
                      % (_esc(n), _esc(w), "".join('<span class="chip" data-nav="how" data-target="#q-%s"><b>%s</b></span>' % (x, x) for x in used.split()))
                      for n, w, used in SOURCES)
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
        '<section class="panel" id="p-overview"><div class="ph"><div><h2>Overview</h2><div class="sub">All times are UTC.</div></div>'
        '<div class="note">Click any number to go to its files.</div></div><div class="grid g4">'
        '<div class="card kpi acc" data-nav="how" data-target="#rules"><span class="go">open ›</span><div class="v" data-count="{scored_n}">0</div><div class="l">files checked</div></div>'
        '<div class="card kpi warn" data-nav="flagged"><span class="go">open ›</span><div class="v" data-count="{flagged}">0</div><div class="l">flagged</div></div>'
        '<div class="card kpi hot" data-nav="flagged"><span class="go">open ›</span><div class="v" data-count="{look}">0</div><div class="l">look first</div></div>'
        '<div class="card kpi {syscls}" data-nav="records"><span class="go">open ›</span><div class="v" data-count="{sys}">0</div><div class="l">record damage /100</div></div></div>'
        '{wide}<div class="grid g2" style="margin-top:14px"><div class="card"><h3>Check activity</h3>{act}'
        '<div class="note" style="margin-top:6px">How often each date check found a disagreement. Click a check to see how it works.</div></div>'
        '<div class="card"><h3>Top flagged files</h3>{tops}<p class="note" style="margin-top:8px">{recnote}</p></div></div></section>'
        '<section class="panel" id="p-flagged"><div class="ph"><div><h2>Flagged files</h2><div class="sub">Files whose own records '
        'disagree. Open one to see why.</div></div></div><div class="toolbar"><label class="search">{sic}<input id="fq" '
        'placeholder="Search path" aria-label="Search flagged files"></label></div><div id="fl">{leads}</div></section>'
        '<section class="panel" id="p-events"><div class="ph"><div><h2>Events</h2><div class="sub">Flagged files changed within '
        'minutes of each other.</div></div></div>{events}</section>'
        '<section class="panel" id="p-records"><div class="ph"><div><h2>Records</h2><div class="sub">Were the records themselves '
        'cleared, reset or removed?</div></div></div><div class="grid g2">{recs}</div></section>'
        '<section class="panel" id="p-how"><div class="ph"><div><h2>How it works</h2><div class="sub">Eleven checks compare the '
        'dates Windows keeps in different places. Open a check to see exactly what the tool does.</div></div></div>'
        '<div class="card"><h3>Where the dates come from</h3><div class="srcs">{sources}</div>'
        '<div class="note" style="margin-top:8px">One file, several witnesses. Changing a date in one place is easy; changing it '
        'consistently in all of them is not. Each check compares two witnesses.</div></div>'
        '<h3 style="margin:22px 0 10px;font-size:15px" id="rules">The eleven checks</h3><div class="grid g2" style="align-items:start">{rules}</div>'
        '<div class="grid g2" style="margin-top:14px"><div class="card"><h3>The score</h3><p>The weighted share of checks that '
        'found a disagreement, out of 100. Flagged above {theta}; “Look first” at {strong}+ with two or more checks.</p>'
        '<dl class="kv"><dt>Weighting</dt><dd>{mode}</dd><dt>Rates from</dt><dd>{cal}</dd></dl></div>'
        '<div class="card"><h3>Inputs</h3><div class="scroll-x"><table class="t"><thead><tr><th>Record</th><th>File</th>'
        '<th class="num">Rows</th><th>SHA-256</th></tr></thead><tbody>{inputs}</tbody></table></div></div></div></section>'
    ).format(scored=format(c["scored"], ","), scored_n=c["scored"], flagged=c["flagged"], look=c["look_first"], sys=sysd["score"],
             syscls="hot" if sysd["level"] != "clear" else "ok", wide=wide_html, act=act_rows, tops=tops or '<div class="empty">None.</div>',
             recnote=_esc(rec_note), sic=icon("search"), leads=leads, events=events, recs=recs, rules=rules, theta=theta100,
             strong=int(round(_strong(d["theta"]) * 100)), mode=_esc(d["weight_mode"]), cal=_esc(d.get("calibration") or "defaults"),
             inputs=inputs, sources=sources)

    return PAGE.replace("@css@", THEME_CSS).replace("@js@", THEME_JS).replace("@tabs@", tabbar).replace("@body@", body) \
        .replace("@generated@", _esc(d["generated"])).replace("@sun@", icon("sun")).replace("@print@", icon("print")) \
        .replace("@brand@", brand("Date checks")).replace("@credit@", credit("Read-only. This report points to files for an examiner to review; it does not by itself prove tampering."))


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Artifact Disagreement Scorer · Date Checks</title>
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
.card.kpi .go{position:absolute;top:12px;right:12px;font:700 11px var(--mono);color:var(--dim);opacity:0;transition:opacity .15s}
.card.kpi[data-nav]:hover .go{opacity:1;color:var(--accent-ink)}
.cbar[data-nav]:hover{background:var(--panel2)}
.srcs{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
.src{border:1px solid var(--line);border-radius:10px;padding:10px;background:var(--panel2);display:grid;gap:4px}
.src b{font:700 13px var(--mono);color:var(--accent-ink)}.src span{font-size:13px;color:var(--muted)}.src div{display:flex;gap:4px;flex-wrap:wrap}
@media (max-width:760px){.srcs{grid-template-columns:minmax(0,1fr)}}
.capx{font:700 11px var(--ui);letter-spacing:.07em;text-transform:uppercase;color:var(--dim);margin-top:12px}
.tech-steps{counter-reset:st;margin:10px 0 0;padding:0;display:grid;gap:8px}
.tech-steps li{list-style:none;display:grid;grid-template-columns:24px 1fr;gap:10px;font-size:14px}
.tech-steps li::before{counter-increment:st;content:counter(st);width:22px;height:22px;border-radius:50%;display:grid;place-items:center;background:var(--accent2-soft);color:var(--accent2);font:700 11px var(--mono)}
.math{font:12px var(--mono);color:var(--muted);background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:8px 10px;margin-top:10px}
.math b{color:var(--text)}
@media (max-width:760px){.lead-row{grid-template-columns:34px 70px minmax(0,1fr) 18px}.lead-row .cicons,.lead-row .badge{display:none}
  .checks11{grid-template-columns:repeat(6,minmax(0,1fr))}.cbar{grid-template-columns:30px minmax(0,1fr)}.cbar .note{grid-column:2}}
</style></head><body>
<header class="top"><div class="wrap">@brand@
<div class="case"><span class="pill acc">NTFS</span><span class="pill hide-s">@generated@</span></div><div class="spacer"></div>
<button class="iconbtn" data-act="theme" title="Light or dark">@sun@</button><button class="iconbtn" data-act="print" title="Print every tab">@print@</button></div></header>
<nav class="tabs" aria-label="Report sections"><div class="wrap">@tabs@</div></nav>
<main class="wrap">@body@</main>
<footer class="foot"><div class="wrap">@credit@</div></footer>
<script>@js@</script>
<script>
document.addEventListener('click',e=>{const g=e.target.closest('[data-go]');if(g){e.preventDefault();ADS_SHOW(g.dataset.go);}});
document.addEventListener('click',e=>{const h=e.target.closest('.acc-head');if(h)setTimeout(()=>ADS_ANIMATE(h.closest('.acc-item')),10);});
const fq=document.getElementById('fq');if(fq)fq.addEventListener('input',()=>{const q=fq.value.trim().toLowerCase();
  document.querySelectorAll('#fl .acc-item').forEach(it=>it.style.display=(!q||it.dataset.text.includes(q))?'':'none');});
</script>
</body></html>
"""
