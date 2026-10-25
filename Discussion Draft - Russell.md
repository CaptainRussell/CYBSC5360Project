---
title: "Cross-Checking Windows Artifacts to Detect Anti-Forensic Tampering"
subtitle: "CPRE 5360 Term Paper: Discussion, Part A (Draft)"
author: "Captain Scott Russell"
---

# V. Discussion

## A. The Same Idea Beyond NTFS: A Demonstration

The rules in Section III need Windows records (the MFT, the change journal, link files, Prefetch and event logs). Many drives an examiner receives have none of these. A USB stick or an external drive is often formatted FAT, which keeps only a name, a size, and a few dates for each file. To see whether the core idea, *look for places where independent records disagree, and weigh the disagreements together*, carries over to such a drive, I added a second set of eight checks to ADS that use what a FAT drive does record:

| Check | What disagrees |
|---|---|
| C1 | The file's name says one type; its first bytes say another |
| C2 | The file keeps going after its format says it has ended |
| C3 | The file is locked with a password |
| C4 | A password is written out in plain words inside a file |
| C5 | The file is unlike everything else in its folder |
| C6 | The folder's own documentation names its neighbors but not this file |
| C7 | An archive holds locked or personal files |
| F1 | The file was last written at a different time from the bulk copy around it |

These checks are scored with the same formula as R1 to R11 (Section III-F). With no clean reference drive, each check's benign rate p_r was taken from the drive itself.

I ran this version on the FAT16 image from the course's Project 1 and compared it with my own EnCase examination of the same image. All eight files I had found by hand ranked in the tool's top eight of 76 files with any finding. The most useful case was a photo with a second, hidden archive attached after its end: by hand I found it only after a hint and a byte-by-byte search, while check C2 named the hidden file directly. Check F1 also showed the timestamp idea at work: 2,224 of 2,236 files share one write time from a bulk copy, and four of the twelve files written at a different time were planted evidence. The tool's own reader for FAT drives matched The Sleuth Kit byte for byte on all 4,923 files on the image.

**This is a demonstration, not a test.** I wrote checks C1 to C7 after I knew the answers for this image, and the report's "look first" cut-offs were set on it. A fair test would use a drive image no one tuned on, such as another course project image. The result is reported only to show that the method generalizes, not as evidence of how well it detects hidden content.
