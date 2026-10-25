# Running the experiment

This folder holds the kit for the lab study in Section IV of the paper. The goal
is to measure whether combining the checks (ADS) catches tampering better than
any single check, on a Windows machine in ordinary use, with the correct answer
known in advance.

Everything here runs on a **throwaway Windows 11 virtual machine** you can
snapshot and roll back. The scenario scripts change the machine on purpose.

## The four sets of images (keep them apart)

| Set | What it is | Used for |
|---|---|---|
| **B** baseline | one VM used normally for two or more weeks, no tampering | each check's false-alarm rate; the clean reference |
| **C** calibration | a few clones with some scenarios applied | setting the tolerances and the flag threshold θ |
| **T** test | separate clones with every scenario applied | the detection results reported in the paper |
| **E** external | the course project images (not built by us) | an extra check on unfamiliar data |

Tuning (C) must never see the test data (T).

## Steps

1. **Build the baseline (B).** Install Windows 11 24H2 in a VM. Use it normally
   for two or more weeks: browse, edit documents, install and update software,
   unzip archives, let it run Windows Update and antivirus. Take a snapshot.

2. **Apply scenarios to clones.** Roll back to the baseline snapshot, then for
   each scenario run the kit **inside the VM, as Administrator**:

   ```powershell
   .\apply_scenario.ps1 -Scenario T1 -Snapshot test01 -Key C:\answer_key.csv -Confirm
   ```

   Without `-Confirm` it only says what it would do. The script appends one row
   per planted change to `answer_key.csv`, in the format `evaluate --truth`
   reads. Scenarios T1 to T8 match Table III of the paper.

   Each file-level scenario first "opens" its file the way Explorer does, which
   makes Windows write a shortcut for it, then waits two minutes (`-WaitSeconds`)
   before tampering. Without that step the tampered files would have no shortcut,
   and the four shortcut checks (R2, R3, R4, R9) could never be tested.

   T2 changes the protected FN dates too, which PowerShell cannot do. Give it the
   command for an outside tool with `{file}` where the path goes, for example
   `-SiFnCommand 'C:\tools\SetMace.exe "{file}" ...'`. Check that tool's own
   documentation for the exact syntax; the script does not guess it.

3. **Image and parse.** Snapshot the clone, image the disk (raw or E01, hashed),
   export the artifacts, and run the parsers:

   ```powershell
   .\..\scripts\run_parsers.ps1 -Tools C:\Tools\EZ -Export E:\test01\export -Out E:\test01\csv
   ```

4. **Analyze.** On any computer with Python 3, point the tool at the CSV folder
   (the window from `python3 -m ads gui`, or the command line):

   ```
   python3 -m ads ingest  --db test01.sqlite --mft mft.csv --usn usn.csv --lnk lnk.csv --prefetch prefetch.csv --evtx evtx_*.csv
   python3 -m ads analyze --db test01.sqlite --out results/test01 --calibration calibration.json
   ```

   Open `results/test01/briefing.html` for the plain-language report.

5. **Score against the answer key.**

   ```
   python3 -m ads evaluate --results results/test01 --truth answer_key.csv
   ```

   Open `results/test01/evaluation.html` for the ROC chart and the "did
   combining help?" summary; `evaluation.csv` has every number.

## A note on the clock (scenario T7)

T7 moves the system clock. The answer key records the guest time taken *before*
the change, so reconcile T7 against the host clock when you read the results, as
the paper's ground-truth rule requires.
