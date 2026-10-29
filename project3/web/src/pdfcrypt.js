// pdfcrypt.py: the PDF Standard Security Handler (R2/R3, RC4) with the empty user password.
"use strict";
(function () {
  var B = BR.base;

  // MD5 (RFC 1321)
  var K = new Int32Array(64), S = [7, 12, 17, 22, 5, 9, 14, 20, 4, 11, 16, 23, 6, 10, 15, 21];
  for (var i = 0; i < 64; i++) K[i] = Math.floor(Math.abs(Math.sin(i + 1)) * 4294967296) | 0;
  function md5(msg) {
    var n = msg.length, total = ((n + 8) >> 6) + 1, w = new Int32Array(total * 16);
    for (var i = 0; i < n; i++) w[i >> 2] |= msg[i] << ((i & 3) * 8);
    w[n >> 2] |= 0x80 << ((n & 3) * 8);
    w[total * 16 - 2] = (n * 8) | 0;
    w[total * 16 - 1] = Math.floor(n / 536870912) | 0;
    var a0 = 0x67452301, b0 = 0xefcdab89 | 0, c0 = 0x98badcfe | 0, d0 = 0x10325476;
    for (var blk = 0; blk < total; blk++) {
      var a = a0, b = b0, c = c0, d = d0, o = blk * 16;
      for (var j = 0; j < 64; j++) {
        var f, g;
        if (j < 16) { f = (b & c) | (~b & d); g = j; }
        else if (j < 32) { f = (d & b) | (~d & c); g = (5 * j + 1) & 15; }
        else if (j < 48) { f = b ^ c ^ d; g = (3 * j + 5) & 15; }
        else { f = c ^ (b | ~d); g = (7 * j) & 15; }
        var t = d; d = c; c = b;
        var x = (a + f + K[j] + w[o + g]) | 0, s = S[(j >> 4) * 4 + (j & 3)];
        b = (b + ((x << s) | (x >>> (32 - s)))) | 0;
        a = t;
      }
      a0 = (a0 + a) | 0; b0 = (b0 + b) | 0; c0 = (c0 + c) | 0; d0 = (d0 + d) | 0;
    }
    var out = new Uint8Array(16);
    [a0, b0, c0, d0].forEach(function (v, k) { for (var q = 0; q < 4; q++) out[4 * k + q] = (v >>> (8 * q)) & 255; });
    return out;
  }

  function rc4(key, data) {
    var S = new Uint8Array(256), i, j = 0, t;
    for (i = 0; i < 256; i++) S[i] = i;
    for (i = 0; i < 256; i++) { j = (j + S[i] + key[i % key.length]) & 255; t = S[i]; S[i] = S[j]; S[j] = t; }
    var out = new Uint8Array(data.length); i = 0; j = 0;
    for (var n = 0; n < data.length; n++) {
      i = (i + 1) & 255; j = (j + S[i]) & 255; t = S[i]; S[i] = S[j]; S[j] = t;
      out[n] = data[n] ^ S[(S[i] + S[j]) & 255];
    }
    return out;
  }

  var PAD = B.unhex("28bf4e5e4e758a4164004e56fffa01082e2e00b6d0683e802f0ca9fe6453697a");
  var ESC = { 110: 10, 114: 13, 116: 9, 98: 8, 102: 12, 40: 40, 41: 41, 92: 92 };

  function literalString(b, i) {   // b[i] == '(' -> [bytes, index after]
    if (b[i] !== 40) throw new Error("not a literal string");
    i++;
    var out = [], depth = 1;
    while (i < b.length) {
      var c = b[i];
      if (c === 92) {
        var n = b[i + 1];
        if (ESC[n] !== undefined) { out.push(ESC[n]); i += 2; }
        else if (n >= 48 && n <= 55) {
          var k = i + 1, digits = "";
          while (k < i + 4 && k < b.length && b[k] >= 48 && b[k] <= 55) { digits += String.fromCharCode(b[k]); k++; }
          out.push(parseInt(digits, 8) & 255); i = k;
        } else if (n === 10 || n === 13) {
          i += 2 + (n === 13 && i + 2 < b.length && b[i + 2] === 10 ? 1 : 0);
        } else { out.push(n); i += 2; }
        continue;
      }
      if (c === 40) depth++;
      else if (c === 41) { depth--; if (depth === 0) return [new Uint8Array(out), i + 1]; }
      out.push(c); i++;
    }
    throw new Error("unterminated string");
  }

  function Security(O, U, P, ID0, R, length) {
    R = R || 3; length = length || 128;
    this.R = R; this.n = R === 2 ? 5 : length >> 3;
    var p = new Uint8Array(4); var pv = P >>> 0;
    for (var q = 0; q < 4; q++) p[q] = (pv >>> (8 * q)) & 255;
    var h = md5(B.concat([PAD.subarray(0, 32), O, p, ID0]));
    if (R >= 3) for (var r = 0; r < 50; r++) h = md5(h.subarray(0, this.n));
    this.key = h.subarray(0, this.n);
    this.ok = this._check(U, ID0);
  }
  Security.prototype._check = function (U, ID0) {
    if (this.R === 2) return B.eq(rc4(this.key, PAD), U);
    var x = rc4(this.key, md5(B.concat([PAD, ID0])));
    for (var i = 1; i < 20; i++) {
      var k = new Uint8Array(this.key.length);
      for (var j = 0; j < k.length; j++) k[j] = this.key[j] ^ i;
      x = rc4(k, x);
    }
    return B.eq(x, U.subarray(0, 16));
  };
  Security.prototype.objectKey = function (num, gen) {
    var e = new Uint8Array([num & 255, (num >> 8) & 255, (num >> 16) & 255, gen & 255, (gen >> 8) & 255]);
    return md5(B.concat([this.key, e])).subarray(0, Math.min(16, this.n + 5));
  };
  Security.prototype.keystream = function (num, gen, length) {
    return rc4(this.objectKey(num, gen), new Uint8Array(length));
  };

  BR.pdfcrypt = { md5: md5, rc4: rc4, literalString: literalString, Security: Security, PAD: PAD };
})();
