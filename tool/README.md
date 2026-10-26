# Artifact Disagreement Scorer (ADS)

*Created by Captain Scott Russell for CPRE 5360.*

Working implementation of the tool in the term paper. It looks for places where a drive's independent records disagree, weighs those disagreements together, and explains every flag in plain words. It has two parts:

* **First look at a drive image:** eight questions asked of every file (disguised, something hidden at the end, locked, password written down, odd one out, never mentioned, archive of personal files, changed at an unusual time). Works on raw images of **FAT and NTFS** drives.
* **Windows date checks:** rules R1 to R11 and warnings S1 to S5 that compare the dates Windows keeps in different places. They read an NTFS image directly (the MFT-only rules R6, R7, R11) or the CSV output of Eric Zimmerman's MFTECmd, PECmd, LECmd and EvtxECmd (all rules).

It uses only the Python 3 standard library. The image is only read, never changed.

## The easiest way: open the page, drop the image

Double-click **`Artifact Disagreement Scorer.html`** (in this folder). It opens in Chrome, Edge or Firefox and needs nothing else: no Python, no installation, no internet.

1. **Drop a drive image** (`.img`, `.dd`, `.raw`) on the left box, or press *Choose an image*. For Windows record files (the CSVs from `scripts/run_parsers.ps1`), use the right box and select all of them.
2. **Watch it work.** The page reads the boot sector and decodes it field by field, lights up a map of the drive as each file is read, counts each of the eight questions' findings as they come in with a feed of what was found, shows how much each clue weighs, ranks the leads, and fingerprints the whole image (SHA-256). NTFS drives then get the Windows date checks too. *Skip animation* jumps to the report as soon as it is ready.
3. **Read the report.** The same report pages as below, inside the page; *First look* and *Date checks* switch between them.
4. **Save results.** Any single file, or *Everything (.zip)*: the same files, in the same folders, that the command line writes (`briefing.html`, `triage.json`, `leads.csv`; `scores.csv`, `outcomes.csv`, `indicators.json`, `clusters.csv`, `run.json`). They work with `ads proof`, `ads rerender` and `ads compare`.

The image is read on your computer and never uploaded or changed. A 1.3 GB NTFS image with 17,000 files takes about a minute.

**Same answers as the command line.** The page runs a JavaScript port of the Python modules (`web/src/`); the tables it uses (check wording, file-type tables, signatures, settings) are generated from the Python modules when the page is built. `tests/test_webapp.py` runs the browser engine under Node on the test drives, seeded stress drives full of awkward and broken files (ZIPs with bad CRCs, overlapping entries and ZIP64, damaged Office files, every "password is" variant, fuzzed signatures), the synthetic Windows record sets and 60 garbled variants of them, and requires every result to match the Python version field by field. To check a real case yourself, save *Everything (.zip)* from the page, unzip it, and run `python3 -m ads compare "BROWSER FOLDER" "COMMAND-LINE FOLDER"`. One known difference: ZIP members compressed with bzip2 or LZMA (rare) are not opened in the browser; the page says so when it meets one.

After changing anything in `ads/` or `web/`, rebuild the page with `python3 -m ads build-web` (a test fails if the committed page is out of date).

## The point-and-click window (Python)

You need Python 3 (python.org). Nothing else to install. Double-click `Run ADS (Windows).bat` or `Run ADS (Mac).command`, or run:

```
python3 -m ads gui
```

This opens a small control panel in your browser (only your own computer can reach it). It has two choices:

* **Windows drive:** give it an NTFS image, or the folder of record files made by `scripts/run_parsers.ps1`. Press Run and the plain-language date report opens.
* **First look at a drive image:** give it a FAT or NTFS image (`.img`, `.dd`, `.raw`). Optionally give an answer key of your own findings, and a second page shows where the tool ranked each item you found by hand.

## Proof of function: the two course projects (Section IV)

The evaluation runs ADS on the course's Project 1 and Project 2 images and compares it with my own EnCase and FTK findings. Step-by-step instructions, the two answer keys, and why Project 2 is a fair held-out test are in **`proof/README.md`**. The Project 1 run and its proof page are in `results/26Fall_Project1B/`.

```
python3 -m ads proof --results results/26Fall_Project1B --key proof/project1_answer_key.csv
```

## First-look report from the command line

* **Windows:** drag the image file onto `Run ADS (Windows).bat`.
* **Any system:** `python3 -m ads IMAGE.img`

The report goes in a folder called "IMAGE report" (choose another with `--out FOLDER`; add `--no-open` to skip opening the browser). It holds:

* `briefing.html`: the report itself, one self-contained page that opens in any browser, with no internet needed. Seven tabs along the top (keys 1 to 7 switch between them):
  * **Overview:** the headline numbers, the top leads and which questions found something.
  * **Leads:** one row per file, which opens to show why it was flagged and a picture of the evidence. Examples: the first bytes of a disguised file beside what its name claims, or the hidden member of an archive. Search, level and check filters sit above the list.
  * **Drive:** the first sector of the drive as a hex map. Hover a byte or a field to see what it means (drive type, sector size and so on).
  * **Keys & Locks:** passwords found, and the locked files they may open.
  * **Timeline:** when files were last written, grouped into periods.
  * **All findings:** one searchable table.
  * **How it works:** each check explained.

  Technical detail is folded away under each file. A sun/moon button switches between dark and light, and the page prints cleanly.

  Everything links to where its files are: click a number on the Overview (for example "look first") and a highlight travels to the tab it opens, already filtered; a "Back" button returns you. Inside an open lead, Previous/Next step through the list and each check's chip opens its explanation. Keys: `1`-`7` tabs, `j`/`k` next/previous row, `/` search, `?` all shortcuts.
  * **Drive** also draws where the parts of the drive sit (partition table, boot area, file tables, folders, data) with the arithmetic that locates each, and how sectors add up to a cluster.
  * **How it works** explains, for each question, exactly what the tool reads and compares, with a worked example and this drive's numbers.
* `leads.csv`: every file with a clue, its score out of 100, its level and what was found, in plain words. Opens in Excel.
* `triage.json`: the same results as data.

The eight questions are C1 to C7 and F1 in `ads/triage.py`. The FAT reader (`ads/fat.py`) matched The Sleuth Kit byte for byte on all 4,923 live files of the Project 1B image. The NTFS reader (`ads/ntfs.py`) matches The Sleuth Kit on every file of the test image in `tests/fixtures/` (paths, sizes, contents and timestamps) and on 3,605 files of a larger partitioned test image.

## Windows date checks from the command line

Every `analyze` run writes **`briefing.html`**, a single page that explains each flagged file in one plain sentence ("the date shown says 1 Mar 2019, but the change journal records the file being created on 10 Oct 2026"), with the exact values folded away for an examiner. It has tabs for an overview (including any check that fires on nearly every file, which describes the drive rather than singling files out), the flagged files, events, record damage and how the checks work. It also writes `report.md` and the CSVs below.

```
cd "Term Paper/tool"
python3 -m unittest discover -s tests -v          # 59 tests

# Straight from an NTFS image (MFT-only rules R6, R7, R11):
python3 -m ads ingest  --db case.sqlite --image drive.img
# Or from Zimmerman CSVs (all rules; on Windows, see scripts/run_parsers.ps1):
python3 -m ads ingest  --db case.sqlite --mft mft.csv --usn usn.csv --lnk lnk.csv \
                       --prefetch prefetch.csv --evtx evtx_system.csv evtx_security.csv evtx_application.csv
python3 -m ads analyze --db case.sqlite --out results/case
```

To rebuild a saved report page after a design change, without the image, run `python3 -m ads rerender RESULTS_FOLDER` (it reads `triage.json`, or `scores.csv` and the files beside it; nothing is re-checked).

`calibrate`, `evaluate` and `analyze --weight-mode equal|specificity|full` remain for measuring the rules against a ground-truth list of tampered files (they are exercised on the synthetic test cases). `evaluate` reports every single rule ("R1 only" and so on) beside ADS and writes `evaluation.html` with an ROC chart.

## Pipeline map (Section III-G)

| Stage | Code | Output |
|---|---|---|
| Extraction and parsing | `scripts/run_parsers.ps1` | Zimmerman CSVs, `hashes.csv` |
| Normalization | `ads/loaders.py`, `ads/paths.py`, `ads/timeutil.py` | `case.sqlite` (input hashes in table `inputs`) |
| Rule evaluation | `ads/rules.py` (R1-R11), `ads/indicators.py` (S1-S5) | one outcome row per file per rule |
| Scoring and report | `ads/scoring.py`, `ads/report.py` | `scores.csv`, `outcomes.csv`, `indicators.json`, `clusters.csv`, `report.md`, `run.json` |
| Evaluation (Section IV) | `ads/evaluate.py` | `evaluation.csv`: AUC, TPR at 1% and 0.1% FPR, confusion counts |

Every tunable value (tolerances τ, θ, allowlists, tamper scores) is in `ads/config.py` and can be overridden with `--config my.json`.

## Ground truth format

`entry_number,sequence_number,path,category,host_time_utc,snapshot`, one row per tampered file (Section IV-B). A row may give only `path`. Every other scored file is treated as benign.

## How each rule is implemented

| Rule | Implementation | Not evaluable when |
|---|---|---|
| R1 | Violated if SIA-E is more than τ_j (2 s) **earlier** than the latest BasicInfoChange in $J. One-sided by default (`r1_two_sided`), see note 1. | no BasicInfoChange for the file |
| R2 | Most recent LNK to the file; LNK's own SIA-E (from the LNK's MFT record) vs target SIA-E, ±τ_lnk | no LNK, or LNK's MFT record not found |
| R3 | Every LNK's SIA-C ≥ target SIA-C − τ_lnk | no LNK |
| R4 | Most recent LNK's SIA-A ≤ target SIA-A + τ_lnk | no LNK or no access time |
| R5 | SIA-C and SIA-M each inside a user session (System 7001/7002, closed early by 6005/6006/6008/41), ±τ_s (60 s). Times outside the System log's coverage are skipped. | no session events, or both times outside coverage |
| R6 | SIA-C ≥ FNA-C − τ_mft (0) | FNA missing |
| R7 | SIA-C and SIA-M sub-second fields not 0000000 | |
| R8 | First FileCreate in $J within τ_j of SIA-C, unless NTFS tunneling explains it (note 3) | no FileCreate (journal rolled over) |
| R9 | Each LNK's embedded target creation time within τ_lnk of the target's SIA-C | no LNK |
| R10 | A Prefetch run within ±30 s of a BasicInfoChange by an executable that is neither allowlisted nor "normally associated" (file in its FilesLoaded and RunCount ≥ 3) | no $J BasicInfoChange or no Prefetch |
| R11 | SIA-C more than 30 days older than the median SIA-C of the 10 MFT records on each side | fewer than 5 neighbors |

LNK targets join on the MFT reference stored in the link when present, rejecting a reused record whose sequence number differs, and otherwise on the normalized path. Examiner mount prefixes such as `E:\C\Users\...` are resolved by anchoring at `\users\`, `\windows\` and similar folders, or explicitly with `mount_prefix`.

## Indicators

| ID | Fires when | Degrades |
|---|---|---|
| S1 | System 104 or Security 1102 | event logs (R5) |
| S2 | Application 3079, or a $J whose first USN shows it never wrapped yet whose first record is more than a day after installation ($MFT record 0 creation, or `install_time`) | $J (R1, R8, R10) |
| S3 | Gaps in EventRecordId within a channel; optionally a log well under its maximum size whose oldest entry is after installation (needs `evtx_files` sizes in the config, since EvtxECmd's CSV does not carry them) | event logs |
| S4 | Security 4616 or Kernel-General event 1 with a shift above 60 s (routine NTP adjustments are ignored) | every time-comparing rule |
| S5 | A .pf or user .lnk file named in $J that is not among the parsed Prefetch or LNK files | LNK and Prefetch rules |

Each scored file reports `confidence`, the share of its evaluable rules whose sources no fired indicator has degraded, and lists which consistent and violated outcomes rest on degraded sources.

## Scoring

`D(f) = Σ w_r v_r / Σ w_r` over evaluable rules, `w_r = log(1/p_r) · t_r`. p_r comes from `calibrate` with add-half smoothing so rules that never fire on the baseline get a finite weight. Without a calibration file the specificity term is 1. t_r is the resistance of the rule's reference source, `4 − mean(seven factor scores)`, so it runs from 1 (easy to tamper) to 3 (hard). Flagged files whose journal or Prefetch evidence times fall within 300 s of each other are grouped into candidate events with the Prefetch runs and indicators in that window.

## Fixtures

`tests/make_fixtures.py` writes `tests/fixtures/{clean,tampered}` in the exact column layout of the four tools. The clean case has a benign document, a T1 SIA stomp (budget.xlsx), a T3 backdated new file (notes.txt), an archive-extracted photo (benign noise for R7 and R10) and an Office-style save (tunneling). The tampered case adds journal deletion, log clearing, a two-day clock change and deleted Prefetch and LNK files. With equal weights and θ = 0.5, ADS flags exactly the two tampered files in both cases, while R7 alone also flags the photo.

## Notes for the paper

1. **R1 direction.** Rule 1 in [1] says SIA-E "should be similar to" the latest BASIC_INFO_CHANGE. Ordinary data writes move SIA-E forward without a new BASIC_INFO_CHANGE, so a two-sided test would fire on every edited file. The implementation flags only an SIA-E earlier than the record, which is the case [1] observed.
2. **R2 needs the LNK's own MFT record.** LECmd reports a link's created, modified and accessed times but not its SIA-E, so R2 joins the LNK file back to the $MFT by path.
3. **R8 and NTFS tunneling.** Office saves a document by writing a temporary file and renaming it over the original, and tunneling copies the old creation time onto the new record. Without an exception R8 would fire on every saved Office document. The rule treats a name freed by another record within 15 s as an explanation.
4. **$LogFile.** Table I lists $LogFile, but no rule R1 to R11 uses it, so it is not ingested yet.
5. **Tamper-resistance factor.** Only the SIA and FNA scores come from Table 1 of [2]. The $J, LNK, Prefetch and event log scores in `config.py` are provisional estimates using the categories of [2]. [2] also presents the factor scores as separate ratings rather than a sum, so the averaging used here is a design choice the paper should state and justify.
6. **Precision.** "No precision is lost" holds only if PECmd and LECmd are run with `--mp`; their default output rounds to whole seconds.
7. **Not yet built.** The parser cross-check with python-evtx, LnkParse3 and libscca (Section III-G step 2), and the optional logistic regression comparison (E5).
