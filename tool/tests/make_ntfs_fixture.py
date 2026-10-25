"""Build tests/fixtures/ntfs_small.img.gz and its answer key from The Sleuth Kit.

Regenerating needs Linux with mkntfs and ntfs-3g (FUSE) and the pytsk3 package;
the tests themselves need none of them, only the committed .img.gz and .json.

    python3 tests/make_ntfs_fixture.py

The image holds the cases the reader must get right: nested folders, a hidden
dot-folder, a JPEG with no extension, tiny files stored inside the MFT record,
a large file, a deliberately fragmented file, a file with enough hard links to
need an attribute list, a named data stream, a deleted file, a file with the
hidden attribute, a non-ASCII name, and set timestamps (one on a whole second).
The answer key is what pytsk3 (The Sleuth Kit) reports for every live file:
path, size, SHA-256 of the contents, and the four $STANDARD_INFORMATION times.
"""

import gzip
import hashlib
import json
import os
import shutil
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_IMG = os.path.join(HERE, "fixtures", "ntfs_small.img.gz")
OUT_KEY = os.path.join(HERE, "fixtures", "ntfs_small_truth.json")
SIZE_MB = 12
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" + b"label " * 4000 + b"\xff\xd9"


def text(seed, n):
    line = ("file %s line " % seed).encode()
    return (line * (n // len(line) + 1))[:n]


def build(mnt):
    def put(rel, data):
        p = os.path.join(mnt, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as fh:
            fh.write(data)
        return p

    put("Disk/bin/gzip", JPEG)                                     # picture with no extension
    put("Disk/bin/ls", b"\x7fELF" + text("ls", 30000))
    put("Disk/lib/security/hello.png", b"\x89PNG\r\n\x1a\n" + text("png", 40000))
    put("Disk/tmp/.font-unix/fs-1/ini/template.pdf", b"%PDF-1.4\n" + text("pdf", 90000) + b"\n%%EOF\n")
    put("Disk/etc/tiny.conf", b"a=1\n")                            # resident in the MFT record
    put("Disk/etc/empty", b"")
    put("Disk/usr/share/big.bin", text("big", 2_500_000))           # non-resident, many clusters
    put("Disk/home/café/notes.txt", text("unicode", 1500))
    for i in range(150):                                           # fill folders, grow the MFT
        put("Disk/usr/lib/lib%03d.so" % i, b"\x7fELF" + text("lib%d" % i, 200 + 37 * i))
    # A fragmented file: grow it in steps while other files take the clusters in between.
    frag = os.path.join(mnt, "Disk/var/log/frag.log")
    os.makedirs(os.path.dirname(frag), exist_ok=True)
    for i in range(12):
        with open(frag, "ab") as fh:
            fh.write(text("frag%d" % i, 9000))
            fh.flush()
            os.fsync(fh.fileno())
        put("Disk/var/log/spacer%02d" % i, text("spacer%d" % i, 9000))
    for i in range(0, 12, 2):                                      # free some gaps, then refill
        os.remove(os.path.join(mnt, "Disk/var/log/spacer%02d" % i))
    with open(frag, "ab") as fh:
        fh.write(text("frag-tail", 40000))
    # Many hard links push the $FILE_NAME attributes into an extension record (attribute list).
    linked = put("Disk/srv/linked.dat", text("linked", 5000))
    os.makedirs(os.path.join(mnt, "Disk/srv/links"), exist_ok=True)
    for i in range(60):
        os.link(linked, os.path.join(mnt, "Disk/srv/links/a_rather_long_hard_link_name_%02d.dat" % i))
    # A named data stream (alternate data stream) next to the unnamed one.
    ads = put("Disk/home/stream.txt", text("main", 3000))
    subprocess.run(["setfattr", "-n", "user.secret", "-v", "hidden stream text", ads], check=False)
    # Hidden attribute (FILE_ATTRIBUTE_HIDDEN = 0x2) through ntfs-3g's attribute xattr.
    hid = put("Disk/home/hidden.txt", text("hidden", 800))
    subprocess.run(["setfattr", "-n", "system.ntfs_attrib_be", "-v", "0x00000002", hid], check=False)
    # A deleted file.
    gone = put("Disk/tmp/deleted.txt", text("deleted", 20000))
    os.remove(gone)
    # Timestamps: modified and accessed set explicitly, one on an exact whole second.
    os.utime(os.path.join(mnt, "Disk/bin/gzip"), (1317729600.25, 1317729600.25))   # 2011-10-04 12:00:00.25
    os.utime(os.path.join(mnt, "Disk/etc/tiny.conf"), (1317556621, 1317556621))   # whole second


def tsk_truth(img):
    import pytsk3
    fs = pytsk3.FS_Info(pytsk3.Img_Info(img))
    out = {}

    def ft(sec, nano):
        return None if not sec else sec * 10_000_000 + nano // 100 + 116444736000000000

    def walk(d, prefix):
        for f in d:
            name = f.info.name.name.decode("utf-8", "replace")
            if name in (".", "..") or name.startswith("$") and prefix == "":
                continue
            meta = f.info.meta
            if meta is None:
                continue
            if f.info.name.flags & pytsk3.TSK_FS_NAME_FLAG_UNALLOC:
                continue
            path = prefix + "/" + name
            if meta.type == pytsk3.TSK_FS_META_TYPE_DIR:
                walk(f.as_directory(), path)
            elif meta.type == pytsk3.TSK_FS_META_TYPE_REG:
                data = f.read_random(0, meta.size) if meta.size else b""
                out[path] = {"size": meta.size, "sha256": hashlib.sha256(data).hexdigest(),
                             "entry": meta.addr,
                             "si": [ft(meta.crtime, meta.crtime_nano), ft(meta.mtime, meta.mtime_nano),
                                    ft(meta.ctime, meta.ctime_nano), ft(meta.atime, meta.atime_nano)]}

    walk(fs.open_dir("/"), "")
    return out


def main():
    with tempfile.TemporaryDirectory() as d:
        img, mnt = os.path.join(d, "ntfs_small.img"), os.path.join(d, "mnt")
        os.makedirs(mnt)
        with open(img, "wb") as fh:
            fh.truncate(SIZE_MB << 20)
        subprocess.run(["mkntfs", "-q", "-F", "-f", "-L", "Disk", img], check=True, capture_output=True)
        subprocess.run(["ntfs-3g", "-o", "rw,streams_interface=xattr", img, mnt], check=True)
        try:
            build(mnt)
        finally:
            subprocess.run(["umount", mnt], check=True)
        key = tsk_truth(img)
        with open(img, "rb") as src, gzip.open(OUT_IMG, "wb", compresslevel=9) as dst:
            shutil.copyfileobj(src, dst)
        with open(OUT_KEY, "w", encoding="utf-8") as fh:
            json.dump({"made_by": "pytsk3 (The Sleuth Kit)", "files": key}, fh, indent=1, sort_keys=True)
    print("wrote %s (%d KB) and %s (%d files)" % (OUT_IMG, os.path.getsize(OUT_IMG) // 1024, OUT_KEY, len(key)))


if __name__ == "__main__":
    main()
