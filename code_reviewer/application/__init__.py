"""Application layer: the review workflow and the ports it depends on.

Knows what a review *is* — triage, analyse, gate, report — but not where the
diff comes from or which model produces the prose. Imports from ``domain``
only.
"""
