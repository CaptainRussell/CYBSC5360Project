"""Ordering the blocks inside one PDF stream.

The stream's first and last blocks are already placed (the object header and the
"endstream" fix them). Every free block is tried at the next position, decrypted
with the key bytes for exactly that position, and judged by what the stream turns
into. The best few partial orderings are kept and extended (a beam search). At
the end the stream must close correctly: zlib's checksum for compressed data, the
end-of-image marker after the last row for a JPEG picture.

What "turns into something sensible" means depends on the stream:
  page drawings, object lists   PDF syntax with the right number of operands
  fonts, colour profiles        the format's own tables and checksums (binfmt)
  other compressed data         the compressor's habits (inflate)
  JPEG pictures                 the picture's rows join up (jpeg.junction)
  XML metadata                  readable text
"""

import re
import struct
import zlib

from . import binfmt, features, inflate, jpeg, pdflex

BS = 512
TIE_LIMIT = 300


class StreamError(Exception):
    pass


def xor(a, b):
    n = min(len(a), len(b))
    return (int.from_bytes(a[:n], "little") ^ int.from_bytes(b[:n], "little")).to_bytes(n, "little")


# --- kinds of stream ------------------------------------------------------------

class Kind:
    name = "?"

    @staticmethod
    def near(best, c):
        """Is cost c too close to the best to drop?"""
        return c == best


class FlateText(Kind):
    name = "compressed PDF text"

    def begin(self, head):
        z = zlib.decompressobj()
        bad, tot, carry = pdflex.check(z.decompress(head))
        return (z, carry, bad, tot)

    def extend(self, st, piece):
        z, carry, bad, tot = st
        zz = z.copy()
        try:
            o = zz.decompress(piece)
        except zlib.error:
            return None
        if zz.eof:
            return None
        b, t, carry = pdflex.check(o, carry)
        return (zz, carry, bad + b, tot + t)

    def cost(self, st):
        return (st[2] + 1) / (st[3] + 50)

    def finish(self, st, tail):
        zz = st[0].copy()
        try:
            zz.decompress(tail)
        except zlib.error:
            return False
        return zz.eof and not zz.unused_data


class FlateBinary(Kind):
    """Compressed binary data, judged by the format's self-checks when it has a checker,
    and always by the compressor's habits."""

    def __init__(self, checker=None, name="compressed binary data"):
        self.checker, self.name = checker, name

    def begin(self, head):
        return self._score(inflate.Inflater().feed(head))

    def _score(self, inf):
        if self.checker:
            bad, chk, _good = self.checker(bytes(inf.out) if inf.base == 0 else b"")
        else:
            bad, chk = 0, 0
        return (inf, (bad + 1) / (chk + 50))

    def extend(self, st, piece):
        inf = st[0].copy()
        try:
            inf.feed(piece)
        except inflate.InflateError:
            return None
        if inf.eof:
            return None
        return self._score(inf)

    def cost(self, st):
        inf = st[0]
        return (round(st[1], 4), (inf.slips + 1) / (inf.tokens + 20))

    @staticmethod
    def near(best, c):
        # the format checks often cannot tell several candidates apart until a later
        # table closes, so keep everything within reach of the best
        return c[0] <= best[0] * 1.5 + 0.002

    def finish(self, st, tail):
        inf = st[0].copy()
        try:
            inf.feed(tail)
        except inflate.InflateError:
            return False
        return inf.eof


class PlainText(Kind):
    """An uncompressed text stream, such as XML metadata: every byte must be text."""
    name = "XML text"

    def begin(self, head):
        return (self._bad(head), len(head))

    @staticmethod
    def _bad(piece):
        try:
            piece.decode("utf-8")
            return sum(1 for x in piece if x < 32 and x not in (9, 10, 13))
        except UnicodeDecodeError as e:
            # a character cut by the block boundary is fine; anything else is not
            if e.start >= len(piece) - 3 and e.reason == "unexpected end of data":
                return 0
            return len(piece)

    def extend(self, st, piece):
        b = self._bad(piece)
        if b > len(piece) // 8:
            return None
        return (st[0] + b, st[1] + len(piece))

    def cost(self, st):
        return (st[0] + 1) / (st[1] + 50)

    def finish(self, st, tail):
        return self._bad(tail) == 0


class JPEGStream(Kind):
    """A JPEG picture: first its header segments must chain correctly, then the picture
    data must decode and its rows must join up."""
    name = "JPEG picture"

    def begin(self, head):
        return self._advance({"raw": b"", "dec": None, "j": None, "tot": 0.0, "cnt": 0,
                              "new": (), "parent": None, "ov": {}}, head)

    def _advance(self, st, piece):
        if st["j"] is None:
            raw = st["raw"] + piece
            ok, end = header_check(raw)
            if not ok:
                return None
            st = self._thumbnail(st, raw)
            if st is None:
                return None
            if end is None:
                return dict(st, raw=raw)
            try:
                dec = jpeg.Decoder(jpeg.Header(raw[:end]))
            except (jpeg.JPEGError, KeyError, struct.error):
                return None
            st = dict(st, raw=b"", dec=dec, j=jpeg.State(len(dec.h.scan)))
            piece = raw[end:]
        dec = st["dec"]
        js = st["j"].copy()
        _dcs, info = dec.run(js, piece)
        if info["error"] or info["eoi"]:
            return None
        m, c = dec.junction(info["edges"], self._overlay(st))
        return {"raw": b"", "dec": dec, "j": js, "tot": st["tot"] + (m or 0) * c, "cnt": st["cnt"] + c,
                "new": info["edges"], "parent": st}

    def _thumbnail(self, st, raw):
        """Photoshop keeps a small JPEG thumbnail inside its header segment. While the header
        passes through it, the thumbnail is decoded and judged like any picture."""
        region = thumbnail_region(raw)
        if region is None:
            return st
        a, b = region
        fed = st.get("tfed", 0)
        if len(raw) <= a + fed or fed >= b - a:
            return st
        new = raw[a + fed:min(len(raw), b)]
        kind = JPEGStream()
        th = st.get("thumb")
        if th is None:
            th = kind.begin(new) if len(raw) < b else None
            if len(raw) >= b:
                th0 = kind.begin(b"")
                th = th0 if th0 is not None and kind.finish(th0, new) else None
        elif len(raw) >= b:
            th = th if kind.finish(th, new) else None
        else:
            th = kind.extend(th, new)
        if th is None:
            return None
        return dict(st, thumb=th, tfed=fed + len(new), tot=st["tot"] + th["tot"] - st.get("ttot", 0),
                    cnt=st["cnt"] + th["cnt"] - st.get("tcnt", 0), ttot=th["tot"], tcnt=th["cnt"])

    @staticmethod
    def _overlay(st):
        """The edges decoded so far on this path. A path's parent was itself extended
        earlier, so its overlay already exists; this one is built from it once."""
        if "ov" not in st:
            ov = dict(st["parent"]["ov"])
            for ci, idx, e in st["new"]:
                ov[(ci, idx)] = e
            st["ov"], st["parent"] = ov, None
        return st["ov"]

    def extend(self, st, piece):
        if st["j"] is not None and features.jpeg_scan_like(piece) == "no":
            return None
        return self._advance(st, piece)

    def cost(self, st):
        return st["tot"] / st["cnt"] if st["cnt"] else 0.0

    def finish(self, st, tail):
        if st["j"] is None:
            return False
        js = st["j"].copy()
        _dcs, info = st["dec"].run(js, tail, final=True)
        # the decoder stops once the last row is decoded; the end marker must follow
        return not info["error"] and js.done and (info["eoi"] or tail.rstrip(b"\0").endswith(b"\xff\xd9"))


JPEG_MARKERS = set(range(0xE0, 0xF0)) | {0xDB, 0xC4, 0xC0, 0xC1, 0xC2, 0xDD, 0xDA, 0xFE}


def header_check(d):
    """Walk JPEG header segments in d. -> (still possible, index after the SOS segment or None)."""
    if len(d) >= 2 and d[:2] != b"\xff\xd8":
        return False, None
    i = 2
    while i + 4 <= len(d):
        if d[i] != 0xFF or d[i + 1] not in JPEG_MARKERS:
            return False, None
        m = d[i + 1]
        ln = struct.unpack(">H", d[i + 2:i + 4])[0]
        if ln < 2:
            return False, None
        seg = d[i + 4:i + 2 + ln]
        if not _segment_ok(m, seg, ln - 2):
            return False, None
        if len(seg) < ln - 2:
            return True, None
        i += 2 + ln
        if m == 0xDA:
            return True, i
    return True, None


def thumbnail_region(d):
    """Where the JPEG data of a Photoshop thumbnail (resource 1036 or 1033) lies in d, or None."""
    i = 2
    while i + 4 <= len(d) and d[i] == 0xFF:
        m = d[i + 1]
        ln = struct.unpack(">H", d[i + 2:i + 4])[0]
        if m == 0xED and d[i + 4:i + 18] == b"Photoshop 3.0\0":
            j, end = i + 18, i + 2 + ln
            while j + 12 <= min(len(d), end) and d[j:j + 4] == b"8BIM":
                rid = struct.unpack(">H", d[j + 4:j + 6])[0]
                nl = d[j + 6]
                k = j + 7 + nl + ((1 + nl) % 2)
                if k + 4 > len(d):
                    return None
                size = struct.unpack(">I", d[k:k + 4])[0]
                if rid in (1033, 1036):
                    return (k + 4 + 28, k + 4 + size)
                j = k + 4 + size + (size % 2)
            return None
        if m == 0xDA:
            return None
        i += 2 + ln
    return None


def _segment_ok(m, seg, full):
    if m == 0xDB:
        j = 0
        while j < len(seg):
            if seg[j] >> 4 > 1 or seg[j] & 15 > 3:
                return False
            j += 1 + (128 if seg[j] >> 4 else 64)
        return j == full or len(seg) < full
    if m == 0xC4:
        j = 0
        while j + 17 <= len(seg):
            if seg[j] >> 4 > 1 or seg[j] & 15 > 3:
                return False
            n = sum(seg[j + 1:j + 17])
            if n > 256:
                return False
            j += 17 + n
        return j == full or len(seg) < full
    if m in (0xC0, 0xC1, 0xC2):
        if len(seg) >= 6:
            if seg[0] != 8 or seg[5] not in (1, 3, 4) or full != 6 + 3 * seg[5]:
                return False
        return True
    if m == 0xDA:
        if seg:
            return 1 <= seg[0] <= 4 and full == 4 + 2 * seg[0]
        return True
    if m == 0xED:
        return _irb_ok(seg, full)
    return True


def _irb_ok(seg, full):
    """Photoshop's APP13 segment: a chain of "8BIM" resources, each with its own size."""
    sig = b"Photoshop 3.0\0"
    if not sig.startswith(seg[:len(sig)]) and not seg.startswith(sig):
        return True                                     # some other APP13 use; not checked
    j = len(sig)
    while j < len(seg):
        if seg[j:j + 4] != b"8BIM"[:len(seg) - j]:
            return False
        if j + 7 > len(seg):
            return True
        nl = seg[j + 6]
        k = j + 6 + 1 + nl + ((1 + nl) % 2)          # the name is padded to an even length
        if k + 4 > len(seg):
            return True
        size = struct.unpack(">I", seg[k:k + 4])[0]
        j = k + 4 + size + (size % 2)
        if j > full:
            return False
    return True


def kind_for(pdfobj, s):
    num, d = s["num"], s["dict"]
    flt = s["filter"]
    if flt == "DCTDecode":
        return JPEGStream()
    if flt is None:
        return PlainText() if b"/Metadata" in d or b"XML" in d else None
    if flt != "FlateDecode" or b"/DecodeParms" in d and b"/Type/XRef" not in d:
        return None
    ref = re.compile(rb"%d\s+%d\s+R" % (num, s["gen"]))
    for other, od in pdfobj.dicts.items():
        m = ref.search(od)
        if not m:
            continue
        before = od[max(0, m.start() - 12):m.start()]
        if b"/FontFile2" in before:
            return FlateBinary(binfmt.truetype, "TrueType font")
        if b"ICCBased" in before:
            return FlateBinary(binfmt.icc, "colour profile")
        if b"/FontFile" in before:
            return FlateBinary(None, "font")
        if b"/Contents" in before or b"/Extends" in before:
            return FlateText()
    if b"/Type/ObjStm" in d:
        return FlateText()
    if b"/Subtype/Image" in d or b"/Type/XRef" in d or b"/S " in d:
        return FlateBinary()
    return FlateText()


# --- the search -------------------------------------------------------------------

def pool_for(pdfobj):
    """Free blocks that could be the inside of an encrypted stream: they look like noise,
    and they do not follow the JPEG rule for FF bytes (encryption breaks that rule)."""
    if pdfobj.sec is None:
        return list(pdfobj.free.values())
    return [b for b in pdfobj.free.values()
            if features.random_like(b.data) and features.jpeg_scan_like(b.data) != "yes"]


def order(pdfobj, s, beams=(6, 40, 300), log=None):
    """-> (kind name, [(position, Block)]) for the unknown blocks inside stream s."""
    kind = kind_for(pdfobj, s)
    L = pdfobj.L
    start, end = s["start"], s["start"] + s["length"]
    first, last = start // BS, (end - 1) // BS
    todo = [p for p in range(first, last + 1) if L.at[p] is None]
    if not todo:
        return (kind.name if kind else "?"), []
    if kind is None:
        raise StreamError("stream %d: no way to check this kind of stream" % s["num"])
    if L.at[first] is None or L.at[last] is None or todo != list(range(todo[0], todo[-1] + 1)):
        raise StreamError("stream %d: its first and last blocks must be placed first" % s["num"])
    ks = pdfobj.sec.keystream(s["num"], s["gen"], s["length"]) if pdfobj.sec else bytes(s["length"])

    def piece(p, data):
        lo, hi = max(start, p * BS), min(end, (p + 1) * BS)
        return xor(data[lo - p * BS:hi - p * BS], ks[lo - start:hi - start])

    head = b"".join(piece(p, L.at[p].data) for p in range(first, todo[0]))
    tail = b"".join(piece(p, L.at[p].data) for p in range(todo[-1] + 1, last + 1))
    pool = pool_for(pdfobj)
    err = None
    for beam in beams:
        try:
            return kind.name, list(zip(todo, _search(kind, head, tail, todo, pool, piece, beam, s["num"])))
        except StreamError as e:
            err = e
            if log:
                log("stream", s["num"], "widening the search after:", e)
    raise err


def _search(kind, head, tail, todo, pool, piece, beam, num):
    st0 = kind.begin(head)
    if st0 is None:
        raise StreamError("stream %d: its known start does not read correctly" % num)
    paths = [(st0, ())]
    for p in todo:
        pieces = {b.name: piece(p, b.data) for b in pool}
        nxt = []
        for st, chosen in paths:
            used = {b.name for b in chosen}
            for b in pool:
                if b.name in used:
                    continue
                st2 = kind.extend(st, pieces[b.name])
                if st2 is not None:
                    nxt.append((kind.cost(st2), st2, chosen + (b,)))
        if not nxt:
            raise StreamError("stream %d: no block continues it at position %d" % (num, p))
        nxt.sort(key=lambda x: x[0])
        best = nxt[0][0]
        paths, seen = [], set()
        for c, st2, chosen in nxt:
            key = tuple(b.data for b in chosen[-3:])     # blocks with equal bytes are interchangeable
            if key in seen:
                continue
            # keep the best `beam`, and every path about as good as the best (up to a limit)
            if len(paths) >= beam and (not kind.near(best, c) or len(paths) >= TIE_LIMIT):
                break
            seen.add(key)
            paths.append((st2, chosen))
    for st, chosen in paths:
        if kind.finish(st, tail):
            return chosen
    raise StreamError("stream %d: no ordering closes the stream correctly" % num)
