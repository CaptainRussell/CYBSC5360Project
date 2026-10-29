# Results

*Block Recovery Toolkit. Created by Captain Scott Russell for CPRE 5360.*

## The course block set (CP3-3-blockset.zip, MD5 017c90727e8dfcb757ae189cacc74c18)

899 blocks of 512 bytes. No answer key is given, so each rebuilt file is judged by its own
internal checks and by opening it.

| File | Blocks | How it was checked | Opens? |
|---|---|---|---|
| PDF | 271 | 31 compressed streams pass zlib's Adler-32 checksum after RC4 decryption; 5 embedded JPEGs end exactly at their last row; the XML metadata decrypts to clean UTF-8 | Yes: 19-page Sprint slide deck, "Defending VoIP Networks from DDoS Attacks" (2004), every page renders |
| Word | 284 | FAT chains, directory, FIB, bin tables and all 48 formatting pages agree; all 135 text blocks are fixed by their paragraph-mark positions | Yes: 18 pages, Swanson et al., "An Evaluation of Speculative Instruction Execution on Simultaneous Multithreaded Processors" |
| JPEG | 344 | decodes to its last row; one block falls after the last row in the best order found and is flagged *not confirmed* | Yes: a 1000×737 painting of a green hill, two birds and the sea. The sky, birds, hill and near water are right (about the top 80%); the textured deep water at the bottom is partly scrambled |

The three files account for all 899 blocks (271 + 284 + 344), so there were no
unallocated or stray blocks, as the assignment says.

### How each PDF block was placed

* By the PDF's own map (header, both cross-reference tables, object offsets, stream ends): 83.
* Inside streams, by decrypting and decoding each candidate: 188, including:
  * 26 page-drawing and object streams (PDF grammar and operand counts);
  * the 12-block Wingdings font (TrueType tables, checksums and its 5 KB DER signature);
  * the 4-block sRGB colour profile (ICC tag table and curves);
  * five embedded JPEGs (2, 2, 2, 9 and 50 blocks). The 50-block one has restart markers
    and a Photoshop header with its own small JPEG thumbnail, which is decoded and judged
    too.

### How each Word block was placed

| Step | Blocks |
|---|---|
| Header, FAT (3), directory (2), mini FAT, mini stream | 8 |
| Word header (FIB, 3 blocks), bin tables, piece table, stylesheet | ~6 |
| Formatting pages (FKPs) at the page numbers the bin tables give | 48 |
| Text, by paragraph-mark positions | 135 |
| Ascending table of paragraph positions, chained by its numbers; repeating records | 63 |
| Empty areas (all-zero blocks: after the FIB, property-set padding) | 15 |
| Last 7 blocks, by how their bytes join their neighbours | 7 |

## First guess compared with the final answer

Before rebuilding, each block is guessed from its own bytes (signatures, keywords, readable
text, randomness, the JPEG rule that every FF byte is followed by 00):

| Final file | guessed PDF | guessed Word | guessed JPEG | unsure |
|---|---|---|---|---|
| PDF | 244 | 0 | 0 | 27 |
| Word | 0 | 269 | 0 | 15 |
| JPEG | 0 | 1 | 176 | 167 |

Content alone gets 689 of 899 blocks right (77%), leaves 209 undecided (23%) and gets one
wrong (a JPEG block guessed as Word). The undecided ones are mostly encrypted PDF data and
JPEG data, which look the same (random-looking bytes). The rebuild settles every one.

### The picture

A JPEG has no map, so its order is a best effort. Each block is decoded as the
continuation of the picture, and the order with the smoothest joins between neighbouring
8×8 squares wins (a beam search keeping 8 partial orders, then 24 if needed). Two clean-up
passes follow: runs that clearly belong together are kept as units, and each unit is tried
elsewhere. The search with 64 partial orders (`--thorough`, about eight times slower)
gives a visibly cleaner bottom on the course picture, but still not an exact one.

The weak spot is JPEG's brightness coding: each square's brightness is stored as a
difference from the one before, so a run of plain squares (calm water, sky) reads as
plausible in many places. Fine texture at the bottom of the picture is where wrong orders
cost almost as little as the right one.

### Command line and browser edition agree

The browser edition (`BlockRecovery.html`) is a separate implementation in JavaScript. On
the course set it gives the same three files byte for byte (MD5 below) and the same
block map (all 899 rows identical), in about four minutes in Chromium.

| File | MD5 (both editions) |
|---|---|
| recovered.pdf | bb0ff50104a4f889bcad40be1e89e7a8 |
| recovered.doc | d7ec40513e13e0a6489af1cced75f596 |
| recovered.jpg | 130963219541822dd65253a83c0a3a3c |

## Evaluation on sets with a known answer

Each set is made fresh by `eval/make_sets.py`: a LibreOffice PDF with text, an embedded
font and a picture, a LibreOffice `.doc`, and a Pillow JPEG landscape, cut into 512-byte
blocks, shuffled and renamed, with the answer kept aside. Results are in
`eval/results.json`.

| Set | Blocks | First guess right | Sorted right | PDF in place | Word in place | JPEG in place | Identical files | Time |
|---|---|---|---|---|---|---|---|---|
| set01 | 204 | 123 (60%) | 183 (90%) | 52/62 (checked) | 51/62 | 3/80 | none | 702 s |
| set02 | 209 | 114 (55%) | 197 (94%) | 50/62 (checked) | 55/55 (checked) | 4/92 (checked) | Word | 290 s |
| set03 | 173 | 118 (68%) | 173 (100%) | 64/64 (checked) | 61/61 (checked) | 48/48 (checked) | PDF, Word, JPEG | 140 s |
| **All** | 586 | 355 (61%) | 553 (94%) | | | | | |

*Sorted right* is the required task: the block is in the file it came from. *In place* is
the bonus task: the block (or an identical copy of it, such as an all-zero block) is at its
true position. *checked* means the file's own checks passed.

What the three sets show:

* **The structure-driven parts are exact when nothing interferes.** In set03 all three
  files come back byte for byte identical to the originals, and set02's Word file does too.
* **The one systematic failure is two pictures in one pile.** In sets 01 and 02 the PDF
  holds its own (unencrypted) JPEG, and the separate JPEG's data blocks decode as plausible
  continuations of it. 10 and 6 of the separate picture's blocks were taken into the PDF's
  picture, which still decoded to its last row, so the PDF's checks passed. The PDF's own
  blocks were then left for the separate picture, which could not be ordered. Every
  sorting error in the table (21 in set01, 12 in set02) is one of these blocks. The seam
  measures could not tell the two apart: on set02 the true path finished with a higher
  mean seam (2.82 against 2.64) and a higher worst seam (5.72 against 4.06) than the
  wrong one. The course PDF is encrypted, so its stream blocks cannot be confused with
  the separate picture's, and the problem does not arise there.
* **Text without paragraph marks is the weak part of Word.** In set01, 21 of the 42 text
  blocks hold no paragraph mark, so they were ordered by a language model trained on the
  document's own blocks; 11 positions came out wrong. (The course document's text blocks
  all carry paragraph marks.)
* **Content alone is not enough.** The first guess from each block's own bytes gets 61%
  right; rebuilding raises sorting to 94%.

Three fixes came out of this evaluation, each checked against the course set, which came
out unchanged after each one:

1. A compressed font block at 7.13 bits per byte had been filtered out of the candidates
   (the cutoff was 7.35), so no order could close its stream. The cutoff for unencrypted
   compressed streams is now 6.5.
2. Wrong blocks starting with bytes FF E0..EF read as a long application segment after the
   picture's frame header, so the header never seemed to end. Encoders never put one there,
   so this now rules a block out.
3. A mostly-zero Word table block passed the JPEG byte rule by chance and was left out of
   Word's last positions; and an old directory copy swapped places with Word's font table.
   Sparse blocks now pass, and the font table's own record lengths settle its block.

When the picture cannot be ordered at all, its blocks are still kept as the picture's set,
marked *not confirmed*, instead of being left unsorted.
