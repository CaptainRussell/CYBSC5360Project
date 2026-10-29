// word.py: putting a Word (.doc, Compound File) document's blocks back in order.
"use strict";
(function () {
  var B = BR.base, BS = 512, PlaceError = B.PlaceError;
  var MAGIC = B.unhex("d0cf11e0a1b11ae1"), FREE = 0xFFFFFFFF, DIFSECT = 0xFFFFFFFC, FATSECT = 0xFFFFFFFD;
  var PARA_END = [0x0D, 0x07, 0x0C];

  function WordError(msg) { this.message = msg; this.name = "WordError"; }
  WordError.prototype = Object.create(PlaceError.prototype);
  var u32s = B.u32les;
  function u16(b, i) { return B.u16le(b, i); }
  function u32(b, i) { return B.u32le(b, i); }

  // ---- text decoding exactly as Python's codecs with errors="replace" -------------------
  var CP1252 = [0x20AC, -1, 0x201A, 0x0192, 0x201E, 0x2026, 0x2020, 0x2021, 0x02C6, 0x2030, 0x0160, 0x2039, 0x0152, -1, 0x017D, -1,
    -1, 0x2018, 0x2019, 0x201C, 0x201D, 0x2022, 0x2013, 0x2014, 0x02DC, 0x2122, 0x0161, 0x203A, 0x0153, -1, 0x017E, 0x0178];
  function cp1252(d, lo, hi) {
    var s = "";
    for (var i = lo; i < hi; i++) {
      var c = d[i];
      if (c >= 0x80 && c < 0xA0) { var u = CP1252[c - 0x80]; s += String.fromCharCode(u < 0 ? 0xFFFD : u); }
      else s += String.fromCharCode(c);
    }
    return s;
  }
  // (a character outside the Basic Multilingual Plane becomes one private-use character, so
  // that, as in Python, it counts as one character)
  function utf16(d, lo, hi, strict) {
    var s = "";
    for (var i = lo; i + 1 < hi; i += 2) {
      var u = d[i] | (d[i + 1] << 8);
      if (u >= 0xD800 && u <= 0xDBFF && i + 3 < hi) {
        var v = d[i + 2] | (d[i + 3] << 8);
        if (v >= 0xDC00 && v <= 0xDFFF) { s += ""; i += 2; continue; }
      }
      if (u >= 0xD800 && u <= 0xDFFF) { if (strict) return null; s += "�"; continue; }
      s += String.fromCharCode(u);
    }
    if ((hi - lo) % 2) { if (strict) return null; s += "�"; }
    return s;
  }
  var NONPRINT = /[\p{C}\p{Z}]/u;
  function isprintable(ch) { return ch === " " || !NONPRINT.test(ch); }

  function Word(blocks, log) {
    this.blocks = blocks; this.free = new Map(); var self = this;
    blocks.forEach(function (b) { self.free.set(b.name, b); });
    this.log = log || function () {};
  }
  var P = Word.prototype;
  P.placeSector = function (sector, block, how) { this.L.put(sector + 1, block, how); this.free.delete(block.name); };
  P.atSector = function (sector) { return this.L.at[sector + 1]; };
  P.unique = function (sector, test, how, rank) {
    if (this.atSector(sector) !== null) return true;
    var c = [];
    this.free.forEach(function (b) { if (test(b.data)) c.push(b); });
    if (rank && c.length > 1) {
      var rk = c.map(function (b, i) { return [-rank(b.data), i, b]; }).sort(function (a, b) { return a[0] - b[0] || a[1] - b[1]; });
      c = rk.map(function (x) { return x[2]; });
      if (rank(c[0].data) > rank(c[1].data)) c = c.slice(0, 1);
    }
    if (c.length && c.every(function (x) { return B.eq(x.data, c[0].data); })) {
      this.placeSector(sector, c[0], how + (c.length > 1 ? " (identical copies)" : ""));
      return true;
    }
    return false;
  };

  P.findHeader = function () {
    var heads = this.blocks.filter(function (b) { return B.startsWith(b.data, MAGIC); });
    if (heads.length !== 1) throw new WordError("expected one block starting with the Compound File signature, found " + heads.length);
    var h = heads[0].data;
    if (u16(h, 0x1E) !== 9) throw new WordError("only 512-byte sectors are handled");
    this.head = h;
    this.nfat = u32(h, 0x2C); this.dirStart = u32(h, 0x30); this.minifatStart = u32(h, 0x3C);
    if (u32(h, 0x48)) throw new WordError("files with an extended FAT list are not handled");
    this.difat = u32s(h.subarray(0x4C, 0x200)).filter(function (x) { return x !== FREE; }).slice(0, this.nfat);
    this.headerBlock = heads[0];
    this.log("header", heads[0].name, this.nfat + " FAT blocks at sectors [" + this.difat.join(", ") + "]");
  };
  P.cutoff = function () { return u32(this.head, 0x38); };
  P.findFat = function () {
    var limit = 128 * this.nfat, scored = [], self = this;
    this.difat.forEach(function (sec, k) {
      self.free.forEach(function (b) {
        var v = u32s(b.data), i;
        for (i = 0; i < v.length; i++) if (!(v[i] < limit || v[i] >= DIFSECT)) return;
        for (i = 0; i < self.difat.length; i++) { var s = self.difat[i]; if (s >= 128 * k && s < 128 * (k + 1) && v[s - 128 * k] !== FATSECT) return; }
        var straight = 0, anyUsed = false;
        for (i = 0; i < v.length; i++) { if (v[i] === 128 * k + i + 1) straight++; if (v[i] !== FREE) anyUsed = true; }
        if (straight || anyUsed) scored.push([straight, k, b, scored.length]);
      });
    });
    scored.sort(function (a, b) { return b[0] - a[0] || a[3] - b[3]; });
    this.fatBlocks = new Map(); var used = new Set();
    scored.forEach(function (t) {
      if (self.fatBlocks.has(t[1]) || used.has(t[2].name)) return;
      self.fatBlocks.set(t[1], t[2]); used.add(t[2].name);
    });
    if (this.fatBlocks.size !== this.nfat) throw new WordError("could not find every FAT block");
    this.fat = [];
    for (var k = 0; k < this.nfat; k++) this.fat = this.fat.concat(u32s(this.fatBlocks.get(k).data));
    var n = 0;
    for (var i = 0; i < this.fat.length; i++) if (this.fat[i] !== FREE) n = i + 1;
    this.L = new BR.Layout(n + 1);
    this.L.put(0, this.headerBlock, "Compound File header");
    this.free.delete(this.headerBlock.name);
    this.difat.forEach(function (sec, k) { self.placeSector(sec, self.fatBlocks.get(k), "FAT block " + k); });
    this.log("FAT", "the file has " + n + " sectors (" + (n + 1) + " blocks with the header)");
  };
  P.chain = function (start) {
    var out = [], s = start, seen = new Set();
    while (s < this.fat.length && !seen.has(s)) {
      out.push(s); seen.add(s); s = this.fat[s];
      if (s >= DIFSECT) break;
    }
    return out;
  };

  var ROOT = (function () { var s = "Root Entry", u = new Uint8Array(2 * s.length); for (var i = 0; i < s.length; i++) u[2 * i] = s.charCodeAt(i); return u; })();
  function dirEntries(d) { var n = 0; for (var i = 0; i < 4; i++) { var t = d[128 * i + 66]; if (t === 1 || t === 2 || t === 5) n++; } return n; }
  function dirLike(d) {
    var ok = 0;
    for (var i = 0; i < 4; i++) {
      var o = 128 * i, nl = u16(d, o + 64);
      if (nl === 0 && !B.anyNonZero(d, o, o + 64)) continue;
      var t = d[o + 66];
      // e[nl-2:nl] == b"\0\0" (for nl 0 that slice is empty, so it fails)
      if (nl % 2 || nl > 64 || (t !== 1 && t !== 2 && t !== 5) || nl < 2 || d[o + nl - 2] !== 0 || d[o + nl - 1] !== 0) return false;
      var name = utf16(d, o, o + nl - 2, true);
      if (name === null || !name) return false;
      for (var k = 0; k < name.length; k++) { var c = name.charCodeAt(k); if (c < 32 && c !== 1 && c !== 5) return false; }
      ok++;
    }
    return ok > 0;
  }
  P.dirFitsFat = function (d) {
    var cutoff = this.cutoff();
    for (var i = 0; i < 4; i++) {
      var o = 128 * i, t = d[o + 66];
      if (t !== 2 && t !== 5) continue;
      var start = u32(d, o + 116), size = u32(d, o + 120);
      if (t === 2 && size < cutoff) continue;
      if (size === 0 && start >= DIFSECT) continue;
      if (start >= this.fat.length || this.chain(start).length !== Math.ceil(size / BS)) return false;
    }
    return true;
  };
  P.findDirectory = function () {
    var secs = this.chain(this.dirStart), self = this;
    this.unique(secs[0], function (d) { return B.startsWith(d, ROOT) && d[66] === 5 && self.dirFitsFat(d); }, "directory (Root Entry)", dirEntries);
    secs.slice(1).forEach(function (s) {
      self.unique(s, function (d) { return dirLike(d) && !B.startsWith(d, ROOT) && self.dirFitsFat(d); }, "directory", dirEntries);
    });
    var raw = B.concat(secs.map(function (s) { var b = self.atSector(s); return b ? b.data : new Uint8Array(BS); }));
    this.entries = [];
    for (var i = 0; i < raw.length / 128; i++) {
      var o = 128 * i, nl = u16(raw, o + 64), t = raw[o + 66];
      if (!(nl >= 2 && nl <= 64) || (t !== 1 && t !== 2 && t !== 5)) continue;
      this.entries.push({ id: i, name: utf16(raw, o, o + nl - 2, false), type: t, start: u32(raw, o + 116), size: u32(raw, o + 120) });
    }
    this.streams = new Map();
    this.entries.forEach(function (e) { self.streams.set(e.name, e); });
    this.log("directory", this.entries.map(function (e) { return e.name + " (" + e.size + " bytes)"; }).join(", "));
  };
  P.findSmallParts = function () {
    var root = this.streams.get("Root Entry"), cutoff = this.cutoff(), self = this;
    if (this.minifatStart < DIFSECT) {
      this.chain(this.minifatStart).forEach(function (s) {
        self.unique(s, function (d) { var v = u32s(d); return v.every(function (x) { return x < 4096 || x >= DIFSECT; }) && B.anyNonZero(d, 0, 4); }, "mini FAT");
      });
    }
    if (root && root.start < DIFSECT) {
      var secs = this.chain(root.start);
      this.entries.forEach(function (e) {
        if (!(e.type === 2 && e.size < cutoff)) return;
        var off = e.start * 64;
        if (Math.floor(off / BS) < secs.length && e.name === "\x01CompObj") {
          var rel = off % BS;
          self.unique(secs[Math.floor(off / BS)], function (d) { return d[rel] === 1 && d[rel + 1] === 0 && d[rel + 2] === 0xFE && d[rel + 3] === 0xFF; }, "mini stream (CompObj)");
        }
      });
    }
  };

  P.wdSize = function () { return this.streams.get("WordDocument").size; };
  P.wordDocument = function () {
    var e = this.streams.get("WordDocument"), self = this;
    if (!e) throw new WordError("no WordDocument stream");
    this.wd = this.chain(e.start);
    this.unique(this.wd[0], function (d) { return d[0] === 0xEC && d[1] === 0xA5; }, "Word header (FIB)");
    var fib0 = this.atSector(this.wd[0]).data;
    this.tableName = u16(fib0, 10) & 0x200 ? "1Table" : "0Table";
    var csw = u16(fib0, 32), i = 34 + 2 * csw, cslw = u16(fib0, i);
    this.ccpText = u32(fib0, i + 2 + 12);
    var j = i + 2 + 4 * cslw;
    this.cbFclcb = u16(fib0, j); this.fclcbAt = j + 2;
    var te = this.streams.get(this.tableName);
    if (!te) throw new WordError("no " + this.tableName + " stream");
    this.tableSize = te.size;
    this.tableMini = te.size < this.cutoff();
    if (this.tableMini) { this.ts = []; this.tmini = this.miniChain(te.start); }
    else this.ts = this.chain(te.start);
    var end = this.fclcbAt + 8 * this.cbFclcb;
    for (var k = 1; k <= Math.floor((end - 1) / BS); k++) {
      (function (k) {
        self.unique(self.wd[k], function (d) { return self.fibPartOk(d, k); }, "Word header, part " + (k + 1), function (d) { return self.fibPairsUsed(d, k); });
      })(k);
    }
    var parts = [];
    for (k = 0; k <= Math.floor((end - 1) / BS); k++) { var b = this.atSector(this.wd[k]); parts.push(b ? b.data : new Uint8Array(BS)); }
    var vals = u32s(B.concat(parts).subarray(this.fclcbAt, end));
    this.fclcb = [];
    for (k = 0; k < this.cbFclcb; k++) this.fclcb.push([vals[2 * k], vals[2 * k + 1]]);
    this.log("Word header", this.ccpText + " characters of text; " + this.fclcb.filter(function (p) { return p[1]; }).length + " tables listed");
  };
  P.fibFirstPair = function (k) { return Math.max(0, Math.ceil((k * BS - this.fclcbAt) / 8)); };
  P.fibPairsUsed = function (d, k) {
    var n = 0;
    for (var pair = this.fibFirstPair(k); pair < this.cbFclcb; pair++) {
      var off = this.fclcbAt + 8 * pair - k * BS;
      if (off + 8 > BS) break;
      if (u32(d, off + 4) > 0) n++;
    }
    return n;
  };
  P.fibPartOk = function (d, k) {
    var ok = 0;
    for (var pair = this.fibFirstPair(k); pair < this.cbFclcb; pair++) {
      var off = this.fclcbAt + 8 * pair - k * BS;
      if (off + 8 > BS) break;
      var fc = u32(d, off), lcb = u32(d, off + 4);
      if (lcb > this.tableSize || (lcb && fc + lcb > this.tableSize)) return false;
      ok++;
    }
    var v = u32s(d), rising = 0, nondec = true;
    for (var i = 1; i < v.length; i++) { if (v[i - 1] < v[i]) rising++; if (v[i - 1] > v[i]) nondec = false; }
    if ((rising >= 16 && nondec) || fkpShape(d, this.wdSize())) return false;
    return ok > 0;
  };
  P.miniChain = function (start) {
    var mf = [], self = this;
    (this.minifatStart < DIFSECT ? this.chain(this.minifatStart) : []).forEach(function (sec) {
      var b = self.atSector(sec);
      if (b === null) throw new WordError("the mini FAT block is not placed");
      mf = mf.concat(u32s(b.data));
    });
    var out = [], s = start, seen = new Set();
    while (s < mf.length && !seen.has(s)) { out.push(s); seen.add(s); s = mf[s]; }
    this.rootSecs = this.chain(this.streams.get("Root Entry").start);
    return out;
  };
  P.tloc = function (off) {
    if (!this.tableMini) return [this.ts[Math.floor(off / BS)], off % BS];
    var mo = 64 * this.tmini[Math.floor(off / 64)] + off % 64;
    return [this.rootSecs[Math.floor(mo / BS)], mo % BS];
  };
  P.tread = function (off, n) {
    var parts = [], unit = this.tableMini ? 64 : BS;
    while (n > 0) {
      var l = this.tloc(off), step = Math.min(n, unit - off % unit), b = this.atSector(l[0]);
      if (!b) return null;
      parts.push(b.data.subarray(l[1], l[1] + step));
      off += step; n -= step;
    }
    return B.concat(parts);
  };
  P.table = function (k) { return k < this.fclcb.length ? this.fclcb[k] : [0, 0]; };
  P.clxOk = function (raw) {
    var pieces;
    try { pieces = clx(raw); } catch (e) { if (e instanceof WordError || e instanceof RangeError) return false; throw e; }
    if (!pieces || !pieces.length || pieces[0][0] !== 0 || pieces[pieces.length - 1][1] < this.ccpText) return false;
    var self = this;
    return pieces.every(function (p) { return p[2] + (p[1] - p[0]) * (p[3] ? 1 : 2) <= self.wdSize(); });
  };
  P.tableStream = function () {
    var self = this;
    this.bte = {};
    [[12, "character"], [13, "paragraph"]].forEach(function (kw) {
      var t = self.table(kw[0]), fc = t[0], lcb = t[1];
      if (!lcb) return;
      var n = Math.floor((lcb - 4) / 8), l = self.tloc(fc);
      if (l[1] + lcb <= BS) self.unique(l[0], function (d) { return bteOk(d, l[1], n, self.wdSize()); }, kw[1] + " formatting index");
    });
    var t33 = this.table(33);
    if (t33[1]) { var l = this.tloc(t33[0]); this.unique(l[0], function (d) { return self.clxOk(d.subarray(l[1], l[1] + t33[1])); }, "piece table"); }
    var t1 = this.table(1);
    if (t1[1] && t1[0] === 0) {
      var l0 = this.tloc(0), NORMAL = B.fromB("N\0o\0r\0m\0a\0l\0");
      this.unique(l0[0], function (d) { var v = u16(d, l0[1]); return (v === 0x12 || v === 0x14 || v === 0x16 || v === 0x18) && B.find(d, NORMAL, l0[1]) >= 0; }, "stylesheet");
    }
    [12, 13].forEach(function (k) {
      var t = self.table(k), raw = self.tread(t[0], t[1]);
      if (raw === null) throw new WordError("formatting index " + k + " could not be placed");
      var n = Math.floor((t[1] - 4) / 8), fcs = u32s(raw.subarray(0, 4 * (n + 1))), pns = u32s(raw.subarray(4 * (n + 1), 4 * (n + 1) + 4 * n)), out = [];
      for (var i = 0; i + 1 < fcs.length && i < pns.length; i++) out.push([fcs[i], fcs[i + 1], pns[i]]);
      self.bte[k] = out;
    });
    var raw = this.tread(t33[0], t33[1]);
    this.pieces = raw ? clx(raw) : [];
    this.log("pieces", this.pieces.map(function (p) { return "chars " + p[0] + "-" + p[1] + " at byte " + p[2] + (p[3] ? " (8-bit)" : ""); }).join("; "));
  };
  P.fkps = function () {
    var self = this;
    this.paraEnds = new Set();
    [[12, "character"], [13, "paragraph"]].forEach(function (kw) {
      self.bte[kw[0]].forEach(function (t) {
        var fc0 = t[0], fc1 = t[1], pn = t[2];
        if (pn >= self.wd.length) throw new WordError("formatting page " + pn + " is past the end of the document");
        var test = function (d) { return fkpOk(d, fc0, fc1); }, d;
        if (self.unique(self.wd[pn], test, kw[1] + " formatting page")) d = self.atSector(self.wd[pn]).data;
        else {
          var c = [];
          self.free.forEach(function (b) { if (test(b.data)) c.push(b.data); });
          var runs = new Set(c.map(function (x) { return B.bstr(x, 0, 4 * (x[511] + 1)); }));
          if (runs.size !== 1) throw new WordError("formatting page " + pn + " could not be placed");
          d = c[0];
        }
        if (kw[0] === 13) u32s(d.subarray(4, 4 * (d[511] + 1))).forEach(function (e) { self.paraEnds.add(e); });
      });
    });
  };
  P.text = function () {
    var self = this;
    this.textSectors = [];
    this.pieces.forEach(function (p) {
      var w = p[3] ? 1 : 2, end = p[2] + (p[1] - p[0]) * w;
      for (var s = Math.floor(p[2] / BS); s <= Math.floor((end - 1) / BS); s++) self.textSectors.push([s, Math.max(p[2], s * BS), Math.min(end, (s + 1) * BS), w]);
    });
    var placed = 0;
    this.textSectors.forEach(function (t) {
      var s = t[0], lo = t[1], hi = t[2], w = t[3], ends = new Set();
      self.paraEnds.forEach(function (e) { if (lo < e && e <= hi) ends.add(e - w - s * BS); });
      if (!ends.size) return;
      var rlo = lo - s * BS, rhi = hi - s * BS;
      var test = function (d) {
        var bad = false;
        ends.forEach(function (i) { if (PARA_END.indexOf(d[i]) < 0 || (w === 2 && d[i + 1])) bad = true; });
        if (bad) return false;
        for (var i = rlo; i < rhi; i += w) if (d[i] === 0x0D && !(w === 2 && d[i + 1]) && !ends.has(i)) return false;
        return true;
      };
      if (self.unique(self.wd[s], test, "text (paragraph marks match)")) placed++;
    });
    this.log("text", placed + " of " + this.textSectors.length + " text blocks placed by their paragraph marks");
  };
  P.textGaps = function () {
    var secs = this.textSectors, self = this;
    var todo0 = secs.filter(function (t) { return self.atSector(self.wd[t[0]]) === null; });
    if (!todo0.length) return;
    var w = todo0[0][3];
    function textOf(d) { return w === 2 ? utf16(d, 0, BS, false) : cp1252(d, 0, BS); }
    var cands = [];
    this.free.forEach(function (b) {
      var t = textOf(b.data), good = 0;
      for (var i = 0; i < t.length; i++) { var ch = t.charAt(i); if (isprintable(ch) || ch === "\r" || ch === "\n" || ch === "\t") good++; }
      if (good / Math.max(1, t.length) > 0.97 && t.indexOf("\r") < 0) cands.push(b);
    });
    var texts = [];
    secs.forEach(function (t) { var b = self.atSector(self.wd[t[0]]); if (b) texts.push(textOf(b.data)); });
    var model = new CharModel(texts.concat(cands.map(function (b) { return textOf(b.data); })));
    var todo = secs.filter(function (t) { return self.atSector(self.wd[t[0]]) === null; }).map(function (t) { return t[0]; });
    var idx = new Map(); secs.forEach(function (t, i) { idx.set(t[0], i); });
    var placed = 0;
    while (todo.length) {
      var pool = cands.filter(function (b) { return self.free.has(b.name); });
      if (!pool.length) break;
      var best = null;
      for (var q = 0; q < todo.length; q++) {
        var s0 = todo[q], i = idx.get(s0);
        var left = i > 0 ? self.atSector(self.wd[secs[i - 1][0]]) : null;
        var right = i + 1 < secs.length ? self.atSector(self.wd[secs[i + 1][0]]) : null;
        if (left === null && right === null) continue;
        var lt = left ? textOf(left.data) : null, rt = right ? textOf(right.data) : null;
        var scores = pool.map(function (b, k) {
          var t = textOf(b.data), sc = 0.0;
          if (left !== null) sc += model.join(lt, t);
          if (right !== null) sc += model.join(t, rt);
          return [sc / ((left !== null ? 1 : 0) + (right !== null ? 1 : 0)), k, b];
        });
        scores.sort(function (a, b) { return b[0] - a[0] || a[1] - b[1]; });
        var margin = scores[0][0] - (scores.length > 1 ? scores[1][0] : scores[0][0] - 50);
        if (best === null || margin > best[0]) best = [margin, s0, scores[0][2]];
      }
      if (best === null) break;
      this.placeSector(this.wd[best[1]], best[2], "text continues its neighbours' words");
      todo.splice(todo.indexOf(best[1]), 1);
      placed++;
    }
    this.log("text", placed + " text blocks placed by how their words join");
  };
  P.ascendingTables = function () {
    var placed = 0, self = this, lim = this.wdSize();
    (this.tableMini ? [] : this.fclcb).forEach(function (t) {
      var fc = t[0], lcb = t[1];
      if (lcb < 2 * BS) return;
      var first = Math.floor(fc / BS), last = Math.floor((fc + lcb - 1) / BS), head = self.atSector(self.ts[first]);
      if (head === null) return;
      var phase = fc % 4, hv = u32s(head.data.subarray(fc % BS));
      if (hv.length < 8) return;
      for (var i = 1; i < hv.length; i++) if (!(hv[i - 1] < hv[i])) return;
      var prev = hv[hv.length - 1];
      for (var k = first + 1; k <= last; k++) {
        var b = self.atSector(self.ts[k]);
        if (b === null) {
          var c = [];
          self.free.forEach(function (x) {
            var v = u32s(x.data.subarray(phase));
            if (!(prev < v[0] && v[0] <= lim)) return;
            for (var q = 1; q < 8; q++) if (!(v[q - 1] < v[q])) return;
            c.push([v[0], c.length, x]);
          });
          if (!c.length) break;
          c.sort(function (a, b) { return a[0] - b[0] || a[1] - b[1]; });
          self.placeSector(self.ts[k], c[0][2], "ascending table, continues the block before");
          placed++; b = c[0][2];
        }
        var v = u32s(b.data.subarray(phase)), asc = true;
        for (var q2 = 1; q2 < v.length; q2++) if (!(v[q2 - 1] < v[q2])) { asc = false; break; }
        if (!asc) { placed += self.plcData(fc, lcb, k, b, phase); break; }
        prev = v[v.length - 1];
      }
    });
    this.log("tables", placed + " blocks of ascending tables placed");
  };
  P.plcData = function (fc, lcb, k, b, phase) {
    var v = u32s(b.data.subarray(phase)), lim = this.wdSize(), stop = -1;
    for (var i = 1; i < v.length; i++) if (v[i] <= v[i - 1] || v[i] > lim) { stop = i; break; }
    if (stop < 0) throw new WordError("table records not found");
    var ds = k * BS + phase + 4 * stop, ncp = Math.floor((ds - fc) / 4), n = ncp - 1;
    if (n <= 0 || (lcb - 4 * ncp) % n) return 0;
    var rec = Math.floor((lcb - 4 * ncp) / n);
    if (!(rec > 0 && rec <= 64) || ds % BS + rec > BS) return 0;
    var tmpl = b.data.slice(ds % BS, ds % BS + rec), end = fc + lcb, placed = 0, self = this;
    for (var j = k + 1; j <= Math.floor((end - 1) / BS); j++) {
      var lo = j * BS, hi = Math.min(end, (j + 1) * BS), want = new Uint8Array(hi - lo);
      for (var x = lo; x < hi; x++) want[x - lo] = tmpl[(((x - ds) % rec) + rec) % rec];
      if (self.unique(self.ts[j], function (d) { return B.eq(d.subarray(0, want.length), want); }, "table records (repeating)")) placed++;
    }
    return placed;
  };
  var FMTID = { "\x05SummaryInformation": B.unhex("e0859ff2f94f6810ab9108002b27b3d9"),
    "\x05DocumentSummaryInformation": B.unhex("02d5cdd59c2e1b10939708002b2cf9ae") };
  function propsetEnd(d) {
    var n = u32(d, 24), end = 28 + 20 * n;
    for (var k = 0; k < Math.min(n, 4); k++) {
      var off = u32(d, 28 + 20 * k + 16);
      if (off + 4 <= d.length) end = Math.max(end, off + u32(d, off));
    }
    return end;
  }
  P.zeroRegions = function () {
    var self = this;
    this.expectZero = new Map();
    var wd = this.wd, parts = [];
    for (var k = 0; k < 3; k++) { var b = this.atSector(wd[k]); if (b) parts.push(b.data); }
    var fib = B.concat(parts), end = this.fclcbAt + 8 * this.cbFclcb;
    if (fib.length >= end + 2) { var cswNew = u16(fib, end); if (cswNew <= 8) end += 2 + 2 * cswNew; }
    var textStart = this.pieces.length ? Math.min.apply(null, this.pieces.map(function (p) { return p[2]; })) : end;
    this.zeroRange(wd, end, textStart);
    var root = this.streams.get("Root Entry");
    if (root && root.start < DIFSECT) this.zeroRange(this.chain(root.start), root.size, this.chain(root.start).length * BS);
    this.entries.forEach(function (e) {
      if (e.type !== 2 || e.size < 4096) return;
      var secs = self.chain(e.start);
      self.zeroRange(secs, e.size, secs.length * BS);
      if (e.name.charAt(0) === "\x05") {
        var first = self.atSector(secs[0]);
        if (first === null) {
          self.unique(secs[0], function (d) {
            return d[0] === 0xFE && d[1] === 0xFF && d[2] === 0 && d[3] === 0 && (!FMTID[e.name] || B.eq(d.subarray(28, 44), FMTID[e.name]));
          }, "property set " + e.name.slice(1));
          first = self.atSector(secs[0]);
        }
        if (first !== null) self.zeroRange(secs, propsetEnd(first.data), e.size);
      }
    });
    var placed = 0, keys = Array.from(this.expectZero.keys()).sort(function (a, b) { return a - b; });
    keys.forEach(function (sec) {
      var r = self.expectZero.get(sec);
      if (r[0] === 0 && r[1] === BS && self.unique(sec, function (d) { return !B.anyNonZero(d); }, "nothing here (zeros)")) placed++;
    });
    this.log("empty", placed + " all-zero blocks placed");
  };
  P.zeroRange = function (secs, lo, hi) {
    for (var k = Math.floor(lo / BS); k < Math.min(secs.length, Math.ceil(hi / BS)); k++) {
      var a = Math.max(lo, k * BS) - k * BS, b = Math.min(hi, (k + 1) * BS) - k * BS;
      if (a < b) {
        var old = this.expectZero.get(secs[k]);
        this.expectZero.set(secs[k], old ? [Math.min(a, old[0]), Math.max(b, old[1])] : [a, b]);
      }
    }
  };
  function contains(hay, lo, hi, gram) {   // gram in hay[lo:hi]
    return B.find(hay.subarray(Math.max(0, lo), Math.max(0, hi)), gram) >= 0;
  }
  function join(a, b) {   // _join(a, b, w=6, g=3)
    var w = 6, g = 3, win = B.concat([a.subarray(a.length - w), b.subarray(0, w)]), hits = 0, tot = 0;
    for (var i = w - g + 1; i < w; i++) {
      var gram = win.subarray(i, i + g);
      tot++;
      if (contains(a, 0, a.length - w, gram) || contains(b, w, b.length, gram)) hits++;
    }
    return hits / tot;
  }
  P.FONT_TABLE = 15;   // SttbfFfn's pair in the FIB's table list
  P.fontTableFits = function (p, b) {   // _font_table_fits()
    if (this.FONT_TABLE >= this.fclcb.length) return null;
    var self = this, fc = this.fclcb[this.FONT_TABLE][0], lcb = this.fclcb[this.FONT_TABLE][1];
    if (!lcb || fc + lcb > this.tableSize) return null;
    var involved = new Set(), step = this.tableMini ? 64 : BS;
    for (var o = fc; o < fc + lcb; o += step) involved.add(this.tloc(o)[0] + 1);
    involved.add(this.tloc(fc + lcb - 1)[0] + 1);
    if (!involved.has(p)) return null;
    function byte(off) {
      var l = self.tloc(off), blk = l[0] + 1 === p ? b : self.atSector(l[0]);
      return blk === null || blk === undefined ? null : blk.data[l[1]];
    }
    var lo = byte(fc), hi = byte(fc + 1), z0 = byte(fc + 2), z1 = byte(fc + 3);
    if (lo === null || hi === null || z0 !== 0 || z1 !== 0) return (lo === null || hi === null || z0 === null || z1 === null) ? null : false;
    var off = fc + 4, end = fc + lcb, count = lo | (hi << 8);
    for (var k = 0; k < count; k++) {
      if (off >= end) return false;
      var n = byte(off);
      if (n === null) return null;
      off += 1 + n;
    }
    return off === end;
  };
  P.leftovers = function (candidates) {
    var self = this, todo = [];
    for (var p = 1; p < this.L.n; p++) if (this.L.at[p] === null) todo.push(p);
    if (!todo.length) return;
    var cands = candidates.filter(function (b) { return self.free.has(b.name); }), starts = new Map();
    this.fclcb.forEach(function (t) {
      if (!t[1] || t[0] >= self.tableSize) return;
      var l = self.tloc(t[0]);
      if (l[0] === undefined) return;
      if (!starts.has(l[0] + 1)) starts.set(l[0] + 1, []);
      starts.get(l[0] + 1).push(l[1]);
    });
    var textSecs = new Set((this.textSectors || []).map(function (t) { return self.wd[t[0]]; })), wdSet = new Set(this.wd);
    function score(b, p) {
      var z = self.expectZero.get(p - 1);
      if (z && B.anyNonZero(b.data, z[0], z[1])) return null;
      var sc = 0.0, left = self.L.at[p - 1], right = p + 1 < self.L.n ? self.L.at[p + 1] : null;
      if (left !== null) sc += join(left.data, b.data);
      if (right !== null) sc += join(b.data, right.data);
      if (wdSet.has(p - 1) && !textSecs.has(p - 1) && fkpShape(b.data, self.wdSize())) sc += 2;
      (starts.get(p) || []).forEach(function (o) { if (b.data[o] === 0xFF && b.data[o + 1] === 0xFF) sc += 4; });
      var fonts = self.fontTableFits(p, b);
      if (fonts !== null) sc += fonts ? 10 : -10;   // the font table's records chain up
      return sc;
    }
    var table = new Map();
    cands.forEach(function (b) { todo.forEach(function (p) { table.set(b.name + "|" + p, score(b, p)); }); });
    if (todo.length <= 8 && cands.length <= 12) {
      var best = null, bestSc = null, perm = [], used = new Array(cands.length).fill(false);
      (function rec(depth) {   // itertools.permutations order
        if (depth === todo.length) {
          var tot = 0;
          for (var i = 0; i < perm.length; i++) { var v = table.get(cands[perm[i]].name + "|" + todo[i]); if (v === null) return; tot += v; }
          if (bestSc === null || tot > bestSc) { best = perm.slice(); bestSc = tot; }
          return;
        }
        for (var c = 0; c < cands.length; c++) {
          if (used[c]) continue;
          used[c] = true; perm.push(c); rec(depth + 1); perm.pop(); used[c] = false;
        }
      })(0);
      if (best === null) throw new WordError("no way to fill the last " + todo.length + " positions");
      best.forEach(function (c, i) { self.L.put(todo[i], cands[c], "fits its neighbours best"); self.free.delete(cands[c].name); });
    } else {
      todo.forEach(function (p) {
        var ok = [];
        cands.forEach(function (b, k) { var v = table.get(b.name + "|" + p); if (self.free.has(b.name) && v !== null) ok.push([v, k, b]); });
        if (ok.length) {
          ok.sort(function (a, b) { return b[0] - a[0] || a[1] - b[1]; });
          self.L.put(p, ok[0][2], "fits its neighbours best"); self.free.delete(ok[0][2].name);
        }
      });
    }
    this.log("last blocks", todo.length + " placed by how they join their neighbours");
  };
  P.anchor = function () {
    this.findHeader(); this.findFat(); this.findDirectory(); this.findSmallParts(); this.wordDocument();
    this.tableStream(); this.fkps(); this.text(); this.textGaps(); this.ascendingTables(); this.zeroRegions();
    return this.L;
  };

  function CharModel(texts, n) {
    n = n || 6; this.n = n;
    var c = [], k, i;
    for (k = 0; k <= n; k++) c.push(new Map());
    texts.forEach(function (t) {
      for (k = 1; k <= n; k++) for (i = 0; i + k <= t.length; i++) { var g = t.substr(i, k); c[k].set(g, (c[k].get(g) || 0) + 1); }
    });
    this.c = c; this.ctx = []; this.types = [];
    for (k = 0; k <= n; k++) { this.ctx.push(new Map()); this.types.push(new Map()); }
    for (k = 1; k <= n; k++) {
      var ctx = this.ctx[k], types = this.types[k];
      c[k].forEach(function (v, g) { var h = g.slice(0, -1); ctx.set(h, (ctx.get(h) || 0) + v); types.set(h, (types.get(h) || 0) + 1); });
    }
    this.V = c[1].size + 1;
    var words = new Map();
    texts.forEach(function (t) {
      var ws = t.match(/[A-Za-z]+/g) || [];
      ws.slice(1, -1).forEach(function (wd) { var l = wd.toLowerCase(); words.set(l, (words.get(l) || 0) + 1); });
    });
    this.words = words;
  }
  CharModel.prototype.p = function (h, ch) {
    var pr = 1.0 / this.V;
    for (var k = 1; k <= this.n; k++) {
      if (h.length < k - 1) break;
      var hh = k > 1 ? h.slice(h.length - (k - 1)) : "", tot = this.ctx[k].get(hh) || 0;
      if (tot) {
        var lam = tot / (tot + this.types[k].get(hh));
        pr = lam * (this.c[k].get(hh + ch) || 0) / tot + (1 - lam) * pr;
      }
    }
    return pr;
  };
  CharModel.prototype.join = function (a, b, span) {
    span = span || 10;
    if (!a) return 0.0;
    var h = a.slice(-(this.n - 1)), sc = 0.0;
    for (var i = 0; i < Math.min(span, b.length); i++) {
      var ch = b.charAt(i);
      sc += Math.log(this.p(h, ch));
      h = (h + ch).slice(-(this.n - 1));
    }
    var left = /[A-Za-z]+$/.exec(a), right = /^[A-Za-z]+/.exec(b);
    if (left && right) sc += (this.words.get((left[0] + right[0]).toLowerCase()) || 0) ? 2.0 : -2.0;
    return sc;
  };

  function bteOk(d, off, n, wdsize) {
    var need = off + 4 * (2 * n + 1);
    if (need > BS) return false;
    var v = u32s(d.subarray(off, need)), fcs = v.slice(0, n + 1), pns = v.slice(n + 1);
    for (var i = 1; i < fcs.length; i++) if (!(fcs[i - 1] < fcs[i])) return false;
    if (fcs[fcs.length - 1] > wdsize) return false;
    return pns.every(function (p) { return p > 0 && p < Math.floor(wdsize / BS) + 1; });
  }
  function fkpOk(d, fc0, fc1) {
    var crun = d[511];
    if (!(crun >= 1 && crun <= 101)) return false;
    var v = u32s(d.subarray(0, 4 * (crun + 1)));
    for (var i = 1; i < v.length; i++) if (!(v[i - 1] < v[i])) return false;
    return v[0] === fc0 && v[v.length - 1] <= fc1 + 1 && v[v.length - 1] >= fc1 - 1;
  }
  function fkpShape(d, limit) {
    var crun = d[511];
    if (!(crun >= 1 && crun <= 101)) return false;
    var v = u32s(d.subarray(0, 4 * (crun + 1)));
    for (var i = 1; i < v.length; i++) if (!(v[i - 1] < v[i])) return false;
    return v[v.length - 1] <= limit;
  }
  function clx(raw) {
    var i = 0;
    while (i < raw.length && raw[i] === 1) {
      if (i + 3 > raw.length) throw new RangeError("short");
      i += 3 + u16(raw, i + 1);
    }
    if (i >= raw.length || raw[i] !== 2) throw new WordError("piece table not found");
    if (i + 5 > raw.length) throw new RangeError("short");
    var lcb = u32(raw, i + 1), plc = raw.subarray(i + 5, i + 5 + lcb), n = Math.floor((lcb - 4) / 12);
    if (4 * (n + 1) > plc.length) throw new RangeError("short");
    var cps = u32s(plc.subarray(0, 4 * (n + 1))), out = [];
    for (var k = 0; k < n; k++) {
      var o = 4 * (n + 1) + 8 * k;
      if (o + 6 > plc.length) throw new RangeError("short");
      var fc = u32(plc, o + 2), comp = !!(fc & 0x40000000);
      fc = fc & 0x3FFFFFFF;
      out.push([cps[k], cps[k + 1], comp ? Math.floor(fc / 2) : fc, comp]);
    }
    return out;
  }

  BR.word = { Word: Word, WordError: WordError, MAGIC: MAGIC };
})();
