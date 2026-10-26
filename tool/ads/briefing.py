"""Render the interactive triage briefing (a single self-contained HTML file)."""

import csv
import json
import os

TEMPLATE = os.path.join(os.path.dirname(__file__), "briefing_template.html")
HEAD = ('<!doctype html>\n<html lang="en">\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n')


def render(data, standalone=True):
    with open(TEMPLATE, encoding="utf-8") as fh:
        page = fh.read()
    # File names come from the evidence: keep them inert inside the script element.
    from .theme import THEME_CSS, THEME_JS
    blob = json.dumps(data, ensure_ascii=False, default=str).replace("</", "<\\/").replace("<!--", "<\\!--")
    page = page.replace("/*__THEME_CSS__*/", THEME_CSS, 1).replace("/*__THEME_JS__*/", THEME_JS, 1)
    page = page.replace("/*__DATA__*/null", blob, 1)
    return (HEAD + page + "\n</html>\n") if standalone else page


def write_triage(t, out, top=40):
    """Write the first-look outputs for a finished Triage: triage.json, leads.csv and briefing.html.

    Shared by the command line and the point-and-click window, so both leave the same files.
    Returns (data, path of briefing.html).
    """
    data = t.to_json(top=top)
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "triage.json"), "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, default=str)
    with open(os.path.join(out, "leads.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["rank", "score_out_of_100", "level", "file", "clues", "check_ids", "what_was_found", "type",
                    "size_bytes", "last_changed_utc"])
        for n, i in enumerate(t.leads(), 1):
            says = " | ".join(i["outcomes"][r][1].get("say", "") for r in i["fired"])
            level = ("Look first" if i["score"] >= data["tiers"]["strong"]
                     else "Worth a look" if i["score"] >= data["tiers"]["moderate"] else "Minor")
            names = "; ".join(data["rules"][r]["name"] for r in i["fired"])
            w.writerow([n, round(i["score"] * 100), level, i["path"], names, " ".join(i["fired"]), says,
                        i["type"], i["size"], i["modified"]])
    html = os.path.join(out, "briefing.html")
    with open(html, "w", encoding="utf-8") as fh:
        fh.write(render(data))
    return data, html
