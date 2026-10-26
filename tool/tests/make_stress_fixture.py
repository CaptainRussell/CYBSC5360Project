"""A large synthetic drive full of awkward files, for checking that the browser version
agrees with the Python version on more than the planted examples.

It holds every file type the checks look at, in valid, borderline and broken forms:
ZIPs (stored, deflated, ZIP64, UTF-8 names, comments, prepended data, a flipped
byte, a wrong local name, overlapping entries, truncated directories, an
encrypted flag), Office files (Word with and without the encrypted flag, Excel
with FILEPASS, damaged containers), images and PDFs with and without data after
their end marker, RAR headers, every "password is" variant the phrase rule has to
judge (spacing, case, punctuation, non-ASCII bytes next to the words), emails, web
pages that name their neighbours, folders where one file is the odd one out, odd
timestamps, deleted files, Mac and Windows clutter, and a few hundred seeded random
files that start with a real signature and then go wrong.

    python tests/make_stress_fixture.py fat OUT.img [SEED]
    python tests/make_stress_fixture.py ntfs OUT.img [SEED]   (needs mkntfs and ntfs-3g)
"""

import io
import os
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_fat_fixture as F  # noqa: E402

BULK = (2015, 3, 14, 9, 26, 52)
SIGS = [b"\xff\xd8\xff\xe0", b"\x89PNG\r\n\x1a\n", b"GIF89a", b"%PDF-1.5\n", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", b"PK\x03\x04",
        b"PK\x05\x06", b"Rar!\x1a\x07\x00", b"7z\xbc\xaf\x27\x1c", b"\x1f\x8b\x08", b"BZh9", b"MZ\x90\x00", b"\x7fELF", b"\xca\xfe\xba\xbe",
        b"SQLite format 3\x00", b"ID3\x03", b"BM", b"\x00\x00\x01\x00", b"II*\x00", b"{\\rtf1", b"<?xml version", b"<html>"]
EXTS = ["jpg", "png", "gif", "pdf", "doc", "docx", "xls", "zip", "rar", "7z", "exe", "dll", "txt", "html", "xml", "dat", "bin",
        "jar", "bmp", "ico", "mp3", "db", "", "log", "csv", "odt", "gz", "class", "eml", "TXT", "Jpg"]


def cfb(streams, mini=False):
    """A small Compound File (the container of Word/Excel 97 files) holding the given streams.

    Streams of 4096 bytes or more go in regular sectors; with mini=True small ones go in the mini stream."""
    ss = 512
    sectors, fat = [], []

    def put(data):
        start = len(sectors)
        n = max(1, (len(data) + ss - 1) // ss)
        for k in range(n):
            sectors.append(data[k * ss:(k + 1) * ss].ljust(ss, b"\x00"))
            fat.append(start + k + 1 if k < n - 1 else 0xFFFFFFFE)
        return start

    entries = [("Root Entry", 5, 0xFFFFFFFE, 0)]
    ministream, minifat = b"", []
    for name, data in streams:
        if mini and len(data) < 4096:
            start = len(ministream) // 64
            n = max(1, (len(data) + 63) // 64)
            for k in range(n):
                minifat.append(start + k + 1 if k < n - 1 else 0xFFFFFFFE)
            ministream += data.ljust(n * 64, b"\x00")
            entries.append((name, 2, start, len(data)))
        else:
            entries.append((name, 2, put(data), len(data)))
    if ministream:
        entries[0] = ("Root Entry", 5, put(ministream), len(ministream))
    mf_start = put(struct.pack("<%dI" % len(minifat), *minifat).ljust(ss, b"\xff")) if minifat else 0xFFFFFFFE
    dirdata = b""
    for k, (name, typ, start, size) in enumerate(entries):
        n = (name + "\x00").encode("utf-16-le")
        e = bytearray(128)
        e[:len(n)] = n
        struct.pack_into("<HBB", e, 64, len(n), typ, 1)
        struct.pack_into("<III", e, 68, 0xFFFFFFFF, k + 1 if 0 < k < len(entries) - 1 else 0xFFFFFFFF,
                         1 if k == 0 and len(entries) > 1 else 0xFFFFFFFF)
        struct.pack_into("<II", e, 116, start, size)
        dirdata += bytes(e)
    dir_start = put(dirdata)
    fat_sector = len(sectors)
    fat.append(0xFFFFFFFD)
    sectors.append(b"")
    fat_bytes = struct.pack("<%dI" % len(fat), *fat).ljust(ss, b"\xff")[:ss]
    sectors[fat_sector] = fat_bytes
    hdr = bytearray(512)
    hdr[0:8] = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    struct.pack_into("<HHHHH", hdr, 24, 0x3E, 3, 0xFFFE, 9, 6)
    struct.pack_into("<IIIIIIIII", hdr, 40, 0, 1, dir_start, 0, 4096, mf_start, 1 if minifat else 0, 0xFFFFFFFE, 0)
    struct.pack_into("<109I", hdr, 76, fat_sector, *([0xFFFFFFFF] * 108))
    return bytes(hdr) + b"".join(sectors)


def word97(encrypted):
    fib = bytearray(4096)
    struct.pack_into("<HH", fib, 0, 0xA5EC, 0xC1)
    struct.pack_into("<H", fib, 10, 0x0100 if encrypted else 0x0000)
    return cfb([("WordDocument", bytes(fib)), ("1Table", b"\x00" * 4096)])


def excel97(encrypted):
    recs = struct.pack("<HH", 0x0809, 16) + b"\x00" * 16
    if encrypted:
        recs += struct.pack("<HH", 0x002F, 6) + b"\x01\x00\x02\x00\x03\x00"
    recs += struct.pack("<HH", 0x0042, 2) + b"\xe4\x04" + struct.pack("<HH", 0x000A, 0)
    return cfb([("Workbook", recs.ljust(4096, b"\x00"))], mini=False)


def zip_bytes(members, compression=zipfile.ZIP_DEFLATED, comment=b"", zip64=False):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression) as z:
        for name, data in members:
            if zip64:
                with z.open(zipfile.ZipInfo(name, date_time=(2014, 2, 3, 4, 5, 6)), "w", force_zip64=True) as fh:
                    fh.write(data)
            else:
                zi = zipfile.ZipInfo(name, date_time=(2013, 7, 8, 9, 10, 12))
                zi.compress_type = compression
                z.writestr(zi, data)
        z.comment = comment
    return buf.getvalue()


def set_encrypted_flag(z, which=0):
    """Set the 'encrypted' bit of one entry, in both its local and central headers."""
    b = bytearray(z)
    loc = [i for i in range(len(b) - 3) if b[i:i + 4] == b"PK\x03\x04"]
    cen = [i for i in range(len(b) - 3) if b[i:i + 4] == b"PK\x01\x02"]
    b[loc[which] + 6] |= 1
    b[cen[which] + 8] |= 1
    return bytes(b)


def tree(seed=1):
    """-> [(path, data, time, deleted)] in the order they are written to the drive."""
    rnd = random.Random(seed)
    out = []

    def add(path, data, t=BULK, deleted=False):
        out.append((path, data, t, deleted))

    J = F.jpeg
    # --- passwords: the phrase rule and its edge cases -----------------------------------------
    phrases = [b"the password is Tr0ub4dor&3 for the zip", b"PASSWORD IS HunterTwo2", b"pass  was  'Abc12345'.", b"secret is\xa0Tr0ub4dor",
               b"secret is:= \"CorrectHorse9\"", b"the pin is 4321", b"the password is incorrect", b"pwd is ab", b"passphrase was averyveryverylongpassphrase",
               b"Your password is required", b"pass\tis\tMixedCase", b"the passcode is \x93Quoted7\x94", b"PassWord Is xYz!!!!", b"compass is north5",
               b"pass is ok.", b"the password is lowercaseonly", b"password was Ab1;", b"\xe9password is Caf\xe9123", b"pin was 0000000000000",
               b"password:is hidden9", b"password is\r\nNextLine99", b"secret was EMPTY1", b"pass is passw0rd" * 3]
    for k, p in enumerate(phrases):
        add("/notes/note%02d.txt" % k, b"Some notes.\n" * (k % 4) + p + b"\nEnd.\n")
    add("/bin/helper.exe", b"MZ\x90\x00" + b"\x00" * 60 + b"PE\x00\x00" + b"\x4c\x01" * 200 + b"pass is Sesame42x" + b"\x00" * 100)
    add("/bin/nope.exe", b"MZ" + b"\x01" * 700)                                     # MZ without PE header: not a program
    add("/bin/small.exe", b"MZ" + b"\x01" * 100)                                    # small MZ: a program
    # --- emails and text kinds ------------------------------------------------------------
    add("/mail/one.eml", b"From: a@b.c\r\nTo: d@e.f\r\nSubject: hi\r\n\r\nbody")
    add("/mail/two.txt", b"Received: x\nX-Mailer: y\nhello")
    add("/mail/three.txt", b"  \n\tFrom: a\nTo: b\n")
    add("/mail/notmail.txt", b"From: only one header\nbody text")
    add("/mail/utf8.txt", "Grüße, naïve café – “quotes”\n".encode("utf-8") * 30)
    add("/mail/latin.txt", "Gr\xfc\xdfe caf\xe9 ".encode("latin-1") * 200)
    add("/mail/page.xml", b"   <?XML version='1.0'?><a/>")
    add("/mail/page.htm", b"\n<!DOCTYPE HTML><html></html>")
    add("/mail/binaryish.txt", bytes(rnd.randrange(256) for _ in range(5000)))
    # --- a documented folder with an orphan (C6) and odd ones out (C5) ----------------------
    names = ["chart%d.gif" % k for k in range(8)]
    add("/manual/index.html", b"<html>" + b"".join(b'<img src="%s">' % n.encode() for n in names[:7]) + b"</html>")
    for n in names:
        add("/manual/" + n, b"GIF89a\x01\x00\x01\x00\x00\x00\x00;" + b"\x00" * 20)
    add("/manual/holiday.jpg", J(3000, seed=4))
    add("/manual/readme.TXT", b"see chart1.gif and CHART2.GIF and Index.Html")
    for k in range(6):
        add("/photos/p%d.jpg" % k, J(500 + 7 * k, seed=10 + k))
    add("/photos/big.jpg", J(40000, seed=30))
    add("/photos/even.jpg", J(1200, seed=31))
    # --- end markers (C2) --------------------------------------------------------------------
    add("/img/tail_zip.jpg", J(2000, seed=1) + zip_bytes([("inner.txt", b"hidden")]))
    add("/img/tail_junk.jpg", J(2000, seed=2) + bytes(rnd.randrange(256) for _ in range(300)))
    add("/img/tail_pad.jpg", J(2000, seed=3) + b"\x00" * 500 + b"\xff" * 20)
    add("/img/tail_short.jpg", J(2000, seed=5) + b"abc")
    add("/img/tail_7z.jpg", J(2000, seed=6) + b"x" * 100 + b"7z\xbc\xaf\x27\x1c" + b"\x00" * 50)
    add("/img/tail_rar.jpg", J(2000, seed=7) + F.rar4("secret.docx", b"payload" * 50))
    png = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + b"\x00" * 13 + b"\x00" * 4 + struct.pack(">I", 0) + b"IEND" + b"\xaeB`\x82"
    add("/img/ok.png", png)
    add("/img/tail.png", png + b"PK\x03\x04" + b"z" * 60)
    add("/img/broken.png", png[:30])
    gif = b"GIF89a\x02\x00\x02\x00\x80\x00\x00" + b"\x00" * 6 + b"\x2c\x00\x00\x00\x00\x02\x00\x02\x00\x00\x02\x02\x44\x01\x00\x3b"
    add("/img/ok.gif", gif)
    add("/img/tail.gif", gif + b"%PDF-1.4 hidden" + b"q" * 40)
    add("/img/trunc.gif", gif[:12])
    pdf = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
    add("/docs/a.pdf", pdf)
    add("/docs/short_tail.pdf", pdf + b"x" * 1000)
    add("/docs/long_tail.pdf", pdf + b"y" * 5000)
    add("/docs/zip_tail.pdf", pdf + b"PK\x03\x04" + b"w" * 40)
    add("/docs/locked.pdf", b"%PDF-1.6\n" + b"<</Encrypt 5 0 R>>" + pdf)
    add("/docs/noeof.pdf", b"%PDF-1.3 no end")
    # --- Office --------------------------------------------------------------------------------
    add("/office/plain.doc", word97(False))
    add("/office/locked.doc", word97(True))
    add("/office/plain.xls", excel97(False))
    add("/office/locked.xls", excel97(True))
    add("/office/locked.docx", F.encrypted_ooxml())
    add("/office/mini.doc", cfb([("WordDocument", b"\xec\xa5\xc1\x00" + b"\x00" * 6 + b"\x00\x01" + b"\x00" * 100)], mini=True))
    add("/office/ppt.ppt", cfb([("PowerPoint Document", b"\x00" * 4096)]))
    add("/office/other.doc", cfb([("Something", b"\x00" * 4096)]))
    add("/office/broken.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 100)
    add("/office/headeronly.xls", F.encrypted_ooxml()[:600])
    add("/office/realdocx.docx", zip_bytes([("[Content_Types].xml", b"<Types/>"), ("word/document.xml", b"<w/>")]))
    add("/office/doc_named_txt.txt", word97(True))
    add("/office/odt.odt", b"PK\x03\x04" + b"\x00" * 26 + b"mimetypeapplication/vnd.oasis.opendocument.text")
    # --- ZIPs, valid and broken ------------------------------------------------------------------
    mail = b"From: x@y.z\r\nTo: q@r.s\r\nSubject: s\r\n\r\nhi"
    add("/zips/plain.zip", zip_bytes([("a.txt", b"hello " * 100), ("dir/", b""), ("dir/b.eml", mail)]))
    add("/zips/stored.zip", zip_bytes([("s.txt", b"stored data"), ("pic.jpg", J(400, seed=8))], zipfile.ZIP_STORED))
    add("/zips/utf8.zip", zip_bytes([("café/naïve.txt", b"unicode name"), ("日本.txt", b"x")]))
    add("/zips/comment.zip", zip_bytes([("c.txt", b"commented")], comment=b"archive comment PK\x05\x06 inside"))
    add("/zips/zip64.zip", zip_bytes([("big.txt", b"z" * 3000), ("letter.docx", zip_bytes([("[Content_Types].xml", b"<T/>")]))], zip64=True))
    add("/zips/locked.zip", set_encrypted_flag(zip_bytes([("mypuppy.jpg", J(300, seed=9)), ("free.txt", b"free")])))
    good = zip_bytes([("x.txt", b"x data " * 50), ("y.txt", b"y data " * 50)])
    add("/zips/prepended.zip", b"JUNKJUNK" * 16 + good)
    flipped = bytearray(good)
    flipped[45] ^= 0xFF
    add("/zips/badcrc.zip", bytes(flipped))
    wrong = bytearray(good)
    wrong[30] = ord("q")
    add("/zips/wrongname.zip", bytes(wrong))
    add("/zips/truncated.zip", good[:len(good) - 30])
    add("/zips/nocd.zip", good[:60])
    cen = good.find(b"PK\x01\x02")
    overl = bytearray(good)
    second = good.find(b"PK\x01\x02", cen + 4)
    struct.pack_into("<I", overl, second + 42, 0)                       # both entries claim offset 0
    add("/zips/overlap.zip", bytes(overl))
    add("/zips/jar.jar", zip_bytes([("META-INF/MANIFEST.MF", b"Manifest"), ("a.class", b"\xca\xfe\xba\xbe")]))
    add("/zips/empty.zip", zip_bytes([]))
    add("/zips/nested.zip", zip_bytes([("inner.zip", good), ("pw.txt", b"the password is Nested123")]))
    add("/zips/__MACOSX_inside.zip", zip_bytes([("__MACOSX/._a.txt", b"\x00\x05\x16\x07"), ("a.txt", b"a")]))
    add("/zips/rar_locked.rar", b"Rar!\x1a\x07\x00" + struct.pack("<HBHH", 0, 0x73, 0x0080, 13) + b"\x00" * 6)
    add("/zips/rar_ok.rar", F.rar4("ok.txt", b"fine"))
    # --- misc types ---------------------------------------------------------------------------------
    add("/misc/good.bmp", b"BM" + struct.pack("<I", 70) + b"\x00" * 64)
    add("/misc/bad.bmp", b"BM" + struct.pack("<I", 9) + b"\x00" * 64)
    add("/misc/icon.ico", b"\x00\x00\x01\x00\x01\x00" + b"\x00" * 30)
    add("/misc/noticon.ico", b"\x00\x00\x01\x00\x00\x00" + b"\x00" * 30)
    add("/misc/song.mp3", b"ID3\x03" + b"\x00" * 500)
    add("/misc/data.db", b"SQLite format 3\x00" + b"\x00" * 500)
    add("/misc/arch.gz", b"\x1f\x8b\x08\x00" + b"\x00" * 50)
    add("/misc/Thumbs.db", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 600)
    add("/misc/desktop.ini", b"[.ShellClassInfo]")
    add("/misc/.DS_Store", b"\x00\x00\x00\x01Bud1" + b"\x00" * 50)
    add("/misc/._helper", b"\x00\x05\x16\x07" + b"\x00" * 40)
    add("/misc/.BC.T_abc", b"leftover")
    add("/misc/_B~1.T_abc", b"leftover2")
    add("/misc/empty.txt", b"")
    add("/misc/renamed.txt", png)
    add("/misc/text.jpg", b"just text, not a photo")
    add("/misc/....", b"dots only")
    add("/misc/noext", J(100, seed=12))
    add("/misc/.hidden.cfg", b"key=value")
    add("/misc/Ünïcode – name.TXT", b"\x89PNG\r\n\x1a\n" + b"\x00" * 40)
    # --- times (F1) and deleted files -------------------------------------------------------------
    for k in range(40):
        add("/bulk/f%02d.dat" % k, bytes([k]) * (50 + k))
    add("/bulk/late.dat", b"late" * 10, t=(2016, 1, 2, 3, 4, 6))
    add("/bulk/later.dat", b"later" * 10, t=(2016, 1, 2, 3, 4, 6))
    add("/bulk/odd_seconds.dat", b"odd" * 10, t=(2015, 3, 14, 9, 26, 54))
    add("/gone/deleted_ok.txt", b"the password is Deleted99 " * 3, deleted=True)
    add("/gone/deleted_jpg.jpg", J(800, seed=13), deleted=True)
    # --- fuzz: real signatures followed by random bytes -----------------------------------------
    for k in range(260):
        sig = rnd.choice(SIGS)
        body = bytes(rnd.randrange(256) for _ in range(rnd.choice([0, 3, 30, 300, 3000, 9000])))
        if rnd.random() < 0.15:
            body += rnd.choice([b"password is Fuzz%d!" % k, b"\xff\xd9", b"IEND", b";", b"%%EOF", b"PK\x05\x06" + b"\x00" * 18, b"PK\x01\x02"])
        ext = rnd.choice(EXTS)
        add("/fuzz/f%03d%s" % (k, "." + ext if ext else ""), sig + body,
            t=BULK if rnd.random() < 0.8 else (2015, rnd.randrange(1, 13), rnd.randrange(1, 28), rnd.randrange(24), rnd.randrange(60), 2 * rnd.randrange(30)))
    return out


def build_fat(path, seed=1):
    F.CLUSTERS = 30000
    F.FAT_SECTORS = (F.CLUSTERS + 2) * 2 // F.SECTOR + 1
    F.TOTAL = F.RESERVED + F.NFATS * F.FAT_SECTORS + F.ROOT_SECTORS + F.CLUSTERS * F.SPC
    b = F.Builder()
    made = set()
    for p, data, t, deleted in tree(seed):
        parts = p.split("/")[1:-1]
        for k in range(1, len(parts) + 1):
            d = "/" + "/".join(parts[:k])
            if d not in made:
                b.mkdir(d)
                made.add(d)
        b.add(p, data, t=t, deleted=deleted)
    with open(path, "wb") as fh:
        fh.write(b.finish())


def build_ntfs(path, seed=1, size_mb=24):
    """Needs mkntfs and a working ntfs-3g FUSE mount (Linux)."""
    import datetime
    with open(path, "wb") as fh:
        fh.truncate(size_mb << 20)
    subprocess.run(["mkntfs", "-F", "-Q", "-q", "-L", "STRESS", path], check=True)
    mnt = tempfile.mkdtemp()
    subprocess.run(["ntfs-3g", path, mnt], check=True)
    try:
        for p, data, t, deleted in tree(seed):
            full = mnt + p
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "wb") as fh:
                fh.write(data)
            ts = datetime.datetime(*t, tzinfo=datetime.timezone.utc).timestamp()
            os.utime(full, (ts, ts))
            if deleted:
                os.remove(full)
    finally:
        subprocess.run(["fusermount", "-u", mnt], check=False)
        shutil.rmtree(mnt, ignore_errors=True)


if __name__ == "__main__":
    kind, out = sys.argv[1], sys.argv[2]
    seed = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    (build_fat if kind == "fat" else build_ntfs)(out, seed)
