"""Self-checks inside binary data that a PDF compresses: colour profiles and fonts.

Text streams can be judged by their grammar. Binary ones cannot, but the formats
inside them describe themselves. A colour profile (ICC) lists every part it holds
with its offset and size, and each part starts with a four-letter type. A TrueType
font lists its tables with a checksum for each, and a signed font carries its
signature as nested length-prefixed records (ASN.1 DER). A wrong block breaks
these descriptions almost at once.

Each checker takes all the output decoded so far and returns (bad bytes, checked
bytes, finished checksums that matched).
"""

import struct

ICC_TYPES = {b"desc", b"text", b"XYZ ", b"curv", b"view", b"meas", b"sig ", b"mluc", b"para",
             b"sf32", b"mft1", b"mft2", b"mAB ", b"mBA ", b"chrm", b"dtim", b"ncl2", b"clrt"}


def _printable(b):
    return all(32 <= x < 127 for x in b)


def icc(out):
    n = len(out)
    if n < 132:
        return 0, 0, 0
    bad = checked = 0
    size = struct.unpack(">I", out[:4])[0]
    if out[36:40] != b"acsp" or not 132 <= size <= 1 << 24:
        return n, n, 0
    count = struct.unpack(">I", out[128:132])[0]
    if count > 200:
        return n, n, 0
    tags = []
    for i in range(count):
        e = 132 + 12 * i
        if e + 12 > n:
            break
        sig, off, ln = struct.unpack(">4sII", out[e:e + 12])
        checked += 12
        if not _printable(sig) or off < 132 + 12 * count or off + ln > size:
            bad += 12
            continue
        tags.append((off, ln))
    covered = set()
    for off, ln in tags:
        if off + min(ln, 12) > n:
            continue
        t = out[off:off + 4]
        covered.add(off)
        end = min(off + ln, n)
        part = out[off:end]
        checked += len(part)
        if t not in ICC_TYPES or part[4:8] != b"\0\0\0\0"[:len(part[4:8])]:
            bad += len(part)
            continue
        if t == b"text":
            body = part[8:].rstrip(b"\0")
            if not _printable(body):
                bad += len(part)
        elif t == b"desc" and len(part) >= 12:
            k = struct.unpack(">I", part[8:12])[0]
            body = part[12:12 + k].rstrip(b"\0")
            if k > ln or not _printable(body):
                bad += len(part)
        elif t == b"XYZ ":
            for j in range(8, len(part) - 3, 4):
                v = struct.unpack(">i", part[j:j + 4])[0] / 65536
                if not -0.5 <= v <= 3:
                    bad += 4
        elif t == b"curv" and len(part) >= 12:
            vals = [struct.unpack(">H", part[j:j + 2])[0] for j in range(12, len(part) - 1, 2)]
            bad += 2 * sum(1 for a, b in zip(vals, vals[1:]) if b < a)
    # bytes between parts are padding
    spans = sorted((off, off + ln) for off, ln in tags)
    pos = 132 + 12 * count
    for a, b in spans:
        if a > pos:
            gap = out[pos:min(a, n)]
            checked += len(gap)
            bad += sum(1 for x in gap if x)
        pos = max(pos, b)
    return bad, checked, 0


# --- TrueType ---------------------------------------------------------------

def _checksum(data, head=False):
    data = data + b"\0" * (-len(data) % 4)
    words = list(struct.unpack(">%dI" % (len(data) // 4), data))
    if head and len(words) > 2:
        words[2] = 0                      # checkSumAdjustment is left out of head's own sum
    return sum(words) & 0xFFFFFFFF


def truetype(out):
    n = len(out)
    if n < 12:
        return 0, 0, 0
    if out[:4] not in (b"\0\1\0\0", b"true", b"OTTO"):
        return n, n, 0
    num = struct.unpack(">H", out[4:6])[0]
    if not 1 <= num <= 64:
        return n, n, 0
    bad = checked = good = 0
    tables = []
    for i in range(num):
        e = 12 + 16 * i
        if e + 16 > n:
            break
        tag, cs, off, ln = struct.unpack(">4sIII", out[e:e + 16])
        checked += 16
        if not _printable(tag) or off < 12 + 16 * num or ln > 1 << 24:
            bad += 16
            continue
        tables.append((off, ln, tag, cs))
    tables.sort()
    pos = 12 + 16 * num
    for off, ln, tag, cs in tables:
        if off > pos and pos < n:                     # padding between tables
            gap = out[pos:min(off, n)]
            checked += len(gap)
            bad += sum(1 for x in gap if x)
        pos = max(pos, off + ln)
        if off >= n:
            continue
        part = out[off:min(off + ln, n)]
        if off + ln <= n:
            checked += ln
            if _checksum(bytes(part), tag == b"head") == cs:
                good += 1
            else:
                bad += ln
            continue
        # a table still being decoded: what can be checked so far
        if tag == b"DSIG":
            b2, c2 = _dsig(part)
        elif tag == b"loca":
            vals = [struct.unpack(">H", part[j:j + 2])[0] for j in range(0, len(part) - 1, 2)]
            b2, c2 = 2 * sum(1 for a, b in zip(vals, vals[1:]) if b < a), len(part)
        elif tag == b"cvt ":
            vals = [struct.unpack(">h", part[j:j + 2])[0] for j in range(0, len(part) - 1, 2)]
            b2, c2 = 2 * sum(1 for v in vals if abs(v) > 5000), len(part)
        else:
            b2, c2 = 0, 0
        bad += b2
        checked += c2
    return bad, checked, good


def _dsig(part):
    if len(part) < 8:
        return 0, 0
    ver, num, flags = struct.unpack(">IHH", part[:8])
    if ver != 1 or num > 8:
        return len(part), len(part)
    bad = checked = 0
    for i in range(num):
        e = 8 + 12 * i
        if e + 12 > len(part):
            break
        fmt, ln, off = struct.unpack(">III", part[e:e + 12])
        if fmt != 1 or off + ln > 1 << 20:
            return len(part), len(part)
        if off + 8 <= len(part):
            sl = struct.unpack(">I", part[off + 4:off + 8])[0]
            if part[off:off + 4] != b"\0\0\0\0" or sl + 8 != ln:
                bad += len(part) - off
                continue
            b2, c2 = der(part, off + 8, off + 8 + sl)
            bad += b2
            checked += c2
    return bad, checked


# --- ASN.1 DER ----------------------------------------------------------------

TEXT_TAGS = {0x0C, 0x12, 0x13, 0x14, 0x16, 0x1A}
TIME_TAGS = {0x17, 0x18}


def der(b, i, end):
    """Walk DER records in b[i:end] (end may lie past the data so far).
    -> (bad bytes, checked bytes). Stops quietly where the data runs out."""
    avail = min(end, len(b))
    start = i
    while i < avail:
        h = _der_head(b, i, avail)
        if h is None:
            return 0, i - start                       # runs out mid-header
        if h is False:
            return avail - i, avail - start
        tag, body, ln = h
        if body + ln > end:
            return avail - i, avail - start
        if tag & 0x20:                                # constructed: its contents are records too
            bb, cc = der(b, body, body + ln)
            if bb:
                return bb + (body - i), (body - i) + cc + (i - start)
        else:
            seg = b[body:min(body + ln, avail)]
            if not _der_prim_ok(tag, seg, ln):
                return avail - i, avail - start
        i = body + ln
    return 0, avail - start


def _der_head(b, i, avail):
    if i + 2 > avail:
        return None
    tag = b[i]
    if tag & 0x1F == 0x1F or tag == 0:
        return False
    l0 = b[i + 1]
    if l0 < 0x80:
        return tag, i + 2, l0
    k = l0 & 0x7F
    if k == 0 or k > 3:
        return False
    if i + 2 + k > avail:
        return None
    ln = int.from_bytes(b[i + 2:i + 2 + k], "big")
    if ln < 0x80 or (k > 1 and ln < 1 << (8 * (k - 1))):
        return False                                  # DER always uses the shortest length
    return tag, i + 2 + k, ln


def _der_prim_ok(tag, seg, ln):
    t = tag & 0x1F if tag < 0x80 else None
    if tag >= 0x80:
        return True                                   # context-specific: opaque
    if t == 0x01:
        return ln == 1
    if t == 0x05:
        return ln == 0
    if t == 0x02:
        return ln >= 1
    if t == 0x06:
        return ln >= 1 and (not seg or seg[-1] < 0x80 or len(seg) < ln)
    if t in TEXT_TAGS:
        return all(32 <= x < 127 or x >= 0x80 for x in seg) if t == 0x0C else _printable(seg)
    if t in TIME_TAGS:
        return all(48 <= x <= 57 or x in b"Z+-." for x in seg)
    if t == 0x1E:
        return ln % 2 == 0
    return t in (0x03, 0x04, 0x10, 0x11)
