"""Triage of a raw FAT image: content and timestamp consistency checks, scored like D(f).

The timeline rules R1-R11 need NTFS artifacts ($MFT, $J, LNK, Prefetch, event
logs). A FAT volume such as a removable drive has none of them, so this module
applies the same idea, many independent disagreement checks combined into one
weighted score, to what a FAT volume does record: each file's bytes, its name,
its folder, and its FAT timestamps.

  C1  the extension disagrees with the content's signature
  C2  data continues after the format's end marker (appended or hidden data)
  C3  the file is encrypted or password-protected
  C4  a password is written out in plain words
  C5  the file does not fit its folder (only one of its kind, or far larger than its peers)
  C6  the folder's own documentation never mentions the file (an orphan among referenced siblings)
  C7  an archive holds encrypted or personal files
  F1  the last-written time sits outside the bulk-copy stratum shared by the rest of the volume

Every outcome is consistent, violated or not evaluable. With no benign baseline
image, p_r is estimated from the image itself (the share of evaluable files a
rule fires on), so a rule that fires everywhere counts for little.
"""

import io
import math
import os
import re
import statistics
import struct
import zipfile
from collections import Counter, defaultdict
from datetime import datetime

from datetime import datetime, timezone

from . import __version__, sniff
from .fat import FATVolume, NotFAT
from .ntfs import NotNTFS, NTFSVolume
from .loaders import sha256_file

CONSISTENT, VIOLATED, NOT_EVALUABLE = "consistent", "violated", "not_evaluable"

# Each check in plain words: a short name, the question it asks, and why the answer matters.
RULES = {
    "C1": {"name": "Disguised file",
           "question": "Does the file's name match what is really inside it?",
           "why": "Renaming a photo to \u201creadme.txt\u201d is a simple way to hide it from someone browsing the folder."},
    "C2": {"name": "Something hidden at the end",
           "question": "Does the file stop where its own format says it should?",
           "why": "Extra data glued onto the end of a picture is invisible when the picture is opened."},
    "C3": {"name": "Locked with a password",
           "question": "Is the file locked so that it cannot be read?",
           "why": "People lock the files they most want to keep private."},
    "C4": {"name": "Password written down",
           "question": "Does the file contain a sentence like \u201cthe password is ...\u201d?",
           "why": "A written-down password may open one of the locked files."},
    "C5": {"name": "Stands out from its neighbors",
           "question": "Is this file very different from the other files in its folder?",
           "why": "A family photo does not belong among a program's diagrams."},
    "C6": {"name": "Never mentioned",
           "question": "Do the drive's own guides mention this file, as they do its neighbors?",
           "why": "Files that came with a program are usually listed in its guides; a file someone added is not."},
    "C7": {"name": "Archive with personal files",
           "question": "Does a bundle of files (ZIP) hold emails, documents or locked files?",
           "why": "Archives are a common place to tuck away private material."},
    "F1": {"name": "Changed at an unusual time",
           "question": "Was the file last changed at the same time as almost everything else?",
           "why": "When a folder is copied, every file gets the same time. A file changed later stands out."},
}

MAX_READ = 64 << 20
STRONG, MODERATE = 0.30, 0.20   # display tiers for D(f); set on this course image, not calibrated
JAVA_LIKE = {"jar", "war", "ear", "apk", "xpi", "crx"}   # software packages, not opened
NAME_TOKEN = re.compile(rb"[A-Za-z0-9_\-]{1,80}\.[A-Za-z0-9]{2,5}")
PHRASE = re.compile(
    rb"(?i)\b(secret|pass|password|passcode|passphrase|pwd|pin)\s+(?:is|was)\s*[:=]?\s*[\"'\x93]?([\x21-\x7e]{3,64})")
STOP = {b"incorrect", b"invalid", b"required", b"wrong", b"not", b"too", b"the", b"a", b"an", b"empty",
        b"correct", b"valid", b"set", b"stored", b"saved", b"being", b"used", b"expired", b"missing",
        b"needed", b"changed", b"entered", b"null", b"blank", b"case", b"only", b"also", b"sent",
        b"protected", b"encrypted", b"weak", b"strong", b"good", b"bad", b"available", b"incorrect."}


TYPE_LABEL = {"encrypted-ooxml": "password-protected Office document", "excel97": "Excel 97-2003 workbook",
              "word97": "Word 97-2003 document", "ppt97": "PowerPoint 97-2003 file", "ole": "OLE compound document",
              "jpeg": "JPEG image", "png": "PNG image", "gif": "GIF image", "pdf": "PDF document", "zip": "ZIP archive",
              "rar": "RAR archive", "pe": "Windows program", "elf": "Linux program", "ooxml": "Office document",
              "email": "email message", "text": "text", "html": "HTML", "xml": "XML", "java-class": "Java class file",
              "macho": "macOS program"}

# Everyday names: (with article, short, plural)
PLAIN = {
    "jpeg": ("a photo (JPEG)", "photo", "photos"), "png": ("a picture (PNG)", "picture", "pictures"),
    "gif": ("a picture (GIF)", "picture", "pictures"), "pdf": ("a PDF document", "PDF document", "PDF documents"),
    "encrypted-ooxml": ("a password-locked Word, Excel or PowerPoint file", "locked Office file", "locked Office files"),
    "ooxml": ("a Word, Excel or PowerPoint file", "Office file", "Office files"),
    "word97": ("a Word document", "Word document", "Word documents"),
    "excel97": ("an Excel spreadsheet", "spreadsheet", "spreadsheets"),
    "ppt97": ("a PowerPoint file", "PowerPoint file", "PowerPoint files"), "ole": ("an Office file", "Office file", "Office files"),
    "zip": ("a ZIP archive (a bundle of files)", "ZIP archive", "ZIP archives"),
    "rar": ("a RAR archive (a bundle of files)", "RAR archive", "RAR archives"),
    "pe": ("a Windows program", "Windows program", "Windows programs"),
    "elf": ("a Linux program", "Linux program", "Linux programs"), "email": ("an email", "email", "emails"),
    "text": ("plain text", "text file", "text files"), "html": ("a web page", "web page", "web pages"),
    "xml": ("a data file (XML)", "data file", "data files"), "java-class": ("a Java program", "Java program", "Java programs"),
    "jar": ("a Java package", "Java package", "Java packages"),
}
EXT_PLAIN = {"txt": "a text file", "gif": "a GIF picture", "jpg": "a photo", "jpeg": "a photo", "png": "a picture",
             "doc": "a Word document", "docx": "a Word document", "xls": "an Excel spreadsheet",
             "xlsx": "an Excel spreadsheet", "pdf": "a PDF document", "zip": "a ZIP archive", "exe": "a Windows program",
             "html": "a web page", "htm": "a web page", "java": "Java source code", "dll": "a Windows program library"}


def label(t):
    return TYPE_LABEL.get(t, t.upper())


def plain(t):
    return PLAIN.get(t, ("a %s file" % t, "%s file" % t, "%s files" % t))[0]


def plain_short(t):
    return PLAIN.get(t, (None, "%s file" % t, None))[1]


def plain_plural(t):
    return PLAIN.get(t, (None, None, "%s files" % t))[2]


def ext_plain(e):
    return EXT_PLAIN.get(e, "a .%s file" % e)


def plain_embedded(what):
    w = what.split(" at +")[0]
    return {"RAR archive": "a hidden RAR archive (a bundle of files)", "ZIP archive": "a hidden ZIP archive (a bundle of files)",
            "7-Zip archive": "a hidden 7-Zip archive", "JPEG image": "a second, hidden photo",
            "PNG image": "a hidden picture", "PDF document": "a hidden PDF document",
            "OLE document": "a hidden Office document", "Windows executable": "a hidden Windows program"}.get(w, "hidden data")


def human_size(n):
    n = float(n)
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%d %s" % (n, unit)) if unit == "bytes" else ("%.0f %s" % (n, unit) if n >= 10 else "%.1f %s" % (n, unit))
        n /= 1024


_MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def human_time(s):
    """'2011-09-06 03:21:58' -> '6 Sep 2011, 3:21:58 AM'.

    Built by hand rather than with strftime's "%-d"/"%-I", which only Linux and macOS
    understand (Windows raises ValueError), and with fixed English month names and AM/PM
    so the wording does not change with the computer's language settings.
    """
    try:
        d = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return s or "unknown"
    return "%d %s %d, %d:%02d:%02d %s" % (d.day, _MONTHS[d.month - 1], d.year, d.hour % 12 or 12,
                                         d.minute, d.second, "AM" if d.hour < 12 else "PM")


def _and(items):
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1] if items else ""


def _ext(name):
    base = name.rsplit("/", 1)[-1]
    return base.rsplit(".", 1)[-1].lower() if "." in base.strip(".") else ""


def _password_token(tok):
    t = tok.rstrip(b".,;:!?)\"'\x94")
    if len(t) < 4 or t.lower() in STOP:
        return None
    if re.search(rb"\d", t) or (re.search(rb"[a-z]", t) and re.search(rb"[A-Z]", t[1:])) or len(t) >= 12:
        return t
    return None


def _noise_reason(item):
    n = item["name"]
    if n.startswith("._"):
        return "Mac hidden helper files (names starting \u201c._\u201d)"
    if n == ".DS_Store":
        return "Mac folder-view settings (.DS_Store)"
    if "__MACOSX/" in item["path"]:
        return "Mac helper files inside archives (__MACOSX)"
    if n.startswith(".BC.T_") or re.match(r"_B~\d\.T_", n) or n.startswith("._.BC.T_"):
        return "Leftover Mac copying files (.BC.T_)"
    if n.lower() in ("thumbs.db", "desktop.ini"):
        return "Windows folder settings"
    if item["deleted"] and item.get("unrecoverable"):
        return "Deleted files whose contents are gone"
    if item["size"] == 0:
        return "Empty files"
    return None


def _rar4_members(blob):
    """File names and encryption flags from RAR 4.x block headers (unencrypted headers only)."""
    out, i = [], 7
    if not blob.startswith(b"Rar!\x1a\x07\x00"):
        return out
    while i + 7 <= len(blob) and len(out) < 1000:
        crc, htype, flags, hsize = struct.unpack("<HBHH", blob[i:i + 7])
        if hsize < 7:
            break
        if htype == 0x73 and flags & 0x0080:
            out.append({"name": "(file names encrypted)", "encrypted": True})
            break
        add = struct.unpack("<I", blob[i + 7:i + 11])[0] if flags & 0x8000 or htype == 0x74 else 0
        if htype == 0x74:
            nsize = struct.unpack("<H", blob[i + 26:i + 28])[0]
            name = blob[i + 32:i + 32 + nsize].split(b"\x00")[0].decode("utf-8", "replace")
            usize = struct.unpack("<I", blob[i + 11:i + 15])[0]
            out.append({"name": name, "encrypted": bool(flags & 0x04), "size": usize})
        if htype == 0x7B:
            break
        i += hsize + add
    return out


class UnsupportedImage(Exception):
    pass


def open_volume(image_path):
    """Open a FAT or an NTFS volume in a raw image (bare, or inside an MBR/GPT partition table)."""
    try:
        return FATVolume(image_path)
    except NotFAT:
        pass
    try:
        return NTFSVolume(image_path)
    except NotNTFS:
        raise UnsupportedImage("%s holds neither a FAT nor an NTFS drive that ADS can read." % image_path)


class Triage:
    def __init__(self, image_path, max_read=MAX_READ, progress=None):
        self.image_path = image_path
        self.vol = open_volume(image_path)
        self.max_read = max_read
        self.progress = progress or (lambda *a: None)
        self.items = []
        self.content = {}

    # ---- collection ---------------------------------------------------------

    def collect(self):
        self.dirs = 0
        for e in self.vol.walk():
            if e.is_dir:
                self.dirs += 1
                continue
            data = self.vol.read(e, self.max_read)
            item = {
                "id": len(self.items), "path": e.path, "name": e.name, "ext": _ext(e.name), "size": e.size,
                "deleted": e.deleted, "hidden": e.hidden, "container": None,
                "created": e.created.isoformat(" ", "seconds") if e.created else None,
                "modified": e.modified.isoformat(" ", "seconds") if e.modified else None,
                "accessed": e.accessed.date().isoformat() if e.accessed else None,
                "unrecoverable": e.deleted and e.size > 0 and not data,
            }
            self._add(item, data)
            if len(self.items) % 500 == 0:
                self.progress("read", len(self.items))
        return self

    def _add(self, item, data):
        item["type"], item["family"] = sniff.sniff(data) if data else ("empty", "text")
        if item["type"] == "ole":
            kind, enc, how = sniff.ole_kind(data)
            item["type"], item["ole_encrypted"], item["ole_how"] = kind, enc, how
        item["noise"] = _noise_reason(item)
        self.items.append(item)
        self.content[item["id"]] = data
        # Open plain archives (not Java .jar libraries) and examine their members as files of their own.
        if (item["type"] == "zip" and not item["noise"] and item["container"] is None
                and item["ext"] not in JAVA_LIKE):
            try:
                zf = zipfile.ZipFile(io.BytesIO(data))
                item["members"] = []
                for zi in zf.infolist():
                    if zi.is_dir():
                        continue
                    enc = bool(zi.flag_bits & 1)
                    item["members"].append({"name": zi.filename, "encrypted": enc, "size": zi.file_size})
                    try:
                        mdata = b"" if enc else zf.read(zi)[:self.max_read]
                    except Exception:
                        mdata = b""
                    self._add({
                        "id": len(self.items), "path": item["path"] + " › " + zi.filename,
                        "name": zi.filename.rsplit("/", 1)[-1], "ext": _ext(zi.filename), "size": zi.file_size,
                        "deleted": False, "hidden": False, "container": item["path"],
                        "created": None, "accessed": None, "zip_encrypted": enc,
                        "modified": "%04d-%02d-%02d %02d:%02d:%02d" % zi.date_time,
                    }, mdata)
            except zipfile.BadZipFile:
                pass

    # ---- context ------------------------------------------------------------

    def _prepare(self):
        live = [i for i in self.items if not i["noise"]]
        self.by_folder = defaultdict(list)
        for i in live:
            folder = (i["container"] or "") + "|" + i["path"].rsplit("/", 1)[0]
            self.by_folder[folder].append(i)
            i["_folder"] = folder
        # F1: is there a bulk-copy stratum (one written time shared by many files)?
        times = Counter(i["modified"] for i in live if i["container"] is None and i["modified"])
        self.n_timed = sum(times.values())
        self.time_counts = times
        top = times.most_common(1)
        self.bulk_time, self.bulk_share = (top[0][0], top[0][1] / self.n_timed) if top else (None, 0)
        # C6: every file name mentioned anywhere in the volume's text and HTML files.
        self.mentioned = set()
        for i in live:
            if i["family"] == "text" or i["type"] in ("html", "xml", "pdf"):
                for tok in NAME_TOKEN.findall(self.content[i["id"]]):
                    self.mentioned.add(tok.decode("ascii", "replace").lower())

    # ---- rules --------------------------------------------------------------

    def c1(self, i, data):
        exp = sniff.EXPECTED.get(i["ext"])
        if exp is None or not data:
            return NOT_EVALUABLE, {"reason": "extension not judged" if exp is None else "no content"}
        t = i["type"]
        base = "ole" if t in ("encrypted-ooxml", "word97", "excel97", "ppt97") else t
        if base in exp or t in exp:
            return CONSISTENT, {"type": t}
        if i["family"] in sniff.STRONG_FAMILIES or base == "ole":
            return VIOLATED, {"extension": i["ext"], "content": t, "first_bytes": data[:8].hex(" ").upper(),
                              "name_says": ext_plain(i["ext"]), "inside_is": plain(t),
                              "say": "The name ends in “.%s”, which means %s, but the file is really %s."
                                     % (i["ext"], ext_plain(i["ext"]), plain(t)),
                              "tech": "First bytes %s are the signature of %s." % (data[:8].hex(" ").upper(), label(t))}
        return NOT_EVALUABLE, {"reason": "content has no strong signature", "type": t}

    def c2(self, i, data):
        finder = sniff.END_FINDERS.get(i["type"])
        if not finder:
            return NOT_EVALUABLE, {"reason": "format has no end marker checked"}
        end = finder(data)
        if end is None:
            return NOT_EVALUABLE, {"reason": "end marker not found"}
        tail = data[end:]
        trailing = len(tail)
        if trailing < 16 or not tail.strip(b"\x00\xff \r\n\t"):
            return CONSISTENT, {"end_offset": end, "trailing_bytes": trailing}
        what = sniff.describe_bytes(tail)
        d = {"end_offset": end, "trailing_bytes": trailing, "file_size": len(data),
             "trailing_starts": tail[:8].hex(" ").upper(), "trailing_is": what}
        if what and what.startswith("RAR"):
            d["hidden_members"] = _rar4_members(tail)
        if i["type"] == "pdf" and trailing < 4096 and not what:
            return CONSISTENT, d   # PDF writers often leave short tails
        kind = plain(i["type"]).split(" (")[0]
        d["say"] = ("%s should end after %s, but the file keeps going for another %s."
                    % (kind[0].upper() + kind[1:], human_size(end), human_size(trailing)))
        if what:
            d["say"] += " That extra part is %s" % plain_embedded(what)
            names = [m["name"] for m in d.get("hidden_members", [])]
            d["say"] += (" holding " + ", ".join(names) + ".") if names else "."
        d["tech"] = "End-of-image marker ends at byte %s; %s trailing bytes start with %s." % (
            format(end, ","), format(trailing, ","), d["trailing_starts"])
        return VIOLATED, d

    def c3(self, i, data):
        t = i["type"]
        locked = "This file is locked with a password. Nobody can read it without the password."
        if t in ("encrypted-ooxml", "word97", "excel97", "ppt97", "ole"):
            enc = i.get("ole_encrypted")
            if enc is None:
                return NOT_EVALUABLE, {"reason": "OLE kind without an encryption flag checked"}
            if enc:
                return VIOLATED, {"how": i["ole_how"], "say": locked, "tech": i["ole_how"] + "."}
            return CONSISTENT, {"type": t}
        if i.get("zip_encrypted"):
            return VIOLATED, {"how": "ZIP entry encryption flag", "say": locked, "tech": "ZIP entry encryption flag set."}
        if t == "zip":
            enc = [m["name"] for m in i.get("members", []) if m["encrypted"]]
            if enc:
                return VIOLATED, {"encrypted_members": enc, "tech": "Encrypted entries: %s." % ", ".join(enc),
                                  "say": "Files inside this archive are locked with a password: %s." % ", ".join(enc)}
            return CONSISTENT, {}
        if t == "pdf":
            if b"/Encrypt" in data[-65536:] or b"/Encrypt" in data[:4096]:
                return VIOLATED, {"how": "PDF /Encrypt dictionary", "say": locked, "tech": "PDF /Encrypt dictionary."}
            return CONSISTENT, {}
        if t == "rar":
            m = _rar4_members(data)
            if any(x["encrypted"] for x in m):
                return VIOLATED, {"members": m, "say": locked, "tech": "RAR file header password flag."}
            return CONSISTENT, {"members": m}
        return NOT_EVALUABLE, {"reason": "not an encryptable container"}

    def c4(self, i, data):
        if not data:
            return NOT_EVALUABLE, {"reason": "no content"}
        hits = []
        for m in PHRASE.finditer(data):
            tok = _password_token(m.group(2))
            if not tok:
                continue
            a, b = max(0, m.start() - 30), min(len(data), m.end() + 10)
            ctx = re.sub(rb"[^\x20-\x7e]", b".", data[a:b]).decode("ascii")
            hits.append({"offset": m.start(), "phrase": m.group(0)[:80].decode("latin-1"),
                         "candidate": tok.decode("latin-1"), "context": ctx})
            if len(hits) >= 5:
                break
        if not hits:
            return CONSISTENT, {}
        phrase = hits[0]["phrase"].strip().rstrip(".")
        if i["family"] == "executable":
            say = ("This is %s, which should hold only computer code, yet it contains the plain sentence "
                   "“%s”. Someone may have hidden a password here." % (plain(i["type"]), phrase))
        else:
            say = "This file contains the sentence “%s”. It looks like a password someone wrote down." % phrase
        return VIOLATED, {"hits": hits, "say": say,
                          "tech": "Phrase at byte offset %s." % format(hits[0]["offset"], ",")}

    def c5(self, i, data):
        sibs = self.by_folder[i["_folder"]]
        if len(sibs) < 5:
            return NOT_EVALUABLE, {"reason": "fewer than 5 files in folder", "files": len(sibs)}
        same = [s for s in sibs if s["type"] == i["type"]]
        if i["type"] in sniff.PERSONAL_TYPES | {"encrypted-ooxml", "word97", "excel97", "email"} and len(same) == 1:
            kinds = Counter(s["type"] for s in sibs if s is not i).most_common(3)
            return VIOLATED, {"folder_files": len(sibs), "others": {plain_short(k): v for k, v in kinds},
                              "this": plain_short(i["type"]), "kind": "odd_type",
                              "say": "It is the only %s among the %d files in its folder. The others are mostly %s." % (
                                  plain_short(i["type"]), len(sibs), _and([plain_plural(k) for k, _ in kinds]))}
        others = [s["size"] for s in same if s is not i and s["size"]]
        if len(others) >= 3 and i["size"] and i["type"] in sniff.PERSONAL_TYPES:
            med = statistics.median(others)
            ratio = i["size"] / med if med else 0
            if ratio >= 10:
                return VIOLATED, {"size": i["size"], "peer_median": med, "ratio": round(ratio, 1), "kind": "big",
                                  "peer_sizes": sorted(others)[:60],
                                  "say": "At %s it is about %.0f times bigger than the other %s in its folder, which are around %s each." % (
                                      human_size(i["size"]), ratio, plain_plural(i["type"]), human_size(med))}
        return CONSISTENT, {"folder_files": len(sibs)}

    def c6(self, i, data):
        if i["container"]:
            return NOT_EVALUABLE, {"reason": "archive member"}
        sibs = [s for s in self.by_folder[i["_folder"]] if s is not i]
        if len(sibs) < 4:
            return NOT_EVALUABLE, {"reason": "too few siblings"}
        ref = [s for s in sibs if s["name"].lower() in self.mentioned]
        if len(ref) / len(sibs) < 0.6:
            return NOT_EVALUABLE, {"reason": "siblings are not usually referenced", "referenced": len(ref)}
        if i["name"].lower() in self.mentioned:
            return CONSISTENT, {}
        return VIOLATED, {"referenced": len(ref), "siblings": len(sibs),
                          "say": "The guides and web pages on this drive mention %d of the %d other files in this folder by name, but never this one."
                                 % (len(ref), len(sibs))}

    def c7(self, i, data):
        members = i.get("members")
        if members is None:
            return NOT_EVALUABLE, {"reason": "not an opened archive"}
        kids = [x for x in self.items if x["container"] == i["path"] and not x["noise"]]
        found = []
        for k in kids:
            if k.get("zip_encrypted") or k.get("ole_encrypted"):
                found.append("%s (%s, locked with a password)" % (k["name"], plain_short(k["type"])))
            elif k["type"] in ("email", "encrypted-ooxml", "word97", "excel97", "ooxml", "rtf"):
                found.append("%s (%s)" % (k["name"], plain_short(k["type"])))
        if found:
            return VIOLATED, {"inside": found,
                              "say": "This archive is a bundle of files. Inside it are personal items: %s." % _and(found)}
        return CONSISTENT, {"members": len(kids)}

    def f1(self, i, data):
        if i["container"] or not i["modified"]:
            return NOT_EVALUABLE, {"reason": "no volume timestamp"}
        if self.bulk_share < 0.2:
            return NOT_EVALUABLE, {"reason": "no bulk-copy pattern on this volume"}
        n = self.time_counts[i["modified"]]
        share = n / self.n_timed
        if i["modified"] == self.bulk_time or share >= 0.01:
            return CONSISTENT, {"modified": i["modified"], "files_with_this_time": n}
        bulk = self.time_counts[self.bulk_time]
        return VIOLATED, {"modified": i["modified"], "files_with_this_time": n, "bulk_time": self.bulk_time,
                          "bulk_files": bulk,
                          "say": "Almost every file on this drive (%s of them) was last changed at the same moment, %s, "
                                 "when they were copied together. This file was changed at a different time, %s, "
                                 "along with only %d other file%s." % (
                                     format(bulk, ","), human_time(self.bulk_time), human_time(i["modified"]),
                                     n - 1, "" if n == 2 else "s")}

    # ---- scoring ------------------------------------------------------------

    def run(self):
        if not self.items:
            self.collect()
        self._prepare()
        fns = {"C1": self.c1, "C2": self.c2, "C3": self.c3, "C4": self.c4, "C5": self.c5,
               "C6": self.c6, "C7": self.c7, "F1": self.f1}
        live = [i for i in self.items if not i["noise"]]
        for n, i in enumerate(live):
            data = self.content[i["id"]]
            i["outcomes"] = {rid: fn(i, data) for rid, fn in fns.items()}
            if n % 500 == 0:
                self.progress("check", n)
        # p_r is the share of all examined files the rule flags (its base rate on this volume), not
        # the share of evaluable files: a rule that can judge only 27 files would otherwise get a
        # noisy, inflated rate, and for triage what matters is how many files a rule sends you to.
        self.rates = {}
        for rid in fns:
            ev = [i for i in live if i["outcomes"][rid][0] != NOT_EVALUABLE]
            v = sum(1 for i in ev if i["outcomes"][rid][0] == VIOLATED)
            p = (v + 0.5) / (len(live) + 1)
            self.rates[rid] = {"evaluable": len(ev), "violated": v, "p_r": p, "weight": math.log(1 / p)}
        for i in live:
            num = den = 0.0
            fired = []
            for rid, (o, _d) in i["outcomes"].items():
                if o == NOT_EVALUABLE:
                    continue
                w = self.rates[rid]["weight"]
                den += w
                if o == VIOLATED:
                    num += w
                    fired.append(rid)
            i["score"] = num / den if den else 0.0
            i["fired"] = fired
            i["evaluable"] = sum(1 for o, _ in i["outcomes"].values() if o != NOT_EVALUABLE)
        return self

    def close(self):
        """Release the image file (Windows cannot delete or move a file that is still open)."""
        self.vol.close()

    def image_sha256(self):
        if not hasattr(self, "_sha"):
            self._sha = sha256_file(self.image_path)
        return self._sha

    def leads(self):
        live = [i for i in self.items if not i["noise"] and i["fired"]]
        return sorted(live, key=lambda i: (-i["score"], -len(i["fired"]), i["path"]))

    # ---- export -------------------------------------------------------------

    def to_json(self, top=40):
        live = [i for i in self.items if not i["noise"]]
        noise = Counter(i["noise"] for i in self.items if i["noise"])
        leads = self.leads()
        types = Counter(i["type"] for i in live)

        def slim(i):
            return {k: v for k, v in i.items() if not k.startswith("_") and k not in ("unrecoverable",)}

        strata = []
        for t, n in sorted(self.time_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:12]:
            members = [i["path"] for i in live if i["container"] is None and i["modified"] == t]
            strata.append({"time": t, "files": n, "share": n / self.n_timed if self.n_timed else 0,
                           "rare": n / self.n_timed < 0.01 if self.n_timed else False,
                           "examples": members[:15] if n / max(1, self.n_timed) < 0.01 else members[:3]})
        keys = []
        for i in live:
            o = i.get("outcomes", {}).get("C4")
            if o and o[0] == VIOLATED:
                for h in o[1]["hits"]:
                    keys.append({"key": h["candidate"], "found_in": i["path"], "offset": h["offset"]})
        locked = [i["path"] for i in live if i.get("outcomes", {}).get("C3", ("",))[0] == VIOLATED]
        return {
            "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "tool": "ADS %s" % __version__,
            "image": {"path": os.path.abspath(self.image_path), "name": os.path.basename(self.image_path),
                      "bytes": os.path.getsize(self.image_path), "sha256": self.image_sha256(),
                      **self.vol.summary()},
            "boot_hex": self.vol._read(0, 64).hex(),   # first bytes of the volume, shown in the briefing
            "strata": strata,
            "keys": keys,
            "locked": locked,
            "tiers": {"strong": STRONG, "moderate": MODERATE},
            "counts": {"entries": len(self.items) + self.dirs, "folders": self.dirs,
                       "files": sum(1 for i in self.items if i["container"] is None),
                       "archive_members": sum(1 for i in self.items if i["container"]),
                       "noise": sum(noise.values()), "examined": len(live), "with_findings": len(leads),
                       "deleted": sum(1 for i in self.items if i["deleted"])},
            "noise": dict(noise.most_common()),
            "types": dict(types.most_common(12)),
            "rules": {rid: {**RULES[rid], **self.rates[rid]} for rid in RULES},
            "timeline": {"bulk_time": self.bulk_time, "bulk_share": self.bulk_share, "timed_files": self.n_timed},
            "not_applicable": (
                "Timeline rules R1-R11 need NTFS artifacts ($MFT, $UsnJrnl, LNK, Prefetch, event logs); "
                "this %s volume has none of them." % self.vol.summary()["fs_type"]
                if self.vol.summary()["fs_type"] != "NTFS" else
                "This is an NTFS volume, so the timestamp rules R1-R11 run in the separate Windows drive report "
                "(python -m ads ingest --image, then analyze); this first-look report asks the eight questions."),
            "leads": [slim(i) for i in leads[:top]],
            "all_leads": [{"path": i["path"], "score": round(i["score"], 4), "fired": i["fired"]} for i in leads],
        }
