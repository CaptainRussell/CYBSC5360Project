# Artifact Disagreement Scorer (ADS)

Working implementation of the tool in Section III of the term paper draft. It reads the CSV output of Eric Zimmerman's MFTECmd, PECmd, LECmd and EvtxECmd, loads it into one SQLite database with every time as a UTC FILETIME, evaluates rules R1 to R11 and indicators S1 to S5, and writes a ranked, explainable report. It uses only the Python 3 standard library.

## First-look report on a drive image (easiest way to use ADS)

You need Python 3 (python.org). Nothing else to install.

* **Windows:** drag the image file onto `Run ADS (Windows).bat`.
* **Mac:** double-click `Run ADS (Mac).command`, then drag the image into the window and press Enter.
* **Any system:** `python3 -m ads IMAGE.img`

The tool reads the image without changing it, shows its progress in four steps, and opens the report in your browser when it is done. The report goes in a folder called "IMAGE report" (choose another with `--out FOLDER`; add `--no-open` to skip opening the browser).

The report folder holds:

* `briefing.html`: the report itself, one self-contained page that opens in any browser. It walks through seven sections (summary, how it works, files to look at first, passwords and locked files, timing, everything found, words and method) with a Next button, arrow keys, animations and a plain-language explanation of every clue. Technical detail for examiners is folded away under each file.
* `leads.csv`: every file with a clue, its score out of 100, its level (Look first, Worth a look, Minor) and what was found, in plain words. Opens in Excel.
* `triage.json`: the same results as data.

The eight questions (C1 to C7 and F1 in `ads/triage.py`) are: disguised file, something hidden at the end, locked with a password, password written down, stands out from its neighbors, never mentioned, archive with personal files, and changed at an unusual time.

The FAT reader (`ads/fat.py`) matched The Sleuth Kit byte for byte on all 4,923 live files of the Project 1B image. The run on that image and its comparison with the EnCase analysis are in `results/26Fall_Project1B/comparison.md`.

## Quick start (NTFS timeline rules)

```
cd "Term Paper/tool"
python3 -m unittest discover -s tests -v          # 24 tests on synthetic fixtures

# 1. On Windows: parse an exported image (see scripts/run_parsers.ps1)
# 2. Anywhere with Python 3:
python3 -m ads ingest    --db case.sqlite --mft mft.csv --usn usn.csv --lnk lnk.csv \
                         --prefetch prefetch.csv --evtx evtx_system.csv evtx_security.csv evtx_application.csv
python3 -m ads calibrate --db baseline.sqlite --out calibration.json     # benign image B -> p_r
python3 -m ads analyze   --db calib01.sqlite --out results/calib01 --calibration calibration.json
python3 -m ads evaluate  --results results/calib01 --truth gt_calib01.csv \
                         --set-theta calibration.json --target-fpr 0.01  # calibration set C -> theta
python3 -m ads analyze   --db test01.sqlite --out results/test01 --calibration calibration.json
python3 -m ads evaluate  --results results/test01 --truth gt_test01.csv  # test set T -> metrics
```

`analyze --weight-mode equal|specificity|full` gives the three variants of experiment E4. `evaluate` always reports every single rule ("R1 only" and so on) beside ADS from the same outcomes, which is experiment E1.

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
