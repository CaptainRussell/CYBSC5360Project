// streams.py: ordering the blocks inside one PDF stream (beam search over decrypted
// candidates, each stream kind with its own test), plus the JPEG kind used for pictures.
"use strict";
(function () {
  var B = BR.base, BS = 512, TIE_LIMIT = 300, PlaceError = B.PlaceError;
  var Inflater = BR.inflate.Inflater, InflateError = BR.inflate.InflateError;

  function StreamError(msg) { this.message = msg; this.name = "StreamError"; this.partial = null; }
  StreamError.prototype = Object.create(PlaceError.prototype);

  function cmpCost(a, b) {     // numbers, or arrays compared like Python tuples
    if (typeof a === "number") return a < b ? -1 : a > b ? 1 : 0;
    for (var i = 0; i < a.length; i++) { if (a[i] < b[i]) return -1; if (a[i] > b[i]) return 1; }
    return 0;
  }
  function nearExact(best, c) { return cmpCost(c, best) === 0; }

  // ---- kinds -----------------------------------------------------------------------
  function FlateText() { this.name = "compressed PDF text"; }
  FlateText.prototype.near = nearExact;
  FlateText.prototype.begin = function (head) {
    var z = new Inflater(), o = z.feedCapture(head);
    var r = BR.pdflex.check(B.bstr(o), "");
    return { z: z, carry: r[2], bad: r[0], tot: r[1] };
  };
  FlateText.prototype.extend = function (st, piece) {
    var zz = st.z.copy(), o;
    try { o = zz.feedCapture(piece); } catch (e) { if (e instanceof InflateError) return null; throw e; }
    if (zz.eof) return null;
    var r = BR.pdflex.check(B.bstr(o), st.carry);
    return { z: zz, carry: r[2], bad: st.bad + r[0], tot: st.tot + r[1] };
  };
  FlateText.prototype.cost = function (st) { return (st.bad + 1) / (st.tot + 50); };
  FlateText.prototype.finish = function (st, tail) {
    var zz = st.z.copy();
    try { zz.feed(tail); } catch (e) { if (e instanceof InflateError) return false; throw e; }
    return zz.eof && zz.inp.length - zz.ip === 0;
  };

  function FlateBinary(checker, name) { this.checker = checker || null; this.name = name || "compressed binary data"; }
  FlateBinary.prototype.score = function (inf) {
    var r = this.checker ? this.checker(inf.base === 0 ? inf.output() : new Uint8Array(0)) : [0, 0, 0];
    return { inf: inf, q: (r[0] + 1) / (r[1] + 50) / (1 + r[2]) };
  };
  FlateBinary.prototype.begin = function (head) { return this.score(new Inflater().feed(head)); };
  FlateBinary.prototype.extend = function (st, piece) {
    var inf = st.inf.copy();
    try { inf.feed(piece); } catch (e) { if (e instanceof InflateError) return null; throw e; }
    if (inf.eof) return null;
    return this.score(inf);
  };
  FlateBinary.prototype.cost = function (st) { return [B.pyRound(st.q, 4), (st.inf.slips + 1) / (st.inf.tokens + 20)]; };
  FlateBinary.prototype.near = function (best, c) { return c[0] <= best[0] * 1.5 + 0.002; };
  FlateBinary.prototype.finish = function (st, tail) {
    var inf = st.inf.copy();
    try { inf.feed(tail); } catch (e) { if (e instanceof InflateError) return false; throw e; }
    return inf.eof;
  };

  function PlainText() { this.name = "XML text"; }
  PlainText.prototype.near = nearExact;
  PlainText.bad = function (piece) {
    var err = B.utf8Error(piece);
    if (err === null) {
      var c = 0;
      for (var i = 0; i < piece.length; i++) { var x = piece[i]; if (x < 32 && x !== 9 && x !== 10 && x !== 13) c++; }
      return c;
    }
    if (err.start >= piece.length - 3 && err.reason === "unexpected end of data") return 0;
    return piece.length;
  };
  PlainText.prototype.begin = function (head) { return [PlainText.bad(head), head.length]; };
  PlainText.prototype.extend = function (st, piece) {
    var b = PlainText.bad(piece);
    if (b > Math.floor(piece.length / 8)) return null;
    return [st[0] + b, st[1] + piece.length];
  };
  PlainText.prototype.cost = function (st) { return (st[0] + 1) / (st[1] + 50); };
  PlainText.prototype.finish = function (st, tail) { return PlainText.bad(tail) === 0; };

  // ---- JPEG pictures ------------------------------------------------------------------
  function key(ci, idx) { return ci * 16777216 + idx; }
  function JPEGStream() { this.name = "JPEG picture"; this.mayEnd = false; this.strict = true; }
  JPEGStream.prototype.near = nearExact;
  JPEGStream.prototype.begin = function (head) {
    return this.advance({ raw: new Uint8Array(0), dec: null, j: null, tot: 0.0, cnt: 0, newE: [], parent: null, ov: new Map() }, head);
  };
  JPEGStream.prototype.advance = function (st, piece) {
    if (st.j === null) {
      var raw = B.concat([st.raw, piece]), hc = headerCheck(raw);
      if (!hc[0]) return null;
      st = this.thumbnail(st, raw);
      if (st === null) return null;
      if (hc[1] === null) return Object.assign({}, st, { raw: raw });
      var dec;
      try { dec = new BR.jpeg.Decoder(new BR.jpeg.Header(raw.subarray(0, hc[1]))); }
      catch (e) { if (e instanceof BR.jpeg.JPEGError || e instanceof RangeError || e instanceof TypeError) return null; throw e; }
      st = Object.assign({}, st, { raw: new Uint8Array(0), dec: dec, j: new BR.jpeg.State(dec.h.scan.length) });
      piece = raw.subarray(hc[1]);
    }
    var dec2 = st.dec, js = st.j.copy(), info = dec2.run(js, piece, false);
    if (info.error || info.eoi) return null;
    if (js.done && (info.rest > 4 || !this.mayEnd) && this.strict) return null;
    var jm = dec2.junction(info.edges, JPEGStream.overlay(st)), m = jm[0], c = jm[1];
    var steps = st.steps || 0, ssum = st.ssum || 0.0;
    if (c) { steps++; ssum += m; }
    return { raw: new Uint8Array(0), dec: dec2, j: js, tot: st.tot + (m || 0) * c, cnt: st.cnt + c,
      newE: info.edges, parent: st, steps: steps, ssum: ssum };
  };
  JPEGStream.prototype.thumbnail = function (st, raw) {
    var region = thumbnailRegion(raw);
    if (region === null) return st;
    var a = region[0], b = region[1], fed = st.tfed || 0;
    if (raw.length <= a + fed || fed >= b - a) return st;
    var nw = raw.subarray(a + fed, Math.min(raw.length, b)), kind = new JPEGStream();
    kind.mayEnd = true;
    var th = st.thumb || null;
    if (th === null) {
      th = raw.length < b ? kind.begin(nw) : null;
      if (raw.length >= b) { var th0 = kind.begin(new Uint8Array(0)); th = th0 !== null && kind.finish(th0, nw) ? th0 : null; }
    } else if (raw.length >= b) th = kind.finish(th, nw) ? th : null;
    else th = kind.extend(th, nw);
    if (th === null) return null;
    return Object.assign({}, st, { thumb: th, tfed: fed + nw.length, tot: st.tot + th.tot - (st.ttot || 0),
      cnt: st.cnt + th.cnt - (st.tcnt || 0), ttot: th.tot, tcnt: th.cnt });
  };
  JPEGStream.overlay = function (st) {
    if (!st.ov) {
      var ov = new Map(st.parent.ov);
      for (var i = 0; i < st.newE.length; i++) ov.set(key(st.newE[i][0], st.newE[i][1]), st.newE[i][2]);
      st.ov = ov; st.parent = null;
    }
    return st.ov;
  };
  JPEGStream.prototype.extend = function (st, piece) {
    if (st.j !== null && st.j.done) {
      if (this.strict) return null;
      return Object.assign({}, st, { steps: (st.steps || 0) + 1, ssum: (st.ssum || 0.0) + 50.0, over: (st.over || 0) + 1, newE: [], parent: st });
    }
    if (st.j !== null && BR.features.jpegScanLike(piece) === "no") return null;
    return this.advance(st, piece);
  };
  JPEGStream.prototype.cost = function (st) { return (st.cnt ? st.tot / st.cnt : 0.0) + 50.0 * (st.over || 0); };
  JPEGStream.prototype.finish = function (st, tail) {
    if (st.j === null) return false;
    if (st.j.done && !this.strict) return true;
    var js = st.j.copy(), info = st.dec.run(js, tail, true);
    var t = B.rstripZero(tail), endsEoi = t.length >= 2 && t[t.length - 2] === 0xFF && t[t.length - 1] === 0xD9;
    return !info.error && js.done && (info.eoi || endsEoi);
  };

  var JPEG_MARKERS = {};
  for (var mk = 0xE0; mk < 0xF0; mk++) JPEG_MARKERS[mk] = true;
  [0xDB, 0xC4, 0xC0, 0xC1, 0xC2, 0xDD, 0xDA, 0xFE].forEach(function (x) { JPEG_MARKERS[x] = true; });

  function headerCheck(d) {   // -> [still possible, index after SOS or null]
    if (d.length >= 2 && !(d[0] === 0xFF && d[1] === 0xD8)) return [false, null];
    var i = 2;
    while (i + 4 <= d.length) {
      if (d[i] !== 0xFF || !JPEG_MARKERS[d[i + 1]]) return [false, null];
      var m = d[i + 1], ln = B.u16be(d, i + 2);
      if (ln < 2) return [false, null];
      var seg = d.subarray(i + 4, i + 2 + ln);
      if (!segmentOk(m, seg, ln - 2)) return [false, null];
      if (seg.length < ln - 2) return [true, null];
      i += 2 + ln;
      if (m === 0xDA) return [true, i];
    }
    return [true, null];
  }
  var PS = B.fromB("Photoshop 3.0\0"), BIM = B.fromB("8BIM");
  function thumbnailRegion(d) {
    var i = 2;
    while (i + 4 <= d.length && d[i] === 0xFF) {
      var m = d[i + 1], ln = B.u16be(d, i + 2);
      if (m === 0xED && B.eq(d.subarray(i + 4, i + 18), PS)) {
        var j = i + 18, end = i + 2 + ln;
        while (j + 12 <= Math.min(d.length, end) && B.startsWith(d, BIM, j)) {
          var rid = B.u16be(d, j + 4), nl = d[j + 6], k = j + 7 + nl + ((1 + nl) % 2);
          if (k + 4 > d.length) return null;
          var size = B.u32be(d, k);
          if (rid === 1033 || rid === 1036) return [k + 4 + 28, k + 4 + size];
          j = k + 4 + size + (size % 2);
        }
        return null;
      }
      if (m === 0xDA) return null;
      i += 2 + ln;
    }
    return null;
  }
  function segmentOk(m, seg, full) {
    var j;
    if (m === 0xDB) {
      j = 0;
      while (j < seg.length) { if ((seg[j] >> 4) > 1 || (seg[j] & 15) > 3) return false; j += 1 + ((seg[j] >> 4) ? 128 : 64); }
      return j === full || seg.length < full;
    }
    if (m === 0xC4) {
      j = 0;
      while (j + 17 <= seg.length) {
        if ((seg[j] >> 4) > 1 || (seg[j] & 15) > 3) return false;
        var n = 0; for (var q = j + 1; q < j + 17; q++) n += seg[q];
        if (n > 256) return false;
        j += 17 + n;
      }
      return j === full || seg.length < full;
    }
    if (m === 0xC0 || m === 0xC1 || m === 0xC2) {
      if (seg.length >= 6 && (seg[0] !== 8 || [1, 3, 4].indexOf(seg[5]) < 0 || full !== 6 + 3 * seg[5])) return false;
      return true;
    }
    if (m === 0xDA) return seg.length ? (seg[0] >= 1 && seg[0] <= 4 && full === 4 + 2 * seg[0]) : true;
    if (m === 0xED) return irbOk(seg, full);
    return true;
  }
  function irbOk(seg, full) {
    var L = PS.length;
    var prefixOfSig = B.eq(seg.subarray(0, Math.min(L, seg.length)), PS.subarray(0, Math.min(L, seg.length)));
    if (!prefixOfSig && !B.startsWith(seg, PS)) return true;
    var j = L;
    while (j < seg.length) {
      var avail = Math.min(4, seg.length - j);
      if (!B.eq(seg.subarray(j, j + avail), BIM.subarray(0, avail))) return false;
      if (j + 7 > seg.length) return true;
      var nl = seg[j + 6], k = j + 6 + 1 + nl + ((1 + nl) % 2);
      if (k + 4 > seg.length) return true;
      var size = B.u32be(seg, k);
      j = k + 4 + size + (size % 2);
      if (j > full) return false;
    }
    return true;
  }

  function kindFor(pdfobj, s) {
    var d = s.dict, flt = s.filter;
    if (flt === "DCTDecode") return new JPEGStream();
    if (flt === null) return (d.indexOf("/Metadata") >= 0 || d.indexOf("XML") >= 0) ? new PlainText() : null;
    if (flt !== "FlateDecode" || (d.indexOf("/DecodeParms") >= 0 && d.indexOf("/Type/XRef") < 0)) return null;
    var ref = new RegExp(s.num + "[ \\t\\n\\r\\x0b\\x0c]+" + s.gen + "[ \\t\\n\\r\\x0b\\x0c]+R"), found = null;
    pdfobj.dicts.forEach(function (od) {
      if (found) return;
      var m = ref.exec(od);
      if (!m) return;
      var before = od.slice(Math.max(0, m.index - 12), m.index);
      if (before.indexOf("/FontFile2") >= 0) found = new FlateBinary(BR.binfmt.truetype, "TrueType font");
      else if (before.indexOf("ICCBased") >= 0) found = new FlateBinary(BR.binfmt.icc, "colour profile");
      else if (before.indexOf("/FontFile") >= 0) found = new FlateBinary(null, "font");
      else if (before.indexOf("/Contents") >= 0 || before.indexOf("/Extends") >= 0) found = new FlateText();
    });
    if (found) return found;
    if (d.indexOf("/Type/ObjStm") >= 0) return new FlateText();
    if (d.indexOf("/Subtype/Image") >= 0 || d.indexOf("/Type/XRef") >= 0 || d.indexOf("/S ") >= 0) return new FlateBinary();
    return new FlateText();
  }

  function poolFor(pdfobj, kind) {
    var free = Array.from(pdfobj.free.values()), F = BR.features;
    if (pdfobj.sec !== null) return free.filter(function (b) { return F.randomLike(b.data) && F.jpegScanLike(b.data) !== "yes"; });
    if (kind instanceof FlateText || kind instanceof FlateBinary) return free.filter(function (b) { return F.randomLike(b.data); });
    return free;
  }

  // ids shared by blocks with identical bytes (Python dedupes by the bytes themselves)
  var contentIds = new WeakMap(), byContent = new Map();
  function cid(b) {
    var v = contentIds.get(b);
    if (v === undefined) {
      var k = BR.pdf.bs(b);
      v = byContent.get(k);
      if (v === undefined) { v = byContent.size; byContent.set(k, v); }
      contentIds.set(b, v);
    }
    return v;
  }

  // chosen paths are linked lists {b, prev, n} so extending one is cheap
  function pathArray(ch) { var out = []; while (ch) { out.push(ch.b); ch = ch.prev; } return out.reverse(); }

  function search(kind, head, tail, todo, pool, piece, beam, num, start, progress) {
    var paths;
    if (!start) {
      var st0 = kind.begin(head);
      if (st0 === null) throw new StreamError("stream " + num + ": its known start does not read correctly");
      paths = [[st0, null]];
    } else paths = [[start[0], start[1] || null]];
    for (var t = 0; t < todo.length; t++) {
      var p = todo[t], pieces = new Map();
      pool.forEach(function (b) { pieces.set(b.name, piece(p, b.data)); });
      var nxt = [];
      for (var a = 0; a < paths.length; a++) {
        var st = paths[a][0], chosen = paths[a][1], used = new Set();
        for (var c = chosen; c; c = c.prev) used.add(c.b.name);
        for (var q = 0; q < pool.length; q++) {
          var b = pool[q];
          if (used.has(b.name)) continue;
          var st2 = kind.extend(st, pieces.get(b.name));
          if (st2 !== null) nxt.push([kind.cost(st2), st2, { b: b, prev: chosen }]);
        }
      }
      if (!nxt.length) {
        var e = new StreamError("stream " + num + ": no block continues it at position " + p);
        e.partial = pathArray(paths[0][1]);
        throw e;
      }
      nxt.sort(function (x, y) { return cmpCost(x[0], y[0]); });
      var best = nxt[0][0], seen = new Set();
      paths = [];
      for (var r = 0; r < nxt.length; r++) {
        var ch = nxt[r][2], keyParts = [], cc = ch;
        for (var z = 0; z < 3 && cc; z++, cc = cc.prev) keyParts.push(cid(cc.b));
        var k = keyParts.join(",");
        if (seen.has(k)) continue;
        if (paths.length >= beam && (!kind.near(best, nxt[r][0]) || paths.length >= TIE_LIMIT)) break;
        seen.add(k);
        paths.push([nxt[r][1], ch]);
      }
      if (progress) progress(t + 1, todo.length, pathArray(paths[0][1]));
    }
    for (var f = 0; f < paths.length; f++) if (kind.finish(paths[f][0], tail)) return pathArray(paths[f][1]);
    var e2 = new StreamError("stream " + num + ": no ordering closes the stream correctly");
    e2.partial = pathArray(paths[0][1]);
    throw e2;
  }

  function order(pdfobj, s, beams, log, progress) {
    beams = beams || [6, 40, 300];
    var kind = kindFor(pdfobj, s), L = pdfobj.L, start = s.start, end = s.start + s.length;
    var first = Math.floor(start / BS), last = Math.floor((end - 1) / BS), todo = [];
    for (var p = first; p <= last; p++) if (L.at[p] === null) todo.push(p);
    if (!todo.length) return [kind ? kind.name : "?", []];
    if (kind === null) throw new StreamError("stream " + s.num + ": no way to check this kind of stream");
    for (var i = 1; i < todo.length; i++) if (todo[i] !== todo[0] + i) throw new StreamError("stream " + s.num + ": its first and last blocks must be placed first");
    if (L.at[first] === null || L.at[last] === null) throw new StreamError("stream " + s.num + ": its first and last blocks must be placed first");
    var ks = pdfobj.sec ? pdfobj.sec.keystream(s.num, s.gen, s.length) : new Uint8Array(s.length);
    function piece(p, data) {
      var lo = Math.max(start, p * BS), hi = Math.min(end, (p + 1) * BS);
      return B.xor(data.subarray(lo - p * BS, hi - p * BS), ks.subarray(lo - start, hi - start));
    }
    var hp = [], tp = [];
    for (p = first; p < todo[0]; p++) hp.push(piece(p, L.at[p].data));
    for (p = todo[todo.length - 1] + 1; p <= last; p++) tp.push(piece(p, L.at[p].data));
    var head = B.concat(hp), tail = B.concat(tp), pool = poolFor(pdfobj, kind);
    if (kind instanceof JPEGStream) kind.mayEnd = tail.length >= 2 && tail[0] === 0xFF && tail[1] === 0xD9;
    var err = null;
    for (var bi = 0; bi < beams.length; bi++) {
      try {
        var got = search(kind, head, tail, todo, pool, piece, beams[bi], s.num, null, progress);
        return [kind.name, todo.map(function (q, k) { return [q, got[k]]; })];
      } catch (e) {
        if (!(e instanceof StreamError)) throw e;
        err = e;
        if (log) log("stream", s.num, "widening the search after:", e.message);
      }
    }
    throw err;
  }

  BR.streams = { StreamError: StreamError, FlateText: FlateText, FlateBinary: FlateBinary, PlainText: PlainText,
    JPEGStream: JPEGStream, headerCheck: headerCheck, thumbnailRegion: thumbnailRegion, kindFor: kindFor,
    poolFor: poolFor, search: search, order: order, cmpCost: cmpCost, pathArray: pathArray };
})();
