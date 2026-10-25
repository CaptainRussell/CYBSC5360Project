# ADS vs. my Project 1 analysis (26Fall_Project1B.img)

Run: `python3 -m ads /mnt/project-files/26Fall_Project1B.img --out results/26Fall_Project1B` (about 6 seconds, read-only). The briefing shows each D(f) as a score out of 100 (D = 0.63 is 63). Full output is in `briefing.html`, `leads.csv` and `triage.json` in this folder.

## The image is FAT16, so the paper's rules R1 to R11 could not run

The image is one FAT16 volume ("PARTB", formatted by macOS) holding an external drive's files. It contains no $MFT, $UsnJrnl, LNK files, Prefetch or event logs, which are the only inputs rules R1 to R11 and indicators S1 to S5 use. The planted evidence is also content hiding (renamed files, an appended archive, locked documents, written-down passwords), not timestamp tampering.

To make ADS useful as a first stop on this kind of image, I added a second rule family that applies the same idea: several independent disagreement checks, combined into the weighted score D(f). These checks look at what a FAT volume does record:

| Check | Disagreement it looks for |
|---|---|
| C1 | Extension vs. the file's signature bytes |
| C2 | Data continuing after the format's end marker |
| C3 | Encrypted or password-protected file |
| C4 | A password written out in plain words ("the secret is ...") |
| C5 | Only file of its kind in its folder, or 10× larger than its peers |
| C6 | Never named by the documentation that names its neighbours |
| C7 | Archive holding locked or personal files |
| F1 | Last-written time outside the volume's bulk-copy timestamp |

With no benign baseline image, each check's p_r is its firing rate on this image itself, so `w = ln(1/p_r)`.

## Item by item

| Your finding | How you found it in EnCase | ADS rank | D(f) | Checks that fired |
|---|---|---|---|---|
| Password A, `Constants.java` | Keyword search, then narrowed phrases | #2 | 0.63 | C4 (shows `QwF3p2Jir9oRt7b`), F1 |
| Manual.docx (Q1, Q2) | "Protected" condition | #4 | 0.47 | C3, F1 |
| Password B, `bin/cref_t1.exe` | Narrowed phrase search | #5 | 0.46 | C4 (shows `kohaku123` at byte 18,967, same offset as yours), F1 |
| ReadMe.txt, High Times cover (Q5, Q6) | Signature analysis + custom condition | #6 | 0.37 | C1 (JPEG named .txt) |
| Password C, `sys/apt/methods/ssh` (decoy) | Phrase search | #7 | 0.35 | C4 (shows `wannabeamillionaire`) |
| Sales.xls inside hello_world.zip (Q4) | Find Archives, then reading the email | #8 | 0.33 | C3 (Excel FILEPASS record) |
| Koala.jpg + JamesCooper.jpg (Q7) | GREP for FF D8 FF, after a TA hint | #3 | 0.49 | C2 (JPEG ends at 780,831; 29,586 more bytes; RAR holding **JamesCooper.jpg**), C5 (29× its peers), C6 |
| TEMP.GIF (decoy) | "Protected" condition | #1 | 0.63 | C1 (OLE file named .gif), C3, C5 |
| hello_world.zip / hello.eml (Q3) | Find Archives, sorted by extension | #16 | 0.27 | C7 (holds an email and a locked workbook), F1 |

All eight files you identified rank in the top eight, and the zip that holds the email is #16 of 76 files with any finding. Q7 is the clearest difference: you needed a TA hint and a manual hex walk, while C2 names `JamesCooper.jpg` directly from the RAR header behind the koala.

The "Keys & locks" section of the briefing lists the three passwords next to the three locked files, which is the pairing you worked out by trial.

## What ADS adds and where it is weak

* **Timestamp stratum.** 2,224 of 2,236 examined files share one write time (2011-09-06 03:21:58), the trace of a bulk copy. Only 12 files were written at 14:02:00 that day, and four of them are planted evidence (Constants.java, Manual.docx, cref_t1.exe, hello_world.zip). You did not use timestamps, and this is the check closest to the paper's own idea.
* **False positives.** F1 also flags seven stock Biometry sample files and `cref_tdual.exe`, none of which contain anything planted (I checked `cref_tdual.exe` for strings that `cref_t1.exe` lacks and found only normal program text). C6 fires on 60 ordinary SDK files, but with low weight they all score below 0.17.
* **What it cannot do.** It does not open locked files, read the letter, or answer Q2 and Q3. It points to files; the examiner still reads them. hello.eml itself is not scored, because no check applies to a plain email; it surfaces only through its zip.

## Caveats before using this in the paper

* **Not an independent test.** I wrote checks C1 to C7 after reading your answers, and the display tiers (strong at D ≥ 0.30, moderate at D ≥ 0.20) were set on this image. That makes this run a demonstration, not an evaluation. A fair test needs an image nobody tuned on, such as another project image.
* **Validation of the reader.** The pure-Python FAT reader matched The Sleuth Kit (pytsk3) byte for byte on all 4,923 live files. It recovers none of the 468 deleted entries, all macOS temporary files, because their clusters were reused.
* **Scope.** The paper's Section III is about timestamp tampering on NTFS. C1 to F1 appear in the paper only as a short demonstration in Discussion (Section V-A, `Discussion Draft - Russell.md`), labelled as not being an independent test.

One file in `signedapplet.zip` (`guan lab.txt`), which you set aside as accidental lab login details, is not a lead and does not appear in any output.
