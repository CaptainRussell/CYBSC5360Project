"""File-type identification from content, minimal OLE (CFB) reading, and end-of-format detection."""

import re
import struct

# (type, family, magic, offset)
MAGIC = [
    ("jpeg", "image", b"\xff\xd8\xff", 0),
    ("png", "image", b"\x89PNG\r\n\x1a\n", 0),
    ("gif", "image", b"GIF87a", 0),
    ("gif", "image", b"GIF89a", 0),
    ("tiff", "image", b"II*\x00", 0),
    ("tiff", "image", b"MM\x00*", 0),
    ("pdf", "document", b"%PDF-", 0),
    ("ole", "document", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", 0),
    ("rtf", "document", b"{\\rtf", 0),
    ("zip", "archive", b"PK\x03\x04", 0),
    ("zip", "archive", b"PK\x05\x06", 0),
    ("rar", "archive", b"Rar!\x1a\x07", 0),
    ("7z", "archive", b"7z\xbc\xaf\x27\x1c", 0),
    ("gzip", "archive", b"\x1f\x8b\x08", 0),
    ("bzip2", "archive", b"BZh", 0),
    ("pe", "executable", b"MZ", 0),
    ("elf", "executable", b"\x7fELF", 0),
    ("macho", "executable", b"\xcf\xfa\xed\xfe", 0),
    ("macho", "executable", b"\xce\xfa\xed\xfe", 0),
    ("java-class", "executable", b"\xca\xfe\xba\xbe", 0),
    ("appledouble", "metadata", b"\x00\x05\x16\x07", 0),
    ("ds_store", "metadata", b"\x00\x00\x00\x01Bud1", 0),
    ("sqlite", "database", b"SQLite format 3\x00", 0),
    ("mp3", "media", b"ID3", 0),
    ("ico", "image", b"\x00\x00\x01\x00", 0),
    ("bmp", "image", b"BM", 0),
]

STRONG_FAMILIES = {"image", "document", "archive", "executable", "database", "media"}

# What each extension is allowed to contain. Extensions not listed are not judged.
TEXTUAL = {"text", "xml", "html", "email", "rtf", "empty"}
EXPECTED = {}
for exts, types in [
    ("jpg jpeg jpe jfif", {"jpeg"}), ("png", {"png"}), ("gif", {"gif"}), ("tif tiff", {"tiff"}),
    ("bmp", {"bmp"}), ("ico cur", {"ico", "png", "bmp"}), ("pdf", {"pdf"}),
    ("doc xls ppt msg msi pub vsd", {"ole"}),
    ("docx xlsx pptx docm xlsm pptm", {"ooxml", "ole"}),     # encrypted OOXML is an OLE container
    ("odt ods odp", {"zip", "odf"}),
    ("zip", {"zip"}), ("jar war ear apk xpi crx", {"zip", "jar"}), ("rar", {"rar"}), ("7z", {"7z"}),
    ("gz tgz", {"gzip"}), ("bz2", {"bzip2"}),
    ("exe dll sys ocx cpl scr drv efi", {"pe"}), ("so ko", {"elf"}), ("class", {"java-class"}),
    ("dylib", {"macho"}), ("db sqlite", {"sqlite", "ole"}), ("mp3", {"mp3"}),
    ("txt text log csv ini cfg conf properties java c h cpp hpp py js css htm html xml xsl xslt xsd json md "
     "sh bat cmd policy mf dtd tld jsp pl rb tcl sql opt scr out expected manifest rdf svg vbs ps1 lst "
     "readme license eml", TEXTUAL),
]:
    for e in exts.split():
        EXPECTED[e] = types

PERSONAL_TYPES = {"jpeg", "png", "ole", "ooxml", "odf", "email", "zip", "rar", "7z", "pdf", "rtf", "sqlite", "mp3"}


def _text_kind(data):
    sample = data[:4096]
    if not sample:
        return "empty"
    printable = sum(1 for b in sample if 32 <= b < 127 or b in (9, 10, 13))
    try:
        sample.decode("utf-8")
        utf8 = True
    except UnicodeDecodeError:
        utf8 = False
    if printable / len(sample) < 0.9 and not utf8:
        return None
    head = sample.lstrip()[:200].lower()
    if head.startswith(b"<?xml"):
        return "xml"
    if head.startswith(b"<!doctype html") or head.startswith(b"<html"):
        return "html"
    if re.match(rb"(?:(?:from|to|subject|date|received|return-path|mime-version|message-id|x-[\w-]+):[^\n]*\r?\n){2,}",
                sample.lstrip()[:2000], re.I):
        return "email"
    return "text"


def sniff(data):
    """-> (type, family). Refines zip into ooxml/jar/odf and ole into its document kind."""
    for t, fam, magic, off in MAGIC:
        if data[off:off + len(magic)] == magic:
            if t == "bmp" and (len(data) < 14 or struct.unpack("<I", data[2:6])[0] not in (len(data), 0)):
                continue
            if t == "ico" and (len(data) < 6 or data[4:6] == b"\x00\x00"):
                continue
            if t == "pe" and b"PE\x00\x00" not in data[:4096] and len(data) > 512:
                continue
            if t == "zip":
                head = data[:65536]
                if b"[Content_Types].xml" in head:
                    return "ooxml", "document"
                if b"META-INF/" in head[:2048] or b".class" in head[:2048]:
                    return "jar", "archive"
                if head[30:38] == b"mimetype":
                    return "odf", "document"
            return t, fam
    tk = _text_kind(data)
    if tk:
        return tk, "text"
    return "binary", "unknown"


class CFB:
    """Just enough of the Compound File Binary format to list streams and read one."""

    def __init__(self, data):
        if data[:8] != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
            raise ValueError("not CFB")
        self.d = data
        self.ss = 1 << struct.unpack("<H", data[30:32])[0]
        self.mss = 1 << struct.unpack("<H", data[32:34])[0]
        nfat, self.dir_start = struct.unpack("<I", data[44:48])[0], struct.unpack("<I", data[48:52])[0]
        self.cutoff, self.minifat_start = struct.unpack("<II", data[56:64])
        difat_start, ndifat = struct.unpack("<II", data[68:76])
        difat = list(struct.unpack("<109I", data[76:76 + 436]))
        s, guard = difat_start, 0
        while s < 0xFFFFFFFA and guard < ndifat + 1:
            blk = struct.unpack("<%dI" % (self.ss // 4), self._sector(s))
            difat += blk[:-1]
            s, guard = blk[-1], guard + 1
        self.fat = []
        for s in difat[:nfat]:
            if s < 0xFFFFFFFA:
                self.fat += struct.unpack("<%dI" % (self.ss // 4), self._sector(s))
        self.entries = []
        dirdata = self._chain_read(self.dir_start, self.fat, self._sector)
        for i in range(0, len(dirdata) - 127, 128):
            e = dirdata[i:i + 128]
            nlen = struct.unpack("<H", e[64:66])[0]
            name = e[:max(0, nlen - 2)].decode("utf-16-le", "replace")
            etype = e[66]
            start, size = struct.unpack("<I", e[116:120])[0], struct.unpack("<I", e[120:124])[0]
            if etype:
                self.entries.append({"name": name, "type": etype, "start": start, "size": size})
        root = next((e for e in self.entries if e["type"] == 5), None)
        self.ministream = self._chain_read(root["start"], self.fat, self._sector) if root else b""
        self.minifat = []
        if self.minifat_start < 0xFFFFFFFA:
            mf = self._chain_read(self.minifat_start, self.fat, self._sector)
            self.minifat = list(struct.unpack("<%dI" % (len(mf) // 4), mf))

    def _sector(self, s):
        o = (s + 1) * self.ss
        return self.d[o:o + self.ss]

    def _mini(self, s):
        o = s * self.mss
        return self.ministream[o:o + self.mss]

    @staticmethod
    def _chain_read(start, fat, reader, limit=1 << 26):
        out, s, seen = bytearray(), start, set()
        while s < 0xFFFFFFFA and s < len(fat) + 1 and s not in seen and len(out) < limit:
            seen.add(s)
            out += reader(s)
            if s >= len(fat):
                break
            s = fat[s]
        return bytes(out)

    def names(self):
        return [e["name"] for e in self.entries]

    def stream(self, name):
        e = next((x for x in self.entries if x["name"] == name and x["type"] == 2), None)
        if not e:
            return None
        if e["size"] < self.cutoff:
            return self._chain_read(e["start"], self.minifat, self._mini)[:e["size"]]
        return self._chain_read(e["start"], self.fat, self._sector)[:e["size"]]


def ole_kind(data):
    """-> (kind, encrypted, how) for an OLE container."""
    try:
        cfb = CFB(data)
    except Exception:
        return "ole", None, "unreadable OLE container"
    names = set(cfb.names())
    if "EncryptedPackage" in names and "EncryptionInfo" in names:
        return "encrypted-ooxml", True, "EncryptedPackage and EncryptionInfo streams (password-protected Office 2007+ file)"
    if "WordDocument" in names:
        wd = cfb.stream("WordDocument") or b""
        enc = len(wd) > 12 and bool(struct.unpack("<H", wd[10:12])[0] & 0x0100)
        return "word97", enc, "Word FIB fEncrypted flag" if enc else ""
    for book in ("Workbook", "Book"):
        if book in names:
            wb = cfb.stream(book) or b""
            pos, enc = 0, False
            for _ in range(64):   # FILEPASS (0x002F) follows BOF near the start of the globals
                if pos + 4 > len(wb):
                    break
                rid, ln = struct.unpack("<HH", wb[pos:pos + 4])
                if rid == 0x002F:
                    enc = True
                    break
                if rid == 0x0809 and pos > 0:
                    break
                pos += 4 + ln
            return "excel97", enc, "Excel FILEPASS record" if enc else ""
    if "PowerPoint Document" in names:
        return "ppt97", None, ""
    return "ole", None, ""


def jpeg_end(data):
    """Offset just past the EOI marker of the first JPEG image, or None."""
    i, n = 2, len(data)
    while i + 4 <= n:
        if data[i] != 0xFF:
            return None
        m = data[i + 1]
        if m == 0xFF:
            i += 1
            continue
        if m in (0xD8, 0x01) or 0xD0 <= m <= 0xD7:
            i += 2
            continue
        if m == 0xD9:
            return i + 2
        ln = struct.unpack(">H", data[i + 2:i + 4])[0]
        if m == 0xDA:   # start of scan: entropy-coded data until a marker other than RSTn / stuffed 00
            j = i + 2 + ln
            while j + 1 < n:
                if data[j] == 0xFF and data[j + 1] not in (0x00,) and not (0xD0 <= data[j + 1] <= 0xD7) and data[j + 1] != 0xFF:
                    break
                j += 1
            i = j
            continue
        i += 2 + ln
    return None


def png_end(data):
    i = 8
    while i + 12 <= len(data):
        ln = struct.unpack(">I", data[i:i + 4])[0]
        if data[i + 4:i + 8] == b"IEND":
            return i + 12 + ln
        i += 12 + ln
    return None


def gif_end(data):
    try:
        i = 13
        flags = data[10]
        if flags & 0x80:
            i += 3 * (2 << (flags & 7))
        while i < len(data):
            b = data[i]
            if b == 0x3B:
                return i + 1
            if b == 0x21:
                i += 2
            elif b == 0x2C:
                lf = data[i + 9]
                i += 10
                if lf & 0x80:
                    i += 3 * (2 << (lf & 7))
                i += 1
            else:
                return None
            while i < len(data) and data[i]:
                i += data[i] + 1
            i += 1
    except IndexError:
        return None
    return None


def zip_end(data):
    p = data.rfind(b"PK\x05\x06")
    if p < 0 or p + 22 > len(data):
        return None
    return p + 22 + struct.unpack("<H", data[p + 20:p + 22])[0]


def pdf_end(data):
    p = data.rfind(b"%%EOF")
    return None if p < 0 else p + 5


END_FINDERS = {"jpeg": jpeg_end, "png": png_end, "gif": gif_end, "zip": zip_end, "pdf": pdf_end}

EMBED_SIGS = [(b"Rar!\x1a\x07", "RAR archive"), (b"7z\xbc\xaf\x27\x1c", "7-Zip archive"),
              (b"PK\x03\x04", "ZIP archive"), (b"\xff\xd8\xff\xe0", "JPEG image"), (b"\xff\xd8\xff\xe1", "JPEG image"),
              (b"\x89PNG\r\n\x1a\n", "PNG image"), (b"%PDF-", "PDF document"),
              (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "OLE document"), (b"MZ\x90\x00", "Windows executable")]


def describe_bytes(blob):
    for sig, name in EMBED_SIGS:
        if blob.startswith(sig):
            return name
    for sig, name in EMBED_SIGS:
        p = blob.find(sig, 0, 4096)
        if p >= 0:
            return "%s at +%d" % (name, p)
    return None
