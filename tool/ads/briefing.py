"""Render the interactive triage briefing (a single self-contained HTML file)."""

import json
import os

TEMPLATE = os.path.join(os.path.dirname(__file__), "briefing_template.html")
HEAD = ('<!doctype html>\n<html lang="en">\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n')


def render(data, standalone=True):
    with open(TEMPLATE, encoding="utf-8") as fh:
        page = fh.read()
    # File names come from the evidence: keep them inert inside the script element.
    blob = json.dumps(data, ensure_ascii=False, default=str).replace("</", "<\\/").replace("<!--", "<\\!--")
    page = page.replace("/*__DATA__*/null", blob, 1)
    return (HEAD + page + "\n</html>\n") if standalone else page
