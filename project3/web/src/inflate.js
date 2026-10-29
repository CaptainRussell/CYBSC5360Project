// inflate.py: a deflate decoder that can stop at any block boundary, be copied, and count
// the compressor's broken habits ("slips"). zlib header and Adler-32 checksum included.
"use strict";
(function () {
  var LEN_BASE = [3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258];
  var LEN_EXTRA = [0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0];
  var DIST_BASE = [1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513, 769, 1025, 1537, 2049, 3073,
    4097, 6145, 8193, 12289, 16385, 24577];
  var DIST_EXTRA = [0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13];
  var CL_ORDER = [16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15];
  var WINDOW = 32768, NEAR = 4096, CAP = 2 * WINDOW + 300;

  function InflateError(msg) { this.message = msg; this.name = "InflateError"; }
  InflateError.prototype = Object.create(BR.base.PlaceError.prototype);
  var NEED = { need: true };

  function table(lengths, kind) {
    var maxbits = 0, i;
    for (i = 0; i < lengths.length; i++) if (lengths[i] > maxbits) maxbits = lengths[i];
    if (maxbits === 0) return [new Int32Array([-1]), 0];
    var count = new Array(16).fill(0);
    for (i = 0; i < lengths.length; i++) count[lengths[i]]++;
    count[0] = 0;
    var left = 1;
    for (var n = 1; n < 16; n++) { left = (left << 1) - count[n]; if (left < 0) throw new InflateError("over-subscribed code"); }
    if (left > 0 && (kind === "codes" || maxbits !== 1)) throw new InflateError("incomplete code");
    var code = 0, nxt = new Array(16).fill(0);
    for (n = 1; n < 16; n++) { code = (code + count[n - 1]) << 1; nxt[n] = code; }
    var size = 1 << maxbits, look = new Int32Array(size).fill(-1);
    for (var sym = 0; sym < lengths.length; sym++) {
      var len = lengths[sym];
      if (!len) continue;
      var c = nxt[len]++, r = 0;
      for (var b = 0; b < len; b++) r = (r << 1) | ((c >> b) & 1);
      for (var k = r; k < size; k += 1 << len) look[k] = (sym << 4) | len;
    }
    return [look, maxbits];
  }
  var FIXED = null;
  function fixed() {
    if (!FIXED) {
      var lit = [], i;
      for (i = 0; i < 144; i++) lit.push(8);
      for (; i < 256; i++) lit.push(9);
      for (; i < 280; i++) lit.push(7);
      for (; i < 288; i++) lit.push(8);
      var d = []; for (i = 0; i < 32; i++) d.push(5);   // codes 30 and 31 exist but are invalid
      FIXED = [table(lit), table(d)];
    }
    return FIXED;
  }

  function adler32(buf, lo, hi, a) {
    var s1 = a & 0xffff, s2 = (a >>> 16) & 0xffff;
    for (var i = lo; i < hi;) {
      var end = Math.min(hi, i + 3800);
      for (; i < end; i++) { s1 += buf[i]; s2 += s1; }
      s1 %= 65521; s2 %= 65521;
    }
    return ((s2 << 16) | s1) >>> 0;
  }

  function Inflater(zlibHeader) {
    this.inp = new Uint8Array(0); this.ip = 0; this.bits = 0; this.nbits = 0;
    this.out = new Uint8Array(CAP); this.olen = 0; this.base = 0;
    this.state = zlibHeader === false ? "block" : "zhead";
    this.lit = this.dist = null; this.final = false; this.eof = false;
    this.slips = 0; this.tokens = 0; this.afterMatch = null; this.lits = [];
    this.storedLeft = 0; this.adler = 1; this.summed = 0;
  }
  var P = Inflater.prototype;
  P.copy = function () {
    var c = Object.create(Inflater.prototype);
    for (var k in this) if (Object.prototype.hasOwnProperty.call(this, k)) c[k] = this[k];
    c.out = new Uint8Array(CAP); c.out.set(this.out.subarray(0, this.olen));
    c.lits = this.lits.slice();
    return c;
  };
  P.total = function () { return this.base + this.olen; };
  P.output = function () { return this.out.subarray(0, this.olen); };

  P._need = function (n) {
    while (this.nbits < n) {
      if (this.ip >= this.inp.length) throw NEED;
      this.bits |= this.inp[this.ip++] << this.nbits; this.nbits += 8;
    }
  };
  P._get = function (n) {
    this._need(n);
    var v = this.bits & ((1 << n) - 1);
    this.bits >>>= n; this.nbits -= n;
    return v;
  };
  P._sym = function (t) {
    var look = t[0], maxbits = t[1], mask = (1 << maxbits) - 1;
    for (;;) {
      var e = this.nbits >= maxbits ? look[this.bits & mask] : -1;
      if (e >= 0 && (e & 15) <= this.nbits) { this.bits >>>= e & 15; this.nbits -= e & 15; return e >> 4; }
      if (this.nbits >= maxbits) throw new InflateError("invalid code");
      if (this.ip >= this.inp.length) {
        e = look[this.bits & mask];
        if (e >= 0 && (e & 15) <= this.nbits) { this.bits >>>= e & 15; this.nbits -= e & 15; return e >> 4; }
        throw NEED;
      }
      this.bits |= this.inp[this.ip++] << this.nbits; this.nbits += 8;
    }
  };

  P._byte = function (abs) { var i = abs - this.base; return i >= 0 && i < this.olen ? this.out[i] : -1; };
  P._push = function (c) {
    this.out[this.olen++] = c;
    if (this.olen > 2 * WINDOW) {
      this._sum();
      var n = this.base + this.olen;
      this.out.copyWithin(0, this.olen - WINDOW, this.olen);
      this.olen = WINDOW; this.base = n - WINDOW;
    }
  };
  P._sum = function () {
    if (this.summed < this.total()) {
      this.adler = adler32(this.out, this.summed - this.base, this.olen, this.adler);
      this.summed = this.total();
    }
  };
  P._emitLiteral = function (c) {
    var pos = this.total();
    if (this.afterMatch !== null && this._byte(this.afterMatch) === c) this.slips++;
    this.afterMatch = null;
    this._push(c);
    this.lits.push(pos);
    this._checkLits(false);
  };
  P._emitCopy = function (length, dist) {
    var pos = this.total();
    if (dist > pos) throw new InflateError("distance too far back");
    var o = this.out, start = this.olen - dist, chunk = new Uint8Array(length), k;
    if (length <= dist) chunk.set(o.subarray(start, start + length));
    else for (k = 0; k < length; k++) chunk[k] = start + k < this.olen ? o[start + k] : chunk[k - dist];
    for (k = 0; k < length; k++) this._push(chunk[k]);
    if (length === 3 && dist > NEAR) this.slips++;
    this.afterMatch = length < 258 ? pos + length - dist : null;
    this._checkLits(true);
  };
  P._checkLits = function (flush) {
    var lits = this.lits;
    while (lits.length >= 2 && this.total() >= lits[0] + 4) {
      var a = lits[0];
      if (lits[1] === a + 1 && this._earlier(a) !== null) this.slips++;
      lits.shift();
    }
    if (flush) this.lits = (!lits.length || this.total() < lits[lits.length - 1] + 4) ? [] : [lits[lits.length - 1]];
  };
  P._earlier = function (a) {
    // like bytearray.rfind(out[i:i+4], max(0, i-NEAR), i+3)
    var o = this.out, i = a - this.base, lo = Math.max(0, i - NEAR);
    var k0 = o[i], k1 = o[i + 1], k2 = o[i + 2], k3 = o[i + 3];
    for (var j = i - 1; j >= lo; j--) if (o[j] === k0 && o[j + 1] === k1 && o[j + 2] === k2 && o[j + 3] === k3) return this.base + j;
    return null;
  };

  P.feed = function (data) {
    var rest = this.inp.subarray(this.ip), inp = new Uint8Array(rest.length + data.length);
    inp.set(rest); inp.set(data, rest.length);
    this.inp = inp; this.ip = 0;
    while (!this.eof) {
      var s0 = this.ip, s1 = this.bits, s2 = this.nbits, s3 = this.final;
      try { this._step(); }
      catch (e) {
        if (e !== NEED) throw e;
        this.ip = s0; this.bits = s1; this.nbits = s2; this.final = s3;
        break;
      }
    }
    return this;
  };
  P._step = function () {
    var st = this.state;
    if (st === "zhead") {
      var cmf = this._get(8), flg = this._get(8);
      if ((cmf & 15) !== 8 || (cmf >> 4) > 7 || ((cmf << 8) | flg) % 31 || (flg & 32)) throw new InflateError("bad zlib header");
      this.state = "block";
    } else if (st === "block") {
      if (this.final) { this.state = "adler"; return; }
      var ip = this.ip, bits = this.bits, nbits = this.nbits;
      this.final = !!this._get(1);
      var kind = this._get(2);
      if (kind === 0) {
        this._get(this.nbits & 7);
        var n = this._get(16), nn = this._get(16);
        if (n !== (~nn & 0xFFFF)) throw new InflateError("bad stored length");
        this.storedLeft = n; this.state = "stored";
      } else if (kind === 1) {
        var f = fixed(); this.lit = f[0]; this.dist = f[1]; this.state = "codes";
      } else if (kind === 2) {
        try { this._dynamic(); }
        catch (e) { if (e === NEED) { this.ip = ip; this.bits = bits; this.nbits = nbits; this.final = false; } throw e; }
        this.state = "codes";
      } else throw new InflateError("bad block type");
    } else if (st === "stored") {
      if (this.storedLeft) { var c = this._get(8); this.storedLeft--; this.afterMatch = null; this._push(c); }
      else this.state = "block";
    } else if (st === "codes") {
      var sym = this._sym(this.lit);
      if (sym < 256) { this.tokens++; this._emitLiteral(sym); }
      else if (sym === 256) this.state = "block";
      else {
        var i = sym - 257;
        if (i >= 29) throw new InflateError("bad length code");
        var length = LEN_BASE[i] + this._get(LEN_EXTRA[i]);
        var d = this._sym(this.dist);
        if (d >= 30) throw new InflateError("bad distance code");
        var dist = DIST_BASE[d] + this._get(DIST_EXTRA[d]);
        this.tokens++;
        this._emitCopy(length, dist);
      }
    } else if (st === "adler") {
      this._get(this.nbits & 7);
      var want = 0;
      for (var q = 0; q < 4; q++) want = want * 256 + this._get(8);
      this._sum();
      if (want !== this.adler) throw new InflateError("checksum does not match");
      this.eof = true;
    }
  };
  P._dynamic = function () {
    var hlit = this._get(5) + 257, hdist = this._get(5) + 1, hclen = this._get(4) + 4;
    if (hlit > 286 || hdist > 30) throw new InflateError("too many length or distance symbols");
    var cl = new Array(19).fill(0);
    for (var i = 0; i < hclen; i++) cl[CL_ORDER[i]] = this._get(3);
    var clt = table(cl, "codes"), lens = [];
    while (lens.length < hlit + hdist) {
      var s = this._sym(clt), r;
      if (s < 16) lens.push(s);
      else if (s === 16) {
        if (!lens.length) throw new InflateError("repeat with nothing before");
        r = 3 + this._get(2); var last = lens[lens.length - 1]; while (r--) lens.push(last);
      } else if (s === 17) { r = 3 + this._get(3); while (r--) lens.push(0); }
      else { r = 11 + this._get(7); while (r--) lens.push(0); }
    }
    if (lens.length > hlit + hdist || !lens[256]) throw new InflateError("bad code lengths");
    this.lit = table(lens.slice(0, hlit)); this.dist = table(lens.slice(hlit));
  };

  BR.inflate = { Inflater: Inflater, InflateError: InflateError, adler32: adler32 };
})();
