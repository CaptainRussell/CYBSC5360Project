"""Command line: py -3 -m blockrecover <block folder or .zip> [--out folder]"""

import argparse
import sys

from . import recover


def main(argv=None):
    ap = argparse.ArgumentParser(prog="blockrecover",
                                 description="Sort shuffled 512-byte blocks into files and rebuild each file.")
    ap.add_argument("blocks", help="a folder of block files, or a .zip holding one")
    ap.add_argument("--out", default="recovered", help="folder for the rebuilt files and the report")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    def progress(stage, msg):
        if not a.quiet:
            print("%-10s %s" % (stage, msg), flush=True)

    R = recover.run(a.blocks, progress=progress)
    s = recover.write(R, a.out)
    try:
        from . import report
        report.write(R, s, a.out)
    except ImportError:
        pass
    print()
    for f in s["files"]:
        print("%-5s %-14s %4d blocks  %s  %s" % (f["kind"], f["name"], f["blocks"],
                                                "checked" if f["ok"] else "INCOMPLETE", f["note"]))
    if s["unplaced"]:
        print("not placed: %d blocks" % len(s["unplaced"]))
    print("written to", a.out)
    return 0 if all(f["ok"] for f in s["files"]) and not s["unplaced"] else 1


if __name__ == "__main__":
    sys.exit(main())
