---
title: "Catching Cover-Ups: Cross-Checking a Drive's Independent Records"
subtitle: "CPRE 5360 Term Paper: Results (Draft for the December 6 paper)"
author: "Captain Scott Russell"
---

# V. Results

This section reports the proof of function described in Section IV. Part A is
complete. Parts B and C are laid out ready to fill in once Project 2 is run
(see `tool/proof/README.md`); no Project 2 numbers have been entered yet.

## A. Project 1: Development Case

**Image.** `26Fall_Project1B.img`, one FAT16 volume ("PARTB") holding an external
drive's files, examined by hand in EnCase. ADS read it in about six seconds,
set aside 3,156 computer-made helper files (mostly Mac `._` files) and 2 empty
files, and asked its eight questions of the 2,246 files left. 76 files had at least one
finding.

**Pointing to the evidence (RQ1).** All seven evidence files I found by hand are
on ADS's list, six in the top ten. To reach all seven, an examiner reads the top
16 files, seven of which are not in the answer key. Both decoys are also listed.

| What I found by hand | Found in EnCase by | ADS rank | Score | Checks that fired |
|---|---|---|---|---|
| Password A, `Constants.java` | Keyword search, then narrowed phrases | #2 | 63 | C4, F1 |
| Koala.jpg with JamesCooper.jpg appended (Q7) | GREP for FF D8 FF, after a TA hint | #3 | 49 | C2, C5, C6 |
| Manual.docx, locked (Q1, Q2) | "Protected" condition | #4 | 47 | C3, F1 |
| Password B, `bin/cref_t1.exe` | Narrowed phrase search | #5 | 46 | C4, F1 |
| ReadMe.txt, really a JPEG (Q5, Q6) | Signature analysis and custom condition | #6 | 37 | C1 |
| Sales.xls in hello_world.zip, locked (Q4) | Find Archives, then reading the email | #8 | 33 | C3 |
| hello_world.zip holding hello.eml (Q3) | Find Archives, sorted by extension | #16 | 27 | C7, F1 |
| *Decoy:* TEMP.GIF, an Office file named .gif | "Protected" condition | #1 | 63 | C1, C3, C5 |
| *Decoy:* Password C, `sys/apt/methods/ssh` | Phrase search | #7 | 35 | C4 |

The clearest difference from the manual examination is Q7. By hand I needed a
TA hint and a byte-by-byte search; check C2 noticed that the photo keeps going
after its end marker and named the hidden file, JamesCooper.jpg, from the RAR
header behind it.

**Each check alone against the combination (RQ2).** No single check caught more
than four of the seven evidence files. The broad checks lost clearly to the
combination: F1 alone flags 12 files and catches 4, while ADS's top 12 hold 6;
C6 alone flags 60 files and catches 1, while ADS's top 60 hold all 7. The two
most precise checks, C2 and C7, each flag one file and catch it, which beats ADS
at a budget of one file because ADS's top file is a decoy.

| Check alone | Files it flags | Evidence it catches | ADS, same number of files |
|---|---|---|---|
| C1 Disguised file | 2 | 1 | 1 |
| C2 Something hidden at the end | 1 | 1 | 0 |
| C3 Locked with a password | 3 | 2 | 2 |
| C4 Password written down | 3 | 2 | 2 |
| C5 Stands out from its neighbors | 2 | 1 | 1 |
| C6 Never mentioned | 60 | 1 | 7 |
| C7 Archive with personal files | 1 | 1 | 0 |
| F1 Changed at an unusual time | 12 | 4 | 6 |

**Timing as a disagreement.** 2,224 of 2,236 files with a date share one write
time (2011-09-06 03:21:58), the trace of a bulk copy. Only twelve were written at
a different time, and four of those are planted evidence. F1 also flags seven
ordinary sample files and one program with no planted content.

**What this does and does not show.** I wrote checks C1 to C7 after knowing this
image's answers, and the report's "look first" cut-offs were set on it, so this
is a demonstration that the method works, not a test of how well. ADS does not
open locked files or answer the case questions; it points to files, and the
examiner still reads them. hello.eml itself is not scored, because no check
applies to a plain email; it surfaces only through its zip.

Sources: `tool/results/26Fall_Project1B/` (`proof.html`, `proof.csv`,
`briefing.html`, `comparison.md`).

## B. Project 2: Held-Out Test

*To complete after the run. The checks were frozen on 2026-10-20, before Project 2
was examined; confirm `python3 -m unittest tests.test_freeze` passes on the
version used, and record that version here.*

**Image.** `26Fall_Project2.img`, one NTFS volume (about 1.3 GB) holding a copied
Red Hat Linux file system, examined by hand in FTK. Answer key: 16 evidence
files (five envelope labels, browser history and cookies, the website login,
four files naming the suspect's real first name, two locked archives and two
written-down passwords) and 3 decoys.

**Pointing to the evidence (RQ1, RQ3).** *From `proof.html`: evidence files
listed (of 16), how many in the top ten, review depth, files above it not in the
key, decoys listed (of 3), and the item-by-item table.*

**Each check alone against the combination (RQ2).** *From the second table in
`proof.html`.*

**Misses.** *For every evidence file not on the list, say why from what ADS
examines (success criterion 4).*

## C. Windows Date Checks on Project 2

*To complete after the run. Report how many files R6, R7 and R11 could check,
what they flagged, and whether any flagged files are in the answer key (from the
date report's `proof.html`). The other rules cannot be checked on this image,
which holds no shortcuts, Prefetch or Windows event logs.*

## D. Understandability and Run Time (RQ4)

*For each project: whether every top-twenty flag is explained by the report
alone, and the run time.*
