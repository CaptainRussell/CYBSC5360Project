// Block Recovery Toolkit, browser edition: shared helpers.
// Created by Captain Scott Russell for CPRE 5360.
// Every module here mirrors a Python module in blockrecover/ and must give the same
// answers; tests/test_web.py checks that under Node.
"use strict";
var BR = (typeof self !== "undefined" ? self : globalThis).BR = (typeof self !== "undefined" ? self : globalThis).BR || {};

(function () {
  // bytes <-> "binary strings" (one char per byte), so byte patterns can use RegExp
  function bstr(u8, lo, hi) {
    lo = lo || 0; hi = hi == null ? u8.length : Math.min(hi, u8.length);
    var out = "", CH = 8192;
    for (var i = lo; i < hi; i += CH) out += String.fromCharCode.apply(null, u8.subarray(i, Math.min(hi, i + CH)));
    return out;
  }
  function fromB(s) { var u = new Uint8Array(s.length); for (var i = 0; i < s.length; i++) u[i] = s.charCodeAt(i) & 255; return u; }
  function concat(list) {
    var n = 0; list.forEach(function (a) { n += a.length; });
    var out = new Uint8Array(n), o = 0;
    list.forEach(function (a) { out.set(a, o); o += a.length; });
    return out;
  }
  function eq(a, b) {
    if (a.length !== b.length) return false;
    for (var i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
    return true;
  }
  function startsWith(u8, prefix, at) {
    at = at || 0;
    if (typeof prefix === "string") prefix = fromB(prefix);
    if (at + prefix.length > u8.length) return false;
    for (var i = 0; i < prefix.length; i++) if (u8[at + i] !== prefix[i]) return false;
    return true;
  }
  function find(u8, pat, from, to) {
    if (typeof pat === "string") pat = fromB(pat);
    from = from || 0; to = to == null ? u8.length : to;
    var n = pat.length;
    outer: for (var i = from; i + n <= to; i++) {
      for (var k = 0; k < n; k++) if (u8[i + k] !== pat[k]) continue outer;
      return i;
    }
    return -1;
  }
  function rfind(u8, pat, from, to) {   // like bytearray.rfind(pat, from, to)
    if (typeof pat === "string") pat = fromB(pat);
    var n = pat.length;
    for (var i = to - n; i >= from; i--) {
      var ok = true;
      for (var k = 0; k < n; k++) if (u8[i + k] !== pat[k]) { ok = false; break; }
      if (ok) return i;
    }
    return -1;
  }
  function anyNonZero(u8, lo, hi) {
    lo = lo || 0; hi = hi == null ? u8.length : hi;
    for (var i = lo; i < hi; i++) if (u8[i]) return true;
    return false;
  }
  function rstripZero(u8) { var n = u8.length; while (n && !u8[n - 1]) n--; return u8.subarray(0, n); }
  function u16be(b, i) { return (b[i] << 8) | b[i + 1]; }
  function i16be(b, i) { var v = u16be(b, i); return v & 0x8000 ? v - 0x10000 : v; }
  function u32be(b, i) { return ((b[i] << 24) >>> 0) + (b[i + 1] << 16) + (b[i + 2] << 8) + b[i + 3]; }
  function i32be(b, i) { return u32be(b, i) | 0; }
  function u16le(b, i) { return b[i] | (b[i + 1] << 8); }
  function u32le(b, i) { return (b[i] | (b[i + 1] << 8) | (b[i + 2] << 16)) + b[i + 3] * 16777216; }
  function u32les(b) { var n = b.length >> 2, out = new Array(n); for (var i = 0; i < n; i++) out[i] = u32le(b, 4 * i); return out; }
  function xor(a, b) {
    var n = Math.min(a.length, b.length), out = new Uint8Array(n);
    for (var i = 0; i < n; i++) out[i] = a[i] ^ b[i];
    return out;
  }
  function hex(u8) { var s = ""; for (var i = 0; i < u8.length; i++) s += (u8[i] < 16 ? "0" : "") + u8[i].toString(16); return s; }
  function unhex(s) { var u = new Uint8Array(s.length >> 1); for (var i = 0; i < u.length; i++) u[i] = parseInt(s.substr(2 * i, 2), 16); return u; }

  // Python-style error, so callers can tell "this did not fit" from a bug
  function PlaceError(msg) { this.message = msg; this.name = "PlaceError"; }
  PlaceError.prototype = Object.create(Error.prototype);

  // round(x, n) exactly as Python: correctly rounded on the exact binary value, ties to even
  function decompose(x) {
    var dv = new DataView(new ArrayBuffer(8)); dv.setFloat64(0, x);
    var hi = dv.getUint32(0), lo = dv.getUint32(4), ex = (hi >>> 20) & 0x7ff;
    var m = (BigInt(hi & 0xfffff) << 32n) | BigInt(lo);
    if (ex === 0) return [m, -1074];
    return [m | (1n << 52n), ex - 1075];
  }
  function pyRound(x, n) {
    if (!isFinite(x) || x === 0) return x;
    var neg = x < 0, d = decompose(Math.abs(x)), m = d[0], e = d[1], q;
    if (e >= 0) q = (m << BigInt(e)) * 10n ** BigInt(n);
    else {
      var k = -e, N = m * 5n ** BigInt(k);
      if (k <= n) q = N * 10n ** BigInt(n - k);
      else {
        var div = 10n ** BigInt(k - n); q = N / div; var r2 = 2n * (N % div);
        if (r2 > div || (r2 === div && (q & 1n))) q += 1n;
      }
    }
    var s = q.toString().padStart(n + 1, "0");
    if (n) s = s.slice(0, -n) + "." + s.slice(-n);
    return Number((neg ? "-" : "") + s);
  }

  // Python's strict UTF-8 decoder: -> null if valid, else {start, reason}
  function utf8Error(b) {
    var i = 0, n = b.length;
    while (i < n) {
      var c = b[i];
      if (c < 0x80) { i++; continue; }
      var need, lo = 0x80, hi = 0xBF;
      if (c >= 0xC2 && c <= 0xDF) need = 1;
      else if (c >= 0xE0 && c <= 0xEF) { need = 2; if (c === 0xE0) lo = 0xA0; if (c === 0xED) hi = 0x9F; }
      else if (c >= 0xF0 && c <= 0xF4) { need = 3; if (c === 0xF0) lo = 0x90; if (c === 0xF4) hi = 0x8F; }
      else return { start: i, reason: "invalid start byte" };
      for (var k = 1; k <= need; k++) {
        if (i + k >= n) return { start: i, reason: "unexpected end of data" };
        var x = b[i + k];
        if (k === 1 ? (x < lo || x > hi) : (x < 0x80 || x > 0xBF)) return { start: i, reason: "invalid continuation byte" };
      }
      i += need + 1;
    }
    return null;
  }

  BR.base = { bstr: bstr, fromB: fromB, concat: concat, eq: eq, startsWith: startsWith, find: find, rfind: rfind,
    anyNonZero: anyNonZero, rstripZero: rstripZero, u16be: u16be, i16be: i16be, u32be: u32be, i32be: i32be,
    u16le: u16le, u32le: u32le, u32les: u32les, xor: xor, hex: hex, unhex: unhex, PlaceError: PlaceError, pyRound: pyRound,
    utf8Error: utf8Error };
  BR.BS = 512;
})();
