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
    "R4": ("A shortcut was opened after the file's last-opened date",
           "A shortcut records the file being opened later than the file's own last-opened date."),
    "R5": ("The file changed while nobody was logged on",
           "The file's dates fall outside every logged-on session in the event log."),
    "R6": ("The visible date is older than the protected copy",
           "The creation date Windows shows is earlier than the file system's own protected copy."),
    "R7": ("The date was set to a round number",
           "The date falls exactly on a whole second, which ordinary activity almost never produces."),
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


_MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def nice(ts):
    """'2026-10-10 09:25:03.5555555' -> '10 Oct 2026, 09:25:03 UTC'. Other values pass through.

    Every time ADS stores is UTC; the exact value stays in the technical detail.
    """
    t = str(ts or "")
    try:
        date, clock = t.split(" ")[:2]
        y, m, d = date.split("-")
        return "%d %s %s, %s UTC" % (int(d), _MONTHS[int(m) - 1], y, clock.split(".")[0])
    except (ValueError, IndexError):
        return t or "?"


def _which(fields, one, many):
    """['si_c', 'si_m'] -> 'created and last-changed dates' (plain names, joined, pluralized)."""
    names = [f.replace("si_c", "created").replace("si_m", "last-changed") for f in fields]
    if not names:
        return many.replace("@", "created or last-changed")
    return (many if len(names) > 1 else one).replace("@", " and ".join(names))


def _g(d, *keys):
    for k in keys:
        if d.get(k) not in (None, ""):
            return d[k]
    return "?"


def say(rid, d):
    """One plain sentence explaining a violated outcome, from its detail values."""
    n = lambda *k: nice(_g(d, *k))   # noqa: E731  a date from the details, in plain form
    try:
        if rid == "R1":
            return ("Windows' change journal last recorded a change to this file at %s, but the file's own "
                    "record claims it last changed at %s, before the journal's entry." % (n("bic_time"), n("si_e")))
        if rid == "R2":
            return ("A shortcut to this file carries the last-change date %s, but the file itself says %s. "
                    "The two are written together and should match." % (n("lnk_si_e"), n("target_si_e")))
        if rid == "R3":
            bad = d.get("lnks_earlier") or [{}]
            return ("A shortcut to this file was created at %s, before the file it points to claims to have "
                    "existed (%s). A shortcut cannot be made before its target."
                    % (nice(_g(bad[0], "lnk_si_c")), n("target_si_c")))
        if rid == "R4":
            return ("A shortcut records this file being opened at %s, later than the file's own last-opened "
                    "date of %s." % (n("lnk_si_a"), n("target_si_a")))
        if rid == "R5":
            return ("The file's %s outside every time a user was logged on, according to the event log. Files "
                    "normally change only while someone is signed in."
                    % _which(d.get("outside_session", []), "@ date falls", "@ dates fall"))
        if rid == "R6":
            return ("The creation date Windows shows (%s) is earlier than the file system's own protected copy "
                    "(%s). The visible date was likely set back." % (n("si_c"), n("fn_c")))
        if rid == "R7":
            return ("The file's %s exactly on a whole second, with no fraction of a second at all. Real activity "
                    "almost never does that, but date-changing tools commonly do."
                    % _which(d.get("zero_fields", []), "@ date is", "@ dates are"))
        if rid == "R8":
            return ("Windows' change journal first recorded this file being created at %s, after the creation "
                    "date it now shows (%s). A file cannot be created after it already existed."
                    % (n("filecreate_time"), n("si_c")))
        if rid == "R9":
            bad = d.get("mismatches") or [{}]
            return ("A shortcut kept an earlier copy of this file's creation date (%s) that no longer matches the "
                    "file's current creation date (%s)." % (nice(_g(bad[0], "embedded_target_c")), n("target_si_c")))
        if rid == "R10":
            hit = (d.get("coinciding_executions") or [{}])[0]
            return ("This file's date changed at %s, the same moment the program %s ran, a program not normally "
                    "associated with this file." % (nice(_g(hit, "bic_time")), _g(hit, "exe")))
        if rid == "R11":
            return ("This file claims to have been created about %s days before the files whose records sit next "
                    "to it on the disk, which usually means its date was set back."
                    % _days(_g(d, "older_than_neighbors_days")))
    except Exception:
        pass
    return rule_what(rid)


def _days(v):
    try:
        return format(int(round(float(v))), ",")
    except (TypeError, ValueError):
        return str(v)
