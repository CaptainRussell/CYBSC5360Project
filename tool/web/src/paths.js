/* Path normalization used to join LNK and Prefetch references to MFT records: a port of ads/paths.py. */

const PATHS = {};
PATHS.ANCHOR_ROOTS = ["\\users\\", "\\windows\\", "\\program files", "\\programdata\\"];
PATHS.normPath = path => {
  if (path == null) return null;
  let p = U.strip(String(path)).split("/").join("\\");
  if (!p) return null;
  if (p.startsWith("\\\\?\\")) p = p.slice(4);
  p = p.replace(/^\\volume\{[^}]*\}/i, "");
  p = p.replace(/^[a-z]:/i, "");
  if (p.startsWith(".")) p = p.slice(1);
  if (!p.startsWith("\\")) p = "\\" + p;
  p = p.replace(/\\+/g, "\\");
  if (p.length > 1) p = U.rstrip(p, "\\");
  return p.toLowerCase();
};
PATHS.joinMftPath = (parentPath, fileName) => {
  const parent = PATHS.normPath(parentPath) || "\\";
  const name = U.strip(fileName || "").toLowerCase();
  return parent === "\\" ? "\\" + name : parent + "\\" + name;
};
PATHS.fromShellPath = path => {
  if (!path) return null;
  const m = /[a-z]:\\/i.exec(path);
  return m ? PATHS.normPath(path.slice(m.index)) : null;
};
PATHS.stripPrefix = (path, prefix) => (path && prefix && path.startsWith(prefix + "\\") ? path.slice(prefix.length) : path);
PATHS.anchorSuffixes = path => {
  if (!path) return [];
  const out = [];
  for (const root of PATHS.ANCHOR_ROOTS) { const i = path.indexOf(root); if (i > 0) out.push(path.slice(i)); }
  return out;
};
PATHS.basename = path => (path ? path.split("/").join("\\").split("\\").pop().toLowerCase() : "");
