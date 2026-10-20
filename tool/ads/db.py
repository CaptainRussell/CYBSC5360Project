"""SQLite case database. All times are FILETIME integers (UTC)."""

import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS inputs (
    kind TEXT, path TEXT, sha256 TEXT, rows INTEGER, loaded_at TEXT
);
CREATE TABLE IF NOT EXISTS mft (
    entry INTEGER, seq INTEGER, in_use INTEGER, is_dir INTEGER,
    parent_entry INTEGER, name TEXT, path TEXT, size INTEGER,
    si_c INTEGER, si_m INTEGER, si_e INTEGER, si_a INTEGER,
    fn_c INTEGER, fn_m INTEGER, fn_e INTEGER, fn_a INTEGER,
    PRIMARY KEY (entry, seq)
);
CREATE INDEX IF NOT EXISTS mft_path ON mft(path);
CREATE TABLE IF NOT EXISTS usn (
    usn INTEGER, ts INTEGER, entry INTEGER, seq INTEGER,
    parent_entry INTEGER, name TEXT, path TEXT, reasons TEXT
);
CREATE INDEX IF NOT EXISTS usn_key ON usn(entry, seq);
CREATE TABLE IF NOT EXISTS lnk (
    id INTEGER PRIMARY KEY, source_file TEXT, source_path TEXT,
    src_c INTEGER, src_m INTEGER, src_a INTEGER,
    tgt_c INTEGER, tgt_m INTEGER, tgt_a INTEGER,
    target_path TEXT, target_entry INTEGER, target_seq INTEGER
);
CREATE TABLE IF NOT EXISTS pf (
    pf_name TEXT, exe TEXT, hash TEXT, run_count INTEGER, source_file TEXT
);
CREATE TABLE IF NOT EXISTS pf_runs (pf_name TEXT, exe TEXT, run_time INTEGER);
CREATE INDEX IF NOT EXISTS pf_runs_t ON pf_runs(run_time);
CREATE TABLE IF NOT EXISTS pf_files (pf_name TEXT, exe TEXT, path TEXT);
CREATE TABLE IF NOT EXISTS events (
    channel TEXT, event_id INTEGER, record_id INTEGER, ts INTEGER,
    provider TEXT, user TEXT, payload TEXT
);
CREATE INDEX IF NOT EXISTS events_ch ON events(channel, event_id);
"""


def connect(path):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con
