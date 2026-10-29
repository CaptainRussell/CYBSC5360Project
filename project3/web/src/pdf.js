// layout.py and pdf.py: positions of one file, and placing a PDF's blocks from its own map
// (header, cross-reference tables, object offsets, stream ends).
"use strict";
(function () {
  var B = BR.base, BS = 512, PlaceError = B.PlaceError, S = "[ \\t\\n\\r\\x0b\\x0c]";

  function Layout(n) { this.n = n; this.at = new Array(n).fill(null); this.how = new Array(n).fill(null); this.pos = new Map(); }
  Layout.prototype.put = function (p, block, how) {
    if (!(p >= 0 && p < this.n)) throw new PlaceError("position " + p + " is outside the file");
    if (this.at[p] !== null) {
      if (this.at[p] === block) return;
      throw new PlaceError("position " + p + " is already " + this.at[p].name + ", cannot also be " + block.name);
    }
    if (this.pos.has(block.name)) throw new PlaceError(block.name + " is already at position " + this.pos.get(block.name));
    this.at[p] = block; this.how[p] = how; this.pos.set(block.name, p);
  };
  Layout.prototype.data = function (lo, hi) {   // bytes lo..hi, or null if a block is unknown
    var parts = [];
    for (var p = Math.floor(lo / BS); p <= Math.floor((hi - 1) / BS); p++) {
      if (p >= this.n || this.at[p] === null) return null;
      parts.push(this.at[p].data);
    }
    var s = Math.floor(lo / BS) * BS;
    return B.concat(parts).slice(lo - s, hi - s);
  };
  Layout.prototype.gaps = function () {
    var out = [], p = 0;
    while (p < this.n) {
      if (this.at[p] === null) { var q = p; while (q < this.n && this.at[q] === null) q++; out.push([p, q]); p = q; } else p++;
    }
    return out;
  };
  BR.Layout = Layout;

  var XREF_LINE = /(\d{10}) (\d{5}) ([nf])(?:\r\n| \r| \n)/y;
  var OBJ = /(\d+) (\d+) obj/g;
  var EOF_TAIL = new RegExp("startxref" + S + "+(\\d+)" + S + "+%%EOF" + S + "*$");
  var STREAM_KW = /stream(\r\n|\n)/y;
  var XREF_HEAD = new RegExp("^xref" + S + "*(\\d+) (\\d+)" + S + "*?(\\r\\n|\\n|\\r)");

  function reEsc(s) { return s.replace(/[.*+?^${}()|[\]\\\/]/g, "\\$&"); }
  function intAfter(text, key) {
    var m = new RegExp(reEsc(key) + S + "*(-?\\d+)").exec(text);
    return m ? parseInt(m[1], 10) : null;
  }
  function xrefHeadOk(t, need) {
    var m = XREF_HEAD.exec(t);
    if (!m) return false;
    var i = m[0].length, left = parseInt(m[2], 10);
    while (i < need && left) {
      XREF_LINE.lastIndex = i;
      var mm = XREF_LINE.exec(t);
      if (!mm) return false;
      i = XREF_LINE.lastIndex; left--;
    }
    return i >= need || !left;
  }
  function bs(block) { if (block.s === undefined) block.s = B.bstr(block.data); return block.s; }

  function PDF(blocks, log) {
    this.blocks = blocks;
    this.log = log || function () {};
    this.free = new Map(); var self = this;
    blocks.forEach(function (b) { self.free.set(b.name, b); });
    this.objects = new Map();        // num -> [gen, offset], in insertion order
    this.headers = new Map();        // "num gen" -> [[block, in-block offset]]
    this.sec = null; this.streams = []; this.dicts = new Map();
    blocks.forEach(function (b) {
      var s = bs(b), m; OBJ.lastIndex = 0;
      while ((m = OBJ.exec(s))) {
        var key = parseInt(m[1], 10) + " " + parseInt(m[2], 10);
        if (!self.headers.has(key)) self.headers.set(key, []);
        self.headers.get(key).push([b, m.index]);
      }
    });
  }
  var P = PDF.prototype;
  P.place = function (p, block, how) { this.L.put(p, block, how); this.free.delete(block.name); };
  P.fits = function (block, p, off, text) {
    var s = off - p * BS, lo = Math.max(0, s), hi = Math.min(BS, s + text.length);
    if (lo >= hi) return true;
    for (var i = lo; i < hi; i++) if (block.data[i] !== text.charCodeAt(i - s)) return false;
    return true;
  };
  P.candidates = function (p, off, text) {
    var out = [], self = this;
    this.free.forEach(function (b) { if (self.fits(b, p, off, text)) out.push(b); });
    return out;
  };
  P.anchorText = function (offset, text, how) {
    var placed = 0;
    for (var p = Math.floor(offset / BS); p <= Math.floor((offset + text.length - 1) / BS); p++) {
      if (this.L.at[p] !== null) {
        if (!this.fits(this.L.at[p], p, offset, text)) throw new PlaceError("block at " + p + " does not hold the text at " + offset);
        continue;
      }
      var c = this.candidates(p, offset, text);
      if (c.length === 1) { this.place(p, c[0], how); placed++; }
      else if (c.length > 1 && c.every(function (x) { return B.eq(x.data, c[0].data); })) { this.place(p, c[0], how + " (identical copies)"); placed++; }
    }
    return placed;
  };

  P.findHeader = function () {
    var heads = this.blocks.filter(function (b) { return B.startsWith(b.data, "%PDF-"); });
    if (heads.length !== 1) throw new PlaceError("expected one block starting with %PDF-, found " + heads.length);
    var h = bs(heads[0]);
    var size = h.indexOf("/Linearized") >= 0 ? intAfter(h, "/L") : null;
    this.eof = null;
    if (size === null) {
      var ends = [], self = this;
      this.blocks.forEach(function (b) {
        var m = EOF_TAIL.exec(B.bstr(B.rstripZero(b.data)));
        if (m) ends.push([b, null, m, m.index + m[0].length]);
      });
      if (!ends.length) {
        this.blocks.forEach(function (x) {
          var t = B.bstr(B.rstripZero(x.data));
          if (!(t.length > 0 && t.length < 16)) return;
          self.blocks.forEach(function (y) {
            if (y !== x && bs(y).slice(-48).indexOf("startxref") >= 0) {
              var m = EOF_TAIL.exec(bs(y) + t);
              if (m) ends.push([x, y, m, m.index + m[0].length]);
            }
          });
        });
      }
      if (ends.length !== 1) throw new PlaceError("expected one block ending the PDF (startxref ... %%EOF), found " + ends.length);
      this.eof = ends[0]; this.size = null;
      this.L = new Layout(this.blocks.length + 1);
      this.log("header", heads[0].name, "not linearized; the table is at byte " + ends[0][2][1]);
    } else {
      this.size = size;
      this.L = new Layout(Math.ceil(size / BS));
      this.log("header", heads[0].name, "file is " + size + " bytes = " + this.L.n + " blocks");
    }
    this.place(0, heads[0], "starts with %PDF-");
  };

  P.placeEnd = function (tableEnd) {
    var last = this.eof[0], prev = this.eof[1], mEnd = this.eof[3];
    var b = prev || last, p = Math.floor(tableEnd / BS);
    if (!(bs(b).indexOf("trailer") === tableEnd % BS || this.L.at[p] !== null)) p++;
    if (this.L.at[p] !== null && this.L.at[p] !== b) p++;
    this.place(p, b, "ends the file (%%EOF)");
    var rel;
    if (prev !== null) { this.place(p + 1, last, "the last bytes of %%EOF"); p++; rel = mEnd - BS; }
    else rel = mEnd;
    var rest = bs(last).slice(rel), nl = /^[\r\n]*/.exec(rest)[0].length;
    this.size = p * BS + rel + nl;
    var n = Math.ceil(this.size / BS);
    for (var q = n; q < this.L.n; q++) if (this.L.at[q] !== null) throw new PlaceError("blocks were placed past the end of the file");
    this.L.n = n; this.L.at = this.L.at.slice(0, n); this.L.how = this.L.how.slice(0, n);
    this.log("size", "file is " + this.size + " bytes = " + n + " blocks");
  };

  P.readXref = function (offset) {
    this.anchorText(offset, "xref", "cross-reference table");
    var head = this.L.data(offset, offset + 64);
    if (head === null) {
      var p = Math.floor(offset / BS) + 1, cur = bs(this.L.at[p - 1]).slice(offset % BS), c = [];
      this.free.forEach(function (b) { if (xrefHeadOk(cur + bs(b).slice(0, 64), cur.length + 1)) c.push(b); });
      if (c.length === 1) this.place(p, c[0], "cross-reference table continues");
      head = this.L.data(offset, offset + 64);
    }
    var m = XREF_HEAD.exec(head ? B.bstr(head) : "");
    if (!m) throw new PlaceError("no cross-reference table at offset " + offset);
    var first = parseInt(m[1], 10), count = parseInt(m[2], 10), body = offset + m[0].length, end = body + 20 * count;
    for (var q = Math.floor(body / BS); q <= Math.floor((end - 1) / BS); q++) if (this.L.at[q] === null) this.placeXrefBlock(q, body, first, count);
    var raw = this.L.data(body, end);
    if (raw === null) throw new PlaceError("could not rebuild the cross-reference table at " + offset);
    var rs = B.bstr(raw);
    for (var i = 0; i < count; i++) {
      XREF_LINE.lastIndex = 0;
      var mm = XREF_LINE.exec(rs.slice(20 * i, 20 * i + 20));
      if (!mm) throw new PlaceError("bad cross-reference line");
      if (mm[3] === "n") this.objects.set(first + i, [parseInt(mm[2], 10), parseInt(mm[1], 10)]);   // (an existing key keeps its place, as in Python)
    }
    return end;
  };
  P.readTrailer = function (end) {
    var text = this.readKnown(end, 4096);
    if (text.slice(0, 16).indexOf("trailer") < 0) { this.anchorText(end, "trailer", "trailer after the table"); text = this.readKnown(end, 4096); }
    var k = text.indexOf("startxref");
    return k >= 0 ? text.slice(0, k) : text;
  };
  P.placeXrefBlock = function (p, body, first, count) {
    var best = null, bestScore = -1, tied = [], lo = p * BS, self = this;
    this.free.forEach(function (b) {
      var k0 = Math.max(0, Math.ceil((lo - body) / 20)), s = body + 20 * k0 - lo, score = 0, ok = true, d = bs(b);
      for (var k = k0; k < count; k++) {
        var i = s + 20 * (k - k0);
        if (i + 20 > BS) break;
        XREF_LINE.lastIndex = i;
        var mm = XREF_LINE.exec(d);
        if (!mm || XREF_LINE.lastIndex !== i + 20) { ok = false; break; }
        if (mm[3] === "n") {
          var num = first + k, gen = parseInt(mm[2], 10), off = parseInt(mm[1], 10);
          var hits = self.headers.get(num + " " + gen) || [];
          if (hits.some(function (h) { return off % BS === h[1]; })) score++;
          else if (!self.straddles(num, gen, off)) { ok = false; break; }
        }
      }
      if (ok && s > 0 && !/^[\d ]*[nf]?[ \r\n]*$/.test(d.slice(0, s))) ok = false;
      if (!ok) return;
      if (score > bestScore) { best = b; bestScore = score; tied = [b]; }
      else if (score === bestScore) tied.push(b);
    });
    if (best === null) throw new PlaceError("no block fits cross-reference position " + p);
    if (tied.length > 1 && !tied.every(function (t) { return B.eq(t.data, best.data); })) {
      if (bestScore === 0) throw new PlaceError("cannot tell which block is at cross-reference position " + p);
      throw new PlaceError("cross-reference position " + p + " is ambiguous");
    }
    this.place(p, best, "cross-reference lines" + (tied.length > 1 ? " (identical copies)" : ""));
  };
  P.straddles = function (num, gen, off) {
    var text = num + " " + gen + " obj", s = off % BS;
    if (s + text.length <= BS) return false;
    var want = text.slice(0, BS - s);
    return this.blocks.some(function (b) { return bs(b).slice(s) === want; });
  };
  P.objectsByOffset = function () {
    var arr = []; this.objects.forEach(function (v, k) { arr.push([k, v[0], v[1]]); });
    return arr.sort(function (a, b) { return a[2] - b[2]; });
  };
  P.placeObjects = function () {
    var self = this;
    this.objectsByOffset().forEach(function (o) { self.anchorText(o[2], o[0] + " " + o[1] + " obj", "object " + o[0] + " starts here"); });
  };
  P.parseObjects = function () {
    var self = this;
    this.dicts = new Map();
    this.objectsByOffset().forEach(function (o) {
      var num = o[0], gen = o[1], off = o[2], head = num + " " + gen + " obj";
      var text = self.readKnown(off, 4096);
      if (text.slice(0, head.length) !== head) return;
      var body = text.slice(head.length), k = BR.pdflex.objectOk(body);
      if (k < 0) {
        var q = Math.floor((off + text.length) / BS);
        if (q < self.L.n && self.L.at[q] === null) {
          var c = [];
          self.free.forEach(function (b) { if (BR.pdflex.objectOk(body + bs(b)) >= 0) c.push(b); });
          if (c.length === 1) { self.place(q, c[0], "completes object " + num); body += bs(c[0]); k = BR.pdflex.objectOk(body); }
        }
        if (k < 0) { self.log("object", num, "could not be read"); return; }
      }
      var d = body.slice(0, k);
      self.dicts.set(num, d);
      STREAM_KW.lastIndex = k;
      var sm = STREAM_KW.exec(body);
      if (!sm) return;
      var ref = new RegExp("/Length" + S + "+(\\d+)" + S + "+(\\d+)" + S + "+R").exec(d);
      var length = ref ? self.lengthObject(parseInt(ref[1], 10)) : intAfter(d, "/Length");
      if (length === null) throw new PlaceError("object " + num + ": stream length could not be read");
      var flt = new RegExp("/Filter" + S + "*/(\\w+)").exec(d);
      self.streams.push({ num: num, gen: gen, start: off + head.length + STREAM_KW.lastIndex, length: length,
        filter: flt ? flt[1] : null, dict: d });
    });
  };
  P.lengthObject = function (num) {
    if (!this.objects.has(num)) return null;
    var m = new RegExp("^\\d+ \\d+ obj" + S + "*(\\d+)" + S + "*endobj").exec(this.readKnown(this.objects.get(num)[1], 64));
    return m ? parseInt(m[1], 10) : null;
  };
  P.readKnown = function (off, n) {   // -> binary string
    var parts = [], len = 0, p = Math.floor(off / BS);
    while (len < n && p < this.L.n && this.L.at[p] !== null) { parts.push(bs(this.L.at[p])); len += BS; p++; }
    return parts.join("").slice(off % BS, off % BS + n);
  };
  P.placeStreamEnds = function () {
    var self = this;
    this.streams.forEach(function (s) {
      var e = s.start + s.length, kws = ["\r\nendstream", "\nendstream", "\rendstream", "endstream"], p = Math.floor(e / BS);
      for (var i = 0; i < kws.length; i++) {
        if (self.candidates(p, e, kws[i]).length || (self.L.at[p] && self.fits(self.L.at[p], p, e, kws[i]))) {
          self.anchorText(e, kws[i], "end of stream " + s.num);
          break;
        }
      }
    });
  };
  P.findSecurity = function (trailer) {
    var m = new RegExp("/Encrypt" + S + "+(\\d+)" + S + "+(\\d+)" + S + "+R").exec(trailer);
    if (!m) return;
    var num = parseInt(m[1], 10), idm = new RegExp("/ID" + S + "*\\[" + S + "*<([0-9A-Fa-f]+)>").exec(trailer);
    if (!this.objects.has(num)) throw new PlaceError("encryption dictionary " + num + " is not in the cross-reference table");
    var d = this.readKnown(this.objects.get(num)[1], 1024), du = B.fromB(d);
    var O = BR.pdfcrypt.literalString(du, d.indexOf("/O(") + 2)[0], U = BR.pdfcrypt.literalString(du, d.indexOf("/U(") + 2)[0];
    var R = intAfter(d, "/R") || 2, length = intAfter(d, "/Length") || 40;
    this.sec = new BR.pdfcrypt.Security(O, U, intAfter(d, "/P"), B.unhex(idm[1]), R, length);
    if (!this.sec.ok) throw new PlaceError("the file needs a password; its streams cannot be checked");
    this.log("encryption", "RC4 " + (8 * this.sec.n) + "-bit, empty user password works");
  };

  P.anchor = function () {
    this.findHeader();
    var offsets;
    if (this.eof) offsets = [parseInt(this.eof[2][1], 10)];
    else { var k = bs(this.L.at[0]).indexOf("xref"); offsets = k >= 0 ? [k] : []; }
    var trailers = [], seen = new Set();
    while (offsets.length) {
      var off = offsets.shift();
      if (seen.has(off)) continue;
      seen.add(off);
      var end = this.readXref(off);
      if (this.eof && seen.size === 1) this.placeEnd(end);
      this.placeObjects();
      var t = this.readTrailer(end);
      trailers.push(t);
      var prev = intAfter(t, "/Prev");
      if (prev !== null) offsets.push(prev);
    }
    this.trailer = trailers.join("");
    this.log("objects", this.objects.size + " objects have a written offset");
    this.placeObjects();
    this.findSecurity(this.trailer);
    this.parseObjects();
    this.placeStreamEnds();
    return this.L;
  };

  BR.pdf = { PDF: PDF, Layout: Layout, intAfter: intAfter, bs: bs };
})();
