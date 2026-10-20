"""Path normalization used to join LNK and Prefetch references to MFT records."""

import re

_VOLUME_RE = re.compile(r"^\\volume\{[^}]*\}", re.IGNORECASE)
_DRIVE_RE = re.compile(r"^[a-z]:", re.IGNORECASE)
_EMBEDDED_DRIVE_RE = re.compile(r"[a-z]:\\", re.IGNORECASE)

# Directory names that anchor a path when the image was mounted under an
# unknown prefix (for example E:\C\Users\... on the examiner's workstation).
ANCHOR_ROOTS = ("\\users\\", "\\windows\\", "\\program files", "\\programdata\\")


def norm_path(path):
    """Lower-case, backslash-separated, volume-relative path starting with '\\'.

    Handles MFTECmd ('.\\Users\\bob'), LECmd ('C:\\Users\\bob\\x.docx'),
    PECmd ('\\VOLUME{guid}\\USERS\\BOB\\X.DOCX') and '\\\\?\\' prefixes.
    """
    if path is None:
        return None
    p = str(path).strip().replace("/", "\\")
    if not p:
        return None
    if p.startswith("\\\\?\\"):
        p = p[4:]
    p = _VOLUME_RE.sub("", p)
    p = _DRIVE_RE.sub("", p)
    if p.startswith("."):
        p = p[1:]
    if not p.startswith("\\"):
        p = "\\" + p
    p = re.sub(r"\\+", r"\\", p)
    if len(p) > 1:
        p = p.rstrip("\\")
    return p.lower()


def join_mft_path(parent_path, file_name):
    parent = norm_path(parent_path) or "\\"
    name = (file_name or "").strip().lower()
    if parent == "\\":
        return "\\" + name
    return parent + "\\" + name


def from_shell_path(path):
    """Extract a drive path from LECmd's TargetIDAbsolutePath ('My Computer\\C:\\...')."""
    if not path:
        return None
    m = _EMBEDDED_DRIVE_RE.search(path)
    return norm_path(path[m.start():]) if m else None


def strip_prefix(path, prefix):
    """Remove an examiner mount prefix such as '\\c' (already normalized)."""
    if path and prefix and path.startswith(prefix + "\\"):
        return path[len(prefix):]
    return path


def anchor_suffixes(path):
    """Candidate volume paths obtained by cutting at well-known root folders."""
    if not path:
        return []
    out = []
    for root in ANCHOR_ROOTS:
        i = path.find(root)
        if i > 0:
            out.append(path[i:])
    return out


def basename(path):
    if not path:
        return ""
    return path.replace("/", "\\").rsplit("\\", 1)[-1].lower()


def parent(path):
    if not path or "\\" not in path:
        return None
    head = path.rsplit("\\", 1)[0]
    return head or "\\"
