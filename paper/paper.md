---
title: Cross-Checking Windows Artifacts to Detect Anti-Forensic Tampering
author: Captain Scott Russell
affiliation: Department of Computer Engineering (Cybersecurity) | Iowa State University, Ames, Iowa
email: russesco@iastate.edu
note: Draft of the proposed solution and evaluation plan, November 1, 2026
---

::: abstract
People hiding evidence on a computer can change a file's dates, rename a photo so it looks like a program, or tuck one file inside another, each in a few seconds. But Windows and its file system write the same facts down in several separate places, and a cover-up rarely changes all of them. I built the Artifact Disagreement Scorer, a tool that compares these records with each other and points the examiner to the files where they disagree, with a plain-English reason for each one. It runs as a command-line program or as a single web page that works offline. I am testing it on the two disk images from this course's lab projects, using my own findings from EnCase and the Forensic Toolkit (FTK) as the answer key. On Project 1 it ranked six of the seven evidence files in its top ten out of 2,246 files. On Project 2, where the checks were locked before I examined the image, it found seven of the sixteen evidence files among 4,818, five of them in its top ten.
:::

::: keywords
Digital forensics, anti-forensics, timestamp tampering, NTFS, triage, tool validation
:::

# The Problem

Hiding evidence is cheap. Any program can rewrite the dates Windows shows for a file, a trick called *timestomping* [4]. A photo can be renamed *gzip* so it sits among system programs, and a file can be hidden inside a ZIP or after the end of another file.

Hiding it *well* is much harder. Windows records the same facts in more than one place, written by different parts of the system for different reasons. Windows' file system (NTFS) keeps a second, harder-to-reach copy of every file's dates. Windows writes a shortcut file when a document is opened, a Prefetch file when a program runs, and event logs for logons and clock changes. A file's name says what it should be, and its first bytes say what it really is. Someone covering their tracks may fix one of these, but rarely all of them, so a cover-up leaves records that *disagree*.

Today's tools leave that comparison to the examiner. EnCase and the Forensic Toolkit display every record, but the examiner has to notice that two of them conflict. Specialized tools automate a single check, and a single check is noisy: normal use also produces odd dates, so one filter can return hundreds of files.

The question for this paper is the one from my topic proposal: *does combining many disagreement checks point an examiner to hidden evidence better than any single check?* To answer it I built the Artifact Disagreement Scorer. Fig. 1 shows the front page of its report on the Project 2 image: of 5,607 entries on the drive, 164 files have at least one clue and 7 are marked "look first".

![The Artifact Disagreement Scorer's report on the Project 2 image narrows the whole drive to a short list.](figures/shot_funnel.png){width=column}

Section II covers what already exists, Section III shows how the tool works, and Section IV explains how I am testing it.

# What Already Exists

**Two copies of every date.** Windows' file system keeps a table with one entry per file (the Master File Table). Each entry holds four dates, for when the file was created, last changed, last opened, and when its entry last changed. It holds them *twice*. The **visible dates** (formally, Standard Information) are what Windows Explorer shows, and any program can change them. The **protected dates** (formally, File Name) are kept by the file system itself and cannot be set the normal way. When the visible dates say a file is older than the protected dates do, something is off.

**Single checks.** Chow and colleagues listed the rules that these dates follow in normal use [3]. Willassen [7] showed that the order in which files were laid down on disk, like layers of rock, can expose a file that claims to be older than its neighbors. Magnet AXIOM, a commercial tool, flags files whose visible and protected dates disagree [10], which is just one of my tool's checks on its own. EnCase and the Forensic Toolkit compare a file's name with its first bytes, another single check. Timeline tools put records in time order but do not test whether they agree.

**Combining records.** The closest work is Palmbach and Breitinger [1]. They showed that the change journal, shortcut files, Prefetch and event logs all keep traces of timestamp changes, concluded that none is reliable alone, and proposed five rules that use them together. Vanini, Hargreaves and Breitinger [2] proposed a way to rate how hard each *type* of record is to fake.

**What is missing.** Each of these stops short in a way that matters to an examiner:

- Palmbach and Breitinger [1] recommend combining sources but never measure whether combining helps. Their test used four files on an unused computer, so it cannot say how often ordinary activity sets off their rules.
- Vanini and colleagues [2] rate record types in general, not whether a particular drive shows tampering.
- The single checks are each easy to dodge or to trip by accident, and the commercial tools leave it to the examiner to connect them.

No one has measured, on the kind of images an examiner actually receives, whether combining these checks finds planted evidence faster than the best single check. That is the gap my tool is built to test.

# How the Tool Works

## The Idea in One Picture

The Artifact Disagreement Scorer opens an exact copy of a drive without changing it, lines up each file's records, asks two sets of questions, and ranks the files by how many independent questions disagree about them (Fig. 2). Four goals shape it:

1. **Combine; never trust one check.** A file rises only when several independent checks disagree about it, so normal noise in one record does not put it at the top.
2. **A missing record is a clue.** Deleting a record is often easier than faking one [1], so the tool reports records that were cleared or are missing instead of quietly skipping the checks that need them.
3. **Explain every flag.** Each flag comes with a plain sentence and the values behind it, so an examiner can state and defend why a file was picked.
4. **Usable by non-specialists.** Findings go to investigators, lawyers and commanders. The tool runs from the command line or as one web page that works offline, and its report is written in plain English.

![How the tool works. Every input is fingerprinted, so each result traces back to the original drive copy.](figures/fig1_pipeline.png){width=2.9in}

**Scope.** Copies of USB sticks (the FAT file system) and Windows drives (the NTFS file system). The date rules target changes made from inside a running Windows system; editing a raw disk offline bypasses Windows' own logs and is out of scope.

## Eight First-Look Questions, for Any Drive

Many drives an examiner receives are not Windows system drives: a USB stick, or a data drive full of another system's files. So the tool first asks eight questions of every file, each comparing what a file claims to be with what it holds. Fig. 3 shows them as the report lists them, with how many files each one flagged on Project 2. For example, *disguised file* (C1) compares a file's name with its first bytes; *stands out from its neighbors* (C5) finds the only photo in a folder of programs; *never mentioned* (C6) finds a file that the folder's own guides and web pages never name, though they name its neighbors; and *changed at an unusual time* (F1) finds a file written apart from the bulk copy around it.

![The eight first-look questions as the report shows them, with how many Project 2 files each flagged.](figures/shot_questions.png){width=column}

## Eleven Date Rules for Windows Drives

Windows keeps five records that the date rules compare (Table I). Each is written by a different part of Windows, which is what makes their agreement meaningful.

Table: The records the date rules compare

| Record | Written by | What the tool uses |
|---|---|---|
| Master File Table | File system | Visible and protected dates (8 per file) |
| Change journal | File system | When files were created and their dates changed |
| Shortcut files | Windows Explorer | Their own dates, and a copy of the target's dates |
| Prefetch files | Windows | Which programs ran, and their last 8 run times |
| Event logs | Windows | Logons, log clearing, clock changes |

Table II lists the rules in the same plain words the report uses. Each rule answers *consistent*, *violated*, or *cannot check* when a record it needs is missing.

Table: The date rules

| Rule | Flags a file when... | From |
|---|---|---|
| R1 | Its record-change date is before the journal's own entry | [1] |
| R2 | A shortcut disagrees on its last-change date | [1] |
| R3 | A shortcut is older than the file it points to | [1] |
| R4 | A shortcut was opened after the file's last-opened date | [1] |
| R5 | It changed while nobody was logged on | [1] |
| R6 | Its visible date is older than the protected copy | [10] |
| R7 | Its date was set to a round number of seconds | Known |
| R8 | It was created later than its visible date says | New |
| R9 | A shortcut remembers a different creation date | New |
| R10 | Its date changed as an unusual program ran | [1] ext. |
| R11 | It claims to be much older than its neighbors on disk | [7] |

R8 and R9 are the main new rules. The change journal's "file created" entry is not touched when someone later rewrites the visible dates, so a journal entry dated well after the claimed creation date is strong evidence of back-dating. Every shortcut also keeps a copy of its target's dates, so a creation date that has since moved is suspicious even when the shortcut's own dates look normal. Five warnings (S1 to S5) keep missing records visible: a cleared event log, a deleted or late-starting change journal, gaps in the event log numbering, a changed system clock, and programs that ran without leaving a Prefetch file. Any "consistent" answer that rests on a damaged record is marked low-confidence.

## Scoring: Agreement Beats Noise

Both sets of checks are scored the same way. A file's score is the weighted share of the checks that fired, out of the checks that could be run on it:

$$ D(f) = \frac{\sum_r w_r \, v_r(f)}{\sum_r w_r} $$

Here v_r(f) is 1 if check r fires for file f and 0 if not. A check that fires on almost every file says little, so each weight is w_r = ln(1/p_r), where p_r is how often check r fires on that drive: a check that fires on 2% of files counts for more than one that fires on 20%. For the date rules, records that a user cannot easily reach (the change journal, the protected dates) also count up to three times more than records a user can edit or delete (shortcuts, Prefetch), using the tamper-resistance ratings of Vanini and colleagues [2]. To my knowledge this is the first use of those ratings as a number inside a detector. A simple weighted sum was chosen over machine learning because there is no labelled training data and because a sum keeps every flag explainable. Fig. 4 shows the result on Project 2: the files ranked by score.

![The top five leads on the Project 2 image, ranked by score.](figures/shot_leads.png){width=column}

## Every Flag Explained

Opening a lead shows why it was picked (Fig. 5). For *attr.html*, three independent questions agree: its name says web page but its first bytes (FF D8 FF) say photo; it is the only photo in its folder; and the drive's guides and web pages name three of its four neighbors but never this file. Each line is a sentence an examiner can repeat in a report, with the evidence printed under it.

![One lead opened: each check that fired is explained in a plain sentence, with the evidence under it.](figures/shot_lead_open.png){width=2.6in}

## Implementation

The tool is written in Python 3 using only its standard library, so it runs on any computer with Python installed. It reads the drive copies itself and never writes to them. Both of its drive readers were checked against The Sleuth Kit, a standard open-source forensic toolkit: the USB-stick reader matched it byte for byte on all 4,923 files of the Project 1 image, and the Windows-drive reader matched it on a test image built with fragmented, linked, hidden and deleted files, and on 3,605 files of a larger image. Every input is fingerprinted with SHA-256. The same code produces the "one check only" results that the evaluation compares against. A browser edition puts the whole tool in a single offline web page, and it gives exactly the same results as the command line on both course images. The code passes 59 automated tests.

# Evaluation Plan

The evaluation is a proof of function: does ADS point an examiner to what a careful manual examination found, and with how much effort, on images I did not build?

## Research Questions

- **RQ1. Does it point to the evidence?** What share of the evidence files found by hand does ADS list, and how far down?
- **RQ2. Better together?** Does the combined ranking reach more evidence for the same number of files reviewed than any single check alone?
- **RQ3. Does it hold on unseen data?** Do the results hold on an image the checks were not tuned on?
- **RQ4. Is it understandable?** Can the report alone explain each flag to a non-specialist, and how long does a run take?

## The Two Course Images

Table IV summarizes the two images. Both were examined by hand before ADS was run on them, so each has an answer key.

Table: The two course images

| | Project 1 | Project 2 |
|---|---|---|
| Drive | FAT16 external drive | NTFS volume of copied Linux files |
| By hand | EnCase | FTK |
| Answer key | 7 evidence, 2 decoys | 16 evidence, 3 decoys |
| Role | Development | Held-out test |

**Answer keys.** Each key lists the files that answered a case question (the evidence) and the files planted to mislead that I had to rule out (decoys), with how each was found by hand. A file matches if its path ends with the key's path. Files ADS lists that are not in a key are not necessarily false alarms: the key is one examiner's findings.

**Freezing the checks.** I wrote the eight first-look questions after examining Project 1, so its result is a demonstration, not a test. They were committed on October 20, before Project 2 was examined, and an automated test fails if they change. Project 2 is therefore a held-out test. Support for reading NTFS was added later, but it only reads the drive and changes no check. Any later change to a check will be reported separately as post hoc.

**Date checks on real data.** Project 2's image is NTFS, so the date rules that need only the MFT (R6, R7, R11) run on it directly. It holds a Linux file system with no shortcuts, Prefetch, or Windows event logs, so the other rules cannot be checked there; they are verified on synthetic test cases. There is no answer key for timestamp tampering on this image, so this part reports what the date rules flag and whether those files appear in the answer key.

## Measures

For each project: evidence files listed; the rank of each; how many are in the top ten; the *review depth*, the number of files an examiner must read to reach every evidence file ADS found, and how many of those are not in the key; and decoys listed (RQ1, RQ3). For RQ2, each check alone flags a set of files in no order; ADS gets the same budget, its top files, and the evidence each finds is compared. For RQ4, I check that every flag in the top twenty is explained by the report alone, and record run time.

**Early result (Project 1, development case).** ADS listed 76 of 2,246 files. All 7 evidence files were among them, 6 in the top ten, and all within the top 16, with 7 files outside the key above the last one. Both decoys were listed. No single check caught more than 4 of the 7. The broad checks lost clearly to the combination (F1 alone caught 4 in the 12 files it flags, ADS's top 12 held 6), but the two most precise checks, which flag one file each, beat it at that budget because ADS's top file was a decoy.

**Held-out result (Project 2).** With the checks frozen, ADS listed 164 of 4,818 files. 7 of the 16 evidence files were among them, 5 in the top ten, and all within the top 15, with 7 files outside the key above the last one. One of the 3 decoys was listed. ADS found less than half of the evidence, and as on Project 1 the narrow checks beat it at budgets of one to three files, so the first two success criteria below were not met. Every top-twenty flag carries a plain-language explanation, and each of the nine misses is explained by what ADS does not read, such as document metadata, page content, or a password written as "pswd =". The date rules R6 and R7 fired on almost every file: nearly every visible date had been set to 2 Oct 2011 11:57:01, while the FN dates show the files were written in two batches six years apart. Because those rules fire everywhere, their weight fell to nearly zero and no single file was flagged.

## Success Criteria

On Project 2: (1) ADS lists at least half of the evidence files; (2) for every single check, ADS's top files hold at least as many evidence files as that check flags with the same budget; (3) every top-twenty flag is explained by the report alone; and (4) every missed evidence file is explained by what ADS does and does not examine. A result that falls short is reported as found.

## Threats to Validity

Two images are a small sample. Each answer key is one examiner's findings and may be incomplete. Both images are teaching cases with planted evidence, not real adversaries. I wrote the checks, which is why Project 1 counts only as development and Project 2 was held out. The Windows-only date rules are exercised on real data only through the MFT; the rules that need shortcuts, Prefetch, and event logs are tested on synthetic cases only.

## Status and Schedule

The tool, both readers, the answer keys, and the runs on both projects (October 26) are done; the Project 1 result reproduced exactly on a second computer. Project 2's full results, including the date checks, are reported in Section V of the final paper (by Dec 6).

# References

::: references
[1] D. Palmbach and F. Breitinger, "Artifacts for detecting timestamp manipulation in NTFS on Windows and their reliability," *Forensic Sci. Int.: Digit. Investig.*, vol. 32, 300920, 2020.

[2] C. Vanini, C. Hargreaves, and F. Breitinger, "Evaluating tamper resistance of digital forensic artifacts during event reconstruction," arXiv:2412.12814, 2024.

[3] K.-P. Chow, F. Y. Law, M. Y. Kwan, and P. K. Lai, "The rules of time on NTFS file system," in *Proc. 2nd Int. Workshop Systematic Approaches to Digital Forensic Engineering (SADFE)*, 2007, pp. 71–85.

[4] MITRE, "Indicator Removal, Technique T1070," MITRE ATT&CK. [Online]. Available: https://attack.mitre.org/techniques/T1070/

[5] X. Ding and H. Zou, "Reliable time based forensics in NTFS," School of Software, Shanghai Jiao Tong University, 2010.

[6] A. Gungor, "Date forgery analysis and timestamp resolution," Meridian Discovery, 2014.

[7] S. Y. Willassen, "Finding evidence of antedating in digital investigations," in *Proc. 3rd Int. Conf. Availability, Reliability and Security (ARES)*, 2008, pp. 26–32.

[8] E. Casey, "Digital stratigraphy: Contextual analysis of file system traces in forensic science," *J. Forensic Sci.*, vol. 63, no. 5, pp. 1383–1391, 2018.

[9] E. Zimmerman, "Eric Zimmerman's tools." [Online]. Available: https://ericzimmerman.github.io/

[10] R. Andrade, "Expose evidence of timestomping with the NTFS timestamp mismatch artifact," Magnet Forensics, 2020.

[11] J. Oh, S. Lee, and H. Hwang, "Forensic detection of timestamp manipulation for digital forensic investigation," *IEEE Access*, 2024.

[12] M. Galhuber and R. Luh, "Time for truth: Forensic analysis of NTFS timestamps," in *Proc. 16th Int. Conf. Availability, Reliability and Security (ARES)*, 2021, pp. 1–10.
:::
