"""Plain-language HTML report for the Windows (NTFS) date checks.

The command-line `analyze` writes report.md for examiners. This renders the same
results as one self-contained, tabbed page in the shared theme: an overview,
the flagged files (each a compact row that expands to its plain sentences and the
values behind them), candidate events, the health of the records themselves, and
how the checks work. No external fonts or scripts are loaded.
"""

import json
import os

from .config import RULE_IDS, load_config
from .explain import INDICATOR_PLAIN, rule_name, rule_what, say
from .rules import NOT_EVALUABLE, VIOLATED
from .theme import ICONS, THEME_CSS, THEME_JS, brand, credit

# Only files above the flag threshold θ are shown as flagged. Among them, "Look first" needs at least
# two independent checks disagreeing and a score of at least STRONG (or θ, if θ is set higher);
# every other flagged file is "Worth a look". Both tiers can therefore occur at any θ.
STRONG = 0.50
# A check that fires on at least this share of the files it could check is reported as a drive-wide
# pattern: it cannot single out files, but it says something about the whole drive.
DRIVE_WIDE = 0.90
DRIVE_WIDE_MIN = 50      # ...and only when it could check enough files for "nearly every file" to mean something


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


def _strong(theta):
    return max(float(theta), STRONG)


def _tier(f, theta):
    if f["score"] >= _strong(theta) and len(f["fired"]) >= 2:
        return "Look first", "hot"
    return "Worth a look", "warn"


def _sorted(v):
    """Dicts with their keys in order, all the way down, as outcomes.csv stores them (so a rebuilt page is identical)."""
    if isinstance(v, dict):
        return {k: _sorted(v[k]) for k in sorted(v)}
    if isinstance(v, (list, tuple)):
        return [_sorted(x) for x in v]
    return v


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
                          "tech": _sorted({k: v for k, v in d.items() if not k.startswith("_")})})
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


TEMPLATE = os.path.join(os.path.dirname(__file__), "date_template.html")


def page_template():
    """The report page with its fixed parts filled in; only /*__DATA__*/ is left for the results.

    The browser version uses this same page, so both write the same report."""
    with open(TEMPLATE, encoding="utf-8") as fh:
        page = fh.read()
    const = {"icons": ICONS, "RULE_TECH": RULE_TECH, "SOURCES": SOURCES, "STRONG": STRONG, "DRIVE_WIDE": DRIVE_WIDE,
             "DRIVE_WIDE_MIN": DRIVE_WIDE_MIN,
             "default_config": {k: v for k, v in load_config(None).items() if isinstance(v, (int, float, str))}}
    return (page.replace("/*__THEME_CSS__*/", THEME_CSS, 1).replace("/*__THEME_JS__*/", THEME_JS, 1)
            .replace("/*__BRAND__*/", brand("Date checks"), 1)
            .replace("/*__CREDIT__*/", credit("Read-only. This report points to files for an examiner to review; it does not by itself prove tampering."), 1)
            .replace("/*__CONST__*/null", _script_json(const), 1))


def _script_json(obj):
    # Paths come from the evidence: keep them inert inside the script element.
    return json.dumps(obj, ensure_ascii=False, default=str).replace("</", "<\\/").replace("<!--", "<\\!--")


def render(data):
    """The whole report page: the template plus this run's results. The page draws itself from the data."""
    return page_template().replace("/*__DATA__*/null", _script_json(data), 1)
