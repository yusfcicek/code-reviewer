# The documentation corpus

Thirteen cases that grade Level 23's deterministic tier the way
[`evaluation/cases`](../cases) grades the analyzers: annotated inputs, a
committed floor, and a test that fails when the rules change what they report.

**These are authored, not captured.** Each case states a symbol index, a set of
documents and a change, and says which `DOCS` rules must fire and which must
not. Nothing here was taken from a real merge request; a corpus of real reviews
would carry somebody's repository into this one.

**Half the cases expect nothing.** That is the point. This tier's failure mode
is not missing a stale reference — it is reporting a library call, a Kubernetes
noun or another tool's flag as a defect, which is what the first implementation
did twenty-five times in one README. A case that forbids a rule is how a fixed
false positive stays fixed.

The retrieved tier (`DRIFT`) is **not** graded here and cannot be: its answer
comes from a model, and a corpus that pinned a model's answers would measure
the recording rather than the tier. It is bounded by attribution instead —
nothing it produces can block — and by the caps in `drift_service.py`.
