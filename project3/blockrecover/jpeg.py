"""A baseline JPEG decoder that can stop at the end of any 512-byte block and carry on
from the same point with whichever block is tried next.

That is what ordering a JPEG's blocks needs: from the decoder's state after the
blocks placed so far, each candidate block is decoded on its own copy of the state,
and the right one is the block that (1) decodes without breaking the JPEG rules and
(2) continues the picture smoothly. Smoothness is judged on the DC coefficient of
each 8x8 block (its average brightness), compared with the blocks to its left and
above, which needs no inverse DCT.

Written from the JPEG standard (ITU-T T.81): baseline sequential, Huffman coded,
any sampling factors, optional restart markers. Progressive JPEGs are not handled.
"""

import math
import struct

ZIGZAG = [0, 1, 8, 16, 9, 2, 3, 10, 17, 24, 32, 25, 18, 11, 4, 5, 12, 19, 26, 33, 40, 48, 41, 34, 27, 20, 13, 6, 7, 14, 21,
          28, 35, 42, 49, 56, 57, 50, 43, 36, 29, 22, 15, 23, 30, 37, 44, 51, 58, 59, 52, 45, 38, 31, 39, 46, 53, 60, 61, 54,
          47, 55, 62, 63]


def _edge_basis():
    """For each zigzag position: its contribution to the 32 edge pixels of an 8x8 block
    (left column, right column, top row, bottom row), so edges need no full inverse DCT."""
    cu = lambda u: 1 / math.sqrt(2) if u == 0 else 1.0   # noqa: E731
    pts = [(0, y) for y in range(8)] + [(7, y) for y in range(8)] + [(x, 0) for x in range(8)] + [(x, 7) for x in range(8)]
    out = []
    for z in range(64):
        p = ZIGZAG[z]
        v, u = divmod(p, 8)
        out.append([0.25 * cu(u) * cu(v) * math.cos((2 * x + 1) * u * math.pi / 16) * math.cos((2 * y + 1) * v * math.pi / 16)
                    for x, y in pts])
    return out


EDGE = _edge_basis()


class JPEGError(Exception):
    pass


class Huffman:
    """Lookup on the next 16 bits: LOOK[bits] = (code length << 8) | symbol, or -1 for no code."""

    def __init__(self, counts, symbols):
        self.look = [-1] * 65536
        code, k = 0, 0
        for length in range(1, 17):
            for _ in range(counts[length - 1]):
                sym = symbols[k]
                k += 1
                lo = code << (16 - length)
                for i in range(lo, lo + (1 << (16 - length))):
                    self.look[i] = (length << 8) | sym
                code += 1
            code <<= 1


class Header:
    """Everything before the entropy-coded data: tables, frame, scan."""

    def __init__(self, data):
        if data[:2] != b"\xff\xd8":
            raise JPEGError("no SOI")
        self.qt, self.dc, self.ac = {}, {}, {}
        self.restart = 0
        i = 2
        while True:
            if i + 4 > len(data):
                raise JPEGError("header runs past the data given")
            if data[i] != 0xFF:
                raise JPEGError("expected a marker at %d" % i)
            m = data[i + 1]
            if m == 0xFF:
                i += 1
                continue
            ln = struct.unpack(">H", data[i + 2:i + 4])[0]
            seg = data[i + 4:i + 2 + ln]
            if len(seg) < ln - 2:
                raise JPEGError("header segment runs past the data given")
            if m == 0xDB:
                j = 0
                while j < len(seg):
                    pq, tq = seg[j] >> 4, seg[j] & 15
                    n = 128 if pq else 64
                    vals = seg[j + 1:j + 1 + n]
                    self.qt[tq] = list(struct.unpack(">64H", vals)) if pq else list(vals)
                    j += 1 + n
            elif m == 0xC4:
                j = 0
                while j < len(seg):
                    tc, th = seg[j] >> 4, seg[j] & 15
                    counts = list(seg[j + 1:j + 17])
                    n = sum(counts)
                    table = Huffman(counts, list(seg[j + 17:j + 17 + n]))
                    (self.ac if tc else self.dc)[th] = table
                    j += 17 + n
            elif m in (0xC0, 0xC1):
                _p, self.height, self.width, nc = struct.unpack(">BHHB", seg[:6])
                self.comps = []
                for k in range(nc):
                    cid, hv, tq = seg[6 + 3 * k], seg[7 + 3 * k], seg[8 + 3 * k]
                    self.comps.append({"id": cid, "h": hv >> 4, "v": hv & 15, "tq": tq})
            elif m == 0xC2 or 0xC3 <= m <= 0xCF and m not in (0xC4, 0xC8, 0xCC):
                raise JPEGError("only baseline JPEGs are handled (marker %02X)" % m)
            elif m == 0xDD:
                self.restart = struct.unpack(">H", seg[:2])[0]
            elif m == 0xDA:
                ns = seg[0]
                byid = {c["id"]: c for c in self.comps}
                self.scan = []
                for k in range(ns):
                    c = byid[seg[1 + 2 * k]]
                    c["td"], c["ta"] = seg[2 + 2 * k] >> 4, seg[2 + 2 * k] & 15
                    self.scan.append(c)
                self.scan_start = i + 2 + ln
                break
            i += 2 + ln
        hmax = max(c["h"] for c in self.comps)
        vmax = max(c["v"] for c in self.comps)
        self.mcux = -(-self.width // (8 * hmax))
        self.mcuy = -(-self.height // (8 * vmax))
        self.mcus = self.mcux * self.mcuy
        # the blocks of one MCU, in coding order: (component index, row offset, column offset)
        self.layout = []
        for ci, c in enumerate(self.scan):
            for v in range(c["v"]):
                for h in range(c["h"]):
                    self.layout.append((ci, v, h))
        self.bw = [self.mcux * c["h"] for c in self.scan]     # blocks per row, per component
        self.bh = [self.mcuy * c["v"] for c in self.scan]
        self.dcq = [self.qt[c["tq"]][0] for c in self.scan]  # DC quantizer (for the brightness range)


class State:
    """Where the decoder is: bits not yet used, position in the MCU and in the block, DC predictors."""
    __slots__ = ("buf", "nbits", "ff", "mcu", "bi", "k", "pred", "done", "rst", "next_rst", "coefs",
                 "marker", "await_rst")

    def __init__(self, ncomp):
        self.buf = self.nbits = 0
        self.ff = False          # the previous byte was FF (stuffing or a marker must follow)
        self.mcu = self.bi = self.k = 0
        self.pred = [0] * ncomp
        self.done = False        # all MCUs decoded
        self.rst = 0
        self.next_rst = 0
        self.coefs = []          # (zigzag position, dequantized value) of the block being decoded
        self.marker = None       # a restart marker read ahead of the bits before it
        self.await_rst = False   # a restart interval just ended; its marker must come next

    def copy(self):
        s = State.__new__(State)
        s.buf, s.nbits, s.ff, s.mcu, s.bi, s.k = self.buf, self.nbits, self.ff, self.mcu, self.bi, self.k
        s.pred, s.done, s.rst, s.next_rst = list(self.pred), self.done, self.rst, self.next_rst
        s.coefs = list(self.coefs)
        s.marker, s.await_rst = self.marker, self.await_rst
        return s


class Decoder:
    """Decodes the entropy-coded data piece by piece. DC values of finished 8x8 blocks are
    kept in `dcmap` (one array per component) once a piece is committed."""

    def __init__(self, header):
        self.h = header
        self.dcmap = [[None] * (self.h.bw[c] * self.h.bh[c]) for c in range(len(self.h.scan))]
        self.edges = [[None] * (self.h.bw[c] * self.h.bh[c]) for c in range(len(self.h.scan))]   # edge pixels of finished blocks
        self.q = [self.h.qt[c["tq"]] for c in self.h.scan]

    def block_pos(self, mcu, bi):
        ci, v, hh = self.h.layout[bi]
        c = self.h.scan[ci]
        row, col = divmod(mcu, self.h.mcux)
        return ci, (row * c["v"] + v) * self.h.bw[ci] + col * c["h"] + hh

    def run(self, state, piece, final=False):
        """Decode `piece` from `state` (which is changed). -> (dcs, info): dcs = [(component, index, dc)]
        for the blocks finished in this piece; info["error"] is set if the JPEG rules were broken,
        info["eoi"] if the end-of-image marker was met."""
        h, s = self.h, state
        dcs, info = [], {"error": None, "eoi": False, "symbols": 0}
        edges_out = []
        coefs = s.coefs
        nl = len(h.layout)
        ntables = [(h.dc[c["td"]].look, h.ac[c["ta"]].look) for c in h.scan]
        layout_ci = [l[0] for l in h.layout]
        buf, nbits, k, bi, mcu = s.buf, s.nbits, s.k, s.bi, s.mcu
        i, n = 0, len(piece)
        cur_dc = None
        while True:
            if s.await_rst:
                # the interval's last bits are padding; then the next restart marker
                if s.marker is None:
                    while i < n and s.marker is None:
                        b = piece[i]
                        i += 1
                        if s.ff:
                            s.ff = False
                            if 0xD0 <= b <= 0xD7:
                                s.marker = b
                            elif b == 0xD9:
                                info["error"] = "end of image before the last MCU"
                            else:
                                info["error"] = "data where a restart marker should be"
                            break
                        if b == 0xFF:
                            s.ff = True
                            continue
                        info["error"] = "data where a restart marker should be"
                        break
                    if info["error"]:
                        break
                    if s.marker is None:
                        break                       # needs the next piece
                if s.marker != 0xD0 + s.rst or nbits >= 8 or (nbits and buf & ((1 << nbits) - 1) != (1 << nbits) - 1):
                    info["error"] = "restart marker out of sequence"
                    break
                buf = nbits = 0
                s.pred = [0] * len(s.pred)
                s.rst = (s.rst + 1) & 7
                s.marker, s.await_rst = None, False
            # refill to at least 32 bits, handling FF stuffing and markers
            while nbits < 32 and i < n and s.marker is None:
                b = piece[i]
                i += 1
                if s.ff:
                    s.ff = False
                    if b == 0x00:
                        buf = (buf << 8) | 0xFF
                        nbits += 8
                        continue
                    if b == 0xD9:
                        info["eoi"] = True       # decode what is left in the bit buffer, then stop
                        final = True
                        i = n
                        break

                    if 0xD0 <= b <= 0xD7 and h.restart:
                        s.marker = b                # decode up to it, then restart
                        break
                    info["error"] = "marker FF%02X inside the image data" % b
                    break
                if b == 0xFF:
                    s.ff = True
                    continue
                buf = (buf << 8) | b
                nbits += 8
            if info["error"] or s.done:
                break
            if not (nbits >= 27 or ((final or s.marker is not None) and nbits > 0)):
                if s.marker is not None and not s.await_rst:
                    info["error"] = "restart marker in the middle of an interval"
                break
            ci = layout_ci[bi]
            dclook, aclook = ntables[ci]
            peek = (buf >> (nbits - 16)) & 0xFFFF if nbits >= 16 else (buf << (16 - nbits)) & 0xFFFF
            if k == 0:
                e = dclook[peek]
                if e < 0:
                    info["error"] = "no DC Huffman code"
                    break
                ln, size = e >> 8, e & 255
                if ln + size > nbits:
                    if final or s.marker is not None:
                        info["error"] = "image ends in the middle of a code"
                    break
                nbits -= ln
                if size:
                    v = (buf >> (nbits - size)) & ((1 << size) - 1)
                    nbits -= size
                    if v < (1 << (size - 1)):
                        v -= (1 << size) - 1
                else:
                    v = 0
                if size > 11:
                    info["error"] = "DC difference too large"
                    break
                s.pred[ci] += v
                cur_dc = s.pred[ci]
                coefs = [(0, cur_dc * h.dcq[ci])]
                if abs(cur_dc * h.dcq[ci]) > 2048 + h.dcq[ci]:
                    info["error"] = "brightness out of range"
                    break
                k = 1
            else:
                e = aclook[peek]
                if e < 0:
                    info["error"] = "no AC Huffman code"
                    break
                ln, rs = e >> 8, e & 255
                r, size = rs >> 4, rs & 15
                if ln + size > nbits:
                    if final or s.marker is not None:
                        info["error"] = "image ends in the middle of a code"
                    break
                nbits -= ln
                if size:
                    v = (buf >> (nbits - size)) & ((1 << size) - 1)
                    nbits -= size
                    if v < (1 << (size - 1)):
                        v -= (1 << size) - 1
                if size == 0:
                    if r == 15:
                        k += 16
                        if k > 63:
                            info["error"] = "coefficients run past 63"
                            break
                        continue
                    k = 64
                else:
                    k += r
                    if k > 63:
                        info["error"] = "coefficients run past 63"
                        break
                    coefs.append((k, v * self.q[ci][k]))
                    k += 1
            info["symbols"] += 1
            if k >= 64:
                # block finished
                if cur_dc is None:
                    cur_dc = s.pred[ci]
                c_i, idx = self.block_pos(mcu, bi)
                dcs.append((c_i, idx, s.pred[ci]))
                e = [128.0] * 32
                for z, val in coefs:
                    bz = EDGE[z]
                    for j in range(32):
                        e[j] += val * bz[j]
                edges_out.append((c_i, idx, e))
                coefs = []
                cur_dc = None
                k = 0
                bi += 1
                if bi == nl:
                    bi = 0
                    mcu += 1
                    if mcu == h.mcus:
                        s.done = True
                    elif h.restart and mcu % h.restart == 0:
                        s.await_rst = True
            buf &= (1 << nbits) - 1 if nbits else 0
        if info["eoi"] and not s.done and not info["error"]:
            info["error"] = "end of image before the last MCU"
        s.coefs = coefs
        info["edges"] = edges_out
        info["rest"] = n - i                 # bytes of the piece not read (after the last row)
        s.buf, s.nbits, s.k, s.bi, s.mcu = buf & ((1 << nbits) - 1) if nbits else 0, nbits, k, bi, mcu
        return dcs, info

    def commit(self, dcs, edges=()):
        for ci, idx, dc in dcs:
            self.dcmap[ci][idx] = dc
        for ci, idx, e in edges:
            self.edges[ci][idx] = e

    def seam(self, edges):
        """Mean |pixel jump| across the edges between each new block and its left and upper
        neighbours (new or already placed), in all three components, and how many edge pixels were
        compared. Natural pictures change gradually from one 8x8 block to the next; wrongly placed
        data does not, and data from elsewhere in the picture arrives with its brightness and colour
        shifted, which the row above shows."""
        local = {(ci, idx): e for ci, idx, e in edges}
        tot = cnt = 0
        for ci, idx, e in edges:
            w = self.h.bw[ci]
            placed = self.edges[ci]
            if idx % w:
                nb = local.get((ci, idx - 1)) or placed[idx - 1]
                if nb is not None:
                    for j in range(8):
                        tot += abs(e[j] - nb[8 + j])          # my left column against its right column
                    cnt += 8
            if idx >= w:
                nb = local.get((ci, idx - w)) or placed[idx - w]
                if nb is not None:
                    for j in range(8):
                        tot += abs(e[16 + j] - nb[24 + j])    # my top row against its bottom row
                    cnt += 8
        return (tot / cnt if cnt else None), cnt

    def junction(self, edges, extra=None):
        """Like seam(), but only edges shared with blocks already placed. A wrong block that holds
        real picture data looks natural inside itself; what gives it away is the join with what is
        already placed (its brightness and colour are offset, or its content does not continue).
        `extra` holds edges placed on one trial path but not committed: {(component, index): edges}."""
        tot = cnt = 0
        for ci, idx, e in edges:
            w = self.h.bw[ci]
            placed = self.edges[ci]
            for nidx, mine, theirs in ((idx - 1 if idx % w else -1, 0, 8), (idx - w, 16, 24)):
                if nidx < 0:
                    continue
                nb = placed[nidx]
                if nb is None and extra:
                    nb = extra.get((ci, nidx))
                if nb is None:
                    continue
                for j in range(8):
                    tot += abs(e[mine + j] - nb[theirs + j])
                cnt += 8
        return (tot / cnt if cnt else None), cnt

    def up_roughness(self, dcs, comps=(0,)):
        """Mean |DC jump| between each new block and the block above it (already placed), and how
        many such pairs there were. Only rows above count: a wrong block's brightness drifts, and
        only the row above, which came from the right blocks, shows it."""
        tot = cnt = 0
        for ci, idx, dc in dcs:
            if ci not in comps:
                continue
            w = self.h.bw[ci]
            if idx >= w:
                v = self.dcmap[ci][idx - w]
                if v is not None:
                    tot += abs(dc - v) * self.h.dcq[ci]
                    cnt += 1
        return (tot / cnt if cnt else None), cnt

    def roughness(self, dcs):
        """How much the new blocks' brightness jumps against their left and upper neighbours
        (mean absolute difference, in quantized DC units). Smooth pictures give small values."""
        local = {}
        tot = cnt = 0
        for ci, idx, dc in dcs:
            local[(ci, idx)] = dc
            w = self.h.bw[ci]
            for nb in ((idx - 1) if idx % w else None, idx - w if idx >= w else None):
                if nb is None:
                    continue
                v = local.get((ci, nb))
                if v is None:
                    v = self.dcmap[ci][nb]
                if v is not None:
                    tot += abs(dc - v) * self.h.dcq[ci]
                    cnt += 1
        return tot / cnt if cnt else 0.0, cnt
