"""Read-only FAT12/16/32 reader for raw disk images (no mounting, no external tools).

FAT stores no time zone: every time below is the local clock of the machine that
wrote it, kept as a naive datetime. Deleted entries (first byte 0xE5) are listed
with their content recovered from contiguous clusters, the usual best effort
once the cluster chain has been cleared.
"""

import struct
from dataclasses import dataclass, field
from datetime import datetime, timedelta

ATTR_RO, ATTR_HIDDEN, ATTR_SYSTEM, ATTR_VOLUME, ATTR_DIR, ATTR_ARCHIVE = 1, 2, 4, 8, 16, 32
ATTR_LFN = 0x0F
FAT_PART_TYPES = {0x01, 0x04, 0x06, 0x0B, 0x0C, 0x0E}


class NotFAT(Exception):
    pass


@dataclass
class Entry:
    path: str                 # '/docs/Manual.docx'
    name: str
    short_name: str
    size: int
    attr: int
    is_dir: bool
    deleted: bool
    created: datetime = None
    modified: datetime = None
    accessed: datetime = None
    first_cluster: int = 0
    entry_offset: int = 0     # byte offset of the 8.3 entry in the image
    children: list = field(default_factory=list, repr=False)

    @property
    def hidden(self):
        return bool(self.attr & ATTR_HIDDEN)


def _fat_date(d):
    if not d:
        return None
    try:
        return datetime(1980 + (d >> 9), (d >> 5) & 15, d & 31)
    except ValueError:
        return None


def _fat_datetime(d, t=0, tenths=0):
    day = _fat_date(d)
    if day is None:
        return None
    try:
        return day.replace(hour=t >> 11, minute=(t >> 5) & 63, second=(t & 31) * 2) + timedelta(milliseconds=10 * tenths)
    except ValueError:
        return day


def find_fat_offsets(f):
    """Byte offsets of FAT volumes: the MBR's FAT partitions, or 0 for a bare volume."""
    f.seek(0)
    s0 = f.read(512)
    if len(s0) < 512:
        return []
    if s0[54:59] in (b"FAT12", b"FAT16") or s0[82:87] == b"FAT32":
        return [0]
    out = []
    if s0[510:512] == b"\x55\xaa":
        for i in range(4):
            e = s0[446 + 16 * i:462 + 16 * i]
            ptype, lba = e[4], struct.unpack("<I", e[8:12])[0]
            if ptype in FAT_PART_TYPES and lba:
                out.append(lba * 512)
    return out


class FATVolume:
    def __init__(self, path, offset=None):
        self.path = path
        self.f = open(path, "rb")   # read-only, never written
        if offset is None:
            offs = find_fat_offsets(self.f)
            if not offs:
                raise NotFAT("no FAT volume found in %s" % path)
            offset = offs[0]
        self.offset = offset
        self._parse_boot()
        self._load_fat()

    def close(self):
        self.f.close()

    def _read(self, pos, n):
        self.f.seek(self.offset + pos)
        return self.f.read(n)

    def _parse_boot(self):
        bs = self._read(0, 512)
        (self.bps, self.spc, self.reserved, self.nfats, self.root_entries, tot16, self.media,
         fatsz16, _spt, _heads, _hidden, tot32) = struct.unpack("<HBHBHHBHHHII", bs[11:36])
        if self.bps not in (512, 1024, 2048, 4096) or not self.spc:
            raise NotFAT("bad boot sector")
        fatsz = fatsz16 or struct.unpack("<I", bs[36:40])[0]
        total = tot16 or tot32
        root_secs = (self.root_entries * 32 + self.bps - 1) // self.bps
        self.fat_start = self.reserved * self.bps
        self.root_start = (self.reserved + self.nfats * fatsz) * self.bps
        self.data_start = self.root_start + root_secs * self.bps
        self.cluster_size = self.spc * self.bps
        clusters = (total - (self.reserved + self.nfats * fatsz + root_secs)) // self.spc
        self.n_clusters = clusters
        self.fat_type = 12 if clusters < 4085 else 16 if clusters < 65525 else 32
        self.fat_bytes = fatsz * self.bps
        self.volume_size = total * self.bps
        if self.fat_type == 32:
            self.root_cluster = struct.unpack("<I", bs[44:48])[0]
            label, serial = bs[71:82], struct.unpack("<I", bs[67:71])[0]
            self.fs_label = bs[82:90].decode("ascii", "replace").strip()
        else:
            self.root_cluster = None
            label, serial = bs[43:54], struct.unpack("<I", bs[39:43])[0]
            self.fs_label = bs[54:62].decode("ascii", "replace").strip()
        self.label = label.decode("ascii", "replace").strip()
        self.serial = "%04X-%04X" % (serial >> 16, serial & 0xFFFF)
        self.oem = bs[3:11].decode("ascii", "replace").strip()

    def _load_fat(self):
        raw = self._read(self.fat_start, self.fat_bytes)
        if self.fat_type == 16:
            self.fat = list(struct.unpack("<%dH" % (len(raw) // 2), raw))
            self.eoc = 0xFFF8
        elif self.fat_type == 32:
            self.fat = [v & 0x0FFFFFFF for v in struct.unpack("<%dI" % (len(raw) // 4), raw)]
            self.eoc = 0x0FFFFFF8
        else:
            self.fat = []
            for i in range(len(raw) * 2 // 3):
                v = struct.unpack("<H", raw[i * 3 // 2:i * 3 // 2 + 2])[0]
                self.fat.append(v >> 4 if i & 1 else v & 0xFFF)
            self.eoc = 0xFF8

    def chain(self, first):
        out, seen, c = [], set(), first
        while 2 <= c < len(self.fat) and c < self.eoc and c not in seen and len(out) <= self.n_clusters:
            seen.add(c)
            out.append(c)
            c = self.fat[c]
        return out

    def cluster_offset(self, c):
        return self.data_start + (c - 2) * self.cluster_size

    def read_clusters(self, clusters, size=None):
        buf = bytearray()
        for c in clusters:
            buf += self._read(self.cluster_offset(c), self.cluster_size)
            if size is not None and len(buf) >= size:
                break
        return bytes(buf if size is None else buf[:size])

    def read(self, e, limit=None):
        """File content (deleted files: contiguous clusters from the first one, if still free)."""
        size = e.size if limit is None else min(e.size, limit)
        if e.first_cluster < 2 or size == 0:
            return b""
        if e.deleted:
            need = (size + self.cluster_size - 1) // self.cluster_size
            clusters = list(range(e.first_cluster, e.first_cluster + need))
            if any(c >= len(self.fat) or self.fat[c] != 0 for c in clusters):
                return b""   # clusters reused since deletion
            return self.read_clusters(clusters, size)
        return self.read_clusters(self.chain(e.first_cluster), size)

    def _dir_bytes(self, first_cluster):
        if first_cluster is None:
            return self._read(self.root_start, self.root_entries * 32), self.root_start
        clusters = self.chain(first_cluster)
        return self.read_clusters(clusters), None

    def _parse_dir(self, data, base_offset, parent_path, deleted_parent=False):
        entries, lfn = [], []
        for i in range(0, len(data) - 31, 32):
            raw = data[i:i + 32]
            first = raw[0]
            if first == 0x00:
                break
            attr = raw[11]
            if attr == ATTR_LFN:
                seq = raw[0]
                part = (raw[1:11] + raw[14:26] + raw[28:32]).decode("utf-16-le", "replace")
                part = part.split("\x00")[0].replace("￿", "")
                if first != 0xE5 and seq & 0x40:   # last fragment comes first; 0xE5 hides the flag
                    lfn = [part]
                else:
                    lfn.append(part)
                continue
            if attr & ATTR_VOLUME:
                lfn = []
                continue
            deleted = first == 0xE5 or deleted_parent
            base = raw[0:8]
            if first == 0x05:
                base = b"\xe5" + base[1:]
            if first == 0xE5:
                base = b"_" + base[1:]
            stem = base.decode("cp437", "replace").rstrip()
            ext = raw[8:11].decode("cp437", "replace").rstrip()
            # Windows NT case flags: 8.3 names stored upper case but displayed lower case.
            if raw[12] & 0x08:
                stem = stem.lower()
            if raw[12] & 0x10:
                ext = ext.lower()
            short = stem + ("." + ext if ext else "")
            long_name = "".join(reversed(lfn)) if lfn else None
            lfn = []
            name = long_name or short
            if name in (".", ".."):
                continue
            ctenths, ctime, cdate, adate, hi, wtime, wdate, lo, size = struct.unpack("<BHHHHHHHI", raw[13:32])
            cluster = lo | (hi << 16 if self.fat_type == 32 else 0)
            e = Entry(path=(parent_path.rstrip("/") + "/" + name), name=name, short_name=short, size=size,
                      attr=attr, is_dir=bool(attr & ATTR_DIR), deleted=deleted,
                      created=_fat_datetime(cdate, ctime, ctenths), modified=_fat_datetime(wdate, wtime),
                      accessed=_fat_date(adate), first_cluster=cluster,
                      entry_offset=(self.offset + base_offset + i) if base_offset is not None else 0)
            if e.is_dir:
                e.size = 0
            entries.append(e)
        return entries

    def walk(self):
        """Yield every entry (files and folders, live and deleted), depth first."""
        root_data, root_off = self._dir_bytes(self.root_cluster)
        stack = [(self._parse_dir(root_data, root_off, "/"), 0)]
        seen = set()
        while stack:
            entries, _ = stack.pop()
            for e in entries:
                yield e
                if e.is_dir and e.first_cluster >= 2 and not e.deleted and e.first_cluster not in seen:
                    seen.add(e.first_cluster)
                    data, _ = self._dir_bytes(e.first_cluster)
                    stack.append((self._parse_dir(data, None, e.path), 0))

    def summary(self):
        return {"fs_type": "FAT%d" % self.fat_type, "label": self.label, "serial": self.serial,
                "oem": self.oem, "offset": self.offset, "cluster_size": self.cluster_size,
                "volume_size": self.volume_size}
