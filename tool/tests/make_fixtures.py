"""Generate small synthetic Zimmerman-format CSVs for testing ADS.

The scenario is a fictional Windows 11 system (user 'bob', volume formatted
2026-09-01) with four files of interest among ~50 ordinary files:

  report.docx  benign, opened from a LNK in Recent
  budget.xlsx  T1: all four SIA times set to 2019-03-01 by UTIL.EXE on 2026-10-12
  notes.txt    T3: created 2026-10-12, SIA and FNA creation backdated to 2020-05-05
  photo.jpg    benign noise: extracted by 7-Zip, modification time kept from the archive
  memo.docx    benign: Office-style save (temp file renamed over the original;
               NTFS tunneling keeps the original creation time)

Two cases share the MFT, LNK and Prefetch CSVs:
  clean/     intact $J and event logs; no system indicator should fire
  tampered/  T8-style: $J deleted and recreated, logs cleared, clock changed,
             a Prefetch file and a LNK file deleted

Usage: python tests/make_fixtures.py [OUT_DIR]   (default tests/fixtures)
"""

import csv
import json
import os
import sys
from datetime import datetime, timedelta

SID = "S-1-5-21-111-222-333-1001"
VOL = r"\VOLUME{01d9a1b2c3d4e5f6-12345678}"
DOCS, PICS, RECENT, PREFETCH, CACHE = 50, 51, 52, 53, 54
PARENT_PATH = {
    DOCS: r".\Users\bob\Documents", PICS: r".\Users\bob\Pictures",
    RECENT: r".\Users\bob\AppData\Roaming\Microsoft\Windows\Recent",
    PREFETCH: r".\Windows\Prefetch", CACHE: r".\Users\bob\AppData\Local\Cache",
}

MFT_COLS = ("EntryNumber,SequenceNumber,InUse,ParentEntryNumber,ParentSequenceNumber,ParentPath,"
            "FileName,Extension,FileSize,ReferenceCount,ReparseTarget,IsDirectory,HasAds,IsAds,SI<FN,"
            "uSecZeros,Copied,SiFlags,NameType,Created0x10,Created0x30,LastModified0x10,LastModified0x30,"
            "LastRecordChange0x10,LastRecordChange0x30,LastAccess0x10,LastAccess0x30,UpdateSequenceNumber,"
            "LogfileSequenceNumber,SecurityId,ObjectIdFileDroid,LoggedUtilStream,ZoneIdContents,SourceFile").split(",")
USN_COLS = ("Name,Extension,EntryNumber,SequenceNumber,ParentEntryNumber,ParentSequenceNumber,ParentPath,"
            "UpdateSequenceNumber,UpdateTimestamp,UpdateReasons,FileAttributes,OffsetToData,SourceFile").split(",")
LNK_COLS = ("SourceFile,SourceCreated,SourceModified,SourceAccessed,TargetCreated,TargetModified,"
            "TargetAccessed,FileSize,RelativePath,WorkingDirectory,FileAttributes,HeaderFlags,DriveType,"
            "VolumeSerialNumber,VolumeLabel,LocalPath,NetworkPath,CommonPath,Arguments,TargetIDAbsolutePath,"
            "TargetMFTEntryNumber,TargetMFTSequenceNumber,MachineID,MachineMACAddress,MACVendor,"
            "TrackerCreatedOn,ExtraBlocksPresent").split(",")
PF_COLS = ("SourceFilename,SourceCreated,SourceModified,SourceAccessed,ExecutableName,Hash,Size,Version,"
           "RunCount,LastRun,PreviousRun0,PreviousRun1,PreviousRun2,PreviousRun3,PreviousRun4,PreviousRun5,"
           "PreviousRun6,Volume0Name,Volume0Serial,Volume0Created,Volume1Name,Volume1Serial,Volume1Created,"
           "Directories,FilesLoaded,ParsingError").split(",")
EVTX_COLS = ("RecordNumber,EventRecordId,TimeCreated,EventId,Level,Provider,Channel,ProcessId,ThreadId,"
             "Computer,ChunkNumber,UserId,MapDescription,UserName,RemoteHost,PayloadData1,PayloadData2,"
             "PayloadData3,PayloadData4,PayloadData5,PayloadData6,ExecutableInfo,HiddenRecord,SourceFile,"
             "Keywords,ExtraDataOffset,Payload").split(",")


def T(s, frac=0):
    """'2026-10-10 09:15:00' + 100ns fraction -> Zimmerman timestamp string."""
    return "%s.%07d" % (s, frac)


def shift(s, sec):
    d = datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S") + timedelta(seconds=sec)
    return d.strftime("%Y-%m-%d %H:%M:%S")


def write(path, cols, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="raise")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


def mft_row(entry, seq, parent, name, si, fn, in_use=True, size=1024):
    """si, fn: dicts with keys c, m, e, a."""
    return {
        "EntryNumber": entry, "SequenceNumber": seq, "InUse": in_use, "ParentEntryNumber": parent,
        "ParentSequenceNumber": 1, "ParentPath": PARENT_PATH.get(parent, "."), "FileName": name,
        "Extension": os.path.splitext(name)[1], "FileSize": size, "ReferenceCount": 1,
        "IsDirectory": False, "HasAds": False, "IsAds": False, "NameType": "Windows",
        "Created0x10": si["c"], "Created0x30": fn["c"], "LastModified0x10": si["m"],
        "LastModified0x30": fn["m"], "LastRecordChange0x10": si["e"], "LastRecordChange0x30": fn["e"],
        "LastAccess0x10": si["a"], "LastAccess0x30": fn["a"], "SourceFile": r"E:\C\$MFT",
    }


def same(t):
    return {"c": t, "m": t, "e": t, "a": t}


class Journal:
    def __init__(self, first_usn):
        self.usn = first_usn
        self.rows = []

    def add(self, ts, entry, seq, parent, name, reasons):
        self.rows.append({
            "Name": name, "Extension": os.path.splitext(name)[1], "EntryNumber": entry,
            "SequenceNumber": seq, "ParentEntryNumber": parent, "ParentSequenceNumber": 1,
            "ParentPath": PARENT_PATH.get(parent, ""), "UpdateSequenceNumber": self.usn,
            "UpdateTimestamp": ts, "UpdateReasons": reasons, "FileAttributes": "Archive",
            "SourceFile": r"E:\C\$Extend\$J",
        })
        self.usn += 96

    def sorted(self):
        return sorted(self.rows, key=lambda r: r["UpdateTimestamp"])


def event(rid, ts, eid, channel, provider, data=None, user="S-1-5-18"):
    payload = {"EventData": {"Data": [{"@Name": k, "#text": v} for k, v in (data or {}).items()]}}
    return {"RecordNumber": rid, "EventRecordId": rid, "TimeCreated": ts, "EventId": eid, "Level": "Info",
            "Provider": provider, "Channel": channel, "Computer": "LAB-W11", "UserId": user,
            "SourceFile": r"E:\C\Windows\System32\winevt\Logs\%s.evtx" % channel,
            "Payload": json.dumps(payload)}


def build(out):
    mft, lnk, pf = [], [], []
    clean_j = Journal(8_000_000_000)   # wrapped journal: first USN far above its maximum size

    # Volume format / install time.
    mft.append(mft_row(0, 1, 5, "$MFT", same(T("2026-09-01 00:00:00", 1234567)),
                       same(T("2026-09-01 00:00:00", 1234567))))

    # ~50 ordinary files created during the 2026-10-10 session.
    special = {100, 105, 110, 115, 119, 120}
    for n, entry in enumerate(e for e in range(80, 131) if e not in special):
        t = T(shift("2026-10-10 08:30:00", 60 * n), 1000 + 1234 * n)
        name = "f%03d.dat" % entry
        mft.append(mft_row(entry, 1, CACHE, name, same(t), same(t)))
        clean_j.add(t, entry, 1, CACHE, name, "FileCreate")

    # report.docx (benign) and its LNK.
    rc, rm = T("2026-10-10 09:15:00", 1234567), T("2026-10-12 10:00:00", 5555555)
    mft.append(mft_row(100, 2, DOCS, "report.docx", {"c": rc, "m": rm, "e": rm, "a": rm}, same(rc)))
    clean_j.add(rc, 100, 2, DOCS, "report.docx", "FileCreate")
    clean_j.add(rm, 100, 2, DOCS, "report.docx", "DataExtend|Close")
    lc, lm = T("2026-10-10 09:15:05", 1111111), T("2026-10-12 10:00:01", 2222222)
    mft.append(mft_row(300, 1, RECENT, "report.lnk", {"c": lc, "m": lm, "e": lm, "a": lm}, same(lc)))
    clean_j.add(lc, 300, 1, RECENT, "report.lnk", "FileCreate")
    lnk.append({"SourceFile": r"E:\C\Users\bob\AppData\Roaming\Microsoft\Windows\Recent\report.lnk",
                "SourceCreated": lc, "SourceModified": lm, "SourceAccessed": lm,
                "TargetCreated": rc, "TargetModified": rm, "TargetAccessed": rm,
                "LocalPath": r"C:\Users\bob\Documents\report.docx", "TargetMFTEntryNumber": "0x64",
                "TargetMFTSequenceNumber": "0x2"})

    # budget.xlsx: T1, full SIA stomp to 2019-03-01 by UTIL.EXE on 2026-10-12 11:00.
    bc, bw = T("2026-10-10 09:20:00", 3333333), T("2026-10-10 09:25:00", 1000000)
    fake = T("2019-03-01 12:00:00", 0)
    stomp = T("2026-10-12 11:00:00", 7777777)
    mft.append(mft_row(105, 1, DOCS, "budget.xlsx", same(fake), {"c": bc, "m": bw, "e": bw, "a": bw}))
    clean_j.add(bc, 105, 1, DOCS, "budget.xlsx", "FileCreate")
    clean_j.add(bw, 105, 1, DOCS, "budget.xlsx", "DataExtend|Close")
    clean_j.add(stomp, 105, 1, DOCS, "budget.xlsx", "BasicInfoChange|Close")
    blc, bla = T("2026-10-10 09:20:10", 4444444), T("2026-10-10 09:25:03", 5555555)
    mft.append(mft_row(301, 1, RECENT, "budget.lnk", {"c": blc, "m": bla, "e": bla, "a": bla}, same(blc)))
    clean_j.add(blc, 301, 1, RECENT, "budget.lnk", "FileCreate")
    lnk.append({"SourceFile": r"E:\C\Users\bob\AppData\Roaming\Microsoft\Windows\Recent\budget.lnk",
                "SourceCreated": blc, "SourceModified": bla, "SourceAccessed": bla,
                "TargetCreated": bc, "TargetModified": bw, "TargetAccessed": bw,
                "LocalPath": r"C:\Users\bob\Documents\budget.xlsx"})   # joined by path

    # notes.txt: T3, created 2026-10-12 11:01, SIA and FNA creation backdated to 2020-05-05.
    nc = T("2026-10-12 11:01:00", 1231231)
    old = T("2020-05-05 08:00:00", 0)
    ne = T("2026-10-12 11:01:30", 5000000)
    mft.append(mft_row(110, 4, DOCS, "notes.txt", {"c": old, "m": old, "e": ne, "a": old}, same(old)))
    clean_j.add(nc, 110, 4, DOCS, "notes.tmp", "FileCreate")
    clean_j.add(T("2026-10-12 11:01:30", 4000000), 110, 4, DOCS, "notes.tmp", "RenameOldName")
    clean_j.add(T("2026-10-12 11:01:30", 4000001), 110, 4, DOCS, "notes.txt", "RenameNewName")
    clean_j.add(ne, 110, 4, DOCS, "notes.txt", "BasicInfoChange|Close")

    # photo.jpg: extracted by 7-Zip; modification time kept from the archive (2 s precision).
    pc, pe = T("2026-10-12 14:00:00", 4444444), T("2026-10-12 14:00:00", 5000000)
    mft.append(mft_row(115, 1, PICS, "photo.jpg", {"c": pc, "m": T("2018-06-01 10:00:00", 0), "e": pe, "a": pc},
                       same(pc)))
    clean_j.add(pc, 115, 1, PICS, "photo.jpg", "FileCreate")
    clean_j.add(T("2026-10-12 14:00:00", 4500000), 115, 1, PICS, "photo.jpg", "DataExtend")
    clean_j.add(pe, 115, 1, PICS, "photo.jpg", "BasicInfoChange|Close")

    # memo.docx: Office-style save. Old record 119 deleted, temp file (120) renamed over it.
    mc = T("2026-10-10 09:40:00", 7777777)
    ms = T("2026-10-12 15:00:00", 3000000)
    mft.append(mft_row(119, 3, DOCS, "memo.docx", same(mc), same(mc), in_use=False))
    mft.append(mft_row(120, 6, DOCS, "memo.docx", {"c": mc, "m": ms, "e": ms, "a": ms}, same(mc)))
    clean_j.add(mc, 119, 3, DOCS, "memo.docx", "FileCreate")
    clean_j.add(T("2026-10-12 15:00:00", 1000000), 120, 6, DOCS, "~WRL0001.tmp", "FileCreate")
    clean_j.add(T("2026-10-12 15:00:00", 2000000), 119, 3, DOCS, "memo.docx", "FileDelete|Close")
    clean_j.add(T("2026-10-12 15:00:00", 2500000), 120, 6, DOCS, "~WRL0001.tmp", "RenameOldName")
    clean_j.add(ms, 120, 6, DOCS, "memo.docx", "RenameNewName")
    mlc, mla = T("2026-10-10 09:40:05", 1212121), T("2026-10-12 15:00:01", 3434343)
    mft.append(mft_row(302, 1, RECENT, "memo.lnk", {"c": mlc, "m": mla, "e": mla, "a": mla}, same(mlc)))
    clean_j.add(mlc, 302, 1, RECENT, "memo.lnk", "FileCreate")
    lnk.append({"SourceFile": r"E:\C\Users\bob\AppData\Roaming\Microsoft\Windows\Recent\memo.lnk",
                "SourceCreated": mlc, "SourceModified": mla, "SourceAccessed": mla,
                "TargetCreated": mc, "TargetModified": ms, "TargetAccessed": ms,
                "TargetIDAbsolutePath": r"My Computer\C:\Users\bob\Documents\memo.docx",
                "TargetMFTEntryNumber": "120", "TargetMFTSequenceNumber": "6"})

    # Prefetch.
    def pf_row(name, exe, runs, count, loaded):
        r = {"SourceFilename": r"E:\C\Windows\Prefetch\%s" % name, "ExecutableName": exe,
             "Hash": name.rsplit("-", 1)[1][:-3], "RunCount": count, "LastRun": runs[0],
             "FilesLoaded": ", ".join(VOL + p for p in loaded)}
        for i, t in enumerate(runs[1:8]):
            r["PreviousRun%d" % i] = t
        return r

    pf.append(pf_row("UTIL.EXE-1A2B3C4D.pf", "UTIL.EXE",
                     [T("2026-10-12 11:01:25", 1000000), T("2026-10-12 11:00:05", 2000000)], 2,
                     [r"\WINDOWS\SYSTEM32\NTDLL.DLL", r"\USERS\BOB\DOCUMENTS\BUDGET.XLSX",
                      r"\USERS\BOB\DOCUMENTS\NOTES.TXT"]))
    pf.append(pf_row("7ZFM.EXE-0F0E0D0C.pf", "7ZFM.EXE",
                     [T("2026-10-12 13:59:58", 3000000), T("2026-10-11 16:00:00", 1000000)], 5,
                     [r"\WINDOWS\SYSTEM32\NTDLL.DLL", r"\PROGRAM FILES\7-ZIP\7Z.DLL"]))
    pf.append(pf_row("WINWORD.EXE-AABBCCDD.pf", "WINWORD.EXE",
                     [T("2026-10-12 14:59:55", 1000000), T("2026-10-12 09:59:50", 2000000)], 12,
                     [r"\WINDOWS\SYSTEM32\NTDLL.DLL", r"\USERS\BOB\DOCUMENTS\REPORT.DOCX",
                      r"\USERS\BOB\DOCUMENTS\MEMO.DOCX"]))
    pf.append(pf_row("EXPLORER.EXE-11223344.pf", "EXPLORER.EXE", [T("2026-10-12 08:31:00", 5000000)], 40,
                     [r"\WINDOWS\SYSTEM32\NTDLL.DLL"]))
    for name, t in [("UTIL.EXE-1A2B3C4D.pf", "2026-10-12 11:01:35"),
                    ("7ZFM.EXE-0F0E0D0C.pf", "2026-10-12 14:00:08"),
                    ("WINWORD.EXE-AABBCCDD.pf", "2026-10-12 15:00:05")]:
        clean_j.add(T(t, 1), 900, 1, PREFETCH, name, "DataExtend|Close")

    # Clean event logs: sessions on 10-01, 10-10 and 10-12; one routine 0.3 s NTP adjustment.
    sess = {"TSId": "1", "UserSid": SID}
    wl, el = "Microsoft-Windows-Winlogon", "EventLog"
    clean_ev = [
        event(1, T("2026-10-01 07:00:00"), 6005, "System", el),
        event(2, T("2026-10-01 07:01:00"), 7001, "System", wl, sess),
        event(3, T("2026-10-01 17:00:00"), 7002, "System", wl, sess),
        event(4, T("2026-10-01 17:05:00"), 6006, "System", el),
        event(5, T("2026-10-10 07:55:00"), 6005, "System", el),
        event(6, T("2026-10-10 08:00:00"), 7001, "System", wl, sess),
        event(7, T("2026-10-10 17:00:00"), 7002, "System", wl, sess),
        event(8, T("2026-10-12 08:30:00"), 7001, "System", wl, sess),
        event(9, T("2026-10-12 12:00:00"), 1, "System", "Microsoft-Windows-Kernel-General",
              {"NewTime": "2026-10-12T12:00:00.3000000Z", "OldTime": "2026-10-12T12:00:00.0000000Z"}),
        event(10, T("2026-10-12 18:00:00"), 7002, "System", wl, sess),
        event(11, T("2026-10-12 18:05:00"), 6006, "System", el),
        event(12, T("2026-10-15 08:00:00"), 6005, "System", el),
        event(1, T("2026-10-10 08:00:00"), 4624, "Security", "Microsoft-Windows-Security-Auditing"),
        event(2, T("2026-10-12 08:30:00"), 4624, "Security", "Microsoft-Windows-Security-Auditing"),
        event(3, T("2026-10-15 08:01:00"), 4624, "Security", "Microsoft-Windows-Security-Auditing"),
        event(1, T("2026-10-10 08:05:00"), 1033, "Application", "MsiInstaller"),
        event(2, T("2026-10-12 08:35:00"), 1033, "Application", "MsiInstaller"),
    ]

    # Tampered case: journal recreated, logs cleared, clock moved back two days,
    # a Prefetch file and a LNK file deleted.
    tj = Journal(0)
    tj.add(T("2026-10-13 02:05:30", 1), 100, 2, DOCS, "report.docx", "DataExtend|Close")
    tj.add(T("2026-10-13 02:06:00", 2), 901, 1, PREFETCH, "CLEANER.EXE-55AA66BB.pf", "FileCreate")
    tj.add(T("2026-10-13 02:07:00", 3), 902, 1, RECENT, "secret.lnk", "FileCreate")
    tj.add(T("2026-10-13 02:29:00", 4), 902, 1, RECENT, "secret.lnk", "FileDelete|Close")
    tj.add(T("2026-10-13 02:30:00", 5), 901, 1, PREFETCH, "CLEANER.EXE-55AA66BB.pf", "FileDelete|Close")
    tampered_ev = [
        event(1, T("2026-10-13 02:00:01"), 104, "System", el, {"SubjectUserName": "bob", "Channel": "System"}),
        event(2, T("2026-10-13 02:10:00"), 7001, "System", wl, sess),
        event(5, T("2026-10-11 02:20:00"), 1, "System", "Microsoft-Windows-Kernel-General",
              {"NewTime": "2026-10-11T02:20:00.0000000Z", "OldTime": "2026-10-13T02:20:00.0000000Z"}),
        event(6, T("2026-10-11 03:00:00"), 7002, "System", wl, sess),
        event(1, T("2026-10-13 02:00:00"), 1102, "Security", "Microsoft-Windows-Eventlog",
              {"SubjectUserName": "bob"}),
        event(2, T("2026-10-13 02:20:00"), 4616, "Security", "Microsoft-Windows-Security-Auditing",
              {"PreviousTime": "2026-10-13T02:20:00.0000000Z", "NewTime": "2026-10-11T02:20:00.0000000Z"}),
        event(1, T("2026-10-13 02:05:00"), 3079, "Application", "Microsoft-Windows-Ntfs"),
    ]

    for case in ("clean", "tampered"):
        write(os.path.join(out, case, "mft.csv"), MFT_COLS, mft)
        write(os.path.join(out, case, "lnk.csv"), LNK_COLS, lnk)
        write(os.path.join(out, case, "prefetch.csv"), PF_COLS, pf)
    write(os.path.join(out, "clean", "usn.csv"), USN_COLS, clean_j.sorted())
    write(os.path.join(out, "clean", "evtx.csv"), EVTX_COLS, clean_ev)
    write(os.path.join(out, "tampered", "usn.csv"), USN_COLS, tj.sorted())
    write(os.path.join(out, "tampered", "evtx.csv"), EVTX_COLS, tampered_ev)

    with open(os.path.join(out, "ground_truth.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["entry_number", "sequence_number", "path", "category", "host_time_utc", "snapshot"])
        w.writerow([105, 1, r"C:\Users\bob\Documents\budget.xlsx", "T1", "2026-10-12 11:00:00", "fixture"])
        w.writerow([110, 4, r"C:\Users\bob\Documents\notes.txt", "T3", "2026-10-12 11:01:00", "fixture"])


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "fixtures"))
