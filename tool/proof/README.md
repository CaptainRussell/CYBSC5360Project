# Proof of function: the two course projects

The paper's evaluation runs ADS on the two forensic images from this course and
compares what it points to with what I found by hand in the course tools. My
own findings are the answer key. There is no lab experiment or baseline period.

| | Project 1 | Project 2 |
|---|---|---|
| Image | `26Fall_Project1B.img` | `26Fall_Project2.img` |
| Drive | FAT16 (an external drive's files) | NTFS volume holding a copied Red Hat Linux file system |
| Examined by hand with | EnCase | FTK |
| Answer key | `project1_answer_key.csv` (9 items) | `project2_answer_key.csv` (19 items) |
| Role | **Development case.** The eight checks were written after I knew its answers, so it is a demonstration. | **Held-out test.** The checks were frozen before Project 2 (see below). |
| Status | Run on 2026-10-20; results and proof page in `../results/26Fall_Project1B/` | To run (steps below) |

## Why Project 2 is a fair test: the checks are frozen

The eight first-look checks (C1 to C7 and F1), their scoring, and the file-type
detection were committed on 2026-10-20 (commit `b38fec5`), before Project 2 was
examined. NTFS support was added later, but only to *read* the drive; it does
not change any check. `tests/test_freeze.py` fails if the check code changes.
If it is ever changed after the Project 2 run, report the new results separately
as post-hoc, never as the held-out result.

Known limits of the frozen checks (design facts, not predictions): C1 only
judges files that have an extension; only ZIP archives are opened (RAR, 7-Zip and
gzip archives are judged from the outside); F1 compares last-written times. ADS
also does not read browser databases or email.

## Running Project 2

You need a computer with Python 3 and a copy of `26Fall_Project2.img`. Nothing
else to install.

### 1. First-look report and the comparison with your findings

1. Double-click `Run ADS (Windows).bat` (or `Run ADS (Mac).command`). A window
   opens in your browser.
2. In **First look at a drive image**, give the path to `26Fall_Project2.img`.
3. In the answer key box, give the path to `proof/project2_answer_key.csv`.
4. Press **Run on this image**. When it finishes, open both links: the report,
   and **the comparison with your findings** (`proof.html`).

Command-line equivalent:

```
python3 -m ads 26Fall_Project2.img --out "results/26Fall_Project2"
python3 -m ads proof --results results/26Fall_Project2 --key proof/project2_answer_key.csv
```

### 2. Windows date checks on the same image

In the window's **Windows drive** card, give the same `26Fall_Project2.img`.
ADS reads the file table (MFT) straight from the image and runs the checks that
need only the MFT (R6, R7, R11). The remaining rules report "cannot check",
because this drive holds a Linux file system with no shortcuts, Prefetch or
Windows event logs. With no clean reference machine, each rule's weight comes
from how often it fires on this image itself (`--self-calibrate`; the window
does this automatically), the same way the first-look checks are weighted.

```
python3 -m ads ingest  --db p2.sqlite --image 26Fall_Project2.img
python3 -m ads analyze --db p2.sqlite --out results/26Fall_Project2_dates --self-calibrate
python3 -m ads proof   --results results/26Fall_Project2_dates --key proof/project2_answer_key.csv --out results/26Fall_Project2_dates
```

No answer key exists for timestamp tampering on this image, so this part shows
that the date rules run on a real NTFS drive and records what they flag; the
proof page shows whether any of those files are ones you found.

Optional, for the change-journal rules (R1, R8, S2): if the image has a change
journal (`$Extend\$UsnJrnl`), export `$MFT` and `$J` with FTK Imager, run
MFTECmd on both (see `../scripts/run_parsers.ps1`), and give that folder to the
Windows drive card instead of the image.

### 3. What to keep for the paper

* `proof.html` and `proof.csv` from step 1 (the numbers for the results section)
* `briefing.html` from steps 1 and 2 (screenshots)
* The tool version: `git rev-parse --short HEAD`, and confirm
  `python3 -m unittest tests.test_freeze` passes on that version
