#!/bin/sh
# Double-click to open the point-and-click window in your browser.
# (From a terminal you can also pass a drive image: "./Run ADS (Mac).command" usb.img)
cd "$(dirname "$0")" || exit 1
if [ $# -eq 0 ]; then
    python3 -m ads gui
else
    python3 start.py "$@"
fi
