"""Timestamp handling.

All times are stored as Windows FILETIME integers (100 ns intervals since
1601-01-01 UTC) so that comparisons keep the full NTFS precision.
"""

import re
from datetime import datetime, timedelta, timezone

TICKS_PER_SECOND = 10_000_000
_EPOCH = datetime(1601, 1, 1)

_TS_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})"
    r"(?:\.(\d{1,7})\d*)?"
    r"\s*(Z|[+-]\d{2}:?\d{2})?$"
)


def parse_ts(value):
    """Parse a Zimmerman-style timestamp ('yyyy-MM-dd HH:mm:ss.fffffff') to FILETIME.

    Accepts ISO 8601 variants with 'T', 'Z' or a numeric offset. Returns None
    for blank or unparseable values.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    m = _TS_RE.match(s)
    if not m:
        return None
    y, mo, d, h, mi, se = (int(m.group(i)) for i in range(1, 7))
    frac = (m.group(7) or "").ljust(7, "0")
    try:
        dt = datetime(y, mo, d, h, mi, se)
    except ValueError:
        return None
    tz = m.group(8)
    if tz and tz != "Z":
        sign = 1 if tz[0] == "+" else -1
        hh, mm = int(tz[1:3]), int(tz[-2:])
        dt -= sign * timedelta(hours=hh, minutes=mm)
    delta = dt - _EPOCH
    seconds = delta.days * 86400 + delta.seconds
    ticks = seconds * TICKS_PER_SECOND + int(frac)
    # FILETIME 0 (1601-01-01) is how parsers render an empty timestamp.
    return ticks if ticks > 0 else None


def fmt_ts(ticks):
    """Format FILETIME as 'yyyy-MM-dd HH:mm:ss.fffffff' (UTC)."""
    if ticks is None:
        return ""
    seconds, frac = divmod(int(ticks), TICKS_PER_SECOND)
    dt = _EPOCH + timedelta(seconds=seconds)
    return dt.strftime("%Y-%m-%d %H:%M:%S") + ".%07d" % frac


def subsecond(ticks):
    """The sub-second part of a FILETIME in 100 ns units."""
    return None if ticks is None else int(ticks) % TICKS_PER_SECOND


def seconds(n):
    """Convert seconds to FILETIME ticks."""
    return int(round(n * TICKS_PER_SECOND))


def diff_seconds(a, b):
    """a - b in seconds (float)."""
    return (a - b) / TICKS_PER_SECOND


def now_utc_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
