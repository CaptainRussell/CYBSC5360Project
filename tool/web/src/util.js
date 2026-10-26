/* Shared helpers for the browser engine.

   The browser version must give exactly the answers the Python version gives, so
   these helpers reproduce Python's behaviour where JavaScript differs: rounding
   (half to even, on the exact binary value), str.strip's idea of whitespace,
   byte-string decoding with "replace", Counter.most_common's tie order, the csv
   module, and json.dumps. Everything here is synchronous: the engine runs in a
   Web Worker that reads the image with FileReaderSync, or in Node for the tests. */

const U = {};

/* ---- bytes ---------------------------------------------------------------- */

U.u16 = (b, o) => (b[o] | (b[o + 1] << 8)) >>> 0;
U.u32 = (b, o) => (b[o] | (b[o + 1] << 8) | (b[o + 2] << 16) | (b[o + 3] << 24)) >>> 0;
U.u16be = (b, o) => ((b[o] << 8) | b[o + 1]) >>> 0;
U.u32be = (b, o) => ((b[o] << 24) | (b[o + 1] << 16) | (b[o + 2] << 8) | b[o + 3]) >>> 0;
U.i8 = (b, o) => (b[o] > 127 ? b[o] - 256 : b[o]);
/* unsigned little-endian of n bytes as BigInt (FILETIMEs, 64-bit sizes) */
U.uBig = (b, o, n) => { let v = 0n; for (let i = n - 1; i >= 0; i--) v = (v << 8n) | BigInt(b[o + i] || 0); return v; };
U.u64 = (b, o) => U.uBig(b, o, 8);
/* a 64-bit value that is an offset or size: as a Number */
U.u64n = (b, o) => Number(U.u64(b, o));

/* Python's struct.unpack raises if the slice is short; so do these "need" checks. */
class StructError extends Error {}
U.StructError = StructError;
U.need = (b, o, n) => { if (o < 0 || o + n > b.length) throw new StructError("unpack requires a buffer of " + n + " bytes"); };

U.concat = parts => {
  let n = 0; for (const p of parts) n += p.length;
  const out = new Uint8Array(n); let o = 0;
  for (const p of parts) { out.set(p, o); o += p.length; }
  return out;
};
U.eq = (b, o, sig) => { if (o < 0 || o + sig.length > b.length) return false; for (let i = 0; i < sig.length; i++) if (b[o + i] !== sig[i]) return false; return true; };
U.bytes = s => { const a = new Uint8Array(s.length); for (let i = 0; i < s.length; i++) a[i] = s.charCodeAt(i) & 255; return a; };
U.hex = (b, sep, upper) => { const h = []; for (const x of b) h.push(x.toString(16).padStart(2, "0")); const s = h.join(sep || ""); return upper ? s.toUpperCase() : s; };
/* bytes.find(sub, start, end): the whole match must fit in [start, end) */
U.find = (b, sub, start, end) => {
  start = start || 0; end = end == null ? b.length : Math.min(end, b.length);
  const n = sub.length, f = sub[0];
  for (let i = start; i + n <= end; i++) {
    if (b[i] !== f) continue;
    let k = 1; while (k < n && b[i + k] === sub[k]) k++;
    if (k === n) return i;
  }
  return -1;
};
U.rfind = (b, sub) => {
  const n = sub.length;
  for (let i = b.length - n; i >= 0; i--) { let k = 0; while (k < n && b[i + k] === sub[k]) k++; if (k === n) return i; }
  return -1;
};
U.contains = (b, sub) => U.find(b, sub) >= 0;

/* One character per byte, so byte-level regexes can run on a JS string. */
U.latin1 = b => {
  let s = ""; const CH = 0x8000;
  for (let i = 0; i < b.length; i += CH) s += String.fromCharCode.apply(null, b.subarray(i, i + CH));
  return s;
};

/* ---- decoding with Python's "replace" error handler -------------------------- */

const CP437_HIGH = "ÇüéâäàåçêëèïîìÄÅÉæÆôöòûùÿÖÜ¢£¥₧ƒáíóúñÑªº¿⌐¬½¼¡«»░▒▓│┤╡╢╖╕╣║╗╝╜╛┐└┴┬├─┼╞╟╚╔╩╦╠═╬╧╨╤╥╙╘╒╓╫╪┘┌█▄▌▐▀αßΓπΣσµτΦΘΩδ∞φε∩≡±≥≤⌠⌡÷≈°∙·√ⁿ²■ ";
U.cp437 = b => { let s = ""; for (const x of b) s += x < 128 ? String.fromCharCode(x) : CP437_HIGH[x - 128]; return s; };
U.ascii = b => { let s = ""; for (const x of b) s += x < 128 ? String.fromCharCode(x) : "�"; return s; };
const UTF16 = new TextDecoder("utf-16le");
const UTF8 = new TextDecoder("utf-8");
const UTF8_STRICT = new TextDecoder("utf-8", { fatal: true });
U.utf16 = b => UTF16.decode(b);
U.utf8 = b => UTF8.decode(b);
U.utf8strict = b => UTF8_STRICT.decode(b);   // throws like bytes.decode("utf-8")
U.isUtf8 = b => { try { UTF8_STRICT.decode(b); return true; } catch (e) { return false; } };

/* ---- strings like Python ------------------------------------------------------ */

const PY_WS = new Set([9, 10, 11, 12, 13, 28, 29, 30, 31, 32, 0x85, 0xa0, 0x1680, 0x2000, 0x2001, 0x2002, 0x2003, 0x2004, 0x2005,
  0x2006, 0x2007, 0x2008, 0x2009, 0x200a, 0x2028, 0x2029, 0x202f, 0x205f, 0x3000]);
U.isSpace = c => PY_WS.has(c.charCodeAt(0));
U.strip = (s, chars) => U.rstrip(U.lstrip(s, chars), chars);
U.lstrip = (s, chars) => { let i = 0; while (i < s.length && (chars == null ? PY_WS.has(s.charCodeAt(i)) : chars.includes(s[i]))) i++; return s.slice(i); };
U.rstrip = (s, chars) => { let i = s.length; while (i > 0 && (chars == null ? PY_WS.has(s.charCodeAt(i - 1)) : chars.includes(s[i - 1]))) i--; return s.slice(0, i); };
/* byte-string strip of a given byte set */
U.bstrip = (b, set) => { let i = 0, j = b.length; while (i < j && set.includes(b[i])) i++; while (j > i && set.includes(b[j - 1])) j--; return b.subarray(i, j); };
U.blstripWS = b => { let i = 0; while (i < b.length && (b[i] === 32 || (b[i] >= 9 && b[i] <= 13))) i++; return b.subarray(i); };
U.blower = b => { const o = new Uint8Array(b.length); for (let i = 0; i < b.length; i++) o[i] = b[i] >= 65 && b[i] <= 90 ? b[i] + 32 : b[i]; return o; };
U.rsplit1 = (s, sep) => { const i = s.lastIndexOf(sep); return i < 0 ? [s] : [s.slice(0, i), s.slice(i + sep.length)]; };
U.lower = s => s.toLowerCase();

/* Compare strings by code point, as Python does (JS compares UTF-16 units). */
U.cmpStr = (a, b) => {
  if (a === b) return 0;
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i++) {
    let x = a.codePointAt(i), y = b.codePointAt(i);
    if (x !== y) return x < y ? -1 : 1;
    if (x > 0xffff) i++;
  }
  return a.length < b.length ? -1 : a.length > b.length ? 1 : 0;
};
/* Python-style comparison of numbers, BigInts, strings, null (None sorts first, like SQLite) and arrays (tuples). */
U.cmp = (a, b) => {
  if (a === b) return 0;
  if (a == null) return b == null ? 0 : -1;
  if (b == null) return 1;
  if (Array.isArray(a)) {
    for (let i = 0; i < Math.min(a.length, b.length); i++) { const c = U.cmp(a[i], b[i]); if (c) return c; }
    return a.length - b.length;
  }
  if (typeof a === "string") return U.cmpStr(a, b);
  return a < b ? -1 : a > b ? 1 : 0;
};
U.sorted = (arr, key) => {   // stable, like Python's sorted
  const k = key || (x => x);
  return arr.map((v, i) => [k(v), i, v]).sort((p, q) => U.cmp(p[0], q[0]) || p[1] - q[1]).map(p => p[2]);
};
U.bisectLeft = (a, x) => { let lo = 0, hi = a.length; while (lo < hi) { const m = (lo + hi) >> 1; if (U.cmp(a[m], x) < 0) lo = m + 1; else hi = m; } return lo; };
U.bisectRight = (a, x) => { let lo = 0, hi = a.length; while (lo < hi) { const m = (lo + hi) >> 1; if (U.cmp(x, a[m]) < 0) hi = m; else lo = m + 1; } return lo; };

/* collections.Counter: insertion-ordered counts; most_common keeps first-seen order on ties. */
class Counter {
  constructor(it) { this.m = new Map(); if (it) for (const x of it) this.add(x); }
  add(x, n) { this.m.set(x, (this.m.get(x) || 0) + (n == null ? 1 : n)); }
  get(x) { return this.m.get(x) || 0; }
  total() { let t = 0; for (const v of this.m.values()) t += v; return t; }
  mostCommon(n) {
    const e = [...this.m.entries()].map((kv, i) => [kv, i]).sort((a, b) => b[0][1] - a[0][1] || a[1] - b[1]).map(x => x[0]);
    return n == null ? e : e.slice(0, n);
  }
}
U.Counter = Counter;

U.median = xs => {   // statistics.median
  const s = xs.slice().sort((a, b) => a - b), n = s.length;
  if (!n) throw new Error("no median for empty data");
  return n % 2 ? s[(n - 1) >> 1] : (s[n / 2 - 1] + s[n / 2]) / 2;
};

/* ---- numbers like Python --------------------------------------------------------- */

function decompose(x) {   // x = m * 2^e exactly
  const dv = new DataView(new ArrayBuffer(8)); dv.setFloat64(0, x);
  const hi = dv.getUint32(0), lo = dv.getUint32(4), ex = (hi >>> 20) & 0x7ff;
  let m = (BigInt(hi & 0xfffff) << 32n) | BigInt(lo);
  if (ex === 0) return [m, -1074];
  return [m | (1n << 52n), ex - 1075];
}
/* "%.nf" % x: correctly rounded, ties to even, on the exact binary value. */
U.fixed = (x, n) => {
  x = Number(x);
  if (!isFinite(x)) return isNaN(x) ? "nan" : (x < 0 ? "-inf" : "inf");
  const neg = x < 0 || Object.is(x, -0);
  const [m, e] = decompose(Math.abs(x));
  let q;
  if (e >= 0) q = (m << BigInt(e)) * 10n ** BigInt(n);
  else {
    const k = -e, N = m * 5n ** BigInt(k);
    if (k <= n) q = N * 10n ** BigInt(n - k);
    else {
      const div = 10n ** BigInt(k - n); q = N / div; const r2 = 2n * (N % div);
      if (r2 > div || (r2 === div && (q & 1n))) q += 1n;
    }
  }
  let s = q.toString().padStart(n + 1, "0");
  if (n) s = s.slice(0, -n) + "." + s.slice(-n);
  return (neg ? "-" : "") + s;
};
U.round = (x, n) => Number(U.fixed(x, n || 0));   // round(x, n), round(x)
U.fmtInt = n => Number(n).toLocaleString("en-US", { maximumFractionDigits: 0, useGrouping: true });   // format(n, ",")
U.pct = (n, d) => d ? n / d : 0;

/* A value Python holds as a float (so json.dumps writes "2.0", not "2"). */
class PF {
  constructor(v) { this.v = Number(v); }
  valueOf() { return this.v; }
  toJSON() { return this.v; }
  toString() { return U.floatRepr(this.v); }
}
U.PF = PF;
U.F = v => (v == null ? v : new PF(v));
U.num = v => (v instanceof PF ? v.v : v);

/* repr(float) */
U.floatRepr = x => {
  if (Number.isNaN(x)) return "NaN";
  if (!isFinite(x)) return x > 0 ? "Infinity" : "-Infinity";
  if (x === 0) return Object.is(x, -0) ? "-0.0" : "0.0";
  let s = Math.abs(x).toExponential();          // shortest digits: d.ddde±x
  let [mant, ex] = s.split("e"); const e = parseInt(ex, 10), digits = mant.replace(".", "");
  let out;
  if (e < -4 || e >= 16) out = digits[0] + (digits.length > 1 ? "." + digits.slice(1) : "") + "e" + (e < 0 ? "-" : "+") + String(Math.abs(e)).padStart(2, "0");
  else if (e < 0) out = "0." + "0".repeat(-e - 1) + digits;
  else if (digits.length <= e + 1) out = digits + "0".repeat(e + 1 - digits.length) + ".0";
  else out = digits.slice(0, e + 1) + "." + digits.slice(e + 1);
  return (x < 0 ? "-" : "") + out;
};

/* json.dumps(obj, sort_keys=?, indent=?, default=str), ensure_ascii=True */
U.pyJson = (obj, opt) => {
  opt = opt || {};
  const ind = opt.indent;
  const esc = s => '"' + s.replace(/[\\"\u0000-\u001f\u007f-￿]/g, c => {
    const m = { '"': '\\"', "\\": "\\\\", "\n": "\\n", "\r": "\\r", "\t": "\\t", "\b": "\\b", "\f": "\\f" }[c];
    if (m) return m;
    const code = c.charCodeAt(0);
    if (code === 0x7f) return c;   // DEL is ASCII: json.dumps leaves it alone
    return "\\u" + code.toString(16).padStart(4, "0");
  }) + '"';
  const enc = (v, level) => {
    if (v === null || v === undefined) return "null";
    if (v instanceof PF) return U.floatRepr(v.v);
    if (typeof v === "boolean") return v ? "true" : "false";
    if (typeof v === "bigint") return v.toString();
    if (typeof v === "number") return Number.isInteger(v) && !Object.is(v, -0) ? String(v) : U.floatRepr(v);
    if (typeof v === "string") return esc(v);
    const nl = ind == null ? "" : "\n" + " ".repeat(ind * (level + 1)), close = ind == null ? "" : "\n" + " ".repeat(ind * level);
    const sep = ind == null ? ", " : ",";
    if (Array.isArray(v)) {
      if (!v.length) return "[]";
      return "[" + nl + v.map(x => enc(x, level + 1)).join(sep + nl) + close + "]";
    }
    let keys = Object.keys(v);
    if (!keys.length) return "{}";
    if (opt.sortKeys) keys = keys.sort(U.cmpStr);
    return "{" + nl + keys.map(k => esc(k) + ": " + enc(v[k], level + 1)).join(sep + nl) + close + "}";
  };
  return enc(obj, 0);
};

/* ---- csv like Python's csv module (excel dialect) -------------------------------- */

/* Rows of fields; blank lines are skipped by the DictReader that uses this. */
U.csvParse = text => {
  const rows = []; let row = [], f = "", i = 0, n = text.length, state = 0; // 0 start of field, 1 unquoted, 2 quoted, 3 quote in quoted
  let any = false;
  const endField = () => { row.push(f); f = ""; };
  const endRow = () => { if (any || row.length) { endField(); rows.push(row); } row = []; f = ""; any = false; state = 0; };
  while (i < n) {
    const c = text[i];
    if (state === 2) {
      if (c === '"') state = 3; else f += c;
      i++; continue;
    }
    if (state === 3) {
      if (c === '"') { f += '"'; state = 2; i++; continue; }
      state = 1;   // non-strict: characters after the closing quote are kept
    }
    if (c === ",") { endField(); state = 0; any = true; i++; continue; }
    if (c === "\r" || c === "\n") {
      endRow();
      if (c === "\r" && text[i + 1] === "\n") i++;
      i++; continue;
    }
    if (c === '"' && state === 0) { state = 2; any = true; i++; continue; }
    f += c; any = true; state = 1; i++;
  }
  if (state !== 0 || any || row.length) endRow();
  return rows;
};
/* csv.DictReader: -> {fieldnames, rows: [{name: value}]}; short rows give null, like restval=None */
U.csvDict = text => {
  if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);   // utf-8-sig
  const all = U.csvParse(text).filter(r => !(r.length === 1 && r[0] === "" && false));
  const rows = all.filter(r => r.length > 0);
  if (!rows.length) return { fieldnames: [], rows: [] };
  const fields = rows[0];
  const out = [];
  for (let k = 1; k < rows.length; k++) {
    const r = rows[k], d = {};
    for (let j = 0; j < fields.length; j++) d[fields[j]] = j < r.length ? r[j] : null;
    out.push(d);
  }
  return { fieldnames: fields, rows: out };
};
/* csv.writer with QUOTE_MINIMAL and \r\n line endings */
U.csvRow = fields => fields.map((v, i) => {
  let s = v == null ? "" : v instanceof PF ? U.floatRepr(v.v) : typeof v === "boolean" ? (v ? "True" : "False") : String(v);
  if (/[",\r\n]/.test(s) || (fields.length === 1 && s === "")) s = '"' + s.replace(/"/g, '""') + '"';
  return s;
}).join(",") + "\r\n";

/* ---- checksums ---------------------------------------------------------------------- */

const CRC_T = (() => { const t = new Uint32Array(256); for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
U.crc32 = (b, crc) => { let c = (crc == null ? 0 : crc) ^ 0xffffffff; for (let i = 0; i < b.length; i++) c = CRC_T[(c ^ b[i]) & 255] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };

/* Streaming SHA-256, so a 1 GB image is hashed piece by piece. */
const K256 = new Uint32Array([0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01,
  0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa,
  0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138,
  0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624,
  0xf40e3585, 0x106aa070, 0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f,
  0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2]);
class SHA256 {
  constructor() { this.h = new Uint32Array([0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19]); this.buf = new Uint8Array(64); this.bl = 0; this.len = 0; this.w = new Uint32Array(64); }
  block(b, o) {
    const w = this.w, h = this.h;
    for (let i = 0; i < 16; i++) w[i] = (b[o + 4 * i] << 24) | (b[o + 4 * i + 1] << 16) | (b[o + 4 * i + 2] << 8) | b[o + 4 * i + 3];
    for (let i = 16; i < 64; i++) {
      const a = w[i - 15], c = w[i - 2];
      const s0 = ((a >>> 7) | (a << 25)) ^ ((a >>> 18) | (a << 14)) ^ (a >>> 3);
      const s1 = ((c >>> 17) | (c << 15)) ^ ((c >>> 19) | (c << 13)) ^ (c >>> 10);
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) | 0;
    }
    let A = h[0], B = h[1], C = h[2], D = h[3], E = h[4], F = h[5], G = h[6], H = h[7];
    for (let i = 0; i < 64; i++) {
      const S1 = ((E >>> 6) | (E << 26)) ^ ((E >>> 11) | (E << 21)) ^ ((E >>> 25) | (E << 7));
      const t1 = (H + S1 + ((E & F) ^ (~E & G)) + K256[i] + w[i]) | 0;
      const S0 = ((A >>> 2) | (A << 30)) ^ ((A >>> 13) | (A << 19)) ^ ((A >>> 22) | (A << 10));
      const t2 = (S0 + ((A & B) ^ (A & C) ^ (B & C))) | 0;
      H = G; G = F; F = E; E = (D + t1) | 0; D = C; C = B; B = A; A = (t1 + t2) | 0;
    }
    h[0] += A; h[1] += B; h[2] += C; h[3] += D; h[4] += E; h[5] += F; h[6] += G; h[7] += H;
  }
  update(b) {
    let i = 0; this.len += b.length;
    if (this.bl) { while (this.bl < 64 && i < b.length) this.buf[this.bl++] = b[i++]; if (this.bl === 64) { this.block(this.buf, 0); this.bl = 0; } }
    for (; i + 64 <= b.length; i += 64) this.block(b, i);
    while (i < b.length) this.buf[this.bl++] = b[i++];
    return this;
  }
  hex() {
    const bits = this.len * 8, pad = new Uint8Array(((this.bl < 56 ? 56 : 120) - this.bl) + 8);
    pad[0] = 0x80;
    const hi = Math.floor(bits / 4294967296), lo = bits >>> 0, p = pad.length;
    pad[p - 8] = hi >>> 24; pad[p - 7] = hi >>> 16; pad[p - 6] = hi >>> 8; pad[p - 5] = hi;
    pad[p - 4] = lo >>> 24; pad[p - 3] = lo >>> 16; pad[p - 2] = lo >>> 8; pad[p - 1] = lo;
    this.update(pad);
    return [...this.h].map(x => (x >>> 0).toString(16).padStart(8, "0")).join("");
  }
}
U.SHA256 = SHA256;

/* ---- raw DEFLATE (what zlib.decompressobj(-15) reads in a ZIP) -------------------------- */

class InflateError extends Error {}
U.InflateError = InflateError;
const LBASE = [3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258];
const LEXT = [0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0];
const DBASE = [1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577];
const DEXT = [0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13];
const CLORD = [16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15];
function huff(lengths) {   // canonical Huffman -> {count, symbol}
  const count = new Uint16Array(16), sym = new Uint16Array(lengths.length), offs = new Uint16Array(16);
  for (const l of lengths) count[l]++;
  count[0] = 0;
  let left = 1;
  for (let i = 1; i < 16; i++) { left = (left << 1) - count[i]; if (left < 0) throw new InflateError("over-subscribed code"); }
  for (let i = 1; i < 15; i++) offs[i + 1] = offs[i] + count[i];
  for (let s = 0; s < lengths.length; s++) if (lengths[s]) sym[offs[lengths[s]]++] = s;
  return { count, sym, incomplete: left > 0 };
}
U.inflate = (src, limit) => {
  limit = limit == null ? Infinity : limit;
  let pos = 0, bitbuf = 0, bitcnt = 0;
  let out = new Uint8Array(Math.min(limit === Infinity ? src.length * 4 + 1024 : limit, 1 << 26) || 16), olen = 0;
  const grow = need => { if (need <= out.length) return; let n = out.length * 2; while (n < need) n *= 2; const o = new Uint8Array(n); o.set(out.subarray(0, olen)); out = o; };
  const bits = n => {
    while (bitcnt < n) { if (pos >= src.length) throw new InflateError("incomplete stream"); bitbuf |= src[pos++] << bitcnt; bitcnt += 8; }
    const v = bitbuf & ((1 << n) - 1); bitbuf >>>= n; bitcnt -= n; return v;
  };
  const decode = h => {
    let code = 0, first = 0, index = 0;
    for (let len = 1; len < 16; len++) {
      code |= bits(1); const c = h.count[len];
      if (code - c < first) return h.sym[index + (code - first)];
      index += c; first += c; first <<= 1; code <<= 1;
    }
    throw new InflateError("invalid code");
  };
  let fixedL = null, fixedD = null, last = 0;
  while (!last && olen < limit) {
    last = bits(1); const type = bits(2);
    if (type === 0) {
      bitbuf = 0; bitcnt = 0;
      if (pos + 4 > src.length) throw new InflateError("incomplete stream");
      const len = src[pos] | (src[pos + 1] << 8), nlen = src[pos + 2] | (src[pos + 3] << 8); pos += 4;
      if (len !== (~nlen & 0xffff)) throw new InflateError("invalid stored block lengths");
      if (pos + len > src.length) throw new InflateError("incomplete stream");
      grow(olen + len); out.set(src.subarray(pos, pos + len), olen); olen += len; pos += len;
      continue;
    }
    let L, Dh;
    if (type === 1) {
      if (!fixedL) { const l = new Array(288); for (let i = 0; i < 288; i++) l[i] = i < 144 ? 8 : i < 256 ? 9 : i < 280 ? 7 : 8; fixedL = huff(l); fixedD = huff(new Array(30).fill(5)); }
      L = fixedL; Dh = fixedD;
    } else if (type === 2) {
      const nl = bits(5) + 257, nd = bits(5) + 1, nc = bits(4) + 4;
      if (nl > 286 || nd > 30) throw new InflateError("bad counts");
      const cl = new Array(19).fill(0); for (let i = 0; i < nc; i++) cl[CLORD[i]] = bits(3);
      const ch = huff(cl); if (ch.incomplete && cl.some(x => x)) { /* zlib accepts only complete code-length codes */ let k = 0; for (const x of cl) if (x) k++; if (k !== 1) throw new InflateError("incomplete code-length code"); }
      const lens = []; while (lens.length < nl + nd) {
        const s = decode(ch);
        if (s < 16) lens.push(s);
        else if (s === 16) { if (!lens.length) throw new InflateError("repeat with no first length"); const p = lens[lens.length - 1]; for (let r = 3 + bits(2); r; r--) lens.push(p); }
        else if (s === 17) for (let r = 3 + bits(3); r; r--) lens.push(0);
        else for (let r = 11 + bits(7); r; r--) lens.push(0);
      }
      if (lens.length > nl + nd) throw new InflateError("too many lengths");
      if (!lens[256]) throw new InflateError("no end-of-block code");
      L = huff(lens.slice(0, nl)); Dh = huff(lens.slice(nl));
    } else throw new InflateError("invalid block type");
    for (;;) {
      const s = decode(L);
      if (s < 256) { grow(olen + 1); out[olen++] = s; if (olen >= limit) break; continue; }
      if (s === 256) break;
      const li = s - 257; if (li >= 29) throw new InflateError("invalid length code");
      const len = LBASE[li] + bits(LEXT[li]);
      const di = decode(Dh); if (di >= 30) throw new InflateError("invalid distance code");
      const dist = DBASE[di] + bits(DEXT[di]);
      if (dist > olen) throw new InflateError("invalid distance too far back");
      grow(olen + len);
      for (let k = 0; k < len; k++) { out[olen] = out[olen - dist]; olen++; }
      if (olen >= limit) break;
    }
  }
  return out.subarray(0, Math.min(olen, limit));
};

/* ---- time ------------------------------------------------------------------------------ */

U.MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(" ");
const p2 = n => String(n).padStart(2, "0");
/* naive date-time parts -> "YYYY-MM-DD HH:MM:SS" (datetime.isoformat(" ", "seconds")) */
U.isoSec = d => String(d.getUTCFullYear()).padStart(4, "0") + "-" + p2(d.getUTCMonth() + 1) + "-" + p2(d.getUTCDate()) + " " +
  p2(d.getUTCHours()) + ":" + p2(d.getUTCMinutes()) + ":" + p2(d.getUTCSeconds());
U.isoDate = d => String(d.getUTCFullYear()).padStart(4, "0") + "-" + p2(d.getUTCMonth() + 1) + "-" + p2(d.getUTCDate());
U.utcDate = (y, mo, d, h, mi, s, ms) => { const t = new Date(0); t.setUTCFullYear(y, mo - 1, d); t.setUTCHours(h || 0, mi || 0, s || 0, ms || 0); return t; };
U.validDate = (y, mo, d) => {
  if (y < 1 || y > 9999 || mo < 1 || mo > 12 || d < 1) return false;
  const dim = [31, (y % 4 === 0 && (y % 100 !== 0 || y % 400 === 0)) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][mo - 1];
  return d <= dim;
};
U.nowIso = () => new Date().toISOString().replace(/\.\d+Z$/, "Z");
U.nowUtcMinute = () => { const d = new Date(); return U.isoSec(d).slice(0, 16) + " UTC"; };

if (typeof module !== "undefined") module.exports = U;
