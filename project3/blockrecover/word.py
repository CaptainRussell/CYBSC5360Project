"""Putting a Word (.doc) file's blocks back in order.

A .doc file is a small file system of its own (Microsoft's Compound File). Its
first block is a header naming the blocks that hold its allocation table (the FAT)
and its directory. The FAT lists, for every block of the file, the block that
comes next in the same stream. So once the FAT blocks are found, the file's whole
shape is known: which positions belong to the text, the formatting tables, the
summary information, and so on. What is left is to decide which free block holds
each position.

Word helps there too. Its header (the FIB) gives the offset and size of every
table it keeps, and one of those tables lists every place a paragraph ends. Each
block of text therefore has a fingerprint: the exact spots where its line breaks
fall. A text block without a line break is placed by how its words join with its
neighbours'.
"""

import re
import struct

from .layout import BS, Layout, PlaceError

MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")
FREE, END, FATSECT, DIFSECT = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD, 0xFFFFFFFC
PARA_END = (0x0D, 0x07, 0x0C)


class WordError(PlaceError):
    pass


def u32s(b):
    return struct.unpack("<%dI" % (len(b) // 4), b[:len(b) // 4 * 4])


class Word:
    def __init__(self, blocks, log=None):
        self.blocks = blocks
        self.free = {b.name: b for b in blocks}
        self.log = log or (lambda *a: None)

    # --- placing ------------------------------------------------------------

    def place_sector(self, sector, block, how):
        self.L.put(sector + 1, block, how)
        self.free.pop(block.name, None)

    def at_sector(self, sector):
        return self.L.at[sector + 1]

    def unique(self, sector, test, how):
        """Place the one free block that passes `test` at `sector`. Copies with equal bytes count once."""
        if self.at_sector(sector) is not None:
            return True
        c = [b for b in self.free.values() if test(b.data)]
        if c and all(x.data == c[0].data for x in c):
            self.place_sector(sector, c[0], how + (" (identical copies)" if len(c) > 1 else ""))
            return True
        return False

    # --- the container --------------------------------------------------------

    def find_header(self):
        heads = [b for b in self.blocks if b.data.startswith(MAGIC)]
        if len(heads) != 1:
            raise WordError("expected one block starting with the Compound File signature, found %d" % len(heads))
        h = heads[0].data
        if struct.unpack("<H", h[0x1E:0x20])[0] != 9:
            raise WordError("only 512-byte sectors are handled")
        self.head = h
        self.nfat = struct.unpack("<I", h[0x2C:0x30])[0]
        self.dir_start = struct.unpack("<I", h[0x30:0x34])[0]
        self.minifat_start = struct.unpack("<I", h[0x3C:0x40])[0]
        if struct.unpack("<I", h[0x48:0x4C])[0]:
            raise WordError("files with an extended FAT list are not handled")
        self.difat = [x for x in u32s(h[0x4C:0x200]) if x != FREE][:self.nfat]
        self.header_block = heads[0]
        self.log("header", heads[0].name, "%d FAT blocks at sectors %s" % (self.nfat, self.difat))

    def find_fat(self):
        """FAT block k describes sectors 128k..128k+127. Chains mostly run straight on,
        so entry i usually reads 128k+i+1; and the FAT's own sectors read FATSECT."""
        limit = 128 * self.nfat
        scored = []
        for k, sec in enumerate(self.difat):
            for b in self.free.values():
                v = u32s(b.data)
                if any(not (x < limit or x >= DIFSECT) for x in v):
                    continue
                if any(128 * k <= s < 128 * (k + 1) and v[s - 128 * k] != FATSECT for s in self.difat):
                    continue
                straight = sum(1 for i, x in enumerate(v) if x == 128 * k + i + 1)
                if straight or any(x != FREE for x in v):
                    scored.append((straight, k, b))
        scored.sort(key=lambda t: -t[0])
        self.fat_blocks, used = {}, set()
        for straight, k, b in scored:
            if k in self.fat_blocks or b.name in used:
                continue
            self.fat_blocks[k] = b
            used.add(b.name)
        if len(self.fat_blocks) != self.nfat:
            raise WordError("could not find every FAT block")
        self.fat = []
        for k in range(self.nfat):
            self.fat += u32s(self.fat_blocks[k].data)
        n = max(i for i, x in enumerate(self.fat) if x != FREE) + 1
        self.L = Layout(n + 1)
        self.L.put(0, self.header_block, "Compound File header")
        self.free.pop(self.header_block.name, None)
        for k, sec in enumerate(self.difat):
            self.place_sector(sec, self.fat_blocks[k], "FAT block %d" % k)
        self.log("FAT", "the file has %d sectors (%d blocks with the header)" % (n, n + 1))

    def chain(self, start):
        out, s = [], start
        while s < len(self.fat) and s not in out:
            out.append(s)
            s = self.fat[s]
            if s >= DIFSECT:
                break
        return out

    def read_stream(self, sectors, size=None):
        """Bytes of a stream as far as its blocks are placed (None for an unplaced block)."""
        parts = []
        for s in sectors:
            b = self.at_sector(s)
            parts.append(b.data if b else None)
        return parts

    def find_directory(self):
        secs = self.chain(self.dir_start)
        root = "Root Entry".encode("utf-16le")
        self.unique(secs[0], lambda d: d.startswith(root) and d[66] == 5, "directory (Root Entry)")
        for s in secs[1:]:
            self.unique(s, _dir_like, "directory")
        raw = b"".join((self.at_sector(s).data if self.at_sector(s) else bytes(BS)) for s in secs)
        self.entries = []
        for i in range(len(raw) // 128):
            e = raw[128 * i:128 * (i + 1)]
            nl = struct.unpack("<H", e[64:66])[0]
            if not 2 <= nl <= 64 or e[66] not in (1, 2, 5):
                continue
            name = e[:nl - 2].decode("utf-16le", "replace")
            start, size = struct.unpack("<II", e[116:124])
            self.entries.append({"id": i, "name": name, "type": e[66], "start": start, "size": size})
        self.streams = {e["name"]: e for e in self.entries}
        self.log("directory", ", ".join("%s (%d bytes)" % (e["name"], e["size"]) for e in self.entries))

    def find_small_parts(self):
        root = self.streams.get("Root Entry")
        cutoff = struct.unpack("<I", self.head[0x38:0x3C])[0]
        if self.minifat_start < DIFSECT:
            for s in self.chain(self.minifat_start):
                self.unique(s, lambda d: all(x < 4096 or x >= DIFSECT for x in u32s(d)) and d[:4] != b"\0\0\0\0",
                            "mini FAT")
        if root and root["start"] < DIFSECT:
            minis = [e for e in self.entries if e["type"] == 2 and e["size"] < cutoff]
            secs = self.chain(root["start"])
            for e in minis:
                off = e["start"] * 64
                if off // BS < len(secs) and e["name"] == "\x01CompObj":
                    rel = off % BS
                    self.unique(secs[off // BS], lambda d, r=rel: d[r:r + 4] == b"\x01\x00\xfe\xff", "mini stream (CompObj)")

    # --- Word's own tables -----------------------------------------------------

    def word_document(self):
        e = self.streams.get("WordDocument")
        if not e:
            raise WordError("no WordDocument stream")
        self.wd = self.chain(e["start"])
        self.unique(self.wd[0], lambda d: d[:2] == b"\xec\xa5", "Word header (FIB)")
        fib0 = self.at_sector(self.wd[0]).data
        flags = struct.unpack("<H", fib0[10:12])[0]
        self.table_name = "1Table" if flags & 0x200 else "0Table"
        self.ccp = None
        csw = struct.unpack("<H", fib0[32:34])[0]
        i = 34 + 2 * csw
        cslw = struct.unpack("<H", fib0[i:i + 2])[0]
        lw = u32s(fib0[i + 2:i + 2 + 4 * cslw])
        self.ccp_text = lw[3]
        j = i + 2 + 4 * cslw
        self.cb_fclcb = struct.unpack("<H", fib0[j:j + 2])[0]
        self.fclcb_at = j + 2
        te = self.streams.get(self.table_name)
        if not te:
            raise WordError("no %s stream" % self.table_name)
        self.ts = self.chain(te["start"])
        self.table_size = te["size"]
        # the rest of the FIB: (offset, size) pairs into the table stream
        end = self.fclcb_at + 8 * self.cb_fclcb
        for k in range(1, (end - 1) // BS + 1):
            self.unique(self.wd[k], lambda d, k=k: self._fib_part_ok(d, k), "Word header, part %d" % (k + 1))
        fib = b"".join(self.at_sector(self.wd[k]).data for k in range((end - 1) // BS + 1))
        vals = u32s(fib[self.fclcb_at:end])
        self.fclcb = [(vals[2 * k], vals[2 * k + 1]) for k in range(self.cb_fclcb)]
        self.log("Word header", "%d characters of text; %d tables listed" % (self.ccp_text, sum(1 for f, l in self.fclcb if l)))

    def _fib_part_ok(self, d, k):
        lo = k * BS
        first = max(0, -(-(lo - self.fclcb_at) // 8))
        ok = 0
        for pair in range(first, self.cb_fclcb):
            off = self.fclcb_at + 8 * pair - lo
            if off + 8 > BS:
                break
            fc, lcb = struct.unpack("<II", d[off:off + 8])
            if lcb > self.table_size or (lcb and fc + lcb > self.table_size):
                return False
            ok += 1
        # an ascending list of numbers also passes the test above; real pairs do not ascend
        v = u32s(d)
        if all(a <= b for a, b in zip(v, v[1:])):
            return False
        return ok > 0

    def table(self, k):
        return self.fclcb[k] if k < len(self.fclcb) else (0, 0)

    def table_stream(self):
        """Place the formatting-table blocks that hold the bin tables and the piece table."""
        ts = self.ts
        tsize = self.table_size
        self.bte = {}
        for k, what in ((12, "character"), (13, "paragraph")):
            fc, lcb = self.table(k)
            if not lcb:
                continue
            n = (lcb - 4) // 8

            def test(d, fc=fc, n=n, first=None):
                return _bte_ok(d, fc % BS, n, self.wd_size())
            if (fc + lcb - 1) // BS == fc // BS:
                self.unique(ts[fc // BS], test, "%s formatting index" % what)
        fc, lcb = self.table(33)
        if lcb:
            self.unique(ts[fc // BS], lambda d, o=fc % BS, n=lcb: self._clx_ok(d[o:o + n]), "piece table")
        # the stylesheet starts the table stream
        fc, lcb = self.table(1)
        if lcb and fc == 0:
            self.unique(ts[0], lambda d: struct.unpack("<H", d[:2])[0] in (0x12, 0x14, 0x16, 0x18) and
                        "Normal".encode("utf-16le") in d, "stylesheet")
        # read the bin tables
        for k in (12, 13):
            fc, lcb = self.table(k)
            raw = self._read(ts, fc, lcb)
            if raw is None:
                raise WordError("formatting index %d could not be placed" % k)
            n = (lcb - 4) // 8
            fcs = u32s(raw[:4 * (n + 1)])
            pns = u32s(raw[4 * (n + 1):4 * (n + 1) + 4 * n])
            self.bte[k] = list(zip(fcs, fcs[1:], pns))
        raw = self._read(ts, *self.table(33))
        self.pieces = _clx(raw) if raw else []
        self.log("pieces", "; ".join("chars %d-%d at byte %d%s" % (a, b, fc, " (8-bit)" if c else "")
                                     for a, b, fc, c in self.pieces))

    def _clx_ok(self, raw):
        try:
            pieces = _clx(raw)
        except (WordError, struct.error, IndexError):
            return False
        return (bool(pieces) and pieces[0][0] == 0 and pieces[-1][1] >= self.ccp_text
                and all(fc + (b - a) * (1 if c else 2) <= self.wd_size() for a, b, fc, c in pieces))

    def wd_size(self):
        return self.streams["WordDocument"]["size"]

    def _read(self, secs, fc, lcb):
        out = b""
        for s in range(fc // BS, (fc + lcb - 1) // BS + 1):
            b = self.at_sector(secs[s])
            if b is None:
                return None
            out += b.data
        return out[fc % BS:fc % BS + lcb]

    def fkps(self):
        """Formatting pages (FKPs) sit at the page numbers the bin tables give. Each starts with
        the text offsets it covers; the paragraph pages list where every paragraph ends."""
        self.para_ends = set()
        for k, what in ((12, "character"), (13, "paragraph")):
            for fc0, fc1, pn in self.bte[k]:
                ok = self.unique(pn, lambda d, a=fc0, b=fc1: _fkp_ok(d, a, b), "%s formatting page" % what)
                if not ok:
                    raise WordError("formatting page %d could not be placed" % pn)
                if k == 13:
                    d = self.at_sector(pn).data
                    crun = d[511]
                    self.para_ends.update(u32s(d[4:4 * (crun + 1)]))

    def text(self):
        """Text blocks: by where their paragraph marks fall."""
        self.text_sectors = []
        for a, b, fc, comp in self.pieces:
            if not comp:
                raise WordError("16-bit text pieces are not handled yet")
            for s in range(fc // BS, (fc + (b - a) - 1) // BS + 1):
                self.text_sectors.append((s, max(fc, s * BS), min(fc + (b - a), (s + 1) * BS)))
        placed = 0
        for s, lo, hi in self.text_sectors:
            ends = {e - 1 - s * BS for e in self.para_ends if lo < e <= hi}
            if not ends:
                continue
            rlo, rhi = lo - s * BS, hi - s * BS

            def test(d, ends=ends, rlo=rlo, rhi=rhi):
                if any(d[i] not in PARA_END for i in ends):
                    return False
                return all(d[i] != 0x0D or i in ends for i in range(rlo, rhi))
            if self.unique(self.wd[s], test, "text (paragraph marks match)"):
                placed += 1
        self.log("text", "%d of %d text blocks placed by their paragraph marks" % (placed, len(self.text_sectors)))

    def ascending_tables(self):
        """A table that is one long ascending list of numbers (text positions) is put back in
        order by its numbers: each block must carry on from where the one before stopped."""
        placed = 0
        for fc, lcb in self.fclcb:
            if lcb < 2 * BS:
                continue
            first, last = fc // BS, (fc + lcb - 1) // BS
            head = self.at_sector(self.ts[first])
            if head is None:
                continue
            phase = fc % 4
            hv = u32s(head.data[fc % BS:])
            if len(hv) < 8 or not all(a < b for a, b in zip(hv, hv[1:])):
                continue
            prev = hv[-1]
            for k in range(first + 1, last + 1):
                b = self.at_sector(self.ts[k])
                if b is None:
                    c = []
                    for x in self.free.values():
                        v = u32s(x.data[phase:])
                        if v[0] > prev and all(p < q for p, q in zip(v, v[1:])):
                            c.append((v[0], x))
                    if not c:
                        break
                    c.sort(key=lambda t: t[0])
                    self.place_sector(self.ts[k], c[0][1], "ascending table, continues the block before")
                    placed += 1
                    b = c[0][1]
                v = u32s(b.data[phase:])
                if not all(p < q for p, q in zip(v, v[1:])):
                    break
                prev = v[-1]
        self.log("tables", "%d blocks of ascending tables placed" % placed)

    # --- the whole job ---------------------------------------------------------

    def anchor(self):
        self.find_header()
        self.find_fat()
        self.find_directory()
        self.find_small_parts()
        self.word_document()
        self.table_stream()
        self.fkps()
        self.text()
        self.ascending_tables()
        return self.L


def _dir_like(d):
    ok = 0
    for i in range(4):
        e = d[128 * i:128 * (i + 1)]
        nl = struct.unpack("<H", e[64:66])[0]
        if nl == 0 and not any(e[:64]):
            continue
        if nl % 2 or nl > 64 or e[66] not in (1, 2, 5) or e[nl - 2:nl] != b"\0\0":
            return False
        try:
            name = e[:nl - 2].decode("utf-16le")
        except UnicodeDecodeError:
            return False
        if not name or any(ord(c) < 32 and c not in "\x01\x05" for c in name):
            return False
        ok += 1
    return ok > 0


def _bte_ok(d, off, n, wdsize):
    need = off + 4 * (2 * n + 1)
    if need > BS:
        return False
    v = u32s(d[off:need])
    fcs, pns = v[:n + 1], v[n + 1:]
    return (all(a < b for a, b in zip(fcs, fcs[1:])) and fcs[-1] <= wdsize
            and all(0 < p < wdsize // BS + 1 for p in pns))


def _fkp_ok(d, fc0, fc1):
    crun = d[511]
    if not 1 <= crun <= 101:
        return False
    v = u32s(d[:4 * (crun + 1)])
    return v[0] == fc0 and all(a < b for a, b in zip(v, v[1:])) and v[-1] <= fc1 + 1 and v[-1] >= fc1 - 1


def _clx(raw):
    i = 0
    while i < len(raw) and raw[i] == 1:                  # property modifiers come first
        i += 3 + struct.unpack("<H", raw[i + 1:i + 3])[0]
    if i >= len(raw) or raw[i] != 2:
        raise WordError("piece table not found")
    lcb = struct.unpack("<I", raw[i + 1:i + 5])[0]
    plc = raw[i + 5:i + 5 + lcb]
    n = (lcb - 4) // 12
    cps = u32s(plc[:4 * (n + 1)])
    out = []
    for k in range(n):
        pcd = plc[4 * (n + 1) + 8 * k:4 * (n + 1) + 8 * k + 8]
        fc = struct.unpack("<I", pcd[2:6])[0]
        comp = bool(fc & 0x40000000)
        fc &= 0x3FFFFFFF
        out.append((cps[k], cps[k + 1], fc // 2 if comp else fc, comp))
    return out
