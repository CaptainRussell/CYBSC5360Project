---
title: "Catching Cover-Ups: Cross-Checking a Drive's Independent Records"
subtitle: "CPRE 5360 Term Paper: Results (Draft for the December 6 paper)"
author: "Captain Scott Russell"
---

# V. Results

This section reports the proof of function described in Section IV. Both projects
were run with tool version `5997b4e` on 2026-10-26, on Windows; the freeze test
passed, so the first-look checks are the ones committed on 2026-10-20, before
Project 2 was examined. Items still to complete are marked *To complete*.

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

**Reproducibility.** The original run (Linux, 2026-10-20) and a re-run on
Windows with version `5997b4e` (2026-10-26) produced identical results: the same
image fingerprint, the same 76 files in the same order with the same scores, and
the same counts.

Sources: `tool/results/26Fall_Project1B/` (`proof.html`, `proof.csv`,
`briefing.html`, `comparison.md`) and `tool/results/26Fall_Project1B_rerun/`.

## B. Project 2: Held-Out Test

**Image.** `26Fall_Project2.img`, one NTFS volume named "Disk" (1,299,558,400
bytes) holding a copied Red Hat Linux file system, examined by hand in FTK. ADS
found 5,607 entries (567 folders, 4,789 files and 251 files inside ZIP archives),
set aside 222 as clutter (221 empty files and one Windows folder-settings file),
and asked its eight questions of the 4,818 files left. 164 had at least one
finding. Answer key: 16 evidence files and 3 decoys.

**Pointing to the evidence (RQ1, RQ3).** ADS listed **7 of the 16** evidence files,
**5 of them in its top 10**. To reach all seven, an examiner reads the top 15
files, 7 of which are not in the answer key. One of the three decoys was listed.

| Evidence found by hand | Question | ADS rank | Score | Check that fired |
|---|---|---|---|---|
| `System Volume Information/tracking.log` (names wendy-pc) | QE | #4 | 49 | F1: written at a different time from the bulk copy |
| `white.zip`, locked (password d0gD0G) | Extra | #6 | 33 | C3 locked; C7 archive with a locked file |
| `home/httpd/icons/small/movie.eml`, signed Wendy | QE | #8 | 28 | C5 the only email among 34 files; C6 never mentioned |
| `home/httpd/html/index.html`, website login | QD | #9 | 28 | C4 password written down |
| `usr/others/mypuppy2.7z`, envelope 4 | QA | #10 | 26 | C1 named .7z but really a RAR archive |
| `bin/gzip`, envelope 1 | QA | #11 | 25 | C5 the only photo among 89 files |
| `places.sqlite`, Firefox history | QB | #15 | 18 | C5 about 25 times bigger than the other databases in its folder |
| *Decoy:* `home/httpd/html/attr.html`, a JPEG named .html | Decoy | #2 | 52 | C1, C5, C6 |

ADS's first file (#1, score 100) is `white.bmp`, the locked file *inside*
`white.zip`. The answer key names the archive, and the matching rule fixed before
the run counts the archive's own rank (#6), so the table above uses #6.

**Files ranked high that are not in the answer key.** #3 and #7 are a deleted
picture in the Recycle Bin (`$RECYCLE.BIN/…/$RZB47AA.jpg`, 35,837 bytes, and its
deletion record `$IZB47AA.jpg`), flagged by F1 because it was written on 5 Oct
2011 between 03:44 and 04:10 UTC, after the bulk copy. My FTK examination had
not looked at the Recycle Bin. Opened in FTK, it is a photo of a running
Dalmatian puppy (439 by 290 pixels), originally `I:\Disk\tmp\rushhour.jpg`,
deleted on 4 Oct 2011 at about 10:44 PM US Central. It is not an envelope; it
matches the case's other dog pictures used as distractions (`bin/error`,
`attr.html`, `change.log`). ADS pointed to a deleted file the hand examination had
missed; on inspection it is a distraction an examiner would still need to rule
out, not case evidence. #5 (`bin/bx`) is a false lead: a program
containing the template text "Password is [$2]". #12 (`etc/nmh/digestcomps`) is a
mailing-list template, which I had also set aside by hand as not a real email.
#13 is a false lead: an IEEE guide PDF that carries an encryption setting, so C3 reports it as locked, but it opens and displays normally in FTK and is not in FTK's Encrypted Files list; the setting only restricts what can be done with it.

**Each check alone against the combination (RQ2).**

| Check alone | Files it flags | Evidence it catches | ADS, same number of files |
|---|---|---|---|
| C1 Disguised file | 2 | 1 | 0 |
| C3 Locked with a password | 3 | 1 | 0 |
| C4 Password written down | 2 | 1 | 0 |
| C5 Stands out from its neighbors | 33 | 3 | 7 |
| C6 Never mentioned | 125 | 1 | 7 |
| C7 Archive with personal files | 1 | 1 | 0 |
| F1 Changed at an unusual time | 3 | 1 | 0 |

As on Project 1, the combination clearly beats the broad checks (C5 alone catches
3 evidence files in 33 flagged; ADS's top 33 hold 7) but loses to the narrow ones
at a budget of one to three files, because ADS's top three are the locked file
inside `white.zip`, a decoy, and the Recycle Bin record, none of which the
matching rule counts as evidence. C2 fired on no file.

**Success criteria (Section IV-D).**

1. *ADS lists at least half of the evidence files:* **not met** (7 of 16, 44%).
2. *ADS's top files hold at least as many evidence files as each single check
   with the same budget:* **not met** (C1, C3, C4, C7 and F1 at budgets of 1 to
   3 files), as on Project 1.
3. *Every top-twenty flag is explained by the report alone:* **met.** Every check
   that fired on the top twenty files has its plain-language sentence.
4. *Every missed evidence file is explained:* **met** (table below).

**Misses.** Every miss is explained below from what each check answered for that
file (`why.csv`, made with `python -m ads why`). Six of the nine sit in folders
with fewer than five files, too few for the two "compare with its neighbors"
checks (C5, C6), which are the ones that found envelope 1 (`bin/gzip`, the only
photo among 89 files). The others hold their evidence inside the file's content
or metadata, which no check reads, or write a password in a form C4 does not
look for.

| Evidence not listed | Why, from what ADS examines |
|---|---|
| `home/httpd/html/more/sunflower.html` (pswd = 'd0gD0G') | C4 looks only for sentences such as "password is …"; "pswd =" has neither a listed word nor "is" |
| `home/ftp/etc/shad` (passwd: k1tt3n@p) | Same: "passwd:" has no "is" |
| `usr/others/mypuppy.gz` holding the locked `mypuppy.zip` | Only ZIP archives are opened; the locked ZIP is inside a gzip file |
| `NIST Hard Disk Write Block Tool specification.doc` | The evidence is the author name in its metadata; no check reads document metadata |
| `lib/security/hello.png`, envelope 2 | A real PNG with the right name and nothing appended (C1, C2 clean). C5 compared it with its 37-file folder and did not find it out of place: the folder holds at least one other PNG, so it was not "the only picture" |
| `lost+found/found/win32/graphicssystems/ps_done.jpeg`, envelope 3 | A real JPEG with the right name (C1 clean); its end marker was not found, so C2 could not check; its folder has only 2 files, too few for C5 and C6 |
| `tmp/.font-unix/fs-1/ini/template.pdf`, envelope 5 | A valid PDF that ends where it should (C1, C2 clean, not locked); the envelope is a page inside it, and no check reads page content; it is alone in its folder, so C5 and C6 could not check. The hidden dot-folder is not one of the eight questions |
| `cookies.sqlite` | A normal browser database of normal size in its 31-file profile folder (C1, C5 clean); the evidence is the cookies inside it, which ADS does not read |
| `lost+found/found/win32/related/test.eml` | A real email with the right name (C1 clean); the evidence (the computer name wendyPC) is inside the message; it is alone in its folder, so C5 and C6 could not check |

Sources: `tool/results/26Fall_Project2/` (`proof.html`, `proof.csv`,
`briefing.html`, `triage.json`).

## C. Windows Date Checks on Project 2

ADS read 5,379 MFT records straight from the image and scored 4,797 files. Only
the MFT-only rules could run (R6, R7, R11); the others cannot be checked on a
drive with no shortcuts, Prefetch or Windows event logs.

| Rule | Files checked | Fired |
|---|---|---|
| R6 visible creation date earlier than the protected (FN) copy | 4,797 | 4,785 |
| R7 date exactly on a whole second | 4,797 | 4,786 |
| R11 much older than neighboring MFT records | 4,797 | 0 |

Because R6 and R7 fire on almost every file, measuring each rule's rate on the
image itself gave them almost no weight (p ≈ 0.997), and no file was flagged.
That is the weighting working as designed for ranking: a check that fires on
every file cannot single any one out. The date report therefore points to no
individual file. (Its proof page lists 15 of the 16 evidence files only because
every file has a near-zero score; none is flagged.)

**What R6 and R7 found: the whole volume's visible dates were set back.** 4,785
files share exactly the same visible created and modified time, 2 Oct 2011
11:57:01.0000000 UTC (06:57:01 US Central, the shared "Created" time FTK showed).
Their protected FN creation dates are all different and all later: 2,689 files on
5 Oct 2011, 2,105 files on 2 Oct 2017, and 3 on 4 Oct 2011. Two independent facts
confirm that the FN dates are the true ones:

* 1,689 Eclipse plug-in files carry their software build date in their folder
  names (2015 and 2016). Their visible created date, 2011, is years before that
  software existed; their FN date (2 Oct 2017) is after the build date in all
  1,689 cases.
* The Firefox history and cookie databases show a visible date of 2011 but an FN
  date of 2 Oct 2017 09:07 UTC, matching the cookie I decoded by hand that dates
  the browser's first use to 1 Oct 2017, 5:37 PM US Central.

So the image was assembled in two batches, six years apart, and every visible date
was then set to one moment. In FTK I saw the shared Created time and read it as
the trace of a bulk copy. R6 on its own (the check commercial tools offer) flags
4,785 files and cannot rank them; ADS correctly declined to rank on it, but its
report did not say that the whole drive's dates disagree. That is a gap in how
system-wide findings are reported, discussed in Section VI.

**Confirmed in FTK.** For `bin/gzip` (MFT record 78), FTK's NTFS properties show
the File Name dates as 5 Oct 2011 03:42:54 UTC, the same second ADS reads, and the
record's last change as 2 Oct 2017 11:57:32 UTC. The folder's own index keeps a
third copy of the file's dates (FTK's "Index Entry" times): created 2 Oct 2011
11:57:01.62 UTC, the visible date's second, and changed 2 Oct 2017 11:57:32.45
UTC. The ".62" in my FTK report was this index copy. So on one file, FTK itself
shows 2011 and 2017 dates that cannot all be true. The two tools agree to the second.
They differ only in the fraction: the file has a single name record (long and
short name combined), whose raw value is 03:42:54.3938891 UTC, which is what ADS
reports, while FTK displays .17. ADS's reader agrees with The Sleuth Kit to the
microsecond on the test images; why FTK shows a different fraction for this field
is unresolved, and it does not affect the finding, which rests on dates years
apart.

Sources: `tool/results/26Fall_Project2_dates/` (`briefing.html`, `scores.csv`,
`outcomes.csv`, `run.json`).

## D. Understandability and Run Time (RQ4)

On both projects every check that fired on the top twenty files carries a
plain-language sentence, with the exact values under it. On a Windows PC (Intel Core i7-7800X, 3.5 GHz), the
first-look report read and checked all 4,818 files of Project 2's 1.3 GB image in
34 seconds, and the date checks read its 5,379 MFT records and scored 4,797 files
in 4.9 seconds. *To complete: my own read of whether each top-twenty sentence
makes sense without the raw records.*

## E. Observations Made After Seeing the Answers (Not Part of the Held-Out Result)

These came from looking at Project 2's results with the answer key in hand. They
suggest improvements, but any check built from them would have to be tested on
new data, not on these two images.

* **True creation order.** Ordered by FN creation time, envelopes 4, 2 and 3 are
  the first three files written on 2 Oct 2017 (positions 2,693 to 2,695 of 4,797,
  right after the 2,692-file 2011 batch), minutes before the Firefox and Eclipse
  content. Two of them were first-look misses. A check on the true creation order
  ("the first files of a later batch") would have pointed to them.
* **System-wide findings.** When a check fires on nearly every file, the report
  should say so as a warning about the whole drive rather than only giving it
  less weight.
* **Narrow misses in the frozen checks.** C4's phrase list misses "pswd =" and
  "passwd:"; only ZIP archives are opened; C1 does not judge files with no
  extension (`bin/gzip` was found through C5 instead).
