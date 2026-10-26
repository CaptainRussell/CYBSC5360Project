/* First-look triage: a port of ads/triage.py (checks C1-C7 and F1, the score, and
   to_json), with a ZIP reader that follows Python's zipfile. The tables (check
   names and wording, plain names of file types, the stop-word list) come from
   PYDATA, generated from the Python modules when the page is built. */

const TRI = {};
const T = PYDATA.triage;
const CONSISTENT = "consistent", VIOLATED = "violated", NOT_EVALUABLE = "not_evaluable";
TRI.CONSISTENT = CONSISTENT; TRI.VIOLATED = VIOLATED; TRI.NOT_EVALUABLE = NOT_EVALUABLE;
const STOP = new Set(T.STOP);
const JAVA_LIKE = new Set(T.JAVA_LIKE);

TRI.label = t => T.TYPE_LABEL[t] || t.toUpperCase();
TRI.plain = t => (T.PLAIN[t] || ["a " + t + " file"])[0];
TRI.plainShort = t => (T.PLAIN[t] ? T.PLAIN[t][1] : t + " file");
TRI.plainPlural = t => (T.PLAIN[t] ? T.PLAIN[t][2] : t + " files");
TRI.extPlain = e => T.EXT_PLAIN[e] || "a ." + e + " file";
TRI.plainEmbedded = what => ({ "RAR archive": "a hidden RAR archive (a bundle of files)", "ZIP archive": "a hidden ZIP archive (a bundle of files)",
  "7-Zip archive": "a hidden 7-Zip archive", "JPEG image": "a second, hidden photo", "PNG image": "a hidden picture",
  "PDF document": "a hidden PDF document", "OLE document": "a hidden Office document", "Windows executable": "a hidden Windows program" })[what.split(" at +")[0]] || "hidden data";
TRI.humanSize = n => {
  n = Number(n);
  for (const unit of ["bytes", "KB", "MB", "GB"]) {
    if (n < 1024 || unit === "GB") return unit === "bytes" ? Math.trunc(n) + " " + unit : (n >= 10 ? U.fixed(n, 0) : U.fixed(n, 1)) + " " + unit;
    n /= 1024;
  }
};
const TIME_RE = /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})$/;
TRI.humanTime = s => {
  const m = TIME_RE.exec(s || "");
  if (!m) return s || "unknown";
  const [y, mo, d, h, mi, se] = m.slice(1).map(Number);
  if (!U.validDate(y, mo, d) || h > 23 || mi > 59 || se > 59) return s || "unknown";
  return d + " " + U.MONTHS[mo - 1] + " " + y + ", " + (h % 12 || 12) + ":" + String(mi).padStart(2, "0") + ":" + String(se).padStart(2, "0") + " " + (h < 12 ? "AM" : "PM");
};
const and = items => items.length === 1 ? items[0] : items.length ? items.slice(0, -1).join(", ") + " and " + items[items.length - 1] : "";
TRI.ext = name => { const base = name.split("/").pop(); return U.strip(base, ".").includes(".") ? base.split(".").pop().toLowerCase() : ""; };

const NAME_TOKEN = /[A-Za-z0-9_\-]{1,80}\.[A-Za-z0-9]{2,5}/g;
const PHRASE = /\b(secret|pass|password|passcode|passphrase|pwd|pin)[ \t\n\r\f\v]+(?:is|was)[ \t\n\r\f\v]*[:=]?[ \t\n\r\f\v]*["'\x93]?([\x21-\x7e]{3,64})/gi;
const TOKEN_TAIL = '.,;:!?)"\'\x94';
function passwordToken(tok) {
  const t = U.rstrip(tok, TOKEN_TAIL);
  if (t.length < 4 || STOP.has(t.replace(/[A-Z]/g, c => c.toLowerCase()))) return null;
  if (/[0-9]/.test(t) || (/[a-z]/.test(t) && /[A-Z]/.test(t.slice(1))) || t.length >= 12) return t;
  return null;
}
function noiseReason(item) {
  const n = item.name;
  if (n.startsWith("._")) return "Mac hidden helper files (names starting \u201c._\u201d)";
  if (n === ".DS_Store") return "Mac folder-view settings (.DS_Store)";
  if (item.path.includes("__MACOSX/")) return "Mac helper files inside archives (__MACOSX)";
  if (n.startsWith(".BC.T_") || /^_B~\d\.T_/.test(n) || n.startsWith("._.BC.T_")) return "Leftover Mac copying files (.BC.T_)";
  if (["thumbs.db", "desktop.ini"].includes(n.toLowerCase())) return "Windows folder settings";
  if (item.deleted && item.unrecoverable) return "Deleted files whose contents are gone";
  if (item.size === 0) return "Empty files";
  return null;
}
TRI.rar4Members = blob => {
  const out = []; let i = 7;
  if (!U.eq(blob, 0, U.bytes("Rar!\x1a\x07\x00"))) return out;
  while (i + 7 <= blob.length && out.length < 1000) {
    const htype = blob[i + 2], flags = U.u16(blob, i + 3), hsize = U.u16(blob, i + 5);
    if (hsize < 7) break;
    if (htype === 0x73 && (flags & 0x0080)) { out.push({ name: "(file names encrypted)", encrypted: true }); break; }
    let add = 0;
    if ((flags & 0x8000) || htype === 0x74) { U.need(blob, i + 7, 4); add = U.u32(blob, i + 7); }
    if (htype === 0x74) {
      U.need(blob, i + 26, 2); U.need(blob, i + 11, 4);
      const nameB = blob.subarray(i + 32, i + 32 + U.u16(blob, i + 26)), z = nameB.indexOf(0);
      out.push({ name: U.utf8(z >= 0 ? nameB.subarray(0, z) : nameB), encrypted: !!(flags & 0x04), size: U.u32(blob, i + 11) });
    }
    if (htype === 0x7b) break;
    i += hsize + add;
  }
  return out;
};

/* ---- zipfile ------------------------------------------------------------------- */
class BadZipFile extends Error {}
TRI.BadZipFile = BadZipFile;
const SIG_EOCD = U.bytes("PK\x05\x06"), SIG_LOC64 = U.bytes("PK\x06\x07"), SIG_EOCD64 = U.bytes("PK\x06\x06");
const SIG_CEN = U.bytes("PK\x01\x02"), SIG_LOC = U.bytes("PK\x03\x04");
const sanitize = name => { const z = name.indexOf("\x00"); if (z >= 0) name = name.slice(0, z); return name.split("\\").join("/"); };   // Windows Python: os.sep is "\\"
function endRecData(d) {
  const n = d.length;
  const ecd = (rec, comment, loc) => endRec64(d, loc, { size: U.u32(rec, 12), offset: U.u32(rec, 16), comment, location: loc });
  if (n >= 22) {
    const r = d.subarray(n - 22);
    if (U.eq(r, 0, SIG_EOCD) && r[20] === 0 && r[21] === 0) return ecd(r, new Uint8Array(0), n - 22);
  }
  const maxStart = Math.max(n - 65535 - 22, 0), data = d.subarray(maxStart), start = U.rfind(data, SIG_EOCD);
  if (start >= 0) {
    const rec = data.subarray(start, start + 22);
    if (rec.length !== 22) return null;
    return ecd(rec, data.subarray(start + 22, start + 22 + U.u16(rec, 20)), maxStart + start);
  }
  return null;
}
function endRec64(d, offset, er) {
  offset -= 20;
  if (offset < 0) return er;
  const loc = d.subarray(offset, offset + 20);
  if (loc.length !== 20) throw new BadZipFile("Unknown I/O error");
  if (!U.eq(loc, 0, SIG_LOC64)) return er;
  const diskno = U.u32(loc, 4), reloff = U.u64n(loc, 8), disks = U.u32(loc, 16);
  if (diskno !== 0 || disks > 1) throw new BadZipFile("zipfiles that span multiple disks are not supported");
  offset -= 56;
  if (reloff > offset) throw new BadZipFile("Corrupt zip64 end of central directory locator");
  let extrasz = offset - reloff, rec = d.subarray(reloff, reloff + 56);
  if (rec.length !== 56) throw new BadZipFile("Unknown I/O error");
  if (!U.eq(rec, 0, SIG_EOCD64) && reloff !== offset) { extrasz = 0; rec = d.subarray(offset, offset + 56); if (rec.length !== 56) throw new BadZipFile("Unknown I/O error"); }
  if (!U.eq(rec, 0, SIG_EOCD64)) throw new BadZipFile("Zip64 end of central directory record not found");
  const sz = U.u64n(rec, 4), dirsize = U.u64n(rec, 40), diroffset = U.u64n(rec, 48);
  if (diroffset + dirsize !== reloff || sz + 12 !== 56 + extrasz) throw new BadZipFile("Corrupt zip64 end of central directory record");
  er.size = dirsize; er.offset = diroffset; er.location = offset - extrasz;
  return er;
}
function decodeName(b, utf) {
  if (utf) { try { return U.utf8strict(b); } catch (e) { throw new BadZipFile("bad utf-8 name"); } }
  return U.cp437(b);
}
TRI.zipOpen = d => {
  const er = endRecData(d);
  if (!er) throw new BadZipFile("File is not a zip file");
  const concat = er.location - er.size - er.offset, startDir = er.offset + concat;
  if (startDir < 0) throw new BadZipFile("Bad offset for central directory");
  const cd = d.subarray(startDir, startDir + er.size);
  const list = []; let total = 0, p = 0;
  const rd = n => { const b = cd.subarray(p, p + n); p += b.length; return b; };
  while (total < er.size) {
    const c = rd(46);
    if (c.length !== 46) throw new BadZipFile("Truncated central directory");
    if (!U.eq(c, 0, SIG_CEN)) throw new BadZipFile("Bad magic number for central directory");
    const fnLen = U.u16(c, 28), exLen = U.u16(c, 30), cmLen = U.u16(c, 32);
    const fnB = rd(fnLen), crcName = U.crc32(fnB), flags = U.u16(c, 8);
    const orig = decodeName(fnB, flags & 0x800);
    const x = { orig_filename: orig, filename: sanitize(orig), flag_bits: flags, compress_type: U.u16(c, 10),
      CRC: U.u32(c, 16), compress_size: U.u32(c, 20), file_size: U.u32(c, 24), header_offset: U.u32(c, 42), extract_version: c[6] };
    const extra = rd(exLen); rd(cmLen);
    if (x.extract_version > 63) throw new BadZipFile("zip file version " + (x.extract_version / 10));
    const t = U.u16(c, 12), dd = U.u16(c, 14);
    x.date_time = [(dd >> 9) + 1980, (dd >> 5) & 0xf, dd & 0x1f, t >> 11, (t >> 5) & 0x3f, (t & 0x1f) * 2];
    let e = extra;
    while (e.length >= 4) {
      const tp = U.u16(e, 0), ln = U.u16(e, 2);
      if (ln + 4 > e.length) throw new BadZipFile("Corrupt extra field");
      let data = e.subarray(4, ln + 4);
      if (tp === 0x0001) {
        const q = () => { if (data.length < 8) throw new BadZipFile("Corrupt zip64 extra field."); const v = U.u64n(data, 0); data = data.subarray(8); return v; };
        if (x.file_size === 0xffffffff) x.file_size = q();
        if (x.compress_size === 0xffffffff) x.compress_size = q();
        if (x.header_offset === 0xffffffff) x.header_offset = q();
      } else if (tp === 0x7075) {
        if (data.length < 5) throw new BadZipFile("Corrupt unicode path extra field (0x7075)");
        if (data[0] === 1 && U.u32(data, 1) === crcName) {
          let un; try { un = U.utf8strict(data.subarray(5)); } catch (err) { throw new BadZipFile("Corrupt unicode path extra field (0x7075)"); }
          if (un) x.filename = sanitize(un);
        }
      }
      e = e.subarray(ln + 4);
    }
    x.header_offset += concat;
    list.push(x);
    total += 46 + fnLen + exLen + cmLen;
  }
  let end = startDir;
  const byOff = U.sorted(list, z => z.header_offset);
  for (let k = byOff.length - 1; k >= 0; k--) { byOff[k]._end_offset = end; end = byOff[k].header_offset; }
  return { infolist: list, d };
};
TRI.zipRead = (z, x, notes) => {
  const d = z.d, h = d.subarray(x.header_offset, x.header_offset + 30);
  if (h.length !== 30) throw new BadZipFile("Truncated file header");
  if (!U.eq(h, 0, SIG_LOC)) throw new BadZipFile("Bad magic number for file header");
  const fnLen = U.u16(h, 26), exLen = U.u16(h, 28), lflags = U.u16(h, 6);
  const fname = d.subarray(x.header_offset + 30, x.header_offset + 30 + fnLen);
  if (x.flag_bits & 0x20) throw new Error("compressed patched data (flag bit 5)");
  if (x.flag_bits & 0x40) throw new Error("strong encryption (flag bit 6)");
  const fstr = lflags & 0x800 ? U.utf8strict(fname) : U.cp437(fname);
  if (fstr !== x.orig_filename) throw new BadZipFile("File name in directory and header differ.");
  const start = x.header_offset + 30 + fname.length + exLen;
  if (x._end_offset != null && start + x.compress_size > x._end_offset && x._end_offset !== x.header_offset) throw new BadZipFile("Overlapped entries");
  const comp = d.subarray(Math.min(start, d.length), start + x.compress_size);
  let out;
  if (x.compress_type === 0) {
    if (comp.length < Math.min(x.compress_size, x.file_size)) throw new Error("EOF");
    out = comp.subarray(0, x.file_size);
  } else if (x.compress_type === 8) out = U.inflate(comp, x.file_size);
  else {
    if (x.compress_type === 12 || x.compress_type === 14)
      notes.push("A " + (x.compress_type === 12 ? "bzip2" : "LZMA") + "-compressed archive member (" + x.filename + ") was not opened; the Python version opens it.");
    throw new Error("compression type " + x.compress_type);
  }
  if (U.crc32(out) !== x.CRC) throw new BadZipFile("Bad CRC-32");
  return out;
};

/* ---- the triage -------------------------------------------------------------------- */
class UnsupportedImage extends Error {}
TRI.UnsupportedImage = UnsupportedImage;
TRI.openVolume = src => {
  try { return new FAT.FATVolume(src); } catch (e) { if (!(e instanceof FAT.NotFAT)) throw e; }
  try { return new NTFS.NTFSVolume(src); } catch (e) {
    if (!(e instanceof NTFS.NotNTFS)) throw e;
    throw new UnsupportedImage(src.name + " holds neither a FAT nor an NTFS drive that the Artifact Disagreement Scorer can read.");
  }
};
const fmtTime = d => (d ? U.isoSec(d) : null);

class Triage {
  constructor(src, opt) {
    opt = opt || {};
    this.src = src; this.vol = TRI.openVolume(src);
    this.max_read = opt.max_read || T.MAX_READ;
    this.on = opt.on || (() => {});
    this.cacheBudget = opt.cacheBudget == null ? (384 << 20) : opt.cacheBudget;
    this.items = []; this.content = new Map(); this.cached = 0; this.notes = [];
  }
  data(i) {   // the file's content, as Python holds it in self.content
    const c = this.content.get(i.id);
    if (c) return c;
    return i._e ? this.vol.read(i._e, this.max_read) : new Uint8Array(0);
  }
  keep(i, data) {
    if (i.container !== null || (data.length <= (1 << 20) && this.cached + data.length <= this.cacheBudget)) {
      this.content.set(i.id, data); if (i.container === null) this.cached += data.length;
    }
  }
  collect() {
    this.dirs = 0;
    for (const e of this.vol.walk()) {
      if (e.is_dir) { this.dirs++; continue; }
      const data = this.vol.read(e, this.max_read);
      const item = { id: this.items.length, path: e.path, name: e.name, ext: TRI.ext(e.name), size: e.size, deleted: e.deleted,
        hidden: e.hidden, container: null, created: fmtTime(e.created), modified: fmtTime(e.modified),
        accessed: e.accessed ? U.isoDate(e.accessed) : null, unrecoverable: e.deleted && e.size > 0 && !data.length, _e: e };
      this.add(item, data);
      this.on("item", { item, pos: this.vol.position(e), n: this.items.length });
    }
    return this;
  }
  add(item, data) {
    [item.type, item.family] = data.length ? SNIFF.sniff(data) : ["empty", "text"];
    if (item.type === "ole") { const [k, enc, how] = SNIFF.oleKind(data); item.type = k; item.ole_encrypted = enc; item.ole_how = how; }
    item.noise = noiseReason(item);
    this.items.push(item);
    this.keep(item, data);
    if (item.type === "zip" && !item.noise && item.container === null && !JAVA_LIKE.has(item.ext)) {
      let z;
      try { z = TRI.zipOpen(data); } catch (err) { if (err instanceof BadZipFile || err instanceof U.StructError) return; throw err; }
      item.members = [];
      for (const zi of z.infolist) {
        if (zi.filename.endsWith("/")) continue;
        const enc = !!(zi.flag_bits & 1);
        item.members.push({ name: zi.filename, encrypted: enc, size: zi.file_size });
        let mdata;
        try { mdata = enc ? new Uint8Array(0) : TRI.zipRead(z, zi, this.notes).subarray(0, this.max_read); } catch (err) { mdata = new Uint8Array(0); }
        const dt = zi.date_time, p2 = v => String(v).padStart(2, "0");
        this.add({ id: this.items.length, path: item.path + " \u203a " + zi.filename, name: zi.filename.split("/").pop(), ext: TRI.ext(zi.filename),
          size: zi.file_size, deleted: false, hidden: false, container: item.path, created: null, accessed: null, zip_encrypted: enc,
          modified: String(dt[0]).padStart(4, "0") + "-" + p2(dt[1]) + "-" + p2(dt[2]) + " " + p2(dt[3]) + ":" + p2(dt[4]) + ":" + p2(dt[5]) }, mdata);
      }
    }
  }
  prepare() {
    const live = this.items.filter(i => !i.noise);
    this.byFolder = new Map();
    for (const i of live) {
      const folder = (i.container || "") + "|" + U.rsplit1(i.path, "/")[0];
      if (!this.byFolder.has(folder)) this.byFolder.set(folder, []);
      this.byFolder.get(folder).push(i); i._folder = folder;
    }
    const times = new U.Counter(live.filter(i => i.container === null && i.modified).map(i => i.modified));
    this.n_timed = times.total(); this.time_counts = times;
    const top = times.mostCommon(1);
    [this.bulk_time, this.bulk_share] = top.length ? [top[0][0], top[0][1] / this.n_timed] : [null, 0];
    this.mentioned = new Set();
    for (const i of live) {
      if (i.family === "text" || ["html", "xml", "pdf"].includes(i.type)) {
        const s = U.latin1(this.data(i));
        for (const m of s.matchAll(NAME_TOKEN)) this.mentioned.add(m[0].toLowerCase());
      }
    }
  }
  c1(i, data) {
    const exp = PYDATA.sniff.EXPECTED[i.ext];
    if (exp == null || !data.length) return [NOT_EVALUABLE, { reason: exp == null ? "extension not judged" : "no content" }];
    const t = i.type, base = ["encrypted-ooxml", "word97", "excel97", "ppt97"].includes(t) ? "ole" : t;
    if (exp.includes(base) || exp.includes(t)) return [CONSISTENT, { type: t }];
    if (SNIFF.STRONG_FAMILIES.has(i.family) || base === "ole") {
      const fb = U.hex(data.subarray(0, 8), " ", true);
      return [VIOLATED, { extension: i.ext, content: t, first_bytes: fb, name_says: TRI.extPlain(i.ext), inside_is: TRI.plain(t),
        say: "The name ends in \u201c." + i.ext + "\u201d, which means " + TRI.extPlain(i.ext) + ", but the file is really " + TRI.plain(t) + ".",
        tech: "First bytes " + fb + " are the signature of " + TRI.label(t) + "." }];
    }
    return [NOT_EVALUABLE, { reason: "content has no strong signature", type: t }];
  }
  c2(i, data) {
    const finder = SNIFF.END_FINDERS[i.type];
    if (!finder) return [NOT_EVALUABLE, { reason: "format has no end marker checked" }];
    const end = finder(data);
    if (end === null) return [NOT_EVALUABLE, { reason: "end marker not found" }];
    const tail = data.subarray(end), trailing = tail.length;
    if (trailing < 16 || !U.bstrip(tail, [0, 0xff, 32, 13, 10, 9]).length) return [CONSISTENT, { end_offset: end, trailing_bytes: trailing }];
    const what = SNIFF.describeBytes(tail);
    const d = { end_offset: end, trailing_bytes: trailing, file_size: data.length, trailing_starts: U.hex(tail.subarray(0, 8), " ", true), trailing_is: what };
    if (what && what.startsWith("RAR")) d.hidden_members = TRI.rar4Members(tail);
    if (i.type === "pdf" && trailing < 4096 && !what) return [CONSISTENT, d];
    const kind = TRI.plain(i.type).split(" (")[0];
    d.say = kind[0].toUpperCase() + kind.slice(1) + " should end after " + TRI.humanSize(end) + ", but the file keeps going for another " + TRI.humanSize(trailing) + ".";
    if (what) {
      d.say += " That extra part is " + TRI.plainEmbedded(what);
      const names = (d.hidden_members || []).map(m => m.name);
      d.say += names.length ? " holding " + names.join(", ") + "." : ".";
    }
    d.tech = "End-of-image marker ends at byte " + U.fmtInt(end) + "; " + U.fmtInt(trailing) + " trailing bytes start with " + d.trailing_starts + ".";
    return [VIOLATED, d];
  }
  c3(i, data) {
    const t = i.type, locked = "This file is locked with a password. Nobody can read it without the password.";
    if (["encrypted-ooxml", "word97", "excel97", "ppt97", "ole"].includes(t)) {
      const enc = i.ole_encrypted;
      if (enc == null) return [NOT_EVALUABLE, { reason: "OLE kind without an encryption flag checked" }];
      if (enc) return [VIOLATED, { how: i.ole_how, say: locked, tech: i.ole_how + "." }];
      return [CONSISTENT, { type: t }];
    }
    if (i.zip_encrypted) return [VIOLATED, { how: "ZIP entry encryption flag", say: locked, tech: "ZIP entry encryption flag set." }];
    if (t === "zip") {
      const enc = (i.members || []).filter(m => m.encrypted).map(m => m.name);
      if (enc.length) return [VIOLATED, { encrypted_members: enc, tech: "Encrypted entries: " + enc.join(", ") + ".",
        say: "Files inside this archive are locked with a password: " + enc.join(", ") + "." }];
      return [CONSISTENT, {}];
    }
    if (t === "pdf") {
      const ENC = U.bytes("/Encrypt");
      if (U.contains(data.subarray(Math.max(0, data.length - 65536)), ENC) || U.contains(data.subarray(0, 4096), ENC))
        return [VIOLATED, { how: "PDF /Encrypt dictionary", say: locked, tech: "PDF /Encrypt dictionary." }];
      return [CONSISTENT, {}];
    }
    if (t === "rar") {
      const m = TRI.rar4Members(data);
      if (m.some(x => x.encrypted)) return [VIOLATED, { members: m, say: locked, tech: "RAR file header password flag." }];
      return [CONSISTENT, { members: m }];
    }
    return [NOT_EVALUABLE, { reason: "not an encryptable container" }];
  }
  c4(i, data) {
    if (!data.length) return [NOT_EVALUABLE, { reason: "no content" }];
    const s = U.latin1(data), hits = [];
    PHRASE.lastIndex = 0;
    for (const m of s.matchAll(PHRASE)) {
      const tok = passwordToken(m[2]);
      if (!tok) continue;
      const a = Math.max(0, m.index - 30), b = Math.min(s.length, m.index + m[0].length + 10);
      const ctx = s.slice(a, b).replace(/[^\x20-\x7e]/g, ".");
      hits.push({ offset: m.index, phrase: m[0].slice(0, 80), candidate: tok, context: ctx });
      if (hits.length >= 5) break;
    }
    if (!hits.length) return [CONSISTENT, {}];
    const phrase = U.rstrip(U.strip(hits[0].phrase), ".");
    const say = i.family === "executable"
      ? "This is " + TRI.plain(i.type) + ", which should hold only computer code, yet it contains the plain sentence \u201c" + phrase + "\u201d. Someone may have hidden a password here."
      : "This file contains the sentence \u201c" + phrase + "\u201d. It looks like a password someone wrote down.";
    return [VIOLATED, { hits, say, tech: "Phrase at byte offset " + U.fmtInt(hits[0].offset) + "." }];
  }
  c5(i, data) {
    const sibs = this.byFolder.get(i._folder);
    if (sibs.length < 5) return [NOT_EVALUABLE, { reason: "fewer than 5 files in folder", files: sibs.length }];
    const same = sibs.filter(s => s.type === i.type);
    const personalPlus = new Set([...SNIFF.PERSONAL_TYPES, "encrypted-ooxml", "word97", "excel97", "email"]);
    if (personalPlus.has(i.type) && same.length === 1) {
      const kinds = new U.Counter(sibs.filter(s => s !== i).map(s => s.type)).mostCommon(3);
      const others = {}; for (const [k, v] of kinds) others[TRI.plainShort(k)] = v;
      return [VIOLATED, { folder_files: sibs.length, others, this: TRI.plainShort(i.type), kind: "odd_type",
        say: "It is the only " + TRI.plainShort(i.type) + " among the " + sibs.length + " files in its folder. The others are mostly " + and(kinds.map(k => TRI.plainPlural(k[0]))) + "." }];
    }
    const others = same.filter(s => s !== i && s.size).map(s => s.size);
    if (others.length >= 3 && i.size && SNIFF.PERSONAL_TYPES.has(i.type)) {
      const med = U.median(others), ratio = med ? i.size / med : 0;
      if (ratio >= 10) return [VIOLATED, { size: i.size, peer_median: med, ratio: U.round(ratio, 1), kind: "big",
        peer_sizes: others.slice().sort((a, b) => a - b).slice(0, 60),
        say: "At " + TRI.humanSize(i.size) + " it is about " + U.fixed(ratio, 0) + " times bigger than the other " + TRI.plainPlural(i.type) + " in its folder, which are around " + TRI.humanSize(med) + " each." }];
    }
    return [CONSISTENT, { folder_files: sibs.length }];
  }
  c6(i) {
    if (i.container) return [NOT_EVALUABLE, { reason: "archive member" }];
    const sibs = this.byFolder.get(i._folder).filter(s => s !== i);
    if (sibs.length < 4) return [NOT_EVALUABLE, { reason: "too few siblings" }];
    const ref = sibs.filter(s => this.mentioned.has(s.name.toLowerCase()));
    if (ref.length / sibs.length < 0.6) return [NOT_EVALUABLE, { reason: "siblings are not usually referenced", referenced: ref.length }];
    if (this.mentioned.has(i.name.toLowerCase())) return [CONSISTENT, {}];
    return [VIOLATED, { referenced: ref.length, siblings: sibs.length,
      say: "The guides and web pages on this drive mention " + ref.length + " of the " + sibs.length + " other files in this folder by name, but never this one." }];
  }
  c7(i) {
    if (i.members == null) return [NOT_EVALUABLE, { reason: "not an opened archive" }];
    const kids = this.items.filter(x => x.container === i.path && !x.noise), found = [];
    for (const k of kids) {
      if (k.zip_encrypted || k.ole_encrypted) found.push(k.name + " (" + TRI.plainShort(k.type) + ", locked with a password)");
      else if (["email", "encrypted-ooxml", "word97", "excel97", "ooxml", "rtf"].includes(k.type)) found.push(k.name + " (" + TRI.plainShort(k.type) + ")");
    }
    if (found.length) return [VIOLATED, { inside: found, say: "This archive is a bundle of files. Inside it are personal items: " + and(found) + "." }];
    return [CONSISTENT, { members: kids.length }];
  }
  f1(i) {
    if (i.container || !i.modified) return [NOT_EVALUABLE, { reason: "no volume timestamp" }];
    if (this.bulk_share < 0.2) return [NOT_EVALUABLE, { reason: "no bulk-copy pattern on this volume" }];
    const n = this.time_counts.get(i.modified), share = n / this.n_timed;
    if (i.modified === this.bulk_time || share >= 0.01) return [CONSISTENT, { modified: i.modified, files_with_this_time: n }];
    const bulk = this.time_counts.get(this.bulk_time);
    return [VIOLATED, { modified: i.modified, files_with_this_time: n, bulk_time: this.bulk_time, bulk_files: bulk,
      say: "Almost every file on this drive (" + U.fmtInt(bulk) + " of them) was last changed at the same moment, " + TRI.humanTime(this.bulk_time) +
        ", when they were copied together. This file was changed at a different time, " + TRI.humanTime(i.modified) + ", along with only " + (n - 1) + " other file" + (n === 2 ? "" : "s") + "." }];
  }
  run() {
    if (!this.items.length) this.collect();
    this.on("stage", { stage: "prepare" });
    this.prepare();
    const ids = ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "F1"], fns = { C1: "c1", C2: "c2", C3: "c3", C4: "c4", C5: "c5", C6: "c6", C7: "c7", F1: "f1" };
    const live = this.items.filter(i => !i.noise);
    this.on("stage", { stage: "check", total: live.length });
    live.forEach((i, n) => {
      const data = this.data(i);
      i.outcomes = {};
      for (const rid of ids) i.outcomes[rid] = this[fns[rid]](i, data);
      this.on("checked", { item: i, n: n + 1, total: live.length });
    });
    this.rates = {};
    for (const rid of ids) {
      const ev = live.filter(i => i.outcomes[rid][0] !== NOT_EVALUABLE), v = ev.filter(i => i.outcomes[rid][0] === VIOLATED).length;
      const p = (v + 0.5) / (live.length + 1);
      this.rates[rid] = { evaluable: ev.length, violated: v, p_r: p, weight: Math.log(1 / p) };
    }
    this.on("stage", { stage: "score", rates: this.rates });
    for (const i of live) {
      let num = 0, den = 0; const fired = [];
      for (const rid of ids) {
        const o = i.outcomes[rid][0];
        if (o === NOT_EVALUABLE) continue;
        const w = this.rates[rid].weight; den += w;
        if (o === VIOLATED) { num += w; fired.push(rid); }
      }
      i.score = den ? num / den : 0; i.fired = fired;
      i.evaluable = ids.filter(r => i.outcomes[r][0] !== NOT_EVALUABLE).length;
    }
    return this;
  }
  leads() {
    return U.sorted(this.items.filter(i => !i.noise && i.fired.length), i => [-i.score, -i.fired.length, i.path]);
  }
  sha256(onProgress) {
    if (this._sha) return this._sha;
    const h = new U.SHA256(), CH = 8 << 20, size = this.src.size;
    for (let pos = 0; pos < size; pos += CH) { h.update(this.src.read(pos, Math.min(CH, size - pos))); if (onProgress) onProgress(Math.min(size, pos + CH), size); }
    return (this._sha = h.hex());
  }
  toJson(top, sha) {
    top = top == null ? 40 : top;
    const live = this.items.filter(i => !i.noise), noise = new U.Counter(this.items.filter(i => i.noise).map(i => i.noise));
    const leads = this.leads(), types = new U.Counter(live.map(i => i.type));
    const slim = i => { const o = {}; for (const k of Object.keys(i)) if (!k.startsWith("_") && k !== "unrecoverable") o[k] = i[k]; return o; };
    const strata = [];
    for (const [t, n] of U.sorted([...this.time_counts.m.entries()], kv => [-kv[1], kv[0]]).slice(0, 12)) {
      const members = live.filter(i => i.container === null && i.modified === t).map(i => i.path);
      strata.push({ time: t, files: n, share: this.n_timed ? n / this.n_timed : 0, rare: this.n_timed ? n / this.n_timed < 0.01 : false,
        examples: n / Math.max(1, this.n_timed) < 0.01 ? members.slice(0, 15) : members.slice(0, 3) });
    }
    const keys = [];
    for (const i of live) { const o = (i.outcomes || {}).C4; if (o && o[0] === VIOLATED) for (const h of o[1].hits) keys.push({ key: h.candidate, found_in: i.path, offset: h.offset }); }
    const locked = live.filter(i => ((i.outcomes || {}).C3 || [""])[0] === VIOLATED).map(i => i.path);
    const sum = this.vol.summary(), rules = {};
    for (const rid of Object.keys(T.RULES)) rules[rid] = Object.assign({}, T.RULES[rid], this.rates[rid]);
    const noiseObj = {}; for (const [k, v] of noise.mostCommon()) noiseObj[k] = v;
    const typesObj = {}; for (const [k, v] of types.mostCommon(12)) typesObj[k] = v;
    return {
      generated: U.nowUtcMinute(),
      tool: "Artifact Disagreement Scorer " + PYDATA.version,
      image: Object.assign({ path: this.src.name, name: this.src.name, bytes: this.src.size, sha256: sha || this.sha256() }, sum),
      boot_hex: U.hex(this.vol._read(0, 512)),
      strata, keys, locked,
      tiers: { strong: T.STRONG, moderate: T.MODERATE },
      counts: { entries: this.items.length + this.dirs, folders: this.dirs, files: this.items.filter(i => i.container === null).length,
        archive_members: this.items.filter(i => i.container).length, noise: noise.total(), examined: live.length,
        with_findings: leads.length, deleted: this.items.filter(i => i.deleted).length },
      noise: noiseObj, types: typesObj, rules,
      timeline: { bulk_time: this.bulk_time, bulk_share: this.bulk_share, timed_files: this.n_timed },
      not_applicable: sum.fs_type !== "NTFS"
        ? "Timeline rules R1-R11 need NTFS artifacts ($MFT, $UsnJrnl, LNK, Prefetch, event logs); this " + sum.fs_type + " volume has none of them."
        : "This is an NTFS volume, so the timestamp rules R1-R11 run in the separate Windows drive report (python -m ads ingest --image, then analyze); this first-look report asks the eight questions.",
      leads: leads.slice(0, top).map(slim),
      all_leads: leads.map(i => ({ path: i.path, score: U.round(i.score, 4), fired: i.fired })),
    };
  }
  /* leads.csv, as briefing.write_triage writes it */
  leadsCsv(data) {
    let out = U.csvRow(["rank", "score_out_of_100", "level", "file", "clues", "check_ids", "what_was_found", "type", "size_bytes", "last_changed_utc"]);
    this.leads().forEach((i, n) => {
      const says = i.fired.map(r => i.outcomes[r][1].say || "").join(" | ");
      const level = i.score >= data.tiers.strong ? "Look first" : i.score >= data.tiers.moderate ? "Worth a look" : "Minor";
      out += U.csvRow([n + 1, U.round(i.score * 100), level, i.path, i.fired.map(r => data.rules[r].name).join("; "), i.fired.join(" "), says, i.type, i.size, i.modified]);
    });
    return out;
  }
}
TRI.Triage = Triage;
