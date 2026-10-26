/* File-type identification from content, minimal OLE (CFB) reading, end-of-format
   detection: a port of ads/sniff.py. Byte regexes run on latin-1 strings (one
   character per byte); Python's \s on bytes is spelled out as [ \t\n\r\f\v]. */

const SNIFF = {};
const B = U.bytes;
const HEXB = h => { const a = new Uint8Array(h.length / 2); for (let i = 0; i < a.length; i++) a[i] = parseInt(h.substr(2 * i, 2), 16); return a; };
SNIFF.MAGIC = PYDATA.sniff.MAGIC.map(([t, fam, hx, off]) => [t, fam, HEXB(hx), off]);
SNIFF.STRONG_FAMILIES = new Set(PYDATA.sniff.STRONG_FAMILIES);
SNIFF.EXPECTED = PYDATA.sniff.EXPECTED;            // extension -> types it may contain
SNIFF.PERSONAL_TYPES = new Set(PYDATA.sniff.PERSONAL_TYPES);

const EMAIL_RE = /^(?:(?:from|to|subject|date|received|return-path|mime-version|message-id|x-[\w-]+):[^\n]*\r?\n){2,}/i;
SNIFF.textKind = data => {
  const sample = data.subarray(0, 4096);
  if (!sample.length) return "empty";
  let printable = 0;
  for (const b of sample) if ((b >= 32 && b < 127) || b === 9 || b === 10 || b === 13) printable++;
  const utf8 = U.isUtf8(sample);
  if (printable / sample.length < 0.9 && !utf8) return null;
  const ls = U.blstripWS(sample), head = U.latin1(U.blower(ls.subarray(0, 200)));
  if (head.startsWith("<?xml")) return "xml";
  if (head.startsWith("<!doctype html") || head.startsWith("<html")) return "html";
  if (EMAIL_RE.test(U.latin1(ls.subarray(0, 2000)))) return "email";
  return "text";
};
const PK_CT = B("[Content_Types].xml"), META_INF = B("META-INF/"), DOT_CLASS = B(".class"), MIMETYPE = B("mimetype"), PE00 = B("PE\x00\x00");
SNIFF.sniff = data => {
  for (const [t, fam, magic, off] of SNIFF.MAGIC) {
    if (!U.eq(data, off, magic)) continue;
    if (t === "bmp" && (data.length < 14 || ![data.length, 0].includes(U.u32(data, 2)))) continue;
    if (t === "ico" && (data.length < 6 || (data[4] === 0 && data[5] === 0))) continue;
    if (t === "pe" && !U.contains(data.subarray(0, 4096), PE00) && data.length > 512) continue;
    if (t === "zip") {
      const head = data.subarray(0, 65536);
      if (U.contains(head, PK_CT)) return ["ooxml", "document"];
      if (U.contains(head.subarray(0, 2048), META_INF) || U.contains(head.subarray(0, 2048), DOT_CLASS)) return ["jar", "archive"];
      if (U.eq(head, 30, MIMETYPE)) return ["odf", "document"];
    }
    return [t, fam];
  }
  const tk = SNIFF.textKind(data);
  if (tk) return [tk, "text"];
  return ["binary", "unknown"];
};

/* Compound File Binary: enough to list streams and read one. Throws where Python's would. */
const u32arr = (b, count) => { if (b.length !== count * 4) throw new U.StructError("unpack requires a buffer of " + count * 4 + " bytes"); const a = new Array(count); for (let i = 0; i < count; i++) a[i] = U.u32(b, 4 * i); return a; };
class CFB {
  constructor(data) {
    if (!U.eq(data, 0, B("\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"))) throw new Error("not CFB");
    this.d = data;
    U.need(data, 30, 4);
    const sh = U.u16(data, 30), msh = U.u16(data, 32);
    if (sh > 24 || msh > 24) throw new Error("sector shift too large");   // Python: struct.error / MemoryError
    this.ss = 1 << sh; this.mss = 1 << msh;
    U.need(data, 44, 8); U.need(data, 56, 8); U.need(data, 68, 8);
    const nfat = U.u32(data, 44); this.dir_start = U.u32(data, 48);
    this.cutoff = U.u32(data, 56); this.minifat_start = U.u32(data, 60);
    const difatStart = U.u32(data, 68), ndifat = U.u32(data, 72);
    let difat = u32arr(data.subarray(76, 512), 109);
    let s = difatStart, guard = 0;
    while (s < 0xfffffffa && guard < ndifat + 1) {
      const blk = u32arr(this.sector(s), this.ss >> 2);
      difat = difat.concat(blk.slice(0, -1));
      s = blk[blk.length - 1]; guard++;
    }
    this.fat = [];
    for (const x of difat.slice(0, nfat)) if (x < 0xfffffffa) { const a = u32arr(this.sector(x), this.ss >> 2); for (const v of a) this.fat.push(v); }
    this.entries = [];
    const dir = this.chainRead(this.dir_start, this.fat, s2 => this.sector(s2));
    for (let i = 0; i + 128 <= dir.length; i += 128) {
      const e = dir.subarray(i, i + 128), nlen = U.u16(e, 64);
      const name = U.utf16(e.subarray(0, Math.max(0, nlen - 2))), etype = e[66];
      const start = U.u32(e, 116), size = U.u32(e, 120);
      if (etype) this.entries.push({ name, type: etype, start, size });
    }
    const root = this.entries.find(e => e.type === 5);
    this.ministream = root ? this.chainRead(root.start, this.fat, s2 => this.sector(s2)) : new Uint8Array(0);
    this.minifat = [];
    if (this.minifat_start < 0xfffffffa) {
      const mf = this.chainRead(this.minifat_start, this.fat, s2 => this.sector(s2));
      this.minifat = u32arr(mf, mf.length >> 2);   // a length that is not a whole number of entries fails, as in Python
    }
  }
  sector(s) { const o = (s + 1) * this.ss; return this.d.subarray(o, o + this.ss); }
  mini(s) { const o = s * this.mss; return this.ministream.subarray(o, o + this.mss); }
  chainRead(start, fat, reader, limit) {
    limit = limit || (1 << 26);
    const out = []; let len = 0, s = start; const seen = new Set();
    while (s < 0xfffffffa && s < fat.length + 1 && !seen.has(s) && len < limit) {
      seen.add(s); const b = reader(s); out.push(b); len += b.length;
      if (s >= fat.length) break;
      s = fat[s];
    }
    return U.concat(out);
  }
  names() { return this.entries.map(e => e.name); }
  stream(name) {
    const e = this.entries.find(x => x.name === name && x.type === 2);
    if (!e) return null;
    if (e.size < this.cutoff) return this.chainRead(e.start, this.minifat, s => this.mini(s)).subarray(0, e.size);
    return this.chainRead(e.start, this.fat, s => this.sector(s)).subarray(0, e.size);
  }
}
SNIFF.CFB = CFB;

/* -> [kind, encrypted (true/false/null), how] */
SNIFF.oleKind = data => {
  let cfb;
  try { cfb = new CFB(data); } catch (e) { return ["ole", null, "unreadable OLE container"]; }
  const names = new Set(cfb.names());
  if (names.has("EncryptedPackage") && names.has("EncryptionInfo"))
    return ["encrypted-ooxml", true, "EncryptedPackage and EncryptionInfo streams (password-protected Office 2007+ file)"];
  if (names.has("WordDocument")) {
    const wd = cfb.stream("WordDocument") || new Uint8Array(0);
    const enc = wd.length > 12 && !!(U.u16(wd, 10) & 0x0100);
    return ["word97", enc, enc ? "Word FIB fEncrypted flag" : ""];
  }
  for (const book of ["Workbook", "Book"]) {
    if (!names.has(book)) continue;
    const wb = cfb.stream(book) || new Uint8Array(0);
    let pos = 0, enc = false;
    for (let k = 0; k < 64; k++) {
      if (pos + 4 > wb.length) break;
      const rid = U.u16(wb, pos), ln = U.u16(wb, pos + 2);
      if (rid === 0x002f) { enc = true; break; }
      if (rid === 0x0809 && pos > 0) break;
      pos += 4 + ln;
    }
    return ["excel97", enc, enc ? "Excel FILEPASS record" : ""];
  }
  if (names.has("PowerPoint Document")) return ["ppt97", null, ""];
  return ["ole", null, ""];
};

SNIFF.jpegEnd = data => {
  let i = 2; const n = data.length;
  while (i + 4 <= n) {
    if (data[i] !== 0xff) return null;
    const m = data[i + 1];
    if (m === 0xff) { i += 1; continue; }
    if (m === 0xd8 || m === 0x01 || (m >= 0xd0 && m <= 0xd7)) { i += 2; continue; }
    if (m === 0xd9) return i + 2;
    const ln = U.u16be(data, i + 2);
    if (m === 0xda) {
      let j = i + 2 + ln;
      while (j + 1 < n) {
        if (data[j] === 0xff && data[j + 1] !== 0x00 && !(data[j + 1] >= 0xd0 && data[j + 1] <= 0xd7) && data[j + 1] !== 0xff) break;
        j++;
      }
      i = j; continue;
    }
    i += 2 + ln;
  }
  return null;
};
SNIFF.pngEnd = data => {
  let i = 8;
  while (i + 12 <= data.length) {
    const ln = U.u32be(data, i);
    if (data[i + 4] === 0x49 && data[i + 5] === 0x45 && data[i + 6] === 0x4e && data[i + 7] === 0x44) return i + 12 + ln;
    i += 12 + ln;
  }
  return null;
};
SNIFF.gifEnd = data => {
  const at = k => { if (k >= data.length || k < 0) throw new RangeError("index"); return data[k]; };
  try {
    let i = 13; const flags = at(10);
    if (flags & 0x80) i += 3 * (2 << (flags & 7));
    while (i < data.length) {
      const b = data[i];
      if (b === 0x3b) return i + 1;
      if (b === 0x21) i += 2;
      else if (b === 0x2c) { const lf = at(i + 9); i += 10; if (lf & 0x80) i += 3 * (2 << (lf & 7)); i += 1; }
      else return null;
      while (i < data.length && data[i]) i += data[i] + 1;
      i += 1;
    }
  } catch (e) { return null; }
  return null;
};
SNIFF.zipEnd = data => {
  const p = U.rfind(data, B("PK\x05\x06"));
  if (p < 0 || p + 22 > data.length) return null;
  return p + 22 + U.u16(data, p + 20);
};
SNIFF.pdfEnd = data => { const p = U.rfind(data, B("%%EOF")); return p < 0 ? null : p + 5; };
SNIFF.END_FINDERS = { jpeg: SNIFF.jpegEnd, png: SNIFF.pngEnd, gif: SNIFF.gifEnd, zip: SNIFF.zipEnd, pdf: SNIFF.pdfEnd };

SNIFF.EMBED_SIGS = PYDATA.sniff.EMBED_SIGS.map(([hx, name]) => [HEXB(hx), name]);
SNIFF.describeBytes = blob => {
  for (const [sig, name] of SNIFF.EMBED_SIGS) if (U.eq(blob, 0, sig)) return name;
  for (const [sig, name] of SNIFF.EMBED_SIGS) { const p = U.find(blob, sig, 0, 4096); if (p >= 0) return name + " at +" + p; }
  return null;
};
