# ADS report

Generated 2026-10-26T00:06:51Z. Threshold θ = 0.5, weight mode `full`.

## Inputs

| Kind | File | Rows | SHA-256 |
|---|---|---|---|
| mft | 26Fall_Project2.img | 5379 | `3e00b19df1980a3cb5f9b876cd2c33e2982dd7fc82eff6c6097b13649f194c56` |

Files scored: 4797. Flagged: 0. LNK files not joined to a target: 0.

## System-level indicators

System score: **0.00** over 0 evaluable indicators.

| ID | Indicator | Status | Details |
|---|---|---|---|
| S1 | Log clearing | not_evaluable | `{"reason": "no System or Security log"}` |
| S2 | Change journal reset | not_evaluable | `{"reason": "no Application log and no $J"}` |
| S3 | Event log discontinuity | not_evaluable | `{"reason": "no event logs"}` |
| S4 | Clock change | not_evaluable | `{"reason": "no System or Security log"}` |
| S5 | Missing expected artifacts | not_evaluable | `{"reason": "no $J data"}` |

## Rule weights

| Rule | p_r | log(1/p_r) | t_r (source) | w_r |
|---|---|---|---|---|
| R1 | 0.5000 | 0.693 | 2.43 (usn) | 1.683 |
| R2 | 0.5000 | 0.693 | 1.86 (lnk) | 1.287 |
| R3 | 0.5000 | 0.693 | 1.86 (lnk) | 1.287 |
| R4 | 0.5000 | 0.693 | 1.86 (lnk) | 1.287 |
| R5 | 0.5000 | 0.693 | 1.86 (evtx) | 1.287 |
| R6 | 0.9974 | 0.003 | 2.43 (fna) | 0.006 |
| R7 | 0.9976 | 0.002 | 1.86 (sia) | 0.004 |
| R8 | 0.5000 | 0.693 | 2.43 (usn) | 1.683 |
| R9 | 0.5000 | 0.693 | 1.86 (lnk) | 1.287 |
| R10 | 0.5000 | 0.693 | 1.86 (prefetch) | 1.287 |
| R11 | 0.0001 | 9.169 | 2.43 (mft_order) | 22.268 |

## Candidate events (temporal clusters)

None.

## Flagged files

None.

## Rule definitions

- **R1**: SIA-E is within tolerance of the most recent BASIC_INFO_CHANGE in $J.
- **R2**: A LNK file's SIA-E matches the SIA-E of its target (most recent LNK).
- **R3**: Every LNK file's SIA-C is equal to or later than its target's SIA-C.
- **R4**: The most recent LNK file's SIA-A is equal to or earlier than its target's SIA-A.
- **R5**: SIA-C and SIA-M fall within a recorded user session (System 7001/7002).
- **R6**: SIA-C is not earlier than FNA-C.
- **R7**: SIA timestamps do not have an all-zero sub-second field.
- **R8**: The FILE_CREATE record for the file in $J agrees with SIA-C.
- **R9**: The target creation time embedded in each LNK agrees with the target's current SIA-C.
- **R10**: Metadata changes do not coincide with Prefetch execution of an unassociated binary.
- **R11**: MFT allocation order is plausible: SIA-C is not far older than neighboring records.
