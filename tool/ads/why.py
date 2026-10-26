"""Why was (or wasn't) a file flagged? Every check's answer for chosen files.

    python -m ads why IMAGE --key proof/project2_answer_key.csv [--out why.csv]

Runs the first-look checks exactly as the report does (it only reads the image
and changes no check), then, for every file named in the answer key, writes what
each of the eight checks answered and why: fired (with its plain sentence),
looked and found nothing unusual, or could not be checked (with the reason).
This is how misses are explained from evidence rather than guessed.
"""

import csv
import os

from . import proof
from .triage import NOT_EVALUABLE, RULES, VIOLATED, Triage

PLAIN = {VIOLATED: "fired", NOT_EVALUABLE: "could not check"}


def _detail(outcome, d):
    if outcome == VIOLATED:
        return d.get("say", "")
    if outcome == NOT_EVALUABLE:
        extra = ", ".join("%s=%s" % (k, v) for k, v in d.items() if k != "reason" and not isinstance(v, (list, dict)))
        return d.get("reason", "") + (" (%s)" % extra if extra else "")
    keep = {k: v for k, v in d.items() if not isinstance(v, (list, dict))}
    return ", ".join("%s=%s" % kv for kv in keep.items())


def explain(image, key_path, out_csv):
    key = proof.load_key(key_path)
    t = Triage(image)
    try:
        t.collect().run()
    finally:
        t.close()
    rows, lines = [], []
    for k in key:
        items = [i for i in t.items if any(proof._matches(i["path"], a) for a in k["alts"])]
        if not items:
            rows.append([k.get("item", ""), k["kind"], k["path"], "", "", "not found in the image", ""])
            lines.append("%s: not found in the image under %s" % (k.get("item", ""), k["path"]))
            continue
        for i in items:
            if i.get("noise"):
                rows.append([k.get("item", ""), k["kind"], i["path"], i["type"], "", "set aside as clutter", i["noise"]])
                lines.append("%s: set aside as clutter (%s)" % (i["path"], i["noise"]))
                continue
            lines.append("%s  [%s, %s bytes, score %d]" % (i["path"], i["type"], format(i["size"], ","),
                                                         round(i.get("score", 0) * 100)))
            for rid in RULES:
                outcome, d = i["outcomes"][rid]
                text = _detail(outcome, d)
                rows.append([k.get("item", ""), k["kind"], i["path"], i["type"], rid,
                             PLAIN.get(outcome, "looked; nothing unusual"), text])
                lines.append("   %-3s %-24s %s" % (rid, PLAIN.get(outcome, "looked; nothing unusual"), text[:150]))
    os.makedirs(os.path.dirname(os.path.abspath(out_csv)), exist_ok=True)
    with open(out_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["item", "kind", "path_in_image", "type", "check", "answer", "why"])
        w.writerows(rows)
    return lines
