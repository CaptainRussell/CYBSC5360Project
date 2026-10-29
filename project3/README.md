# Block Recovery Toolkit (Course Project 3, Option 2)

*Created by Captain Scott Russell for CPRE 5360.*

A file-system analysis toolkit for file recovery. It takes a pile of shuffled 512-byte
blocks that came from a few files, sorts the blocks into their files, and puts each file
back together in order. It was built for the course block set (899 blocks from one PDF,
one Word document and one JPEG picture) and tested on block sets made fresh with a known
answer.

It uses only the Python 3 standard library. The blocks are only read, never changed.

## Run it

```
py -3 -m blockrecover CP3-3-blockset.zip --out recovered
```

(`python3` on Mac or Linux.) The input is the ZIP itself or the folder of block files.
The output folder holds:

* `recovered.pdf`, `recovered.doc`, `recovered.jpg`: the rebuilt files.
* `report.html`: one offline page with the results. It has four tabs: an overview with each
  file's checks and hashes, a map of every block (point at one to see where it went and why),
  each file position by position, and *How it works* in plain words.
* `block_map.csv`: one row per block: its MD5, the first guess from its own bytes, the file
  and position it was placed at, and the reason.
* `summary.json`: the same as data, with the run log.

## How it works

The order of work matters: the PDF first, then the Word file from what is left, then the
picture from what is left after that. A block's file is the file it has a checked place in.
A quick first guess from each block's own bytes is kept beside it for comparison.

**PDF.** A PDF carries its own map. The first block gives the file's length; the
cross-reference tables give the offset of every object; each object starts with
`N 0 obj`. So most blocks are placed by reading that map. The insides of streams (page
drawings, fonts, pictures) are not on the map. For those, each remaining block is tried as
the next one and the stream is decoded to see whether it still makes sense. The course
file's streams are RC4-encrypted with an empty user password (it may be opened but not
copied), so each candidate is first decrypted with the key bytes for its exact position.
What "makes sense" depends on the stream:

| Stream | Test |
|---|---|
| Page drawings, object lists | PDF syntax, each operator with the right number of operands |
| TrueType fonts | table directory, table checksums, glyph structure, signature records (ASN.1 DER) |
| Colour profiles (ICC) | tag table, tag types, curve shapes, padding |
| Other compressed data | the compressor's habits: a wrong block "spells out" repeats a real compressor would copy |
| JPEG pictures | the picture's rows must join without seams (also a Photoshop thumbnail inside a header) |
| XML metadata | readable UTF-8 text |

At the end of each stream its own check must pass: zlib's Adler-32 checksum, or the
picture's end marker right after its last row.

**Word.** A `.doc` file is a small file system (Compound File). The first block names the
blocks holding the allocation table (FAT), and the FAT lists the next block of every
stream, so the file's whole shape is known. Word's header (FIB) then gives the offset of
each table it keeps; one of them lists every paragraph end. Each text block is placed by
the exact positions of its paragraph marks. Text blocks without a paragraph mark are placed
by how their words join the neighbours (a character model learned from the document's own
blocks). Numbered tables are chained by their numbers, repeating records are predicted from
their phase, and empty areas take the all-zero blocks.

**JPEG.** The block with the JPEG signature comes first and the block with the end-of-image
marker comes last. Each block in between is decoded as the continuation of the picture,
and the new 8x8 squares are compared with the squares already above and to their left
(the "seam" between them). Several partial orders are kept at once (a beam search), and the
order with the smoothest seams over the whole picture wins. Two clean-up passes follow:
runs of blocks that clearly belong together are kept as units, and each block is tried in
other places in case it fits better there ("second thoughts").

A JPEG has no map, and flat areas of a picture fit almost anywhere, so this file is a best
effort: the report marks it *incomplete* and flags the blocks it is least sure of. On the
course picture the sky, birds, hill and near water come out right; the textured water at the
bottom (about the last fifth) is partly scrambled. `--thorough` keeps eight times as many
partial orders (about eight times slower) and often gives a cleaner bottom.

## Browser edition

`BlockRecovery.html` is the same toolkit as one offline web page. Open it in a browser and
drop the ZIP (or all the block files) on it. Nothing is uploaded; the work runs on your
computer. While it works it shows the pile of blocks, each one leaving the pile when it gets
a checked place, and the three files filling in. At the end it offers the rebuilt files, the
block map, the summary and the report (also shown in its *Report* tab). On the course set it
takes about four minutes and gives byte-for-byte the same files as the command line.

The page is built from `web/` with `py -3 web/build.py`. The JavaScript in `web/src/`
mirrors the Python modules one for one, and `tests/test_web.py` runs it under Node to check
that both editions place every block the same way.

## Results

See `RESULTS.md` (course set and evaluation sets).

## Tests

```
py -3 -m unittest discover -s tests
```

The JPEG tests need Pillow, and the browser-edition tests need Node. Put the course block set at `tests/data/CP3-3-blockset.zip`
(it is not in the repository) to run the end-to-end check on it.

To build evaluation sets with a known answer (needs LibreOffice and Pillow, used only to
make the test files) and score the toolkit on them:

```
py -3 eval/make_sets.py --out eval/sets --seeds 1 2 3
py -3 eval/evaluate.py eval/sets/set01 eval/sets/set02 eval/sets/set03 --out eval/results.json
```
