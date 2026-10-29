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

import itertools
import math
import re
import struct
from collections import Counter

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

    def unique(self, sector, test, how, rank=None):
        """Place the one free block that passes `test` at `sector`. Copies with equal bytes count once.
        With `rank`, several passing blocks are settled by the one ranked strictly highest."""
        if self.at_sector(sector) is not None:
            return True
        c = [b for b in self.free.values() if test(b.data)]
        if rank and len(c) > 1:
            c.sort(key=lambda b: -rank(b.data))
            if rank(c[0].data) > rank(c[1].data):
                c = c[:1]
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
        self.unique(secs[0], lambda d: d.startswith(root) and d[66] == 5 and self._dir_fits_fat(d),
                    "directory (Root Entry)", rank=_dir_entries)
        for s in secs[1:]:
            # (only the first directory block holds the Root Entry)
            self.unique(s, lambda d: _dir_like(d) and not d.startswith(root) and self._dir_fits_fat(d),
                        "directory", rank=_dir_entries)
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

    def _dir_fits_fat(self, d):
        """Every stream listed in a directory block must have a FAT chain as long as its size needs."""
        cutoff = struct.unpack("<I", self.head[0x38:0x3C])[0]
        for i in range(4):
            e = d[128 * i:128 * (i + 1)]
            if e[66] not in (2, 5):
                continue
            start, size = struct.unpack("<II", e[116:124])
            if e[66] == 2 and size < cutoff:
                continue                                   # lives in the mini stream
            if size == 0 and start >= DIFSECT:
                continue
            if start >= len(self.fat) or len(self.chain(start)) != -(-size // BS):
                return False
        return True

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
        self.table_size = te["size"]
        cutoff = struct.unpack("<I", self.head[0x38:0x3C])[0]
        self.table_mini = te["size"] < cutoff
        if self.table_mini:
            # a small table stream lives in the mini stream, in 64-byte pieces
            self.ts = []
            self.tmini = self.mini_chain(te["start"])
        else:
            self.ts = self.chain(te["start"])
        # the rest of the FIB: (offset, size) pairs into the table stream
        end = self.fclcb_at + 8 * self.cb_fclcb
        for k in range(1, (end - 1) // BS + 1):
            self.unique(self.wd[k], lambda d, k=k: self._fib_part_ok(d, k), "Word header, part %d" % (k + 1),
                        rank=lambda d, k=k: self._fib_pairs_used(d, k))
        # (the tables this toolkit reads are listed in the FIB's first block; a later FIB block
        # that cannot be told apart yet is filled in at the end)
        fib = b"".join((self.at_sector(self.wd[k]).data if self.at_sector(self.wd[k]) else bytes(BS))
                       for k in range((end - 1) // BS + 1))
        vals = u32s(fib[self.fclcb_at:end])
        self.fclcb = [(vals[2 * k], vals[2 * k + 1]) for k in range(self.cb_fclcb)]
        self.log("Word header", "%d characters of text; %d tables listed" % (self.ccp_text, sum(1 for f, l in self.fclcb if l)))

    def _fib_pairs_used(self, d, k):
        lo = k * BS
        first = max(0, -(-(lo - self.fclcb_at) // 8))
        n = 0
        for pair in range(first, self.cb_fclcb):
            off = self.fclcb_at + 8 * pair - lo
            if off + 8 > BS:
                break
            n += struct.unpack("<I", d[off + 4:off + 8])[0] > 0
        return n

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
        # an ascending list of numbers, or a formatting page (which starts with one), also
        # passes the test above; real pairs do not ascend
        v = u32s(d)
        rising = sum(1 for a, b in zip(v, v[1:]) if a < b)
        if (rising >= 16 and all(a <= b for a, b in zip(v, v[1:]))) or _fkp_shape(d, self.wd_size()):
            return False
        return ok > 0

    def mini_chain(self, start):
        """Follow the mini FAT (its blocks must be placed) from a mini sector."""
        mf = []
        for sec in self.chain(self.minifat_start) if self.minifat_start < DIFSECT else []:
            b = self.at_sector(sec)
            if b is None:
                raise WordError("the mini FAT block is not placed")
            mf += u32s(b.data)
        out, s = [], start
        while s < len(mf) and s not in out:
            out.append(s)
            s = mf[s]
        self.root_secs = self.chain(self.streams["Root Entry"]["start"])
        return out

    def tloc(self, off):
        """Table-stream offset -> (sector, offset inside that block)."""
        if not self.table_mini:
            return self.ts[off // BS], off % BS
        mo = 64 * self.tmini[off // 64] + off % 64
        return self.root_secs[mo // BS], mo % BS

    def tread(self, off, n):
        out = b""
        while n > 0:
            sec, o = self.tloc(off)
            step = min(n, (64 if self.table_mini else BS) - off % (64 if self.table_mini else BS))
            b = self.at_sector(sec)
            if b is None:
                return None
            out += b.data[o:o + step]
            off += step
            n -= step
        return out

    def table_sectors(self):
        """The distinct blocks that hold the table stream, in stream order."""
        if not self.table_mini:
            return list(self.ts)
        seen = []
        for k in range(-(-self.table_size // 64)):
            sec = self.tloc(64 * k)[0]
            if sec not in seen:
                seen.append(sec)
        return seen

    def table(self, k):
        return self.fclcb[k] if k < len(self.fclcb) else (0, 0)

    def table_stream(self):
        """Place the formatting-table blocks that hold the bin tables and the piece table."""
        self.bte = {}
        for k, what in ((12, "character"), (13, "paragraph")):
            fc, lcb = self.table(k)
            if not lcb:
                continue
            n = (lcb - 4) // 8
            sec, o = self.tloc(fc)
            if o + lcb <= BS:
                self.unique(sec, lambda d, o=o, n=n: _bte_ok(d, o, n, self.wd_size()), "%s formatting index" % what)
        fc, lcb = self.table(33)
        if lcb:
            sec, o = self.tloc(fc)
            self.unique(sec, lambda d, o=o, n=lcb: self._clx_ok(d[o:o + n]), "piece table")
        # the stylesheet starts the table stream
        fc, lcb = self.table(1)
        if lcb and fc == 0:
            sec, o = self.tloc(0)
            self.unique(sec, lambda d, o=o: struct.unpack("<H", d[o:o + 2])[0] in (0x12, 0x14, 0x16, 0x18) and
                        "Normal".encode("utf-16le") in d[o:], "stylesheet")
        # read the bin tables
        for k in (12, 13):
            fc, lcb = self.table(k)
            raw = self.tread(fc, lcb)
            if raw is None:
                raise WordError("formatting index %d could not be placed" % k)
            n = (lcb - 4) // 8
            fcs = u32s(raw[:4 * (n + 1)])
            pns = u32s(raw[4 * (n + 1):4 * (n + 1) + 4 * n])
            self.bte[k] = list(zip(fcs, fcs[1:], pns))
        raw = self.tread(*self.table(33))
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

    def fkps(self):
        """Formatting pages (FKPs) sit at the page numbers the bin tables give (counted in
        512-byte pages of the WordDocument stream). Each starts with the text offsets it covers;
        the paragraph pages list where every paragraph ends."""
        self.para_ends = set()
        for k, what in ((12, "character"), (13, "paragraph")):
            for fc0, fc1, pn in self.bte[k]:
                if pn >= len(self.wd):
                    raise WordError("formatting page %d is past the end of the document" % pn)
                test = lambda d, a=fc0, b=fc1: _fkp_ok(d, a, b)   # noqa: E731
                if self.unique(self.wd[pn], test, "%s formatting page" % what):
                    d = self.at_sector(self.wd[pn]).data
                else:
                    # several pages fit (an old copy left in the file); if they agree on the
                    # offsets, those are still known, and the page itself is placed later
                    c = [b.data for b in self.free.values() if test(b.data)]
                    runs = {c0[:4 * (c0[511] + 1)] for c0 in c}
                    if len(runs) != 1:
                        raise WordError("formatting page %d could not be placed" % pn)
                    d = c[0]
                if k == 13:
                    crun = d[511]
                    self.para_ends.update(u32s(d[4:4 * (crun + 1)]))

    def text(self):
        """Text blocks: by where their paragraph marks fall. Text is 8-bit or 16-bit per piece."""
        self.text_sectors = []
        for a, b, fc, comp in self.pieces:
            w = 1 if comp else 2
            end = fc + (b - a) * w
            for s in range(fc // BS, (end - 1) // BS + 1):
                self.text_sectors.append((s, max(fc, s * BS), min(end, (s + 1) * BS), w))
        placed = 0
        for s, lo, hi, w in self.text_sectors:
            ends = {e - w - s * BS for e in self.para_ends if lo < e <= hi}
            if not ends:
                continue
            rlo, rhi = lo - s * BS, hi - s * BS

            def test(d, ends=ends, rlo=rlo, rhi=rhi, w=w):
                if any(d[i] not in PARA_END or (w == 2 and d[i + 1]) for i in ends):
                    return False
                return all(d[i] != 0x0D or (w == 2 and d[i + 1]) or i in ends for i in range(rlo, rhi, w))
            if self.unique(self.wd[s], test, "text (paragraph marks match)"):
                placed += 1
        self.log("text", "%d of %d text blocks placed by their paragraph marks" % (placed, len(self.text_sectors)))

    def text_gaps(self):
        """Text blocks with no paragraph mark: put in the gaps between placed text by how well
        their characters continue the text on both sides (a character model learned from the
        document's own text)."""
        secs = [t for t in self.text_sectors]
        todo = [t for t in secs if self.at_sector(self.wd[t[0]]) is None]
        if not todo:
            return
        w = todo[0][3]
        enc = "utf-16le" if w == 2 else "cp1252"

        def text_of(d, lo=0, hi=BS):
            return d[lo:hi].decode(enc, "replace")
        cands = []
        for b in self.free.values():
            t = text_of(b.data)
            if sum(c.isprintable() or c in "\r\n\t" for c in t) / max(1, len(t)) > 0.97 and "\r" not in t:
                cands.append(b)
        texts = [text_of(self.at_sector(self.wd[t[0]]).data) for t in secs if self.at_sector(self.wd[t[0]])]
        model = _CharModel(texts + [text_of(b.data) for b in cands])
        todo = [t[0] for t in secs if self.at_sector(self.wd[t[0]]) is None]
        idx = {t[0]: i for i, t in enumerate(secs)}
        placed = 0
        # most confident first: a gap position next to placed text, and the candidate that
        # joins it far better than any other
        while todo:
            pool = [b for b in cands if b.name in self.free]
            if not pool:
                break
            best = None
            for s0 in todo:
                i = idx[s0]
                left = self.at_sector(self.wd[secs[i - 1][0]]) if i > 0 else None
                right = self.at_sector(self.wd[secs[i + 1][0]]) if i + 1 < len(secs) else None
                if left is None and right is None:
                    continue
                scores = []
                for b in pool:
                    t = text_of(b.data)
                    sc = 0.0
                    if left is not None:
                        sc += model.join(text_of(left.data), t)
                    if right is not None:
                        sc += model.join(t, text_of(right.data))
                    scores.append((sc / ((left is not None) + (right is not None)), b))
                scores.sort(key=lambda x: -x[0])
                margin = scores[0][0] - (scores[1][0] if len(scores) > 1 else scores[0][0] - 50)
                if best is None or margin > best[0]:
                    best = (margin, s0, scores[0][1])
            if best is None:
                break
            _m, s0, b = best
            self.place_sector(self.wd[s0], b, "text continues its neighbours' words")
            todo.remove(s0)
            placed += 1
        self.log("text", "%d text blocks placed by how their words join" % placed)

    def ascending_tables(self):
        """A table that is one long ascending list of numbers (text positions) is put back in
        order by its numbers: each block must carry on from where the one before stopped."""
        placed = 0
        for fc, lcb in self.fclcb if not self.table_mini else ():
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
                        if prev < v[0] <= self.wd_size() and all(p < q for p, q in zip(v[:8], v[1:8])):
                            c.append((v[0], x))
                    if not c:
                        break
                    c.sort(key=lambda t: t[0])
                    self.place_sector(self.ts[k], c[0][1], "ascending table, continues the block before")
                    placed += 1
                    b = c[0][1]
                v = u32s(b.data[phase:])
                if not all(p < q for p, q in zip(v, v[1:])):
                    placed += self._plc_data(fc, lcb, k, b, phase)
                    break
                prev = v[-1]
        self.log("tables", "%d blocks of ascending tables placed" % placed)

    def _plc_data(self, fc, lcb, k, b, phase):
        """After its positions, a PLC holds one fixed-size record per entry. Where the records
        repeat, each later block's bytes follow from where it falls."""
        v = u32s(b.data[phase:])
        # positions are character numbers, so they cannot pass the document's length
        lim = self.wd_size()
        stop = next(i for i in range(1, len(v)) if v[i] <= v[i - 1] or v[i] > lim)
        ds = k * BS + phase + 4 * stop                       # where the records start (table offset)
        ncp = (ds - fc) // 4
        n = ncp - 1
        if n <= 0 or (lcb - 4 * ncp) % n:
            return 0
        rec = (lcb - 4 * ncp) // n
        if not 0 < rec <= 64 or ds % BS + rec > BS:
            return 0
        tmpl = b.data[ds % BS:ds % BS + rec]
        end = fc + lcb
        placed = 0
        for j in range(k + 1, (end - 1) // BS + 1):
            lo, hi = j * BS, min(end, (j + 1) * BS)
            want = bytes(tmpl[(x - ds) % rec] for x in range(lo, hi))

            def test(d, want=want, n=hi - lo):
                return d[:n] == want
            if self.unique(self.ts[j], test, "table records (repeating)"):
                placed += 1
        return placed

    def zero_regions(self):
        """Parts of streams that hold nothing: after the FIB until the text, after a property
        set's last section, after a stream's end. Blocks there must be all zeros (or zero
        where the stream has ended)."""
        self.expect_zero = {}                         # sector -> (lo, hi) range within it that must be 0
        wd = self.wd
        fib = b"".join(self.at_sector(wd[k]).data for k in range(3) if self.at_sector(wd[k]))
        end = self.fclcb_at + 8 * self.cb_fclcb
        if len(fib) >= end + 2:
            csw_new = struct.unpack("<H", fib[end:end + 2])[0]
            if csw_new <= 8:                          # (a larger count is not a real FIB field)
                end += 2 + 2 * csw_new
        text_start = min(fc for a, b, fc, c in self.pieces) if self.pieces else end
        self._zero_range(wd, end, text_start)
        root = self.streams.get("Root Entry")
        if root and root["start"] < DIFSECT:
            self._zero_range(self.chain(root["start"]), root["size"], len(self.chain(root["start"])) * BS)
        for e in self.entries:
            if e["type"] != 2 or e["size"] < 4096:
                continue
            secs = self.chain(e["start"])
            self._zero_range(secs, e["size"], len(secs) * BS)
            if e["name"].startswith("\x05"):
                first = self.at_sector(secs[0])
                if first is None:
                    self.unique(secs[0], lambda d: d[:4] == b"\xfe\xff\x00\x00" and
                                d[28:44] == _FMTID.get(e["name"], d[28:44]), "property set " + e["name"][1:])
                    first = self.at_sector(secs[0])
                if first is not None:
                    self._zero_range(secs, _propset_end(first.data), e["size"])
        placed = 0
        for sec, (lo, hi) in sorted(self.expect_zero.items()):
            if lo == 0 and hi == BS and self.unique(sec, lambda d: not any(d), "nothing here (zeros)"):
                placed += 1
        self.log("empty", "%d all-zero blocks placed" % placed)

    def _zero_range(self, secs, lo, hi):
        for k in range(lo // BS, min(len(secs), -(-hi // BS))):
            a, b = max(lo, k * BS) - k * BS, min(hi, (k + 1) * BS) - k * BS
            if a < b:
                old = self.expect_zero.get(secs[k])
                self.expect_zero[secs[k]] = (min(a, old[0]), max(b, old[1])) if old else (a, b)

    def leftovers(self, candidates):
        """The last few positions: pick the assignment whose joins with the neighbours look most
        like the bytes around them, among blocks that are zero where they must be."""
        todo = [p for p in range(1, self.L.n) if self.L.at[p] is None]
        if not todo:
            return
        cands = [b for b in candidates if b.name in self.free]
        starts = {}
        for fc, lcb in self.fclcb:
            if lcb:
                sec, o = self.tloc(fc) if fc < self.table_size else (None, None)
                if sec is not None:
                    starts.setdefault(sec + 1, []).append(o)

        text_secs = {self.wd[t[0]] for t in getattr(self, "text_sectors", ())}

        def score(b, p):
            z = self.expect_zero.get(p - 1)
            if z and any(b.data[z[0]:z[1]]):
                return None
            sc = 0.0
            left = self.L.at[p - 1]
            right = self.L.at[p + 1] if p + 1 < self.L.n else None
            if left is not None:
                sc += _join(left.data, b.data)
            if right is not None:
                sc += _join(b.data, right.data)
            if p - 1 in self.wd and p - 1 not in text_secs and _fkp_shape(b.data, self.wd_size()):
                sc += 2                                # the formatting pages' area of the document
            for o in starts.get(p, ()):
                if b.data[o:o + 2] == b"\xff\xff":     # a string table starts here
                    sc += 4
            return sc

        table = {(b.name, p): score(b, p) for b in cands for p in todo}
        if len(todo) <= 8 and len(cands) <= 12:
            best, best_sc = None, None
            for perm in itertools.permutations(cands, len(todo)):
                tot = 0
                for b, p in zip(perm, todo):
                    v = table[(b.name, p)]
                    if v is None:
                        break
                    tot += v
                else:
                    if best_sc is None or tot > best_sc:
                        best, best_sc = perm, tot
            if best is None:
                raise WordError("no way to fill the last %d positions" % len(todo))
            for b, p in zip(best, todo):
                self.L.put(p, b, "fits its neighbours best")
                self.free.pop(b.name, None)
        else:
            for p in todo:
                ok = [(table[(b.name, p)], b) for b in cands if b.name in self.free and table[(b.name, p)] is not None]
                if ok:
                    ok.sort(key=lambda t: -t[0])
                    self.L.put(p, ok[0][1], "fits its neighbours best")
                    self.free.pop(ok[0][1].name, None)
        self.log("last blocks", "%d placed by how they join their neighbours" % len(todo))

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
        self.text_gaps()
        self.ascending_tables()
        self.zero_regions()
        return self.L


_FMTID = {
    "\x05SummaryInformation": bytes.fromhex("E0859FF2F94F6810AB9108002B27B3D9"),
    "\x05DocumentSummaryInformation": bytes.fromhex("02D5CDD59C2E1B10939708002B2CF9AE"),
}


def _propset_end(d):
    """Where the last section of a property set ends."""
    n = struct.unpack("<I", d[24:28])[0]
    end = 28 + 20 * n
    for k in range(min(n, 4)):
        off = struct.unpack("<I", d[28 + 20 * k + 16:28 + 20 * k + 20])[0]
        if off + 4 <= len(d):
            end = max(end, off + struct.unpack("<I", d[off:off + 4])[0])
    return end


def _join(a, b, w=6, g=3):
    """How familiar the bytes across the join of a then b are: the share of short byte
    sequences spanning the join that also occur inside a or b."""
    win = a[-w:] + b[:w]
    hits = tot = 0
    for i in range(w - g + 1, w):
        gram = win[i:i + g]
        tot += 1
        if gram in a[:-w] or gram in b[w:]:
            hits += 1
    return hits / tot


class _CharModel:
    """Character n-grams (Witten-Bell smoothing), learned inside each text block separately so
    that no join is ever learned from, plus the words the document uses."""

    def __init__(self, texts, n=6):
        self.n = n
        self.c = [Counter() for _ in range(n + 1)]
        for text in texts:
            for k in range(1, n + 1):
                for i in range(len(text) - k + 1):
                    self.c[k][text[i:i + k]] += 1
        self.ctx = [Counter() for _ in range(n + 1)]
        self.types = [Counter() for _ in range(n + 1)]
        for k in range(1, n + 1):
            for g, v in self.c[k].items():
                self.ctx[k][g[:-1]] += v
                self.types[k][g[:-1]] += 1
        self.V = len(self.c[1]) + 1
        self.words = Counter(w.lower() for t in texts for w in re.findall(r"[A-Za-z]+", t)[1:-1])

    def p(self, h, ch):
        pr = 1.0 / self.V
        for k in range(1, self.n + 1):
            if len(h) < k - 1:
                break
            hh = h[len(h) - (k - 1):] if k > 1 else ""
            tot = self.ctx[k][hh]
            if tot:
                lam = tot / (tot + self.types[k][hh])
                pr = lam * self.c[k][hh + ch] / tot + (1 - lam) * pr
        return pr

    def join(self, a, b, span=10):
        """How likely the first characters of b are right after the end of a, and whether a
        word cut by the join is one the document uses."""
        if not a:
            return 0.0
        h, sc = a[-(self.n - 1):], 0.0
        for ch in b[:span]:
            sc += math.log(self.p(h, ch))
            h = (h + ch)[-(self.n - 1):]
        left, right = re.search(r"[A-Za-z]+$", a), re.match(r"[A-Za-z]+", b)
        if left and right:
            sc += 2.0 if self.words[(left.group(0) + right.group(0)).lower()] else -2.0
        return sc


def _dir_entries(d):
    return sum(1 for i in range(4) if d[128 * i + 66] in (1, 2, 5))


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


def _fkp_shape(d, limit):
    crun = d[511]
    if not 1 <= crun <= 101:
        return False
    v = u32s(d[:4 * (crun + 1)])
    return all(a < b for a, b in zip(v, v[1:])) and v[-1] <= limit


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
