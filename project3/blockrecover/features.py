"""Simple measurements of one block, used to sort blocks before any file is rebuilt.

These are the first-pass answer to "which file is this block from?". They are
cheap and need no other block, but they are only a guess: the rebuild that follows
is what settles each block.
"""

import math
from collections import Counter


def entropy(data):
    """Bits per byte, 0 (one repeated byte) to 8 (every byte value equally common)."""
    n = len(data)
    if not n:
        return 0.0
    s = 0.0
    for c in Counter(data).values():       # a plain loop: sum() of floats differs across Python versions
        s += c / n * math.log2(c / n)
    return -s


def text_share(data):
    return sum(32 <= x < 127 or x in (9, 10, 13) for x in data) / max(1, len(data))


def jpeg_scan_like(data):
    """Inside a JPEG picture every FF byte is followed by 00 (or a restart marker).
    -> 'yes' if there are 2+ FF bytes and all obey that, 'no' if one breaks it, 'unsure'."""
    ffs = [i for i in range(len(data) - 1) if data[i] == 0xFF]
    for i in ffs:
        if data[i + 1] != 0 and not 0xD0 <= data[i + 1] <= 0xD7:
            return "no"
    if data[-1:] == b"\xff":
        ffs.append(len(data) - 1)
    return "yes" if len(ffs) >= 2 else "unsure"


def random_like(data):
    """Encrypted or well-compressed bytes look like noise: near 8 bits per byte."""
    return entropy(data) >= 7.35


def compressed_like(data):
    """Compressed bytes are usually near 8 bits per byte too, but a stretch of a font or a
    picture can compress less well (7.1 has been seen), so this floor is lower. The
    decompressor rejects any wrong block anyway; this only keeps the search small."""
    return entropy(data) >= 6.5
