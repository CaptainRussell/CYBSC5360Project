"""Seeded random variants of the synthetic Windows record files, for checking that the
browser version's date checks agree with the Python version beyond the two planted cases.

Each variant starts from tests/fixtures/clean or tampered and changes cells at random:
times moved by seconds or years, set to whole seconds, given a time zone, blanked or
made impossible (30 February); flags flipped; record numbers and sequence numbers
changed; rows duplicated, dropped or shuffled; journal reasons recombined; names
given commas, quotes and line breaks; event payloads with clock-change fields or
broken JSON; Prefetch runs placed next to journal changes.

    python tests/make_date_stress.py SEED OUT_DIR
"""

import csv
import io
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REASONS = ["FileCreate", "BasicInfoChange", "DataExtend", "Close", "FileDelete", "RenameOldName", "RenameNewName", "SecurityChange"]


def _read(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.reader(fh))


def _ts(rnd, v):
    r = rnd.random()
    if not v or r < 0.05:
        return rnd.choice(["", "2026-02-30 10:00:00.0000000", "not a time", "1601-01-01 00:00:00.0000000"])
    try:
        date, _, rest = v.partition(" ")
        clock, _, frac = rest.partition(".")
        y, mo, d = (int(x) for x in date.split("-"))
        h, mi, s = (int(x) for x in clock.split(":"))
    except ValueError:
        return v
    if r < 0.25:
        s = (s + rnd.randrange(-3, 4)) % 60
    elif r < 0.35:
        y = rnd.choice([2019, 2020, 2026, 2027])
    elif r < 0.45:
        frac = "0000000"
    elif r < 0.5:
        mi = rnd.randrange(60)
    out = "%04d-%02d-%02d %02d:%02d:%02d.%s" % (y, mo, d, h, mi, s, (frac or "0").ljust(7, "0")[:7])
    if rnd.random() < 0.04:
        out = out.replace(" ", "T") + rnd.choice(["Z", "+02:00", "-0500"])
    return out


def mutate(rows, rnd, kind):
    head, body = rows[0], rows[1:]
    tcols = [i for i, h in enumerate(head) if any(k in h for k in ("Created", "Modified", "Accessed", "Change", "Timestamp", "TimeCreated", "Run"))
             and not h.startswith("Volume")]
    out = []
    for r in body:
        r = r + [""] * (len(head) - len(r))
        if rnd.random() < 0.05:
            continue
        r = list(r)
        for i in tcols:
            if rnd.random() < 0.35:
                r[i] = _ts(rnd, r[i])
        for i, h in enumerate(head):
            if h in ("InUse", "IsDirectory", "IsAds") and rnd.random() < 0.04:
                r[i] = rnd.choice(["True", "False", "", "1", "yes"])
            if h in ("SequenceNumber", "EntryNumber", "ParentEntryNumber", "TargetMFTEntryNumber", "TargetMFTSequenceNumber") and rnd.random() < 0.03:
                r[i] = rnd.choice(["", "0x1f", "12.0", str(rnd.randrange(1, 120)), "abc"])
            if h == "UpdateReasons" and rnd.random() < 0.3:
                r[i] = "|".join(rnd.sample(REASONS, rnd.randrange(1, 4)))
            if h in ("FileName", "Name") and rnd.random() < 0.03:
                r[i] = r[i] + rnd.choice([",x", ' "q"', "\nnext", ""])
            if h == "NameType" and rnd.random() < 0.05:
                r[i] = rnd.choice(["Dos", "Windows", "DosWindows", "Posix"])
            if h == "Payload" and rnd.random() < 0.1:
                r[i] = rnd.choice(['{"EventData": {"Data": [{"@Name": "PreviousTime", "#text": "2026-10-10 10:00:00.0000000"}, '
                                   '{"@Name": "NewTime", "#text": "2026-10-10 12:30:00.0000000"}]}}',
                                   '{"EventData": {"Data": {"@Name": "OldTime", "#text": "2026-10-10 10:00:00.0000000"}}}',
                                   'not json "@Name": "NewTime", "#text": "2026-10-10 11:00:00.0000000"', "", "[1, 2]"])
            if h == "EventId" and rnd.random() < 0.05:
                r[i] = rnd.choice(["104", "1102", "3079", "4616", "1", "7001", "7002", "6005", "41"])
            if h == "EventRecordId" and rnd.random() < 0.05:
                r[i] = str(rnd.randrange(1, 400))
            if h == "RunCount" and rnd.random() < 0.1:
                r[i] = rnd.choice(["", "1", "5", "9"])
        out.append(r)
        if rnd.random() < 0.04:
            out.append(list(r))
    if rnd.random() < 0.5:
        rnd.shuffle(out)
    return [head] + out


def build(seed, out_dir):
    rnd = random.Random(seed)
    base = os.path.join(HERE, "fixtures", rnd.choice(["clean", "tampered"]))
    os.makedirs(out_dir, exist_ok=True)
    for name in sorted(os.listdir(base)):
        if not name.endswith(".csv"):
            continue
        rows = mutate(_read(os.path.join(base, name)), rnd, name)
        buf = io.StringIO()
        csv.writer(buf).writerows(rows)
        with open(os.path.join(out_dir, name), "w", newline="", encoding="utf-8-sig") as fh:
            fh.write(buf.getvalue())
    return out_dir


if __name__ == "__main__":
    build(int(sys.argv[1]), sys.argv[2])
