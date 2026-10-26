/* Run the browser engine in Node: node run.js ENGINE.js triage IMAGE OUT.json
   (the tests build ENGINE.js with ads.webapp.engine_js). */
const fs = require("fs"), vm = require("vm");
const [engineFile, mode, ...args] = process.argv.slice(2);
const ctx = { console, TextDecoder, Uint8Array, Uint16Array, Uint32Array, DataView, ArrayBuffer, Map, Set, BigInt, Math, JSON, Date, Number, String, Object, Array, Error, RangeError, TypeError, isNaN, isFinite, parseInt, Infinity, NaN, Symbol, RegExp };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(engineFile, "utf8") + "\n;globalThis.__E = {U, FAT, NTFS, SNIFF, TRI, PATHS, PYDATA, DATES: typeof DATES !== 'undefined' ? DATES : null, DREP: typeof DREP !== 'undefined' ? DREP : null};", ctx);
const E = ctx.__E;
function fileSrc(path) {
  const fd = fs.openSync(path, "r"), size = fs.fstatSync(fd).size, name = require("path").basename(path);
  return { name, size, read(pos, n) { pos = Math.max(0, pos); n = Math.max(0, Math.min(n, size - pos)); const b = new Uint8Array(n); if (n) fs.readSync(fd, b, 0, n, pos); return b; } };
}
const replacer = (k, v) => (typeof v === "bigint" ? v.toString() : v);
if (mode === "triage") {
  const t = new E.TRI.Triage(fileSrc(args[0]));
  t.collect().run();
  const data = t.toJson(40);
  fs.writeFileSync(args[1], JSON.stringify({ data, leads_csv: t.leadsCsv(data), notes: t.notes }, replacer));
} else if (mode === "dates") {
  const res = E.DATES.runFromArgs(args.slice(0, -1).map(a => { const [kind, p] = a.split("="); return { kind, src: fileSrc(p), text: kind === "image" ? null : fs.readFileSync(p, "utf8"), name: require("path").basename(p) }; }));
  fs.writeFileSync(args[args.length - 1], JSON.stringify(res, replacer));
} else if (mode === "eval") {
  console.log(vm.runInContext(args[0], ctx));
}
