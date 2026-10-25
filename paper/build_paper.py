"""Build the IEEE-style two-column paper from paper.md.

    python3 build_paper.py            # writes the .docx, and the .pdf too if LibreOffice is installed

paper.md is the only source to edit. It is ordinary Markdown with a few additions:
  front matter (title, author, affiliation, note), ::: abstract / keywords / references blocks,
  "Table: caption" before a table, ![caption](figure.png){width=column}, and $$ ... $$ for one
  displayed equation. x_y in body text prints y as a subscript (w_r, p_r).
"""

import os
import re
import shutil
import subprocess
import sys

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "paper.md")
OUT = os.path.join(HERE, "CPRE 5360 Term Paper Draft - Russell.docx")
FONT = "Times New Roman"
COLUMN_WIDTH = Inches(3.45)
ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"]
INLINE = re.compile(r"(\*\*.+?\*\*|\*.+?\*|(?<![A-Za-z0-9$])[A-Za-z]_[a-z](?![A-Za-z]))")


def add_runs(p, text, size=10, bold=False, italic=False):
    """Add text with **bold**, *italic* and x_y subscripts."""
    for part in INLINE.split(text):
        if not part:
            continue
        b, i, sub = bold, italic, None
        if part.startswith("**") and part.endswith("**"):
            part, b = part[2:-2], True
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            part, i = part[1:-1], True
        elif re.fullmatch(r"[A-Za-z]_[a-z]", part):
            part, sub = part[0], part[2]
        for t, is_sub in ((part, False), (sub, True)):
            if not t:
                continue
            r = p.add_run(t)
            r.font.size, r.font.bold, r.font.italic = Pt(size), b, i
            r.font.subscript = is_sub
            r.font.name = FONT


def para(doc, text="", size=10, align=WD_ALIGN_PARAGRAPH.JUSTIFY, indent=True, before=0, after=0,
         bold=False, italic=False):
    p = doc.add_paragraph()
    f = p.paragraph_format
    f.alignment, f.space_before, f.space_after, f.line_spacing = align, Pt(before), Pt(after), 1.0
    if indent:
        f.first_line_indent = Inches(0.14)
    if (bold or italic or align == WD_ALIGN_PARAGRAPH.CENTER) and size <= 10 and text:
        f.keep_with_next = True
    add_runs(p, text, size, bold, italic)
    return p


def hanging(doc, label, text, size=10, indent=0.18):
    p = para(doc, "", size=size, indent=False)
    p.paragraph_format.left_indent = Inches(indent)
    p.paragraph_format.first_line_indent = Inches(-indent)
    add_runs(p, label + "\t" + text, size)
    p.paragraph_format.tab_stops.add_tab_stop(Inches(indent))
    return p


def set_columns(section, n):
    cols = section._sectPr.find(qn("w:cols"))
    if cols is None:
        cols = OxmlElement("w:cols")
        section._sectPr.append(cols)
    cols.set(qn("w:num"), str(n))
    cols.set(qn("w:space"), "288")


def border_table(table):
    """IEEE tables: rules above and below the table and under the header row only."""
    tbl = table._tbl
    pr = tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "bottom"):
        e = OxmlElement("w:" + edge)
        e.set(qn("w:val"), "single"), e.set(qn("w:sz"), "8"), e.set(qn("w:color"), "000000")
        borders.append(e)
    pr.append(borders)
    for cell in table.rows[0].cells:
        tcpr = cell._tc.get_or_add_tcPr()
        b = OxmlElement("w:tcBorders")
        e = OxmlElement("w:bottom")
        e.set(qn("w:val"), "single"), e.set(qn("w:sz"), "4"), e.set(qn("w:color"), "000000")
        b.append(e)
        tcpr.append(b)


def front_matter(lines):
    meta, i = {}, 0
    if lines and lines[0].strip() == "---":
        i = 1
        while lines[i].strip() != "---":
            k, _, v = lines[i].partition(":")
            meta[k.strip()] = v.strip()
            i += 1
        i += 1
    return meta, lines[i:]


def build():
    with open(SRC, encoding="utf-8") as fh:
        meta, lines = front_matter(fh.read().splitlines())

    doc = Document()
    st = doc.styles["Normal"]
    st.font.name, st.font.size = FONT, Pt(10)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Inches(8.5), Inches(11)
    sec.top_margin, sec.bottom_margin = Inches(0.75), Inches(1.0)
    sec.left_margin = sec.right_margin = Inches(0.625)

    # Title block, one column.
    para(doc, meta.get("title", ""), size=22, align=WD_ALIGN_PARAGRAPH.CENTER, indent=False, after=8)
    para(doc, meta.get("author", ""), size=11, align=WD_ALIGN_PARAGRAPH.CENTER, indent=False)
    para(doc, meta.get("affiliation", ""), size=9, align=WD_ALIGN_PARAGRAPH.CENTER, indent=False, italic=True)
    if meta.get("note"):
        para(doc, meta["note"], size=9, align=WD_ALIGN_PARAGRAPH.CENTER, indent=False, italic=True, after=10)
    set_columns(doc.add_section(WD_SECTION.CONTINUOUS), 2)

    sec_no, sub_no, tab_no, fig_no = 0, 0, 0, 0
    block, buf, table_caption = None, [], None
    i = 0

    def flush():
        nonlocal buf
        if buf:
            text = " ".join(s.strip() for s in buf)
            if block == "abstract":
                p = para(doc, "", size=9, indent=False, after=4)
                add_runs(p, "Abstract—", 9, bold=True, italic=True)
                add_runs(p, text, 9, bold=True)
            elif block == "keywords":
                p = para(doc, "", size=9, indent=False, after=6)
                add_runs(p, "Index Terms—", 9, bold=True, italic=True)
                add_runs(p, text, 9, bold=True)
            elif block == "references":
                m = re.match(r"(\[\d+\])\s*(.*)", text)
                hanging(doc, m.group(1), m.group(2), size=8, indent=0.3)
            else:
                para(doc, text)
        buf = []

    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if s.startswith(":::"):
            flush()
            name = s[3:].strip()
            block = name or None
        elif not s:
            flush()
        elif s.startswith("# "):
            flush()
            title = s[2:]
            if title == "References":
                para(doc, "References".upper(), size=10, align=WD_ALIGN_PARAGRAPH.CENTER, indent=False,
                     before=8, after=4)
            else:
                sec_no += 1
                sub_no = 0
                para(doc, "%s. %s" % (ROMAN[sec_no - 1], title.upper()), size=10,
                     align=WD_ALIGN_PARAGRAPH.CENTER, indent=False, before=8, after=4)
        elif s.startswith("## "):
            flush()
            sub_no += 1
            para(doc, "%s. %s" % (chr(64 + sub_no), s[3:]), size=10, align=WD_ALIGN_PARAGRAPH.LEFT,
                 indent=False, before=4, after=2, italic=True)
        elif s.startswith("Table:"):
            flush()
            table_caption = s[6:].strip()
        elif s.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-+:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            tab_no += 1
            para(doc, "TABLE %s" % ROMAN[tab_no - 1], size=8, align=WD_ALIGN_PARAGRAPH.CENTER,
                 indent=False, before=6)
            para(doc, (table_caption or "").upper(), size=8, align=WD_ALIGN_PARAGRAPH.CENTER, indent=False,
                 after=3)
            t = doc.add_table(rows=len(rows), cols=len(rows[0]))
            t.alignment = WD_TABLE_ALIGNMENT.CENTER
            t.autofit = False
            layout = OxmlElement("w:tblLayout")
            layout.set(qn("w:type"), "fixed")
            t._tbl.tblPr.append(layout)
            # Column widths in proportion to the longest text in each column, to fill one column.
            longest = [max(min(len(r[c]), 48) for r in rows) + 4 for c in range(len(rows[0]))]
            widths = [int(COLUMN_WIDTH * n / sum(longest)) for n in longest]
            for col, w in zip(t._tbl.tblGrid.findall(qn("w:gridCol")), widths):
                col.set(qn("w:w"), str(int(w / 635)))     # EMU -> twentieths of a point
            for r, cells in enumerate(rows):
                for c, text in enumerate(cells):
                    cell = t.cell(r, c)
                    cell.width = widths[c]
                    f = cell.paragraphs[0].paragraph_format
                    f.space_after, f.keep_with_next = Pt(0), r < len(rows) - 1
                    add_runs(cell.paragraphs[0], text, 8, bold=(r == 0))
            border_table(t)
            para(doc, "", size=4, indent=False)
            table_caption = None
            continue
        elif s.startswith("!["):
            flush()
            m = re.match(r"!\[(.*)\]\((.*?)\)", s)
            fig_no += 1
            p = para(doc, "", align=WD_ALIGN_PARAGRAPH.CENTER, indent=False, before=6)
            w = re.search(r"width=([\d.]+)in", s)
            p.add_run().add_picture(os.path.join(HERE, m.group(2)), width=Inches(float(w.group(1))) if w else COLUMN_WIDTH)
            cap = para(doc, "", size=8, indent=False, after=6)
            add_runs(cap, "Fig. %d. " % fig_no, 8)
            add_runs(cap, m.group(1), 8)
        elif s.startswith("$$"):
            flush()
            p = para(doc, "", align=WD_ALIGN_PARAGRAPH.CENTER, indent=False, before=4, after=4)
            add_runs(p, "D(f) = Σ", 10, italic=False)
            add_runs(p, "r", 8)
            add_runs(p, " w_r v_r(f)  /  Σ", 10)
            add_runs(p, "r", 8)
            add_runs(p, " w_r", 10)
            add_runs(p, "\t\t(1)", 10)
        elif re.match(r"\d+\. ", s) or s.startswith("- "):
            flush()
            label = s.split(" ", 1)[0] if s[0].isdigit() else "•"
            text = [s.split(" ", 1)[1]]
            while i + 1 < len(lines) and lines[i + 1].startswith("   ") and lines[i + 1].strip():
                i += 1
                text.append(lines[i].strip())
            hanging(doc, label, " ".join(text))
        else:
            buf.append(line)
        i += 1
    flush()
    doc.save(OUT)
    return OUT


def to_pdf(docx):
    office = shutil.which("soffice") or shutil.which("libreoffice")
    if not office:
        return None
    subprocess.run([office, "--headless", "--convert-to", "pdf", "--outdir", HERE, docx],
                   check=True, capture_output=True)
    return os.path.splitext(docx)[0] + ".pdf"


if __name__ == "__main__":
    out = build()
    print("wrote", out)
    pdf = to_pdf(out) if "--no-pdf" not in sys.argv else None
    if pdf:
        print("wrote", pdf)
