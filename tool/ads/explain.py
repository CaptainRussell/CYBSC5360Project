"""Plain-language wording for the Windows (NTFS) rules and system warnings.

The rules in rules.py and indicators.py return exact values for an examiner.
This module turns a *violated* outcome into one sentence a non-specialist can
read, and gives each rule a short plain name and a one-line description of what
it checks. It never changes a decision; it only describes one.
"""

# Short plain name, and what the rule checks, for every rule.
RULE_PLAIN = {
    "R1": ("Record-change date is before the journal's own entry",
           "The file's record says it last changed before Windows' change journal recorded that change."),
    "R2": ("A shortcut disagrees on the last-change date",
           "A shortcut pointing at the file carries a different last-change date from the file itself."),
    "R3": ("A shortcut is older than the file it points to",
           "A shortcut was created before the file it points to claims to have existed."),
    "R4": ("A shortcut was used before the file was opened",
           "A shortcut records the file being opened later than the file's own last-opened date."),
    "R5": ("The file changed while nobody was logged on",
           "The file's dates fall outside every logged-on session in the event log."),
    "R6": ("The visible date is older than the protected copy",
           "The creation date Windows shows is earlier than the file system's own protected copy."),
    "R7": ("The date was set to a round number",
           "The date ends in exactly .0000000 seconds, which ordinary activity almost never produces."),
    "R8": ("The file was created later than its visible date",
           "The change journal first recorded the file being created after the date it now shows."),
    "R9": ("A shortcut remembers a different creation date",
           "A shortcut kept an older copy of the file's creation date that no longer matches."),
    "R10": ("The date changed as an unusual program ran",
            "The file's date changed at the same moment a program not associated with it ran."),
    "R11": ("It claims to be much older than its neighbors",
            "The file claims to pre-date the files whose records sit next to it on the disk."),
}

INDICATOR_PLAIN = {
    "S1": "An event log was cleared, so some activity can no longer be checked.",
    "S2": "The change journal was reset or deleted, so some creation and change records are gone.",
    "S3": "The event log has gaps in its numbering, so entries may have been removed.",
    "S4": "The system clock was changed, which makes every date on the drive less trustworthy.",
    "S5": "Records that should exist are missing (files opened with no shortcut, or programs run with no Prefetch).",
}


def rule_name(rid):
    return RULE_PLAIN.get(rid, (rid, ""))[0]


def rule_what(rid):
    return RULE_PLAIN.get(rid, ("", ""))[1]


def _g(d, *keys):
    for k in keys:
        if d.get(k) not in (None, ""):
            return d[k]
    return "?"


def say(rid, d):
    """One plain sentence explaining a violated outcome, from its detail values."""
    try:
        if rid == "R1":
            return ("Windows' change journal last recorded a change to this file at %s, but the file's own "
                    "record claims it last changed at %s — before the journal's entry." % (_g(d, "bic_time"), _g(d, "si_e")))
        if rid == "R2":
            return ("A shortcut to this file carries the last-change date %s, but the file itself says %s. "
                    "The two are written together and should match." % (_g(d, "lnk_si_e"), _g(d, "target_si_e")))
        if rid == "R3":
            bad = d.get("lnks_earlier") or [{}]
            return ("A shortcut to this file was created at %s, before the file it points to claims to have "
                    "existed (%s). A shortcut cannot be made before its target." % (_g(bad[0], "lnk_si_c"), _g(d, "target_si_c")))
        if rid == "R4":
            return ("A shortcut records this file being opened at %s, later than the file's own last-opened "
                    "date of %s." % (_g(d, "lnk_si_a"), _g(d, "target_si_a")))
        if rid == "R5":
            which = " and ".join(f.replace("si_c", "created").replace("si_m", "last-changed") for f in d.get("outside_session", []))
            return ("The file's %s date falls outside every time a user was logged on, according to the event "
                    "log. Files normally change only while someone is signed in." % (which or "created/changed"))
        if rid == "R6":
            return ("The creation date Windows shows (%s) is earlier than the file system's own protected copy "
                    "(%s). The visible date was likely set back." % (_g(d, "si_c"), _g(d, "fn_c")))
        if rid == "R7":
            z = ", ".join(k.replace("si_c", "created").replace("si_m", "last-changed") for k in d.get("zero_fields", []))
            return ("The file's %s date ends in exactly .0000000 seconds. Real activity almost never lands on a "
                    "whole second, but date-changing tools commonly do." % (z or "created/changed"))
        if rid == "R8":
            return ("Windows' change journal first recorded this file being created at %s, after the creation "
                    "date it now shows (%s). A file cannot be created after it already existed." % (
                        _g(d, "filecreate_time"), _g(d, "si_c")))
        if rid == "R9":
            bad = d.get("mismatches") or [{}]
            return ("A shortcut kept an earlier copy of this file's creation date (%s) that no longer matches the "
                    "file's current creation date (%s)." % (_g(bad[0], "embedded_target_c"), _g(d, "target_si_c")))
        if rid == "R10":
            hit = (d.get("coinciding_executions") or [{}])[0]
            return ("This file's date changed at %s, the same moment the program %s ran — a program not normally "
                    "associated with this file." % (_g(hit, "bic_time"), _g(hit, "exe")))
        if rid == "R11":
            return ("This file claims to have been created about %s days before the files whose records sit next "
                    "to it on the disk, which usually means its date was set back." % (_g(d, "older_than_neighbors_days")))
    except Exception:
        pass
    return rule_what(rid)
