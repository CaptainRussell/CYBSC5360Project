"""The positions of one file being rebuilt, and which block sits at each."""

BS = 512


class PlaceError(Exception):
    pass


class Layout:
    """Positions 0..n-1 of one file, and which block sits at each."""

    def __init__(self, n):
        self.n = n
        self.at = [None] * n            # position -> Block
        self.how = [None] * n           # position -> short reason it was placed there
        self.pos = {}                   # block name -> position

    def put(self, p, block, how):
        if not 0 <= p < self.n:
            raise PlaceError("position %d is outside the file" % p)
        if self.at[p] is not None:
            if self.at[p] is block:
                return
            raise PlaceError("position %d is already %s, cannot also be %s" % (p, self.at[p].name, block.name))
        if block.name in self.pos:
            raise PlaceError("%s is already at position %d" % (block.name, self.pos[block.name]))
        self.at[p], self.how[p], self.pos[block.name] = block, how, p

    def data(self, lo, hi):
        """Bytes lo..hi of the file, or None if any block in the range is still unknown."""
        out = bytearray()
        for p in range(lo // BS, (hi - 1) // BS + 1):
            if self.at[p] is None:
                return None
            out += self.at[p].data
        s = (lo // BS) * BS
        return bytes(out[lo - s:hi - s])

    def gaps(self):
        out, p = [], 0
        while p < self.n:
            if self.at[p] is None:
                q = p
                while q < self.n and self.at[q] is None:
                    q += 1
                out.append((p, q))
                p = q
            else:
                p += 1
        return out
