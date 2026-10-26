"""System-level indicators S1-S5 (Section III-E).

These do not accuse any file. They report that the evidence base has been
degraded so that "consistent" outcomes from the affected sources are read with
less confidence.
"""

from .loaders import payload_fields
from .timeutil import TICKS_PER_SECOND, fmt_ts, parse_ts

FIRED = "fired"
CLEAR = "clear"
NOT_EVALUABLE = "not_evaluable"


def _result(sid, name, status, times=(), **details):
    return {"id": sid, "name": name, "status": status, "times": sorted(t for t in times if t),
            "details": details}


def _install_time(ctx):
    if ctx.cfg.get("install_time"):
        return parse_ts(ctx.cfg["install_time"]), "config"
    rec = next((d for (e, _), d in ctx.mft.items() if e == 0), None)   # $MFT itself: volume format
    if rec:
        return rec["fn_c"] or rec["si_c"], "$MFT record 0 creation"
    return None, None


def _find(ctx, channel, ids, provider=None):
    out = []
    for e in ctx.events.get(channel, []):
        if e["event_id"] in ids and (provider is None or provider in (e["provider"] or "").lower()):
            out.append(e)
    return out


def s1_log_clearing(ctx):
    if not ctx.events.get("system") and not ctx.events.get("security"):
        return _result("S1", "Log clearing", NOT_EVALUABLE, reason="no System or Security log")
    hits = _find(ctx, "system", {104}) + _find(ctx, "security", {1102})
    return _result("S1", "Log clearing", FIRED if hits else CLEAR, [h["ts"] for h in hits],
                   events=[{"channel": h["channel"], "event_id": h["event_id"],
                            "time": fmt_ts(h["ts"]), "user": h["user"]} for h in hits])


def s2_journal_reset(ctx):
    app = ctx.events.get("application")
    if not app and not ctx.has_usn:
        return _result("S2", "Change journal reset", NOT_EVALUABLE, reason="no Application log and no $J")
    hits = _find(ctx, "application", {3079})
    times = [h["ts"] for h in hits]
    details = {"event_3079": [fmt_ts(h["ts"]) for h in hits]}
    fired = bool(hits)
    if ctx.has_usn:
        install, src = _install_time(ctx)
        timed = [u for u in ctx.usn_rows if u["ts"] is not None]
        first = min(timed, key=lambda u: u["ts"]) if timed else {"ts": None}
        min_usn = min((u["usn"] for u in ctx.usn_rows if u["usn"] is not None), default=None)
        details.update(journal_first_record=fmt_ts(first["ts"]), journal_min_usn=min_usn,
                       install_time=fmt_ts(install), install_time_source=src)
        if install is not None and first["ts"] is not None and min_usn is not None:
            gap_days = (first["ts"] - install) / TICKS_PER_SECOND / 86400
            details["journal_start_after_install_days"] = round(gap_days, 2)
            # A journal that never wrapped (low first USN) should reach back to installation.
            if gap_days > ctx.cfg["s2_journal_gap_days"] and min_usn < ctx.cfg["s2_unwrapped_usn_max"]:
                fired = True
                times.append(first["ts"])
                details["unwrapped_journal_starts_late"] = True
    else:
        details["note"] = "no $J input; journal-start test skipped"
    return _result("S2", "Change journal reset", FIRED if fired else CLEAR, times, **details)


def s3_log_discontinuity(ctx):
    if not ctx.events:
        return _result("S3", "Event log discontinuity", NOT_EVALUABLE, reason="no event logs")
    install, _ = _install_time(ctx)
    max_report = ctx.cfg["s3_max_gaps_reported"]
    gaps, times, oldest = [], [], []
    for channel, evs in ctx.events.items():
        recs = sorted((e["record_id"], e["ts"]) for e in evs if e["record_id"] is not None)
        for (r0, t0), (r1, t1) in zip(recs, recs[1:]):
            if r1 - r0 > 1:
                gaps.append({"channel": channel, "after_record": r0, "next_record": r1,
                             "missing": r1 - r0 - 1, "from": fmt_ts(t0), "to": fmt_ts(t1)})
                times.append(t1)
        # A log that has not reached its maximum size should reach back to installation.
        meta = {k.lower(): v for k, v in ctx.cfg.get("evtx_files", {}).items()}.get(channel)
        if meta and install and recs:
            first_ts = min(t for _, t in recs)
            gap_days = (first_ts - install) / TICKS_PER_SECOND / 86400
            if meta.get("size_bytes", 0) < 0.9 * meta.get("max_bytes", 0) and gap_days > ctx.cfg["s3_oldest_gap_days"]:
                oldest.append({"channel": channel, "oldest_entry": fmt_ts(first_ts),
                               "days_after_install": round(gap_days, 2), **meta})
                times.append(first_ts)
    fired = bool(gaps or oldest)
    return _result("S3", "Event log discontinuity", FIRED if fired else CLEAR, times,
                   record_gaps=gaps[:max_report], record_gaps_total=len(gaps),
                   oldest_entry_too_recent=oldest)


def s4_clock_change(ctx):
    if not ctx.events.get("system") and not ctx.events.get("security"):
        return _result("S4", "Clock change", NOT_EVALUABLE, reason="no System or Security log")
    hits = _find(ctx, "security", {4616}) + _find(ctx, "system", {1}, provider="kernel-general")
    min_shift = ctx.cfg["s4_min_shift_s"]
    changes, times = [], []
    for h in hits:
        f = payload_fields(h["payload"])
        old = parse_ts(f.get("PreviousTime") or f.get("OldTime"))
        new = parse_ts(f.get("NewTime"))
        shift = None if old is None or new is None else (new - old) / TICKS_PER_SECOND
        if shift is not None and abs(shift) < min_shift:
            continue   # routine time synchronisation
        changes.append({"channel": h["channel"], "event_id": h["event_id"], "time": fmt_ts(h["ts"]),
                        "old": fmt_ts(old), "new": fmt_ts(new),
                        "shift_s": None if shift is None else round(shift, 3)})
        times.append(h["ts"])
    return _result("S4", "Clock change", FIRED if changes else CLEAR, times,
                   changes=changes, min_shift_s=min_shift)


def s5_missing_artifacts(ctx):
    if not ctx.has_usn:
        return _result("S5", "Missing expected artifacts", NOT_EVALUABLE, reason="no $J data")
    loaded_pf = ctx.pf_names
    loaded_lnk = {(l["source_path"] or "").rsplit("\\", 1)[-1] for l in ctx.lnks}
    seen_pf, seen_lnk, deletes = {}, {}, []
    for u in ctx.usn_rows:
        name = (u["name"] or "").lower()
        if name.endswith(".pf"):
            seen_pf.setdefault(name, u["ts"])
        elif name.endswith(".lnk") and (u["path"] is None or "\\users\\" in u["path"]):
            seen_lnk.setdefault(name, u["ts"])
        else:
            continue
        if "filedelete" in u["reasons"].lower():
            deletes.append({"name": u["name"], "time": fmt_ts(u["ts"]), "_t": u["ts"]})
    missing_pf = sorted(n for n in seen_pf if n not in loaded_pf)
    missing_lnk = sorted(n for n in seen_lnk if n not in loaded_lnk)
    times = [d["_t"] for d in deletes if d["name"].lower() in set(missing_pf) | set(missing_lnk)]
    fired = bool(missing_pf or missing_lnk)
    return _result("S5", "Missing expected artifacts", FIRED if fired else CLEAR, times,
                   prefetch_in_journal_but_absent=missing_pf, lnk_in_journal_but_absent=missing_lnk,
                   deletions=[{k: v for k, v in d.items() if k != "_t"} for d in deletes])


INDICATORS = [s1_log_clearing, s2_journal_reset, s3_log_discontinuity, s4_clock_change,
              s5_missing_artifacts]


def evaluate_indicators(ctx):
    return [fn(ctx) for fn in INDICATORS]
