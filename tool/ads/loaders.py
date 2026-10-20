"""Load Eric Zimmerman tool CSV output into the case database.

Expected inputs (see scripts/run_parsers.ps1 for the exact command lines):
  MFTECmd  $MFT       -> mft CSV
  MFTECmd  $J (-m)    -> usn CSV
  LECmd    (--mp)     -> lnk CSV
  PECmd    (--mp)     -> prefetch CSV (the main file, not *_Timeline.csv)
  EvtxECmd            -> evtx CSV (System, Security, Application)
"""

import csv
import hashlib
import json
import re

from . import paths
from .timeutil import now_utc_iso, parse_ts

csv.field_size_limit(1 << 30)


class InputError(Exception):
    pass


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _rows(path, required, kind):
    # Zimmerman tools write UTF-8 with a BOM.
    fh = open(path, newline="", encoding="utf-8-sig")
    reader = csv.DictReader(fh)
    header = {h.strip().lower(): h for h in (reader.fieldnames or [])}
    missing = [c for c in required if c.lower() not in header]
    if missing:
        fh.close()
        raise InputError("%s CSV %s is missing columns: %s" % (kind, path, ", ".join(missing)))

    def get(row, col):
        key = header.get(col.lower())
        return row.get(key) if key else None

    def gen():
        with fh:
            for row in reader:
                yield lambda col, row=row: get(row, col)

    return gen()


def _int(v):
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    try:
        return int(s, 16) if s.lower().startswith("0x") else int(float(s))
    except ValueError:
        return None


def _bool(v):
    return str(v).strip().lower() in ("true", "1", "yes")


def _record_input(con, kind, path, rows):
    con.execute(
        "INSERT INTO inputs VALUES (?,?,?,?,?)",
        (kind, path, sha256_file(path), rows, now_utc_iso()),
    )


def load_mft(con, path):
    req = ["EntryNumber", "SequenceNumber", "InUse", "ParentPath", "FileName",
           "Created0x10", "LastModified0x10", "LastRecordChange0x10", "LastAccess0x10"]
    best = {}
    for g in _rows(path, req, "MFT"):
        if _bool(g("IsAds")):
            continue
        key = (_int(g("EntryNumber")), _int(g("SequenceNumber")))
        if key[0] is None:
            continue
        name_type = (g("NameType") or "").strip().lower()
        # Prefer the long (Windows/POSIX) name over the 8.3 DOS name.
        if key in best and name_type == "dos":
            continue
        best[key] = (
            key[0], key[1], int(_bool(g("InUse"))), int(_bool(g("IsDirectory"))),
            _int(g("ParentEntryNumber")), (g("FileName") or "").strip(),
            paths.join_mft_path(g("ParentPath"), g("FileName")), _int(g("FileSize")),
            parse_ts(g("Created0x10")), parse_ts(g("LastModified0x10")),
            parse_ts(g("LastRecordChange0x10")), parse_ts(g("LastAccess0x10")),
            parse_ts(g("Created0x30")), parse_ts(g("LastModified0x30")),
            parse_ts(g("LastRecordChange0x30")), parse_ts(g("LastAccess0x30")),
        )
    con.executemany("INSERT OR REPLACE INTO mft VALUES (%s)" % ",".join("?" * 16), best.values())
    _record_input(con, "mft", path, len(best))
    return len(best)


def load_usn(con, path):
    req = ["Name", "EntryNumber", "SequenceNumber", "UpdateSequenceNumber",
           "UpdateTimestamp", "UpdateReasons"]
    rows = []
    for g in _rows(path, req, "$J"):
        name = (g("Name") or "").strip()
        parent_path = g("ParentPath")
        rows.append((
            _int(g("UpdateSequenceNumber")), parse_ts(g("UpdateTimestamp")),
            _int(g("EntryNumber")), _int(g("SequenceNumber")),
            _int(g("ParentEntryNumber")), name,
            paths.join_mft_path(parent_path, name) if parent_path else None,
            (g("UpdateReasons") or "").strip(),
        ))
    con.executemany("INSERT INTO usn VALUES (?,?,?,?,?,?,?,?)", rows)
    _record_input(con, "usn", path, len(rows))
    return len(rows)


def load_lnk(con, path, mount_prefix=None):
    req = ["SourceFile", "SourceCreated", "SourceModified", "SourceAccessed",
           "TargetCreated", "TargetModified", "TargetAccessed"]
    prefix = paths.norm_path(mount_prefix) if mount_prefix else None
    rows = []
    for g in _rows(path, req, "LNK"):
        src = g("SourceFile")
        source_path = paths.strip_prefix(paths.norm_path(src), prefix)
        target = paths.norm_path(g("LocalPath")) or paths.from_shell_path(g("TargetIDAbsolutePath"))
        entry = _int(g("TargetMFTEntryNumber"))
        seq = _int(g("TargetMFTSequenceNumber"))
        rows.append((
            src, source_path,
            parse_ts(g("SourceCreated")), parse_ts(g("SourceModified")), parse_ts(g("SourceAccessed")),
            parse_ts(g("TargetCreated")), parse_ts(g("TargetModified")), parse_ts(g("TargetAccessed")),
            target, entry or None, seq if entry else None,
        ))
    con.executemany(
        "INSERT INTO lnk (source_file, source_path, src_c, src_m, src_a, tgt_c, tgt_m, tgt_a,"
        " target_path, target_entry, target_seq) VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    _record_input(con, "lnk", path, len(rows))
    return len(rows)


def load_prefetch(con, path):
    req = ["SourceFilename", "ExecutableName", "LastRun"]
    n = 0
    for g in _rows(path, req, "Prefetch"):
        pf_name = paths.basename(g("SourceFilename"))
        exe = (g("ExecutableName") or "").strip().lower()
        con.execute("INSERT INTO pf VALUES (?,?,?,?,?)",
                    (pf_name, exe, (g("Hash") or "").strip(), _int(g("RunCount")), g("SourceFilename")))
        runs = [g("LastRun")] + [g("PreviousRun%d" % i) for i in range(7)]
        for t in filter(None, (parse_ts(r) for r in runs)):
            con.execute("INSERT INTO pf_runs VALUES (?,?,?)", (pf_name, exe, t))
        for f in (g("FilesLoaded") or "").split(","):
            p = paths.norm_path(f)
            if p:
                con.execute("INSERT INTO pf_files VALUES (?,?,?)", (pf_name, exe, p))
        n += 1
    _record_input(con, "prefetch", path, n)
    return n


_SID_RE = re.compile(r"S-1-5-21-[0-9-]+")


def load_evtx(con, path):
    req = ["EventRecordId", "TimeCreated", "EventId", "Channel"]
    rows = []
    for g in _rows(path, req, "EVTX"):
        payload = g("Payload") or ""
        user = None
        m = _SID_RE.search(payload)
        if m:
            user = m.group(0)
        rows.append((
            (g("Channel") or "").strip(), _int(g("EventId")), _int(g("EventRecordId")),
            parse_ts(g("TimeCreated")), (g("Provider") or "").strip(),
            user or (g("UserId") or "").strip() or None, payload,
        ))
    con.executemany("INSERT INTO events VALUES (?,?,?,?,?,?,?)", rows)
    _record_input(con, "evtx", path, len(rows))
    return len(rows)


def payload_fields(payload):
    """Name -> text for EvtxECmd's JSON Payload column (EventData/Data items)."""
    out = {}
    if not payload:
        return out
    try:
        data = json.loads(payload)
        items = data.get("EventData", {}).get("Data", [])
        if isinstance(items, dict):
            items = [items]
        for it in items:
            if isinstance(it, dict) and "@Name" in it:
                out[it["@Name"]] = it.get("#text")
    except (ValueError, AttributeError):
        for name, text in re.findall(r'"@Name"\s*:\s*"(\w+)"\s*,\s*"#text"\s*:\s*"([^"]*)"', payload):
            out[name] = text
    return out
