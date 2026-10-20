"""Easiest way to run ADS: double-click a launcher, or run "python start.py", then drop the image file in.

It asks for the drive image, makes the first-look report next to the current folder, and opens it.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ads.cli import main  # noqa: E402


def ask():
    print("ADS first-look report")
    print("Drag the drive image file into this window (or type its path), then press Enter.")
    while True:
        path = input("> ").strip().strip('"').strip("'").replace("\\ ", " ")
        if os.path.isfile(path):
            return path
        print("That file was not found. Try again, or press Ctrl+C to quit.")


if __name__ == "__main__":
    args = sys.argv[1:] or [ask()]
    try:
        main(args)
    finally:
        if len(sys.argv) <= 2 and sys.stdin.isatty():
            input("\nPress Enter to close.")
