/* The analysis runs here, in a Web Worker, so the page stays smooth while a 1 GB image
   is read. The image is read straight from the user's disk with FileReaderSync: nothing
   is uploaded, and the file is never written. Progress is sent back in small batches
   so the page can draw the analysis as it happens. */

const fr = new FileReaderSync();
const fileSrc = file => ({ name: file.name, size: file.size, read(pos, n) {
  pos = Math.max(0, pos); const end = Math.min(file.size, pos + Math.max(0, n));
  return end > pos ? new Uint8Array(fr.readAsArrayBuffer(file.slice(pos, end))) : new Uint8Array(0);
} });

/* batch high-rate events, flushing at most every 60 ms */
let pend = {}, last = 0;
const flush = force => {
  const now = Date.now();
  if (!force && now - last < 60) return;
  last = now;
  for (const [ev, v] of Object.entries(pend)) postMessage(Object.assign({ ev }, v));
  pend = {};
};
const queue = (ev, item, extra) => { const p = pend[ev] || (pend[ev] = { batch: [] }); if (item) p.batch.push(item); Object.assign(p, extra); flush(false); };

function firstLook(file) {
  const src = fileSrc(file);
  const head = src.read(0, 16);
  if (U.ascii(head.subarray(0, 3)) === "EVF") throw new TRI.UnsupportedImage("This is an EnCase evidence file (E01). Export it to a raw image (.dd or .img) first, for example with FTK Imager's 'Export Disk Image', then drop that here.");
  const counts = { C1: 0, C2: 0, C3: 0, C4: 0, C5: 0, C6: 0, C7: 0, F1: 0 };
  let t;
  const on = (ev, v) => {
    if (ev === "item") {
      const i = v.item;
      queue("items", { p: i.path, t: i.type, f: i.family, noise: !!i.noise, pos: v.pos, z: i.container !== null }, { n: v.n });
    } else if (ev === "checked") {
      const i = v.item;
      for (const rid of Object.keys(i.outcomes)) if (i.outcomes[rid][0] === "violated") {
        counts[rid]++;
        queue("hits", { p: i.path, rid, say: i.outcomes[rid][1].say || "" }, { counts, n: v.n, total: v.total });
      }
      queue("checked", null, { n: v.n, total: v.total, counts });
    } else if (ev === "stage") { flush(true); postMessage({ ev: "stage", stage: v.stage, total: v.total, rates: v.rates }); }
  };
  t = new TRI.Triage(src, { on, cacheBudget: 256 << 20 });
  postMessage({ ev: "volume", summary: t.vol.summary(), boot_hex: U.hex(t.vol._read(0, 512)), name: file.name, size: file.size });
  postMessage({ ev: "stage", stage: "read" });
  t.collect();
  flush(true);
  t.run();
  flush(true);
  const leads = t.leads().slice(0, 12).map(i => ({ p: i.path, score: i.score, fired: i.fired }));
  postMessage({ ev: "leads", leads, total: t.leads().length, examined: t.items.filter(i => !i.noise).length });
  postMessage({ ev: "stage", stage: "hash" });
  const sha = t.sha256((done, total) => { if (Date.now() - last > 80) { last = Date.now(); postMessage({ ev: "hash", done, total }); } });
  postMessage({ ev: "hash", done: src.size, total: src.size, hex: sha });
  const data = t.toJson(40, sha);
  postMessage({ ev: "firstlook", data, leads_csv: t.leadsCsv(data), notes: t.notes });
  return { t, sha, src };
}

function dateChecks(inputs) {
  const cfg = DATES.defaults();
  postMessage({ ev: "stage", stage: "dates" });
  const counts = {}; for (const r of PYDATA.config.RULE_IDS) counts[r] = 0;
  const db = DATES.ingest(inputs, cfg, (ev, v) => postMessage({ ev: "dates_loaded", kind: v.kind, file: v.file, rows: v.rows }));
  const out = DATES.analyze(db, cfg, { selfCalibrate: true, on: (ev, v) => {
    if (ev === "rules") postMessage({ ev: "dates_progress", n: v.n, total: v.total });
    if (ev === "stage") postMessage({ ev: "dates_stage", stage: v.stage, total: v.total });
  } });
  postMessage({ ev: "dates", data: out.data, files: out.files, summary: out.summary });
}

onmessage = e => {
  const m = e.data;
  try {
    if (m.cmd === "image") {
      const r = firstLook(m.file);
      if (r.t.vol instanceof NTFS.NTFSVolume) dateChecks([{ kind: "image", name: m.file.name, src: r.src, vol: r.t.vol, sha256: r.sha }]);
      postMessage({ ev: "done" });
    } else if (m.cmd === "records") {
      dateChecks(m.files.map(f => ({ kind: "csv", name: f.name, src: fileSrc(f) })));
      postMessage({ ev: "done" });
    }
  } catch (err) {
    flush(true);
    postMessage({ ev: "error", message: err && err.message ? err.message : String(err), unsupported: err instanceof TRI.UnsupportedImage || err instanceof DATES.InputError });
  }
};
