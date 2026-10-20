"""Build a tiny synthetic FAT16 image that plants one example of each triage finding.

  /docs/notes.docx                 password-protected Office file (OLE EncryptedPackage), odd timestamp
  /docs/figures/photo.jpg          large JPEG with a RAR archive (holding suspect.jpg) appended, not
                                   referenced by guide.html, 20x the size of its neighbours
  /legal/ReadMe.txt                a JPEG named .txt
  /bin/tool                        ELF program containing 'the pass is "hunter42x"', odd timestamp
  /mail.zip                        a ZIP holding an email
  /lib/*.dat                       300 ordinary files sharing one bulk-copy timestamp
  ._ files and a deleted entry     noise

Usage: python tests/make_fat_fixture.py OUT.img
"""

import io
import struct
import sys
import zipfile

SECTOR, SPC, RESERVED, NFATS, ROOT_ENTRIES = 512, 1, 1, 2, 512
CLUSTERS = 4400
FAT_SECTORS = (CLUSTERS + 2) * 2 // SECTOR + 1
ROOT_SECTORS = ROOT_ENTRIES * 32 // SECTOR
TOTAL = RESERVED + NFATS * FAT_SECTORS + ROOT_SECTORS + CLUSTERS * SPC

BULK = (2011, 9, 6, 3, 21, 58)
ODD = (2011, 9, 6, 14, 2, 0)


def jpeg(n_entropy, seed=7):
    body = bytes((seed * 31 + i * 17) % 254 for i in range(n_entropy))   # never 0xFF
    return (b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
            b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00" + body + b"\xff\xd9")


def rar4(name, payload):
    nb = name.encode()
    fh = struct.pack("<HBHHIIBIIBBHI", 0, 0x74, 0x8000, 32 + len(nb), len(payload), len(payload),
                     2, 0, 0, 29, 0x30, len(nb), 0x20) + nb
    return b"Rar!\x1a\x07\x00" + struct.pack("<HBHH", 0, 0x73, 0, 13) + b"\x00" * 6 + fh + payload


def encrypted_ooxml():
    hdr = bytearray(512)
    hdr[0:8] = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    struct.pack_into("<HHHHH", hdr, 24, 0x3E, 3, 0xFFFE, 9, 6)
    struct.pack_into("<IIIIIIIII", hdr, 40, 0, 1, 1, 0, 4096, 0xFFFFFFFE, 0, 0xFFFFFFFE, 0)
    struct.pack_into("<109I", hdr, 76, 0, *([0xFFFFFFFF] * 108))
    fat = struct.pack("<128I", 0xFFFFFFFD, 0xFFFFFFFE, *([0xFFFFFFFF] * 126))

    def de(name, typ, child=0xFFFFFFFF, right=0xFFFFFFFF):
        n = (name + "\x00").encode("utf-16-le")
        e = bytearray(128)
        e[:len(n)] = n
        struct.pack_into("<HBB", e, 64, len(n), typ, 1)
        struct.pack_into("<III", e, 68, 0xFFFFFFFF, right, child)
        struct.pack_into("<II", e, 116, 0xFFFFFFFE, 0)
        return bytes(e)

    dirs = de("Root Entry", 5, child=1) + de("EncryptionInfo", 2, right=2) + de("EncryptedPackage", 2) + bytes(128)
    return bytes(hdr) + fat + dirs


def dos_dt(t):
    y, mo, d, h, mi, s = t
    return ((h << 11) | (mi << 5) | (s // 2)), (((y - 1980) << 9) | (mo << 5) | d)


class Builder:
    def __init__(self):
        self.img = bytearray(TOTAL * SECTOR)
        self.fat = [0xFFF8, 0xFFFF] + [0] * CLUSTERS
        self.next = 2
        self.root = []        # raw 32-byte entries
        self.dirs = {"/": self.root}
        self.dir_cluster = {}

    def alloc(self, data):
        n = max(1, (len(data) + SECTOR * SPC - 1) // (SECTOR * SPC))
        first = self.next
        for k in range(n):
            c = first + k
            self.fat[c] = c + 1 if k < n - 1 else 0xFFFF
        self.next += n
        off = self.data_off(first)
        self.img[off:off + len(data)] = data
        return first

    def data_off(self, c):
        return (RESERVED + NFATS * FAT_SECTORS + ROOT_SECTORS + (c - 2) * SPC) * SECTOR

    @staticmethod
    def short(name, n):
        stem = "".join(ch for ch in name.upper() if ch.isalnum())[:6] or "F"
        ext = name.rsplit(".", 1)[1].upper()[:3] if "." in name else ""
        return ("%s~%d" % (stem, n)).ljust(8)[:8].encode() + ext.ljust(3).encode()

    def entries(self, name, attr, cluster, size, t, deleted=False):
        sn = self.short(name, len(self.dirs) + sum(len(v) for v in self.dirs.values()) % 9 + 1)
        csum = 0
        for b in sn:
            csum = (((csum & 1) << 7) + (csum >> 1) + b) & 0xFF
        u = name.encode("utf-16-le") + b"\x00\x00"
        chunks = [u[i:i + 26] for i in range(0, len(u), 26)]
        out = []
        for k, ch in enumerate(chunks, 1):
            ch = ch.ljust(26, b"\xff")
            seq = k | (0x40 if k == len(chunks) else 0)
            e = bytes([seq]) + ch[0:10] + b"\x0f\x00" + bytes([csum]) + ch[10:22] + b"\x00\x00" + ch[22:26]
            out.insert(0, e)
        tm, dt = dos_dt(t)
        e = sn + bytes([attr, 0, 0]) + struct.pack("<HHHHHHHI", tm, dt, dt, 0, tm, dt, cluster, size)
        out.append(e)
        if deleted:
            out = [b"\xe5" + x[1:] for x in out]
        return out

    def mkdir(self, path, t=BULK):
        parent, name = path.rsplit("/", 1)
        self.dirs[path] = []
        self.dir_cluster[path] = self.alloc(b"\x00" * 32768)
        self.dirs[parent or "/"].extend(self.entries(name, 0x10, self.dir_cluster[path], 0, t))

    def add(self, path, data, t=BULK, deleted=False):
        parent, name = path.rsplit("/", 1)
        c = self.alloc(data) if data else 0
        if deleted:   # a deleted file's clusters are free again in the FAT
            for k in range(c, self.next):
                self.fat[k] = 0
        self.dirs[parent or "/"].extend(self.entries(name, 0x20, c, len(data), t, deleted))

    def finish(self):
        bs = bytearray(512)
        bs[0:3] = b"\xeb\x3c\x90"
        bs[3:11] = b"TESTFAT "
        struct.pack_into("<HBHBHHBHHHII", bs, 11, SECTOR, SPC, RESERVED, NFATS, ROOT_ENTRIES, TOTAL, 0xF8,
                         FAT_SECTORS, 32, 2, 0, 0)
        bs[36] = 0x80
        bs[38] = 0x29
        struct.pack_into("<I", bs, 39, 0x12345678)
        bs[43:54] = b"TESTVOL    "
        bs[54:62] = b"FAT16   "
        bs[510:512] = b"\x55\xaa"
        self.img[0:512] = bs
        fat = struct.pack("<%dH" % len(self.fat), *self.fat)
        for k in range(NFATS):
            off = (RESERVED + k * FAT_SECTORS) * SECTOR
            self.img[off:off + len(fat)] = fat
        root_off = (RESERVED + NFATS * FAT_SECTORS) * SECTOR
        raw = b"".join(self.root)
        self.img[root_off:root_off + len(raw)] = raw
        for path, ents in self.dirs.items():
            if path == "/":
                continue
            raw = b"".join(ents)
            off = self.data_off(self.dir_cluster[path])
            self.img[off:off + len(raw)] = raw
        return bytes(self.img)


def build(out_path):
    b = Builder()
    for d in ("/docs", "/docs/figures", "/legal", "/bin", "/lib"):
        b.mkdir(d)
    for n in range(300):
        b.add("/lib/part%03d.dat" % n, bytes([65 + n % 26]) * (100 + n))
    b.add("/docs/guide.pdf", b"%PDF-1.4\n%%EOF\n")
    b.add("/docs/index.html", b"<html><body>See guide.pdf</body></html>")
    b.add("/docs/notes.docx", encrypted_ooxml(), t=ODD)
    b.add("/docs/._notes.docx", b"\x00\x05\x16\x07" + b"\x00" * 60)
    html = b"<html>" + b"".join(b'<img src="fig%d.jpg">' % k for k in range(5)) + b"</html>"
    b.add("/docs/figures/guide.html", html)
    for k in range(5):
        b.add("/docs/figures/fig%d.jpg" % k, jpeg(900 + 10 * k, seed=k))
    b.add("/docs/figures/photo.jpg", jpeg(20000, seed=9) + rar4("suspect.jpg", jpeg(300, seed=3)))
    b.add("/legal/ReadMe.txt", jpeg(500, seed=5))
    for k in range(4):
        b.add("/legal/LICENSE%d.txt" % k, b"Licensed under terms. " * 20)
    b.add("/bin/tool", b"\x7fELF\x01\x01\x01" + b"\x00\x13\x88" * 300 + b'the pass is "hunter42x".' + b"\x00" * 200, t=ODD)
    for k in range(5):
        b.add("/bin/util%d" % k, b"\x7fELF\x01\x01\x01" + bytes(range(256)) * 3)
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w") as z:
        z.writestr("mail/hello.eml", "From: a@example.com\r\nTo: b@example.com\r\nSubject: list\r\n\r\nSee attached.\r\n")
        z.writestr("mail/readme.txt", "plain text")
    b.add("/mail.zip", zbuf.getvalue())
    b.add("/old.txt", b"deleted content " * 10, deleted=True)
    with open(out_path, "wb") as fh:
        fh.write(b.finish())


if __name__ == "__main__":
    build(sys.argv[1])
