"""Artifact Disagreement Scorer (ADS).

Correlates Windows artifacts parsed by Eric Zimmerman's tools (MFTECmd, PECmd,
LECmd, EvtxECmd), evaluates consistency rules R1-R11 and system-level
indicators S1-S5, and combines the outcomes into a per-file disagreement
score D(f) as described in Section III of the term paper.
"""

__version__ = "0.2.0"
