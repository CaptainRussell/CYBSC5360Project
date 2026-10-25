"""Read-only NTFS reader in pure Python (no extra packages).

It walks a raw NTFS image the same way fat.py walks a FAT image, so the
first-look triage can examine the files of either kind of drive, and it can load
the Master File Table into the case database so the timestamp rules that need
only the MFT (R6, R7, R11) run straight from an image, without other tools.

Scope: uncompressed, unencrypted files and their unnamed $DATA stream; resident
and non-resident data; fragmented files and attributes spread over extension
records; MBR and GPT partition tables or a bare volume. Compressed and EFS files
are listed but their contents are not read. A deleted file's contents are
returned only if none of its clusters has been reused (checked against $Bitmap).
The image is opened read-only and never written.
"""

import struct
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from . import paths

SECTOR = 512
FILETIME_EPOCH = datetime(1601, 1, 1)
ROOT = 5
NTFS_PART_TYPES = {0x07, 0x17, 0x27}
GPT_BASIC_DATA = bytes.fromhex("A2A0D0EBE5B9334487C068B6B72699C7")   # EBD0A0A2-B9E5-4433-87C0-68B6B72699C7

AT_STANDARD_INFORMATION, AT_ATTRIBUTE_LIST, AT_FILE_NAME = 0x10, 0x20, 0x30
AT_VOLUME_NAME, AT_DATA, AT_END = 0x60, 0x80, 0xFFFFFFFF
FLAG_COMPRESSED, FLAG_ENCRYPTED, FLAG_SPARSE = 0x0001, 0x4000, 0x8000
FILE_ATTR_HIDDEN = 0x2
NS_DOS = 2


class NotNTFS(Exception):
    pass


def filetime_dt(ft):
    if not ft:
        return None
    try:
        return FILETIME_EPOCH + timedelta(microseconds=ft // 10)
    except OverflowError:
        return None


@dataclass
class Entry:
    """One file or folder, with the same fields triage reads from a FAT entry."""
    path: str                     # '/Disk/bin/gzip'
    name: str
    size: int
    is_dir: bool
    deleted: bool
    entry: int = 0                # MFT record number
    seq: int = 0
    parent: int = 0
    hidden_attr: bool = False
    si: tuple = (None, None, None, None)     # FILETIMEs: created, modified, record changed, accessed
    fn: tuple = (None, None, None, None)
    data_flags: int = 0
    resident: bytes = None        # unnamed $DATA held inside the record
    runs: list = field(default_factory=list, repr=False)   # [(lcn or None, clusters)]

    @property
    def hidden(self):
        return self.hidden_attr

    @property
    def created(self):
        return filetime_dt(self.si[0])

    @property
    def modified(self):
        return filetime_dt(self.si[1])

    @property
    def accessed(self):
        return filetime_dt(self.si[3])


def find_ntfs_offsets(f):
    """Byte offsets of NTFS volumes: 0 for a bare volume, else from the MBR or GPT."""
    f.seek(0)
    s0 = f.read(SECTOR)
    if len(s0) < SECTOR:
        return []
    if s0[3:11] == b"NTFS    ":
        return [0]
    out = []
    if s0[510:512] == b"\x55\xaa":
        parts = [s0[446 + 16 * i:462 + 16 * i] for i in range(4)]
        if any(p[4] == 0xEE for p in parts):                      # protective MBR: read the GPT
            f.seek(SECTOR)
            hdr = f.read(SECTOR)
            if hdr[:8] == b"EFI PART":
                lba, count, size = struct.unpack("<QII", hdr[72:88])
                f.seek(lba * SECTOR)
                table = f.read(count * size)
                for i in range(count):
                    e = table[i * size:(i + 1) * size]
                    if e[:16] == GPT_BASIC_DATA:
                        out.append(struct.unpack("<Q", e[32:40])[0] * SECTOR)
        else:
            for p in parts:
                lba = struct.unpack("<I", p[8:12])[0]
                if p[4] in NTFS_PART_TYPES and lba:
                    out.append(lba * SECTOR)
    good = []
    for off in out:
        f.seek(off)
        if f.read(11)[3:11] == b"NTFS    ":
            good.append(off)
    return good


def decode_runs(raw):
    """NTFS mapping pairs -> [(lcn or None for a sparse run, length in clusters)]."""
    runs, i, lcn = [], 0, 0
    while i < len(raw) and raw[i]:
        h = raw[i]
        nlen, noff = h & 0x0F, h >> 4
        i += 1
        length = int.from_bytes(raw[i:i + nlen], "little")
        i += nlen
        if noff:
            lcn += int.from_bytes(raw[i:i + noff], "little", signed=True)
            runs.append((lcn, length))
        else:
            runs.append((None, length))
        i += noff
    return runs


def apply_fixups(rec, bps):
    """Undo the update-sequence protection on an MFT record. Returns None if it is damaged."""
    usa_off, usa_count = struct.unpack("<HH", rec[4:8])
    if usa_count < 2 or usa_off + 2 * usa_count > len(rec):
        return None
    rec = bytearray(rec)
    usn = rec[usa_off:usa_off + 2]
    for i in range(1, usa_count):
        end = i * bps
        if end > len(rec):
            break
        if rec[end - 2:end] != usn:
            return None
        rec[end - 2:end] = rec[usa_off + 2 * i:usa_off + 2 * i + 2]
    return bytes(rec)


def parse_attributes(rec):
    """Yield (type, name, non_resident, flags, header_dict, value_or_runs) for each attribute."""
    off = struct.unpack("<H", rec[20:22])[0]
    while off + 16 <= len(rec):
        atype, alen = struct.unpack("<II", rec[off:off + 8])
        if atype == AT_END or alen < 16 or off + alen > len(rec):
            break
        nonres, nlen, noff, flags = rec[off + 8], rec[off + 9], *struct.unpack("<HH", rec[off + 10:off + 14])
        name = rec[off + noff:off + noff + 2 * nlen].decode("utf-16-le", "replace") if nlen else ""
        if nonres:
            start_vcn, _last, roff = struct.unpack("<QQH", rec[off + 16:off + 34])
            alloc, real, init = struct.unpack("<QQQ", rec[off + 40:off + 64])
            hdr = {"start_vcn": start_vcn, "alloc": alloc, "real": real, "init": init}
            yield atype, name, True, flags, hdr, decode_runs(rec[off + roff:off + alen])
        else:
            vlen, voff = struct.unpack("<IH", rec[off + 16:off + 22])
            yield atype, name, False, flags, {}, rec[off + voff:off + voff + vlen]
        off += alen


class NTFSVolume:
    def __init__(self, path, offset=None):
        self.path = path
        self.f = open(path, "rb")   # read-only, never written
        if offset is None:
            offs = find_ntfs_offsets(self.f)
            if not offs:
                self.f.close()
                raise NotNTFS("no NTFS volume found in %s" % path)
            offset = offs[0]
        self.offset = offset
        self._parse_boot()
        self._load_mft()

    def close(self):
        self.f.close()

    def _read(self, pos, n):
        self.f.seek(self.offset + pos)
        return self.f.read(n)

    # ---- boot sector and MFT ---------------------------------------------------

    def _parse_boot(self):
        bs = self._read(0, SECTOR)
        if bs[3:11] != b"NTFS    ":
            raise NotNTFS("bad boot sector")
        self.bps = struct.unpack("<H", bs[11:13])[0]
        spc = bs[13]
        spc = 1 << (256 - spc) if spc > 0x80 else spc
        if self.bps not in (512, 1024, 2048, 4096) or not spc:
            raise NotNTFS("bad boot sector geometry")
        self.cluster_size = self.bps * spc
        total, self.mft_lcn = struct.unpack("<QQ", bs[40:56])
        self.volume_size = total * self.bps
        c = struct.unpack("<b", bs[64:65])[0]
        self.record_size = (1 << -c) if c < 0 else c * self.cluster_size
        self.serial_raw = struct.unpack("<Q", bs[72:80])[0]
        self.oem = bs[3:11].decode("ascii", "replace").strip()

    def _read_runs(self, runs, size):
        out = bytearray()
        for lcn, n in runs:
            want = size - len(out)
            if want <= 0:
                break
            nbytes = min(n * self.cluster_size, want)       # never read past what was asked for
            out += bytes(nbytes) if lcn is None else self._read(lcn * self.cluster_size, nbytes)
        return bytes(out[:size])

    def _load_mft(self):
        rs = self.record_size
        rec0 = apply_fixups(self._read(self.mft_lcn * self.cluster_size, rs), self.bps)
        if not rec0 or rec0[:4] != b"FILE":
            raise NotNTFS("MFT record 0 is unreadable")
        frags, size, ext_refs = [], None, []
        for atype, name, nonres, _fl, hdr, val in parse_attributes(rec0):
            if atype == AT_DATA and not name and nonres:
                frags.append((hdr["start_vcn"], val))
                if hdr["start_vcn"] == 0:
                    size = hdr["real"]
            elif atype == AT_ATTRIBUTE_LIST and not nonres:
                ext_refs += self._attribute_list_records(val, 0)
        runs = [r for _v, rr in sorted(frags) for r in rr]
        # $MFT's own data can continue in extension records listed in its attribute list.
        if ext_refs:
            first = self._read_runs(runs, max(ext_refs) * rs + rs)
            for n in sorted(set(ext_refs)):
                rec = apply_fixups(first[n * rs:(n + 1) * rs], self.bps)
                if rec and rec[:4] == b"FILE":
                    for atype, name, nonres, _fl, hdr, val in parse_attributes(rec):
                        if atype == AT_DATA and not name and nonres and hdr["start_vcn"]:
                            frags.append((hdr["start_vcn"], val))
            runs = [r for _v, rr in sorted(frags) for r in rr]
        self.mft_raw = self._read_runs(runs, size or 0)
        self.n_records = len(self.mft_raw) // rs
        self._parse_records()

    @staticmethod
    def _attribute_list_records(val, own):
        out, i = [], 0
        while i + 26 <= len(val):
            rlen = struct.unpack("<H", val[i + 4:i + 6])[0]
            if rlen < 26:
                break
            ref = struct.unpack("<Q", val[i + 16:i + 24])[0] & 0xFFFFFFFFFFFF
            if ref != own:
                out.append(ref)
            i += rlen
        return out

    def _record(self, n):
        rs = self.record_size
        raw = self.mft_raw[n * rs:(n + 1) * rs]
        if raw[:4] != b"FILE":
            return None
        return apply_fixups(raw, self.bps)

    def _parse_records(self):
        """Parse every record once; merge extension records into their base record."""
        self.records = {}
        extensions = []
        for n in range(self.n_records):
            rec = self._record(n)
            if rec is None:
                continue
            flags = struct.unpack("<H", rec[22:24])[0]
            base = struct.unpack("<Q", rec[32:40])[0] & 0xFFFFFFFFFFFF
            seq = struct.unpack("<H", rec[16:18])[0]
            attrs = list(parse_attributes(rec))
            if base:
                extensions.append((base, attrs))
                continue
            self.records[n] = {"seq": seq, "in_use": bool(flags & 1), "is_dir": bool(flags & 2), "attrs": attrs}
        for base, attrs in extensions:
            if base in self.records:
                self.records[base]["attrs"] += attrs
        self.entries = {}
        for n, r in self.records.items():
            e = self._entry(n, r)
            if e:
                self.entries[n] = e
        self._bitmap = None
        self.label = ""
        vol = self.records.get(3)
        if vol:
            for atype, _name, nonres, _fl, _hdr, val in vol["attrs"]:
                if atype == AT_VOLUME_NAME and not nonres:
                    self.label = val.decode("utf-16-le", "replace")

    def _entry(self, n, r):
        si = fn = None
        best_ns = None
        name, parent, fsize = None, None, 0
        hidden = False
        data_frags, data_size, data_flags, resident = [], None, 0, None
        for atype, aname, nonres, flags, hdr, val in r["attrs"]:
            if atype == AT_STANDARD_INFORMATION and not nonres and len(val) >= 36:
                si = struct.unpack("<QQQQ", val[0:32])
                hidden = bool(struct.unpack("<I", val[32:36])[0] & FILE_ATTR_HIDDEN)
            elif atype == AT_FILE_NAME and not nonres and len(val) >= 66:
                ns = val[65]
                # Prefer the long name (POSIX, Win32, Win32&DOS) over the 8.3 DOS name.
                if best_ns is None or (best_ns == NS_DOS and ns != NS_DOS):
                    best_ns = ns
                    pref = struct.unpack("<Q", val[0:8])[0]
                    parent = pref & 0xFFFFFFFFFFFF
                    fn = struct.unpack("<QQQQ", val[8:40])
                    fsize = struct.unpack("<Q", val[48:56])[0]
                    name = val[66:66 + 2 * val[64]].decode("utf-16-le", "replace")
            elif atype == AT_DATA and not aname:
                data_flags |= flags
                if nonres:
                    data_frags.append((hdr["start_vcn"], val))
                    if hdr["start_vcn"] == 0:
                        data_size = hdr["real"]
                else:
                    resident = bytes(val)
                    data_size = len(val)
        if name is None:
            return None
        runs = [x for _v, rr in sorted(data_frags) for x in rr]
        size = data_size if data_size is not None else (0 if r["is_dir"] else fsize)
        return Entry(path=None, name=name, size=size, is_dir=r["is_dir"], deleted=not r["in_use"], entry=n,
                     seq=r["seq"], parent=parent, hidden_attr=hidden, si=si or (None,) * 4, fn=fn or (None,) * 4,
                     data_flags=data_flags, resident=resident, runs=runs)

    # ---- paths and walking -------------------------------------------------------

    def path_of(self, e, _depth=0):
        if e.path is not None:
            return e.path
        if e.entry == ROOT:
            e.path = "/"
            return e.path
        parent = self.entries.get(e.parent)
        if parent is None or not parent.is_dir or _depth > 256 or e.parent == e.entry:
            base = "/$OrphanFiles"
        else:
            base = self.path_of(parent, _depth + 1).rstrip("/")
        e.path = base + "/" + e.name
        return e.path

    def walk(self):
        """Yield every entry (files and folders, live and deleted) except NTFS's own metadata files."""
        for n in sorted(self.entries):
            e = self.entries[n]
            if n < 24 or n == ROOT:          # $MFT, $Bitmap, $Extend, ... and the root folder itself
                continue
            p = self.path_of(e)
            if p.startswith("/$Extend/") or p == "/$Extend":
                continue
            yield e

    # ---- contents ----------------------------------------------------------------

    def _allocated(self, lcn):
        if self._bitmap is None:
            bm = self.entries.get(6)
            self._bitmap = self._read_runs(bm.runs, bm.size) if bm else b""
        byte = lcn >> 3
        return byte < len(self._bitmap) and bool(self._bitmap[byte] & (1 << (lcn & 7)))

    def readable(self, e):
        """False when the contents cannot be read faithfully (compressed, encrypted, or reused clusters)."""
        if e.data_flags & (FLAG_COMPRESSED | FLAG_ENCRYPTED):
            return False
        if e.deleted and e.resident is None:
            for lcn, n in e.runs:
                if lcn is not None and any(self._allocated(c) for c in range(lcn, lcn + n)):
                    return False      # another file now owns at least one of these clusters
        return True

    def read(self, e, limit=None):
        if e.is_dir or not self.readable(e):
            return b""
        size = e.size if limit is None else min(e.size, limit)
        if e.resident is not None:
            return e.resident[:size]
        return self._read_runs(e.runs, size)

    def summary(self):
        s = self.serial_raw
        return {"fs_type": "NTFS", "label": self.label, "serial": "%04X-%04X" % ((s >> 16) & 0xFFFF, s & 0xFFFF),
                "oem": self.oem, "offset": self.offset, "cluster_size": self.cluster_size,
                "volume_size": self.volume_size}

    # ---- the MFT as the case database's mft table ----------------------------------

    def mft_rows(self):
        """Rows for the mft table, matching what loaders.load_mft makes from MFTECmd's CSV."""
        for n in sorted(self.entries):
            e = self.entries[n]
            parent = self.entries.get(e.parent)
            ppath = "\\" if e.parent == ROOT or parent is None else \
                self.path_of(parent).replace("/", "\\")
            yield (n, e.seq, int(not e.deleted), int(e.is_dir), e.parent, e.name,
                   paths.join_mft_path(ppath, e.name), e.size, *e.si, *e.fn)


def load_mft_from_image(con, image_path):
    """Load an NTFS image's MFT into the case database (kind 'mft'), like loading MFTECmd's CSV."""
    from .loaders import _record_input
    vol = NTFSVolume(image_path)
    rows = list(vol.mft_rows())
    vol.close()
    con.executemany("INSERT OR REPLACE INTO mft VALUES (%s)" % ",".join("?" * 16), rows)
    _record_input(con, "mft", image_path, len(rows))
    return len(rows)
