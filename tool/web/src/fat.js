/* Read-only FAT12/16/32 reader: a line-for-line port of ads/fat.py.

   FAT stores no time zone, so times are naive: kept here as Date objects whose
   UTC fields hold the local clock that was written. */

const FAT = {};
FAT.ATTR_HIDDEN = 2; FAT.ATTR_VOLUME = 8; FAT.ATTR_DIR = 16; FAT.ATTR_LFN = 0x0f;
FAT.PART_TYPES = new Set([0x01, 0x04, 0x06, 0x0b, 0x0c, 0x0e]);
class NotFAT extends Error {}
FAT.NotFAT = NotFAT;

FAT.fatDate = d => {
  if (!d) return null;
  const y = 1980 + (d >> 9), m = (d >> 5) & 15, day = d & 31;
  return U.validDate(y, m, day) ? U.utcDate(y, m, day) : null;
};
FAT.fatDatetime = (d, t, tenths) => {
  const day = FAT.fatDate(d);
  if (day === null) return null;
  t = t || 0; tenths = tenths || 0;
  const h = t >> 11, mi = (t >> 5) & 63, s = (t & 31) * 2;
  if (h > 23 || mi > 59 || s > 59) return day;
  return new Date(day.getTime() + ((h * 60 + mi) * 60 + s) * 1000 + 10 * tenths);
};

FAT.findOffsets = src => {
  const s0 = src.read(0, 512);
  if (s0.length < 512) return [];
  const t = U.ascii(s0.subarray(54, 59));
  if (t === "FAT12" || t === "FAT16" || U.ascii(s0.subarray(82, 87)) === "FAT32") return [0];
  const out = [];
  if (s0[510] === 0x55 && s0[511] === 0xaa) {
    for (let i = 0; i < 4; i++) {
      const o = 446 + 16 * i, ptype = s0[o + 4], lba = U.u32(s0, o + 8);
      if (FAT.PART_TYPES.has(ptype) && lba) out.push(lba * 512);
    }
  }
  return out;
};

class FATVolume {
  constructor(src, offset) {
    this.src = src;
    if (offset == null) {
      const offs = FAT.findOffsets(src);
      if (!offs.length) throw new NotFAT("no FAT volume found");
      offset = offs[0];
    }
    this.offset = offset;
    this.parseBoot();
    this.loadFat();
  }
  close() {}
  _read(pos, n) { return this.src.read(this.offset + pos, n); }
  parseBoot() {
    const bs = this._read(0, 512);
    U.need(bs, 11, 25);
    this.bps = U.u16(bs, 11); this.spc = bs[13]; this.reserved = U.u16(bs, 14); this.nfats = bs[16];
    this.root_entries = U.u16(bs, 17); const tot16 = U.u16(bs, 19); this.media = bs[21];
    const fatsz16 = U.u16(bs, 22), tot32 = U.u32(bs, 32);
    if (![512, 1024, 2048, 4096].includes(this.bps) || !this.spc) throw new NotFAT("bad boot sector");
    U.need(bs, 36, 4);
    const fatsz = fatsz16 || U.u32(bs, 36), total = tot16 || tot32;
    const rootSecs = Math.floor((this.root_entries * 32 + this.bps - 1) / this.bps);
    this.fat_start = this.reserved * this.bps;
    this.root_start = (this.reserved + this.nfats * fatsz) * this.bps;
    this.data_start = this.root_start + rootSecs * this.bps;
    this.cluster_size = this.spc * this.bps;
    const clusters = Math.floor((total - (this.reserved + this.nfats * fatsz + rootSecs)) / this.spc);
    this.n_clusters = clusters;
    this.fat_type = clusters < 4085 ? 12 : clusters < 65525 ? 16 : 32;
    this.fat_bytes = fatsz * this.bps;
    this.volume_size = total * this.bps;
    let label, serial;
    if (this.fat_type === 32) {
      this.root_cluster = U.u32(bs, 44);
      label = bs.subarray(71, 82); serial = U.u32(bs, 67);
      this.fs_label = U.strip(U.ascii(bs.subarray(82, 90)));
    } else {
      this.root_cluster = null;
      label = bs.subarray(43, 54); serial = U.u32(bs, 39);
      this.fs_label = U.strip(U.ascii(bs.subarray(54, 62)));
    }
    this.label = U.strip(U.ascii(label));
    const h = x => x.toString(16).toUpperCase().padStart(4, "0");
    this.serial = h(serial >>> 16) + "-" + h(serial & 0xffff);
    this.oem = U.strip(U.ascii(bs.subarray(3, 11)));
  }
  loadFat() {
    const raw = this._read(this.fat_start, this.fat_bytes);
    if (this.fat_type === 16) {
      const n = raw.length >> 1; this.fat = new Uint32Array(n);
      for (let i = 0; i < n; i++) this.fat[i] = raw[2 * i] | (raw[2 * i + 1] << 8);
      this.eoc = 0xfff8;
    } else if (this.fat_type === 32) {
      const n = raw.length >> 2; this.fat = new Uint32Array(n);
      for (let i = 0; i < n; i++) this.fat[i] = U.u32(raw, 4 * i) & 0x0fffffff;
      this.eoc = 0x0ffffff8;
    } else {
      const n = Math.floor(raw.length * 2 / 3); this.fat = new Uint32Array(n);
      for (let i = 0; i < n; i++) {
        const o = Math.floor(i * 3 / 2); U.need(raw, o, 2);
        const v = raw[o] | (raw[o + 1] << 8);
        this.fat[i] = i & 1 ? v >> 4 : v & 0xfff;
      }
      this.eoc = 0xff8;
    }
  }
  chain(first) {
    const out = [], seen = new Set(); let c = first;
    while (c >= 2 && c < this.fat.length && c < this.eoc && !seen.has(c) && out.length <= this.n_clusters) {
      seen.add(c); out.push(c); c = this.fat[c];
    }
    return out;
  }
  clusterOffset(c) { return this.data_start + (c - 2) * this.cluster_size; }
  /* Contiguous clusters are read in one go; the bytes are the same as cluster by cluster. */
  readClusters(clusters, size) {
    const parts = []; let got = 0, i = 0;
    while (i < clusters.length) {
      let j = i + 1; while (j < clusters.length && clusters[j] === clusters[j - 1] + 1) j++;
      let n = j - i;
      if (size != null) n = Math.min(n, Math.ceil((size - got) / this.cluster_size));
      const b = this._read(this.clusterOffset(clusters[i]), n * this.cluster_size);
      parts.push(b); got += b.length;
      if (size != null && got >= size) break;
      if (b.length < n * this.cluster_size) {   // ran off the end of the image: Python keeps reading (empty) clusters
        i += n; continue;
      }
      i += n;
    }
    const all = U.concat(parts);
    return size == null ? all : all.subarray(0, size);
  }
  read(e, limit) {
    const size = limit == null ? e.size : Math.min(e.size, limit);
    if (e.first_cluster < 2 || size === 0) return new Uint8Array(0);
    if (e.deleted) {
      const need = Math.floor((size + this.cluster_size - 1) / this.cluster_size), cl = [];
      for (let c = e.first_cluster; c < e.first_cluster + need; c++) {
        if (c >= this.fat.length || this.fat[c] !== 0) return new Uint8Array(0);   // reused since deletion
        cl.push(c);
      }
      return this.readClusters(cl, size);
    }
    return this.readClusters(this.chain(e.first_cluster), size);
  }
  dirBytes(first) {
    if (first == null) return [this._read(this.root_start, this.root_entries * 32), this.root_start];
    return [this.readClusters(this.chain(first)), null];
  }
  parseDir(data, baseOffset, parentPath, deletedParent) {
    const entries = []; let lfn = [];
    for (let i = 0; i < data.length - 31; i += 32) {
      const raw = data.subarray(i, i + 32), first = raw[0];
      if (first === 0x00) break;
      const attr = raw[11];
      if (attr === FAT.ATTR_LFN) {
        const seq = raw[0];
        let part = U.utf16(U.concat([raw.subarray(1, 11), raw.subarray(14, 26), raw.subarray(28, 32)]));
        part = part.split("\x00")[0].split("￿").join("");
        if (first !== 0xe5 && (seq & 0x40)) lfn = [part]; else lfn.push(part);
        continue;
      }
      if (attr & FAT.ATTR_VOLUME) { lfn = []; continue; }
      const deleted = first === 0xe5 || !!deletedParent;
      const base = raw.slice(0, 8);
      if (first === 0x05) base[0] = 0xe5;
      if (first === 0xe5) base[0] = 0x5f;
      let stem = U.rstrip(U.cp437(base)), ext = U.rstrip(U.cp437(raw.subarray(8, 11)));
      if (raw[12] & 0x08) stem = stem.toLowerCase();
      if (raw[12] & 0x10) ext = ext.toLowerCase();
      const short = stem + (ext ? "." + ext : "");
      const longName = lfn.length ? lfn.slice().reverse().join("") : null;
      lfn = [];
      const name = longName || short;
      if (name === "." || name === "..") continue;
      const ctenths = raw[13], ctime = U.u16(raw, 14), cdate = U.u16(raw, 16), adate = U.u16(raw, 18), hi = U.u16(raw, 20);
      const wtime = U.u16(raw, 22), wdate = U.u16(raw, 24), lo = U.u16(raw, 26), size = U.u32(raw, 28);
      const cluster = lo | (this.fat_type === 32 ? hi * 65536 : 0);
      const e = {
        path: U.rstrip(parentPath, "/") + "/" + name, name, short_name: short, size, attr,
        is_dir: !!(attr & FAT.ATTR_DIR), deleted,
        created: FAT.fatDatetime(cdate, ctime, ctenths), modified: FAT.fatDatetime(wdate, wtime),
        accessed: FAT.fatDate(adate), first_cluster: cluster, hidden: !!(attr & FAT.ATTR_HIDDEN),
      };
      if (e.is_dir) e.size = 0;
      entries.push(e);
    }
    return entries;
  }
  *walk() {
    const [rootData, rootOff] = this.dirBytes(this.root_cluster);
    const stack = [this.parseDir(rootData, rootOff, "/")], seen = new Set();
    while (stack.length) {
      const entries = stack.pop();
      for (const e of entries) {
        yield e;
        if (e.is_dir && e.first_cluster >= 2 && !e.deleted && !seen.has(e.first_cluster)) {
          seen.add(e.first_cluster);
          const [data] = this.dirBytes(e.first_cluster);
          stack.push(this.parseDir(data, null, e.path));
        }
      }
    }
  }
  /* where each file's data starts, as a share of the volume (for the live disk map) */
  position(e) { return e.first_cluster >= 2 ? (this.clusterOffset(e.first_cluster) / Math.max(1, this.volume_size)) : null; }
  summary() {
    return { fs_type: "FAT" + this.fat_type, label: this.label, serial: this.serial, oem: this.oem, offset: this.offset,
      cluster_size: this.cluster_size, volume_size: this.volume_size };
  }
}
FAT.FATVolume = FATVolume;
