/* Windows date checks: a port of ads/timeutil.py, loaders.py, rules.py, indicators.py,
   scoring.py, explain.py, pipeline.py (ingest and analyze), report.py (the saved files)
   and ntfs_briefing.build_data. The SQLite case database becomes plain arrays kept in
   the order SQLite would return them. Times are FILETIME ticks as BigInts. */

const DATES = {};
const CFG0 = PYDATA.config;
const RIDS_D = CFG0.RULE_IDS;
const TPS = 10000000n;
const V_OK = "consistent", V_BAD = "violated", V_NE = "not_evaluable";
class InputError extends Error {}
DATES.InputError = InputError;
DATES.defaults = () => JSON.parse(JSON.stringify(CFG0.DEFAULTS));

/* ---- timeutil ---------------------------------------------------------------------------- */
const TS_RE = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,7})\d*)?\s*(Z|[+-]\d{2}:?\d{2})?$/;
const EPOCH_MS = Date.UTC(1601, 0, 1);
const civilMs = (y, mo, d, h, mi, s) => { const t = new Date(0); t.setUTCFullYear(y, mo - 1, d); t.setUTCHours(h, mi, s, 0); return t.getTime(); };
DATES.parseTs = value => {
  if (value == null) return null;
  const s = U.strip(String(value));
  if (!s) return null;
  const m = TS_RE.exec(s);
  if (!m) return null;
  const [y, mo, d, h, mi, se] = m.slice(1, 7).map(Number);
  if (!U.validDate(y, mo, d) || h > 23 || mi > 59 || se > 59) return null;
  let ms = civilMs(y, mo, d, h, mi, se);
  const tz = m[8];
  if (tz && tz !== "Z") { const sign = tz[0] === "+" ? 1 : -1; ms -= sign * (parseInt(tz.slice(1, 3), 10) * 60 + parseInt(tz.slice(-2), 10)) * 60000; }
  const ticks = BigInt((ms - EPOCH_MS) / 1000) * TPS + BigInt(parseInt((m[7] || "").padEnd(7, "0"), 10));
  return ticks > 0n ? ticks : null;
};
DATES.fmtTs = ticks => {
  if (ticks == null) return "";
  let sec = ticks / TPS, frac = ticks % TPS;
  if (frac < 0n) { frac += TPS; sec -= 1n; }
  const dt = new Date(EPOCH_MS + Number(sec) * 1000);
  return U.isoSec(dt) + "." + frac.toString().padStart(7, "0");
};
DATES.subsecond = t => (t == null ? null : ((t % TPS) + TPS) % TPS);
DATES.seconds = n => BigInt(U.round(n * 10000000));
DATES.diffSeconds = (a, b) => Number(a - b) / 1e7;
const _has = (reasons, flag) => reasons.toLowerCase().includes(flag);
const maxBy = (arr, key) => { let best = null, bk; for (const x of arr) { const k = key(x); if (best === null || U.cmp(k, bk) > 0) { best = x; bk = k; } } return best; };
const minBy = (arr, key) => { let best = null, bk; for (const x of arr) { const k = key(x); if (best === null || U.cmp(k, bk) < 0) { best = x; bk = k; } } return best; };
const bigMax = xs => xs.reduce((a, b) => (a === null || b > a ? b : a), null);

/* ---- loaders: Zimmerman CSVs into the case tables ----------------------------------------- */
function rowsOf(text, required, kind, name) {
  const { fieldnames, rows } = U.csvDict(text);
  const header = {}; for (const h of fieldnames) header[U.strip(h).toLowerCase()] = h;
  const missing = required.filter(c => !(c.toLowerCase() in header));
  if (missing.length) throw new InputError(kind + " CSV " + name + " is missing columns: " + missing.join(", "));
  return rows.map(r => col => { const k = header[col.toLowerCase()]; return k !== undefined ? (r[k] === undefined ? null : r[k]) : null; });
}
const FLOAT_RE = /^[+-]?(?:\d+(?:_\d+)*(?:\.(?:\d+(?:_\d+)*)?)?|\.\d+(?:_\d+)*)(?:[eE][+-]?\d+(?:_\d+)*)?$/;
DATES.int = v => {
  if (v == null) return null;
  const s = U.strip(String(v));
  if (!s) return null;
  if (s.toLowerCase().startsWith("0x")) { if (!/^0x[0-9a-f_]+$/i.test(s)) return null; return Number(BigInt("0x" + s.slice(2).replace(/_/g, ""))); }
  if (!FLOAT_RE.test(s)) return null;
  return Math.trunc(Number(s.replace(/_/g, "")));
};
DATES.bool = v => ["true", "1", "yes"].includes(U.strip(String(v)).toLowerCase());

class CaseDB {
  constructor() { this.inputs = []; this.mft = new Map(); this.usn = []; this.lnk = []; this.pf = []; this.pf_runs = []; this.pf_files = []; this.events = []; }
  putMft(r) { const k = r.entry + "," + r.seq; if (this.mft.has(k)) this.mft.delete(k); this.mft.set(k, r); }   // INSERT OR REPLACE
  record(kind, name, rows, sha) { this.inputs.push({ kind, path: name, sha256: sha, rows, loaded_at: U.nowIso() }); }
}
DATES.CaseDB = CaseDB;
const shaOf = src => { const h = new U.SHA256(), CH = 8 << 20; for (let p = 0; p < src.size; p += CH) h.update(src.read(p, Math.min(CH, src.size - p))); return h.hex(); };
DATES.loadMft = (db, text, name, sha) => {
  const req = ["EntryNumber", "SequenceNumber", "InUse", "ParentPath", "FileName", "Created0x10", "LastModified0x10", "LastRecordChange0x10", "LastAccess0x10"];
  const best = new Map(), P = DATES.parseTs;
  for (const g of rowsOf(text, req, "MFT", name)) {
    if (DATES.bool(g("IsAds"))) continue;
    const e = DATES.int(g("EntryNumber")), s = DATES.int(g("SequenceNumber"));
    if (e === null) continue;
    const key = e + "," + s, nt = U.strip(g("NameType") || "").toLowerCase();
    if (best.has(key) && nt === "dos") continue;
    best.set(key, { entry: e, seq: s, in_use: DATES.bool(g("InUse")) ? 1 : 0, is_dir: DATES.bool(g("IsDirectory")) ? 1 : 0,
      parent_entry: DATES.int(g("ParentEntryNumber")), name: U.strip(g("FileName") || ""), path: PATHS.joinMftPath(g("ParentPath"), g("FileName")),
      size: DATES.int(g("FileSize")), si_c: P(g("Created0x10")), si_m: P(g("LastModified0x10")), si_e: P(g("LastRecordChange0x10")), si_a: P(g("LastAccess0x10")),
      fn_c: P(g("Created0x30")), fn_m: P(g("LastModified0x30")), fn_e: P(g("LastRecordChange0x30")), fn_a: P(g("LastAccess0x30")) });
  }
  for (const r of best.values()) db.putMft(r);
  db.record("mft", name, best.size, sha);
  return best.size;
};
DATES.loadUsn = (db, text, name, sha) => {
  const req = ["Name", "EntryNumber", "SequenceNumber", "UpdateSequenceNumber", "UpdateTimestamp", "UpdateReasons"]; let n = 0;
  for (const g of rowsOf(text, req, "$J", name)) {
    const nm = U.strip(g("Name") || ""), pp = g("ParentPath");
    db.usn.push({ usn: DATES.int(g("UpdateSequenceNumber")), ts: DATES.parseTs(g("UpdateTimestamp")), entry: DATES.int(g("EntryNumber")), seq: DATES.int(g("SequenceNumber")),
      parent_entry: DATES.int(g("ParentEntryNumber")), name: nm, path: pp ? PATHS.joinMftPath(pp, nm) : null, reasons: U.strip(g("UpdateReasons") || "") });
    n++;
  }
  db.record("usn", name, n, sha); return n;
};
DATES.loadLnk = (db, text, name, sha, mountPrefix) => {
  const req = ["SourceFile", "SourceCreated", "SourceModified", "SourceAccessed", "TargetCreated", "TargetModified", "TargetAccessed"];
  const prefix = mountPrefix ? PATHS.normPath(mountPrefix) : null, P = DATES.parseTs; let n = 0;
  for (const g of rowsOf(text, req, "LNK", name)) {
    const src = g("SourceFile"), entry = DATES.int(g("TargetMFTEntryNumber")), seq = DATES.int(g("TargetMFTSequenceNumber"));
    db.lnk.push({ id: db.lnk.length + 1, source_file: src, source_path: PATHS.stripPrefix(PATHS.normPath(src), prefix),
      src_c: P(g("SourceCreated")), src_m: P(g("SourceModified")), src_a: P(g("SourceAccessed")),
      tgt_c: P(g("TargetCreated")), tgt_m: P(g("TargetModified")), tgt_a: P(g("TargetAccessed")),
      target_path: PATHS.normPath(g("LocalPath")) || PATHS.fromShellPath(g("TargetIDAbsolutePath")),
      target_entry: entry || null, target_seq: entry ? seq : null });
    n++;
  }
  db.record("lnk", name, n, sha); return n;
};
DATES.loadPrefetch = (db, text, name, sha) => {
  const req = ["SourceFilename", "ExecutableName", "LastRun"]; let n = 0;
  for (const g of rowsOf(text, req, "Prefetch", name)) {
    const pfName = PATHS.basename(g("SourceFilename")), exe = U.strip(g("ExecutableName") || "").toLowerCase();
    db.pf.push({ pf_name: pfName, exe, hash: U.strip(g("Hash") || ""), run_count: DATES.int(g("RunCount")), source_file: g("SourceFilename") });
    const runs = [g("LastRun")]; for (let i = 0; i < 7; i++) runs.push(g("PreviousRun" + i));
    for (const r of runs) { const t = DATES.parseTs(r); if (t) db.pf_runs.push({ pf_name: pfName, exe, run_time: t }); }
    for (const f of (g("FilesLoaded") || "").split(",")) { const p = PATHS.normPath(f); if (p) db.pf_files.push({ pf_name: pfName, exe, path: p }); }
    n++;
  }
  db.record("prefetch", name, n, sha); return n;
};
const SID_RE = /S-1-5-21-[0-9-]+/;
DATES.loadEvtx = (db, text, name, sha) => {
  const req = ["EventRecordId", "TimeCreated", "EventId", "Channel"]; let n = 0;
  for (const g of rowsOf(text, req, "EVTX", name)) {
    const payload = g("Payload") || "", m = SID_RE.exec(payload);
    db.events.push({ channel: U.strip(g("Channel") || ""), event_id: DATES.int(g("EventId")), record_id: DATES.int(g("EventRecordId")),
      ts: DATES.parseTs(g("TimeCreated")), provider: U.strip(g("Provider") || ""), user: (m ? m[0] : null) || U.strip(g("UserId") || "") || null, payload });
    n++;
  }
  db.record("evtx", name, n, sha); return n;
};
DATES.payloadFields = payload => {
  const out = {};
  if (!payload) return out;
  try {
    const data = JSON.parse(payload);
    if (data === null || typeof data !== "object" || Array.isArray(data)) throw new TypeError("not a dict");
    const ed = data.EventData === undefined ? {} : data.EventData;
    if (ed === null || typeof ed !== "object" || Array.isArray(ed)) throw new TypeError("not a dict");
    let items = ed.Data === undefined ? [] : ed.Data;
    if (items && typeof items === "object" && !Array.isArray(items)) items = [items];
    for (const it of (typeof items === "string" ? [] : items || [])) if (it && typeof it === "object" && !Array.isArray(it) && "@Name" in it) out[it["@Name"]] = it["#text"] === undefined ? null : it["#text"];
  } catch (e) {
    for (const m of payload.matchAll(/"@Name"\s*:\s*"(\w+)"\s*,\s*"#text"\s*:\s*"([^"]*)"/g)) out[m[1]] = m[2];
  }
  return out;
};

/* which kind of record a parser CSV holds, from its file name (pipeline.classify_csv) */
const glob = p => new RegExp("^" + p.replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*").replace(/\?/g, ".") + "$", "s");
const CSV_SKIP = PYDATA.pipeline.CSV_SKIP.map(glob), CSV_KINDS = PYDATA.pipeline.CSV_KINDS.map(([k, ps]) => [k, ps.map(glob)]);
DATES.classifyCsv = name => {
  const n = name.split(/[\\/]/).pop().toLowerCase();
  if (!n.endsWith(".csv") || CSV_SKIP.some(r => r.test(n))) return null;
  for (const [kind, pats] of CSV_KINDS) if (pats.some(r => r.test(n))) return kind;
  return null;
};

/* ---- the rules' context (rules.Context) ------------------------------------------------------- */
class Context {
  constructor(db, cfg) {
    this.cfg = cfg; this.db = db;
    this.mft = new Map(); this.path_index = new Map();
    for (const d of db.mft.values()) {
      const k = d.entry + "," + d.seq; this.mft.set(k, d);
      if (d.path) { if (!this.path_index.has(d.path)) this.path_index.set(d.path, []); this.path_index.get(d.path).push(k); }
    }
    this.candidates = U.sorted([...this.mft.values()].filter(d => d.in_use && !d.is_dir && d.entry >= cfg.min_entry), d => [d.entry, d.seq]).map(d => d.entry + "," + d.seq);
    this.usn_rows = U.sorted(db.usn, u => [u.ts, u.usn]);
    this.usn_by_key = new Map();
    for (const u of this.usn_rows) { const k = u.entry + "," + u.seq; if (!this.usn_by_key.has(k)) this.usn_by_key.set(k, []); this.usn_by_key.get(k).push(u); }
    this.has_usn = this.usn_rows.length > 0;
    this.loadLnk(); this.loadPrefetch(); this.loadEvents();
  }
  resolvePath(path) {
    for (const p of [path].concat(PATHS.anchorSuffixes(path))) {
      const keys = (this.path_index.get(p) || []).filter(k => this.mft.get(k).in_use);
      if (keys.length) return maxBy(keys, k => this.mft.get(k).seq);
    }
    return null;
  }
  loadLnk() {
    this.lnks = []; this.lnks_by_target = new Map(); this.lnk_unresolved = 0;
    const entries = new Set([...this.mft.values()].map(d => d.entry));
    for (const r of this.db.lnk) {
      const d = Object.assign({}, r);
      d.own_key = this.resolvePath(d.source_path);
      let tk = null, how = null;
      if (d.target_entry != null) {
        const k = d.target_entry + "," + d.target_seq;
        if (this.mft.has(k)) { tk = k; how = "mft_reference"; } else if (entries.has(d.target_entry)) how = "sequence_mismatch";
      }
      if (tk === null && how === null && d.target_path) { tk = this.resolvePath(d.target_path); how = tk ? "path" : null; }
      d.target_key = tk; d.join = how;
      this.lnks.push(d);
      if (tk) { if (!this.lnks_by_target.has(tk)) this.lnks_by_target.set(tk, []); this.lnks_by_target.get(tk).push(d); } else this.lnk_unresolved++;
    }
  }
  loadPrefetch() {
    this.pf_runs = U.sorted(this.db.pf_runs.map(r => [r.run_time, r.exe, r.pf_name]), x => x);
    this.pf_run_times = this.pf_runs.map(r => r[0]);
    this.pf_files = new Map(); for (const r of this.db.pf_files) { if (!this.pf_files.has(r.exe)) this.pf_files.set(r.exe, new Set()); this.pf_files.get(r.exe).add(r.path); }
    this.pf_run_count = new Map(); this.pf_names = new Set();
    for (const r of this.db.pf) { this.pf_run_count.set(r.exe, Math.max(this.pf_run_count.get(r.exe) || 0, r.run_count || 0)); this.pf_names.add(r.pf_name); }
    this.has_prefetch = this.pf_names.size > 0;
  }
  pfRunsBetween(a, b) { return this.pf_runs.slice(U.bisectLeft(this.pf_run_times, a), U.bisectRight(this.pf_run_times, b)); }
  loadEvents() {
    this.events = new Map();
    for (const r of U.sorted(this.db.events.filter(e => e.ts !== null), e => [e.ts, e.record_id])) {
      const ch = r.channel.toLowerCase(); if (!this.events.has(ch)) this.events.set(ch, []); this.events.get(ch).push(r);
    }
    const system = this.events.get("system") || [];
    this.system_coverage = system.length ? [system[0].ts, system[system.length - 1].ts] : null;
    this.sessions = this.buildSessions(system);
  }
  buildSessions(system) {
    const starts = new Set(this.cfg.session_start_ids), ends = new Set(this.cfg.session_end_ids), resets = new Set(this.cfg.boot_shutdown_ids);
    if (!system.some(e => starts.has(e.event_id))) return null;
    const open = new Map(), sessions = [];
    for (const e of system) {
      const eid = e.event_id, user = e.user || "any";
      if (starts.has(eid)) { if (!open.has(user)) open.set(user, e.ts); }
      else if (ends.has(eid)) {
        if (open.has(user)) { sessions.push([open.get(user), e.ts]); open.delete(user); }
        else if (open.has("any")) { sessions.push([open.get("any"), e.ts]); open.delete("any"); }
      } else if (resets.has(eid)) { for (const t of open.values()) sessions.push([t, e.ts]); open.clear(); }
    }
    const end = this.system_coverage[1];
    for (const t of open.values()) sessions.push([t, end]);
    return U.sorted(sessions, s => s);
  }
  mostRecentLnk(lnks) {
    const mtime = l => { const own = l.own_key ? this.mft.get(l.own_key) : null; return (own ? own.si_m : null) || l.src_m || 0n; };
    return maxBy(lnks, mtime);
  }
  lnkOwnTimes(l) {
    const own = l.own_key ? this.mft.get(l.own_key) : null;
    if (own) return { c: own.si_c, m: own.si_m, a: own.si_a, e: own.si_e, from: "mft" };
    return { c: l.src_c, m: l.src_m, a: l.src_a, e: null, from: "lecmd" };
  }
}
DATES.Context = Context;

/* ---- rules R1-R11 ------------------------------------------------------------------------------- */
const ne = (reason, extra) => [V_NE, Object.assign({ reason }, extra || {})];
const F = DATES.fmtTs;
const R = {};
R.R1 = (ctx, key) => {
  if (!ctx.has_usn) return ne("no $J data");
  const f = ctx.mft.get(key), bics = (ctx.usn_by_key.get(key) || []).filter(u => _has(u.reasons, "basicinfochange") && u.ts !== null);
  if (!bics.length) return ne("no BasicInfoChange record for file in $J");
  if (f.si_e === null) return ne("SIA-E missing");
  const last = maxBy(bics, u => u.ts), diff = DATES.diffSeconds(f.si_e, last.ts), tau = ctx.cfg.tau_journal_s;
  const bad = ctx.cfg.r1_two_sided ? Math.abs(diff) > tau : diff < -tau;
  return [bad ? V_BAD : V_OK, { si_e: F(f.si_e), bic_time: F(last.ts), bic_usn: last.usn, si_e_minus_bic_s: U.round(diff, 3), tolerance_s: tau, _evidence_time: last.ts }];
};
R.R2 = (ctx, key) => {
  const lnks = ctx.lnks_by_target.get(key);
  if (!lnks) return ne("no LNK file references this file");
  const lnk = ctx.mostRecentLnk(lnks), own = ctx.lnkOwnTimes(lnk);
  if (own.e === null) return ne("LNK file's own MFT record not found (SIA-E unavailable)", { lnk: lnk.source_file });
  const t = ctx.mft.get(key);
  if (t.si_e === null) return ne("SIA-E missing");
  const diff = DATES.diffSeconds(own.e, t.si_e), tau = ctx.cfg.tau_lnk_s;
  return [Math.abs(diff) > tau ? V_BAD : V_OK, { lnk: lnk.source_file, lnk_si_e: F(own.e), target_si_e: F(t.si_e), diff_s: U.round(diff, 3), tolerance_s: tau, join: lnk.join }];
};
R.R3 = (ctx, key) => {
  const lnks = ctx.lnks_by_target.get(key);
  if (!lnks) return ne("no LNK file references this file");
  const t = ctx.mft.get(key);
  if (t.si_c === null) return ne("SIA-C missing");
  const tau = DATES.seconds(ctx.cfg.tau_lnk_s), checked = [], bad = [];
  for (const l of lnks) {
    const own = ctx.lnkOwnTimes(l);
    if (own.c === null) continue;
    checked.push(l.source_file);
    if (own.c < t.si_c - tau) bad.push({ lnk: l.source_file, lnk_si_c: F(own.c) });
  }
  if (!checked.length) return ne("LNK creation time unavailable");
  return [bad.length ? V_BAD : V_OK, { target_si_c: F(t.si_c), lnks_checked: checked.length, lnks_earlier: bad }];
};
R.R4 = (ctx, key) => {
  const lnks = ctx.lnks_by_target.get(key);
  if (!lnks) return ne("no LNK file references this file");
  const lnk = ctx.mostRecentLnk(lnks), own = ctx.lnkOwnTimes(lnk), t = ctx.mft.get(key);
  if (own.a === null || t.si_a === null) return ne("access time unavailable");
  const diff = DATES.diffSeconds(own.a, t.si_a), tau = ctx.cfg.tau_lnk_s;
  return [diff > tau ? V_BAD : V_OK, { lnk: lnk.source_file, lnk_si_a: F(own.a), target_si_a: F(t.si_a), lnk_minus_target_s: U.round(diff, 3), tolerance_s: tau, lnk_times_from: own.from }];
};
R.R5 = (ctx, key) => {
  if (ctx.sessions === null) return ne("no user session events in System log");
  const [lo, hi] = ctx.system_coverage, tau = DATES.seconds(ctx.cfg.tau_session_s), f = ctx.mft.get(key);
  const checked = {}, outside = [], skipped = [];
  for (const field of ["si_c", "si_m"]) {
    const t = f[field];
    if (t === null) continue;
    if (!(lo <= t && t <= hi)) { skipped.push(field); continue; }
    const inside = ctx.sessions.some(([s, e]) => s - tau <= t && t <= e + tau);
    checked[field] = F(t);
    if (!inside) outside.push(field);
  }
  if (!Object.keys(checked).length) return ne("timestamps fall outside System log coverage", { coverage: [F(lo), F(hi)], skipped });
  return [outside.length ? V_BAD : V_OK, { checked, outside_session: outside, outside_log_coverage: skipped, sessions: ctx.sessions.length }];
};
R.R6 = (ctx, key) => {
  const f = ctx.mft.get(key);
  if (f.si_c === null || f.fn_c === null) return ne("SIA-C or FNA-C missing");
  const diff = DATES.diffSeconds(f.si_c, f.fn_c);
  return [diff < -ctx.cfg.tau_mft_s ? V_BAD : V_OK, { si_c: F(f.si_c), fn_c: F(f.fn_c), si_minus_fn_s: U.round(diff, 3) }];
};
R.R7 = (ctx, key) => {
  const f = ctx.mft.get(key), vals = {};
  for (const k of ctx.cfg.r7_fields) if (f[k] != null) vals[k] = f[k];
  if (!Object.keys(vals).length) return ne("SIA timestamps missing");
  const zero = Object.keys(vals).filter(k => DATES.subsecond(vals[k]) === 0n), sub = {};
  for (const k of Object.keys(vals)) sub[k] = DATES.subsecond(vals[k]).toString().padStart(7, "0");
  return [zero.length ? V_BAD : V_OK, { subsecond: sub, zero_fields: zero }];
};
function tunneling(ctx, key, records) {
  const window = DATES.seconds(ctx.cfg.tunneling_window_s);
  if (!ctx._name_freed) {
    ctx._name_freed = new Map();
    for (const u of ctx.usn_rows) if (_has(u.reasons, "filedelete") || _has(u.reasons, "renameoldname")) {
      const k = u.parent_entry + "|" + u.name.toLowerCase(); if (!ctx._name_freed.has(k)) ctx._name_freed.set(k, []); ctx._name_freed.get(k).push(u);
    }
  }
  for (const a of records.filter(u => _has(u.reasons, "filecreate") || _has(u.reasons, "renamenewname"))) {
    for (const u of ctx._name_freed.get(a.parent_entry + "|" + a.name.toLowerCase()) || []) {
      if ((u.entry + "," + u.seq) !== key && a.ts - u.ts >= 0n && a.ts - u.ts <= window)
        return { freed_by: [u.entry, u.seq], freed_at: F(u.ts), arrived_at: F(a.ts), name: a.name };
    }
  }
  return null;
}
R.R8 = (ctx, key) => {
  if (!ctx.has_usn) return ne("no $J data");
  const recs = ctx.usn_by_key.get(key) || [], creates = recs.filter(u => _has(u.reasons, "filecreate") && u.ts !== null);
  if (!creates.length) return ne("no FileCreate record for file in $J");
  const f = ctx.mft.get(key);
  if (f.si_c === null) return ne("SIA-C missing");
  const first = minBy(creates, u => u.ts), diff = DATES.diffSeconds(f.si_c, first.ts);
  const details = { si_c: F(f.si_c), filecreate_time: F(first.ts), si_c_minus_create_s: U.round(diff, 3), tolerance_s: ctx.cfg.tau_journal_s };
  if (Math.abs(diff) <= ctx.cfg.tau_journal_s) return [V_OK, details];
  const tun = tunneling(ctx, key, recs);
  if (tun) { details.explained_by_tunneling = tun; return [V_OK, details]; }
  return [V_BAD, details];
};
R.R9 = (ctx, key) => {
  const lnks = ctx.lnks_by_target.get(key);
  if (!lnks) return ne("no LNK file references this file");
  const f = ctx.mft.get(key);
  if (f.si_c === null) return ne("SIA-C missing");
  const tau = ctx.cfg.tau_lnk_s, bad = []; let checked = 0;
  for (const l of lnks) {
    if (l.tgt_c === null) continue;
    checked++;
    const diff = DATES.diffSeconds(l.tgt_c, f.si_c);
    if (Math.abs(diff) > tau) bad.push({ lnk: l.source_file, embedded_target_c: F(l.tgt_c), diff_s: U.round(diff, 3) });
  }
  if (!checked) return ne("LNK files carry no target creation time");
  return [bad.length ? V_BAD : V_OK, { target_si_c: F(f.si_c), lnks_checked: checked, mismatches: bad }];
};
R.R10 = (ctx, key) => {
  if (!ctx.has_usn) return ne("no $J data");
  if (!ctx.has_prefetch) return ne("no Prefetch data");
  const bics = (ctx.usn_by_key.get(key) || []).filter(u => _has(u.reasons, "basicinfochange") && u.ts !== null);
  if (!bics.length) return ne("no BasicInfoChange record for file in $J");
  const f = ctx.mft.get(key), allow = new Set(ctx.cfg.r10_allowlist.map(x => x.toLowerCase()));
  const minRuns = ctx.cfg.r10_min_assoc_runs, win = DATES.seconds(ctx.cfg.tau_prefetch_s), hits = [], seen = new Set();
  for (const b of bics) {
    for (const [runTime, exe, pfName] of ctx.pfRunsBetween(b.ts - win, b.ts + win)) {
      const sk = pfName + "\u0000" + b.ts;
      if (allow.has(exe) || seen.has(sk)) continue;
      const loaded = (ctx.pf_files.get(exe) || new Set()).has(f.path);
      if (loaded && (ctx.pf_run_count.get(exe) || 0) >= minRuns) continue;
      seen.add(sk);
      hits.push({ exe, prefetch: pfName, run_time: F(runTime), bic_time: F(b.ts), file_in_files_loaded: loaded, run_count: ctx.pf_run_count.get(exe) || 0, _t: b.ts });
    }
  }
  const details = { basicinfochange_records: bics.length, window_s: ctx.cfg.tau_prefetch_s,
    coinciding_executions: hits.map(h => { const o = Object.assign({}, h); delete o._t; return o; }) };
  if (hits.length) details._evidence_time = bigMax(hits.map(h => h._t));
  return [hits.length ? V_BAD : V_OK, details];
};
R.R11 = (ctx, key) => {
  if (!ctx._strat) {
    const recs = U.sorted([...ctx.mft.values()].filter(d => d.in_use && d.si_c !== null && d.entry >= ctx.cfg.min_entry).map(d => [d.entry, d.si_c]), x => x);
    ctx._strat = { entries: recs.map(r => r[0]), times: recs.map(r => r[1]) };
  }
  const s = ctx._strat, f = ctx.mft.get(key);
  if (f.si_c === null) return ne("SIA-C missing");
  const k = ctx.cfg.r11_neighbors, i = U.bisectLeft(s.entries, f.entry);
  let neigh = s.times.slice(Math.max(0, i - k), i).concat(s.times.slice(i + 1, i + 1 + k));
  if (neigh.length < ctx.cfg.r11_min_neighbors) return ne("too few neighboring MFT records", { neighbors: neigh.length });
  neigh = U.sorted(neigh, x => x);
  const median = neigh[neigh.length >> 1], olderDays = Number(median - f.si_c) / 1e7 / 86400;
  return [olderDays > ctx.cfg.r11_delta_days ? V_BAD : V_OK, { si_c: F(f.si_c), neighbor_median_c: F(median),
    older_than_neighbors_days: U.round(olderDays, 2), neighbors: neigh.length, threshold_days: ctx.cfg.r11_delta_days }];
};
DATES.RULES = R;
DATES.evaluateAll = (ctx, onProgress) => {
  const out = [];
  ctx.candidates.forEach((key, n) => {
    for (const rid of RIDS_D) { const [o, d] = R[rid](ctx, key); out.push([key, rid, o, d]); }
    if (onProgress && n % 200 === 0) onProgress(n, ctx.candidates.length);
  });
  return out;
};

/* ---- indicators S1-S5 ------------------------------------------------------------------------------ */
const res = (sid, name, status, times, details) => ({ id: sid, name, status, times: U.sorted((times || []).filter(t => t), t => t), details: details || {} });
function installTime(ctx) {
  if (ctx.cfg.install_time) return [DATES.parseTs(ctx.cfg.install_time), "config"];
  const rec = [...ctx.mft.values()].find(d => d.entry === 0);
  if (rec) return [rec.fn_c || rec.si_c, "$MFT record 0 creation"];
  return [null, null];
}
const find = (ctx, ch, ids, provider) => (ctx.events.get(ch) || []).filter(e => ids.has(e.event_id) && (provider == null || (e.provider || "").toLowerCase().includes(provider)));
const IND = [
  ctx => {
    if (!(ctx.events.get("system") || []).length && !(ctx.events.get("security") || []).length) return res("S1", "Log clearing", V_NE, [], { reason: "no System or Security log" });
    const hits = find(ctx, "system", new Set([104])).concat(find(ctx, "security", new Set([1102])));
    return res("S1", "Log clearing", hits.length ? "fired" : "clear", hits.map(h => h.ts),
      { events: hits.map(h => ({ channel: h.channel, event_id: h.event_id, time: F(h.ts), user: h.user })) });
  },
  ctx => {
    const app = ctx.events.get("application");
    if (!(app && app.length) && !ctx.has_usn) return res("S2", "Change journal reset", V_NE, [], { reason: "no Application log and no $J" });
    const hits = find(ctx, "application", new Set([3079])), times = hits.map(h => h.ts), details = { event_3079: hits.map(h => F(h.ts)) };
    let fired = hits.length > 0;
    if (ctx.has_usn) {
      const timed = ctx.usn_rows.filter(u => u.ts !== null), [install, src] = installTime(ctx), first = timed.length ? minBy(timed, u => u.ts) : { ts: null };
      const usns = ctx.usn_rows.map(u => u.usn).filter(u => u !== null), minUsn = usns.length ? usns.reduce((a, b) => (b < a ? b : a)) : null;
      Object.assign(details, { journal_first_record: F(first.ts), journal_min_usn: minUsn, install_time: F(install), install_time_source: src });
      if (install !== null && first.ts !== null && minUsn !== null) {
        const gap = Number(first.ts - install) / 1e7 / 86400;
        details.journal_start_after_install_days = U.round(gap, 2);
        if (gap > ctx.cfg.s2_journal_gap_days && minUsn < ctx.cfg.s2_unwrapped_usn_max) { fired = true; times.push(first.ts); details.unwrapped_journal_starts_late = true; }
      }
    } else details.note = "no $J input; journal-start test skipped";
    return res("S2", "Change journal reset", fired ? "fired" : "clear", times, details);
  },
  ctx => {
    if (!ctx.events.size) return res("S3", "Event log discontinuity", V_NE, [], { reason: "no event logs" });
    const [install] = installTime(ctx), maxReport = ctx.cfg.s3_max_gaps_reported, gaps = [], times = [], oldest = [];
    const files = {}; for (const [k, v] of Object.entries(ctx.cfg.evtx_files || {})) files[k.toLowerCase()] = v;
    for (const [channel, evs] of ctx.events) {
      const recs = U.sorted(evs.filter(e => e.record_id !== null).map(e => [e.record_id, e.ts]), x => x);
      for (let i = 0; i + 1 < recs.length; i++) {
        const [r0, t0] = recs[i], [r1, t1] = recs[i + 1];
        if (r1 - r0 > 1) { gaps.push({ channel, after_record: r0, next_record: r1, missing: r1 - r0 - 1, from: F(t0), to: F(t1) }); times.push(t1); }
      }
      const meta = files[channel];
      if (meta && install && recs.length) {
        const firstTs = recs.map(r => r[1]).reduce((a, b) => (b < a ? b : a)), gap = Number(firstTs - install) / 1e7 / 86400;
        if ((meta.size_bytes || 0) < 0.9 * (meta.max_bytes || 0) && gap > ctx.cfg.s3_oldest_gap_days) {
          oldest.push(Object.assign({ channel, oldest_entry: F(firstTs), days_after_install: U.round(gap, 2) }, meta)); times.push(firstTs);
        }
      }
    }
    return res("S3", "Event log discontinuity", gaps.length || oldest.length ? "fired" : "clear", times,
      { record_gaps: gaps.slice(0, maxReport), record_gaps_total: gaps.length, oldest_entry_too_recent: oldest });
  },
  ctx => {
    if (!(ctx.events.get("system") || []).length && !(ctx.events.get("security") || []).length) return res("S4", "Clock change", V_NE, [], { reason: "no System or Security log" });
    const hits = find(ctx, "security", new Set([4616])).concat(find(ctx, "system", new Set([1]), "kernel-general"));
    const minShift = ctx.cfg.s4_min_shift_s, changes = [], times = [];
    for (const h of hits) {
      const f = DATES.payloadFields(h.payload), old = DATES.parseTs(f.PreviousTime || f.OldTime), nw = DATES.parseTs(f.NewTime);
      const shift = old === null || nw === null ? null : Number(nw - old) / 1e7;
      if (shift !== null && Math.abs(shift) < minShift) continue;
      changes.push({ channel: h.channel, event_id: h.event_id, time: F(h.ts), old: F(old), new: F(nw), shift_s: shift === null ? null : U.round(shift, 3) });
      times.push(h.ts);
    }
    return res("S4", "Clock change", changes.length ? "fired" : "clear", times, { changes, min_shift_s: minShift });
  },
  ctx => {
    if (!ctx.has_usn) return res("S5", "Missing expected artifacts", V_NE, [], { reason: "no $J data" });
    const loadedPf = ctx.pf_names, loadedLnk = new Set(ctx.lnks.map(l => (l.source_path || "").split("\\").pop()));
    const seenPf = new Map(), seenLnk = new Map(), deletes = [];
    for (const u of ctx.usn_rows) {
      const name = (u.name || "").toLowerCase();
      if (name.endsWith(".pf")) { if (!seenPf.has(name)) seenPf.set(name, u.ts); }
      else if (name.endsWith(".lnk") && (u.path === null || u.path.includes("\\users\\"))) { if (!seenLnk.has(name)) seenLnk.set(name, u.ts); }
      else continue;
      if (u.reasons.toLowerCase().includes("filedelete")) deletes.push({ name: u.name, time: F(u.ts), _t: u.ts });
    }
    const missingPf = U.sorted([...seenPf.keys()].filter(n => !loadedPf.has(n)), x => x), missingLnk = U.sorted([...seenLnk.keys()].filter(n => !loadedLnk.has(n)), x => x);
    const miss = new Set(missingPf.concat(missingLnk));
    return res("S5", "Missing expected artifacts", missingPf.length || missingLnk.length ? "fired" : "clear", deletes.filter(d => miss.has(d.name.toLowerCase())).map(d => d._t),
      { prefetch_in_journal_but_absent: missingPf, lnk_in_journal_but_absent: missingLnk, deletions: deletes.map(d => ({ name: d.name, time: d.time })) });
  },
];
DATES.evaluateIndicators = ctx => IND.map(fn => fn(ctx));

/* ---- scoring ------------------------------------------------------------------------------------ */
DATES.baselineRates = rows => {
  const c = {}; for (const r of RIDS_D) c[r] = { violated: 0, evaluable: 0 };
  for (const [, rid, o] of rows) { if (o === V_NE) continue; c[rid].evaluable++; if (o === V_BAD) c[rid].violated++; }
  for (const v of Object.values(c)) v.p_r = (v.violated + 0.5) / (v.evaluable + 1);
  return c;
};
DATES.computeWeights = (cfg, calibration, mode) => {
  mode = mode || cfg.weight_mode;
  const rates = (calibration || {}).rates || {}, out = {};
  for (const rid of RIDS_D) {
    const p = (rates[rid] || {}).p_r, spec = p ? Math.log(1 / p) : 1.0, src = cfg.rule_reference_source[rid];
    const sc = cfg.tamper_scores[src], resist = 4.0 - sc.reduce((a, b) => a + b, 0) / sc.length;
    out[rid] = { weight: { equal: 1.0, specificity: spec, full: spec * resist }[mode], p_r: p === undefined ? null : p, specificity: spec, resistance: resist, reference_source: src };
  }
  return out;
};
DATES.degradedRules = indicators => {
  const out = new Map();
  for (const ind of indicators) {
    if (ind.status !== "fired") continue;
    const hit = new Set(CFG0.INDICATOR_DEGRADES[ind.id]);
    for (const rid of RIDS_D) if (CFG0.RULE_SOURCES[rid].some(s => hit.has(s)) || (hit.has("clock") && CFG0.TIME_RULES.includes(rid))) {
      if (!out.has(rid)) out.set(rid, []); out.get(rid).push(ind.id);
    }
  }
  return out;
};
DATES.scoreFiles = (ctx, rows, weights, indicators, theta, minEvaluable) => {
  const byKey = new Map();
  for (const [key, rid, o, d] of rows) { if (!byKey.has(key)) byKey.set(key, {}); byKey.get(key)[rid] = [o, d]; }
  const degraded = DATES.degradedRules(indicators), results = [];
  for (const [key, rules] of byKey) {
    let num = 0, den = 0; const evaluable = [], fired = [], weak = [], weakFired = [], evidence = [];
    for (const rid of RIDS_D) {
      const [o, d] = rules[rid] || [V_NE, {}];
      if (o === V_NE) continue;
      const w = weights[rid].weight; evaluable.push(rid); den += w;
      if (o === V_BAD) { num += w; fired.push(rid); if (degraded.has(rid)) weakFired.push(rid); if ("_evidence_time" in d) evidence.push(d._evidence_time); }
      else if (o === V_OK && degraded.has(rid)) weak.push(rid);
    }
    const score = den ? num / den : 0, f = ctx.mft.get(key), clean = evaluable.filter(r => !degraded.has(r));
    const fallback = [f.si_e, f.fn_e].filter(x => x);
    results.push({ entry: f.entry, seq: f.seq, path: f.path, score, evaluable: evaluable.length, coverage: evaluable.length / RIDS_D.length,
      fired, evaluable_rules: evaluable, consistent_from_degraded_sources: weak, violated_from_degraded_sources: weakFired,
      confidence: evaluable.length ? clean.length / evaluable.length : 0, flagged: score > theta && evaluable.length >= minEvaluable,
      anchor: evidence.length ? bigMax(evidence) : (fallback.length ? bigMax(fallback) : null),
      anchor_source: evidence.length ? "journal/prefetch record" : "latest SIA-E/FNA-E" });
  }
  return U.sorted(results, r => [-r.score, -r.evaluable, r.entry]);
};
DATES.systemScore = (indicators, cfg) => {
  const w = cfg.indicator_weights, ev = indicators.filter(i => i.status !== V_NE);
  const den = ev.reduce((a, i) => a + (w[i.id] == null ? 1.0 : w[i.id]), 0), num = ev.filter(i => i.status === "fired").reduce((a, i) => a + (w[i.id] == null ? 1.0 : w[i.id]), 0);
  return [den ? num / den : 0, ev.length];
};
DATES.cluster = (ctx, scored, indicators, cfg) => {
  const window = DATES.seconds(cfg.cluster_window_s), pad = DATES.seconds(cfg.cluster_pad_s);
  const flagged = U.sorted(scored.filter(r => r.flagged && r.anchor), r => r.anchor), groups = []; let cur = [];
  for (const r of flagged) { if (cur.length && r.anchor - cur[cur.length - 1].anchor > window) { groups.push(cur); cur = []; } cur.push(r); }
  if (cur.length) groups.push(cur);
  return groups.map((g, i) => {
    const start = g[0].anchor, end = g[g.length - 1].anchor, runs = ctx.pfRunsBetween(start - pad, end + pad);
    const inds = U.sorted([...new Set(indicators.filter(ind => ind.times.some(t => start - pad <= t && t <= end + pad)).map(ind => ind.id))], x => x);
    for (const r of g) r.cluster = i + 1;
    return { cluster: i + 1, start: F(start), end: F(end), files: g.length, paths: g.map(r => r.path),
      prefetch_runs: U.sorted([...new Set(runs.map(([t, exe]) => exe + " @ " + F(t)))], x => x), indicators: inds };
  });
};

/* ---- plain words (explain.py) and the report data (ntfs_briefing.build_data) ----------------------- */
const RP = PYDATA.explain.RULE_PLAIN;
DATES.ruleName = rid => (RP[rid] || [rid, ""])[0];
DATES.ruleWhat = rid => (RP[rid] || ["", ""])[1];
DATES.nice = ts => {
  const t = String(ts == null ? "" : ts);
  const parts = t.split(" ");
  if (parts.length >= 2) {
    const dp = parts[0].split("-");
    if (dp.length === 3 && /^\s*[+-]?\d+\s*$/.test(dp[2]) && /^\s*[+-]?\d+\s*$/.test(dp[1])) {
      const mi = parseInt(dp[1], 10) - 1, idx = mi < 0 ? mi + 12 : mi;
      if (idx >= 0 && idx < 12) return parseInt(dp[2], 10) + " " + U.MONTHS[idx] + " " + dp[0] + ", " + parts[1].split(".")[0] + " UTC";
    }
  }
  return t || "?";
};
const which = (fields, one, many) => {
  const names = fields.map(f => f.split("si_c").join("created").split("si_m").join("last-changed"));
  if (!names.length) return many.replace("@", "created or last-changed");
  return (names.length > 1 ? many : one).replace("@", names.join(" and "));
};
const gv = (d, ...keys) => { for (const k of keys) if (d[k] != null && d[k] !== "") return d[k]; return "?"; };
const days = v => { const x = Number(typeof v === "string" ? U.strip(v) : v); if (v === "?" || v == null || isNaN(x)) return String(v); return U.fmtInt(U.round(x)); };
DATES.say = (rid, d) => {
  const n = (...k) => DATES.nice(gv(d, ...k));
  try {
    if (rid === "R1") return "Windows' change journal last recorded a change to this file at " + n("bic_time") + ", but the file's own record claims it last changed at " + n("si_e") + ", before the journal's entry.";
    if (rid === "R2") return "A shortcut to this file carries the last-change date " + n("lnk_si_e") + ", but the file itself says " + n("target_si_e") + ". The two are written together and should match.";
    if (rid === "R3") { const bad = (d.lnks_earlier && d.lnks_earlier.length ? d.lnks_earlier : [{}]); return "A shortcut to this file was created at " + DATES.nice(gv(bad[0], "lnk_si_c")) + ", before the file it points to claims to have existed (" + n("target_si_c") + "). A shortcut cannot be made before its target."; }
    if (rid === "R4") return "A shortcut records this file being opened at " + n("lnk_si_a") + ", later than the file's own last-opened date of " + n("target_si_a") + ".";
    if (rid === "R5") return "The file's " + which(d.outside_session || [], "@ date falls", "@ dates fall") + " outside every time a user was logged on, according to the event log. Files normally change only while someone is signed in.";
    if (rid === "R6") return "The creation date Windows shows (" + n("si_c") + ") is earlier than the file system's own protected copy (" + n("fn_c") + "). The visible date was likely set back.";
    if (rid === "R7") return "The file's " + which(d.zero_fields || [], "@ date is", "@ dates are") + " exactly on a whole second, with no fraction of a second at all. Real activity almost never does that, but date-changing tools commonly do.";
    if (rid === "R8") return "Windows' change journal first recorded this file being created at " + n("filecreate_time") + ", after the creation date it now shows (" + n("si_c") + "). A file cannot be created after it already existed.";
    if (rid === "R9") { const bad = (d.mismatches && d.mismatches.length ? d.mismatches : [{}]); return "A shortcut kept an earlier copy of this file's creation date (" + DATES.nice(gv(bad[0], "embedded_target_c")) + ") that no longer matches the file's current creation date (" + n("target_si_c") + ")."; }
    if (rid === "R10") { const hit = (d.coinciding_executions && d.coinciding_executions.length ? d.coinciding_executions : [{}])[0]; return "This file's date changed at " + DATES.nice(gv(hit, "bic_time")) + ", the same moment the program " + gv(hit, "exe") + " ran, a program not normally associated with this file."; }
    if (rid === "R11") return "This file claims to have been created about " + days(gv(d, "older_than_neighbors_days")) + " days before the files whose records sit next to it on the disk, which usually means its date was set back.";
  } catch (e) { /* fall through */ }
  return DATES.ruleWhat(rid);
};
const NB = PYDATA.ntfs_briefing;
const sortedDeep = v => { if (Array.isArray(v)) return v.map(sortedDeep); if (v && typeof v === "object") { const o = {}; for (const k of Object.keys(v).sort(U.cmpStr)) o[k] = sortedDeep(v[k]); return o; } return v; };
DATES.buildData = (rows, scored, indicators, clusters, sys, meta) => {
  const outcomes = new Map(), activity = {};
  for (const r of RIDS_D) activity[r] = { evaluable: 0, violated: 0 };
  for (const [key, rid, o, d] of rows) {
    if (!outcomes.has(key)) outcomes.set(key, {}); outcomes.get(key)[rid] = [o, d];
    if (o !== V_NE) { activity[rid].evaluable++; if (o === V_BAD) activity[rid].violated++; }
  }
  const flagged = scored.filter(r => r.flagged), strong = Math.max(Number(meta.theta), NB.STRONG), leads = [];
  for (const r of U.sorted(flagged, r => [-r.score, -r.fired.length])) {
    const key = r.entry + "," + r.seq, oc = outcomes.get(key);
    const fired = r.fired.map(rid => { const d = oc[rid][1], tech = {}; for (const k of Object.keys(d)) if (!k.startsWith("_")) tech[k] = d[k];
      return { id: rid, name: DATES.ruleName(rid), say: DATES.say(rid, d), tech: sortedDeep(tech) }; });
    const status = {}; for (const rid of RIDS_D) { const [o, d] = oc[rid] || [V_NE, {}]; status[rid] = [o, d.reason || ""]; }
    const look = r.score >= strong && r.fired.length >= 2;
    leads.push({ path: r.path, entry: r.entry, seq: r.seq, score: U.round(r.score * 100), tier: look ? "Look first" : "Worth a look", cls: look ? "hot" : "warn",
      evaluable: r.evaluable, confidence: U.round(r.confidence * 100), cluster: r.cluster == null ? null : r.cluster, fired, status, weak: r.violated_from_degraded_sources });
  }
  const warnings = indicators.map(i => ({ id: i.id, name: i.name, status: i.status, plain: PYDATA.explain.INDICATOR_PLAIN[i.id] || "", details: i.details }));
  const rules = {}; for (const rid of RIDS_D) rules[rid] = { name: DATES.ruleName(rid), what: DATES.ruleWhat(rid) };
  const config = {}; for (const [k, v] of Object.entries(meta.config)) if (v !== null && ["number", "string", "boolean"].includes(typeof v)) config[k] = v;
  return { generated: meta.generated || "", theta: meta.theta, weight_mode: meta.weight_mode, calibration: meta.calibration == null ? null : meta.calibration, inputs: meta.inputs,
    counts: { scored: scored.length, flagged: flagged.length, look_first: leads.filter(l => l.tier === "Look first").length },
    system: { score: U.round(sys[0] * 100), evaluable: sys[1], level: warnings.some(w => w.status === "fired") ? "degraded" : "clear" },
    leads, activity, clusters: clusters.map(c => ({ start: c.start, end: c.end, files: c.files, paths: c.paths, prefetch: c.prefetch_runs, indicators: c.indicators })),
    warnings, rules, config };
};

/* ---- the saved files (report.write_outputs) ---------------------------------------------------------- */
const pub = d => { const o = {}; for (const k of Object.keys(d)) if (!k.startsWith("_")) o[k] = d[k]; return o; };
DATES.outputs = (ctx, rows, scored, indicators, clusters, weights, sys, meta) => {
  const byKey = new Map(scored.map(r => [r.entry + "," + r.seq, r]));
  let scores = U.csvRow(["rank", "entry", "seq", "path", "score", "flagged", "evaluable", "coverage", "confidence", "fired", "consistent_from_degraded_sources", "violated_from_degraded_sources", "cluster"]);
  scored.forEach((r, i) => { scores += U.csvRow([i + 1, r.entry, r.seq, r.path, U.fixed(r.score, 4), r.flagged ? 1 : 0, r.evaluable, U.fixed(r.coverage, 3), U.fixed(r.confidence, 3),
    r.fired.join(" "), r.consistent_from_degraded_sources.join(" "), r.violated_from_degraded_sources.join(" "), r.cluster == null ? "" : r.cluster]); });
  let outcomes = U.csvRow(["entry", "seq", "path", "rule", "outcome", "details"]);
  for (const [key, rid, o, d] of rows) { const s = byKey.get(key); outcomes += U.csvRow([s.entry, s.seq, s.path, rid, o, U.pyJson(pub(d), { sortKeys: true })]); }
  const indJson = U.pyJson(indicators.map(i => { const o = Object.assign({}, i); delete o.times; return o; }), { indent: 2 });
  let cl = U.csvRow(["cluster", "start", "end", "files", "paths", "prefetch_runs", "indicators"]);
  for (const c of clusters) cl += U.csvRow([c.cluster, c.start, c.end, c.files, c.paths.join("; "), c.prefetch_runs.join("; "), c.indicators.join(" ")]);
  const run = Object.assign({ generated: U.nowIso() }, meta, { weights, system_score: sys[0], indicators_evaluable: sys[1] });
  return { "scores.csv": scores, "outcomes.csv": outcomes, "indicators.json": indJson, "clusters.csv": cl, "run.json": U.pyJson(run, { indent: 2 }) };
};

/* ---- ingest and analyze (pipeline.py) -------------------------------------------------------------- */
/* inputs: [{kind: "image"|"csv", name, src, text?}]. With an image, the MFT is read from it (rules R6, R7, R11). */
DATES.ingest = (inputs, cfg, on) => {
  const db = new CaseDB(); on = on || (() => {});
  const image = inputs.find(i => i.kind === "image");
  if (image) {
    const vol = image.vol || new NTFS.NTFSVolume(image.src);
    let n = 0; for (const r of vol.mftRows()) { db.putMft(r); n++; }
    db.record("mft", image.name, n, image.sha256 || shaOf(image.src));
    on("loaded", { kind: "mft", file: image.name + " (MFT read from the image)", rows: n });
    return db;
  }
  const csvs = new Map();
  for (const f of U.sorted(inputs.filter(i => i.kind === "csv"), i => i.name)) {
    const kind = DATES.classifyCsv(f.name);
    if (kind) { if (!csvs.has(kind)) csvs.set(kind, []); csvs.get(kind).push(f); }
  }
  if (!csvs.has("mft")) throw new InputError("No MFT CSV among these files. Run the parsers first (see scripts/run_parsers.ps1); the folder should hold mft.csv and, ideally, usn.csv, lnk.csv, prefetch.csv and evtx*.csv.");
  const L = { mft: DATES.loadMft, usn: DATES.loadUsn, prefetch: DATES.loadPrefetch, evtx: DATES.loadEvtx };
  for (const [kind, files] of csvs) for (const f of files) {
    const sha = shaOf(f.src), text = f.text != null ? f.text : U.utf8(f.src.read(0, f.src.size));
    const n = kind === "lnk" ? DATES.loadLnk(db, text, f.name, sha, cfg.mount_prefix) : L[kind](db, text, f.name, sha);
    on("loaded", { kind, file: f.name, rows: n });
  }
  return db;
};
DATES.analyze = (db, cfg, opt) => {
  opt = opt || {}; const on = opt.on || (() => {});
  const ctx = new Context(db, cfg);
  on("stage", { stage: "rules", total: ctx.candidates.length });
  const rows = DATES.evaluateAll(ctx, (n, t) => on("rules", { n, total: t }));
  let calibration = null, calPath = null;
  if (opt.selfCalibrate !== false) { calibration = { rates: DATES.baselineRates(rows) }; calPath = "(rates measured on this image)"; }
  const theta = cfg.theta, mode = cfg.weight_mode, weights = DATES.computeWeights(cfg, calibration, mode);
  on("stage", { stage: "indicators" });
  const indicators = DATES.evaluateIndicators(ctx);
  on("stage", { stage: "score", weights });
  const scored = DATES.scoreFiles(ctx, rows, weights, indicators, theta, cfg.min_evaluable);
  const clusters = DATES.cluster(ctx, scored, indicators, cfg), sys = DATES.systemScore(indicators, cfg);
  const meta = { db: "(in the browser)", theta, weight_mode: mode, calibration: calPath || (calibration ? "(in memory)" : null), config: cfg, inputs: db.inputs };
  const files = DATES.outputs(ctx, rows, scored, indicators, clusters, weights, sys, meta);
  const data = DATES.buildData(rows, scored, indicators, clusters, sys, Object.assign({}, meta, { generated: U.nowIso() }));
  return { data, files, rows, scored, indicators, clusters, summary: { scored: scored.length, flagged: scored.filter(r => r.flagged).length, clusters: clusters.length, system_score: sys[0] } };
};
/* for the Node tests: inputs as [{kind: "image"|"mft"|"usn"|..., src, name}] */
DATES.runFromArgs = args => {
  const cfg = DATES.defaults();
  const inputs = args.map(a => (a.kind === "image" ? { kind: "image", name: a.name, src: a.src } : { kind: "csv", name: a.name, src: a.src }));
  const db = DATES.ingest(inputs, cfg);
  const out = DATES.analyze(db, cfg, { selfCalibrate: true });
  return { data: out.data, files: out.files };
};
