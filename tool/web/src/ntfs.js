/* Read-only NTFS reader: a line-for-line port of ads/ntfs.py.
   FILETIMEs (100 ns ticks since 1601) are BigInts: they do not fit a JS number exactly. */

const NTFS = {};
NTFS.SECTOR = 512; NTFS.ROOT = 5;
NTFS.PART_TYPES = new Set([0x07, 0x17, 0x27]);
NTFS.GPT_BASIC_DATA = [0xa2, 0xa0, 0xd0, 0xeb, 0xe5, 0xb9, 0x33, 0x44, 0x87, 0xc0, 0x68, 0xb6, 0xb7, 0x26, 0x99, 0xc7];
const AT_SI = 0x10, AT_LIST = 0x20, AT_FN = 0x30, AT_VOLNAME = 0x60, AT_DATA = 0x80, AT_END = 0xffffffff;
const FLAG_COMPRESSED = 0x0001, FLAG_ENCRYPTED = 0x4000, NS_DOS = 2;
class NotNTFS extends Error {}
NTFS.NotNTFS = NotNTFS;
const NTFS_SIG = [0x4e, 0x54, 0x46, 0x53, 0x20, 0x20, 0x20, 0x20];   // "NTFS    "
const FILE_SIG = [0x46, 0x49, 0x4c, 0x45];

/* FILETIME -> naive UTC Date, or null (0, or beyond year 9999 where Python overflows) */
NTFS.filetimeDate = ft => {
  if (ft == null || ft === 0n) return null;
  const us = ft / 10n, ms = Number(us / 1000n);
  const d = new Date(Date.UTC(1601, 0, 1) + ms);
  if (isNaN(d) || d.getUTCFullYear() > 9999) return null;
  return d;
};

NTFS.findOffsets = src => {
  const S = NTFS.SECTOR, s0 = src.read(0, S);
  if (s0.length < S) return [];
  if (U.eq(s0, 3, NTFS_SIG)) return [0];
  const out = [];
  if (s0[510] === 0x55 && s0[511] === 0xaa) {
    const parts = [0, 1, 2, 3].map(i => s0.subarray(446 + 16 * i, 462 + 16 * i));
    if (parts.some(p => p[4] === 0xee)) {
      const hdr = src.read(S, S);
      if (U.ascii(hdr.subarray(0, 8)) === "EFI PART") {
        const lba = U.u64n(hdr, 72), count = U.u32(hdr, 80), size = U.u32(hdr, 84);
        const table = src.read(lba * S, count * size);
        for (let i = 0; i < count; i++) {
          const e = table.subarray(i * size, (i + 1) * size);
          if (U.eq(e, 0, NTFS.GPT_BASIC_DATA)) { U.need(e, 32, 8); out.push(U.u64n(e, 32) * S); }
        }
      }
    } else {
      for (const p of parts) { const lba = U.u32(p, 8); if (NTFS.PART_TYPES.has(p[4]) && lba) out.push(lba * S); }
    }
  }
  return out.filter(off => U.eq(src.read(off, 11), 3, NTFS_SIG));
};

/* mapping pairs -> [[lcn or null, clusters]] */
NTFS.decodeRuns = raw => {
  const runs = []; let i = 0, lcn = 0n;
  while (i < raw.length && raw[i]) {
    const h = raw[i], nlen = h & 0x0f, noff = h >> 4; i++;
    const length = U.uBig(raw.subarray(i, i + nlen), 0, Math.min(nlen, Math.max(0, raw.length - i))); i += nlen;
    if (noff) {
      const b = raw.subarray(i, i + noff); let v = U.uBig(b, 0, b.length);
      if (b.length && (b[b.length - 1] & 0x80)) v -= 1n << BigInt(8 * b.length);
      lcn += v; runs.push([Number(lcn), Number(length)]);
    } else runs.push([null, Number(length)]);
    i += noff;
  }
  return runs;
};

NTFS.applyFixups = (rec, bps) => {
  U.need(rec, 4, 4);
  const usaOff = U.u16(rec, 4), usaCount = U.u16(rec, 6);
  if (usaCount < 2 || usaOff + 2 * usaCount > rec.length) return null;
  rec = rec.slice();
  const u0 = rec[usaOff], u1 = rec[usaOff + 1];
  for (let i = 1; i < usaCount; i++) {
    const end = i * bps;
    if (end > rec.length) break;
    if (rec[end - 2] !== u0 || rec[end - 1] !== u1) return null;
    rec[end - 2] = rec[usaOff + 2 * i]; rec[end - 1] = rec[usaOff + 2 * i + 1];
  }
  return rec;
};

/* [type, name, nonResident, flags, header, valueOrRuns] for each attribute */
NTFS.parseAttributes = rec => {
  const out = []; U.need(rec, 20, 2);
  let off = U.u16(rec, 20);
  while (off + 16 <= rec.length) {
    const atype = U.u32(rec, off), alen = U.u32(rec, off + 4);
    if (atype === AT_END || alen < 16 || off + alen > rec.length) break;
    const nonres = rec[off + 8], nlen = rec[off + 9], noff = U.u16(rec, off + 10), flags = U.u16(rec, off + 12);
    const name = nlen ? U.utf16(rec.subarray(off + noff, off + noff + 2 * nlen)) : "";
    if (nonres) {
      U.need(rec, off + 16, 18); U.need(rec, off + 40, 24);
      const startVcn = U.u64n(rec, off + 16), roff = U.u16(rec, off + 32);
      const hdr = { start_vcn: startVcn, alloc: U.u64n(rec, off + 40), real: U.u64n(rec, off + 48), init: U.u64n(rec, off + 56) };
      out.push([atype, name, true, flags, hdr, NTFS.decodeRuns(rec.subarray(off + roff, off + alen))]);
    } else {
      U.need(rec, off + 16, 6);
      const vlen = U.u32(rec, off + 16), voff = U.u16(rec, off + 20);
      out.push([atype, name, false, flags, {}, rec.subarray(off + voff, off + voff + vlen)]);
    }
    off += alen;
  }
  return out;
};

const sortedFrags = frags => U.sorted(frags, f => f[0]).flatMap(f => f[1]);

class NTFSVolume {
  constructor(src, offset) {
    this.src = src;
    if (offset == null) {
      const offs = NTFS.findOffsets(src);
      if (!offs.length) throw new NotNTFS("no NTFS volume found");
      offset = offs[0];
    }
    this.offset = offset;
    this.parseBoot();
    this.loadMft();
  }
  close() {}
  _read(pos, n) { return this.src.read(this.offset + pos, n); }
  parseBoot() {
    const bs = this._read(0, NTFS.SECTOR);
    if (!U.eq(bs, 3, NTFS_SIG)) throw new NotNTFS("bad boot sector");
    this.bps = U.u16(bs, 11);
    let spc = bs[13]; spc = spc > 0x80 ? 2 ** (256 - spc) : spc;
    if (![512, 1024, 2048, 4096].includes(this.bps) || !spc) throw new NotNTFS("bad boot sector geometry");
    this.cluster_size = this.bps * spc;
    U.need(bs, 40, 16);
    const total = U.u64n(bs, 40); this.mft_lcn = U.u64n(bs, 48);
    this.volume_size = total * this.bps;
    U.need(bs, 64, 1);
    const c = U.i8(bs, 64);
    this.record_size = c < 0 ? 2 ** -c : c * this.cluster_size;
    U.need(bs, 72, 8);
    this.serial_raw = U.u64(bs, 72);
    this.oem = U.strip(U.ascii(bs.subarray(3, 11)));
  }
  readRuns(runs, size) {
    const parts = []; let got = 0;
    for (const [lcn, n] of runs) {
      const want = size - got;
      if (want <= 0) break;
      const nbytes = Math.min(n * this.cluster_size, want);
      const b = lcn === null ? new Uint8Array(nbytes) : this._read(lcn * this.cluster_size, nbytes);
      parts.push(b); got += b.length;
    }
    const all = U.concat(parts);
    return all.length > size ? all.subarray(0, size) : all;
  }
  loadMft() {
    const rs = this.record_size;
    const rec0 = NTFS.applyFixups(this._read(this.mft_lcn * this.cluster_size, rs), this.bps);
    if (!rec0 || !U.eq(rec0, 0, FILE_SIG)) throw new NotNTFS("MFT record 0 is unreadable");
    let frags = [], size = null, extRefs = [];
    for (const [atype, name, nonres, , hdr, val] of NTFS.parseAttributes(rec0)) {
      if (atype === AT_DATA && !name && nonres) { frags.push([hdr.start_vcn, val]); if (hdr.start_vcn === 0) size = hdr.real; }
      else if (atype === AT_LIST && !nonres) extRefs = extRefs.concat(NTFS.attributeListRecords(val, 0));
    }
    let runs = sortedFrags(frags);
    if (extRefs.length) {
      const first = this.readRuns(runs, Math.max(...extRefs) * rs + rs);
      for (const n of [...new Set(extRefs)].sort((a, b) => a - b)) {
        const raw = first.subarray(n * rs, (n + 1) * rs);
        const rec = raw.length >= 8 ? NTFS.applyFixups(raw, this.bps) : null;
        if (rec && U.eq(rec, 0, FILE_SIG)) {
          for (const [atype, name, nonres, , hdr, val] of NTFS.parseAttributes(rec))
            if (atype === AT_DATA && !name && nonres && hdr.start_vcn) frags.push([hdr.start_vcn, val]);
        }
      }
      runs = sortedFrags(frags);
    }
    this.mft_raw = this.readRuns(runs, size || 0);
    this.n_records = Math.floor(this.mft_raw.length / rs);
    this.parseRecords();
  }
  static attributeListRecords(val, own) { return NTFS.attributeListRecords(val, own); }
  record(n) {
    const rs = this.record_size, raw = this.mft_raw.subarray(n * rs, (n + 1) * rs);
    if (!U.eq(raw, 0, FILE_SIG)) return null;
    return NTFS.applyFixups(raw, this.bps);
  }
  parseRecords() {
    this.records = new Map();
    const extensions = [];
    for (let n = 0; n < this.n_records; n++) {
      const rec = this.record(n);
      if (rec === null) continue;
      U.need(rec, 16, 24);
      const flags = U.u16(rec, 22), base = Number(U.u64(rec, 32) & 0xffffffffffffn), seq = U.u16(rec, 16);
      const attrs = NTFS.parseAttributes(rec);
      if (base) { extensions.push([base, attrs]); continue; }
      this.records.set(n, { seq, in_use: !!(flags & 1), is_dir: !!(flags & 2), attrs });
    }
    for (const [base, attrs] of extensions) { const r = this.records.get(base); if (r) r.attrs = r.attrs.concat(attrs); }
    this.entries = new Map();
    for (const [n, r] of this.records) { const e = this.entry(n, r); if (e) this.entries.set(n, e); }
    this.keys = [...this.entries.keys()].sort((a, b) => a - b);
    this._bitmap = null;
    this.label = "";
    const vol = this.records.get(3);
    if (vol) for (const [atype, , nonres, , , val] of vol.attrs)
      if (atype === AT_VOLNAME && !nonres) this.label = U.rstrip(U.utf16(val), "\x00 ");
  }
  entry(n, r) {
    let si = null, fn = null, bestNs = null, name = null, parent = null, fsize = 0, hidden = false;
    const dataFrags = []; let dataSize = null, dataFlags = 0, resident = null;
    for (const [atype, aname, nonres, flags, hdr, val] of r.attrs) {
      if (atype === AT_SI && !nonres && val.length >= 36) {
        si = [U.u64(val, 0), U.u64(val, 8), U.u64(val, 16), U.u64(val, 24)];
        hidden = !!(U.u32(val, 32) & 2);
      } else if (atype === AT_FN && !nonres && val.length >= 66) {
        const ns = val[65];
        if (bestNs === null || (bestNs === NS_DOS && ns !== NS_DOS)) {
          bestNs = ns;
          parent = Number(U.u64(val, 0) & 0xffffffffffffn);
          fn = [U.u64(val, 8), U.u64(val, 16), U.u64(val, 24), U.u64(val, 32)];
          fsize = U.u64n(val, 48);
          name = U.utf16(val.subarray(66, 66 + 2 * val[64]));
        }
      } else if (atype === AT_DATA && !aname) {
        dataFlags |= flags;
        if (nonres) { dataFrags.push([hdr.start_vcn, val]); if (hdr.start_vcn === 0) dataSize = hdr.real; }
        else { resident = val.slice(); dataSize = val.length; }
      }
    }
    if (name === null) return null;
    const size = dataSize !== null ? dataSize : (r.is_dir ? 0 : fsize);
    const SI = si || [null, null, null, null];
    return { path: null, name, size, is_dir: r.is_dir, deleted: !r.in_use, entry: n, seq: r.seq, parent, hidden,
      si: SI, fn: fn || [null, null, null, null], data_flags: dataFlags, resident, runs: sortedFrags(dataFrags),
      get created() { return NTFS.filetimeDate(SI[0]); }, get modified() { return NTFS.filetimeDate(SI[1]); },
      get accessed() { return NTFS.filetimeDate(SI[3]); } };
  }
  pathOf(e, depth) {
    depth = depth || 0;
    if (e.path !== null) return e.path;
    if (e.entry === NTFS.ROOT) { e.path = "/"; return e.path; }
    const parent = this.entries.get(e.parent);
    let base;
    if (!parent || !parent.is_dir || depth > 256 || e.parent === e.entry) base = "/$OrphanFiles";
    else base = U.rstrip(this.pathOf(parent, depth + 1), "/");
    e.path = base + "/" + e.name;
    return e.path;
  }
  *walk() {
    for (const n of this.keys) {
      const e = this.entries.get(n);
      if (n < 24 || n === NTFS.ROOT) continue;
      const p = this.pathOf(e);
      if (p.startsWith("/$Extend/") || p === "/$Extend") continue;
      yield e;
    }
  }
  allocated(lcn) {
    if (this._bitmap === null) { const bm = this.entries.get(6); this._bitmap = bm ? this.readRuns(bm.runs, bm.size) : new Uint8Array(0); }
    const byte = Math.floor(lcn / 8);
    return byte < this._bitmap.length && !!(this._bitmap[byte] & (1 << (lcn & 7)));
  }
  readable(e) {
    if (e.data_flags & (FLAG_COMPRESSED | FLAG_ENCRYPTED)) return false;
    if (e.deleted && e.resident === null) {
      for (const [lcn, n] of e.runs) {
        if (lcn === null) continue;
        for (let c = lcn; c < lcn + n; c++) if (this.allocated(c)) return false;
      }
    }
    return true;
  }
  read(e, limit) {
    if (e.is_dir || !this.readable(e)) return new Uint8Array(0);
    const size = limit == null ? e.size : Math.min(e.size, limit);
    if (e.resident !== null) return e.resident.subarray(0, size);
    return this.readRuns(e.runs, size);
  }
  position(e) {
    const r = e.runs.find(x => x[0] !== null);
    return r ? r[0] * this.cluster_size / Math.max(1, this.volume_size) : (e.resident ? this.mft_lcn * this.cluster_size / Math.max(1, this.volume_size) : null);
  }
  summary() {
    const s = this.serial_raw, h = x => Number(x).toString(16).toUpperCase().padStart(4, "0");
    return { fs_type: "NTFS", label: this.label, serial: h((s >> 16n) & 0xffffn) + "-" + h(s & 0xffffn), oem: this.oem,
      offset: this.offset, cluster_size: this.cluster_size, volume_size: this.volume_size };
  }
  /* rows for the date checks' mft table, as loaders.load_mft would make them from MFTECmd's CSV */
  *mftRows() {
    for (const n of this.keys) {
      const e = this.entries.get(n), parent = this.entries.get(e.parent);
      const ppath = e.parent === NTFS.ROOT || !parent ? "\\" : this.pathOf(parent).split("/").join("\\");
      yield { entry: n, seq: e.seq, in_use: e.deleted ? 0 : 1, is_dir: e.is_dir ? 1 : 0, parent_entry: e.parent, name: e.name,
        path: PATHS.joinMftPath(ppath, e.name), size: e.size,
        si_c: e.si[0], si_m: e.si[1], si_e: e.si[2], si_a: e.si[3], fn_c: e.fn[0], fn_m: e.fn[1], fn_e: e.fn[2], fn_a: e.fn[3] };
    }
  }
}
NTFS.attributeListRecords = (val, own) => {
  const out = []; let i = 0;
  while (i + 26 <= val.length) {
    const rlen = U.u16(val, i + 4);
    if (rlen < 26) break;
    const ref = Number(U.u64(val, i + 16) & 0xffffffffffffn);
    if (ref !== own) out.push(ref);
    i += rlen;
  }
  return out;
};
NTFS.NTFSVolume = NTFSVolume;
