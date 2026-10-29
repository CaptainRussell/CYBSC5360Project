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
    # Blocks may follow the picture's last row, at a heavy cost per block: an order that
    # ends exactly is always preferred, and when none is found the best one is kept and
    # its extra blocks are reported as not confirmed.
    err, chosen = None, None
    kind.strict = False
    for beam in beams:
        try:
            chosen = list(streams._search(kind, head.data, tail.data, list(range(len(middle))), middle,
                                          lambda p, d: d, beam, "picture"))
            break
        except streams.StreamError as e:
            err = e
            log("picture", "widening the search after:", e)
    ev = evaluate(kind, head, tail, chosen) if chosen else None
    if ev:
        log("picture", "first pass: seam cost %.3f" % total_cost(kind, head, tail, chosen))
        items = consolidate(chosen, ev[1], ev[2])
    else:
        items = [Run([b]) for b in middle]
    # second pass: trusted runs as units, best-first with limited discrepancies, judged on
    # the whole picture
    best = lds(kind, head, tail, items, chosen, log, tries=max(4, min(40, 3000 // max(1, len(items)))))
    if best is None:
        if chosen is None:
            raise JPEGFileError(str(err) if err else "no order decodes the whole picture")
        best = chosen
    chosen = best
    over = after_last_row(kind, head, chosen)
    L = Layout(n)
    L.put(0, head, "starts with the JPEG signature")
    for p, b in enumerate(chosen, 1):
        L.put(p, b, "picture rows join up" if p - 1 < len(chosen) - over else
              "not confirmed: comes after the picture's last row in the best order found")
    L.exact = over == 0
    L.put(n - 1, tail, "holds the end-of-image marker")
    return L


class Run:
    """Blocks searched as one unit: a run that a first pass joined reliably."""
    __slots__ = ("parts", "name", "data")

    def __init__(self, parts):
        self.parts = parts
        self.name = parts[0].name if len(parts) == 1 else parts[0].name + "+" + str(len(parts) - 1)
        self.data = b"".join(b.data for b in parts)


def consolidate(flat, incs, rows, min_len=6):
    """Group the order into runs: a block stays joined to the one before when the join is
    as good as is typical and there were rows above it to check it against (near the top
    of a picture, flat areas let wrong blocks join as well as right ones)."""
    srt = sorted(incs)
    med = srt[len(srt) // 2] or 1e-9
    runs, cur = [], [flat[0]]
    for i in range(1, len(flat)):
        if incs[i] <= 1.5 * med and rows[i] >= 3:
            cur.append(flat[i])
        else:
            runs.append(cur)
            cur = [flat[i]]
    runs.append(cur)
    out = []
    for r in runs:
        if len(r) >= min_len:
            out.append(Run(r))
        else:
            out += [Run([b]) for b in r]
    return out


def after_last_row(kind, head, order):
    """How many blocks at the end of `order` come after the picture is complete."""
    st = kind.begin(head.data)
    for i, b in enumerate(order):
        if st["j"] is not None and st["j"].done:
            return len(order) - i
        st = kind.extend(st, b.data)
        if st is None:
            return len(order) - i
        kind._overlay(st)
    return 0


def total_cost(kind, head, tail, order):
    """The whole picture's seam cost: mean pixel jump over every join (None if it breaks)."""
    st = kind.begin(head.data)
    for b in order:
        st = kind.extend(st, b.data)
        if st is None:
            return None
        kind._overlay(st)
    if not kind.finish(st, tail.data):
        return None
    return st["tot"] / st["cnt"] if st["cnt"] else None


def lds(kind, head, tail, items, incumbent, log, tries=40):
    """Best-first with second thoughts. A greedy pass takes, at each step, the item (single
    block or trusted run) whose first block joins best, and notes how close the runner-up
    was. Then, starting with the closest calls, one step at a time is changed to its 2nd or
    3rd choice and the rest is redone greedily. Each complete order is scored on the whole
    picture; a better one becomes the new base and the process repeats."""
    best_cost = total_cost(kind, head, tail, incumbent) if incumbent else None
    best = incumbent

    def ranked(st, avail):
        out = []
        for it in avail:
            x = kind.extend(st, it.parts[0].data)
            if x is None:
                continue
            dc = x["cnt"] - st["cnt"]
            out.append(((x["tot"] - st["tot"]) / dc if dc else 0.0, it, x))
        out.sort(key=lambda t: t[0])
        return out

    def place(it, x):
        kind._overlay(x)
        for b in it.parts[1:]:
            x = kind.extend(x, b.data)
            if x is None:
                return None
            kind._overlay(x)
        return x

    def greedy(prefix, forced):
        """Replay prefix, take `forced` next, then greedy. -> (path, margins, cost) or None."""
        st = kind.begin(head.data)
        avail = list(items)
        path, margins = [], []
        for it in prefix + ([forced] if forced else []):
            x = kind.extend(st, it.parts[0].data)
            if x is None:
                return None
            st = place(it, x)
            if st is None:
                return None
            avail.remove(it)
            path.append(it)
            margins.append(None)
        while avail:
            r = ranked(st, avail)
            while r:
                st2 = place(r[0][1], r[0][2])
                if st2 is not None:
                    break
                r.pop(0)
            if not r:
                return path, margins, None              # a dead end: no item can come next
            margins.append((r[1][0] - r[0][0] if len(r) > 1 else 1e9, [t[1] for t in r[1:3]]))
            path.append(r[0][1])
            avail.remove(r[0][1])
            st = st2
        if not kind.finish(st, tail.data):
            return path, margins, None
        return path, margins, st["tot"] / st["cnt"]

    def better(r, than):
        if r is None:
            return False
        if than is None or than[2] is None:
            return r[2] is not None or (than is not None and len(r[0]) > len(than[0]))
        return r[2] is not None and r[2] < than[2] - 1e-9

    base = greedy([], None)
    if base is None:
        return best
    tried = 0
    while tried < tries:
        path, margins, cost = base
        if cost is not None and (best_cost is None or cost < best_cost - 1e-9):
            best_cost, best = cost, [b for it in path for b in it.parts]
            log("picture", "order found: seam cost %.3f" % cost)
        steps = sorted((m[0], i) for i, m in enumerate(margins) if m)
        improved = False
        for _m, i in steps:
            for alt in margins[i][1]:
                tried += 1
                r = greedy(path[:i], alt)
                if better(r, base):
                    base, improved = r, True
                    break
                if tried >= tries:
                    break
            if improved or tried >= tries:
                break
        if not improved:
            break
    path, margins, cost = base
    if cost is not None and (best_cost is None or cost < best_cost - 1e-9):
        best_cost, best = cost, [b for it in path for b in it.parts]
    log("picture", "second pass: seam cost %s after %d second thoughts" % (
        "%.3f" % best_cost if best_cost is not None else "none", tried))
    return best


def evaluate(kind, head, tail, middle):
    """Decode a whole order. -> (mean seam cost, cost of each block's joins) or None if it breaks."""
    st = kind.begin(head.data)
    incs, rows = [], []
    for b in middle:
        x = kind.extend(st, b.data)
        if x is None:
            return None
        kind._overlay(x)
        dc = x["cnt"] - st["cnt"]
        incs.append((x["tot"] - st["tot"]) / dc if dc else 0.0)
        rows.append(st["j"].mcu // st["dec"].h.mcux if st["j"] is not None else -1)
        st = x
    if not kind.finish(st, tail.data):
        return None
    return kind.cost(st), incs, rows
