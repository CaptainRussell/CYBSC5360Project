# Results

*Block Recovery Toolkit. Created by Captain Scott Russell for CPRE 5360.*

## The course block set (CP3-3-blockset.zip, MD5 017c90727e8dfcb757ae189cacc74c18)

899 blocks of 512 bytes. No answer key is given, so each rebuilt file is judged by its own
internal checks and by opening it.

| File | Blocks | How it was checked | Opens? |
|---|---|---|---|
| PDF | 271 | 31 compressed streams pass zlib's Adler-32 checksum after RC4 decryption; 5 embedded JPEGs end exactly at their last row; the XML metadata decrypts to clean UTF-8 | Yes: 19-page Sprint slide deck, "Defending VoIP Networks from DDoS Attacks" (2004), every page renders |
| Word | 284 | FAT chains, directory, FIB, bin tables and all 48 formatting pages agree; all 135 text blocks are fixed by their paragraph-mark positions | Yes: 18 pages, Swanson et al., "An Evaluation of Speculative Instruction Execution on Simultaneous Multithreaded Processors" |
| JPEG | 344 | decodes to its last row, then the end marker (see below) | (pending) |

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
| PDF | 227+ | 17 | 0 | 27 |
| Word | 0 | 269 | 0 | 15 |
| JPEG | 0 | 1 | 176 | 167 |

Content alone leaves about a quarter of the blocks undecided, mostly encrypted PDF data
and JPEG data that look the same (random-looking bytes). The rebuild settles every one.

## Evaluation on sets with a known answer

(pending: eval/evaluate.py on fresh sets, each a LibreOffice PDF with text, a font and a
picture, a LibreOffice .doc, and a Pillow JPEG landscape.)
