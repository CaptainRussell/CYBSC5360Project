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
    err, chosen = None, None
    try:
        chosen = backtracking_search(kind, head, tail, middle, beams, log)
    except streams.StreamError as e:
        err = e
        # best effort: let blocks follow the last row, and say which ones did
        log("picture", "no order ends exactly at the last row; keeping the best order found")
        kind.strict = False
        try:
            chosen = list(streams._search(kind, head.data, tail.data, list(range(len(middle))), middle,
                                          lambda p, d: d, beams[0], "picture"))
        except streams.StreamError as e2:
            err = e2
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


def backtracking_search(kind, head, tail, middle, beams, log, back=12, tries=4):
    """Beam search; at a dead end, keep the best path up to `back` blocks before it and
    search the rest again with a wider beam, backing up further each time it fails."""
    beam = beams[0]
    prefix = []
    for t in range(tries):
        st = kind.begin(head.data)
        for b in prefix:
            st = kind.extend(st, b.data)
            kind._overlay(st)
        used = {b.name for b in prefix}
        pool = [b for b in middle if b.name not in used]
        try:
            rest = streams._search(kind, head.data, tail.data, list(range(len(pool))), pool,
                                   lambda p, d: d, beam, "picture", start=(st, ()))
            return prefix + list(rest)
        except streams.StreamError as e:
            part = prefix + list(getattr(e, "partial", ()))
            keep = max(0, len(part) - back * (2 ** t))
            log("picture", "dead end after %d blocks; backing up to %d and widening the search" % (len(part), keep))
            prefix = part[:keep]
            beam = beams[min(len(beams) - 1, t + 1)] if t + 1 < len(beams) else beams[-1]
    raise streams.StreamError("picture: no order decodes the whole picture")


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


def repair(kind, head, tail, middle, log=None, rounds=40):
    """The beam search can join long correct runs in the wrong order (where the picture is
    flat, early on, many blocks fit). Find the weakest joins, try moving each run between
    them to another weak join, and keep any move that lowers the picture's total seam cost
    while it still decodes exactly to its last row."""
    log = log or (lambda *a: None)
    ev = evaluate(kind, head, tail, middle)
    if ev is None:
        return middle
    cost, incs, rows = ev
    for _r in range(rounds):
        srt = sorted(incs)
        med = srt[len(srt) // 2] or 1e-9
        cuts = {0, len(middle)} | {i for i, v in enumerate(incs) if v > 2.5 * med}
        if len(cuts) > 40:
            cuts = {0, len(middle)} | set(sorted(range(len(incs)), key=lambda i: -incs[i])[:38])
        # the top rows have nothing above them to check against, so a wrong run can start
        # there without a weak join to show it: every position in them may be a cut
        cuts = sorted(cuts | {i for i, r in enumerate(rows) if 0 <= r < 2})
        best = None
        segs = list(zip(cuts, cuts[1:]))
        for a, b in segs:
            seg = middle[a:b]
            rest = middle[:a] + middle[b:]
            for c in cuts:
                # insertion points in `rest` coordinates
                ins = c if c <= a else c - (b - a)
                if ins < 0 or ins > len(rest) or a <= c <= b:
                    continue
                trial = rest[:ins] + seg + rest[ins:]
                ev2 = evaluate(kind, head, tail, trial)
                if ev2 and ev2[0] < cost - 1e-9 and (best is None or ev2[0] < best[0]):
                    best = (ev2[0], trial, ev2[1], ev2[2])
        if best is None:
            break
        cost, middle, incs, rows = best
        log("picture", "moved a run of blocks; seam cost now %.3f" % cost)
    return middle
