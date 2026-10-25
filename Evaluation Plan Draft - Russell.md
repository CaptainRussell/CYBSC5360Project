---
title: "Cross-Checking Windows Artifacts to Detect Anti-Forensic Tampering"
subtitle: "CPRE 5360 Term Paper: Drafted Evaluation Plan (Draft for November 1)"
author: "Captain Scott Russell"
---

> **Superseded.** This draft is kept for the record. The current text is `paper/paper.md` (built into `paper/CPRE 5360 Term Paper Draft - Russell.pdf`). Since this draft, the project's scope changed: the two-week baseline and the virtual-machine experiment were dropped, and the evaluation is now a proof of function on the two course project images (`tool/proof/README.md`). ADS also reads five records, not six (there is no $LogFile parser), and the parser cross-check was dropped because it was never built.

# IV. Evaluation Plan

## A. Research Questions

The evaluation tests whether the Artifact Disagreement Scorer (ADS) described in Section III detects tampering more reliably than the single-artifact checks it is built from. It is organized around four questions.

* **RQ1. Detection versus single checks.** At a fixed false positive rate, does the combined score D(f) detect more tampered files than any individual rule R1 through R11?
* **RQ2. Benign noise.** How often does each rule, and the combined score, fire on files that were never tampered with on a system in ordinary use? This is the measurement missing from [1], whose experiment used four files on an otherwise unused system.
* **RQ3. Robustness to artifact removal.** Does ADS keep detecting tampering when one or more sources ($J, LNK, Prefetch, or event logs) have been cleared or deleted, and do the system-level indicators S1 through S5 report that the evidence base has been degraded?
* **RQ4. Practicality.** Are the results explainable to an examiner, and does the pipeline run in a reasonable time on a full system image?

## B. Test Platform and Ground Truth

**Platform.** All test systems are Windows 11 24H2 virtual machines on a single NTFS system volume, matching the scope in Section III-A. Each VM is built from the same installation media, with its configuration (installed applications, Prefetch enabled, default event log sizes, USN journal enabled) recorded so the setup can be repeated.

**Ground truth.** The correct answer must be known before ADS is run. Every intentional change made during the experiment is recorded in a ground-truth log kept outside the VM: the file affected, the MFT reference, the action category (Section C), the wall-clock time from the host, and the VM snapshot it belongs to. The host clock, not the guest clock, is the reference, so a scenario that changes the guest's time does not corrupt the ground truth. A file is labeled *tampered* if it appears in this log and *benign* otherwise. Every other file on the image is treated as benign, which is a conservative assumption that may slightly inflate the measured false positive rate.

**Snapshots.** Each scenario is applied to a fresh clone of a common base snapshot, so scenarios do not contaminate one another and each test image differs from the baseline only by the recorded actions plus ordinary activity.

## C. Tampering Scenario Categories

Section III-B deferred the scenario list to this plan. To keep the paper focused on detection, scenarios are described here by category and by the artifact effects they are expected to produce, drawn from the techniques already documented in [1] and the sub-techniques of MITRE ATT&CK T1070, Indicator Removal [4]. The exact tools and versions used will be listed in the final paper for reproducibility, following the practice of [1].

**Table III. Scenario categories**

| ID | Category | Source | Rules and indicators expected to respond |
|---|---|---|---|
| T1 | SIA timestamp alteration through the Windows API | [1], T1070.006 | R1, R5, R7, R8, R9, R10 |
| T2 | SIA and FNA timestamp alteration together | [1], T1070.006 | R1, R5, R8, R9, R11 |
| T3 | Backdating of a newly created file to appear old | [1], [7] | R6, R8, R9, R11 |
| T4 | Event log clearing | [1], T1070.001 | S1, S3, R5 not evaluable |
| T5 | Change journal deletion | [1] | S2, R1 and R8 not evaluable |
| T6 | Removal of LNK and Prefetch files | T1070.004 | S5, R2 to R4, R9, R10 not evaluable |
| T7 | System clock change around file activity | [1] | S4, R5, R11 |
| T8 | Combined: T1 or T2 followed by one or more of T4 to T6 | Composite | All of the above; tests RQ3 |

T1 through T3 alter files and are scored at the file level. T4 through T7 degrade the evidence base and are scored at the system level. T8 represents a more careful adversary who alters files and then removes the records most likely to expose the change; it is the main test of whether combining sources helps when some sources are gone.

Each category is repeated across several target files of different types (documents, images, executables, files in user and system-adjacent folders) so results do not depend on one file type.

## D. Datasets

The evaluation uses four sets of images, kept strictly separate so that tuning never sees test data.

1. **Benign baseline (B).** One VM used normally for a period of about two weeks: web browsing, editing documents, installing and updating software, extracting archives, cloud sync, and routine Windows updates and antivirus scans. No tampering is applied. This image is used to measure each rule's benign firing rate p_r (Section III-F) and is the main source for RQ2.
2. **Calibration set (C).** A small number of clones of the baseline with a subset of scenarios applied. It is used only to set the tolerances τ and the threshold θ, and is never used to report results.
3. **Test set (T).** Separate clones with every scenario category applied, each repeated on several files. All reported detection results come from this set.
4. **External images (E), time permitting.** The forensic images used in this course's projects, which I did not build. They have no tampering ground truth, so they are used only to report how often ADS flags files on unfamiliar data (an upper bound on the false positive rate) and to check that the parsers handle images not produced by my own setup.

Ordinary activity continues on the test clones before and after the recorded actions, so tampered files are mixed with realistic benign noise rather than sitting on an otherwise idle system.

## E. Tools

* **Virtualization and imaging:** a hypervisor with snapshot support; images exported as raw or E01, hashed with SHA-256 at acquisition.
* **Parsers:** Eric Zimmerman's MFTECmd, PECmd, LECmd, and EvtxECmd [9], as specified in Section III-G.
* **Parser cross-check:** python-evtx, LnkParse3, and libscca bindings on a random sample of records from each artifact type. Agreement between the two parsers is reported as a small tool-validation result in its own right.
* **Reference tools for comparison:** the SIA and FNA mismatch check available in commercial tools [10], which corresponds to R6, and the course's examination suites (EnCase or FTK) for a manual spot check of flagged files.
* **ADS itself:** Python 3 with SQLite, as described in Section III-G. The same code produces the single-rule baselines, so ADS and the baselines share identical parsing and ground truth.

## F. Metrics

All metrics are computed per file against the ground-truth labels, except where noted.

* **True positive rate (detection rate):** tampered files flagged divided by all tampered files.
* **False positive rate:** benign files flagged divided by all benign files. Because benign files greatly outnumber tampered ones, the false positive rate is also reported as an absolute count per image, since that is what an examiner experiences.
* **Precision:** flagged files that were actually tampered with, divided by all flagged files.
* **ROC curve and area under the curve:** obtained by sweeping θ for ADS and comparing it with each single rule, which gives a fair comparison without choosing one threshold in advance.
* **Detection at a fixed false positive rate:** the true positive rate of ADS and of each single rule at false positive rates of 1% and 0.1%, which answers RQ1 directly.
* **Coverage:** the fraction of rules that were evaluable for each tampered file, reported alongside D(f) as described in Section III-F.
* **Event-level detection:** for the temporal clustering step, the fraction of scenario instances for which at least one reported cluster overlaps the recorded tampering window.
* **System-level indicator accuracy:** for T4 through T7, whether the corresponding indicator S1 through S5 fired on the tampered image and did not fire on the baseline.
* **Runtime:** wall-clock time for each pipeline stage on a full image.

## G. Experiments

**E1. Single rules versus ADS (RQ1).** Run every rule alone and ADS on the test set. Compare true positive rates at fixed false positive rates and compare ROC curves.

**E2. Benign firing rates (RQ2).** Run every rule on the baseline image and report p_r for each rule, along with the most common benign causes found on inspection (for example, archive extraction or installers setting fixed times). This table is expected to be one of the most useful results, because it quantifies the noise that [1] could not measure.

**E3. Ablation by source (RQ3).** Rerun ADS on the T8 images, and on test images with each source removed in turn, to show how detection falls as sources disappear. Report whether the matching system-level indicator fired in each case.

**E4. Weighting ablation.** Compare three versions of the score: equal weights, the specificity term alone, and the full weight with the tamper-resistance factor from [2]. This tests whether quantifying [2] actually improves detection.

**E5. Optional learned comparison.** If time permits, train a logistic regression on the calibration set's rule outputs and compare it with the weighted sum on the test set, as proposed in Section III-F.

**E6. Explainability check (RQ4).** For a sample of flagged files, confirm that the report alone (the rules fired, the timestamps compared, and their sources) is enough to explain the flag without reopening the raw artifacts.

## H. Success Criteria

The proposal is considered supported if all of the following hold on the test set:

1. ADS achieves a higher true positive rate than the best single rule at the same false positive rate, at both 1% and 0.1%.
2. ADS has a larger area under the ROC curve than any single rule.
3. On the T8 images, ADS still flags the altered files, or the system-level indicators report the removal, in every scenario instance; no scenario produces a clean result with no warning.
4. The full weighting performs at least as well as equal weighting in E4.
5. The parser cross-check agrees on at least 99% of sampled records, or every disagreement is explained.

If ADS does not beat the best single rule, that is reported as a finding: it would mean the recommendation in [1] to combine artifacts does not hold once realistic benign activity is included, and the per-rule false positive rates from E2 would explain why.

## I. Threats to Validity

* **Self-built data.** The test systems and scenarios are built by the same person who designed the rules, which can bias results toward detection. Holding out the test set, fixing θ on calibration data only, and running on external images (E) reduce this risk.
* **Limited benign activity.** Two weeks of use on one VM does not represent every real workload. Benign firing rates are reported as estimates for this platform, not general values.
* **Single platform.** Results apply to Windows 11 24H2 on NTFS. Artifact behavior differs across Windows versions, as [1] notes for its own test platform.
* **Adversary knowledge.** Scenarios assume an adversary working within the running operating system who does not know the ADS rules. Offline disk modification and adversaries who deliberately keep all sources consistent are out of scope and noted as limitations.
* **Small sample.** The number of tampered files is small, so results are reported with counts and, where possible, confidence intervals rather than as precise rates.

## J. Schedule to the Final Paper

The tool is ahead of the original plan. As of this draft, every stage in Section III-G is written: loading the parser output, rules R1 to R11, indicators S1 to S5, scoring, clustering, the report, and the evaluation metrics. It passes its automated tests on small synthetic cases. The time this frees goes to the part that cannot be rushed: a longer period of ordinary use on the baseline machine, and more test runs.

| Dates | Work |
|---|---|
| Oct 26 to Nov 1 | Submit this draft; build the base VM and begin ordinary use |
| Nov 2 to Nov 15 | Two or more weeks of ordinary use on the baseline VM; run the tool on early snapshots and fix anything real data exposes; parser cross-check |
| Nov 16 to Nov 22 | Freeze the baseline; build calibration clones; apply scenarios with the answer-key script; set τ and θ |
| Nov 23 to Nov 29 | Build test clones; run E1 to E6; run on course images |
| Nov 30 to Dec 6 | Write results and discussion; finalize the six-page IEEE paper |
