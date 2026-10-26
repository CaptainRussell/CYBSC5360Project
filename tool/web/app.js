/* The browser edition: drop an image, watch the analysis happen, read the report.

   The engine (the same checks as the command-line tool, ported to JavaScript and kept
   identical by the test suite) runs in a Web Worker built from the page's own text, so
   the page works from a double-clicked file with no internet. Events from the worker
   are played back with short minimum durations, so a small image's analysis can still
   be followed; "Skip animation" plays them back as fast as they arrive. */
(function () {
const $ = s => document.querySelector(s), $$ = s => Array.from(document.querySelectorAll(s));
const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = n => Number(n || 0).toLocaleString("en-US");
const size = n => { n = +n || 0; const u = ["bytes", "KB", "MB", "GB", "TB"]; let i = 0; while (n >= 1024 && i < 4) { n /= 1024; i++; } return i ? (n >= 10 ? n.toFixed(0) : n.toFixed(1)) + " " + u[i] : n + " bytes"; };
const SVG = (p, c) => '<svg class="' + (c || "ico") + '" viewBox="0 0 24 24" aria-hidden="true">' + p + "</svg>";
const CI = {
  C1: '<path d="M4 4h16v6a8 8 0 0 1-16 0z"/><path d="M9 9h.01M15 9h.01M9 14c1.5 1 4.5 1 6 0"/>', C2: '<path d="M4 6h10M4 12h10M4 18h6"/><rect x="16" y="14" width="5" height="6" rx="1"/>',
  C3: '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>', C4: '<circle cx="8" cy="15" r="4"/><path d="m10.8 12.2 8.7-8.7M17 6l2 2M14.5 8.5l2 2"/>',
  C5: '<circle cx="5" cy="12" r="2"/><circle cx="11" cy="12" r="2"/><circle cx="18" cy="12" r="3.6"/>', C6: '<path d="M4 4h12a4 4 0 0 1 4 4v12H8a4 4 0 0 1-4-4z"/><path d="m10 10 4 4m0-4-4 4"/>',
  C7: '<path d="M3 7h18v13H3zM3 7l2-3h14l2 3M10 12h4"/>', F1: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>' };
const QN = { C1: "Disguised", C2: "Hidden at end", C3: "Locked", C4: "Password", C5: "Odd one out", C6: "Never mentioned", C7: "Archive", F1: "Unusual time" };
const FAM = { image: "var(--f5)", document: "var(--f3)", archive: "var(--f2)", executable: "var(--f7)", text: "var(--f4)", database: "var(--f6)", media: "var(--f6)", metadata: "var(--minor)", unknown: "var(--minor)" };
const toast = msg => { const t = $("#toast"); t.textContent = msg; t.classList.add("on"); clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove("on"), 2600); };
const show = (id, dir) => { $$(".view").forEach(v => { v.classList.remove("from-r", "from-l"); v.classList.toggle("on", v.id === id); if (v.id === id && dir) v.classList.add(dir); }); window.scrollTo({ top: 0 }); };
/* the pages after a drive is dropped: the analysis itself, then the reports; the analysis page always stays */
const PAGES = ["analysis", "first", "dates"];
let page = "analysis";
function goPage(p) {
  const tab = $('#apptabs [data-p="' + p + '"]');
  if (!tab || tab.disabled) return;
  const dir = PAGES.indexOf(p) > PAGES.indexOf(page) ? "from-r" : PAGES.indexOf(p) < PAGES.indexOf(page) ? "from-l" : "";
  page = p;
  $$("#apptabs .atab").forEach(t => t.classList.toggle("on", t.dataset.p === p));
  tab.classList.remove("fresh");
  $("#print").style.display = p === "analysis" ? "none" : "";
  if (p === "analysis") show("v-live", dir);
  else {
    current = p;
    if ($("#frame").dataset.k !== p) { $("#frame").src = reports[p].url; $("#frame").dataset.k = p; }
    saveMenu();
    show("v-report", dir);
  }
}
$("#apptabs").addEventListener("click", e => { const b = e.target.closest(".atab"); if (b) goPage(b.dataset.p); });
/* a highlight travels from what was clicked to the tab it opens */
function flyTo(from, p) {
  const tab = $('#apptabs [data-p="' + p + '"]');
  if (!from || !tab || matchMedia("(prefers-reduced-motion: reduce)").matches) return goPage(p);
  const a = from.getBoundingClientRect(), b = tab.getBoundingClientRect(), g = document.createElement("div");
  g.className = "flyer"; Object.assign(g.style, { left: a.left + "px", top: a.top + "px", width: a.width + "px", height: a.height + "px" });
  document.body.appendChild(g);
  requestAnimationFrame(() => requestAnimationFrame(() => Object.assign(g.style, { left: b.left + "px", top: b.top + "px", width: b.width + "px", height: b.height + "px", opacity: ".35" })));
  setTimeout(() => { g.remove(); goPage(p); }, 460);
}
const setBar = () => { const h = $("#appbar").offsetHeight; if (h) document.documentElement.style.setProperty("--bar", h + "px"); };
addEventListener("resize", setBar);
const theme = () => document.documentElement.dataset.theme || "dark";
const toFrame = m => { const f = $("#frame").contentWindow; if (f) f.postMessage(m, "*"); };
$("#frame").addEventListener("load", () => toFrame({ theme: theme() }));
$("#a-theme").addEventListener("click", () => setTimeout(() => toFrame({ theme: theme() }), 0));
$("#print").addEventListener("click", () => toFrame({ print: true }));

/* ---------------- start screen ---------------- */
function wireDrop(zone, input, onFiles) {
  ["dragenter", "dragover"].forEach(t => zone.addEventListener(t, e => { e.preventDefault(); zone.classList.add("over"); }));
  ["dragleave", "drop"].forEach(t => zone.addEventListener(t, e => { e.preventDefault(); zone.classList.remove("over"); }));
  zone.addEventListener("drop", e => onFiles([...e.dataTransfer.files]));
  zone.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } });
  input.addEventListener("change", () => { onFiles([...input.files]); input.value = ""; });
}
const route = files => {
  if (!files.length) return;
  const csv = files.filter(f => /\.csv$/i.test(f.name));
  if (csv.length === files.length) return startRecords(csv);
  const img = files.find(f => !/\.csv$/i.test(f.name));
  if (/\.(e01|ex01|l01|aff|vmdk|vhdx?|zip|7z)$/i.test(img.name)) return showError("“" + img.name + "” is not a raw image. The tool reads raw .img, .dd or .raw images: export one first (for example with FTK Imager's “Export Disk Image”, choosing Raw (dd)).");
  startImage(img);
};
wireDrop($("#drop-img"), $("#f-img"), route);
wireDrop($("#drop-rec"), $("#f-rec"), route);
document.addEventListener("dragover", e => e.preventDefault());
document.addEventListener("drop", e => { e.preventDefault(); if ($("#v-home").classList.contains("on") && !e.target.closest(".drop")) route([...e.dataTransfer.files]); });
function showError(msg) { const e = $("#err"); e.innerHTML = "<b>That did not work.</b> " + esc(msg); e.classList.add("on"); show("v-home"); }

/* ---------------- the worker ---------------- */
let worker = null;
function newWorker() {
  if (worker) worker.terminate();
  const src = $("#engine-src").textContent;
  try { worker = new Worker(URL.createObjectURL(new Blob([src], { type: "text/javascript" }))); }
  catch (e) { showError("This browser would not start the background reader (" + e.message + "). Try Chrome, Edge or Firefox."); return null; }
  worker.onmessage = e => { Q.push(e.data); if (run) run.log.push(e.data); };
  worker.onerror = e => Q.push({ ev: "error", message: e.message || "The analysis stopped unexpectedly." });
  return worker;
}

/* ---------------- live view ---------------- */
let reports = {}, Q = [], fast = false, gateUntil = 0, itemBuf = [], hitBuf = [], run = null;
const STEPS_IMG = [["open", "Open the drive"], ["read", "Read every file"], ["check", "Ask eight questions"], ["score", "Score and rank"], ["hash", "Fingerprint"], ["dates", "Windows date checks"], ["report", "Report"]];
const STEPS_REC = [["load", "Load the records"], ["dates", "Eleven date checks"], ["report", "Report"]];
function setSteps(list) { $("#steps").innerHTML = list.map(s => '<div class="step" data-s="' + s[0] + '">' + s[1] + "</div>").join(""); }
function stepOn(id) {
  let seen = false;
  $$("#steps .step").forEach(s => { if (s.dataset.s === id) { s.classList.add("on"); s.classList.remove("done"); seen = true; } else if (!seen) { s.classList.remove("on"); if (!s.classList.contains("skip")) s.classList.add("done"); } });
}
function resetLive(name, bytes, steps) {
  Q = []; itemBuf = []; hitBuf = []; fast = false; gateUntil = 0;
  run = { name, bytes, items: 0, zip: 0, noise: 0, kinds: new Map(), counts: {}, cells: new Uint16Array(384), firstlook: null, dates: null, fs: "", done: false, log: [], steps };
  $("#l-name").textContent = name; $("#l-size").textContent = size(bytes); $("#l-fs").textContent = "…";
  setSteps(steps); stepOn(steps[0][0]);
  $("#l-hex").innerHTML = ""; $("#l-fields").innerHTML = '<div class="note">Waiting for the drive…</div>';
  const map = $("#l-map"); map.innerHTML = '<div class="sweep"></div>' + "<i></i>".repeat(384); map.classList.remove("reading");
  ["#c-files", "#c-zip", "#c-noise"].forEach(s => $(s).textContent = "0");
  $("#l-kinds").innerHTML = '<div class="note">Each file is identified from its first bytes, not its name.</div>';
  $("#l-q").innerHTML = Object.keys(QN).map(r => '<div class="qt" data-r="' + r + '" data-tip="<b>' + r + "</b> " + QN[r] + '">' + SVG(CI[r]) + "<b>0</b><span>" + r + " · " + QN[r] + "</span></div>").join("");
  $("#l-feed").innerHTML = ""; $("#p-check").style.width = "0";
  ["#card-rank", "#card-hash", "#card-dates", "#card-done"].forEach(s => $(s).style.display = "none");
  $("#card-q").style.display = steps === STEPS_REC ? "none" : "";
  $("#l-path").innerHTML = "&nbsp;";
  $("#skip").style.display = ""; $("#replay").style.display = "none";
  $("#a-state").textContent = "ANALYSING"; $(".atab .live-dot").classList.remove("off");
  $("#appbar").hidden = false; setBar();
  page = "analysis"; $$("#apptabs .atab").forEach(t => t.classList.toggle("on", t.dataset.p === "analysis"));
  show("v-live");
}
/* play the recorded analysis again; the reports stay as they are */
function replay() {
  const saved = run;
  resetLive(saved.name, saved.bytes, saved.steps);
  Object.assign(run, { log: saved.log, firstlook: saved.firstlook, dates: saved.dates, replaying: true });
  setCols(saved.steps === STEPS_REC);
  if (saved.steps === STEPS_REC) { $("#l-fs").textContent = "Windows records"; $("#card-dates").style.display = ""; dateTiles(); }
  for (const k of Object.keys(reports)) $('#apptabs [data-p="' + k + '"]').disabled = false;
  Q = saved.log.slice();
  requestAnimationFrame(tick);
}
$("#replay").addEventListener("click", replay);
const setCols = rec => { $(".c1").style.display = rec ? "none" : ""; $(".c2").style.display = rec ? "none" : ""; };
$("#skip").addEventListener("click", () => { fast = true; gateUntil = 0; $("#skip").style.display = "none"; });

function resetTabs() {
  Object.values(reports).forEach(r => URL.revokeObjectURL(r.url)); reports = {};
  $$("#apptabs .atab").forEach(t => { if (t.dataset.p !== "analysis") { t.disabled = true; t.classList.remove("fresh"); t.style.display = ""; } });
  $("#frame").removeAttribute("src"); delete $("#frame").dataset.k;
  $("#save").style.display = "none";
}
function startImage(file) {
  $("#err").classList.remove("on");
  resetTabs();
  resetLive(file.name, file.size, STEPS_IMG);
  setCols(false);
  if (!newWorker()) return;
  worker.postMessage({ cmd: "image", file });
  requestAnimationFrame(tick);
}
function startRecords(files) {
  $("#err").classList.remove("on");
  resetTabs();
  resetLive(files.length + " record file" + (files.length === 1 ? "" : "s"), files.reduce((a, f) => a + f.size, 0), STEPS_REC);
  setCols(true);
  $("#l-fs").textContent = "Windows records";
  $("#card-dates").style.display = ""; dateTiles();
  if (!newWorker()) return;
  worker.postMessage({ cmd: "records", files });
  requestAnimationFrame(tick);
}

/* the boot sector, typed out row by row, then its fields lit one by one */
function bootFields(B, fs) {
  const u = (o, n) => { let v = 0; for (let i = n - 1; i >= 0; i--) v = v * 256 + (B[o + i] || 0); return v; };
  const asc = (o, n) => String.fromCharCode(...B.slice(o, o + n)).replace(/[^\x20-\x7e]/g, "").trim();
  const bps = u(11, 2), spc = B[13] > 128 ? 2 ** (256 - B[13]) : B[13];
  const F = [[3, 8, "Drive type", '"' + asc(3, 8) + '"'], [11, 2, "Bytes per sector", fmt(bps)], [13, 1, "Sectors per cluster", spc + " (" + fmt(bps * spc) + " bytes)"]];
  if (fs === "NTFS") F.push([40, 8, "Volume size", size(u(40, 8) * bps)], [48, 8, "File table starts at", "cluster " + fmt(u(48, 8))], [72, 8, "Serial number", run.serial || ""]);
  else {
    F.push([14, 2, "Reserved sectors", fmt(u(14, 2))], [16, 1, "File tables (FATs)", B[16]], [u(19, 2) ? 19 : 32, u(19, 2) ? 2 : 4, "Volume size", size((u(19, 2) || u(32, 4)) * bps)]);
    const f32 = fs === "FAT32"; F.push([f32 ? 71 : 43, 11, "Drive name", '"' + asc(f32 ? 71 : 43, 11) + '"']);
  }
  F.push([510, 2, "Boot signature", (B[510] || 0).toString(16).toUpperCase() + " " + (B[511] || 0).toString(16).toUpperCase()]);
  return F;
}
function playBoot(hex, fs) {
  const B = (hex.match(/../g) || []).map(h => parseInt(h, 16)), F = bootFields(B, fs), own = {};
  F.forEach((f, i) => { for (let k = f[0]; k < f[0] + f[1]; k++) own[k] = i; });
  const rows = [0, 16, 32, 48, 64, 80, 496];
  $("#l-hex").innerHTML = rows.map((r, j) => (j === 6 ? '<div class="r note" style="font-size:11px">…</div>' : "") + '<div class="r"><span class="o">' + r.toString(16).padStart(4, "0").toUpperCase() + "</span><span>" +
    B.slice(r, r + 16).map((b, k) => '<i data-k="' + (r + k) + '"' + (own[r + k] != null ? ' style="--fc:var(--f' + (own[r + k] % 8 + 1) + ')"' : "") + ">" + b.toString(16).padStart(2, "0").toUpperCase() + "</i>").join(" ") + "</span></div>").join("");
  $("#l-fields").innerHTML = F.map((f, i) => '<div class="lf" style="--fc:var(--f' + (i % 8 + 1) + ')"><i></i><span>' + esc(f[2]) + "</span><b>" + esc(f[3]) + "</b></div>").join("");
  const rowsEl = $$("#l-hex .r"), fEl = $$("#l-fields .lf"), step = fast ? 0 : 90;
  rowsEl.forEach((r, i) => setTimeout(() => r.classList.add("in"), i * step));
  fEl.forEach((el, i) => setTimeout(() => {
    el.classList.add("in");
    const f = F[i];
    for (let k = f[0]; k < f[0] + f[1]; k++) { const b = $('#l-hex i[data-k="' + k + '"]'); if (b) b.classList.add("hl"); }
  }, rowsEl.length * step + i * (fast ? 0 : 150)));
  return rowsEl.length * step + F.length * (fast ? 0 : 150) + 200;
}
function lightItems(n) {
  const cells = $("#l-map").children;
  for (let k = 0; k < n && itemBuf.length; k++) {
    const it = itemBuf.shift();
    if (it.z) run.zip++; else run.items++;
    if (it.noise) run.noise++;
    else run.kinds.set(it.t, (run.kinds.get(it.t) || 0) + 1);
    if (it.pos != null && !it.z) {
      const c = Math.min(383, Math.max(0, Math.floor(it.pos * 384)));
      run.cells[c]++;
      const el = cells[c + 1];
      if (el) { el.style.background = it.noise ? "var(--minor)" : (FAM[it.f] || "var(--accent)"); el.classList.remove("lit"); void el.offsetWidth; el.classList.add("lit"); }
      $("#l-map .sweep").style.left = (100 * ((c % 32) + 0.5) / 32) + "%";
    }
    run.lastPath = it.p;
  }
  $("#c-files").textContent = fmt(run.items); $("#c-zip").textContent = fmt(run.zip); $("#c-noise").textContent = fmt(run.noise);
  if (run.lastPath) $("#l-path").textContent = run.lastPath;
  const top = [...run.kinds.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8), max = Math.max(1, ...top.map(t => t[1]));
  $("#l-kinds").innerHTML = top.map(([t, c]) => '<div class="kbar"><span>' + esc(t) + '</span><div class="bar"><i style="width:' + (100 * c / max).toFixed(1) + '%"></i></div><b>' + fmt(c) + "</b></div>").join("");
}
function showHits(n) {
  for (let k = 0; k < n && hitBuf.length; k++) {
    const h = hitBuf.shift();
    run.counts[h.rid] = (run.counts[h.rid] || 0) + 1;
    const tile = $('#l-q .qt[data-r="' + h.rid + '"]');
    if (tile) { tile.querySelector("b").textContent = fmt(run.counts[h.rid]); tile.classList.add("any"); tile.classList.remove("hit"); void tile.offsetWidth; tile.classList.add("hit"); }
    const now = performance.now();
    if (!fast && now - (showHits.last || 0) < 150 && hitBuf.length) continue;   // the feed shows the newest clue every 150 ms
    showHits.last = now;
    const feed = $("#l-feed"), name = h.p.split(" › ").pop().split("/").pop();
    feed.insertAdjacentHTML("afterbegin", '<div class="fi"><b>' + h.rid + '</b><div><div class="p">' + esc(name) + '</div><div class="s">' + esc(h.say || QN[h.rid]) + "</div></div></div>");
    while (feed.children.length > 6) feed.lastChild.remove();
  }
}
function showRanking(m) {
  $("#card-q").style.display = "none"; $("#card-rank").style.display = "";
  const rates = run.rates || {}, ws = Object.keys(rates), maxW = Math.max(1e-9, ...ws.map(r => rates[r].weight));
  $("#l-weights").innerHTML = '<div class="note" style="margin-bottom:4px">How much each clue counts on this drive (rarer = heavier):</div>' +
    ws.map(r => '<div class="wt"><b>' + r + '</b><div class="bar"><i data-w="' + (100 * rates[r].weight / maxW).toFixed(1) + '"></i></div><span>' + rates[r].weight.toFixed(2) + "</span></div>").join("");
  requestAnimationFrame(() => requestAnimationFrame(() => $$("#l-weights .bar>i").forEach(i => i.style.width = i.dataset.w + "%")));
  const lead = m.leads.slice(0, 8);
  $("#l-rank").innerHTML = lead.length ? lead.map((l, i) => { const s = Math.round(l.score * 100), cls = l.score >= 0.3 ? "hot" : l.score >= 0.2 ? "warn" : "minor";
    return '<div class="rk"><span class="n">#' + (i + 1) + '</span><span class="p">' + esc(l.p.split(" › ").pop().split("/").pop()) + '</span><div class="bar ' + cls + '"><i data-w="' + s + '"></i></div></div>'; }).join("")
    : '<div class="note">No file had a clue.</div>';
  $$("#l-rank .rk").forEach((el, i) => setTimeout(() => { el.classList.add("in"); const b = el.querySelector(".bar>i"); b.style.width = b.dataset.w + "%"; }, fast ? 0 : 400 + i * 160));
  return fast ? 0 : 400 + lead.length * 160 + 700;
}
function scramble(done, total, hexFinal) {
  const H = "0123456789abcdef", n = hexFinal ? 64 : Math.floor(64 * done / Math.max(1, total));
  let s = ""; for (let i = 0; i < 64; i++) s += i < n && hexFinal ? hexFinal[i] : H[Math.floor(Math.random() * 16)];
  $("#l-hash").innerHTML = hexFinal ? esc(hexFinal) : '<span style="opacity:.55">' + s + "</span>";
  $("#p-hash").style.width = (100 * done / Math.max(1, total)).toFixed(1) + "%";
}
function dateTiles(activity) {
  const ids = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10", "R11"];
  $("#l-dq").innerHTML = ids.map(r => { const a = (activity || {})[r] || { evaluable: 0, violated: 0 };
    return '<div class="qt' + (a.violated ? " any" : "") + '" style="padding:6px"><span style="font-size:11px">' + r + '</span><b style="font-size:16px">' + (activity ? fmt(a.violated) : "–") + "</b><span>" + (activity ? (a.evaluable ? "of " + fmt(a.evaluable) : "n/a") : "") + "</span></div>"; }).join("");
}

/* keep the card that is changing in view */
const into = sel => { const el = $(sel), r = el.getBoundingClientRect(); if (r.bottom > innerHeight || r.top < 0) el.scrollIntoView({ behavior: "smooth", block: "nearest" }); };
function handle(m) {
  switch (m.ev) {
    case "volume": {
      run.fs = m.summary.fs_type; run.serial = m.summary.serial;
      $("#l-fs").textContent = m.summary.fs_type + (m.summary.label ? " · " + m.summary.label.replace(/[\x00-\x1f]/g, "") : "");
      if (m.summary.fs_type !== "NTFS") { const s = $('#steps .step[data-s="dates"]'); if (s) s.classList.add("skip"); }
      gateUntil = performance.now() + playBoot(m.boot_hex, m.summary.fs_type);
      break;
    }
    case "stage":
      if (m.stage === "read") { stepOn("read"); $("#l-map").classList.add("reading"); }
      if (m.stage === "check") { stepOn("check"); $("#l-map").classList.remove("reading"); run.checkTotal = m.total; gateUntil = performance.now() + (fast ? 0 : 300); }
      if (m.stage === "score") { run.rates = m.rates; stepOn("score"); }
      if (m.stage === "hash") { stepOn("hash"); $("#card-hash").style.display = ""; scramble(0, 1); into("#card-hash"); }
      if (m.stage === "dates") { stepOn("dates"); $("#card-dates").style.display = ""; dateTiles(); $("#l-dnote").textContent = "Comparing the dates Windows keeps in different places…"; into("#card-dates"); }
      break;
    case "items": itemBuf.push(...m.batch); break;
    case "hits": hitBuf.push(...m.batch); break;
    case "checked": $("#p-check").style.width = (100 * m.n / Math.max(1, m.total)).toFixed(1) + "%"; break;
    case "leads": gateUntil = performance.now() + showRanking(m); break;
    case "hash": scramble(m.done, m.total, m.hex); if (m.hex) gateUntil = performance.now() + (fast ? 0 : 500); break;
    case "firstlook": run.firstlook = m; break;
    case "dates_loaded": stepOn("load"); $("#l-dnote").textContent = "Loaded " + m.kind + ": " + m.file + " (" + fmt(m.rows) + " rows)"; gateUntil = performance.now() + (fast ? 0 : 350); break;
    case "dates_stage": if (m.stage === "rules") { stepOn("dates"); $("#l-dnote").textContent = "Checking " + fmt(m.total) + " files against eleven rules…"; } break;
    case "dates_progress": $("#p-dates").style.width = (100 * m.n / Math.max(1, m.total)).toFixed(1) + "%"; break;
    case "dates": {
      run.dates = m; $("#p-dates").style.width = "100%"; dateTiles(m.data.activity);
      const wide = Object.entries(m.data.activity).filter(([, a]) => a.evaluable >= 50 && a.violated / a.evaluable >= 0.9).map(([r]) => r);
      $("#l-dnote").innerHTML = fmt(m.data.counts.scored) + " files checked, " + fmt(m.data.counts.flagged) + " flagged." + (wide.length ? ' <b style="color:var(--hot)">Drive-wide pattern: ' + wide.join(", ") + "</b>" : "");
      gateUntil = performance.now() + (fast ? 0 : 1400);
      break;
    }
    case "done": finish(); break;
    case "error":
      if (m.unsupported) showError(m.message);
      else showError("The analysis stopped: " + m.message + ". Please report this with the image's file system and size.");
      run.done = true;
      break;
  }
}
/* events at the head of the queue wait for the animation of the step before them */
const GATED = new Set(["stage", "leads", "firstlook", "dates_stage", "dates", "done"]);
function tick() {
  if (!run || run.done) return;
  const now = performance.now();
  if (itemBuf.length) lightItems(fast ? itemBuf.length : Math.max(4, Math.ceil(itemBuf.length / 40)));
  if (hitBuf.length) showHits(fast ? hitBuf.length : Math.max(1, Math.ceil(hitBuf.length / 30)));
  let guard = 0;
  while (Q.length && guard++ < 400) {
    const m = Q[0];
    if (GATED.has(m.ev) && (now < gateUntil || itemBuf.length || hitBuf.length) && !fast) break;
    if (GATED.has(m.ev) && fast && now < gateUntil) break;
    Q.shift(); handle(m);
    if (run.done) return;
  }
  requestAnimationFrame(tick);
}
function finish() {
  run.done = true;
  stepOn("report"); $$("#steps .step").forEach(s => { if (!s.classList.contains("skip")) s.classList.add("done"); s.classList.remove("on"); });
  $("#skip").style.display = "none";
  const f = run.firstlook && run.firstlook.data, d = run.dates && run.dates.data;
  let msg = "";
  if (f) { const first = f.all_leads.filter(l => l.score >= f.tiers.strong).length; msg = "Checked " + fmt(f.counts.examined) + " files: " + fmt(f.counts.with_findings) + " with a clue, " + fmt(first) + " to look at first."; }
  if (d) msg += (msg ? " " : "") + "Date checks: " + fmt(d.counts.scored) + " files, " + fmt(d.counts.flagged) + " flagged.";
  $("#l-summary").textContent = msg;
  const notes = (run.firstlook && run.firstlook.notes) || [];
  if (notes.length) $("#l-summary").insertAdjacentHTML("beforeend", '<br><span style="color:var(--warn)">' + esc(notes.length + " note" + (notes.length === 1 ? "" : "s") + ": " + notes.slice(0, 3).join(" ")) + "</span>");
  $("#card-done").style.display = "";
  window.scrollTo({ top: 0, behavior: "smooth" });
  if (!run.replaying) buildReports();
  $("#a-state").textContent = "ANALYSIS COMPLETE"; $(".atab .live-dot").classList.add("off");
  $("#replay").style.display = ""; $("#save").style.display = ""; saveMenu();
  // the report tabs light up; nothing moves until you choose
  for (const k of ["first", "dates"]) { const t = $('#apptabs [data-p="' + k + '"]'); t.disabled = !reports[k]; t.style.display = reports[k] || k === "first" ? "" : "none"; if (reports[k] && !run.replaying) t.classList.add("fresh"); }
  $("#done-btns").innerHTML = Object.keys(reports).map((k, i) => '<button class="btn' + (i ? " alt" : "") + '" data-open="' + k + '">Open the ' + (k === "first" ? "first-look report" : "date checks") + " ›</button>").join("");
  setBar();
}
$("#done-btns").addEventListener("click", e => { const b = e.target.closest("[data-open]"); if (b) flyTo(b, b.dataset.open); });


/* ---------------- reports ---------------- */
let current = null;
/* inside the app, a report hides its own title bar (the app bar above it has the same buttons) and takes
   theme and print requests from the app; the saved file is the plain report */
const EMBED = '<style>body>header.top{display:none}.tabs{top:0!important}</style><script>addEventListener("message",e=>{const m=e.data||{};' +
  'if(m.theme)document.documentElement.dataset.theme=m.theme;if(m.print)window.print();});<\/script>';
const embed = html => { const i = html.lastIndexOf("</body>"); return i < 0 ? html + EMBED : html.slice(0, i) + EMBED + html.slice(i); };
const inert = obj => JSON.stringify(obj).replace(/<\//g, "<\\/").replace(/<!--/g, "<\\!--");
function buildReports() {
  Object.values(reports).forEach(r => URL.revokeObjectURL(r.url));
  reports = {};
  const stem = run.name.replace(/\.[^.]+$/, "");
  if (run.firstlook) {
    const html = TEMPLATES.firstlook_head + TEMPLATES.firstlook.replace("/*__DATA__*/null", inert(run.firstlook.data)) + "\n</html>\n";
    reports.first = { label: "First look", html, url: URL.createObjectURL(new Blob([embed(html)], { type: "text/html" })), folder: stem + " report",
      files: { "briefing.html": html, "triage.json": JSON.stringify(run.firstlook.data, null, 1), "leads.csv": run.firstlook.leads_csv } };
  }
  if (run.dates) {
    const html = TEMPLATES.date.replace("/*__DATA__*/null", inert(run.dates.data));
    reports.dates = { label: "Date checks", html, url: URL.createObjectURL(new Blob([embed(html)], { type: "text/html" })), saveUrl: null,
      folder: run.firstlook ? stem + " Windows report" : "Windows report", files: Object.assign({ "briefing.html": html }, run.dates.files) };
  }
}
$("#new").addEventListener("click", () => { if (worker) worker.terminate(); worker = null; if (run) run.done = true; $("#appbar").hidden = true; show("v-home"); });

/* ---------------- saving ---------------- */
function download(name, data, type) {
  const url = URL.createObjectURL(data instanceof Blob ? data : new Blob([data], { type: type || "application/octet-stream" }));
  const a = document.createElement("a"); a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}
const ICO = { html: '<path d="M4 4h16v16H4z"/><path d="M8 9h8M8 13h8M8 17h5"/>', data: '<path d="M4 6h16M4 12h16M4 18h16"/>', zip: '<path d="M3 7h18v13H3zM3 7l2-3h14l2 3M10 12h4"/>', tab: '<path d="M14 4h6v6M20 4l-9 9M18 14v6H4V6h6"/>' };
const TYPES = { html: "text/html", json: "application/json", csv: "text/csv" };
function saveMenu() {
  const items = current && reports[current] ? [["tab", "Open this report in its own tab", "Full window, keep it open", () => window.open(URL.createObjectURL(new Blob([reports[current].html], { type: "text/html" })), "_blank")]] : [];
  for (const [k, r] of Object.entries(reports)) for (const name of Object.keys(r.files)) {
    const ext = name.split(".").pop();
    items.push([ext === "html" ? "html" : "data", r.label + ": " + name, { "briefing.html": "the report page", "triage.json": "every result, as data", "leads.csv": "opens in Excel",
      "scores.csv": "every file's score", "outcomes.csv": "every check for every file", "indicators.json": "record warnings", "clusters.csv": "events", "run.json": "settings and inputs" }[name] || "",
      () => download((k === "first" ? "" : "") + name, r.files[name], TYPES[ext])]);
  }
  items.push(["zip", "Everything (.zip)", "Unzip next to the command-line results to compare", () => download(run.name.replace(/\.[^.]+$/, "") + " results.zip", zipAll(), "application/zip")]);
  $("#save-list").innerHTML = items.map((it, i) => '<button data-i="' + i + '">' + SVG(ICO[it[0]]) + "<span>" + esc(it[1]) + "<small>" + esc(it[2]) + "</small></span></button>").join("");
  saveMenu.items = items;
}
$("#save-btn").addEventListener("click", e => { e.stopPropagation(); $("#save").classList.toggle("open"); });
$("#save-list").addEventListener("click", e => { const b = e.target.closest("button"); if (!b) return; saveMenu.items[+b.dataset.i][3](); $("#save").classList.remove("open"); toast("Saved to your Downloads folder"); });
document.addEventListener("click", e => { if (!e.target.closest("#save")) $("#save").classList.remove("open"); });

/* a plain (stored) ZIP of every result file, in the folders the command line uses */
const CRC = (() => { const t = new Uint32Array(256); for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
const crc32 = b => { let c = 0xffffffff; for (let i = 0; i < b.length; i++) c = CRC[(c ^ b[i]) & 255] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };
function zipAll() {
  const enc = new TextEncoder(), parts = [], central = []; let off = 0;
  const d = new Date(), dt = ((d.getFullYear() - 1980) << 9) | ((d.getMonth() + 1) << 5) | d.getDate(), tm = (d.getHours() << 11) | (d.getMinutes() << 5) | (d.getSeconds() >> 1);
  for (const r of Object.values(reports)) for (const [name, text] of Object.entries(r.files)) {
    const fn = enc.encode(r.folder + "/" + name), data = enc.encode(text), crc = crc32(data);
    const h = new DataView(new ArrayBuffer(30));
    h.setUint32(0, 0x04034b50, true); h.setUint16(4, 20, true); h.setUint16(6, 0x800, true); h.setUint16(8, 0, true); h.setUint16(10, tm, true); h.setUint16(12, dt, true);
    h.setUint32(14, crc, true); h.setUint32(18, data.length, true); h.setUint32(22, data.length, true); h.setUint16(26, fn.length, true); h.setUint16(28, 0, true);
    const c = new DataView(new ArrayBuffer(46));
    c.setUint32(0, 0x02014b50, true); c.setUint16(4, 20, true); c.setUint16(6, 20, true); c.setUint16(8, 0x800, true); c.setUint16(10, 0, true); c.setUint16(12, tm, true); c.setUint16(14, dt, true);
    c.setUint32(16, crc, true); c.setUint32(20, data.length, true); c.setUint32(24, data.length, true); c.setUint16(28, fn.length, true); c.setUint32(42, off, true);
    parts.push(new Uint8Array(h.buffer), fn, data); central.push(new Uint8Array(c.buffer), fn);
    off += 30 + fn.length + data.length;
  }
  const cdSize = central.reduce((a, b) => a + b.length, 0), n = central.length / 2, e = new DataView(new ArrayBuffer(22));
  e.setUint32(0, 0x06054b50, true); e.setUint16(8, n, true); e.setUint16(10, n, true); e.setUint32(12, cdSize, true); e.setUint32(16, off, true);
  return new Blob([...parts, ...central, new Uint8Array(e.buffer)], { type: "application/zip" });
}
})();
