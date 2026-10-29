"""Loading a block set: a folder of block files, or a ZIP of one."""

import io
import os
import zipfile


class Block:
    __slots__ = ("name", "data", "index")

    def __init__(self, name, data, index):
        self.name, self.data, self.index = name, data, index

    def __repr__(self):
        return "Block(%s)" % self.name


def load(path):
    """-> list of Block, sorted by name. `path` is a folder of block files or a .zip holding one."""
    items = []
    if os.path.isdir(path):
        for root, _dirs, files in os.walk(path):
            for f in files:
                with open(os.path.join(root, f), "rb") as fh:
                    items.append((f, fh.read()))
    else:
        with zipfile.ZipFile(path) as z:
            for zi in z.infolist():
                if not zi.is_dir():
                    items.append((zi.filename.rsplit("/", 1)[-1], z.read(zi)))
    items.sort()
    return [Block(n, d, i) for i, (n, d) in enumerate(items)]
