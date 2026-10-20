"""Default configuration. Any key can be overridden with a JSON file (--config)."""

import copy
import json

DEFAULTS = {
    # Section III-D tolerances (seconds). Calibrate on benign data (Section III-F).
    "tau_journal_s": 2.0,        # R1, R8: SIA vs $J record time
    "tau_lnk_s": 2.0,            # R2, R3, R4, R9: LNK vs target
    "tau_session_s": 60.0,       # R5: timestamp vs user session boundary
    "tau_mft_s": 0.0,            # R6: SIA-C vs FNA-C
    "tau_prefetch_s": 30.0,      # R10: Prefetch run time vs BasicInfoChange

    # R1: Palmbach & Breitinger's rule 1 says SIA-E "should be similar to" the
    # latest BASIC_INFO_CHANGE. Later data writes legitimately move SIA-E
    # forward without a new BASIC_INFO_CHANGE, so by default only an SIA-E that
    # is EARLIER than the record counts as a violation.
    "r1_two_sided": False,

    # R5: System log events that open and close user sessions.
    "session_start_ids": [7001],
    "session_end_ids": [7002],
    "boot_shutdown_ids": [6005, 6006, 6008, 41],

    # R7: which SIA timestamps are checked for an all-zero sub-second field.
    "r7_fields": ["si_c", "si_m"],

    # R8: NTFS tunneling (a file deleted or renamed away and recreated under the
    # same name within this window inherits the old creation time). Office
    # "safe save" does this on every save, so it is treated as an explanation.
    "tunneling_window_s": 15.0,

    # R10: executables whose metadata changes are normal, and how many runs
    # with the file in FilesLoaded make an executable "normally associated".
    "r10_allowlist": [
        "explorer.exe", "searchprotocolhost.exe", "searchindexer.exe",
        "searchfilterhost.exe", "msmpeng.exe", "mpcmdrun.exe", "svchost.exe",
        "tiworker.exe", "trustedinstaller.exe", "onedrive.exe", "msiexec.exe",
        "dllhost.exe", "runtimebroker.exe", "backgroundtaskhost.exe",
        "taskhostw.exe", "compattelrunner.exe", "wuauclt.exe",
    ],
    "r10_min_assoc_runs": 3,

    # R11: MFT allocation order (digital stratigraphy).
    "r11_neighbors": 10,          # records on each side
    "r11_min_neighbors": 5,
    "r11_delta_days": 30.0,       # how much older than its neighborhood a file may claim to be

    # Candidate files: skip NTFS metafiles (entries 0-23).
    "min_entry": 24,

    # Path joins: examiner mount prefix to strip from LNK source paths,
    # e.g. "E:\\C" when the image was mounted at E:\C.
    "mount_prefix": None,

    # System-level indicators (Section III-E).
    "install_time": None,          # 'yyyy-MM-dd HH:mm:ss'; default is $MFT record 0 creation time
    "s2_journal_gap_days": 1.0,
    "s2_unwrapped_usn_max": 33554432,   # $J that never wrapped starts below this USN
    "s3_max_gaps_reported": 10,
    # Optional per-channel .evtx sizes for the "oldest entry too recent" test:
    # {"Security": {"size_bytes": 1052672, "max_bytes": 20971520}}
    "evtx_files": {},
    "s3_oldest_gap_days": 1.0,
    "s4_min_shift_s": 60.0,
    "indicator_weights": {"S1": 1.0, "S2": 1.0, "S3": 1.0, "S4": 1.0, "S5": 1.0},

    # Scoring (Section III-F).
    "theta": 0.5,                 # flag threshold; set from the calibration set
    "min_evaluable": 1,
    "weight_mode": "full",        # equal | specificity | full  (experiment E4)
    "cluster_window_s": 300.0,
    "cluster_pad_s": 60.0,

    # Tamper-resistance factor inputs from Vanini, Hargreaves & Breitinger [2].
    # Seven factor scores per source, 1 (hard to tamper) to 3 (easy), in the
    # order: user visible, permissions, software to edit, facets of access,
    # encryption, file format, structural. SIA and FNA are Table 1 of [2]; the
    # other sources are provisional estimates using the same categories and
    # must be confirmed for the test system before results are reported.
    "tamper_scores": {
        "sia":      [1, 1, 3, 2, 3, 3, 2],
        "fna":      [1, 1, 1, 1, 3, 2, 2],
        "mft_order": [1, 1, 1, 1, 3, 2, 2],
        "usn":      [1, 1, 1, 1, 3, 2, 2],
        "lnk":      [3, 3, 1, 1, 3, 2, 2],
        "prefetch": [3, 3, 1, 1, 3, 2, 2],
        "evtx":     [3, 3, 1, 1, 3, 2, 2],
    },
    # Each rule is weighted by the resistance of its reference source: the
    # source that supplies the value the SIA is checked against.
    "rule_reference_source": {
        "R1": "usn", "R2": "lnk", "R3": "lnk", "R4": "lnk", "R5": "evtx",
        "R6": "fna", "R7": "sia", "R8": "usn", "R9": "lnk", "R10": "prefetch",
        "R11": "mft_order",
    },
}

# Sources each rule reads (used to mark outcomes from degraded sources).
RULE_SOURCES = {
    "R1": {"mft", "usn"},
    "R2": {"mft", "lnk"},
    "R3": {"mft", "lnk"},
    "R4": {"mft", "lnk"},
    "R5": {"mft", "evtx"},
    "R6": {"mft"},
    "R7": {"mft"},
    "R8": {"mft", "usn"},
    "R9": {"mft", "lnk"},
    "R10": {"usn", "prefetch"},
    "R11": {"mft"},
}

# Rules that compare times taken from the system clock at different moments;
# a clock change (S4) undermines them.
TIME_RULES = {"R1", "R2", "R3", "R4", "R5", "R8", "R9", "R10", "R11"}

# Sources each system-level indicator degrades.
INDICATOR_DEGRADES = {
    "S1": {"evtx"},
    "S2": {"usn"},
    "S3": {"evtx"},
    "S4": {"clock"},
    "S5": {"lnk", "prefetch"},
}

RULE_IDS = ["R%d" % i for i in range(1, 12)]


def _merge(base, override):
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def load_config(path=None):
    cfg = copy.deepcopy(DEFAULTS)
    if path:
        with open(path, encoding="utf-8") as fh:
            _merge(cfg, json.load(fh))
    return cfg
