// jpegfile.py: putting a JPEG picture's blocks back in order (beam search with back-up,
// a lenient fallback, then a second pass over trusted runs judged on the whole picture).
"use strict";
(function () {
  var B = BR.base, S = BR.streams;
  function JPEGFileError(msg) { this.message = msg; this.name = "JPEGFileError"; }
  JPEGFileError.prototype = Object.create(B.PlaceError.prototype);
  function ident(p, d) { return d; }

  function Run(parts) {
    this.parts = parts;
    this.name = parts.length === 1 ? parts[0].name : parts[0].name + "+" + (parts.length - 1);
    this.data = parts.length === 1 ? parts[0].data : B.concat(parts.map(function (b) { return b.data; }));
  }

  function consolidate(flat, incs, rows, minLen) {
    minLen = minLen || 6;
    var srt = incs.slice().sort(function (a, b) { return a - b; }), med = srt[Math.floor(srt.length / 2)] || 1e-9;
    var runs = [], cur = [flat[0]];
    for (var i = 1; i < flat.length; i++) {
      if (incs[i] <= 1.5 * med && rows[i] >= 3) cur.push(flat[i]);
      else { runs.push(cur); cur = [flat[i]]; }
    }
    runs.push(cur);
    var out = [];
    runs.forEach(function (r) { if (r.length >= minLen) out.push(new Run(r)); else r.forEach(function (b) { out.push(new Run([b])); }); });
    return out;
  }
  function afterLastRow(kind, head, order) {
    var st = kind.begin(head.data);
    for (var i = 0; i < order.length; i++) {
      if (st.j !== null && st.j.done) return order.length - i;
      st = kind.extend(st, order[i].data);
      if (st === null) return order.length - i;
      S.JPEGStream.overlay(st);
    }
    return 0;
  }
  function totalCost(kind, head, tail, order) {
    var st = kind.begin(head.data);
    for (var i = 0; i < order.length; i++) {
      st = kind.extend(st, order[i].data);
      if (st === null) return null;
      S.JPEGStream.overlay(st);
    }
    if (!kind.finish(st, tail.data)) return null;
    return st.cnt ? st.tot / st.cnt : null;
  }
  function evaluate(kind, head, tail, middle) {
    var st = kind.begin(head.data), incs = [], rows = [];
    for (var i = 0; i < middle.length; i++) {
      var x = kind.extend(st, middle[i].data);
      if (x === null) return null;
      S.JPEGStream.overlay(x);
      var dc = x.cnt - st.cnt;
      incs.push(dc ? (x.tot - st.tot) / dc : 0.0);
      rows.push(st.j !== null ? Math.floor(st.j.mcu / st.dec.h.mcux) : -1);
      st = x;
    }
    if (!kind.finish(st, tail.data)) return null;
    return [kind.cost(st), incs, rows];
  }

  function lds(kind, head, tail, items, incumbent, log, tries, progress) {
    var bestCost = incumbent ? totalCost(kind, head, tail, incumbent) : null, best = incumbent;
    function ranked(st, avail) {
      var out = [];
      avail.forEach(function (it, k) {
        var x = kind.extend(st, it.parts[0].data);
        if (x === null) return;
        var dc = x.cnt - st.cnt;
        out.push([dc ? (x.tot - st.tot) / dc : 0.0, k, it, x]);
      });
      out.sort(function (a, b) { return a[0] - b[0] || a[1] - b[1]; });
      return out;
    }
    function place(it, x) {
      S.JPEGStream.overlay(x);
      for (var i = 1; i < it.parts.length; i++) {
        x = kind.extend(x, it.parts[i].data);
        if (x === null) return null;
        S.JPEGStream.overlay(x);
      }
      return x;
    }
    function greedy(prefix, forced) {
      var st = kind.begin(head.data), avail = items.slice(), path = [], margins = [];
      var pre = forced ? prefix.concat([forced]) : prefix;
      for (var i = 0; i < pre.length; i++) {
        var x = kind.extend(st, pre[i].parts[0].data);
        if (x === null) return null;
        st = place(pre[i], x);
        if (st === null) return null;
        avail.splice(avail.indexOf(pre[i]), 1);
        path.push(pre[i]); margins.push(null);
      }
      while (avail.length) {
        var r = ranked(st, avail), st2 = null;
        while (r.length) { st2 = place(r[0][2], r[0][3]); if (st2 !== null) break; r.shift(); }
        if (!r.length) return [path, margins, null];
        margins.push([r.length > 1 ? r[1][0] - r[0][0] : 1e9, r.slice(1, 3).map(function (t) { return t[2]; })]);
        path.push(r[0][2]);
        avail.splice(avail.indexOf(r[0][2]), 1);
        st = st2;
        if (progress) progress(path.length, items.length);
      }
      if (!kind.finish(st, tail.data)) return [path, margins, null];
      return [path, margins, st.tot / st.cnt];
    }
    function better(r, than) {
      if (r === null) return false;
      if (than === null || than[2] === null) return r[2] !== null || (than !== null && r[0].length > than[0].length);
      return r[2] !== null && r[2] < than[2] - 1e-9;
    }
    function flat(path) { var out = []; path.forEach(function (it) { out = out.concat(it.parts); }); return out; }
    var base = greedy([], null);
    if (base === null) return best;
    var tried = 0;
    while (tried < tries) {
      var path = base[0], margins = base[1], cost = base[2];
      if (cost !== null && (bestCost === null || cost < bestCost - 1e-9)) {
        bestCost = cost; best = flat(path);
        log("picture", "order found: seam cost " + cost.toFixed(3));
      }
      var steps = [];
      margins.forEach(function (m, i) { if (m) steps.push([m[0], i]); });
      steps.sort(function (a, b) { return a[0] - b[0] || a[1] - b[1]; });
      var improved = false;
      for (var s = 0; s < steps.length; s++) {
        var i = steps[s][1], alts = margins[i][1];
        for (var a = 0; a < alts.length; a++) {
          tried++;
          var r = greedy(path.slice(0, i), alts[a]);
          if (better(r, base)) { base = r; improved = true; break; }
          if (tried >= tries) break;
        }
        if (improved || tried >= tries) break;
      }
      if (!improved) break;
    }
    if (base[2] !== null && (bestCost === null || base[2] < bestCost - 1e-9)) { bestCost = base[2]; best = flat(base[0]); }
    log("picture", "second pass: seam cost " + (bestCost !== null ? bestCost.toFixed(3) : "none") + " after " + tried + " second thoughts");
    return best;
  }

  // jpegfile.BEAMS and THOROUGH: how many partial orders the picture search keeps
  var BEAMS = [8, 24], THOROUGH = [64];

  function rebuild(pool, log, beams, progress) {
    log = log || function () {};
    beams = beams || BEAMS;
    var heads = pool.filter(function (b) { return b.data[0] === 0xFF && b.data[1] === 0xD8 && b.data[2] === 0xFF; });
    if (heads.length !== 1) throw new JPEGFileError("expected one block starting a JPEG, found " + heads.length);
    var head = heads[0], rest = pool.filter(function (b) { return b !== head; });
    var EOI = B.fromB("\xff\xd9"), tails = rest.filter(function (b) { return B.find(b.data, EOI) >= 0; });
    if (tails.length !== 1) throw new JPEGFileError("expected one block holding the end-of-image marker, found " + tails.length);
    var tail = tails[0], middle = rest.filter(function (b) { return b !== tail; }), n = middle.length + 2;
    var kind = new S.JPEGStream();
    kind.mayEnd = tail.data[0] === 0xFF && tail.data[1] === 0xD9;
    var st = kind.begin(head.data);
    if (st === null) throw new JPEGFileError("the first block does not start a valid JPEG header");
    if (st.dec !== null) {
      var h = st.dec.h;
      log("picture", h.width + "x" + h.height + ", " + h.scan.length + " components, " + h.mcus + " coding units" + (h.restart ? ", restart every " + h.restart : ""));
    } else log("picture", "the header carries on past the first block");
    var err = null, chosen = null;
    kind.strict = false;
    for (var bi = 0; bi < beams.length; bi++) {
      try { chosen = S.search(kind, head.data, tail.data, middle.map(function (_, k) { return k; }), middle, ident, beams[bi], "picture", null, progress && function (k, nn, path) { progress(k, middle.length, path); }); break; }
      catch (e2) { if (!(e2 instanceof S.StreamError)) throw e2; err = e2; log("picture", "widening the search after:", e2.message); }
    }
    var ev = chosen ? evaluate(kind, head, tail, chosen) : null, items;
    if (ev) {
      log("picture", "first pass: seam cost " + totalCost(kind, head, tail, chosen).toFixed(3));
      items = consolidate(chosen, ev[1], ev[2]);
    } else items = middle.map(function (b) { return new Run([b]); });
    var best = lds(kind, head, tail, items, chosen, log, Math.max(4, Math.min(40, Math.floor(3000 / Math.max(1, items.length)))));
    var L = new BR.Layout(n);
    L.put(0, head, "starts with the JPEG signature");
    if (best === null && chosen === null) {   // (see jpegfile.py: keep the picture's set, unconfirmed)
      var partial = (err && err.partial) ? err.partial.slice() : [], names = new Set(partial.map(function (b) { return b.name; }));
      var rest = middle.filter(function (b) { return !names.has(b.name); });
      log("picture", "no order reaches the last row; " + partial.length + " blocks kept in the best partial order, " + rest.length + " unordered");
      partial.concat(rest).forEach(function (b, i) {
        L.put(i + 1, b, i < partial.length ? "not confirmed: best partial order found" : "not confirmed: in the picture's set, position unknown");
      });
      L.exact = false;
      L.put(n - 1, tail, "holds the end-of-image marker");
      return L;
    }
    chosen = best !== null ? best : chosen;
    var over = afterLastRow(kind, head, chosen);
    chosen.forEach(function (b, i) {
      L.put(i + 1, b, i < chosen.length - over ? "picture rows join up" : "not confirmed: comes after the picture's last row in the best order found");
    });
    L.exact = over === 0;
    L.put(n - 1, tail, "holds the end-of-image marker");
    return L;
  }

  BR.jpegfile = { rebuild: rebuild, JPEGFileError: JPEGFileError, BEAMS: BEAMS, THOROUGH: THOROUGH };
})();
