// The browser edition's page: load the blocks, run the engine in a worker, show it live.
// Created by Captain Scott Russell for CPRE 5360.
(function () {
  "use strict";
  var $ = function (s) { return document.querySelector(s); };
  var KIND = { PDF: "PDF document", Word: "Word document", JPEG: "JPEG picture" };
  var drop = $("#drop"), pick = $("#pick"), worker = null, result = null, names = [], tiles = new Map(), tracks = {};

  // ---- the worker: the engine source is in this page, so it runs offline ---------------
  var WORKER = [
    ENGINE_SRC,
    "self.onmessage = function (m) {",
    "  var last = 0;",
    "  function send(o, force) { var t = Date.now(); if (o.ev === 'log' || o.ev === 'placed' || o.ev === 'guesses' || force || t - last > 120) { last = t; postMessage(o); } }",
    "  try {",
    "    var items = [], input = null;",
    "    m.data.files.forEach(function (f) {",
    "      var u = new Uint8Array(f.buf);",
    "      if (/\\.zip$/i.test(f.name) || (u[0] === 0x50 && u[1] === 0x4B && u[2] === 3 && u[3] === 4)) { items = items.concat(BR.recover.readZip(u)); input = m.data.files.length === 1 ? BR.recover.fingerprint(f.name, u) : null; }",
    "      else items.push([f.name, u]);",
    "    });",
    "    var blocks = BR.recover.makeBlocks(items);",
    "    postMessage({ ev: 'blocks', names: blocks.map(function (b) { return b.name; }) });",
    "    var R = BR.recover.run(blocks, send, null, m.data.thorough);",
    "    R.input = input;",
    "    var out = BR.recover.summarize(R), data = BR.recover.reportData(R, out.summary);",
    "    var files = R.files.map(function (f) { return { name: f.name, kind: f.kind, bytes: f.data }; });",
    "    postMessage({ ev: 'result', data: data, summary: out, csv: BR.recover.csv(out.blocks), files: files });",
    "  } catch (e) { postMessage({ ev: 'error', msg: e && e.message ? e.message : String(e) }); }",
    "};"].join("\n");

  function start(fileList) {
    var files = Array.prototype.slice.call(fileList);
    if (!files.length) return;
    drop.classList.add("hidden"); $("#work").classList.remove("hidden");
    $("#feed").textContent = ""; feed("Reading " + files.length + " file" + (files.length > 1 ? "s" : "") + "...");
    Promise.all(files.map(function (f) { return f.arrayBuffer().then(function (buf) { return { name: f.name, buf: buf }; }); })).then(function (loaded) {
      var url = URL.createObjectURL(new Blob([WORKER], { type: "text/javascript" }));
      worker = new Worker(url);
      worker.onmessage = function (m) { on(m.data); };
      worker.postMessage({ files: loaded, thorough: $("#thorough").checked }, loaded.map(function (f) { return f.buf; }));
    });
  }
  function feed(line, stage) {
    var f = $("#feed"), d = document.createElement("div");
    if (stage) { var b = document.createElement("b"); b.textContent = stage + "  "; d.appendChild(b); }
    d.appendChild(document.createTextNode(line));
    f.appendChild(d); f.scrollTop = f.scrollHeight;
  }
  function now(t, frac) { $("#now").textContent = t; if (frac != null) $("#barfill").style.width = Math.round(100 * frac) + "%"; }

  function on(m) {
    if (m.ev === "blocks") {
      names = m.names;
      var pile = $("#pile"); pile.innerHTML = "";
      names.forEach(function (n) { var i = document.createElement("i"); i.title = n; pile.appendChild(i); tiles.set(n, i); });
      now(names.length + " blocks loaded", 0.02);
    } else if (m.ev === "guesses") {
      m.guesses.forEach(function (g, k) { var t = tiles.get(names[k]); if (t) t.className = "g-" + g; });
    } else if (m.ev === "log") {
      feed(m.msg, m.stage);
      if (m.stage === "header" || m.stage === "FAT" || m.stage === "picture") now(m.msg);
    } else if (m.ev === "placed") {
      showTrack(m.kind, m.at, null);
    } else if (m.ev === "trying") {
      now("PDF stream " + m.stream + ": trying each candidate as block " + m.done + " of " + m.of, 0.1 + 0.3 * (m.done / m.of));
    } else if (m.ev === "picture") {
      now("Picture: block " + m.done + " of " + m.of + " decoded and judged by how its rows join", 0.55 + 0.4 * (m.done / m.of));
      if (m.path) showTrack("JPEG", [null].concat(m.path), null, true);
    } else if (m.ev === "result") {
      result = m;
      m.data.files.forEach(function (f) { showTrack(f.kind, f.at, f.how); });
      finished();
    } else if (m.ev === "error") {
      feed("Stopped: " + m.msg, "error"); now("Stopped: " + m.msg);
    }
  }
  function showTrack(kind, at, how, live) {
    var tr = tracks[kind];
    if (!tr || tr.n !== at.length) {
      if (tr) tr.el.remove();
      var el = document.createElement("div"); el.className = "track t-" + kind;
      el.innerHTML = '<h4><b>' + KIND[kind] + '</b><span class="cnt"></span></h4><div class="cells"></div>';
      var cells = el.querySelector(".cells"), list = [];
      for (var p = 0; p < at.length; p++) { var c = document.createElement("i"); cells.appendChild(c); list.push(c); }
      $("#tracks").appendChild(el);
      tr = tracks[kind] = { el: el, cells: list, n: at.length, shown: new Array(at.length).fill(null) };
    }
    var placed = 0;
    at.forEach(function (name, p) {
      if (name) placed++;
      if (tr.shown[p] === name) return;
      var c = tr.cells[p];
      if (tr.shown[p]) { var old = tiles.get(tr.shown[p]); if (old) old.classList.remove("gone"); }
      tr.shown[p] = name;
      c.className = name ? "on" + (how && /not confirmed/.test(how[p] || "") ? " unsure" : "") : "";
      c.title = name ? name + " at position " + p + (how && how[p] ? " - " + how[p] : "") : "position " + p;
      if (name) { var t = tiles.get(name); if (t) t.classList.add("gone"); }
    });
    tr.el.querySelector(".cnt").textContent = placed + " of " + at.length + (live ? " (trying)" : "");
  }

  function finished() {
    var s = result.summary.summary;
    now("Done", 1);
    $("#title").textContent = "Sorted and rebuilt";
    $("#done").classList.remove("hidden");
    $("#donemsg").textContent = s.files.map(function (f) { return KIND[f.kind] + ": " + f.blocks + " blocks" + (f.ok ? ", checked" : ", not fully confirmed"); }).join(" · ") +
      (s.unplaced.length ? " · " + s.unplaced.length + " blocks left over" : "");
    var dl = $("#dl"); dl.innerHTML = "";
    result.files.forEach(function (f) { addDl(dl, f.name, f.bytes, f.kind === "PDF" ? "application/pdf" : f.kind === "JPEG" ? "image/jpeg" : "application/msword"); });
    addDl(dl, "block_map.csv", new TextEncoder().encode(result.csv), "text/csv");
    addDl(dl, "summary.json", new TextEncoder().encode(JSON.stringify(result.summary, null, 1)), "application/json");
    var rep = reportHtml();
    addDl(dl, "report.html", new TextEncoder().encode(rep), "text/html");
    var all = [];
    result.files.forEach(function (f) { all.push([f.name, f.bytes]); });
    all.push(["block_map.csv", new TextEncoder().encode(result.csv)], ["summary.json", new TextEncoder().encode(JSON.stringify(result.summary, null, 1))], ["report.html", new TextEncoder().encode(rep)]);
    addDl(dl, "Everything (.zip)", zipStore(all), "application/zip", "recovered.zip");
    var fr = $("#rep"); fr.srcdoc = rep; $("#norep").classList.add("hidden");
    var tab = document.querySelector('.tab[data-tab="report"]'); tab.classList.add("ping");
  }
  function reportHtml() {
    return REPORT_TPL.replace("/*DATA*/", JSON.stringify(result.data).replace(/<\//g, "<\\/"));
  }
  function addDl(dl, label, bytes, type, fname) {
    var a = document.createElement("a"); a.className = "btn alt"; a.textContent = label;
    a.href = URL.createObjectURL(new Blob([bytes], { type: type })); a.download = fname || label;
    dl.appendChild(a);
  }
  // a ZIP with stored (uncompressed) entries
  var CRC = (function () { var t = new Uint32Array(256); for (var n = 0; n < 256; n++) { var c = n; for (var k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
  function crc32(b) { var c = 0xffffffff; for (var i = 0; i < b.length; i++) c = CRC[(c ^ b[i]) & 255] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; }
  function zipStore(items) {
    var parts = [], central = [], off = 0;
    function le(n, w) { var a = []; for (var i = 0; i < w; i++) a.push((n >>> (8 * i)) & 255); return a; }
    items.forEach(function (it) {
      var name = new TextEncoder().encode("recovered/" + it[0]), d = it[1], c = crc32(d);
      var head = [].concat(le(0x04034b50, 4), le(20, 2), le(0, 2), le(0, 2), le(0, 2), le(0x21, 2), le(c, 4), le(d.length, 4), le(d.length, 4), le(name.length, 2), le(0, 2));
      parts.push(new Uint8Array(head), name, d);
      central.push(new Uint8Array([].concat(le(0x02014b50, 4), le(20, 2), le(20, 2), le(0, 2), le(0, 2), le(0, 2), le(0x21, 2), le(c, 4), le(d.length, 4), le(d.length, 4),
        le(name.length, 2), le(0, 2), le(0, 2), le(0, 2), le(0, 2), le(0, 4), le(off, 4))), name);
      off += head.length + name.length + d.length;
    });
    var csize = central.reduce(function (a, b) { return a + b.length; }, 0);
    var end = new Uint8Array([].concat(le(0x06054b50, 4), le(0, 2), le(0, 2), le(items.length, 2), le(items.length, 2), le(csize, 4), le(off, 4), le(0, 2)));
    return new Blob(parts.concat(central, [end]));
  }

  drop.addEventListener("dragover", function (e) { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", function () { drop.classList.remove("over"); });
  drop.addEventListener("drop", function (e) { e.preventDefault(); drop.classList.remove("over"); start(e.dataTransfer.files); });
  pick.addEventListener("change", function () { start(pick.files); });
})();
