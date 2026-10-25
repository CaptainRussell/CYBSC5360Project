"""Graphical, plain-language evaluation summary: an ROC chart and a readable page.

Turns the numbers from evaluate.py into one web page a non-specialist can read,
with a drawn ROC curve (ADS against the best single check) built as inline SVG,
so it needs no plotting library.
"""

import html
import os

from .explain import rule_name

W, H, PAD = 460, 360, 54
CARDINAL, GOLD, LINE, INK, MUTED = "#C8102E", "#B07A0C", "#DAD6D6", "#1A1A1A", "#5E5A5A"


def _x(fpr):
    return PAD + fpr * (W - 2 * PAD)


def _y(tpr):
    return H - PAD - tpr * (H - 2 * PAD)


def _poly(points):
    return " ".join("%.1f,%.1f" % (_x(f), _y(t)) for f, t in points)


def roc_svg(ads_pts, rule_pts, rule_label):
    grid = ""
    for g in (0, 0.25, 0.5, 0.75, 1.0):
        grid += ('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="1"/>'
                 % (_x(g), _y(0), _x(g), _y(1), LINE))
        grid += ('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="1"/>'
                 % (_x(0), _y(g), _x(1), _y(g), LINE))
        grid += ('<text x="%.1f" y="%.1f" font-size="11" fill="%s" text-anchor="middle">%g</text>'
                 % (_x(g), H - PAD + 16, MUTED, g))
        grid += ('<text x="%.1f" y="%.1f" font-size="11" fill="%s" text-anchor="end">%g</text>'
                 % (PAD - 8, _y(g) + 4, MUTED, g))
    return (
        '<svg viewBox="0 0 %d %d" width="100%%" style="max-width:480px" role="img" '
        'aria-label="ROC curve: ADS against the best single check">'
        '<rect x="%d" y="%d" width="%d" height="%d" fill="none" stroke="%s"/>'
        '%s'
        '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-dasharray="4 4" stroke-width="1"/>'
        '<polyline points="%s" fill="none" stroke="%s" stroke-width="1.6"/>'
        '<polyline points="%s" fill="none" stroke="%s" stroke-width="2.4"/>'
        '<text x="%d" y="20" font-size="13" font-weight="700" fill="%s" text-anchor="middle">Detection vs. false alarms</text>'
        '<text x="%d" y="%d" font-size="12" fill="%s" text-anchor="middle">False alarm rate</text>'
        '<text x="16" y="%d" font-size="12" fill="%s" text-anchor="middle" transform="rotate(-90 16 %d)">Detection rate</text>'
        '</svg>'
        % (W, H, PAD, PAD, W - 2 * PAD, H - 2 * PAD, LINE, grid,
           _x(0), _y(0), _x(1), _y(1), MUTED,
           _poly(rule_pts), GOLD, _poly(ads_pts), CARDINAL,
           W // 2, INK, W // 2, H - 14, MUTED, H // 2, MUTED, H // 2))


def _pct(v):
    return "–" if v is None else "%.0f%%" % (v * 100)


def render(result, out_dir, target_fpr=0.01):
    rows = result["detectors"]
    ads = next(r for r in rows if r["detector"] == "ADS")
    singles = [r for r in rows if r["detector"] != "ADS" and r["auc"] is not None]
    best = max(singles, key=lambda r: r["auc"]) if singles else None
    fpr_key = "tpr_at_fpr_%g" % target_fpr
    svg = roc_svg(ads["points"], best["points"] if best else [(0, 0), (1, 1)],
                  best["detector"] if best else "")

    best_rid = best["detector"].split()[0] if best else ""
    verdict = "—"
    if best:
        if ads[fpr_key] > best[fpr_key]:
            verdict = ("At a %g%% false-alarm rate, ADS caught %s of the tampering, more than the best single "
                       "check (%s, %s). Combining the records helped."
                       % (target_fpr * 100, _pct(ads[fpr_key]), rule_name(best_rid), _pct(best[fpr_key])))
        elif ads[fpr_key] == best[fpr_key]:
            verdict = ("At a %g%% false-alarm rate, ADS matched the best single check (%s) at %s. Combining did "
                       "not help here." % (target_fpr * 100, rule_name(best_rid), _pct(ads[fpr_key])))
        else:
            verdict = ("At a %g%% false-alarm rate, the best single check (%s, %s) beat ADS (%s). On this data, "
                       "combining did not help — see the per-check table."
                       % (target_fpr * 100, rule_name(best_rid), _pct(best[fpr_key]), _pct(ads[fpr_key])))

    def bar(v, color):
        w = 0 if v is None else int(round(v * 100))
        return ('<div class="track"><span style="width:%d%%;background:%s"></span></div>' % (w, color))

    trows = ""
    for r in sorted(rows, key=lambda r: (r["detector"] != "ADS", -(r["auc"] or 0))):
        name = "ADS (all checks together)" if r["detector"] == "ADS" else \
               "%s — %s" % (r["detector"].split()[0], rule_name(r["detector"].split()[0]))
        color = CARDINAL if r["detector"] == "ADS" else GOLD
        trows += ('<tr%s><td>%s</td><td>%s</td><td>%s%s</td><td>%s</td></tr>'
                  % (' class="ads"' if r["detector"] == "ADS" else "",
                     html.escape(name), "–" if r["auc"] is None else "%.2f" % r["auc"],
                     _pct(r[fpr_key]), bar(r[fpr_key], color), _pct(r.get("precision"))))

    page = TEMPLATE.replace("@svg@", svg).replace("@verdict@", html.escape(verdict)) \
        .replace("@tampered@", str(result["tampered"])).replace("@benign@", str(result["benign"])) \
        .replace("@fpr@", "%g" % (target_fpr * 100)).replace("@rows@", trows) \
        .replace("@adsauc@", "–" if ads["auc"] is None else "%.2f" % ads["auc"])
    with open(os.path.join(out_dir, "evaluation.html"), "w", encoding="utf-8") as fh:
        fh.write(page)
    with open(os.path.join(out_dir, "roc.svg"), "w", encoding="utf-8") as fh:
        fh.write('<?xml version="1.0" encoding="utf-8"?>\n' + svg)
    return os.path.join(out_dir, "evaluation.html")


TEMPLATE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>ADS Evaluation</title>
<style>
:root{--cardinal:#C8102E;--gold:#B07A0C;--ink:#1A1A1A;--muted:#5E5A5A;--line:#DAD6D6;--paper:#fff;--panel:#F7F4F2;
--head:Cambria,Georgia,serif;--body:Calibri,"Segoe UI",Arial,sans-serif}
@media(prefers-color-scheme:dark){:root{--cardinal:#E2304C;--gold:#F1BE48;--ink:#EDE8E6;--muted:#ADA5A3;--line:#3A3434;--paper:#151212;--panel:#1F1A1A;color-scheme:dark}}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:17px/1.55 var(--body)}
.wrap{max-width:860px;margin:0 auto;padding:0 16px}
.band{background:var(--cardinal);color:#fff;border-bottom:8px solid #F1BE48}.band .wrap{padding:26px 16px}
h1{font-family:var(--head);font-size:clamp(24px,4vw,36px);margin:4px 0}
h2{font-family:var(--head);color:var(--cardinal);font-size:22px;margin:24px 0 6px}
.eyebrow{color:#F1BE48;font-weight:700;letter-spacing:.14em;text-transform:uppercase;font-size:13px}
.verdict{font-size:19px;background:var(--panel);border-left:6px solid var(--cardinal);border-radius:8px;padding:14px 16px;margin:18px 0}
.cols{display:grid;grid-template-columns:480px 1fr;gap:24px;align-items:center}
@media(max-width:800px){.cols{grid-template-columns:1fr}}
.key span{display:inline-flex;align-items:center;gap:7px;margin-right:16px;font-size:15px}
.key i{width:22px;height:4px;border-radius:2px;display:inline-block}
table{border-collapse:collapse;width:100%;margin:10px 0;font-size:15px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line)}
th{color:var(--muted);font-size:13px;text-transform:uppercase;letter-spacing:.05em}
tr.ads td{background:var(--panel);font-weight:700}
.track{display:inline-block;vertical-align:middle;width:120px;height:10px;background:var(--line);border-radius:5px;overflow:hidden;margin-left:8px}
.track span{display:block;height:100%}
footer{color:var(--muted);font-size:14px;padding:26px 0 50px}
</style></head><body>
<div class="band"><div class="wrap">
<div class="eyebrow">Artifact Disagreement Scorer · how well it worked</div>
<h1>Did combining the checks help?</h1></div></div>
<div class="wrap">
<p class="verdict">@verdict@</p>
<div class="cols">
<div>@svg@
<div class="key"><span><i style="background:#C8102E"></i>ADS (all checks)</span><span><i style="background:#B07A0C"></i>best single check</span><span><i style="background:#999;height:0;border-top:2px dashed #999"></i>pure guessing</span></div>
</div>
<div>
<p>The curve shows the trade-off between catching tampering (up) and raising false alarms (right). A curve
that hugs the top-left corner is better. The straight diagonal is what random guessing would do.</p>
<p>Tested on <b>@tampered@</b> tampered files and <b>@benign@</b> clean files. ADS overall score (area under
the curve): <b>@adsauc@</b> out of 1.00.</p>
</div></div>

<h2>Every check, side by side</h2>
<p>“Caught at @fpr@% false alarms” is the share of tampering each check would find if it were tuned to raise a
false alarm on only @fpr@% of clean files — the fair way to compare them.</p>
<table><tr><th>Check</th><th>Overall (0–1)</th><th>Caught at @fpr@% false alarms</th><th>Precision</th></tr>@rows@</table>
</div>
<footer><div class="wrap">Artifact Disagreement Scorer · CPRE 5360 · Numbers come from the ground-truth answer key for this test set.</div></footer>
</body></html>"""
