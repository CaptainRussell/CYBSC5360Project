"""Build the browser version: one offline HTML file that runs the whole tool.

    python -m ads build-web            # writes "Artifact Disagreement Scorer.html" next to this folder

The analysis is a JavaScript port of the Python modules (tool/web/src). It must give
the same answers, so the tables it relies on (check names and wording, file-type
tables, signatures, default settings) are not copied by hand: they are generated
here from the Python modules themselves and embedded as PYDATA. The report pages are
the same templates the Python version writes, so a browser run and a command-line
run produce the same report.
"""

import json
import os

from . import __version__, config, explain, ntfs_briefing, pipeline, sniff, triage
from .theme import AUTHOR, THEME_CSS, THEME_JS, TOOL

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(os.path.dirname(HERE), "web")
SRC = os.path.join(WEB, "src")
ENGINE_FILES = ["util.js", "paths.js", "fat.js", "ntfs.js", "sniff.js", "triage.js", "dates.js", "datereport.js"]
OUT_NAME = TOOL + ".html"


def _latin1(b):
    return b.decode("latin-1")


def pydata():
    """Every table the JavaScript engine needs, taken from the Python modules."""
    return {
        "version": __version__,
        "tool": TOOL, "author": AUTHOR,
        "triage": {
            "RULES": triage.RULES, "TYPE_LABEL": triage.TYPE_LABEL,
            "PLAIN": {k: list(v) for k, v in triage.PLAIN.items()}, "EXT_PLAIN": triage.EXT_PLAIN,
            "STOP": sorted(_latin1(s) for s in triage.STOP), "JAVA_LIKE": sorted(triage.JAVA_LIKE),
            "MAX_READ": triage.MAX_READ, "STRONG": triage.STRONG, "MODERATE": triage.MODERATE,
        },
        "sniff": {
            "MAGIC": [[t, fam, magic.hex(), off] for t, fam, magic, off in sniff.MAGIC],
            "EXPECTED": {k: sorted(v) for k, v in sniff.EXPECTED.items()},
            "PERSONAL_TYPES": sorted(sniff.PERSONAL_TYPES), "STRONG_FAMILIES": sorted(sniff.STRONG_FAMILIES),
            "EMBED_SIGS": [[sig.hex(), name] for sig, name in sniff.EMBED_SIGS],
        },
        "config": {
            "DEFAULTS": config.DEFAULTS, "RULE_IDS": config.RULE_IDS,
            "RULE_SOURCES": {k: sorted(v) for k, v in config.RULE_SOURCES.items()},
            "TIME_RULES": sorted(config.TIME_RULES),
            "INDICATOR_DEGRADES": {k: sorted(v) for k, v in config.INDICATOR_DEGRADES.items()},
        },
        "explain": {"RULE_PLAIN": {k: list(v) for k, v in explain.RULE_PLAIN.items()}, "INDICATOR_PLAIN": explain.INDICATOR_PLAIN},
        "ntfs_briefing": {"STRONG": ntfs_briefing.STRONG, "DRIVE_WIDE": ntfs_briefing.DRIVE_WIDE,
                          "DRIVE_WIDE_MIN": ntfs_briefing.DRIVE_WIDE_MIN, "RULE_TECH": ntfs_briefing.RULE_TECH,
                          "SOURCES": [list(s) for s in ntfs_briefing.SOURCES]},
        "pipeline": {"CSV_KINDS": [[k, p] for k, p in pipeline.CSV_KINDS], "CSV_SKIP": pipeline.CSV_SKIP},
    }


def engine_js():
    """The analysis engine as one script (used by the page's worker, and by the Node tests)."""
    parts = ["const PYDATA = %s;\n" % json.dumps(pydata(), ensure_ascii=False)]
    for name in ENGINE_FILES:
        with open(os.path.join(SRC, name), encoding="utf-8") as fh:
            parts.append("/* ---- %s ---- */\n%s\n" % (name, fh.read()))
    return "".join(parts)


def report_templates():
    """The two report pages, exactly as the Python version writes them, minus their data."""
    from .briefing import HEAD, TEMPLATE
    with open(TEMPLATE, encoding="utf-8") as fh:
        first = fh.read().replace("/*__THEME_CSS__*/", THEME_CSS, 1).replace("/*__THEME_JS__*/", THEME_JS, 1)
    return {"firstlook_head": HEAD, "firstlook": first, "date": ntfs_briefing.page_template()}


def build(out=None):
    out = out or os.path.join(os.path.dirname(HERE), OUT_NAME)
    with open(os.path.join(WEB, "app.html"), encoding="utf-8") as fh:
        page = fh.read()
    with open(os.path.join(WEB, "app.js"), encoding="utf-8") as fh:
        app = fh.read()
    with open(os.path.join(WEB, "worker.js"), encoding="utf-8") as fh:
        engine = engine_js() + "/* ---- worker.js ---- */\n" + fh.read()

    def script_safe(s):
        # The engine sits inside a <script> element: nothing in it may close the element early.
        return s.replace("</script", "<\\/script").replace("<!--", "<\\!--")
    page = (page.replace("/*@css@*/", THEME_CSS, 1)
                .replace("/*@engine@*/", script_safe(engine), 1)
                .replace("/*@templates@*/null", script_safe(json.dumps(report_templates(), ensure_ascii=False)), 1)
                .replace("/*@theme_js@*/", THEME_JS, 1)
                .replace("/*@app@*/", script_safe(app), 1)
                .replace("@version@", __version__).replace("@tool@", TOOL).replace("@author@", AUTHOR))
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(page)
    return out
