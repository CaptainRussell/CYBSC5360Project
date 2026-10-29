"""Putting a JPEG picture's blocks back in order.

The block with the JPEG signature comes first; the block with the end-of-image
marker comes last (inside picture data an FF byte is always followed by 00, so
the marker FF D9 appears only there). Every block between is placed by decoding
it as the continuation of the picture so far and measuring how well the new
8x8 pixel squares join the ones already above and to the left of them. A wrong
block either breaks the coding rules or arrives with its brightness, colour or
content out of line with its neighbours. Several partial orderings are kept and
extended at once (a beam search); the picture must end exactly at its last row.
"""

from . import streams
from .layout import Layout, PlaceError


class JPEGFileError(PlaceError):
    pass


def rebuild(pool, log=None, beams=(8, 24)):
    """pool: the blocks left after the other files. -> Layout of the picture."""
    log = log or (lambda *a: None)
    heads = [b for b in pool if b.data[:3] == b"\xff\xd8\xff"]
    if len(heads) != 1:
        raise JPEGFileError("expected one block starting a JPEG, found %d" % len(heads))
    head = heads[0]
    rest = [b for b in pool if b is not head]
    tails = [b for b in rest if b"\xff\xd9" in b.data]
    if len(tails) != 1:
        raise JPEGFileError("expected one block holding the end-of-image marker, found %d" % len(tails))
    tail = tails[0]
    middle = [b for b in rest if b is not tail]
    n = len(middle) + 2
    kind = streams.JPEGStream()
    kind.may_end = tail.data[:2] == b"\xff\xd9"
    st = kind.begin(head.data)
    if st is None:
        raise JPEGFileError("the first block does not start a valid JPEG header")
    if st["dec"] is not None:
        h = st["dec"].h
        log("picture", "%dx%d, %d components, %d coding units%s" % (
            h.width, h.height, len(h.scan), h.mcus, ", restart every %d" % h.restart if h.restart else ""))
    else:
        log("picture", "the header carries on past the first block")
    err = None
    for beam in beams:
        try:
            chosen = streams._search(kind, head.data, tail.data, list(range(1, n - 1)), middle,
                                     lambda p, d: d, beam, "picture")
            break
        except streams.StreamError as e:
            err = e
            log("picture", "widening the search after:", e)
    else:
        raise JPEGFileError(str(err))
    L = Layout(n)
    L.put(0, head, "starts with the JPEG signature")
    for p, b in enumerate(chosen, 1):
        L.put(p, b, "picture rows join up")
    L.put(n - 1, tail, "holds the end-of-image marker")
    return L
