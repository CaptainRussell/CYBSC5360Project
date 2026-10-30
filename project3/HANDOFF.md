# Handoff: CPRE 5360 Course Project 3, Option 2 — Block Recovery Toolkit

Repository: `captainrussell/cybsc5360project` (GitHub). Work lives in `project3/`.
Branches: `main` and `claude/bold-lovelace-c69six` are kept identical (the last code
change is commit `4527922`). The owner's local clone is on Windows (`py -3`), at
`C:\Users\Idont\Desktop\Code Projects\5360 Project`.

## 1. The assignment

The input is "File System Analysis Toolkit for File Recovery". The course gives
`CP3-3-blockset.zip` (MD5 `017c90727e8dfcb757ae189cacc74c18`): 899 shuffled 512-byte
blocks from one PDF, one Word `.doc` and one JPEG, with no unallocated blocks and no
pointers.

- **Required:** classify the blocks into the three files.
- **+3 bonus:** order each file's blocks and rebuild the files.
- **Also expected:** design, evaluation and validation, with attention to scientific
  and legal (forensic) requirements.

The owner chose to rebuild all three files, add an offline browser page, and write up
the methodology, forensic principles, limitations and enhancements.

## 2. Status: done and verified

| File | Blocks | Result |
|---|---|---|
| PDF | 271 | Rebuilt exactly. All 31 compressed streams pass Adler-32 after RC4 decryption, and all 5 embedded JPEGs end correctly. Opens as a 19-page Sprint deck, "Defending VoIP Networks from DDoS Attacks". |
| Word | 284 | Rebuilt exactly. FAT, directory, FIB, bin tables and 48 FKPs agree. Opens as the 18-page Swanson et al. paper on SMT speculative execution. |
| JPEG | 344 | Best effort, marked *incomplete*. 1000×737 painting: about the top 80% is right, and the textured water at the bottom is partly scrambled. |

- **Sorting:** 271 + 284 + 344 = 899, every block in a set.
- **Content-only first guess:** 689/899 right, 209 unsure, 1 wrong.
- **Output hashes, identical in both editions:**
  - `recovered.pdf` bb0ff50104a4f889bcad40be1e89e7a8
  - `recovered.doc` d7ec40513e13e0a6489af1cced75f596
  - `recovered.jpg` 130963219541822dd65253a83c0a3a3c
- **Run time:** the CLI takes about 16 minutes (PDF ~200 s, Word <1 s, JPEG ~780 s). The browser edition takes about 220 s in Chromium.

**Evaluation on generated known-answer sets** (`eval/results.json`):

| Set | Sorted right | PDF in place | Word in place | JPEG in place | Identical files |
|---|---|---|---|---|---|
| set01 (204) | 90% | 52/62 ✓ | 51/62 | 3/80 | none |
| set02 (209) | 94% | 50/62 ✓ | 55/55 ✓ | 4/92 ✓ | Word |
| set03 (173) | 100% | 64/64 ✓ | 61/61 ✓ | 48/48 ✓ | all three |
| **All 586** | **94%** (61% first guess) | | | | |

## 3. How to run

```
cd project3
py -3 -m blockrecover CP3-3-blockset.zip --out recovered      # add --thorough for a wider JPEG search (~8x slower)
py -3 web/build.py                                              # rebuilds BlockRecovery.html (single offline file)
py -3 -m unittest discover -s tests                             # course-set tests need tests/data/CP3-3-blockset.zip; Node needed for test_web
py -3 eval/make_sets.py --out eval/sets --seeds 1 2 3           # needs LibreOffice + Pillow
py -3 eval/evaluate.py eval/sets/set01 eval/sets/set02 eval/sets/set03 --out eval/results.json
```

- **Outputs:** `recovered.pdf/.doc/.jpg`, `block_map.csv`, `summary.json` and `report.html`.
- **`block_map.csv`** has one row per block: its MD5, the first guess with its reason, the file, the position, the offset, and how it was placed.
- **`report.html`** is a plain-language page with four tabs (Overview, Block map, Files, How it works). The Overview shows the input ZIP's MD5 and SHA-256, and notes when they match the published course value.
- **The CLI** uses the Python standard library only. Pillow is used only in tests and set generation.

## 4. Architecture (`project3/`)

The core principle: **a block's file is the file in which it has a checked place.** The
files are rebuilt PDF first, then Word from the blocks left over, then the JPEG from what
remains. The content-only first guess is recorded but never decides anything.

`blockrecover/` (Python), with matching modules in `web/src/` (JavaScript):

| Module | Role |
|---|---|
| `blocks.py` | Loads a folder or ZIP into Block(name, data, index), sorted by name. |
| `features.py`, `classify.py` | Entropy, text share, `jpeg_scan_like`, `random_like` (≥7.35), `compressed_like` (≥6.5); first guess. |
| `layout.py` | Layout: positions → block, plus a per-position "how" string. `PlaceError` is the base error. |
| `pdfcrypt.py` | MD5, RC4 and the Standard security handler (R3, 128-bit, empty user password, per-object key). |
| `pdflex.py` | PDF lexer, plus `object_ok` for dictionaries cut by a block boundary. |
| `inflate.py` | Its own raw-DEFLATE inflater: as strict as zlib, resumable, copyable, verifies Adler-32. Fuzzed against zlib. |
| `binfmt.py` | Format checkers: TrueType (directory, checksums, glyf/loca/cvt, DSIG DER) and ICC profiles. |
| `pdf.py` | Anchors blocks from the PDF's own map: header, /L or startxref, xref tables (20-byte lines), object offsets, stream ends. |
| `streams.py` | Orders the inside of each stream by beam search (`_search`, TIE_LIMIT 300; beams 6/40/300). Kinds: FlateText (operator-arity grammar), FlateBinary (slips plus binfmt checkers), PlainText (strict UTF-8), JPEGStream (header segments, Photoshop 8BIM and thumbnail, restart markers, edge-seam "junction" cost). Each stream closes with Adler-32 or the JPEG end. |
| `word.py` | CFB: header, FAT, directory (with a stale-copy guard), mini FAT and stream, FIB, bin tables and FKPs. Text placed by paragraph-mark positions, `text_gaps` by a Witten-Bell order-6 character model, ascending PLCs, repeating records, zero regions, `leftovers` (permutations of up to 8 positions; font-table record chaining check). |
| `jpeg.py` | Baseline JPEG decoder (resumable at any byte) and edge-pixel basis; `junction()` seam cost. |
| `jpegfile.py` | The standalone JPEG: lenient beam search (cost = pixel-weighted mean seam + 50 per block after the last row), consolidate runs, then LDS "second thoughts". BEAMS=(8,24), THOROUGH=(64,). If no order fits, it keeps the best partial order and marks every block *not confirmed*. |
| `recover.py` | Pipeline `run(path, progress, stages, thorough)`, `write()` and `fingerprint()` (input hashes). |
| `report.py`, `theme.py` | Single-file HTML report, in the same theme as the term project. |

Other files:

- **`web/`:** `app.html` and `app.js` (drag and drop, a Web Worker running the embedded engine, a live view of the pile and the file tracks, downloads, the report in an iframe). `build.py` writes `src/tables.js` (JPEG EDGE basis and PLOGP512, generated from Python) and inlines everything into `project3/BlockRecovery.html`.
- **JS parity rules (keep these):**
  - Python-exact `round` (BigInt).
  - Strict UTF-8 error semantics.
  - Explicit bytes whitespace.
  - Exact Number arithmetic in the JPEG bit buffer.
  - Entropy summed in a plain loop.
  - Stable sorts, so tie order matches Python.
- **Rule:** any change to a Python module must be mirrored in its JS twin, and `tests/test_web.py` must pass.
- **`tests/`:** `test_blockrecover.py` (RC4 vectors, inflate vs zlib, slips, grammar, DER, classify, JPEG decode and reorder, the APPn-after-SOF rule, the missing-block fallback, the course set's PDF and Word, ~3 min). `test_web.py` (Node vs Python on a picture, a missing-block picture, and the course set's PDF and Word, ~7 min).
- **`eval/`:** `make_sets.py` (LibreOffice PDF with text, a font and a picture; LibreOffice .doc; Pillow JPEG; plus an answer key) and `evaluate.py` (sorted right, exact position, right neighbour, identical file, first-guess accuracy).
- **Docs:** `README.md`, `RESULTS.md` (course results and evaluation) and `WRITEUP.md` (the submission write-up: problem, design, evaluation method, results, forensic principles, limitations, enhancements, tie-in to the term project).

## 5. Limitations (all documented in WRITEUP.md §6)

1. **Two pictures in one pile.** An unencrypted PDF with an embedded JPEG, next to a separate JPEG: the separate picture's blocks decode as plausible continuations of the PDF's picture. In set01 and set02, 10 and 6 of them were pulled in, while the PDF still passed its weak "right number of rows" end check. Every sorting error in the evaluation comes from this.
   - Tried and ruled out: mean seam (the true path costs 2.82 against 2.64 wrong) and worst seam (5.72 against 4.06). Neither separates them.
   - The course PDF is encrypted, so the case doesn't arise there.
   - Proposed fix: order the two pictures jointly, or test which picture's quantization and Huffman tables a block was encoded for.
2. **The JPEG ordering is a best effort.** JPEG's differential DC coding lets flat or finely textured blocks fit in many places. The bottom fifth of the course picture is wrong; `--thorough` helps but isn't exact.
3. **Word text without paragraph marks** is ordered by the character model and can swap similar prose (11/62 positions in set01). Every text block in the course document has paragraph marks.
4. **Formats.** Only PDF, Word .doc (CFB) and baseline JPEG. No progressive JPEG, TIFF, .docx, PNG or TXT.
5. **Assumes complete files.** A missing block leaves a stream unconfirmed and its position as zeros, shown as "empty" in the report.
6. **Speed.** Every free block is tried at every unknown position, so this would not scale to thousands of blocks without indexing the candidates.
7. **Depends on surviving maps.** The PDF xref tables and the Word FAT/FIB carry most of the placement.

## 6. Open items / next steps

- **Submission format.** The write-up is Markdown, so it may need converting to .docx, PDF or IEEE layout, with screenshots of the browser page and report. The owner hasn't said which.
- **Windows check.** Not yet run on the owner's Windows machine, or in Edge or Firefox (only headless Chromium so far).
- **README:** add the CLI time (~16 min) next to the browser time.
- **Re-run the slow tests** (`TestCourseSet` and `test_web`'s course test) as a formality after the last two commits. The equivalent full runs were already identical.
- **Optional:** the two-picture fix (Limitation 1), and character-formatting runs as extra anchors for Word text (Limitation 3).

## 7. Constraints and conventions (please keep)

- **Never modify the frozen term-project checks:** `tool/ads/triage.py` C1–F1 and `tool/ads/sniff.py`, guarded by `tool/tests/test_freeze.py` (run it from `tool/`).
- **Never commit** disk images, the course block set (`project3/tests/data/`, gitignored), or the generated sets (`project3/eval/sets/`).
- **User-facing text** must be plain language for a non-technical reader, with tool names spelled out (for example "Artifact Disagreement Scorer"), and credit "Created by Captain Scott Russell for CPRE 5360".
- **Stated confidence:** report a file as *checked* only when its own format confirms it; label guesses "not confirmed"; never fill a position with a plausible block.
- **Git:** push to `claude/bold-lovelace-c69six` and fast-forward `main`.
- **Debugging tip:** when killing processes, don't use `pkill -f` or `pgrep -f` patterns that also match your own shell's command line. Kill by PID.
