"""Graphical, plain-language evaluation summary: an ROC chart and a readable page.

Turns the numbers from evaluate.py into one web page a non-specialist can read,
with a drawn ROC curve (ADS against the best single check) built as inline SVG,
so it needs no plotting library.
"""

import html
import os

from .explain import rule_name

W, H, PAD = 460, 360, 54
ADS_C, ONE_C, LINE, INK, MUTED = "var(--accent)", "var(--accent2)", "var(--line2)", "var(--text)", "var(--muted)"


def _x(fpr):
    return PAD + fpr * (W - 2 * PAD)


def _y(tpr):
    return H - PAD - tpr * (H - 2 * PAD)


def _poly(points):
    return " ".join("%.1f,%.1f" % (_x(f), _y(t)) for f, t in points)


def roc_svg(ads_pts, rule_pts, rule_label):
    grid = ""
    for g in (0, 0.25, 0.5, 0.75, 1.0):
        grid += ('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" style="stroke:%s" stroke-width="1"/>'
                 % (_x(g), _y(0), _x(g), _y(1), LINE))
        grid += ('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" style="stroke:%s" stroke-width="1"/>'
                 % (_x(0), _y(g), _x(1), _y(g), LINE))
        grid += ('<text x="%.1f" y="%.1f" font-size="11" style="fill:%s" text-anchor="middle">%g</text>'
                 % (_x(g), H - PAD + 16, MUTED, g))
        grid += ('<text x="%.1f" y="%.1f" font-size="11" style="fill:%s" text-anchor="end">%g</text>'
                 % (PAD - 8, _y(g) + 4, MUTED, g))
    return (
        '<svg viewBox="0 0 %d %d" width="100%%" style="max-width:480px" role="img" '
        'aria-label="ROC curve: ADS against the best single check">'
        '<rect x="%d" y="%d" width="%d" height="%d" fill="none" style="stroke:%s"/>'
        '%s'
        '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" style="stroke:%s" stroke-dasharray="4 4" stroke-width="1"/>'
        '<polyline points="%s" fill="none" style="stroke:%s" stroke-width="2"/>'
        '<polyline points="%s" fill="none" style="stroke:%s" stroke-width="2.6"/>'
        '<text x="%d" y="20" font-size="13" font-weight="700" style="fill:%s" text-anchor="middle">Detection vs. false alarms</text>'
        '<text x="%d" y="%d" font-size="12" style="fill:%s" text-anchor="middle">False alarm rate</text>'
        '<text x="16" y="%d" font-size="12" style="fill:%s" text-anchor="middle" transform="rotate(-90 16 %d)">Detection rate</text>'
        '</svg>'
        % (W, H, PAD, PAD, W - 2 * PAD, H - 2 * PAD, LINE, grid,
           _x(0), _y(0), _x(1), _y(1), MUTED,
           _poly(rule_pts), ONE_C, _poly(ads_pts), ADS_C,
           W // 2, INK, W // 2, H - 14, MUTED, H // 2, MUTED, H // 2))


def _pct(v):
    return "–" if v is None else "%.0f%%" % (v * 100)


def render(result, out_dir, target_fpr=0.01):
    rows = result["detectors"]
    ads = next(r for r in rows if r["detector"] == "ADS")
    fpr_key = "tpr_at_fpr_%g" % target_fpr
    singles = [r for r in rows if r["detector"] != "ADS" and r["auc"] is not None]
    # "Best single check" means best at the false-alarm rate the verdict talks about (success
    # criterion 1); overall AUC only breaks ties.
    best = max(singles, key=lambda r: (r[fpr_key], r["auc"])) if singles else None
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
        return ('<div class="bar" style="width:120px;display:inline-block;vertical-align:middle;margin-left:8px">'
                '<i data-w="%d" style="background:%s"></i></div>' % (w, color))

    trows = ""
    for r in sorted(rows, key=lambda r: (r["detector"] != "ADS", -(r["auc"] or 0))):
        name = "ADS (all checks together)" if r["detector"] == "ADS" else \
               "%s — %s" % (r["detector"].split()[0], rule_name(r["detector"].split()[0]))
        color = ADS_C if r["detector"] == "ADS" else ONE_C
        trows += ('<tr%s><td>%s</td><td class="num">%s</td><td>%s%s</td><td class="num">%s</td></tr>'
                  % (' class="ads"' if r["detector"] == "ADS" else "",
                     html.escape(name), "–" if r["auc"] is None else "%.2f" % r["auc"],
                     _pct(r[fpr_key]), bar(r[fpr_key], color), _pct(r.get("precision"))))

    from .theme import THEME_CSS, THEME_JS, icon
    page = TEMPLATE.replace("@css@", THEME_CSS).replace("@js@", THEME_JS).replace("@sun@", icon("sun")) \
        .replace("@print@", icon("print")).replace("@ico1@", icon("overview")).replace("@ico2@", icon("all")).replace("@svg@", svg).replace("@verdict@", html.escape(verdict)) \
        .replace("@tampered@", str(result["tampered"])).replace("@benign@", str(result["benign"])) \
        .replace("@fpr@", "%g" % (target_fpr * 100)).replace("@rows@", trows) \
        .replace("@adsauc@", "–" if ads["auc"] is None else "%.2f" % ads["auc"])
    with open(os.path.join(out_dir, "evaluation.html"), "w", encoding="utf-8") as fh:
        fh.write(page)
    with open(os.path.join(out_dir, "roc.svg"), "w", encoding="utf-8") as fh:
        # A standalone file has no page to define the theme colours, so give it fixed (light) ones.
        alone = svg.replace(">", '><style>svg{--accent:#0891B2;--accent2:#7C3AED;--line2:#C5D1E2;--text:#0F172A;'
                                 '--muted:#475569}</style>', 1).replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" ', 1)
        fh.write('<?xml version="1.0" encoding="utf-8"?>\n' + alone)
    return os.path.join(out_dir, "evaluation.html")


TEMPLATE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>ADS Evaluation</title>
<style>@css@
tr.ads td{background:var(--accent-soft);font-weight:650}
.key span{display:inline-flex;align-items:center;gap:7px;margin-right:16px;font-size:13px;color:var(--muted)}
.key i{width:22px;height:3px;border-radius:2px;display:inline-block}
.vbig{font-size:18px;line-height:1.5}
</style></head><body>
<header class="top"><div class="wrap"><div class="brand"><span class="dot"></span>ADS // EVALUATION</div>
<div class="case"><span class="pill acc">@tampered@ tampered · @benign@ clean</span></div><div class="spacer"></div>
<button class="iconbtn" data-act="theme" title="Light or dark">@sun@</button><button class="iconbtn" data-act="print" title="Print every tab">@print@</button></div></header>
<nav class="tabs"><div class="wrap"><a class="tab" href="#summary" data-tab="summary">@ico1@Summary <kbd>1</kbd></a>
<a class="tab" href="#checks" data-tab="checks">@ico2@Every check <kbd>2</kbd></a></div></nav>
<main class="wrap">
<section class="panel" id="p-summary"><div class="ph"><div><h2>Did combining the checks help?</h2><div class="sub">Against the ground-truth list of tampered files.</div></div></div>
<div class="grid" style="grid-template-columns:minmax(0,1fr) minmax(0,1fr);align-items:start">
<div class="card"><p class="vbig">@verdict@</p><div class="grid g2" style="margin-top:14px">
<div class="card kpi acc"><div class="v">@adsauc@</div><div class="l">ADS overall (area under curve, of 1.00)</div></div>
<div class="card kpi"><div class="v">@fpr@%</div><div class="l">false-alarm rate compared at</div></div></div></div>
<div class="card">@svg@<div class="key" style="margin-top:8px"><span><i style="background:var(--accent)"></i>ADS (all checks)</span><span><i style="background:var(--accent2)"></i>best single check at @fpr@%</span><span><i style="background:var(--line2)"></i>guessing</span></div>
<div class="note" style="margin-top:8px">Up means catching more tampering; right means more false alarms. Closer to the top-left is better.</div></div></div>
</section>
<section class="panel" id="p-checks"><div class="ph"><div><h2>Every check, side by side</h2><div class="sub">“Caught” is the share of tampering found when tuned to @fpr@% false alarms.</div></div></div>
<div class="card scroll-x"><table class="t"><thead><tr><th>Check</th><th class="num">Overall</th><th>Caught at @fpr@%</th><th class="num">Precision</th></tr></thead><tbody>@rows@</tbody></table></div></section>
</main>
<footer class="foot"><div class="wrap">Artifact Disagreement Scorer · numbers come from the ground-truth list for this test set.</div></footer>
<script>@js@</script></body></html>"""
