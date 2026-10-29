// blocks.py, recover.py and report.data(): load a block set, rebuild every file, and the
// data the report page draws itself from.
"use strict";
(function () {
  var B = BR.base, BS = 512;

  // ---- SHA-256 (from the term project's browser edition) ----------------------------
  var K256 = new Uint32Array([0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01,
    0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa,
    0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138,
    0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624,
    0xf40e3585, 0x106aa070, 0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f,
    0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2]);
  function sha256(msg) {
    var h = new Uint32Array([0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19]);
    var n = msg.length, total = Math.ceil((n + 9) / 64) * 64, b = new Uint8Array(total), w = new Uint32Array(64);
    b.set(msg); b[n] = 0x80;
    var bits = n * 8, hi = Math.floor(bits / 4294967296), lo = bits >>> 0;
    b[total - 8] = hi >>> 24; b[total - 7] = hi >>> 16; b[total - 6] = hi >>> 8; b[total - 5] = hi;
    b[total - 4] = lo >>> 24; b[total - 3] = lo >>> 16; b[total - 2] = lo >>> 8; b[total - 1] = lo;
    for (var o = 0; o < total; o += 64) {
      for (var i = 0; i < 16; i++) w[i] = (b[o + 4 * i] << 24) | (b[o + 4 * i + 1] << 16) | (b[o + 4 * i + 2] << 8) | b[o + 4 * i + 3];
      for (i = 16; i < 64; i++) {
        var a = w[i - 15], c = w[i - 2];
        var s0 = ((a >>> 7) | (a << 25)) ^ ((a >>> 18) | (a << 14)) ^ (a >>> 3), s1 = ((c >>> 17) | (c << 15)) ^ ((c >>> 19) | (c << 13)) ^ (c >>> 10);
        w[i] = (w[i - 16] + s0 + w[i - 7] + s1) | 0;
      }
      var A = h[0], Bb = h[1], C = h[2], D = h[3], E = h[4], F = h[5], G = h[6], H = h[7];
      for (i = 0; i < 64; i++) {
        var S1 = ((E >>> 6) | (E << 26)) ^ ((E >>> 11) | (E << 21)) ^ ((E >>> 25) | (E << 7));
        var t1 = (H + S1 + ((E & F) ^ (~E & G)) + K256[i] + w[i]) | 0;
        var S0 = ((A >>> 2) | (A << 30)) ^ ((A >>> 13) | (A << 19)) ^ ((A >>> 22) | (A << 10));
        var t2 = (S0 + ((A & Bb) ^ (A & C) ^ (Bb & C))) | 0;
        H = G; G = F; F = E; E = (D + t1) | 0; D = C; C = Bb; Bb = A; A = (t1 + t2) | 0;
      }
      h[0] += A; h[1] += Bb; h[2] += C; h[3] += D; h[4] += E; h[5] += F; h[6] += G; h[7] += H;
    }
    return Array.from(h).map(function (x) { return (x >>> 0).toString(16).padStart(8, "0"); }).join("");
  }

  // ---- loading -------------------------------------------------------------------------
  function readZip(d) {   // -> [[name, bytes]] for every file entry (stored or deflated)
    var eocd = -1;
    for (var i = d.length - 22; i >= Math.max(0, d.length - 65557); i--) if (B.u32le(d, i) === 0x06054b50) { eocd = i; break; }
    if (eocd < 0) throw new B.PlaceError("this is not a ZIP file");
    var count = B.u16le(d, eocd + 10), off = B.u32le(d, eocd + 16), out = [];
    for (var k = 0; k < count; k++) {
      if (B.u32le(d, off) !== 0x02014b50) throw new B.PlaceError("damaged ZIP directory");
      var method = B.u16le(d, off + 10), csize = B.u32le(d, off + 20), usize = B.u32le(d, off + 24);
      var fnl = B.u16le(d, off + 28), exl = B.u16le(d, off + 30), cml = B.u16le(d, off + 32), lho = B.u32le(d, off + 42);
      var name = B.bstr(d, off + 46, off + 46 + fnl);
      off += 46 + fnl + exl + cml;
      if (name.slice(-1) === "/") continue;
      var lfn = B.u16le(d, lho + 26), lex = B.u16le(d, lho + 28), start = lho + 30 + lfn + lex, comp = d.subarray(start, start + csize), data;
      if (method === 0) data = comp.slice(0, usize);
      else if (method === 8) {
        var inf = new BR.inflate.Inflater(false), cap = inf.feedCapture(comp);
        data = cap.slice(0, usize);
      } else throw new B.PlaceError("ZIP entry " + name + " uses a compression this page cannot open");
      out.push([name.split("/").pop(), data]);
    }
    return out;
  }
  function makeBlocks(items) {   // items [[name, bytes]] -> blocks sorted as Python sorts (name, data)
    items.sort(function (a, b) {
      if (a[0] !== b[0]) return a[0] < b[0] ? -1 : 1;
      var x = B.bstr(a[1]), y = B.bstr(b[1]);
      return x < y ? -1 : x > y ? 1 : 0;
    });
    return items.map(function (it, i) { return { name: it[0], data: it[1], index: i }; });
  }

  // ---- the whole job -------------------------------------------------------------------
  function run(blocks, progress, stages) {
    stages = stages || ["PDF", "Word", "JPEG"];
    var R = { blocks: blocks, files: [], log: [], t0: Date.now() };
    function say(stage) {
      var msg = Array.prototype.slice.call(arguments, 1).map(String).join(" ");
      R.log.push([Math.round((Date.now() - R.t0) / 10) / 100, stage, msg]);
      if (progress) progress({ ev: "log", stage: stage, msg: msg });
    }
    say("start", blocks.length + " blocks of " + (blocks.length ? blocks[0].data.length : 0) + " bytes");
    R.guesses = new Map();
    blocks.forEach(function (b) { R.guesses.set(b.name, BR.classify.guess(b)); });
    if (progress) progress({ ev: "guesses", guesses: blocks.map(function (b) { return R.guesses.get(b.name)[0]; }) });
    var free = blocks.slice();

    if (stages.indexOf("PDF") >= 0 && free.some(function (b) { return B.startsWith(b.data, "%PDF-"); })) {
      var P = new BR.pdf.PDF(free, say), ok = true, note;
      try {
        P.anchor();
        if (progress) progress({ ev: "placed", kind: "PDF", at: P.L.at.map(function (b) { return b ? b.name : null; }) });
        var ss = P.streams.slice().sort(function (a, b) { return ((a.filter === "DCTDecode") - (b.filter === "DCTDecode")) || (a.length - b.length); });
        ss.forEach(function (s) {
          var r = BR.streams.order(P, s, null, say, progress && function (k, n, path) { progress({ ev: "trying", kind: "PDF", stream: s.num, done: k, of: n }); });
          r[1].forEach(function (pb) { P.place(pb[0], pb[1], "inside stream " + s.num + " (" + r[0] + ")"); });
          if (r[1].length) {
            say("stream", "object " + s.num + ", " + r[0] + ": " + r[1].length + " blocks ordered and checked");
            if (progress) progress({ ev: "placed", kind: "PDF", at: P.L.at.map(function (b) { return b ? b.name : null; }) });
          }
        });
        note = "every stream decrypts and closes correctly (zlib checksums, JPEG end markers)";
      } catch (e) {
        if (!(e instanceof B.PlaceError)) throw e;
        ok = false; note = e.message; say("PDF", "stopped:", e.message);
      }
      if (P.L) { R.files.push({ kind: "PDF", name: "recovered.pdf", layout: P.L, size: P.size, ok: ok, note: note }); free = Array.from(P.free.values()); }
    }

    if (stages.indexOf("Word") >= 0 && free.some(function (b) { return B.startsWith(b.data, BR.word.MAGIC); })) {
      var W = new BR.word.Word(free, say), wok, wnote, F = BR.features;
      try {
        W.anchor();
        var cands = [];
        W.free.forEach(function (b) {
          if (F.jpegScanLike(b.data) !== "yes" && B.find(b.data, B.fromB("\xff\xd9")) < 0 && !(b.data[0] === 0xFF && b.data[1] === 0xD8) && F.entropy(b.data) < 6.5) cands.push(b);
        });
        W.leftovers(cands);
        wok = W.L.at.every(function (x) { return x !== null; }); wnote = "header, FAT, directory and Word's own tables agree";
      } catch (e) {
        if (!(e instanceof B.PlaceError)) throw e;
        wok = false; wnote = e.message; say("Word", "stopped:", e.message);
      }
      if (W.L) {
        R.files.push({ kind: "Word", name: "recovered.doc", layout: W.L, size: W.L.n * BS, ok: wok, note: wnote });
        free = Array.from(W.free.values());
        if (progress) progress({ ev: "placed", kind: "Word", at: W.L.at.map(function (b) { return b ? b.name : null; }) });
      }
    }

    if (stages.indexOf("JPEG") >= 0 && free.some(function (b) { return b.data[0] === 0xFF && b.data[1] === 0xD8 && b.data[2] === 0xFF; })) {
      try {
        var L = BR.jpegfile.rebuild(free, say, null, progress && function (k, n, path) {
          progress({ ev: "picture", done: k, of: n, path: path ? path.map(function (b) { return b.name; }) : null });
        });
        var used = new Set(L.at.filter(Boolean).map(function (b) { return b.name; }));
        free = free.filter(function (b) { return !used.has(b.name); });
        var exact = L.exact !== false;
        R.files.push({ kind: "JPEG", name: "recovered.jpg", layout: L, size: null, ok: exact,
          note: exact ? "decodes to the last row, then the end-of-image marker" : "best order found; some blocks could not be placed with confidence" });
      } catch (e) {
        if (!(e instanceof B.PlaceError)) throw e;
        say("JPEG", "stopped:", e.message);
      }
    }
    R.unplaced = free;
    say("done", (blocks.length - free.length) + " blocks placed in " + R.files.length + " files, " + free.length + " left over");
    return R;
  }

  function fileBytes(f) {
    var data = B.concat(f.layout.at.map(function (b) { return b ? b.data : new Uint8Array(BS); }));
    if (f.kind === "JPEG") {
      var k = B.rfind(data, B.fromB("\xff\xd9"), 0, data.length);
      if (k >= 0) data = data.subarray(0, k + 2);
    } else if (f.size) data = data.subarray(0, f.size);
    return data;
  }
  function placedMap(R) {
    var m = new Map();
    R.files.forEach(function (f) { f.layout.at.forEach(function (b, p) { if (b) m.set(b.name, [f, p]); }); });
    return m;
  }
  function summarize(R) {
    var placed = placedMap(R), rows = [];
    R.files.forEach(function (f) {
      var data = fileBytes(f);
      f.bytes = data.length; f.md5 = B.hex(BR.pdfcrypt.md5(data)); f.sha256 = sha256(data); f.data = data;
    });
    R.blocks.forEach(function (b) {
      var g = R.guesses.get(b.name), fp = placed.get(b.name) || [null, null];
      rows.push({ block: b.name, md5: B.hex(BR.pdfcrypt.md5(b.data)), first_guess: g[0], first_guess_reason: g[1],
        file: fp[0] ? fp[0].kind : "unplaced", position: fp[1], offset: fp[1] !== null ? fp[1] * BS : null, how: fp[0] ? fp[0].layout.how[fp[1]] : "" });
    });
    var summary = {
      blocks: R.blocks.length,
      files: R.files.map(function (f) { return { kind: f.kind, name: f.name, ok: f.ok, note: f.note, bytes: f.bytes, md5: f.md5, sha256: f.sha256,
        blocks: f.layout.at.filter(Boolean).length, positions: f.layout.n }; }),
      unplaced: R.unplaced.map(function (b) { return b.name; }), log: R.log
    };
    return { summary: summary, blocks: rows };
  }
  function b64(u8) {
    var s = "";
    for (var i = 0; i < u8.length; i += 8192) s += String.fromCharCode.apply(null, u8.subarray(i, i + 8192));
    return btoa(s);
  }
  function reportData(R, summary) {   // report.data()
    var placed = placedMap(R);
    var files = R.files.map(function (f) {
      var info = summary.files.filter(function (x) { return x.name === f.name; })[0], item = Object.assign({}, info);
      item.how = f.layout.how; item.at = f.layout.at.map(function (b) { return b ? b.name : null; });
      if (f.kind === "JPEG") item.preview = "data:image/jpeg;base64," + b64(f.data);
      return item;
    });
    return { credit: "Created by Captain Scott Russell for CPRE 5360", files: files,
      blocks: R.blocks.map(function (b) { var fp = placed.get(b.name) || [null, null], g = R.guesses.get(b.name); return [b.name, fp[0] ? fp[0].kind : "", fp[1], g[0], g[1]]; }),
      unplaced: summary.unplaced, log: summary.log, total: R.blocks.length };
  }
  function csv(rows) {
    var cols = ["block", "md5", "first_guess", "first_guess_reason", "file", "position", "offset", "how"];
    function q(v) { v = v === null || v === undefined ? "" : String(v); return /[",\r\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; }
    return cols.join(",") + "\r\n" + rows.map(function (r) { return cols.map(function (c) { return q(r[c]); }).join(","); }).join("\r\n") + "\r\n";
  }

  BR.recover = { run: run, readZip: readZip, makeBlocks: makeBlocks, fileBytes: fileBytes, summarize: summarize,
    reportData: reportData, csv: csv, sha256: sha256 };
})();
