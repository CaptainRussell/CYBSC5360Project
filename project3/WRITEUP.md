# Course Project 3, Option 2: File System Analysis Toolkit for File Recovery

*Block Recovery Toolkit. Created by Captain Scott Russell for CPRE 5360.*

## 1. The problem

An investigator has a pile of disk sectors from an image, but the index that said which
sectors belong to which file, and in what order, is gone (a wiped inode or FAT, or blocks
carved from unallocated space). The blocks hold no pointers. The task is to:

1. sort the blocks into one set per file (required), and
2. put each set back in order and rebuild the files (bonus).

The course set, `CP3-3-blockset.zip` (MD5 `017c90727e8dfcb757ae189cacc74c18`; the toolkit
records the input's hashes and confirms the match), holds 899 blocks of 512 bytes from one PDF, one Word document and one JPEG
picture, with no unallocated blocks.

## 2. Design

### 2.1 The main idea: a block's file is the file it has a checked place in

Many classifiers sort blocks by statistics alone (byte entropy, character frequencies). That
works for text, but not here: the course PDF is encrypted, so its compressed streams look
exactly like JPEG picture data. Both are random-looking bytes. On the course set a
statistics-only first guess leaves 209 of 899 blocks (23%) undecided, nearly all of them
encrypted PDF data or picture data.

So the toolkit sorts and rebuilds in one step. A block belongs to a file when it has been
put at a position in that file and the file's own structure accepts it there. Each format's
own rules do the work:

* a **PDF** carries a map of itself (cross-reference tables giving every object's offset);
* a **Word** `.doc` is a small file system (Compound File) with its own allocation table;
* a **JPEG** has no map, but its picture data must decode, and neighbouring rows must join
  without seams.

The files are rebuilt in order of how much structure they carry: the PDF first, then the
Word file from the blocks left over, then the picture from what is left after that. Each
step makes the next one's pool smaller. A quick first guess from each block's bytes alone
(signatures, keywords, readable text, entropy, the JPEG rule that every FF byte is followed
by 00) is kept beside the final answer. It is not used to decide anything, but it shows how
much the rebuild adds.

### 2.2 PDF

1. **Anchor blocks from the file's own map.** The block starting `%PDF-` is first. Its
   linearization dictionary (or, in other files, the `startxref` at the end) gives the
   file length and the cross-reference tables. Each table line is 20 bytes, so a block of
   table lines is placed by its line numbers. Each object's offset gives its block
   (offset ÷ 512), and the block must show `N 0 obj` at the right byte. An object
   dictionary cut by a block boundary is completed and parsed to check the join.
2. **Decrypt.** The course PDF uses the Standard security handler (revision 3, 128-bit
   RC4) with an empty user password: anyone may open it, but copying is restricted. The
   toolkit derives the key as the PDF standard (ISO 32000) describes, and checks it
   against the file's own password check value. Each object has its own key, and each
   byte position in a stream has its own keystream byte, so a candidate block is decrypted
   with the keystream for the exact position it is being tried at.
3. **Order the inside of each stream.** Streams (page drawings, fonts, colour profiles,
   pictures) are not on the map. Their first and last blocks are known (the object header
   and the `endstream` keyword). The blocks between are found by a beam search: every
   free block is tried as the next one, the stream is decoded so far, and the few best
   partial orders are kept. "Best" depends on the stream:

   | Stream | What a right block must satisfy |
   |---|---|
   | Page drawings, object lists | inflates; PDF syntax with each operator taking its right number of operands |
   | TrueType fonts | inflates; table directory, table checksums, glyph outlines, the DER-encoded signature |
   | ICC colour profiles | inflates; tag table, tag types, curve shapes |
   | Other compressed data | inflates without "slips": a wrong block makes the decompressor spell out text a real compressor would have copied |
   | JPEG pictures | the header segments chain; picture rows join without seams |
   | XML metadata | strict UTF-8 text |

4. **Close every stream with its own check.** A compressed stream must end with zlib's
   Adler-32 checksum matching everything inflated. A picture must decode its last row and
   then show its end marker. A wrong order cannot pass these by chance.

The toolkit has its own decompressor (a strict re-implementation of zlib's), because it must
stop at any block boundary, copy its state, and try every candidate from the same point.

### 2.3 Word (Compound File)

1. The block starting `D0 CF 11 E0` is the header. It names the FAT's blocks, so FAT blocks
   are recognised by their entries. The FAT then gives every stream's chain of sectors:
   the shape of the whole file is known before any content is placed.
2. The directory block is found by its entry structure and must agree with the FAT. The
   mini FAT and mini stream follow.
3. Word's own header (the FIB) gives the offset of every table Word keeps. The bin tables
   give the page number of every formatting page (FKP), which places those blocks exactly.
4. **Text.** One of Word's tables lists every paragraph end in the text. Each text block is
   placed where its paragraph marks fall at exactly those character positions. Text blocks
   without a paragraph mark are placed by how their words join the neighbours (a character
   model trained on the document's own blocks).
5. Ascending number tables are chained by their numbers, repeating records by their phase,
   and areas that must be empty take the all-zero blocks. The last few blocks are placed by
   how their bytes join their neighbours, with an exhaustive check of every assignment.

### 2.4 JPEG

1. The block with the JPEG signature is first, and the block with the end-of-image marker
   is last.
2. Every other block is decoded as the continuation of the picture. The toolkit's own
   baseline JPEG decoder can stop at any block boundary and resume. Each new 8×8 square's
   edge pixels are compared with the squares already above and to its left (the "seam").
3. A beam search keeps the partial orders with the smoothest seams over the whole picture.
4. Two clean-up passes: runs of blocks that clearly belong together are kept as units, and
   each unit is tried at other places ("second thoughts").

The picture has no map, and a flat area of a picture fits almost anywhere (JPEG codes each
square's brightness as a difference from the last one, so a plain block reads as plausible
in many places). The picture is therefore a best effort, and the report says so (§5).
If no order reaches the picture's last row at all, the blocks left are still the picture's
set: they are kept in the best partial order found and every one is marked *not
confirmed*.

### 2.5 What is produced

From one command (`py -3 -m blockrecover CP3-3-blockset.zip --out recovered`) or one
offline web page (`BlockRecovery.html`, drag and drop):

* the three rebuilt files;
* `block_map.csv`: for each block, its MD5, the first guess with its reason, the file and
  position it was placed at, and how it was placed;
* `summary.json`: the same with the run log and the hashes of every rebuilt file;
* `report.html`: one plain-language page: an overview, a map of all 899 blocks (point at
  one to see where it went and why), each file position by position, and *How it works*.

The command line uses only the Python 3 standard library. The web page runs the same
method in JavaScript, entirely on the user's computer.

## 3. Evaluation methodology

There is no answer key for the course set, so the evaluation has four parts.

**3.1 Internal validation on the course set.** Each rebuilt file is checked by its own
format: every PDF stream's checksum, every Word table's agreement with the FAT and the
directory, the picture decoding to its last row. Then each file is opened in ordinary
software (a PDF reader, LibreOffice, an image viewer) and read by a person.

**3.2 Sets with a known answer.** `eval/make_sets.py` makes fresh sets the same way the
course set was made: a PDF (LibreOffice, with text, an embedded font and a picture), a Word
`.doc` (LibreOffice), and a JPEG photograph-like picture (Pillow), each cut into 512-byte
blocks, shuffled and renamed, with an answer key kept aside. `eval/evaluate.py` runs the
toolkit and scores:

* **sorted right**: the block was put in the file it came from (the required task);
* **exact position**: ... and at the position it came from (the bonus task);
* **right neighbour**: the block after it is its true successor (fairer for a long run
  that is right but shifted);
* **identical file**: the rebuilt file is byte-for-byte the original;
* the same "sorted right" for the first guess alone, to show what the rebuild adds.

**3.3 Component tests against references.** The decompressor is checked against zlib on
10,000 random pieces; RC4 and MD5 against published test vectors; the JPEG decoder against
Pillow; the font and DER checks on real fonts. These run as unit tests
(`py -3 -m unittest discover -s tests`).

**3.4 Two independent implementations.** The browser edition is a separate implementation
in JavaScript. On the course set it gives byte-for-byte the same three files and places
all 899 blocks identically to the Python edition. `tests/test_web.py` checks this under
Node. Agreement between two implementations does not prove either right, but it rules out
a whole class of mistakes (a stray off-by-one, a language quirk).

## 4. Results

### 4.1 The course set

| File | Blocks | Checks | Opens as |
|---|---|---|---|
| PDF | 271 | all 31 compressed streams pass Adler-32 after decryption; all 5 embedded pictures end at their last row; XML metadata is clean UTF-8 | 19-page slide deck, "Defending VoIP Networks from DDoS Attacks" (Sprint, 2004); every page renders |
| Word | 284 | header, FAT, directory, FIB, bin tables and all 48 formatting pages agree; all 135 text blocks fixed by paragraph-mark positions | 18-page paper, Swanson et al., "An Evaluation of Speculative Instruction Execution on Simultaneous Multithreaded Processors" |
| JPEG | 344 | decodes to its last row, then the end marker | 1000×737 painting of a hill, birds and the sea; about the top 80% is right, and the textured water at the bottom is partly scrambled |

**Sorting (the required task): all 899 blocks are in a set, 271 + 284 + 344.** The PDF and
Word sets are confirmed by their files' own checks, and each opens and reads correctly. The
JPEG set is the 344 blocks left, which all decode as picture data. **Ordering (the bonus):**
the PDF and the Word document are rebuilt completely and pass every check, and the picture
is rebuilt as a best effort.

### 4.2 Sets with a known answer

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

## 5. Forensic principles

The project brief asks for a tool that meets scientific and legal requirements, not only a
working one. These are the ones the toolkit was designed around.

* **Integrity of the evidence.** The blocks are only read, never changed. The input ZIP's
  MD5 and SHA-256 are recorded, and the report says when the MD5 matches the published
  value. Every block's MD5 and every rebuilt file's MD5 and SHA-256 are recorded too, so
  anyone can confirm that the output came from this input.
* **Repeatability.** The method has no randomness; the same input gives the same output
  every time, and two separate implementations (Python and JavaScript) give byte-identical
  files. Another examiner can rerun it and get the same answer.
* **Every conclusion is explained.** Each block's row in the block map says how it was
  placed ("object 12 starts here at byte 307", "paragraph marks at characters 18,433 and
  18,512", "fits its neighbours best"). An examiner can check any one claim by hand, and
  can tell a structural fact from a best guess.
* **Confidence is stated, not implied.** A file is marked *checked* only when its own
  format confirms it (checksums, tables). The picture is marked *incomplete*, and blocks
  placed after the picture's last row are flagged as not confirmed. The report never
  presents a guess as a finding.
* **Nothing is invented.** A position the toolkit cannot fill is left as zeros and shown
  as empty in the report, not filled with a plausible-looking block. The summary gives
  each file's filled positions against its total.
* **Known error rates.** Courts in the United States weigh a technique's known error rate
  (the *Daubert* factors). The known-answer sets in §3.2 measure it, and the method and
  test sets are documented so others can repeat the measurement.
* **Validated against references.** Each low-level part (decompressor, decryption, hashes,
  JPEG decoding) is tested against an established implementation, in the spirit of NIST's
  Computer Forensics Tool Testing programme.
* **Lawful handling of protected content.** The course PDF restricts copying. The toolkit
  uses only the empty user password that the file itself allows anyone to use. It does not
  remove the restriction, and the rebuilt file keeps the original's encryption and
  permissions.

## 6. Limitations

* **Formats.** The toolkit rebuilds PDF, Word `.doc` (Compound File) and baseline JPEG.
  Progressive JPEG, TIFF, Office Open XML (`.docx`, which is a ZIP) and plain text are not
  supported. Plain text has no structure, so only the text model would apply.
* **JPEG ordering is a best effort.** Without a map, flat or finely textured areas can be
  ordered in more than one plausible way. On the course picture the bottom fifth is partly
  wrong. `--thorough` widens the search (about eight times slower) and often helps, but
  cannot guarantee the exact order.
* **Two pictures in one pile.** When an unencrypted PDF holds a picture and a separate JPEG
  is also in the pile, the separate picture's blocks decode as plausible continuations of
  the PDF's picture. In two of the three test sets, 6 to 10 blocks went to the wrong
  picture even though the PDF passed its checks, because a picture's end check (the right
  number of rows) is much weaker than a checksum. Every sorting error in the evaluation
  comes from this case. The course PDF is encrypted, which keeps the two apart.
* **Text without paragraph marks.** Word text blocks that hold no paragraph mark are
  ordered by a language model, which can swap blocks of similar prose (11 of 62 positions
  in one test set). The course document's text blocks all carry paragraph marks.
* **Speed.** The method tries every free block at every unknown position. The course set
  takes about 4 minutes in the browser edition and about 16 from the command line (13 of
  them on the picture); a pile of many thousands of blocks would need the candidate pools
  narrowed first.
* **The files must be complete.** The method assumes every block of each file is present
  (as the course set states). A missing block breaks a stream's checksum, so that stream
  would be reported as unconfirmed rather than rebuilt.
* **Known structure helps a great deal.** The PDF and Word results depend on their maps
  surviving. If the blocks holding a PDF's cross-reference table were missing, every
  object would have to be placed by searching, which is much slower and less certain.

## 7. Enhancements

* **More formats**: `.docx`/`.xlsx` (rebuild the ZIP's deflate streams the way PDF
  streams are rebuilt, with the ZIP's CRC-32 as the end check), PNG (zlib plus per-chunk
  CRC-32), progressive JPEG.
* **Better picture ordering**: score seams on all three colour channels and on the
  frequency content, or use a learned model of natural-image edges; treat the order as a
  shortest-path problem over the whole picture instead of a beam search.
* **Two pictures at once**: order the PDF's picture and the separate JPEG together, so a
  block goes to the picture it fits better rather than to whichever is searched first;
  each picture has its own quantization and Huffman tables, which could also be used to
  test which picture a block was encoded for.
* **Text order**: use Word's character-formatting runs (which give byte positions where
  the formatting changes) as extra anchors for text blocks without paragraph marks.
* **Mixed piles from a real disk**: add unallocated noise and duplicate blocks, and
  several files of the same type, to the known-answer sets, then sort first by
  statistics (to split, say, two Word files) before rebuilding each.
* **Speed**: index the candidate pools (for example by the first bytes a stream may
  continue with) and run the per-stream searches in parallel.
* **Court-ready output**: a signed, time-stamped run log and a one-page examiner summary.

## 8. How it ties into the term project

The term project, the Artifact Disagreement Scorer, compares what a file system's own
records say about a file with what other evidence says, and flags where they disagree. This
toolkit uses the same idea one level down: a file's own internal records (a PDF's
cross-reference table, a Word file's FAT and paragraph table) are the evidence that each
block is in the right place, and a block whose content disagrees with those records is
rejected. Both tools share the report design and the offline browser edition, and both are
built on two principles: keep the evidence unchanged, and explain every finding in plain
language.
