# Term paper

* `CPRE 5360 Term Paper Draft - Russell.pdf`: the November 1 submission (4 pages, IEEE two-column).
* `CPRE 5360 Term Paper Draft - Russell.docx`: the same paper as an editable Word file.
* `paper.md`: **the one file to edit.** Everything else is built from it.
* `figures/`: the two figures. Each is a small web page (`.html`) turned into a picture (`.png`).

## Rebuilding after an edit

```
python3 build_paper.py                 # needs python-docx (pip install python-docx); LibreOffice for the PDF
node figures/render.js figures/fig1_pipeline.html figures/fig2_disagree.html   # only if a figure changed
```

The PDF is made by LibreOffice, which uses Liberation Serif in place of Times New Roman. The two fonts have identical letter widths, so the page count matches Word.

## Sections for the final paper (December 6)

The final paper adds Results (Section V) and Discussion (Section VI). The Results draft, with Project 1 complete and Project 2 laid out ready to fill in, is `../Results Draft - Russell.md`. How to run Project 2 is in `../tool/proof/README.md`.
