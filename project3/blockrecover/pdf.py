"""Putting a PDF's blocks back in order.

A PDF says where its own pieces are. The header gives the file's length, the
cross-reference tables give the byte offset of every object, and each object
starts with "N 0 obj". So most blocks can be placed by reading the file's own
map: an object at offset X lives in block X // 512, at X % 512 inside it.

What the map does not cover is the inside of a stream: page drawings, fonts,
pictures. Those blocks are ordered by trying each candidate as the next block and
asking whether the stream still makes sense: for a compressed stream, whether it
still decompresses and the result still reads as PDF drawing commands; for a
picture, whether the picture's edges still line up. This file's streams are also
encrypted, with an empty password, so each candidate is decrypted first with the
key for its exact position.
"""

import re

from . import pdfcrypt, pdflex
from .layout import BS, Layout, PlaceError as PDFError  # noqa: F401

XREF_LINE = re.compile(rb"(\d{10}) (\d{5}) ([nf])(?:\r\n| \r| \n)")
OBJ = re.compile(rb"(\d+) (\d+) obj")
EOF_TAIL = re.compile(rb"startxref\s+(\d+)\s+%%EOF\s*$")
STREAM_KW = re.compile(rb"stream(\r\n|\n)")


def _xref_head_ok(t, need):
    """t starts a table; its lines must stay valid past byte `need` (into the joined block)."""
    m = re.match(rb"xref\s*(\d+) (\d+)\s*?(\r\n|\n|\r)", t)
    if not m:
        return False
    i, left = m.end(), int(m.group(2))
    while i < need and left:
        mm = XREF_LINE.match(t, i)
        if not mm:
            return False
        i, left = mm.end(), left - 1
    return i >= need or not left


def xor(a, b):
    n = min(len(a), len(b))
    return (int.from_bytes(a[:n], "little") ^ int.from_bytes(b[:n], "little")).to_bytes(n, "little")


def _int_after(text, key):
    m = re.search(re.escape(key) + rb"\s*(-?\d+)", text)
    return int(m.group(1)) if m else None


class PDF:
    def __init__(self, blocks, log=None):
        self.blocks = blocks
        self.log = log or (lambda *a: None)
        self.free = {b.name: b for b in blocks}
        self.objects = {}               # num -> (gen, offset)
        self.headers = {}               # (num, gen) -> [(block, in-block offset)]
        self.sec = None
        self.streams = []               # dicts: num, gen, start, length, filter, kind
        self._index_headers()

    # --- finding things -------------------------------------------------

    def _index_headers(self):
        for b in self.blocks:
            for m in OBJ.finditer(b.data):
                self.headers.setdefault((int(m.group(1)), int(m.group(2))), []).append((b, m.start()))

    def place(self, p, block, how):
        self.L.put(p, block, how)
        self.free.pop(block.name, None)

    def fits(self, block, p, offset_in_file, text):
        """Does `block` at position p hold `text` where the file offset says it should?"""
        s = offset_in_file - p * BS
        lo, hi = max(0, s), min(BS, s + len(text))
        if lo >= hi:
            return True
        return block.data[lo:hi] == text[lo - s:hi - s]

    def candidates(self, p, offset_in_file, text):
        return [b for b in self.free.values() if self.fits(b, p, offset_in_file, text)]

    def anchor_text(self, offset, text, how):
        """Place every block the text at `offset` must lie in, if only one free block fits each."""
        placed = 0
        for p in range(offset // BS, (offset + len(text) - 1) // BS + 1):
            if self.L.at[p] is not None:
                if not self.fits(self.L.at[p], p, offset, text):
                    raise PDFError("block at %d does not hold %r at %d" % (p, text[:20], offset))
                continue
            c = self.candidates(p, offset, text)
            if len(c) == 1:
                self.place(p, c[0], how)
                placed += 1
            elif len(c) > 1 and all(x.data == c[0].data for x in c):
                self.place(p, c[0], how + " (identical copies)")
                placed += 1
        return placed

    # --- steps ----------------------------------------------------------

    def find_header(self):
        heads = [b for b in self.blocks if b.data.startswith(b"%PDF-")]
        if len(heads) != 1:
            raise PDFError("expected one block starting with %%PDF-, found %d" % len(heads))
        h = heads[0].data
        size = _int_after(h, b"/L") if b"/Linearized" in h else None
        self.eof = None
        if size is None:
            # not linearized: the last block says where the cross-reference table is
            ends = []
            for b in self.blocks:
                m = EOF_TAIL.search(b.data.rstrip(b"\0"))
                if m:
                    ends.append((b, None, m))
            if not ends:
                # the end may be cut by a block boundary: a nearly empty last block finishes
                # the "startxref ... %%EOF" that another block starts
                for x in self.blocks:
                    t = x.data.rstrip(b"\0")
                    if not 0 < len(t) < 16:
                        continue
                    for y in self.blocks:
                        if y is not x and b"startxref" in y.data[-48:]:
                            m = EOF_TAIL.search(y.data + t)
                            if m:
                                ends.append((x, y, m))
            if len(ends) != 1:
                raise PDFError("expected one block ending the PDF (startxref ... %%%%EOF), found %d" % len(ends))
            self.eof = ends[0]
            self.size = None
            self.L = Layout(len(self.blocks) + 1)
            self.log("header", heads[0].name, "not linearized; the table is at byte %s" % ends[0][2].group(1).decode())
        else:
            self.size = size
            self.L = Layout((size + BS - 1) // BS)
            self.log("header", heads[0].name, "file is %d bytes = %d blocks" % (size, self.L.n))
        self.place(0, heads[0], "starts with %PDF-")

    def place_end(self, table_end):
        """Non-linearized: the trailer follows the last table, and the block holding
        "%%EOF" ends the file. That fixes the file's length."""
        last, prev, m = self.eof
        b = prev or last                                 # the block holding "startxref"
        p = table_end // BS
        if not (b.data.find(b"trailer") == table_end % BS or self.L.at[p] is not None):
            p += 1
        if self.L.at[p] is not None and self.L.at[p] is not b:
            p += 1
        self.place(p, b, "ends the file (%%EOF)")
        if prev is not None:
            self.place(p + 1, last, "the last bytes of %%EOF")
            p += 1
            rel = m.end() - BS
        else:
            rel = m.end()
        self.size = p * BS + rel + len(re.match(rb"[\r\n]*", last.data[rel:]).group(0))
        n = -(-self.size // BS)
        if any(x is not None for x in self.L.at[n:]):
            raise PDFError("blocks were placed past the end of the file")
        self.L.n, self.L.at, self.L.how = n, self.L.at[:n], self.L.how[:n]
        self.log("size", "file is %d bytes = %d blocks" % (self.size, n))

    def read_xref(self, offset):
        """Read a cross-reference table at `offset`, placing its blocks as they are needed. -> trailer text."""
        self.anchor_text(offset, b"xref", "cross-reference table")
        head = self.L.data(offset, offset + 64)
        if head is None:
            # the table's first lines run into the next block: the block that continues
            # them into a header and a valid first entry is the one
            p = offset // BS + 1
            cur = self.L.at[p - 1].data[offset % BS:]
            c = [b for b in self.free.values() if _xref_head_ok(cur + b.data[:64], len(cur) + 1)]
            if len(c) == 1:
                self.place(p, c[0], "cross-reference table continues")
            head = self.L.data(offset, offset + 64)
        m = re.match(rb"xref\s*(\d+) (\d+)\s*?(\r\n|\n|\r)", head or b"")
        if not m:
            raise PDFError("no cross-reference table at offset %d" % offset)
        first, count = int(m.group(1)), int(m.group(2))
        body = offset + m.end()
        end = body + 20 * count
        line = 20
        # the blocks wholly or partly inside the table, in order
        for p in range(body // BS, (end - 1) // BS + 1):
            if self.L.at[p] is None:
                self._place_xref_block(p, body, first, count)
        raw = self.L.data(body, end)
        if raw is None:
            raise PDFError("could not rebuild the cross-reference table at %d" % offset)
        for i in range(count):
            e = raw[i * line:(i + 1) * line]
            mm = XREF_LINE.match(e)
            if not mm:
                raise PDFError("bad cross-reference line %r" % e)
            if mm.group(3) == b"n":
                self.objects[first + i] = (int(mm.group(2)), int(mm.group(1)))
        return end

    def read_trailer(self, end):
        """The trailer text after a table, as far as the placed blocks reach."""
        text = self._read_known(end, 4096)
        if b"trailer" not in text[:16]:
            self.anchor_text(end, b"trailer", "trailer after the table")
            text = self._read_known(end, 4096)
        return text[:text.find(b"startxref") if b"startxref" in text else len(text)]

    def _place_xref_block(self, p, body, first, count):
        """A block inside a table: its lines must fall at the right phase, and its 'in use'
        entries must point at real object headers."""
        best, best_score, tied = None, -1, []
        lo = p * BS
        for b in self.free.values():
            # the first whole line in this block starts here
            k0 = max(0, -(-(lo - body) // 20))
            s = body + 20 * k0 - lo
            score, ok = 0, True
            for k in range(k0, count):
                i = s + 20 * (k - k0)
                if i + 20 > BS:
                    break
                mm = XREF_LINE.match(b.data, i)
                if not mm or mm.end() != i + 20:
                    ok = False
                    break
                if mm.group(3) == b"n":
                    num, gen, off = first + k, int(mm.group(2)), int(mm.group(1))
                    hits = self.headers.get((num, gen), ())
                    if any(off % BS == pos for _blk, pos in hits):
                        score += 1
                    elif not self._straddles(num, gen, off):
                        ok = False
                        break
            if ok and s > 0:
                # a line cut by the block boundary must be the end of a valid line
                frag = b.data[:s]
                if not re.fullmatch(rb"[\d ]*[nf]?[ \r\n]*", frag):
                    ok = False
            if not ok:
                continue
            if score > best_score:
                best, best_score, tied = b, score, [b]
            elif score == best_score:
                tied.append(b)
        if best is None:
            raise PDFError("no block fits cross-reference position %d" % p)
        if len(tied) > 1 and not all(t.data == best.data for t in tied):
            if best_score == 0:
                raise PDFError("cannot tell which block is at cross-reference position %d" % p)
            raise PDFError("cross-reference position %d is ambiguous" % p)
        self.place(p, best, "cross-reference lines" + (" (identical copies)" if len(tied) > 1 else ""))

    def _straddles(self, num, gen, off):
        """An object header cut by a block boundary: some block ends with its start."""
        text = b"%d %d obj" % (num, gen)
        s = off % BS
        if s + len(text) <= BS:
            return False
        return any(b.data[s:] == text[:BS - s] for b in self.blocks)

    def place_objects(self):
        for num, (gen, off) in sorted(self.objects.items(), key=lambda kv: kv[1][1]):
            self.anchor_text(off, b"%d %d obj" % (num, gen), "object %d starts here" % num)

    def parse_objects(self):
        """For each placed object, read its dictionary and note its stream. An object cut by
        an unplaced block is completed by the one free block that makes it well formed."""
        self.dicts = {}
        for num, (gen, off) in sorted(self.objects.items(), key=lambda kv: kv[1][1]):
            head = b"%d %d obj" % (num, gen)
            text = self._read_known(off, 4096)
            if not text.startswith(head):
                continue
            body = text[len(head):]
            k = pdflex.object_ok(body)
            if k < 0:
                q = (off + len(text)) // BS
                if q < self.L.n and self.L.at[q] is None:
                    c = [b for b in self.free.values() if pdflex.object_ok(body + b.data) >= 0]
                    if len(c) == 1:
                        self.place(q, c[0], "completes object %d" % num)
                        body += c[0].data
                        k = pdflex.object_ok(body)
                if k < 0:
                    self.log("object", num, "could not be read")
                    continue
            self.dicts[num] = body[:k]
            sm = STREAM_KW.match(body, k)
            if not sm:
                continue
            d = body[:k]
            ref = re.search(rb"/Length\s+(\d+)\s+(\d+)\s+R", d)
            length = self._length_object(int(ref.group(1))) if ref else _int_after(d, b"/Length")
            if length is None:
                raise PDFError("object %d: stream length could not be read" % num)
            flt = re.search(rb"/Filter\s*/(\w+)", d)
            self.streams.append({
                "num": num, "gen": gen, "start": off + len(head) + sm.end(), "length": length,
                "filter": flt.group(1).decode() if flt else None, "dict": d,
            })

    def _length_object(self, num):
        """A stream length given as a separate object: "N 0 obj 1234 endobj"."""
        if num not in self.objects:
            return None
        gen, off = self.objects[num]
        m = re.match(rb"\d+ \d+ obj\s*(\d+)\s*endobj", self._read_known(off, 64))
        return int(m.group(1)) if m else None

    def _read_known(self, off, n):
        out = b""
        p = off // BS
        while len(out) < n and p < self.L.n and self.L.at[p] is not None:
            out += self.L.at[p].data
            p += 1
        return out[off % BS:off % BS + n]

    def place_stream_ends(self):
        for s in self.streams:
            e = s["start"] + s["length"]
            for kw in (b"\r\nendstream", b"\nendstream", b"\rendstream", b"endstream"):
                if self.candidates(e // BS, e, kw) or (self.L.at[e // BS] and self.fits(self.L.at[e // BS], e // BS, e, kw)):
                    self.anchor_text(e, kw, "end of stream %d" % s["num"])
                    break

    def find_security(self, trailer):
        m = re.search(rb"/Encrypt\s+(\d+)\s+(\d+)\s+R", trailer)
        if not m:
            return
        num = int(m.group(1))
        idm = re.search(rb"/ID\s*\[\s*<([0-9A-Fa-f]+)>", trailer)
        if num not in self.objects:
            raise PDFError("encryption dictionary %d is not in the cross-reference table" % num)
        d = self._read_known(self.objects[num][1], 1024)
        O, _ = pdfcrypt.literal_string(d, d.find(b"/O(") + 2)
        U, _ = pdfcrypt.literal_string(d, d.find(b"/U(") + 2)
        R = _int_after(d, b"/R") or 2
        length = _int_after(d, b"/Length") or 40
        self.sec = pdfcrypt.Security(O, U, _int_after(d, b"/P"), bytes.fromhex(idm.group(1).decode()), R, length)
        if not self.sec.ok:
            raise PDFError("the file needs a password; its streams cannot be checked")
        self.log("encryption", "RC4 %d-bit, empty user password works" % (8 * self.sec.n))

    # --- the whole job --------------------------------------------------

    def anchor(self):
        self.find_header()
        if self.eof:
            offsets = [int(self.eof[2].group(1))]
        else:
            m = re.search(rb"xref", self.L.at[0].data)
            offsets = [m.start()] if m else []
        trailers, seen = [], set()
        while offsets:
            off = offsets.pop(0)
            if off in seen:
                continue
            seen.add(off)
            end = self.read_xref(off)
            if self.eof and len(seen) == 1:
                self.place_end(end)
            self.place_objects()
            t = self.read_trailer(end)
            trailers.append(t)
            prev = _int_after(t, b"/Prev")
            if prev is not None:
                offsets.append(prev)
        self.trailer = b"".join(trailers)
        self.log("objects", "%d objects have a written offset" % len(self.objects))
        self.place_objects()
        self.find_security(self.trailer)
        self.parse_objects()
        self.place_stream_ends()
        return self.L
