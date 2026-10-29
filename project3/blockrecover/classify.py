"""First-pass guess at which file each block came from, from the block alone.

This is the quick answer, made before any file is rebuilt, and it is reported
next to the final answer so the two can be compared. The final answer comes from
the rebuild: a block belongs to a file when it has a place in that file.
"""

import re

from . import features

PDF_WORDS = re.compile(rb"\d{10} \d{5} [nf]|\d+ \d+ obj|endobj|endstream|/Type\s*/|/Filter|/Length \d|xref|trailer|%%EOF")


def guess(block):
    """-> (label, reason). label is 'PDF', 'Word', 'JPEG' or 'unsure'."""
    d = block.data
    if d.startswith(b"%PDF-"):
        return "PDF", "starts with the PDF signature"
    if d.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
        return "Word", "starts with the Compound File signature"
    if d.startswith(b"\xff\xd8\xff"):
        return "JPEG", "starts with the JPEG signature"
    if PDF_WORDS.search(d):
        return "PDF", "holds PDF keywords"
    if not any(d):
        return "unsure", "all zeros"
    ent = features.entropy(d)
    scan = features.jpeg_scan_like(d)
    if ent >= 7.35:
        if scan == "yes":
            return "JPEG", "noise-like, and every FF byte is followed by 00 as in JPEG picture data"
        if scan == "no":
            return "PDF", "noise-like, but breaks JPEG's FF rule: encrypted or compressed data"
        return "unsure", "noise-like, too few FF bytes to tell"
    if features.text_share(d) > 0.9:
        return "Word", "readable text"
    if scan == "yes" and ent > 6:
        return "JPEG", "every FF byte is followed by 00 as in JPEG picture data"
    return "Word", "structured binary (tables, numbers, small values)"
