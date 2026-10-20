"""Consistency rules R1-R11 (Section III-D, Table II).

Each rule is a self-contained function taking the analysis context and a file
key (MFT entry, sequence) and returning (outcome, details). The outcome is one
of CONSISTENT, VIOLATED or NOT_EVALUABLE; details holds the raw values compared
so every flag can be explained.
"""

import bisect
from collections import defaultdict

from . import paths
from .timeutil import TICKS_PER_SECOND, diff_seconds, fmt_ts, seconds, subsecond

CONSISTENT = "consistent"
VIOLATED = "violated"
NOT_EVALUABLE = "not_evaluable"


def _has(reasons, flag):
    return flag in reasons.lower()


class Context:
    """Everything the rules need, loaded once from the case database."""

    def __init__(self, con, cfg):
        self.cfg = cfg
        self.con = con
        self.mft = {}
        self.path_index = defaultdict(list)
        for r in con.execute("SELECT * FROM mft"):
            d = dict(r)
            key = (d["entry"], d["seq"])
            self.mft[key] = d
            if d["path"]:
                self.path_index[d["path"]].append(key)
        self.candidates = sorted(
            k for k, d in self.mft.items()
            if d["in_use"] and not d["is_dir"] and k[0] >= cfg["min_entry"]
        )

        self.usn_by_key = defaultdict(list)
        self.usn_rows = [dict(r) for r in con.execute("SELECT * FROM usn ORDER BY ts, usn")]
        for u in self.usn_rows:
            self.usn_by_key[(u["entry"], u["seq"])].append(u)
        self.has_usn = bool(self.usn_rows)

        self._load_lnk()
        self._load_prefetch()
        self._load_events()

    # ---- joins -------------------------------------------------------------

    def resolve_path(self, path):
        """Path -> in-use MFT key, trying anchor suffixes for mounted-image paths."""
        for p in [path] + paths.anchor_suffixes(path):
            keys = [k for k in self.path_index.get(p, []) if self.mft[k]["in_use"]]
            if keys:
                return max(keys, key=lambda k: k[1])
        return None

    def _load_lnk(self):
        self.lnks = []
        self.lnks_by_target = defaultdict(list)
        self.lnk_unresolved = 0
        for r in self.con.execute("SELECT * FROM lnk"):
            d = dict(r)
            d["own_key"] = self.resolve_path(d["source_path"])
            target_key, how = None, None
            if d["target_entry"] is not None:
                k = (d["target_entry"], d["target_seq"])
                if k in self.mft:
                    target_key, how = k, "mft_reference"
                elif any(e == d["target_entry"] for e, _ in self.mft):
                    how = "sequence_mismatch"   # record reused since the link was written
            if target_key is None and how is None and d["target_path"]:
                target_key = self.resolve_path(d["target_path"])
                how = "path" if target_key else None
            d["target_key"], d["join"] = target_key, how
            self.lnks.append(d)
            if target_key:
                self.lnks_by_target[target_key].append(d)
            else:
                self.lnk_unresolved += 1

    def _load_prefetch(self):
        self.pf_runs = sorted(
            (r["run_time"], r["exe"], r["pf_name"])
            for r in self.con.execute("SELECT * FROM pf_runs"))
        self.pf_run_times = [r[0] for r in self.pf_runs]
        self.pf_files = defaultdict(set)
        for r in self.con.execute("SELECT exe, path FROM pf_files"):
            self.pf_files[r["exe"]].add(r["path"])
        self.pf_run_count = defaultdict(int)
        self.pf_names = set()
        for r in self.con.execute("SELECT * FROM pf"):
            self.pf_run_count[r["exe"]] = max(self.pf_run_count[r["exe"]], r["run_count"] or 0)
            self.pf_names.add(r["pf_name"])
        self.has_prefetch = bool(self.pf_names)

    def pf_runs_between(self, start, end):
        i = bisect.bisect_left(self.pf_run_times, start)
        j = bisect.bisect_right(self.pf_run_times, end)
        return self.pf_runs[i:j]

    def _load_events(self):
        self.events = defaultdict(list)
        for r in self.con.execute("SELECT * FROM events WHERE ts IS NOT NULL ORDER BY ts, record_id"):
            self.events[r["channel"].lower()].append(dict(r))
        system = self.events.get("system", [])
        self.system_coverage = (system[0]["ts"], system[-1]["ts"]) if system else None
        self.sessions = self._build_sessions(system)

    def _build_sessions(self, system):
        """User sessions from Winlogon 7001/7002, closed early by boot/shutdown events."""
        starts = set(self.cfg["session_start_ids"])
        ends = set(self.cfg["session_end_ids"])
        resets = set(self.cfg["boot_shutdown_ids"])
        if not any(e["event_id"] in starts for e in system):
            return None
        open_by_user, sessions = {}, []
        for e in system:
            eid, user = e["event_id"], e["user"] or "any"
            if eid in starts:
                open_by_user.setdefault(user, e["ts"])
            elif eid in ends:
                if user in open_by_user:
                    sessions.append((open_by_user.pop(user), e["ts"]))
                elif "any" in open_by_user:
                    sessions.append((open_by_user.pop("any"), e["ts"]))
            elif eid in resets:
                for u, t in list(open_by_user.items()):
                    sessions.append((t, e["ts"]))
                open_by_user.clear()
        end = self.system_coverage[1]
        sessions.extend((t, end) for t in open_by_user.values())
        return sorted(sessions)

    def most_recent_lnk(self, lnks):
        def mtime(l):
            own = self.mft.get(l["own_key"]) if l["own_key"] else None
            return (own["si_m"] if own else None) or l["src_m"] or 0
        return max(lnks, key=mtime)

    def lnk_own_times(self, lnk):
        """The LNK file's own SIA times: from its MFT record, else LECmd's Source* times.

        LECmd does not report the LNK's SIA-E, so R2 needs the MFT record.
        """
        own = self.mft.get(lnk["own_key"]) if lnk["own_key"] else None
        if own:
            return {"c": own["si_c"], "m": own["si_m"], "a": own["si_a"], "e": own["si_e"], "from": "mft"}
        return {"c": lnk["src_c"], "m": lnk["src_m"], "a": lnk["src_a"], "e": None, "from": "lecmd"}


def _ne(reason, **extra):
    d = {"reason": reason}
    d.update(extra)
    return NOT_EVALUABLE, d


# ---- R1-R11 ---------------------------------------------------------------


def r1(ctx, key):
    """SIA-E is within tolerance of the most recent BASIC_INFO_CHANGE in $J."""
    if not ctx.has_usn:
        return _ne("no $J data")
    f = ctx.mft[key]
    bics = [u for u in ctx.usn_by_key.get(key, []) if _has(u["reasons"], "basicinfochange")]
    if not bics:
        return _ne("no BasicInfoChange record for file in $J")
    if f["si_e"] is None:
        return _ne("SIA-E missing")
    last = max(bics, key=lambda u: u["ts"])
    diff = diff_seconds(f["si_e"], last["ts"])
    tau = ctx.cfg["tau_journal_s"]
    bad = abs(diff) > tau if ctx.cfg["r1_two_sided"] else diff < -tau
    return (VIOLATED if bad else CONSISTENT), {
        "si_e": fmt_ts(f["si_e"]), "bic_time": fmt_ts(last["ts"]), "bic_usn": last["usn"],
        "si_e_minus_bic_s": round(diff, 3), "tolerance_s": tau, "_evidence_time": last["ts"],
    }


def _lnk_pairs(ctx, key):
    return ctx.lnks_by_target.get(key)


def r2(ctx, key):
    """A LNK file's SIA-E matches the SIA-E of its target (most recent LNK)."""
    lnks = _lnk_pairs(ctx, key)
    if not lnks:
        return _ne("no LNK file references this file")
    lnk = ctx.most_recent_lnk(lnks)
    own = ctx.lnk_own_times(lnk)
    if own["e"] is None:
        return _ne("LNK file's own MFT record not found (SIA-E unavailable)", lnk=lnk["source_file"])
    t = ctx.mft[key]
    diff = diff_seconds(own["e"], t["si_e"])
    tau = ctx.cfg["tau_lnk_s"]
    return (VIOLATED if abs(diff) > tau else CONSISTENT), {
        "lnk": lnk["source_file"], "lnk_si_e": fmt_ts(own["e"]), "target_si_e": fmt_ts(t["si_e"]),
        "diff_s": round(diff, 3), "tolerance_s": tau, "join": lnk["join"],
    }


def r3(ctx, key):
    """Every LNK file's SIA-C is equal to or later than its target's SIA-C."""
    lnks = _lnk_pairs(ctx, key)
    if not lnks:
        return _ne("no LNK file references this file")
    t = ctx.mft[key]
    tau = seconds(ctx.cfg["tau_lnk_s"])
    checked, bad = [], []
    for lnk in lnks:
        own = ctx.lnk_own_times(lnk)
        if own["c"] is None:
            continue
        checked.append(lnk["source_file"])
        if own["c"] < t["si_c"] - tau:
            bad.append({"lnk": lnk["source_file"], "lnk_si_c": fmt_ts(own["c"])})
    if not checked:
        return _ne("LNK creation time unavailable")
    return (VIOLATED if bad else CONSISTENT), {
        "target_si_c": fmt_ts(t["si_c"]), "lnks_checked": len(checked), "lnks_earlier": bad,
    }


def r4(ctx, key):
    """The most recent LNK file's SIA-A is equal to or earlier than its target's SIA-A."""
    lnks = _lnk_pairs(ctx, key)
    if not lnks:
        return _ne("no LNK file references this file")
    lnk = ctx.most_recent_lnk(lnks)
    own = ctx.lnk_own_times(lnk)
    t = ctx.mft[key]
    if own["a"] is None or t["si_a"] is None:
        return _ne("access time unavailable")
    diff = diff_seconds(own["a"], t["si_a"])
    tau = ctx.cfg["tau_lnk_s"]
    return (VIOLATED if diff > tau else CONSISTENT), {
        "lnk": lnk["source_file"], "lnk_si_a": fmt_ts(own["a"]), "target_si_a": fmt_ts(t["si_a"]),
        "lnk_minus_target_s": round(diff, 3), "tolerance_s": tau, "lnk_times_from": own["from"],
    }


def r5(ctx, key):
    """SIA-C and SIA-M fall within a recorded user session (System 7001/7002)."""
    if ctx.sessions is None:
        return _ne("no user session events in System log")
    lo, hi = ctx.system_coverage
    tau = seconds(ctx.cfg["tau_session_s"])
    f = ctx.mft[key]
    checked, outside, skipped = {}, [], []
    for field in ("si_c", "si_m"):
        t = f[field]
        if t is None:
            continue
        if not (lo <= t <= hi):
            skipped.append(field)
            continue
        inside = any(s - tau <= t <= e + tau for s, e in ctx.sessions)
        checked[field] = fmt_ts(t)
        if not inside:
            outside.append(field)
    if not checked:
        return _ne("timestamps fall outside System log coverage",
                   coverage=[fmt_ts(lo), fmt_ts(hi)], skipped=skipped)
    return (VIOLATED if outside else CONSISTENT), {
        "checked": checked, "outside_session": outside, "outside_log_coverage": skipped,
        "sessions": len(ctx.sessions),
    }


def r6(ctx, key):
    """SIA-C is not earlier than FNA-C."""
    f = ctx.mft[key]
    if f["si_c"] is None or f["fn_c"] is None:
        return _ne("SIA-C or FNA-C missing")
    diff = diff_seconds(f["si_c"], f["fn_c"])
    return (VIOLATED if diff < -ctx.cfg["tau_mft_s"] else CONSISTENT), {
        "si_c": fmt_ts(f["si_c"]), "fn_c": fmt_ts(f["fn_c"]), "si_minus_fn_s": round(diff, 3),
    }


def r7(ctx, key):
    """SIA timestamps do not have an all-zero sub-second field."""
    f = ctx.mft[key]
    fields = ctx.cfg["r7_fields"]
    vals = {k: f[k] for k in fields if f.get(k) is not None}
    if not vals:
        return _ne("SIA timestamps missing")
    zero = [k for k, v in vals.items() if subsecond(v) == 0]
    return (VIOLATED if zero else CONSISTENT), {
        "subsecond": {k: "%07d" % subsecond(v) for k, v in vals.items()}, "zero_fields": zero,
    }


def _tunneling_explains(ctx, key, records):
    """Details if the file's name was freed by another record shortly before it appeared.

    NTFS tunneling then copies the old creation time onto the new file.
    """
    window = seconds(ctx.cfg["tunneling_window_s"])
    if not hasattr(ctx, "_name_freed"):
        ctx._name_freed = defaultdict(list)
        for u in ctx.usn_rows:
            if _has(u["reasons"], "filedelete") or _has(u["reasons"], "renameoldname"):
                ctx._name_freed[(u["parent_entry"], u["name"].lower())].append(u)
    arrivals = [u for u in records if _has(u["reasons"], "filecreate") or _has(u["reasons"], "renamenewname")]
    for a in arrivals:
        for u in ctx._name_freed.get((a["parent_entry"], a["name"].lower()), []):
            if (u["entry"], u["seq"]) != key and 0 <= a["ts"] - u["ts"] <= window:
                return {"freed_by": [u["entry"], u["seq"]], "freed_at": fmt_ts(u["ts"]),
                        "arrived_at": fmt_ts(a["ts"]), "name": a["name"]}
    return None


def r8(ctx, key):
    """The FILE_CREATE record for the file in $J agrees with SIA-C."""
    if not ctx.has_usn:
        return _ne("no $J data")
    recs = ctx.usn_by_key.get(key, [])
    creates = [u for u in recs if _has(u["reasons"], "filecreate")]
    if not creates:
        return _ne("no FileCreate record for file in $J")
    f = ctx.mft[key]
    if f["si_c"] is None:
        return _ne("SIA-C missing")
    first = min(creates, key=lambda u: u["ts"])
    diff = diff_seconds(f["si_c"], first["ts"])
    details = {"si_c": fmt_ts(f["si_c"]), "filecreate_time": fmt_ts(first["ts"]),
               "si_c_minus_create_s": round(diff, 3), "tolerance_s": ctx.cfg["tau_journal_s"]}
    if abs(diff) <= ctx.cfg["tau_journal_s"]:
        return CONSISTENT, details
    tun = _tunneling_explains(ctx, key, recs)
    if tun:
        details["explained_by_tunneling"] = tun
        return CONSISTENT, details
    return VIOLATED, details


def r9(ctx, key):
    """The target creation time embedded in each LNK agrees with the target's current SIA-C."""
    lnks = _lnk_pairs(ctx, key)
    if not lnks:
        return _ne("no LNK file references this file")
    f = ctx.mft[key]
    tau = ctx.cfg["tau_lnk_s"]
    checked, bad = 0, []
    for lnk in lnks:
        if lnk["tgt_c"] is None:
            continue
        checked += 1
        diff = diff_seconds(lnk["tgt_c"], f["si_c"])
        if abs(diff) > tau:
            bad.append({"lnk": lnk["source_file"], "embedded_target_c": fmt_ts(lnk["tgt_c"]),
                        "diff_s": round(diff, 3)})
    if not checked:
        return _ne("LNK files carry no target creation time")
    return (VIOLATED if bad else CONSISTENT), {
        "target_si_c": fmt_ts(f["si_c"]), "lnks_checked": checked, "mismatches": bad,
    }


def r10(ctx, key):
    """Metadata changes do not coincide with Prefetch execution of an unassociated binary."""
    if not ctx.has_usn:
        return _ne("no $J data")
    if not ctx.has_prefetch:
        return _ne("no Prefetch data")
    bics = [u for u in ctx.usn_by_key.get(key, []) if _has(u["reasons"], "basicinfochange")]
    if not bics:
        return _ne("no BasicInfoChange record for file in $J")
    f = ctx.mft[key]
    allow = {x.lower() for x in ctx.cfg["r10_allowlist"]}
    min_runs = ctx.cfg["r10_min_assoc_runs"]
    win = seconds(ctx.cfg["tau_prefetch_s"])
    hits, seen = [], set()
    for b in bics:
        for run_time, exe, pf_name in ctx.pf_runs_between(b["ts"] - win, b["ts"] + win):
            if exe in allow or (pf_name, b["ts"]) in seen:
                continue
            loaded = f["path"] in ctx.pf_files.get(exe, ())
            if loaded and ctx.pf_run_count.get(exe, 0) >= min_runs:
                continue   # a program that routinely opens this file
            seen.add((pf_name, b["ts"]))
            hits.append({"exe": exe, "prefetch": pf_name, "run_time": fmt_ts(run_time),
                         "bic_time": fmt_ts(b["ts"]), "file_in_files_loaded": loaded,
                         "run_count": ctx.pf_run_count.get(exe, 0), "_t": b["ts"]})
    details = {"basicinfochange_records": len(bics), "window_s": ctx.cfg["tau_prefetch_s"],
               "coinciding_executions": [{k: v for k, v in h.items() if k != "_t"} for h in hits]}
    if hits:
        details["_evidence_time"] = max(h["_t"] for h in hits)
    return (VIOLATED if hits else CONSISTENT), details


class _Stratigraphy:
    def __init__(self, ctx):
        recs = sorted((k[0], d["si_c"]) for k, d in ctx.mft.items()
                      if d["in_use"] and d["si_c"] is not None and k[0] >= ctx.cfg["min_entry"])
        self.entries = [r[0] for r in recs]
        self.times = [r[1] for r in recs]


def r11(ctx, key):
    """MFT allocation order is plausible: SIA-C is not far older than neighboring records."""
    if not hasattr(ctx, "_strat"):
        ctx._strat = _Stratigraphy(ctx)
    s = ctx._strat
    f = ctx.mft[key]
    if f["si_c"] is None:
        return _ne("SIA-C missing")
    k = ctx.cfg["r11_neighbors"]
    i = bisect.bisect_left(s.entries, key[0])
    neigh = s.times[max(0, i - k):i] + s.times[i + 1:i + 1 + k]
    if len(neigh) < ctx.cfg["r11_min_neighbors"]:
        return _ne("too few neighboring MFT records", neighbors=len(neigh))
    neigh = sorted(neigh)
    median = neigh[len(neigh) // 2]
    older_days = (median - f["si_c"]) / TICKS_PER_SECOND / 86400
    return (VIOLATED if older_days > ctx.cfg["r11_delta_days"] else CONSISTENT), {
        "si_c": fmt_ts(f["si_c"]), "neighbor_median_c": fmt_ts(median),
        "older_than_neighbors_days": round(older_days, 2), "neighbors": len(neigh),
        "threshold_days": ctx.cfg["r11_delta_days"],
    }


RULES = {
    "R1": r1, "R2": r2, "R3": r3, "R4": r4, "R5": r5, "R6": r6,
    "R7": r7, "R8": r8, "R9": r9, "R10": r10, "R11": r11,
}


def evaluate_all(ctx, rule_ids=None):
    """Yield (key, rule_id, outcome, details) for every candidate file and rule."""
    rule_ids = rule_ids or list(RULES)
    for key in ctx.candidates:
        for rid in rule_ids:
            outcome, details = RULES[rid](ctx, key)
            yield key, rid, outcome, details

