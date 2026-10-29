"""A deflate decoder that can stop at any block boundary and that judges its input.

zlib can say whether bytes decompress, but almost any bytes do: a wrong block
fed into the middle of a stream is read with the stream's own code tables and
comes out as plausible-looking data. What a wrong block cannot imitate is the
compressor's habits. A real compressor always makes a repeat as long as it can,
and never spells out letter by letter a run it could have copied from just
before. Random bits break both habits within a few dozen symbols. This decoder
counts those breaks ("slips"); the right next block has almost none.

(RFC 1950/1951. Pure Python, so it is used only where zlib's answer is not enough.)
"""

import zlib

LEN_BASE = [3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59,
            67, 83, 99, 115, 131, 163, 195, 227, 258]
LEN_EXTRA = [0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0]
DIST_BASE = [1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513, 769,
             1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577]
DIST_EXTRA = [0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13]
CL_ORDER = [16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15]
WINDOW = 32768
NEAR = 4096          # a copyable run this close is one any compressor would find


class InflateError(Exception):
    pass


class _NeedMore(Exception):
    pass


def _table(lengths, kind="lens"):
    """-> (lookup list indexed by the next maxbits input bits, maxbits). Entry = (sym << 4) | len.
    As strict as zlib: an over-subscribed code is invalid, and so is an incomplete one
    (except a lone 1-bit code among literal/length or distance codes)."""
    maxbits = max(lengths) if lengths else 0
    if maxbits == 0:
        return [-1], 0
    count = [0] * 16
    for n in lengths:
        count[n] += 1
    count[0] = 0
    left = 1
    for n in range(1, 16):
        left = (left << 1) - count[n]
        if left < 0:
            raise InflateError("over-subscribed code")
    if left > 0 and (kind == "codes" or maxbits != 1):
        raise InflateError("incomplete code")
    code, nxt = 0, [0] * 16
    for n in range(1, 16):
        code = (code + count[n - 1]) << 1
        nxt[n] = code
    size = 1 << maxbits
    look = [-1] * size
    for sym, n in enumerate(lengths):
        if not n:
            continue
        c = nxt[n]
        nxt[n] += 1
        r = int(format(c, "0%db" % n)[::-1], 2)
        for k in range(r, size, 1 << n):
            look[k] = (sym << 4) | n
    return look, maxbits


_FIXED = None


def _fixed():
    global _FIXED
    if _FIXED is None:
        lit = [8] * 144 + [9] * 112 + [7] * 24 + [8] * 8
        _FIXED = (_table(lit), _table([5] * 32))        # codes 30 and 31 exist but are invalid
    return _FIXED


class Inflater:
    """Feed it compressed bytes a piece at a time; copy() it to try different next pieces."""

    __slots__ = ("inp", "ip", "bits", "nbits", "out", "base", "state", "lit", "dist", "final",
                 "eof", "slips", "tokens", "after_match", "lits", "stored_left", "adler", "summed")

    def __init__(self, zlib_header=True):
        self.inp, self.ip, self.bits, self.nbits = b"", 0, 0, 0
        self.out = bytearray()          # the last WINDOW bytes of output
        self.base = 0                   # total output before out[0]
        self.state = "zhead" if zlib_header else "block"
        self.lit = self.dist = None
        self.final = self.eof = False
        self.slips = self.tokens = 0
        self.after_match = None         # (source position) when the last token was a copy
        self.lits = []                  # output positions of the latest literals (pending checks)
        self.stored_left = 0
        self.adler, self.summed = 1, 0   # zlib's checksum of the output, and how far it reaches

    def copy(self):
        c = Inflater.__new__(Inflater)
        for k in Inflater.__slots__:
            setattr(c, k, getattr(self, k))
        c.out = bytearray(self.out)
        c.lits = list(self.lits)
        return c

    @property
    def total(self):
        return self.base + len(self.out)

    # --- bits -------------------------------------------------------------

    def _need(self, n):
        while self.nbits < n:
            if self.ip >= len(self.inp):
                raise _NeedMore
            self.bits |= self.inp[self.ip] << self.nbits
            self.ip += 1
            self.nbits += 8

    def _get(self, n):
        self._need(n)
        v = self.bits & ((1 << n) - 1)
        self.bits >>= n
        self.nbits -= n
        return v

    def _sym(self, table):
        look, maxbits = table
        while True:
            e = look[self.bits & ((1 << maxbits) - 1)] if self.nbits >= maxbits else -1
            if e >= 0 and (e & 15) <= self.nbits:
                self.bits >>= e & 15
                self.nbits -= e & 15
                return e >> 4
            if self.nbits >= maxbits:
                raise InflateError("invalid code")
            if self.ip >= len(self.inp):
                # fewer than maxbits left: a short code may still fit
                e = look[self.bits & ((1 << maxbits) - 1)]
                if e >= 0 and (e & 15) <= self.nbits:
                    self.bits >>= e & 15
                    self.nbits -= e & 15
                    return e >> 4
                raise _NeedMore
            self.bits |= self.inp[self.ip] << self.nbits
            self.ip += 1
            self.nbits += 8

    # --- output and the compressor's habits --------------------------------

    def _emit_literal(self, c):
        pos = self.total
        if self.after_match is not None:
            # the copy before this could have been one byte longer
            src = self.after_match
            if self._byte(src) == c:
                self.slips += 1
        self.after_match = None
        self._push(c)
        self.lits.append(pos)
        self._check_lits()

    def _emit_copy(self, length, dist):
        pos = self.total
        if dist > pos:
            raise InflateError("distance too far back")
        o, start = self.out, len(self.out) - dist
        if length <= dist:
            chunk = o[start:start + length]
        else:
            chunk = bytearray()
            for k in range(length):
                chunk.append(o[start + k] if start + k < len(o) else chunk[k - dist])
        for c in chunk:
            self._push(c)
        if length == 3 and dist > NEAR:
            self.slips += 1             # zlib and its kin drop 3-byte copies from this far
        self.after_match = pos + length - dist if length < 258 else None
        self._check_lits(flush=True)

    def _byte(self, absolute):
        i = absolute - self.base
        return self.out[i] if 0 <= i < len(self.out) else -1

    def _push(self, c):
        o = self.out
        o.append(c)
        if len(o) > 2 * WINDOW:
            self._sum()
            n = self.base + len(o)
            del o[:len(o) - WINDOW]
            self.base = n - len(o)

    def _sum(self):
        if self.summed < self.total:
            self.adler = zlib.adler32(bytes(self.out[self.summed - self.base:]), self.adler)
            self.summed = self.total

    def _check_lits(self, flush=False):
        """Two literals in a row, where the first starts 4 bytes already seen close by:
        a compressor would have copied them."""
        lits = self.lits
        while len(lits) >= 2 and self.total >= lits[0] + 4:
            a = lits[0]
            if lits[1] == a + 1:
                key = bytes(self.out[a - self.base:a - self.base + 4])
                prev = self._earlier(key, a)
                if prev is not None:
                    self.slips += 1
            lits.pop(0)
        if flush:
            self.lits = [] if not lits or self.total < lits[-1] + 4 else lits[-1:]

    def _earlier(self, key, a):
        """The latest position before a, within NEAR, where these 4 bytes start."""
        i = a - self.base
        j = self.out.rfind(key, max(0, i - NEAR), i + 3)
        return self.base + j if j >= 0 else None

    # --- decoding -----------------------------------------------------------

    def feed(self, data):
        """Decode as far as `data` allows. Raises InflateError on invalid data."""
        self.inp = self.inp[self.ip:] + data
        self.ip = 0
        while not self.eof:
            save = (self.ip, self.bits, self.nbits, self.final)
            try:
                self._step()
            except _NeedMore:
                self.ip, self.bits, self.nbits, self.final = save
                break
        return self

    def _step(self):
        st = self.state
        if st == "zhead":
            cmf, flg = self._get(8), self._get(8)
            if cmf & 15 != 8 or cmf >> 4 > 7 or ((cmf << 8) | flg) % 31 or flg & 32:
                raise InflateError("bad zlib header")
            self.state = "block"
        elif st == "block":
            if self.final:
                self.state = "adler"
                return
            # read the whole header at once so that stopping mid-header is clean
            ip, bits, nbits = self.ip, self.bits, self.nbits
            self.final = bool(self._get(1))
            kind = self._get(2)
            if kind == 0:
                self._get(self.nbits & 7)
                n, nn = self._get(16), self._get(16)
                if n != (~nn & 0xFFFF):
                    raise InflateError("bad stored length")
                self.stored_left, self.state = n, "stored"
            elif kind == 1:
                self.lit, self.dist = _fixed()
                self.state = "codes"
            elif kind == 2:
                try:
                    self._dynamic()
                except _NeedMore:
                    self.ip, self.bits, self.nbits, self.final = ip, bits, nbits, False
                    raise
                self.state = "codes"
            else:
                raise InflateError("bad block type")
        elif st == "stored":
            if self.stored_left:
                c = self._get(8)
                self.stored_left -= 1
                self.after_match = None
                self._push(c)
            else:
                self.state = "block"
        elif st == "codes":
            sym = self._sym(self.lit)
            if sym < 256:
                self.tokens += 1
                self._emit_literal(sym)
            elif sym == 256:
                self.state = "block"
            else:
                i = sym - 257
                if i >= 29:
                    raise InflateError("bad length code")
                length = LEN_BASE[i] + self._get(LEN_EXTRA[i])
                d = self._sym(self.dist)
                if d >= 30:
                    raise InflateError("bad distance code")
                dist = DIST_BASE[d] + self._get(DIST_EXTRA[d])
                self.tokens += 1
                self._emit_copy(length, dist)
        elif st == "adler":
            self._get(self.nbits & 7)
            want = 0
            for _ in range(4):
                want = (want << 8) | self._get(8)
            self._sum()
            if want != self.adler:
                raise InflateError("checksum does not match")
            self.eof = True

    def _dynamic(self):
        hlit, hdist, hclen = self._get(5) + 257, self._get(5) + 1, self._get(4) + 4
        if hlit > 286 or hdist > 30:
            raise InflateError("too many length or distance symbols")
        cl = [0] * 19
        for i in range(hclen):
            cl[CL_ORDER[i]] = self._get(3)
        clt = _table(cl, "codes")
        lens = []
        while len(lens) < hlit + hdist:
            s = self._sym(clt)
            if s < 16:
                lens.append(s)
            elif s == 16:
                if not lens:
                    raise InflateError("repeat with nothing before")
                lens += [lens[-1]] * (3 + self._get(2))
            elif s == 17:
                lens += [0] * (3 + self._get(3))
            else:
                lens += [0] * (11 + self._get(7))
        if len(lens) > hlit + hdist or not lens[256]:
            raise InflateError("bad code lengths")
        self.lit, self.dist = _table(lens[:hlit]), _table(lens[hlit:])
