---
title: "Cross-Checking Windows Artifacts to Detect Anti-Forensic Tampering"
subtitle: "CPRE 5360 Term Paper: Proposed Solution (Draft for November 1)"
author: "Captain Scott Russell"
---

# III. Proposed Solution

## A. Overview and Design Goals

The central idea of this work is that tampering on a Windows system is rarely exposed by one record being wrong. It is exposed because several records, written by different parts of the operating system for different reasons, stop agreeing with each other. Palmbach and Breitinger [1] showed that the change journal ($UsnJrnl:$J), link (LNK) files, Prefetch files, and Windows event logs each carry evidence of timestamp manipulation, and that none of them is reliable on its own. They recommend combining these sources but do not measure whether combining them improves detection. Vanini, Hargreaves, and Breitinger [2] score how resistant a source is to tampering, but their framework rates the source itself rather than whether a particular system shows that tampering occurred.

I propose a tool, referred to here as the Artifact Disagreement Scorer (ADS), to close this gap. ADS parses several independent Windows artifacts from a forensic image, aligns them on common keys (the MFT file reference, the full path, and time), evaluates a set of consistency rules, and combines the rule outcomes into a disagreement score for each file and for the system as a whole. The design has four goals:

1. **Combination over isolation.** No single rule decides the outcome. A file is flagged when the weight of independent disagreement crosses a threshold, so ordinary noise in one artifact, such as an antivirus scan updating access times, does not by itself produce an alert.
2. **Treating absence as evidence.** Palmbach and Breitinger found that removing an artifact is often easier than altering it convincingly [1]. ADS therefore records missing, cleared, or truncated artifacts as observations in their own right rather than silently skipping the rules that depend on them.
3. **Explainability.** Every score decomposes into the specific rules that fired and the raw values behind them. An examiner must be able to state in a report, and defend under cross-examination, exactly why a file was flagged.
4. **Reuse of validated parsers.** Artifact parsing is a solved problem with widely used, community-tested tools. ADS builds on those tools and contributes only the correlation and scoring layer, which is where existing tooling stops.

Scope remains narrow, as stated in the topic submission: one Windows release (Windows 11 24H2 by default, so the test platform matches a currently supported system), NTFS system volumes only, a stated list of tampering scenarios, and test systems I build myself.

## B. Assumptions and Scope of Detection

ADS assumes the examiner holds a full image of the system volume and that the tampering, if any, was performed from within the running operating system. Under that assumption every change to file metadata passes through NTFS and is therefore visible, at least for a time, to more than one recording mechanism. ADS does not attempt to detect modifications made offline to a raw disk, which bypass the journaling mechanisms entirely; this is noted as a limitation in Section V.

Following [1], ADS also assumes the timestamps in the $MFT have been set to values that satisfy the classical NTFS timestamp rules [3], so checks performed on a single MFT record are not expected to succeed alone. The specific tampering scenarios used for testing are drawn from the timestamp manipulation tools already documented in [1] and from public descriptions in MITRE ATT&CK (T1070, Indicator Removal) [4]. They are listed in the evaluation plan rather than here, because this section concerns how detection works rather than how tampering is performed.

## C. Artifacts and Join Keys

ADS ingests six sources, summarized in Table I. They were chosen because each is written by a different subsystem, which is what makes their agreement meaningful.

**Table I. Artifacts used by ADS**

| Source | Writer | Key facts used | Join key |
|---|---|---|---|
| $MFT (SIA and FNA) | NTFS driver | Eight MACE timestamps, record number, sequence number | MFT reference |
| $UsnJrnl:$J | NTFS change journal | Reason flags (FILE_CREATE, BASIC_INFO_CHANGE, RENAME), record time, USN | MFT reference |
| $LogFile | NTFS transaction log | Before and after images of metadata updates | MFT reference |
| LNK files | Windows shell | Link's own SIA times; embedded target MAC times; target path | Full path |
| Prefetch | Cache manager | Executable name, up to eight run times, files referenced at load | Full path, time |
| Event logs (System, Security, Application) | Event Log service | Session boundaries, log clearing, journal deletion, system time changes | Time |

The MFT reference (record number plus sequence number) is the strongest join key because it is stored directly in each USN record and $LogFile entry, so those joins are exact. LNK and Prefetch files reference their targets by path, so those joins are made on a normalized full path, with the MFT sequence number used to reject matches against a reused record. Event log entries carry no file reference and are joined by time interval.

## D. Consistency Rules

ADS starts from the five rules proposed in [1] and adds rules drawn from related work and from properties of the artifacts that [1] did not use. Each rule returns one of three outcomes for a file: *consistent*, *violated*, or *not evaluable* when the required artifact is absent. Table II lists the rule set.

**Table II. Consistency rules**

| ID | Rule | Origin |
|---|---|---|
| R1 | SIA-E is within tolerance of the most recent BASIC_INFO_CHANGE record for the file in $J | [1] |
| R2 | A LNK file's SIA-E matches the SIA-E of its target | [1] |
| R3 | A LNK file's SIA-C is equal to or later than its target's SIA-C | [1] |
| R4 | A LNK file's SIA-A is equal to or earlier than its target's SIA-A | [1] |
| R5 | A file's SIA-C and SIA-M fall within a recorded user session | [1] |
| R6 | SIA-C is not earlier than FNA-C | [5], via [1] |
| R7 | SIA timestamps do not have an all-zero sub-second field | [6], via [1] |
| R8 | The FILE_CREATE record for the file in $J agrees with SIA-C | New |
| R9 | The target creation time embedded in a LNK header agrees with the target's current SIA-C | New |
| R10 | The file's metadata change does not coincide with execution of a binary recorded in Prefetch that is not normally associated with the file | Extends [1], Table 6 |
| R11 | MFT record allocation order is plausible given SIA-C, relative to neighboring records | [7], [8] |

R1 through R5 are taken directly from [1]. R6 and R7 are older checks summarized in [1]; they are included because they are cheap to compute and because they help show how weak single-artifact checks are on their own. R8 and R9 are the main new rules. A USN FILE_CREATE record is written when a file is created and is not changed by later edits to the file's SIA, so a creation record dated well after a file's claimed creation time is strong evidence of backdating while the record survives. Similarly, every LNK file stores a copy of its target's creation, access, and write times in the shell link header when the link is updated. Creation time should not change under normal use, so disagreement between the embedded copy and the current SIA-C is suspicious even when the LNK file's own timestamps look normal. R10 generalizes the correlation shown in Table 6 of [1], where metadata changes on test files lined up with Prefetch updates for the program that made them. R11 applies the digital stratigraphy idea of Casey [8] and the antedating work of Willassen [7]; it is expected to be the noisiest rule and is included mainly to test whether a weak signal adds anything once combined.

Rules that compare times use a tolerance τ, because related records are not written at exactly the same instant. The initial value is two seconds for journal comparisons and sixty seconds for session comparisons; both will be calibrated on benign data as described in Section F.

## E. System-Level Indicators

File-level rules cannot fire when the artifact they depend on is gone. To keep absence visible, ADS computes a separate set of system-level indicators:

* **S1. Log clearing.** System log event 104 or Security log event 1102, each of which records when and by whom a log was cleared [1].
* **S2. Change journal reset.** Application log event 3079, recorded when the USN journal is deleted [1], or a journal whose earliest record is much later than the operating system installation date.
* **S3. Event log discontinuity.** Gaps in event record numbers, or a log whose oldest entry is unusually recent given its configured maximum size.
* **S4. Clock changes.** Security event 4616 or System log Kernel-General events recording a change to the system time, which would undermine every time-based rule.
* **S5. Missing expected artifacts.** Files that were demonstrably opened (from jump lists or USN records) with no corresponding LNK file, or executables with USN evidence of execution-related activity and no Prefetch file.

These indicators do not prove that any particular file was altered. They lower the confidence ADS places in "consistent" outcomes from the affected sources and raise the overall system score, so an examiner sees that the evidence base has been degraded instead of seeing a misleadingly clean result.

## F. Scoring Model

The score must reward agreement among independent rules, discount rules that fire often on benign activity, and account for how trustworthy each underlying source is. ADS combines rule outcomes as a weighted sum over the rules that are evaluable for a file:

  D(f) = Σ_r w_r · v_r(f) / Σ_r w_r

where v_r(f) is 1 if rule r is violated for file f and 0 if it is consistent. Rules that are not evaluable are left out of both sums, and the fraction of rules that were evaluable is reported alongside D(f), so a high score based on one rule is never confused with a high score based on six.

Each weight is the product of two terms. The first is a specificity term, log(1 / p_r), where p_r is the rate at which rule r fires on files in a benign baseline image. A rule that fires on two percent of normal files therefore counts for more than one that fires on twenty percent. This addresses the main weakness of single-artifact checks: many violations are explained by normal behavior, such as archive extraction preserving original modification times, installers setting fixed timestamps, cloud sync clients restoring server-side times, and security software updating access times. The second term is a tamper-resistance factor derived from the scores in [2]: sources that are harder for a user to modify (for example $J and the FNA, which are user-inaccessible and lack a built-in editor) receive more weight than those a user can edit directly (for example LNK and Prefetch files). This is the first use I am aware of that turns the qualitative framework of [2] into a quantitative input to detection.

A file is flagged when D(f) exceeds a threshold θ. The threshold is chosen on a calibration image, separate from the test images, to meet a target false positive rate. A simple weighted sum was chosen over a learned classifier for two reasons. First, the number of known-tampered files in a lab experiment is small, and a trained model would overfit. Second, a weighted sum keeps every flag explainable as "these rules, with these weights." A logistic regression over the same rule outputs will be tested as a comparison if time permits.

Finally, ADS applies a temporal clustering step. Real tampering tends to touch several files within a short window, often around the execution of a single program. Flagged files whose violating records fall within the same short interval are grouped, and each group is reported with any Prefetch executions and system-level indicators inside that interval. This turns a list of suspicious files into a candidate event that an examiner can investigate.

## G. Implementation

ADS is written in Python 3 and organized as a four-stage pipeline (Fig. 1).

*Fig. 1 (to be drawn): Image → Extraction → Normalization → Rule evaluation → Scoring and report.*

1. **Extraction.** The image is mounted read-only and its hash recorded. The $MFT, $J, $LogFile, the Prefetch directory, user Recent folders, and event logs are exported, each with its own hash, so the chain of custody extends to every intermediate file.
2. **Parsing and normalization.** Parsing uses existing, widely validated tools rather than new parsers: Eric Zimmerman's MFTECmd for the $MFT and $J, PECmd for Prefetch, LECmd for LNK files, and EvtxECmd for event logs [9]. Their CSV output is loaded into a single SQLite database with all times converted to UTC FILETIME values, so no precision is lost in comparisons. Pure-Python libraries (python-evtx, LnkParse3, and libscca bindings) serve as a cross-check on a sample of records, which also partially validates the parsers as the course's tool-validation topic recommends.
3. **Rule evaluation.** Each rule is a self-contained function that queries the database and writes one outcome row per file, with the raw values that produced it. New rules can be added without changing the scoring code.
4. **Scoring and reporting.** The scorer applies the weights from Section F and produces a ranked CSV and a human-readable report. For each flagged file the report lists every rule outcome, the timestamps compared, the source of each timestamp, and any system-level indicators in effect.

The same pipeline also reproduces each single-rule baseline, so ADS can be compared against "R1 only," "R2 only," and so on with identical parsing and identical ground truth, which is the comparison the evaluation depends on.

## H. Relationship to Existing Tools

Commercial suites such as EnCase and FTK present these artifacts but leave correlation to the examiner. Some tools automate individual checks; for example, Magnet AXIOM reports SIA and FNA mismatches [10], which corresponds to R6 alone. Super-timeline tools such as Plaso merge artifacts by time but do not test their consistency. ADS differs in combining many checks, weighting them by benign false positive rate and source resistance, and reporting when the evidence base itself has been degraded. Recent academic work on timestamp manipulation detection, such as Oh, Lee, and Hwang [11] and Galhuber and Luh [12], focuses primarily on NTFS internals; the literature review will confirm how ADS compares with these in detail.

## I. Expected Contribution

If combining artifacts helps as [1] suggests, ADS should show a higher detection rate than any single rule at the same false positive rate, and it should keep detecting tampering after one or two sources have been removed. If it does not, that negative result is also useful, because it would show that the recommendation in [1] does not hold once normal system activity is included. The evaluation plan specifies how both outcomes will be measured.

# References

[1] D. Palmbach and F. Breitinger, "Artifacts for detecting timestamp manipulation in NTFS on Windows and their reliability," *Forensic Sci. Int.: Digit. Investig.*, vol. 32, 300920, 2020.

[2] C. Vanini, C. Hargreaves, and F. Breitinger, "Evaluating tamper resistance of digital forensic artifacts during event reconstruction," arXiv:2412.12814, 2024.

[3] K.-P. Chow, F. Y. Law, M. Y. Kwan, and P. K. Lai, "The rules of time on NTFS file system," in *Proc. 2nd Int. Workshop Systematic Approaches to Digital Forensic Engineering (SADFE)*, 2007, pp. 71-85.

[4] MITRE, "Indicator Removal, Technique T1070," MITRE ATT&CK. [Online]. Available: https://attack.mitre.org/techniques/T1070/

[5] X. Ding and H. Zou, "Reliable time based forensics in NTFS," School of Software, Shanghai Jiao Tong University, 2010.

[6] A. Gungor, "Date forgery analysis and timestamp resolution," Meridian Discovery, 2014.

[7] S. Y. Willassen, "Finding evidence of antedating in digital investigations," in *Proc. 3rd Int. Conf. Availability, Reliability and Security (ARES)*, 2008, pp. 26-32.

[8] E. Casey, "Digital stratigraphy: Contextual analysis of file system traces in forensic science," *J. Forensic Sci.*, vol. 63, no. 5, pp. 1383-1391, 2018.

[9] E. Zimmerman, "Eric Zimmerman's tools." [Online]. Available: https://ericzimmerman.github.io/

[10] R. Andrade, "Expose evidence of timestomping with the NTFS timestamp mismatch artifact," Magnet Forensics, 2020.

[11] J. Oh, S. Lee, and H. Hwang, "Forensic detection of timestamp manipulation for digital forensic investigation," *IEEE Access*, 2024.

[12] M. Galhuber and R. Luh, "Time for truth: Forensic analysis of NTFS timestamps," in *Proc. 16th Int. Conf. Availability, Reliability and Security (ARES)*, 2021, pp. 1-10.
