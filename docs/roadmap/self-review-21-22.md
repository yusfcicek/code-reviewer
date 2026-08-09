# Self-review of levels 21 and 22

Two levels, both of which claim to *check* something: Level 21 checks what the
model said, Level 22 checks what an edit would do. A level whose subject is
checking has one characteristic failure — the check that reads well and fires on
almost nothing — and this pass went looking for exactly that.

It found three of them, and the worst is in Level 21's headline discipline
check.

| # | Severity | Where | What | Status |
|---|---|---|---|---|
| S-01 | 🔴 High | `domain/narration.py` | `the_prose_claims_no_verdict` catches 3 of 8 natural phrasings. "This blocks the pipeline", "this merge request is blocked", "LGTM, approved" and "do not merge" all pass. | ✅ closed |
| S-02 | 🔴 High | `application/remediation_service.py` | Suggestions are proposed for any line of the file, including lines the merge request never touched. A note cannot be anchored outside the diff, so the platform rejects them and the failure is a warning nobody reads. | ✅ closed |
| S-03 | 🔴 High | `infrastructure/forge/gitlab_forge.py` | Suggestions have no idempotency. Five pipeline runs leave five copies of every suggestion — the defect Level 5 fixed for the review comment (G-12), reintroduced beside it. | open |
| S-04 | 🟠 Medium | `domain/narration.py` | `severity_claims_are_backed` fires on the word "high" anywhere in the prose. "The function has high complexity" fails a review that said nothing wrong. | ✅ closed |
| S-05 | 🟡 Low | `evaluate.py` | `--json` is accepted with `--narration` and silently ignored. | open |
| S-06 | 🟡 Low | `application/remediation_service.py` | With no `path` the subject is taken from `findings[0]`, so a finding about a sibling file decides which file the rest are checked against. | open |

---

## S-01 — the check that agreed with almost everything

`the_prose_claims_no_verdict` is the check that makes
[ADR 0004](../adr/0004-findings-drive-the-gate.md) measurable in the text. It is
the reason Level 21 claims to close C-19's text half.

Measured against eight phrasings a model actually writes:

| Phrasing | Caught |
|---|---|
| `This blocks the pipeline.` | ❌ |
| `This merge request is blocked.` | ❌ |
| `LGTM, approved.` | ❌ |
| `The pipeline will be blocked by this.` | ❌ |
| `Recommendation: do not merge.` | ❌ |
| `Approving this change.` | ✅ |
| `This will block the pipeline.` | ✅ |
| `I reject this merge request.` | ✅ |

Three of eight. The patterns were written against the phrasings that came to
mind while writing them, and the corpus case built to demonstrate the check uses
`I reject this merge request` — one of the three that happens to work. So the
corpus proves the check *can* fire, which is what it was designed to prove, and
proves nothing at all about coverage.

This is the exact failure the level was written to catch in somebody else's
work.

## S-02 — suggestions the platform cannot accept

`SuggestionService.suggest_for` proposes an edit for any finding in the file. A
GitLab note carries a position, and a position has to name a line **in the
diff**; a note about an untouched line is rejected.

The rejection is caught and logged as a warning, which is correct behaviour for
an improvement that fails — and it means the feature can be broken for most
findings while every test passes and every review still publishes. A merge
request that changes one line of a hundred-line file will have most of its
suggestions silently discarded by the API.

It is also the wrong thing to *propose*: an edit to code this merge request did
not touch is a change of subject, not a fix.

## S-03 — five runs, five copies

Level 5 fixed exactly this for the review comment (finding G-12): the comment
carries a marker, the next run finds it and edits rather than adding a second
one.

Suggestions carry nothing. Every pipeline run posts a new discussion for every
suggestion, so a merge request pushed to four times ends with four identical
buttons on the same line, each in its own thread.

## S-04 — a check that fires on ordinary English

`severity_claims_are_backed` searches the whole review for `critical` and `high`
as words. Real reviews say "high complexity", "high coupling", "a high number of
branches" — none of which claims a severity, all of which fail the check when
the analyzers reported nothing HIGH.

The corpus does not catch it because every recorded review in it was written by
somebody who knew what the checks were.

## S-05 — a flag accepted and ignored

`--json` is documented as "where to write the machine-readable summary". With
`--narration` it is parsed, accepted, and nothing is written. Same shape as
R-04 from the last review, one level later.

## S-06 — the subject of a suggestion

`suggest_for(findings, source, path="")` falls back to `findings[0].file_path`.
A caller who passes findings from two files gets the first one's path as the
subject for all of them. The workflow always passes `path`, so this is a latent
constraint rather than a live defect — and one nothing states.
