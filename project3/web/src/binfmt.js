// binfmt.py: self-checks inside binary data a PDF compresses (ICC profiles, TrueType fonts,
// ASN.1 DER signatures). Each checker takes all output so far -> [bad, checked, good].
"use strict";
(function () {
  var B = BR.base;
  var ICC_TYPES = ["desc", "text", "XYZ ", "curv", "view", "meas", "sig ", "mluc", "para", "sf32", "mft1", "mft2",
    "mAB ", "mBA ", "chrm", "dtim", "ncl2", "clrt"];
  function printable(b, lo, hi) { for (var i = lo; i < hi; i++) if (b[i] < 32 || b[i] >= 127) return false; return true; }
  function str4(b, i) { return String.fromCharCode(b[i], b[i + 1], b[i + 2], b[i + 3]); }
  function rstripLen(b, lo, hi) { while (hi > lo && b[hi - 1] === 0) hi--; return hi; }
  function cmpBytes(a, b) { for (var i = 0; i < Math.min(a.length, b.length); i++) if (a.charCodeAt(i) !== b.charCodeAt(i)) return a.charCodeAt(i) - b.charCodeAt(i); return a.length - b.length; }

  function icc(out) {
    var n = out.length;
    if (n < 132) return [0, 0, 0];
    var bad = 0, checked = 0, size = B.u32be(out, 0);
    if (str4(out, 36) !== "acsp" || !(size >= 132 && size <= (1 << 24))) return [n, n, 0];
    var count = B.u32be(out, 128);
    if (count > 200) return [n, n, 0];
    var tags = [], i;
    for (i = 0; i < count; i++) {
      var e = 132 + 12 * i;
      if (e + 12 > n) break;
      var off = B.u32be(out, e + 4), ln = B.u32be(out, e + 8);
      checked += 12;
      if (!printable(out, e, e + 4) || off < 132 + 12 * count || off + ln > size) { bad += 12; continue; }
      tags.push([off, ln]);
    }
    tags.forEach(function (t) {
      var off = t[0], ln = t[1];
      if (off + Math.min(ln, 12) > n) return;
      var end = Math.min(off + ln, n), plen = end - off, ty = str4(out, off);
      checked += plen;
      var z = true;
      for (var q = off + 4; q < Math.min(off + 8, end); q++) if (out[q]) z = false;
      if (ICC_TYPES.indexOf(ty) < 0 || !z) { bad += plen; return; }
      if (ty === "text") {
        if (!printable(out, off + 8, rstripLen(out, Math.min(off + 8, end), end))) bad += plen;
      } else if (ty === "desc" && plen >= 12) {
        var k = B.u32be(out, off + 8), bhi = Math.min(off + 12 + k, end);
        if (k > ln || !printable(out, off + 12, rstripLen(out, Math.min(off + 12, bhi), bhi))) bad += plen;
      } else if (ty === "XYZ ") {
        for (var j = 8; j < plen - 3; j += 4) { var v = B.i32be(out, off + j) / 65536; if (!(v >= -0.5 && v <= 3)) bad += 4; }
      } else if (ty === "curv" && plen >= 12) {
        var prev = null;
        for (var jj = 12; jj < plen - 1; jj += 2) { var c = B.u16be(out, off + jj); if (prev !== null && c < prev) bad += 2; prev = c; }
      }
    });
    var spans = tags.map(function (t) { return [t[0], t[0] + t[1]]; }).sort(function (a, b) { return a[0] - b[0] || a[1] - b[1]; });
    var pos = 132 + 12 * count;
    spans.forEach(function (s) {
      if (s[0] > pos) {
        var hi = Math.min(s[0], n);
        if (hi > pos) { checked += hi - pos; for (var q = pos; q < hi; q++) if (out[q]) bad++; }
      }
      pos = Math.max(pos, s[1]);
    });
    return [bad, checked, 0];
  }

  function checksum(b, lo, hi, head) {
    var s = 0, len = hi - lo;
    for (var i = 0; i < len; i += 4) {
      if (head && i === 8) continue;
      var w = 0;
      for (var k = 0; k < 4; k++) w = w * 256 + (i + k < len ? b[lo + i + k] : 0);
      s = (s + w) % 4294967296;
    }
    return s;
  }

  function truetype(out) {
    var n = out.length;
    if (n < 12) return [0, 0, 0];
    var sig = str4(out, 0);
    if (sig !== "\0\x01\0\0" && sig !== "true" && sig !== "OTTO") return [n, n, 0];
    var num = B.u16be(out, 4);
    if (!(num >= 1 && num <= 64)) return [n, n, 0];
    var bad = 0, checked = 0, good = 0, tables = [];
    for (var i = 0; i < num; i++) {
      var e = 12 + 16 * i;
      if (e + 16 > n) break;
      var tag = str4(out, e), cs = B.u32be(out, e + 4), off = B.u32be(out, e + 8), ln = B.u32be(out, e + 12);
      checked += 16;
      if (!printable(out, e, e + 4) || off < 12 + 16 * num || ln > (1 << 24)) { bad += 16; continue; }
      tables.push([off, ln, tag, cs]);
    }
    tables.sort(function (a, b) { return a[0] - b[0] || a[1] - b[1] || cmpBytes(a[2], b[2]) || a[3] - b[3]; });
    var pos = 12 + 16 * num;
    tables.forEach(function (t) {
      var off = t[0], ln = t[1], tag = t[2], cs = t[3];
      if (off > pos && pos < n) {
        var hi = Math.min(off, n);
        checked += hi - pos;
        for (var q = pos; q < hi; q++) if (out[q]) bad++;
      }
      pos = Math.max(pos, off + ln);
      if (off >= n) return;
      var end = Math.min(off + ln, n);
      if (off + ln <= n && checksum(out, off, end, tag === "head") === cs) { good++; checked += ln; return; }
      var part = out.subarray(off, end), r;
      if (tag === "DSIG") r = dsig(part);
      else if (tag === "glyf") r = glyf(part);
      else if (tag === "loca") {
        var bb = 0, pv = null;
        for (var j = 0; j < part.length - 1; j += 2) { var v = B.u16be(part, j); if (pv !== null && v < pv) bb += 2; pv = v; }
        r = [bb, part.length];
      } else if (tag === "cvt ") {
        var b3 = 0;
        for (var j2 = 0; j2 < part.length - 1; j2 += 2) if (Math.abs(B.i16be(part, j2)) > 5000) b3 += 2;
        r = [b3, part.length];
      } else r = [0, 0];
      bad += r[0]; checked += r[1];
    });
    return [bad, checked, good];
  }

  function glyf(part) {
    var i = 0, n = part.length;
    for (;;) {
      while (i < n && i % 2) { if (part[i]) return [n - i, n]; i++; }
      if (i + 10 > n) return [0, i];
      var nc = B.i16be(part, i), x0 = B.i16be(part, i + 2), y0 = B.i16be(part, i + 4), x1 = B.i16be(part, i + 6), y1 = B.i16be(part, i + 8);
      if (nc === 0) { i += 2; continue; }
      if (!(nc >= -1 && nc <= 300) || x0 > x1 || y0 > y1 || Math.max(Math.abs(x0), Math.abs(y0), Math.abs(x1), Math.abs(y1)) > 16384) {
        if (part[i] === 0 && part[i + 1] === 0) { i += 2; continue; }
        return [n - i, n];
      }
      var j = glyphEnd(part, i + 10, nc);
      if (j === null) return [0, i];
      if (j === false) return [n - i, n];
      i = j;
    }
  }
  function glyphEnd(b, j, nc) {
    var n = b.length, k, flags;
    if (nc >= 0) {
      if (j + 2 * nc + 2 > n) return null;
      var ends = [];
      for (k = 0; k < nc; k++) ends.push(B.u16be(b, j + 2 * k));
      for (k = 1; k < ends.length; k++) if (ends[k - 1] >= ends[k]) return false;
      if (ends.length && ends[ends.length - 1] > 4000) return false;
      j += 2 * nc;
      var il = B.u16be(b, j);
      if (il > 8000) return false;
      j += 2 + il;
      var pts = ends.length ? ends[ends.length - 1] + 1 : 0, xs = 0, ys = 0;
      k = 0;
      while (k < pts) {
        if (j >= n) return null;
        var f = b[j++];
        if ((f & 0xC0) && (f & 0x80)) return false;
        var rep = 1;
        if (f & 8) { if (j >= n) return null; rep += b[j++]; }
        if (k + rep > pts) return false;
        xs += rep * (f & 2 ? 1 : (f & 16 ? 0 : 2));
        ys += rep * (f & 4 ? 1 : (f & 32 ? 0 : 2));
        k += rep;
      }
      return j + xs + ys <= n ? j + xs + ys : null;
    }
    for (;;) {
      if (j + 4 > n) return null;
      flags = B.u16be(b, j);
      if (flags & 0xE010) return false;
      j += 4 + (flags & 1 ? 4 : 2);
      j += flags & 8 ? 2 : flags & 0x40 ? 4 : flags & 0x80 ? 8 : 0;
      if (!(flags & 0x20)) break;
    }
    if (flags & 0x100) { if (j + 2 > n) return null; j += 2 + B.u16be(b, j); }
    return j <= n ? j : null;
  }

  function dsig(part) {
    if (part.length < 8) return [0, 0];
    var ver = B.u32be(part, 0), num = B.u16be(part, 4);
    if (ver !== 1 || num > 8) return [part.length, part.length];
    var bad = 0, checked = 0;
    for (var i = 0; i < num; i++) {
      var e = 8 + 12 * i;
      if (e + 12 > part.length) break;
      var fmt = B.u32be(part, e), ln = B.u32be(part, e + 4), off = B.u32be(part, e + 8);
      if (fmt !== 1 || off + ln > (1 << 20)) return [part.length, part.length];
      if (off + 8 <= part.length) {
        var sl = B.u32be(part, off + 4);
        if (B.anyNonZero(part, off, off + 4) || sl + 8 !== ln) { bad += part.length - off; continue; }
        var r = der(part, off + 8, off + 8 + sl);
        bad += r[0]; checked += r[1];
      }
    }
    return [bad, checked];
  }

  var TEXT_TAGS = [0x0C, 0x12, 0x13, 0x14, 0x16, 0x1A], TIME_TAGS = [0x17, 0x18];
  function der(b, i, end) {
    var avail = Math.min(end, b.length), start = i;
    while (i < avail) {
      var h = derHead(b, i, avail);
      if (h === null) return [0, i - start];
      if (h === false) return [avail - i, avail - start];
      var tag = h[0], body = h[1], ln = h[2];
      if (body + ln > end) return [avail - i, avail - start];
      if (tag & 0x20) {
        var r = der(b, body, body + ln);
        if (r[0]) return [r[0] + (body - i), (body - i) + r[1] + (i - start)];
      } else if (!primOk(tag, b, body, Math.min(body + ln, avail), ln)) return [avail - i, avail - start];
      i = body + ln;
    }
    return [0, avail - start];
  }
  function derHead(b, i, avail) {
    if (i + 2 > avail) return null;
    var tag = b[i];
    if ((tag & 0x1F) === 0x1F || tag === 0) return false;
    var l0 = b[i + 1];
    if (l0 < 0x80) return [tag, i + 2, l0];
    var k = l0 & 0x7F;
    if (k === 0 || k > 3) return false;
    if (i + 2 + k > avail) return null;
    var ln = 0;
    for (var q = 0; q < k; q++) ln = ln * 256 + b[i + 2 + q];
    if (ln < 0x80 || (k > 1 && ln < Math.pow(2, 8 * (k - 1)))) return false;
    return [tag, i + 2 + k, ln];
  }
  function primOk(tag, b, lo, hi, ln) {
    if (tag >= 0x80) return true;
    var t = tag & 0x1F, i;
    if (t === 0x01) return ln === 1;
    if (t === 0x05) return ln === 0;
    if (t === 0x02) return ln >= 1;
    if (t === 0x06) return ln >= 1 && (hi === lo || b[hi - 1] < 0x80 || hi - lo < ln);
    if (TEXT_TAGS.indexOf(t) >= 0) {
      if (t === 0x0C) { for (i = lo; i < hi; i++) if (!((b[i] >= 32 && b[i] < 127) || b[i] >= 0x80)) return false; return true; }
      return printable(b, lo, hi);
    }
    if (TIME_TAGS.indexOf(t) >= 0) {
      for (i = lo; i < hi; i++) { var x = b[i]; if (!((x >= 48 && x <= 57) || x === 90 || x === 43 || x === 45 || x === 46)) return false; }
      return true;
    }
    if (t === 0x1E) return ln % 2 === 0;
    return t === 0x03 || t === 0x04 || t === 0x10 || t === 0x11;
  }

  BR.binfmt = { icc: icc, truetype: truetype, der: der };
})();
