// jpeg.py: a baseline JPEG decoder that can stop at the end of any block and carry on with
// whichever block is tried next, and the seam measure used to judge each try.
// The bit buffer can hold up to 40 bits, so it is kept as an exact integer Number (not 32-bit
// bitwise operations). EDGE (the edge-pixel basis) comes from tables.js, generated from Python.
"use strict";
(function () {
  var B = BR.base;
  var P2 = []; for (var q = 0; q <= 48; q++) P2.push(Math.pow(2, q));

  function JPEGError(msg) { this.message = msg; this.name = "JPEGError"; }
  JPEGError.prototype = Object.create(Error.prototype);

  function Huffman(counts, symbols) {
    var look = new Int32Array(65536).fill(-1), code = 0, k = 0;
    for (var length = 1; length <= 16; length++) {
      for (var c = 0; c < counts[length - 1]; c++) {
        if (k >= symbols.length) throw new JPEGError("Huffman table shorter than its counts");
        var sym = symbols[k++], lo = code << (16 - length), hi = lo + (1 << (16 - length));
        if (hi > 65536) throw new JPEGError("Huffman code too long");
        for (var i = lo; i < hi; i++) look[i] = (length << 8) | sym;
        code++;
      }
      code <<= 1;
    }
    this.look = look;
  }

  function Header(data) {
    if (data[0] !== 0xFF || data[1] !== 0xD8) throw new JPEGError("no SOI");
    this.qt = {}; this.dc = {}; this.ac = {}; this.restart = 0;
    var i = 2, j, n, k;
    for (;;) {
      if (i + 4 > data.length) throw new JPEGError("header runs past the data given");
      if (data[i] !== 0xFF) throw new JPEGError("expected a marker at " + i);
      var m = data[i + 1];
      if (m === 0xFF) { i++; continue; }
      var ln = B.u16be(data, i + 2), seg = data.subarray(i + 4, i + 2 + ln);
      if (seg.length < ln - 2) throw new JPEGError("header segment runs past the data given");
      if (m === 0xDB) {
        j = 0;
        while (j < seg.length) {
          var pq = seg[j] >> 4, tq = seg[j] & 15;
          n = pq ? 128 : 64;
          if (j + 1 + n > seg.length) throw new JPEGError("short quantization table");
          var vals = [];
          for (k = 0; k < 64; k++) vals.push(pq ? B.u16be(seg, j + 1 + 2 * k) : seg[j + 1 + k]);
          this.qt[tq] = vals;
          j += 1 + n;
        }
      } else if (m === 0xC4) {
        j = 0;
        while (j < seg.length) {
          var tc = seg[j] >> 4, th = seg[j] & 15, counts = Array.prototype.slice.call(seg.subarray(j + 1, j + 17));
          n = counts.reduce(function (a, b) { return a + b; }, 0);
          var table = new Huffman(counts, Array.prototype.slice.call(seg.subarray(j + 17, j + 17 + n)));
          (tc ? this.ac : this.dc)[th] = table;
          j += 17 + n;
        }
      } else if (m === 0xC0 || m === 0xC1) {
        this.height = B.u16be(seg, 1); this.width = B.u16be(seg, 3);
        var nc = seg[5];
        this.comps = [];
        for (k = 0; k < nc; k++) this.comps.push({ id: seg[6 + 3 * k], h: seg[7 + 3 * k] >> 4, v: seg[7 + 3 * k] & 15, tq: seg[8 + 3 * k] });
      } else if (m === 0xC2 || (m >= 0xC3 && m <= 0xCF && m !== 0xC4 && m !== 0xC8 && m !== 0xCC)) {
        throw new JPEGError("only baseline JPEGs are handled");
      } else if (m === 0xDD) {
        this.restart = B.u16be(seg, 0);
      } else if (m === 0xDA) {
        if (!this.comps) throw new JPEGError("scan before frame");
        var ns = seg[0], byid = {};
        this.comps.forEach(function (c) { byid[c.id] = c; });
        this.scan = [];
        for (k = 0; k < ns; k++) {
          var c = byid[seg[1 + 2 * k]];
          if (!c) throw new JPEGError("scan names an unknown component");
          c.td = seg[2 + 2 * k] >> 4; c.ta = seg[2 + 2 * k] & 15;
          this.scan.push(c);
        }
        this.scanStart = i + 2 + ln;
        break;
      }
      i += 2 + ln;
    }
    var hmax = 0, vmax = 0, self = this;
    this.comps.forEach(function (c) { hmax = Math.max(hmax, c.h); vmax = Math.max(vmax, c.v); });
    this.mcux = Math.ceil(this.width / (8 * hmax)); this.mcuy = Math.ceil(this.height / (8 * vmax));
    this.mcus = this.mcux * this.mcuy;
    this.layout = [];
    this.scan.forEach(function (c, ci) { for (var v = 0; v < c.v; v++) for (var h = 0; h < c.h; h++) self.layout.push([ci, v, h]); });
    this.bw = this.scan.map(function (c) { return self.mcux * c.h; });
    this.bh = this.scan.map(function (c) { return self.mcuy * c.v; });
    this.scan.forEach(function (c) { if (!self.qt[c.tq]) throw new JPEGError("missing quantization table"); });
    this.dcq = this.scan.map(function (c) { return self.qt[c.tq][0]; });
  }

  function State(ncomp) {
    this.buf = 0; this.nbits = 0; this.ff = false; this.mcu = 0; this.bi = 0; this.k = 0;
    this.pred = new Array(ncomp).fill(0); this.done = false; this.rst = 0; this.coefs = [];
    this.marker = null; this.awaitRst = false;
  }
  State.prototype.copy = function () {
    var s = Object.create(State.prototype);
    s.buf = this.buf; s.nbits = this.nbits; s.ff = this.ff; s.mcu = this.mcu; s.bi = this.bi; s.k = this.k;
    s.pred = this.pred.slice(); s.done = this.done; s.rst = this.rst; s.coefs = this.coefs.slice();
    s.marker = this.marker; s.awaitRst = this.awaitRst;
    return s;
  };

  function Decoder(h) {
    this.h = h;
    this.edges = h.scan.map(function (c, ci) { return new Array(h.bw[ci] * h.bh[ci]).fill(null); });
    this.q = h.scan.map(function (c) { return h.qt[c.tq]; });
    this.tables = h.scan.map(function (c) {
      if (!h.dc[c.td] || !h.ac[c.ta]) throw new JPEGError("missing Huffman table");
      return [h.dc[c.td].look, h.ac[c.ta].look];
    });
    this.layoutCi = h.layout.map(function (l) { return l[0]; });
  }
  Decoder.prototype.blockPos = function (mcu, bi) {
    var l = this.h.layout[bi], ci = l[0], c = this.h.scan[ci], row = Math.floor(mcu / this.h.mcux), col = mcu % this.h.mcux;
    return [ci, (row * c.v + l[1]) * this.h.bw[ci] + col * c.h + l[2]];
  };

  // Decode `piece` from state s (changed). -> info {error, eoi, symbols, edges:[[ci, idx, e(32)]], rest}
  Decoder.prototype.run = function (s, piece, final) {
    var h = this.h, EDGE = BR.tables.EDGE;
    var info = { error: null, eoi: false, symbols: 0 }, edgesOut = [];
    var coefs = s.coefs, nl = h.layout.length, layoutCi = this.layoutCi;
    var buf = s.buf, nbits = s.nbits, k = s.k, bi = s.bi, mcu = s.mcu;
    var i = 0, n = piece.length, curDc = null, b, e, ln, size, v;
    for (;;) {
      if (s.awaitRst) {
        if (s.marker === null) {
          while (i < n && s.marker === null) {
            b = piece[i++];
            if (s.ff) {
              s.ff = false;
              if (b >= 0xD0 && b <= 0xD7) s.marker = b;
              else if (b === 0xD9) info.error = "end of image before the last MCU";
              else info.error = "data where a restart marker should be";
              break;
            }
            if (b === 0xFF) { s.ff = true; continue; }
            info.error = "data where a restart marker should be";
            break;
          }
          if (info.error) break;
          if (s.marker === null) break;
        }
        if (s.marker !== 0xD0 + s.rst || nbits >= 8 || (nbits && (buf % P2[nbits]) !== P2[nbits] - 1)) {
          info.error = "restart marker out of sequence";
          break;
        }
        buf = 0; nbits = 0;
        s.pred = new Array(s.pred.length).fill(0);
        s.rst = (s.rst + 1) & 7;
        s.marker = null; s.awaitRst = false;
      }
      while (nbits < 32 && i < n && s.marker === null) {
        b = piece[i++];
        if (s.ff) {
          s.ff = false;
          if (b === 0x00) { buf = buf * 256 + 0xFF; nbits += 8; continue; }
          if (b === 0xD9) { info.eoi = true; final = true; i = n; break; }
          if (b >= 0xD0 && b <= 0xD7 && h.restart) { s.marker = b; break; }
          info.error = "marker FF" + (b < 16 ? "0" : "") + b.toString(16).toUpperCase() + " inside the image data";
          break;
        }
        if (b === 0xFF) { s.ff = true; continue; }
        buf = buf * 256 + b; nbits += 8;
      }
      if (info.error || s.done) break;
      if (!(nbits >= 27 || ((final || s.marker !== null) && nbits > 0))) {
        if (s.marker !== null && !s.awaitRst) info.error = "restart marker in the middle of an interval";
        break;
      }
      var ci = layoutCi[bi], tb = this.tables[ci];
      var peek = nbits >= 16 ? Math.floor(buf / P2[nbits - 16]) % 65536 : (buf * P2[16 - nbits]) % 65536;
      if (k === 0) {
        e = tb[0][peek];
        if (e < 0) { info.error = "no DC Huffman code"; break; }
        ln = e >> 8; size = e & 255;
        if (ln + size > nbits) { if (final || s.marker !== null) info.error = "image ends in the middle of a code"; break; }
        nbits -= ln;
        if (size) {
          v = Math.floor(buf / P2[nbits - size]) % P2[size];
          nbits -= size;
          if (v < P2[size - 1]) v -= P2[size] - 1;
        } else v = 0;
        if (size > 11) { info.error = "DC difference too large"; break; }
        s.pred[ci] += v;
        curDc = s.pred[ci];
        coefs = [[0, curDc * h.dcq[ci]]];
        if (Math.abs(curDc * h.dcq[ci]) > 2048 + h.dcq[ci]) { info.error = "brightness out of range"; break; }
        k = 1;
      } else {
        e = tb[1][peek];
        if (e < 0) { info.error = "no AC Huffman code"; break; }
        ln = e >> 8;
        var rs = e & 255, r = rs >> 4;
        size = rs & 15;
        if (ln + size > nbits) { if (final || s.marker !== null) info.error = "image ends in the middle of a code"; break; }
        nbits -= ln;
        if (size) {
          v = Math.floor(buf / P2[nbits - size]) % P2[size];
          nbits -= size;
          if (v < P2[size - 1]) v -= P2[size] - 1;
        }
        if (size === 0) {
          if (r === 15) {
            k += 16;
            if (k > 63) { info.error = "coefficients run past 63"; break; }
            buf = nbits ? buf % P2[nbits] : 0;     // (Python leaves the used bits; they are masked off anyway)
            continue;
          }
          k = 64;
        } else {
          k += r;
          if (k > 63) { info.error = "coefficients run past 63"; break; }
          coefs.push([k, v * this.q[ci][k]]);
          k++;
        }
      }
      info.symbols++;
      if (k >= 64) {
        if (curDc === null) curDc = s.pred[ci];
        var pos = this.blockPos(mcu, bi), ed = new Array(32).fill(128.0);
        for (var c = 0; c < coefs.length; c++) {
          var bz = EDGE[coefs[c][0]], val = coefs[c][1];
          for (var j = 0; j < 32; j++) ed[j] += val * bz[j];
        }
        edgesOut.push([pos[0], pos[1], ed]);
        coefs = []; curDc = null; k = 0; bi++;
        if (bi === nl) {
          bi = 0; mcu++;
          if (mcu === h.mcus) s.done = true;
          else if (h.restart && mcu % h.restart === 0) s.awaitRst = true;
        }
      }
      buf = nbits ? buf % P2[nbits] : 0;
    }
    if (info.eoi && !s.done && !info.error) info.error = "end of image before the last MCU";
    s.coefs = coefs;
    info.edges = edgesOut;
    info.rest = n - i;
    s.buf = nbits ? buf % P2[nbits] : 0; s.nbits = nbits; s.k = k; s.bi = bi; s.mcu = mcu;
    return info;
  };

  // Mean |pixel jump| on edges shared with blocks already decoded ("placed" or in `extra`,
  // a Map keyed ci*2^24+idx). -> [mean or null, count]
  Decoder.prototype.junction = function (edges, extra) {
    var tot = 0, cnt = 0;
    for (var a = 0; a < edges.length; a++) {
      var ci = edges[a][0], idx = edges[a][1], e = edges[a][2], w = this.h.bw[ci], placed = this.edges[ci];
      for (var side = 0; side < 2; side++) {
        var nidx = side === 0 ? (idx % w ? idx - 1 : -1) : idx - w, mine = side === 0 ? 0 : 16, theirs = side === 0 ? 8 : 24;
        if (nidx < 0) continue;
        var nb = placed[nidx];
        if (nb === null && extra) nb = extra.get(ci * 16777216 + nidx) || null;
        if (nb === null || nb === undefined) continue;
        for (var j = 0; j < 8; j++) tot += Math.abs(e[mine + j] - nb[theirs + j]);
        cnt += 8;
      }
    }
    return [cnt ? tot / cnt : null, cnt];
  };

  BR.jpeg = { Header: Header, State: State, Decoder: Decoder, JPEGError: JPEGError, Huffman: Huffman };
})();
